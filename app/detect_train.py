# -*- coding: utf-8 -*-
"""目标检测训练 CLI（torch + torchvision，作为子进程运行）。stdout 每行一个 JSON 事件，stderr 自由。

  python detect_train.py probe
  python detect_train.py train --dataset DIR --out DIR [--arch ssdlite|fasterrcnn_mobile] [--epochs 20] [--batch 8]
                               [--imgsz 320] [--lr 0.01] [--device auto|cuda|cpu] [--resume] [--holdout 0.15]
                               [--pretrained auto|yes|no] [--seed 0]
  python detect_train.py predict --model DIR --image PATH [--conf 0.4] [--device auto]

事件：start / log / progress(epoch, epochs, step, steps, loss, eta_seconds) / oom(retry, batch) / result / error(kind)。

数据集目录：images/*.jpg、labels/*.txt（YOLO：class_id cx cy w h，归一化）、classes.json。
产出：<out>/model.pt（state_dict）、<out>/meta.json、<out>/last.pt（每个 epoch 的断点，--resume 用）。

torch / torchvision 都在函数里按需导入：没装时 `probe` 仍能正常退出，vision_server 也能把本文件当模块导入（Detector）。
测试用环境变量：LAYA_WB_FAKE_OOM=<n> 让前 n 个训练步在 CPU 上也抛显存不足，用来验证降档重试。
"""
import argparse
import json
import math
import os
import random
import sys
import time

import cv2
import numpy as np

