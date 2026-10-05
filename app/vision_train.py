# -*- coding: utf-8 -*-
"""训练：让 OpenCV「认东西」。需要 OpenCV 4.x（带 cv2.ml）和 numpy。

做法是「特征 + 小分类器」，每类几十张图、在 CPU 上几秒到几十秒就能训练完：

  特征（可以组合）
    color    HSV 直方图和 Lab 的均值、方差          适合靠颜色区分的东西（成熟度、锈斑、污渍）
    texture  LBP 纹理直方图和梯度、频谱统计          适合靠表面纹理区分的东西（织物、金属表面）
    hog      梯度方向直方图                          适合靠轮廓区分的东西
    shape    轮廓的 Hu 矩、圆度、长宽比、尺寸        适合靠形状和大小区分的东西（虫体、划痕与凹坑）
    deep     预训练骨干网络（cv2.dnn 加载 ONNX）的特征  外观复杂的目标（害虫种类、杂草种类）效果好得多

  分类器（cv2.ml）
    svm      一对多的 SVM，用交叉验证的输出做 Platt 校准，得到概率
    rtrees   随机森林，概率 = 各棵树的投票比例
    knn      K 近邻，概率 = 近邻里各类的比例

准确率来自分层 K 折交叉验证的折外预测，不是训练集上的自测。

模型文件用内存里的 FileStorage 读写，再由 Python 存取，这样项目放在带中文的路径下也能用
（OpenCV 自己按路径读写文件时，在 Windows 上遇到非 ASCII 路径会失败）。
"""
import json
import math
import os
import re
import threading
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("LAYA_WB_DATA") or os.path.join(ROOT, "data")
DATASETS = os.path.join(DATA, "datasets")
MODELS = os.path.join(DATA, "models")
BACKBONES = os.path.join(DATA, "backbones")

ALL_FEATURES = ("color", "texture", "hog", "shape", "deep")
ALGOS = ("svm", "rtrees", "knn")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")
HAS_ML = all(hasattr(getattr(cv2, "ml", None), name) for name in ("SVM_create", "RTrees_create", "KNearest_create"))
HAS_HOG = hasattr(cv2, "HOGDescriptor")        # OpenCV 5 的主包里没有 cv2.ml 和 HOG，要用 4.x（或 5.x 的 contrib 包）
FEATURES = tuple(f for f in ALL_FEATURES if f != "hog" or HAS_HOG)


class TrainError(Exception):
    pass


# ----------------------------------------------------------------- 文件

def safe_name(text, fallback=""):
    """数据集、类别、模型的名字：可以用中文，去掉路径和系统保留字符。"""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(text or "")).strip().strip(".")
    text = re.sub(r"\s+", "_", text)[:48]
    if text.upper() in ("CON", "PRN", "AUX", "NUL") or re.match(r"^(COM|LPT)\d$", text.upper() or "-"):
        text = "_" + text
    return text or fallback