ARCHS = {"ssdlite": "ssdlite320_mobilenet_v3_large", "fasterrcnn_mobile": "fasterrcnn_mobilenet_v3_large_320_fpn"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
WEIGHT_FILES = {"ssdlite": "mobilenet_v3_large-8738ca79.pth", "fasterrcnn_mobile": "mobilenet_v3_large-8738ca79.pth"}
WEIGHT_URL = "https://download.pytorch.org/models/mobilenet_v3_large-8738ca79.pth"


def emit(event, **fields):
    fields["event"] = event
    sys.stdout.write(json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(zh, en):
    emit("log", message="%s / %s" % (zh, en))


class TrainFail(Exception):
    def __init__(self, message, kind="other"):
        Exception.__init__(self, message)
        self.kind = kind


# ----------------------------------------------------------------- 环境

def pick_device(wanted="auto"):
    import torch
    wanted = (wanted or "auto").lower()
    if wanted == "cpu":
        return torch.device("cpu")
    if wanted.startswith("cuda") and torch.cuda.is_available():
        return torch.device(wanted)
    if wanted == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return torch.device("mps")
    return torch.device("cpu")


def probe():
    out = {"torch": None, "torchvision": None, "device": None, "gpu_name": None, "vram_mb": None, "cuda": None}
    try:
        import torch
        out["torch"] = torch.__version__
    except ImportError:
        return out
    try:
        import torchvision
        out["torchvision"] = torchvision.__version__
    except ImportError:
        pass
    device = pick_device("auto")
    out["device"] = device.type
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(0)
        out["gpu_name"] = props.name
        out["vram_mb"] = int(props.total_memory // (1024 * 1024))
        out["cuda"] = torch.version.cuda
    return out


def is_oom(error):
    import torch
    if isinstance(error, getattr(torch, "OutOfMemoryError", ())) or isinstance(error, getattr(torch.cuda, "OutOfMemoryError", ())):
        return True
    text = str(error).lower()
    return isinstance(error, RuntimeError) and ("out of memory" in text or "cudnn_status_alloc_failed" in text)


# ----------------------------------------------------------------- 数据

def read_image(path):
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def read_classes(folder):
    path = os.path.join(folder, "classes.json")
    if not os.path.isfile(path):
        raise TrainFail("classes.json not found in %s" % folder, "data")
    with open(path, encoding="utf-8") as handle:
        classes = json.load(handle)
    if not isinstance(classes, list) or not classes:
        raise TrainFail("classes.json must be a non-empty list", "data")
    return [str(c) for c in classes]


def read_labels(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                rows.append((int(float(parts[0])), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
            except ValueError:
                continue
    return rows


def load_dataset(folder, imgsz):
    """读入全部图片（缩到长边 imgsz）和框（像素 xyxy）。小数据集全放内存最省事。"""
    classes = read_classes(folder)
    images_dir = os.path.join(folder, "images")
    if not os.path.isdir(images_dir):
        raise TrainFail("no images/ folder in %s" % folder, "data")
    items = []
    for filename in sorted(os.listdir(images_dir)):
        if not filename.lower().endswith(IMAGE_EXT):
            continue
        img = read_image(os.path.join(images_dir, filename))
        if img is None:
            continue
        h, w = img.shape[:2]
        factor = float(imgsz) / max(h, w)
        if factor < 1:
            img = cv2.resize(img, (max(1, int(round(w * factor))), max(1, int(round(h * factor)))), interpolation=cv2.INTER_AREA)
        nh, nw = img.shape[:2]
        boxes, labels = [], []
        for cid, cx, cy, bw, bh in read_labels(os.path.join(folder, "labels", os.path.splitext(filename)[0] + ".txt")):
            if not 0 <= cid < len(classes):
                continue
            x0, y0 = max(0.0, (cx - bw / 2.0) * nw), max(0.0, (cy - bh / 2.0) * nh)
            x1, y1 = min(float(nw), (cx + bw / 2.0) * nw), min(float(nh), (cy + bh / 2.0) * nh)
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            boxes.append([x0, y0, x1, y1])
            labels.append(cid + 1)                # 0 留给背景
        items.append({"file": filename, "img": np.ascontiguousarray(img[:, :, ::-1]), "boxes": np.array(boxes, np.float32).reshape(-1, 4),
                      "labels": np.array(labels, np.int64)})
    if not items:
        raise TrainFail("dataset has no readable images", "data")
    return classes, items


def split(items, holdout, seed):
    order = list(range(len(items)))
    random.Random(seed).shuffle(order)
    n_val = int(round(len(items) * holdout)) if holdout > 0 else 0
    if holdout > 0 and n_val == 0 and len(items) >= 4:
        n_val = 1
    n_val = min(n_val, max(0, len(items) - 2))
    val = [items[i] for i in order[:n_val]]
    train = [items[i] for i in order[n_val:]]
    return train, val


def augment(item, rng):
    """水平翻转 + 亮度 / 对比度 / 饱和度抖动。"""
    img, boxes = item["img"], item["boxes"].copy()
    if rng.random() < 0.5:
        img = np.ascontiguousarray(img[:, ::-1, :])
        w = img.shape[1]
        if len(boxes):
            boxes = np.stack([w - boxes[:, 2], boxes[:, 1], w - boxes[:, 0], boxes[:, 3]], axis=1)
    f = img.astype(np.float32)
    f = (f - 128.0) * rng.uniform(0.8, 1.2) + 128.0 + rng.uniform(-24, 24)
    if rng.random() < 0.5:
        gray = f.mean(axis=2, keepdims=True)
        f = gray + (f - gray) * rng.uniform(0.7, 1.3)
    return np.clip(f, 0, 255).astype(np.uint8), boxes


def to_tensor(img):
    import torch
    return torch.from_numpy(img).permute(2, 0, 1).float().div_(255.0)


def batches(items, batch, rng, train):
    order = list(range(len(items)))
    if train:
        rng.shuffle(order)
        while len(order) % batch and len(order) >= batch:    # 补齐最后一批：BatchNorm 在只有 1 张图时会报错
            order.append(order[len(order) % batch - 1])
    for start in range(0, len(order), batch):
        yield [items[i] for i in order[start:start + batch]]


def set_train_mode(model, batch):
    """batch 为 1 时 BatchNorm 没法统计，把它们固定在 eval 模式（常见做法），其余层照常训练。"""
    import torch
    model.train()
    if batch <= 1:
        for module in model.modules():
            if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
                module.eval()


def make_targets(batch, rng, train):
    import torch
    images, targets = [], []
    for item in batch:
        if train:
            img, boxes = augment(item, rng)
        else:
            img, boxes = item["img"], item["boxes"]
        images.append(to_tensor(img))
        targets.append({"boxes": torch.from_numpy(np.asarray(boxes, np.float32).reshape(-1, 4)), "labels": torch.from_numpy(item["labels"])})
    return images, targets


# ----------------------------------------------------------------- 模型

def weights_hint():
    home = os.environ.get("TORCH_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "torch")
    folder = os.path.join(home, "hub", "checkpoints")
    return ("预训练权重下载失败（国内网络常见）。可手动下载 %s 放到 %s 后重试；本次改为从头训练，效果会差一些、需要更多轮数。"
            % (WEIGHT_URL, folder),
            "Could not download the pretrained weights. Download %s manually into %s and retry; training from scratch this time "
            "(lower accuracy, needs more epochs)." % (WEIGHT_URL, folder))


def build_model(arch, num_classes, imgsz, pretrained):
    """按架构建模型，分类头按类别数新建。pretrained: auto / yes / no。返回 (model, 是否用了预训练)。"""
    import torch
    import torchvision
    from torchvision.models import MobileNet_V3_Large_Weights
    from torchvision.models.detection.transform import GeneralizedRCNNTransform
    name = ARCHS.get(arch, arch)
    builder = getattr(torchvision.models.detection, name, None)
    if builder is None:
        raise TrainFail("unknown arch '%s' (use %s)" % (arch, " / ".join(ARCHS)), "other")
    kwargs = {"weights": None, "num_classes": num_classes}
    if arch == "fasterrcnn_mobile":
        kwargs.update(min_size=imgsz, max_size=imgsz * 2)
    else:
        kwargs.update(detections_per_img=100)
    used = False
    if pretrained in ("auto", "yes"):
        try:
            model = builder(weights_backbone=MobileNet_V3_Large_Weights.IMAGENET1K_V1, **kwargs)
            used = True
        except Exception as error:               # 下载失败（无网络）、文件损坏等
            if pretrained == "yes":
                raise TrainFail("%s / %s (%s)" % (weights_hint() + (str(error).strip().splitlines()[-1][:200],)), "download")
            log(*weights_hint())
            emit("log", message="pretrained: %s" % str(error).strip().splitlines()[-1][:300])
    if not used:
        model = builder(weights_backbone=None, **kwargs)
    if arch != "fasterrcnn_mobile":              # SSDLite 的输入固定 320×320；按 imgsz 改掉（默认框是相对坐标，尺寸可变）
        old = model.transform
        model.transform = GeneralizedRCNNTransform(min_size=imgsz, max_size=imgsz, image_mean=old.image_mean, image_std=old.image_std,
                                                   fixed_size=(imgsz, imgsz))
    return model, used


# ----------------------------------------------------------------- 评估：mAP@0.5

def iou_matrix(a, b):
    """a: [N,4], b: [M,4]，xyxy。"""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), np.float32)
    x0 = np.maximum(a[:, None, 0], b[None, :, 0])
    y0 = np.maximum(a[:, None, 1], b[None, :, 1])
    x1 = np.minimum(a[:, None, 2], b[None, :, 2])
    y1 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x1 - x0, 0, None) * np.clip(y1 - y0, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (area_a[:, None] + area_b[None, :] - inter + 1e-9)


def average_precision(recall, precision):
    """VOC 风格：precision 包络后对 recall 积分。"""
    r = np.concatenate([[0.0], recall, [1.0]])
    p = np.concatenate([[0.0], precision, [0.0]])
    for i in range(len(p) - 2, -1, -1):
        p[i] = max(p[i], p[i + 1])
    idx = np.where(r[1:] != r[:-1])[0]
    return float(np.sum((r[idx + 1] - r[idx]) * p[idx + 1]))


def map50(predictions, truths, num_classes, iou_thr=0.5):
    """predictions: 每张图 {"boxes":[N,4], "scores":[N], "labels":[N]}；truths: 每张图 {"boxes","labels"}。
    返回 (mAP, {类别下标(从 1 起): AP 或 None})。没有真值的类别不计入平均。"""
    per_class = {}
    for cls in range(1, num_classes):
        records = []                             # (score, is_tp)
        total = 0
        for pred, truth in zip(predictions, truths):
            gt = truth["boxes"][truth["labels"] == cls]
            total += len(gt)
            sel = pred["labels"] == cls
            boxes, scores = pred["boxes"][sel], pred["scores"][sel]
            order = np.argsort(-scores)
            taken = np.zeros(len(gt), bool)
            ious = iou_matrix(boxes[order], gt) if len(gt) else None
            for rank, i in enumerate(order):
                hit = False
                if ious is not None and ious.shape[1]:
                    j = int(np.argmax(ious[rank]))
                    if ious[rank, j] >= iou_thr and not taken[j]:
                        taken[j] = True
                        hit = True
                records.append((float(scores[i]), hit))
        if total == 0:
            per_class[cls] = None
            continue
        if not records:
            per_class[cls] = 0.0
            continue
        records.sort(key=lambda r: -r[0])
        tp = np.cumsum([1 if r[1] else 0 for r in records], dtype=np.float64)
        fp = np.cumsum([0 if r[1] else 1 for r in records], dtype=np.float64)
        per_class[cls] = average_precision(tp / total, tp / np.maximum(tp + fp, 1e-9))
    valid = [v for v in per_class.values() if v is not None]
    return (float(sum(valid) / len(valid)) if valid else None), per_class


def evaluate(model, items, device, batch, num_classes):
    import torch
    model.eval()
    predictions, truths = [], []
    with torch.no_grad():
        for group in batches(items, max(1, batch), None, False):
            images, targets = make_targets(group, None, False)
            outputs = model([img.to(device) for img in images])
            for out, target in zip(outputs, targets):
                predictions.append({"boxes": out["boxes"].cpu().numpy(), "scores": out["scores"].cpu().numpy(), "labels": out["labels"].cpu().numpy()})
                truths.append({"boxes": target["boxes"].numpy(), "labels": target["labels"].numpy()})
    return map50(predictions, truths, num_classes)


# ----------------------------------------------------------------- 训练

def train(args):
    import torch
    started = time.time()
    folder, out = os.path.abspath(args.dataset), os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    arch = args.arch if args.arch in ARCHS else ("ssdlite" if args.arch in (None, "", "ssdlite320_mobilenet_v3_large") else args.arch)
    if arch == "fasterrcnn_mobilenet_v3_large_320_fpn":
        arch = "fasterrcnn_mobile"
    if arch not in ARCHS:
        raise TrainFail("unknown arch '%s' (use %s)" % (args.arch, " / ".join(ARCHS)), "other")
    imgsz = max(96, int(args.imgsz))
    emit("start", command="train", config={"dataset": folder, "out": out, "arch": arch, "epochs": args.epochs, "batch": args.batch,
                                            "imgsz": imgsz, "lr": args.lr, "holdout": args.holdout, "pretrained": args.pretrained})
    emit("progress", stage="prepare", progress=0.0)
    classes, items = load_dataset(folder, imgsz)
    train_items, val_items = split(items, float(args.holdout), int(args.seed))
    total_boxes = int(sum(len(i["labels"]) for i in items))
    if total_boxes == 0:
        raise TrainFail("dataset has no boxes; label some images first", "data")
    log("数据：%d 张图，%d 个框，%d 类；训练 %d 张，验证 %d 张" % (len(items), total_boxes, len(classes), len(train_items), len(val_items)),
        "data: %d images, %d boxes, %d classes; train %d, holdout %d" % (len(items), total_boxes, len(classes), len(train_items), len(val_items)))

    device = pick_device(args.device)
    log("设备：%s" % device, "device: %s" % device)
    num_classes = len(classes) + 1
    model, pretrained_used = build_model(arch, num_classes, imgsz, args.pretrained)
    model.to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.SGD(params, lr=float(args.lr), momentum=0.9, weight_decay=5e-4)

    epochs = max(1, int(args.epochs))
    start_epoch = 0
    last_path = os.path.join(out, "last.pt")
    if args.resume and os.path.isfile(last_path):
        state = torch.load(last_path, map_location="cpu", weights_only=False)
        if state.get("classes") != classes or state.get("arch") != arch:
            raise TrainFail("last.pt was trained with different classes or arch; cannot resume", "other")
        model.load_state_dict(state["model"])
        try:
            optimizer.load_state_dict(state["optimizer"])
        except Exception:
            pass
        start_epoch = int(state.get("epoch", 0))
        pretrained_used = bool(state.get("pretrained_used", pretrained_used))
        log("从 last.pt 继续：已完成 %d 轮" % start_epoch, "resuming from last.pt: %d epochs done" % start_epoch)

    batch = max(1, int(args.batch))
    fake_oom = int(os.environ.get("LAYA_WB_FAKE_OOM") or 0)
    rng = random.Random(int(args.seed))
    peak = 0
    retries = 0
    global_step = [0]
    epoch = start_epoch
    losses = []
    step_times = []
    warmup = 50

    def save_last(done):
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "epoch": done, "classes": classes, "arch": arch,
                    "imgsz": imgsz, "pretrained_used": pretrained_used}, last_path)

    batch = min(batch, len(train_items))
    while epoch < epochs:
        set_train_mode(model, batch)
        steps = int(math.ceil(len(train_items) / float(batch)))
        step = 0
        epoch_loss = []
        try:
            for group in batches(train_items, batch, rng, True):
                t0 = time.time()
                images, targets = make_targets(group, rng, True)
                images = [img.to(device) for img in images]
                targets = [{k: v.to(device) for k, v in tg.items()} for tg in targets]
                if fake_oom > 0:
                    fake_oom -= 1
                    raise torch.OutOfMemoryError("fake CUDA out of memory (LAYA_WB_FAKE_OOM)")
                if global_step[0] < warmup:          # 线性预热，避免一开始就发散
                    for g in optimizer.param_groups:
                        g["lr"] = float(args.lr) * (0.1 + 0.9 * (global_step[0] + 1) / warmup)
                elif epoch >= int(epochs * 0.75):     # 最后四分之一降 10 倍
                    for g in optimizer.param_groups:
                        g["lr"] = float(args.lr) * 0.1
                loss_dict = model(images, targets)
                loss = sum(v for v in loss_dict.values())
                if not torch.isfinite(loss):
                    raise TrainFail("loss became NaN / inf; lower --lr", "other")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 10.0)
                optimizer.step()
                value = float(loss.detach().cpu())
                epoch_loss.append(value)
                step += 1
                global_step[0] += 1
                step_times.append(time.time() - t0)
                step_times = step_times[-50:]
                avg = sum(step_times) / len(step_times)
                remaining = (steps - step) + steps * (epochs - epoch - 1)
                done = ((epoch - start_epoch) * steps + step) / float(max(1, (epochs - start_epoch) * steps))
                emit("progress", stage="train", progress=round(done * 0.95, 4), epoch=epoch + 1, epochs=epochs, step=step, steps=steps,
                     loss=round(value, 4), lr=round(optimizer.param_groups[0]["lr"], 6), eta_seconds=int(avg * remaining))
        except Exception as error:               # noqa: BLE001 - 需要判断是不是显存不足
            if not is_oom(error):
                raise
            if device.type == "cuda":
                torch.cuda.empty_cache()
            if batch <= 1:
                raise TrainFail("out of memory even with batch 1; use a smaller --imgsz or the ssdlite arch", "oom")
            batch = max(1, batch // 2)
            retries += 1
            emit("oom", retry=retries, batch=batch, imgsz=imgsz)
            log("显存不足，batch 降到 %d 重试本轮" % batch, "out of memory; retrying this epoch with batch %d" % batch)
            continue
        epoch += 1
        losses.append(sum(epoch_loss) / max(1, len(epoch_loss)))
        if device.type == "cuda":
            peak = max(peak, int(torch.cuda.max_memory_allocated() // (1024 * 1024)))
        save_last(epoch)
        log("第 %d/%d 轮完成，平均损失 %.4f" % (epoch, epochs, losses[-1]), "epoch %d/%d done, mean loss %.4f" % (epoch, epochs, losses[-1]))

    emit("progress", stage="evaluate", progress=0.95, epoch=epochs, epochs=epochs)
    score, per_class = (None, {})
    if val_items:
        score, per_class = evaluate(model, val_items, device, batch, num_classes)
    per_class_named = {classes[cid - 1]: (None if ap is None else round(ap, 4)) for cid, ap in per_class.items()}
    emit("progress", stage="save", progress=0.98)
    torch.save(model.state_dict(), os.path.join(out, "model.pt"))
    meta = {"arch": arch, "classes": classes, "imgsz": imgsz, "map50": None if score is None else round(score, 4), "per_class": per_class_named,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "torchvision": __import__("torchvision").__version__,
            "pretrained_used": bool(pretrained_used), "epochs_done": epochs, "batch": batch, "lr": float(args.lr),
            "train_images": len(train_items), "holdout_images": len(val_items), "boxes": total_boxes,
            "losses": [round(v, 4) for v in losses], "device": device.type,
            "note": "batch 8 / imgsz 320 on a 4 GB GPU is an estimate, not measured" if device.type != "cuda" else None}
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
    result = {"out": out, "classes": classes, "epochs_done": epochs, "map50": meta["map50"], "per_class": per_class_named,
              "seconds": round(time.time() - started, 1), "peak_vram_mb": peak or None, "pretrained_used": bool(pretrained_used),
              "batch": batch, "holdout_images": len(val_items), "train_images": len(train_items), "oom_retries": retries}
    emit("progress", stage="save", progress=1.0)
    emit("result", **result)
    return result


# ----------------------------------------------------------------- 推理

class Detector:
    """加载 <dir>/model.pt + meta.json；predict(img_bgr, conf) → [{"label","score","bbox":[x,y,w,h]}]（原图像素）。"""

    def __init__(self, folder, device="auto"):
        import torch
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as handle:
            self.meta = json.load(handle)
        self.classes = [str(c) for c in self.meta["classes"]]
        self.imgsz = int(self.meta.get("imgsz", 320))
        self.arch = self.meta.get("arch", "ssdlite")
        self.device = pick_device(os.environ.get("LAYA_WB_DETECT_DEVICE") or device)
        self.model, _ = build_model(self.arch, len(self.classes) + 1, self.imgsz, "no")
        self.model.load_state_dict(torch.load(os.path.join(folder, "model.pt"), map_location="cpu", weights_only=True))
        self.model.to(self.device).eval()
        self.lock = __import__("threading").Lock()

    def predict(self, img, conf=0.4, classes=None):
        import torch
        h, w = img.shape[:2]
        factor = float(self.imgsz) / max(h, w)
        small = img if factor >= 1 else cv2.resize(img, (max(1, int(round(w * factor))), max(1, int(round(h * factor)))), interpolation=cv2.INTER_AREA)
        factor = small.shape[1] / float(w)
        tensor = to_tensor(np.ascontiguousarray(small[:, :, ::-1])).to(self.device)
        with self.lock, torch.no_grad():
            out = self.model([tensor])[0]
        boxes = out["boxes"].cpu().numpy() / factor
        scores = out["scores"].cpu().numpy()
        labels = out["labels"].cpu().numpy()
        found = []
        wanted = set(str(c) for c in classes) if classes else None
        for (x0, y0, x1, y1), score, cid in zip(boxes, scores, labels):
            if score < conf or not 1 <= int(cid) <= len(self.classes):
                continue
            label = self.classes[int(cid) - 1]
            if wanted and label not in wanted:
                continue
            x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
            x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            found.append({"label": label, "score": round(float(score), 4), "bbox": [x0, y0, x1 - x0, y1 - y0]})
        found.sort(key=lambda f: -f["score"])
        return found


def predict(args):
    emit("start", command="predict", config={"model": args.model, "image": args.image, "conf": args.conf})
    if os.environ.get("LAYA_WB_DETECT_DEVICE") is None and args.device:
        os.environ["LAYA_WB_DETECT_DEVICE"] = args.device
    img = read_image(args.image)
    if img is None:
        raise TrainFail("cannot read image %s" % args.image, "data")
    detector = Detector(os.path.abspath(args.model), args.device)
    boxes = detector.predict(img, float(args.conf))
    emit("result", boxes=boxes, width=int(img.shape[1]), height=int(img.shape[0]), classes=detector.classes)


# ----------------------------------------------------------------- 入口

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("probe")
    p_train = sub.add_parser("train")
    p_train.add_argument("--dataset", required=True)
    p_train.add_argument("--out", required=True)
    p_train.add_argument("--arch", default="ssdlite")
    p_train.add_argument("--epochs", type=int, default=20)
    p_train.add_argument("--batch", type=int, default=8)
    p_train.add_argument("--imgsz", type=int, default=320)
    p_train.add_argument("--lr", type=float, default=0.01)
    p_train.add_argument("--device", default="auto")
    p_train.add_argument("--resume", action="store_true")
    p_train.add_argument("--holdout", type=float, default=0.15)
    p_train.add_argument("--pretrained", default="auto", choices=("auto", "yes", "no"))
    p_train.add_argument("--seed", type=int, default=0)
    p_pred = sub.add_parser("predict")
    p_pred.add_argument("--model", required=True)
    p_pred.add_argument("--image", required=True)
    p_pred.add_argument("--conf", type=float, default=0.4)
    p_pred.add_argument("--device", default="auto")
    args = parser.parse_args(argv)
    if args.command == "probe":
        emit("start", command="probe", config={})
        emit("result", **probe())
        return 0
    if args.command not in ("train", "predict"):
        parser.print_help(sys.stderr)
        return 2
    try:
        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
        except ImportError as error:
            raise TrainFail("torch / torchvision not installed: %s / 没有安装 torch 和 torchvision，请重新运行安装脚本并开启 install_training" % error, "other")
        if args.command == "train":
            train(args)
        else:
            predict(args)
    except TrainFail as error:
        emit("error", message=str(error), kind=error.kind)
        return 1
    except KeyboardInterrupt:
        emit("error", message="interrupted", kind="other")
        return 130
    except Exception as error:                   # noqa: BLE001
        import traceback
        traceback.print_exc()
        emit("error", message="%s: %s" % (type(error).__name__, error), kind="oom" if "out of memory" in str(error).lower() else "other")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