def read_image(path):
    """用 Python 读文件再解码，带中文的路径也能读。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def write_image(path, img):
    ext = os.path.splitext(path)[1].lower() or ".png"
    ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in (".jpg", ".jpeg") else [])
    if not ok:
        raise TrainError("cannot encode image")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(buf.tobytes())


def _algo_text(algo):
    fs = cv2.FileStorage(".yml", cv2.FILE_STORAGE_WRITE | cv2.FILE_STORAGE_MEMORY)
    algo.write(fs)
    return fs.releaseAndGetString()


def _algo_load(algo, text):
    fs = cv2.FileStorage(text, cv2.FILE_STORAGE_READ | cv2.FILE_STORAGE_MEMORY)
    algo.read(fs.root())
    fs.release()
    return algo


# ----------------------------------------------------------------- 数据集

def list_datasets():
    out = []
    if not os.path.isdir(DATASETS):
        return out
    for name in sorted(os.listdir(DATASETS)):
        folder = os.path.join(DATASETS, name)
        if not os.path.isdir(folder):
            continue
        classes = []
        for label in sorted(os.listdir(folder)):
            sub = os.path.join(folder, label)
            if os.path.isdir(sub):
                files = sorted(f for f in os.listdir(sub) if f.lower().endswith(IMAGE_EXT))
                classes.append({"label": label, "count": len(files), "files": files[:60]})
        out.append({"name": name, "classes": classes, "total": sum(c["count"] for c in classes)})
    return out


def dataset_path(dataset, label=None, filename=None):
    parts = [DATASETS, safe_name(dataset)]
    if not parts[1]:
        raise TrainError("dataset name is required")
    if label is not None:
        parts.append(safe_name(label))
        if not parts[2]:
            raise TrainError("class label is required")
    if filename is not None:
        parts.append(os.path.basename(str(filename)))
    return os.path.join(*parts)


_SEQ = [0]
_SEQ_LOCK = threading.Lock()


def add_images(dataset, label, images, ext=None):
    """把图片存进数据集的某个类别。images 是 BGR 数组的列表。"""
    folder = dataset_path(dataset, label)
    os.makedirs(folder, exist_ok=True)
    saved = 0
    for img in images:
        if img is None or img.size == 0:
            continue
        with _SEQ_LOCK:
            _SEQ[0] += 1
            seq = _SEQ[0]
        kind = ext or (".png" if max(img.shape[:2]) <= 320 else ".jpg")
        write_image(os.path.join(folder, "%d_%04d%s" % (int(time.time() * 1000), seq % 10000, kind)), img)
        saved += 1
    return saved


def delete_item(dataset, label=None, filename=None):
    import shutil
    path = dataset_path(dataset, label, filename)
    if not os.path.abspath(path).startswith(os.path.abspath(DATASETS) + os.sep):
        raise TrainError("bad path")
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isfile(path):
        os.remove(path)


def thumbnail(dataset, label, filename, size=96):
    img = read_image(dataset_path(dataset, label, filename))
    if img is None:
        return None
    h, w = img.shape[:2]
    factor = float(size) / max(h, w)
    if factor < 1:
        img = cv2.resize(img, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def load_dataset(dataset):
    folder = dataset_path(dataset)
    if not os.path.isdir(folder):
        raise TrainError("dataset '%s' does not exist" % dataset)
    images, labels, classes = [], [], []
    for label in sorted(os.listdir(folder)):
        sub = os.path.join(folder, label)
        if not os.path.isdir(sub):
            continue
        found = 0
        for name in sorted(os.listdir(sub)):
            if not name.lower().endswith(IMAGE_EXT):
                continue
            img = read_image(os.path.join(sub, name))
            if img is not None:
                images.append(img)
                labels.append(len(classes))
                found += 1
        if found:
            classes.append(label)
    return images, np.array(labels, np.int32), classes


# ----------------------------------------------------------------- 特征

def _gray(img, size):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def feat_color(img):
    small = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    colored = (hsv[:, :, 1] > 30).astype(np.uint8)          # 灰色像素的色相没有意义，不计入色相直方图
    parts = [cv2.calcHist([hsv], [0], colored, [18], [0, 180]).ravel(),
             cv2.calcHist([hsv], [1], None, [8], [0, 256]).ravel(),
             cv2.calcHist([hsv], [2], None, [8], [0, 256]).ravel()]
    parts = [p / (p.sum() + 1e-6) for p in parts]
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32) / 255.0
    parts.append(lab.mean(axis=0))
    parts.append(lab.std(axis=0))
    parts.append(np.array([colored.mean()], np.float32))
    return np.concatenate(parts).astype(np.float32)


def _uniform_table():
    """LBP 的 256 种模式 → 59 个「均匀模式」编号。"""
    table = np.zeros(256, np.int32)
    index = 0
    for code in range(256):
        bits = [(code >> i) & 1 for i in range(8)]
        jumps = sum(bits[i] != bits[(i + 1) % 8] for i in range(8))
        if jumps <= 2:
            table[code] = index
            index += 1
        else:
            table[code] = 58
    return table


LBP_TABLE = _uniform_table()


def _lbp_hist(gray, step):
    center = gray[step:-step, step:-step]
    code = np.zeros(center.shape, np.int32)
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
    for bit, (dy, dx) in enumerate(offsets):
        shifted = gray[step + dy * step:gray.shape[0] - step + dy * step, step + dx * step:gray.shape[1] - step + dx * step]
        code |= (shifted >= center).astype(np.int32) << bit
    hist = np.bincount(LBP_TABLE[code].ravel(), minlength=59).astype(np.float32)
    return hist / (hist.sum() + 1e-6)


def feat_texture(img):
    gray = _gray(img, 96).astype(np.int32)
    parts = [_lbp_hist(gray, 1), _lbp_hist(gray, 2)]
    g = gray.astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(g - g.mean()))) ** 2
    yy, xx = np.mgrid[-48:48, -48:48]
    radius = np.sqrt(xx ** 2 + yy ** 2)
    total = spectrum.sum() + 1e-6
    rings = [spectrum[(radius >= a) & (radius < b)].sum() / total for a, b in ((0, 4), (4, 10), (10, 22), (22, 68))]
    stats = [g.std() / 64.0, mag.mean() / 64.0, mag.std() / 64.0, math.log1p(cv2.Laplacian(g, cv2.CV_32F).var()) / 8.0,
             np.abs(gx).mean() / (np.abs(gy).mean() + 1e-3) / 4.0]
    parts.append(np.array(rings + stats, np.float32))
    return np.concatenate(parts).astype(np.float32)


_HOG = None


def feat_hog(img):
    global _HOG
    if _HOG is None:
        _HOG = cv2.HOGDescriptor((64, 64), (16, 16), (8, 8), (8, 8), 9)
    return _HOG.compute(_gray(img, 64)).ravel().astype(np.float32)


def feat_shape(img):
    """前景轮廓的形状，加上小图本身的长宽比和尺寸（同一拍摄距离下，大小本身就是线索）。"""
    h, w = img.shape[:2]
    gray = _gray(img, 96)
    best = None
    for flag in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
        mask = cv2.threshold(cv2.GaussianBlur(gray, (0, 0), 1.2), 0, 255, flag + cv2.THRESH_OTSU)[1]
        border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]]).mean() / 255.0
        if best is None or border < best[0]:     # 贴着边的那一面是背景
            best = (border, mask)
    contours, _ = cv2.findContours(best[1], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros(15, np.float32)
    out[12] = math.log(max(w, 1) / float(max(h, 1)))
    out[13] = math.log(max(w * h, 1)) / 12.0
    out[14] = math.log(max(w, h, 1)) / 6.0
    if contours:
        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)
        if area > 4:
            hu = cv2.HuMoments(cv2.moments(contour)).ravel()
            out[0:7] = np.sign(hu) * np.log10(np.abs(hu) + 1e-12) / 12.0
            perimeter = cv2.arcLength(contour, True)
            (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
            hull = cv2.contourArea(cv2.convexHull(contour))
            out[7] = min(1.0, 4 * math.pi * area / (perimeter * perimeter + 1e-6))
            out[8] = area / (hull + 1e-6)
            out[9] = min(rw, rh) / (max(rw, rh) + 1e-6)
            out[10] = area / (96.0 * 96.0)
            out[11] = len(contours) / 20.0
    return out


# ---- 深度特征

BACKBONE_MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 3, 1, 1)
BACKBONE_STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 3, 1, 1)
BACKBONE_URLS = [
    "https://huggingface.co/opencv/image_classification_mobilenet/resolve/main/image_classification_mobilenetv2_2022apr.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/image_classification_mobilenet/image_classification_mobilenetv2_2022apr.onnx",
]
BACKBONE_FILE = "mobilenetv2.onnx"
_BACKBONE = {"key": None, "net": None, "layer": None, "pool": False, "dim": 0, "lock": threading.Lock()}


def backbone_path():
    """data/backbones 里的第一个 .onnx 文件（默认下载的是 MobileNetV2，也可以自己放别的分类网络）。"""
    if not os.path.isdir(BACKBONES):
        return None
    files = sorted(f for f in os.listdir(BACKBONES) if f.lower().endswith(".onnx"))
    if BACKBONE_FILE in files:
        return os.path.join(BACKBONES, BACKBONE_FILE)
    return os.path.join(BACKBONES, files[0]) if files else None


def _backbone():
    path = backbone_path()
    if not path:
        raise TrainError("backbone_missing")
    key = (path, os.path.getmtime(path))
    state = _BACKBONE
    if state["key"] != key:
        net = cv2.dnn.readNetFromONNX(np.fromfile(path, dtype=np.uint8))
        blob = np.zeros((1, 3, 224, 224), np.float32)
        net.setInput(blob)
        final = net.forward()
        layer, pool, dim = None, False, int(final.size)
        for name in reversed(net.getLayerNames()[-12:]):       # 从后往前找分类层之前的那一层
            net.setInput(blob)
            try:
                out = net.forward(name)
            except cv2.error:
                continue
            if out.size == final.size:
                continue
            if out.ndim == 4 and out.shape[2] * out.shape[3] > 1:
                layer, pool, dim = name, True, int(out.shape[1])
            else:
                layer, pool, dim = name, False, int(out.size)
            break
        state.update(key=key, net=net, layer=layer, pool=pool, dim=dim)
    return state


def backbone_info():
    path = backbone_path()
    if not path:
        return {"available": False, "file": None}
    info = {"available": True, "file": os.path.basename(path), "size": os.path.getsize(path)}
    try:
        with _BACKBONE["lock"]:
            info["dim"] = _backbone()["dim"]
    except Exception as error:               # 文件坏了或不是 OpenCV 能读的网络
        info.update(available=False, error=str(error).strip().splitlines()[-1][:200])
    return info


def feat_deep(img):
    with _BACKBONE["lock"]:
        state = _backbone()
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, (224, 224), swapRB=True, crop=False)
        blob = (blob - BACKBONE_MEAN) / BACKBONE_STD
        state["net"].setInput(blob)
        out = state["net"].forward(state["layer"]) if state["layer"] else state["net"].forward()
    if state["pool"]:
        out = out.mean(axis=(2, 3))
    vec = out.ravel().astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-6)


def download_backbone(urls=None, proxy=None, progress=None):
    """下载预训练骨干网络（MobileNetV2，约 14 MB）。依次尝试 urls，成功一个即可。"""
    import urllib.request
    os.makedirs(BACKBONES, exist_ok=True)
    target = os.path.join(BACKBONES, BACKBONE_FILE)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else urllib.request.build_opener()
    errors = []
    for url in urls or BACKBONE_URLS:
        tmp = target + ".part"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "laya-opencv"})
            with opener.open(req, timeout=30) as resp, open(tmp, "wb") as handle:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            if os.path.getsize(tmp) < 500000:
                raise TrainError("file too small (%d bytes)" % os.path.getsize(tmp))
            cv2.dnn.readNetFromONNX(np.fromfile(tmp, dtype=np.uint8))        # 确认 OpenCV 能读
            os.replace(tmp, target)
            _BACKBONE["key"] = None
            return {"file": BACKBONE_FILE, "url": url, "size": os.path.getsize(target)}
        except Exception as error:
            errors.append("%s: %s" % (url.split("/")[2], str(error).strip().splitlines()[-1][:160]))
            try:
                os.remove(tmp)
            except OSError:
                pass
    raise TrainError("; ".join(errors))


EXTRACTORS = {"color": feat_color, "texture": feat_texture, "hog": feat_hog, "shape": feat_shape, "deep": feat_deep}


def extract(img, features):
    """返回 (特征向量, 各组的长度)。"""
    parts = [EXTRACTORS[name](img) for name in features]
    return np.concatenate(parts), [int(p.size) for p in parts]


def augment(img, rotate=False):
    """简单的增强：水平、垂直翻转；rotate=True 时再加 90 度旋转（朝向无关紧要的目标才用）。"""
    out = [cv2.flip(img, 1), cv2.flip(img, 0)]
    if rotate:
        out.append(cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE))
    return out


# ----------------------------------------------------------------- 分类器

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


def platt_fit(scores, targets, iters=200):
    """Platt 校准：拟合 p = sigmoid(a * score + b)。用带先验修正的目标值，避免小样本时过拟合到 0 / 1。"""
    scores = np.asarray(scores, np.float64)
    targets = np.asarray(targets, np.float64)
    pos, neg = targets.sum(), len(targets) - targets.sum()
    t = np.where(targets > 0.5, (pos + 1.0) / (pos + 2.0), 1.0 / (neg + 2.0))
    scale = np.abs(scores).mean() + 1e-6
    s = scores / scale
    a, b = 0.0, math.log((pos + 1.0) / (neg + 1.0))
    for _ in range(iters):
        p = _sigmoid(a * s + b)
        g_a, g_b = ((p - t) * s).sum(), (p - t).sum()
        w = p * (1 - p) + 1e-9
        h_aa, h_ab, h_bb = (w * s * s).sum() + 1e-6, (w * s).sum(), w.sum() + 1e-6
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        da, db = (h_bb * g_a - h_ab * g_b) / det, (h_aa * g_b - h_ab * g_a) / det
        a, b = a - da, b - db
        if abs(da) + abs(db) < 1e-7:
            break
    return float(a / scale), float(b)


def _svm_new(kernel, c, gamma, weights):
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR if kernel == "linear" else cv2.ml.SVM_RBF)
    svm.setC(float(c))
    svm.setGamma(float(gamma))
    svm.setClassWeights(np.array(weights, np.float64).reshape(-1, 1))
    svm.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 2000, 1e-5))
    return svm


class Classifier:
    """统一的训练 / 打分接口。scores() 返回每类一列的原始分数，后面再校准成概率。"""

    def __init__(self, algo, classes, params=None):
        self.algo = algo
        self.n = int(classes)
        self.params = dict(params or {})
        self.parts = []
        self.train_x = None
        self.train_y = None

    def fit(self, x, y):
        x = np.ascontiguousarray(x, np.float32)
        if self.algo == "svm":
            self.parts = []
            for k in range(self.n):
                target = np.where(y == k, 1, -1).astype(np.int32)
                pos = max(1, int((target == 1).sum()))
                neg = max(1, int((target == -1).sum()))
                total = float(pos + neg)
                svm = _svm_new(self.params.get("kernel", "rbf"), self.params.get("C", 10.0), self.params.get("gamma", 1.0),
                               [total / (2.0 * neg), total / (2.0 * pos)])       # 权重顺序对应标签 -1、+1
                svm.train(x, cv2.ml.ROW_SAMPLE, target)
                sign = 1.0                      # OpenCV 原始输出的正负号不固定，这里按训练集对齐成「越大越像本类」
                raw = svm.predict(x, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
                if raw[target == 1].mean() < raw[target == -1].mean():
                    sign = -1.0
                self.parts.append((svm, sign))
        elif self.algo == "rtrees":
            trees = cv2.ml.RTrees_create()
            trees.setMaxDepth(int(self.params.get("depth", 14)))
            trees.setMinSampleCount(2)
            trees.setCalculateVarImportance(False)
            trees.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER, int(self.params.get("trees", 120)), 0))
            trees.train(x, cv2.ml.ROW_SAMPLE, y.astype(np.int32))
            self.parts = [trees]
        else:
            self.train_x, self.train_y = x, y.astype(np.int32)
            knn = cv2.ml.KNearest_create()
            knn.train(x, cv2.ml.ROW_SAMPLE, y.astype(np.float32))
            self.parts = [knn]
        return self

    def scores(self, x):
        x = np.ascontiguousarray(x, np.float32)
        out = np.zeros((len(x), self.n), np.float32)
        if not len(x):
            return out
        if self.algo == "svm":
            for k, (svm, sign) in enumerate(self.parts):
                out[:, k] = sign * svm.predict(x, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
        elif self.algo == "rtrees":
            votes = self.parts[0].getVotes(x, 0)
            labels = votes[0].astype(int)
            counts = votes[1:].astype(np.float32)
            counts /= counts.sum(axis=1, keepdims=True) + 1e-6
            for col, label in enumerate(labels):
                if 0 <= label < self.n:
                    out[:, label] = counts[:, col]
        else:
            k = max(1, min(int(self.params.get("k", 5)), len(self.train_y)))
            neighbours = self.parts[0].findNearest(x, k)[2].astype(int)
            for label in range(self.n):
                out[:, label] = (neighbours == label).mean(axis=1)
        return out

    def dump(self):
        if self.algo == "svm":
            return {"svm": [_algo_text(svm) for svm, _ in self.parts], "sign": [sign for _, sign in self.parts]}
        if self.algo == "rtrees":
            return {"rtrees": _algo_text(self.parts[0])}
        return {}

    def restore(self, payload, arrays):
        if self.algo == "svm":
            self.parts = [(_algo_load(cv2.ml.SVM_create(), text), float(sign)) for text, sign in zip(payload["svm"], payload["sign"])]
        elif self.algo == "rtrees":
            self.parts = [_algo_load(cv2.ml.RTrees_create(), payload["rtrees"])]
        else:
            self.fit(arrays["knn_x"], arrays["knn_y"])
        return self


def _probabilities(scores, algo, platt):
    """把原始分数变成每行和为 1 的概率。"""
    if algo == "svm":
        probs = np.zeros_like(scores, dtype=np.float64)
        for k, (a, b) in enumerate(platt):
            probs[:, k] = _sigmoid(a * scores[:, k] + b)
    else:
        probs = scores.astype(np.float64) + 1e-3
    return probs / (probs.sum(axis=1, keepdims=True) + 1e-12)


def _folds(y, k, seed=0):
    """分层 K 折：每一折里各类的比例大致相同。"""
    rng = np.random.default_rng(seed)
    fold = np.zeros(len(y), np.int32)
    for label in np.unique(y):
        idx = np.where(y == label)[0]
        rng.shuffle(idx)
        fold[idx] = np.arange(len(idx)) % k
    return fold


def _metrics(y, pred, classes):
    n = len(classes)
    matrix = np.zeros((n, n), np.int32)
    for actual, got in zip(y, pred):
        matrix[int(actual), int(got)] += 1
    per_class = []
    for k, label in enumerate(classes):
        tp = int(matrix[k, k])
        actual, predicted = int(matrix[k].sum()), int(matrix[:, k].sum())
        per_class.append({"label": label, "n": actual, "recall": round(tp / actual, 4) if actual else None,
                          "precision": round(tp / predicted, 4) if predicted else None})
    return {"accuracy": round(float((y == pred).mean()), 4) if len(y) else None, "confusion": matrix.tolist(), "per_class": per_class}


def candidates(algo, groups, params):
    """要比较的参数组合。特征按组归一化后，样本间距离的平方大约是 2 × 组数，gamma 取它的倒数量级。"""
    base = 1.0 / max(1, groups)
    if algo == "svm":
        if params.get("kernel") or params.get("C"):
            return [{"kernel": params.get("kernel", "rbf"), "C": float(params.get("C", 10)), "gamma": float(params.get("gamma", base))}]
        return [{"kernel": "rbf", "C": 10.0, "gamma": base}, {"kernel": "rbf", "C": 100.0, "gamma": base * 0.3},
                {"kernel": "linear", "C": 1.0, "gamma": base}]
    if algo == "rtrees":
        return [{"trees": int(params.get("trees", 120)), "depth": int(params.get("depth", 14))}]
    return [{"k": int(params.get("k", 5))}]


def train(dataset, name, features=("color", "texture", "shape"), algo="svm", folds=5, use_augment=True, rotate=False,
          params=None, progress=None):
    """训练并保存一个识别模型，返回它的 meta（含交叉验证指标）。"""
    if not HAS_ML:
        raise TrainError("this OpenCV build has no cv2.ml; install opencv-python-headless 4.x (not 5.x)")
    started = time.time()
    features = [f for f in FEATURES if f in (features or [])]
    if not features:
        raise TrainError("pick at least one feature")
    if algo not in ALGOS:
        raise TrainError("unknown algorithm '%s'" % algo)
    name = safe_name(name)
    if not name:
        raise TrainError("model name is required")
    if "deep" in features:
        with _BACKBONE["lock"]:
            _backbone()                          # 没有骨干网络时尽早报错
    say = progress or (lambda stage, done: None)

    say("load", 0.0)
    images, y, classes = load_dataset(dataset)
    if len(classes) < 2:
        raise TrainError("need at least 2 classes with images; dataset '%s' has %d" % (dataset, len(classes)))
    counts = np.bincount(y, minlength=len(classes))
    if counts.min() < 2:
        raise TrainError("every class needs at least 2 images; '%s' has %d" % (classes[int(counts.argmin())], int(counts.min())))

    # 特征：原图一份，增强图各一份（增强图只进训练折，不进验证折）
    variants = []
    sizes = None
    total = len(images)
    for index, img in enumerate(images):
        row = [img] + (augment(img, rotate) if use_augment else [])
        vecs = []
        for item in row:
            vec, sizes = extract(item, features)
            vecs.append(vec)
        variants.append(np.stack(vecs))
        if index % 5 == 0:
            say("features", index / float(total))
    base = np.stack([v[0] for v in variants]).astype(np.float32)

    mean, std = base.mean(axis=0), base.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    weight = np.concatenate([np.full(size, 1.0 / math.sqrt(size), np.float32) for size in sizes])   # 每组特征的总分量相同

    def scale(matrix):
        return ((matrix - mean) / std * weight).astype(np.float32)

    k = int(max(2, min(int(folds), int(counts.min()))))
    fold = _folds(y, k)
    best = None
    options = candidates(algo, len(features), params or {})
    for number, option in enumerate(options):
        oof = np.zeros((len(y), len(classes)), np.float32)
        for f in range(k):
            train_idx, test_idx = np.where(fold != f)[0], np.where(fold == f)[0]
            x_train = np.concatenate([variants[i] for i in train_idx])
            y_train = np.concatenate([np.full(len(variants[i]), y[i], np.int32) for i in train_idx])
            model = Classifier(algo, len(classes), option).fit(scale(x_train), y_train)
            oof[test_idx] = model.scores(scale(base[test_idx]))
            say("validate", (number + (f + 1) / float(k)) / len(options))
        platt = [platt_fit(oof[:, c], (y == c).astype(np.float64)) for c in range(len(classes))] if algo == "svm" else []
        probs = _probabilities(oof, algo, platt)
        accuracy = float((probs.argmax(axis=1) == y).mean())
        if best is None or accuracy > best["accuracy"] + 1e-9:
            best = {"accuracy": accuracy, "option": option, "platt": platt, "probs": probs}

    say("fit", 0.0)
    x_all = scale(np.concatenate(variants))
    y_all = np.concatenate([np.full(len(v), y[i], np.int32) for i, v in enumerate(variants)])
    final = Classifier(algo, len(classes), best["option"]).fit(x_all, y_all)

    pred = best["probs"].argmax(axis=1)
    metrics = _metrics(y, pred, classes)
    metrics["mean_confidence"] = round(float(best["probs"].max(axis=1).mean()), 4)
    meta = {"name": name, "dataset": safe_name(dataset), "classes": classes, "features": features, "feature_sizes": sizes,
            "algo": algo, "params": best["option"], "platt": best["platt"], "folds": k, "samples": int(len(y)),
            "augment": bool(use_augment), "rotate": bool(rotate), "metrics": metrics,
            "backbone": os.path.basename(backbone_path() or "") if "deep" in features else None,
            "opencv": cv2.__version__, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - started, 2)}

    folder = os.path.join(MODELS, name)
    os.makedirs(folder, exist_ok=True)
    arrays = {"mean": mean.astype(np.float32), "std": std.astype(np.float32), "weight": weight}
    if algo == "knn":
        arrays["knn_x"], arrays["knn_y"] = x_all, y_all
    with open(os.path.join(folder, "arrays.npz"), "wb") as handle:
        np.savez_compressed(handle, **arrays)
    with open(os.path.join(folder, "weights.json"), "w", encoding="utf-8") as handle:
        json.dump(final.dump(), handle)
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
    _CACHE.pop(name, None)
    say("done", 1.0)
    return meta


# ----------------------------------------------------------------- 使用模型

class Model:
    def __init__(self, folder):
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as handle:
            self.meta = json.load(handle)
        with open(os.path.join(folder, "arrays.npz"), "rb") as handle:
            arrays = dict(np.load(handle))
        with open(os.path.join(folder, "weights.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.classes = self.meta["classes"]
        self.features = self.meta["features"]
        self.mean, self.std, self.weight = arrays["mean"], arrays["std"], arrays["weight"]
        self.clf = Classifier(self.meta["algo"], len(self.classes), self.meta.get("params")).restore(payload, arrays)
        self.lock = threading.Lock()

    def predict(self, images):
        """返回 [(类别, 概率, {类别: 概率})]，和 images 一一对应。"""
        if not images:
            return []
        rows = []
        for img in images:
            if img is None or img.size == 0:
                img = np.zeros((8, 8, 3), np.uint8)
            rows.append(extract(img, self.features)[0])
        x = ((np.stack(rows) - self.mean) / self.std * self.weight).astype(np.float32)
        with self.lock:
            scores = self.clf.scores(x)
        probs = _probabilities(scores, self.meta["algo"], self.meta.get("platt") or [])
        out = []
        for row in probs:
            best = int(row.argmax())
            out.append((self.classes[best], float(row[best]), {c: round(float(p), 4) for c, p in zip(self.classes, row)}))
        return out


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def get_model(name):
    """按名字取模型；没有训练过返回 None。"""
    name = safe_name(name)
    folder = os.path.join(MODELS, name)
    meta = os.path.join(folder, "meta.json")
    if not name or not os.path.isfile(meta):
        return None
    stamp = os.path.getmtime(meta)
    with _CACHE_LOCK:
        hit = _CACHE.get(name)
        if hit and hit[0] == stamp:
            return hit[1]
        model = Model(folder)
        _CACHE[name] = (stamp, model)
        return model


def list_models():
    out = []
    if not os.path.isdir(MODELS):
        return out
    for name in sorted(os.listdir(MODELS)):
        path = os.path.join(MODELS, name, "meta.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    out.append(json.load(handle))
            except (OSError, ValueError):
                continue
    return out


def delete_model(name):
    import shutil
    folder = os.path.join(MODELS, safe_name(name))
    if safe_name(name) and os.path.isdir(folder):
        shutil.rmtree(folder)
    _CACHE.pop(safe_name(name), None)
