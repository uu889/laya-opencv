# -*- coding: utf-8 -*-
"""视觉核心：按检测方案（recipe）处理一张图，得到测量值和标注图。需要 OpenCV 和 numpy。

方案的 pipeline 是一串步骤，每一步产出一个有名字的结果，后面的步骤和测量值按名字引用它：

  mask      分割出一张掩膜   method: hsv / exg / gray / anomaly / chroma / rows / combine
  regions   从掩膜里取出连通区域，并算出每个区域的面积、长度、圆度等属性
  classify  用「训练」页训练出的模型给区域、整图或网格切块分类
  detect    用检测模型直接得到带类别的框：model = 「视觉训练 → 目标检测」训练出的模型名（torchvision），
            或 model_file = 外部训练好的 YOLO ONNX 文件

测量值写在方案的 measurements 里，每一项的 compute 说明怎么算：
  area_ratio / area / count / sum / max / min / mean / density / mean_channel /
  class_count / class_ratio / top_label / label / input / expr
"""
import ast
import base64
import math
import operator
import os
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 方案里的相对路径以项目目录为准
NET_CACHE = {}
PALETTE = ["#14b8a6", "#e11d48", "#f59e0b", "#3b82f6", "#a855f7", "#84cc16", "#f97316", "#06b6d4"]


class VisionError(Exception):
    pass


class Unavailable(Exception):
    """测量值依赖的东西不存在（例如检测模型文件没放好）：这一项没有值。"""


# ----------------------------------------------------------------- 图像进出

def decode_image(data):
    """接受 bytes、base64 字符串或 data URL，返回 BGR 图像。"""
    if isinstance(data, np.ndarray):
        return data
    if isinstance(data, str):
        text = data.strip()
        if text.startswith("data:"):
            text = text.split(",", 1)[1] if "," in text else ""
        try:
            data = base64.b64decode(text, validate=False)
        except Exception:
            raise VisionError("image is not valid base64")
    if not data:
        raise VisionError("empty image")
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise VisionError("cannot decode the image (supported: JPEG, PNG, BMP, WebP, TIFF)")
    return img


def encode_image(img, fmt=".jpg", quality=88):
    params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)] if fmt == ".jpg" else []
    ok, buf = cv2.imencode(fmt, img, params)
    if not ok:
        raise VisionError("cannot encode the image")
    return buf.tobytes()


def data_url(img, fmt=".jpg", quality=88):
    mime = "image/jpeg" if fmt == ".jpg" else "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(encode_image(img, fmt, quality)).decode("ascii"))


def resize_max(img, max_side):
    h, w = img.shape[:2]
    side = max(h, w)
    if not max_side or side <= max_side:
        return img, 1.0
    factor = float(max_side) / side
    return cv2.resize(img, (max(1, int(round(w * factor))), max(1, int(round(h * factor)))), interpolation=cv2.INTER_AREA), factor


def color_bgr(text, fallback=(166, 184, 20)):
    text = str(text or "").lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        return int(text[4:6], 16), int(text[2:4], 16), int(text[0:2], 16)
    except ValueError:
        return fallback


# ----------------------------------------------------------------- 上下文

class Context:
    def __init__(self, img, recipe, models=None, inputs=None, detectors=None):
        self.img = img
        self.recipe = recipe
        self.h, self.w = img.shape[:2]
        self.masks = {}
        self.regions = {}
        self.labels = {}
        self.classified = set()                # 已经由模型分过类的区域组
        self.detected = set()                  # 由检测模型产出的区域组（标注图上写类别和分数）
        self.unavailable = set()               # 本该由模型产出、但模型不存在的区域组
        self.notes = []
        self.models = models                   # 可调用：models(name) -> 分类器；没有训练模块时为 None
        self.detectors = detectors             # 可调用：detectors(name) -> 检测器（.predict(img, conf, classes)）；没有 torch 时返回 None
        self.inputs = inputs or {}
        self._cache = {}
        cal = recipe.get("calibration") or {}
        self.mm_per_px = float(cal["mm_per_px"]) if _num(cal.get("mm_per_px")) and cal["mm_per_px"] > 0 else None

    def channel(self, name):
        name = str(name or "gray").lower()
        if name not in self._cache:
            if name == "gray":
                self._cache[name] = cv2.cvtColor(self.img, cv2.COLOR_BGR2GRAY)
            elif name in ("h", "s", "v"):
                hsv = cv2.cvtColor(self.img, cv2.COLOR_BGR2HSV)
                for i, key in enumerate("hsv"):
                    self._cache[key] = hsv[:, :, i]
            elif name in ("l", "a", "b"):
                lab = cv2.cvtColor(self.img, cv2.COLOR_BGR2LAB)
                for i, key in enumerate("lab"):
                    self._cache[key] = lab[:, :, i]
            else:
                raise VisionError("unknown channel '%s'" % name)
        return self._cache[name]

    def mask(self, name):
        if name is None:
            return None
        if name not in self.masks:
            raise VisionError("mask '%s' is used before it is defined" % name)
        return self.masks[name]

    def scale_len(self, px):
        return px * self.mm_per_px if self.mm_per_px else px

    def scale_area(self, px2):
        return px2 * self.mm_per_px * self.mm_per_px if self.mm_per_px else px2


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _kernel(size):
    size = max(1, int(round(size)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


# ----------------------------------------------------------------- 分割

def _mask_hsv(ctx, step):
    """ranges: [{"h": [340, 20], "s": [35, 100], "v": [25, 100]}]，色相用 0~360 度，饱和度和亮度用 0~100。"""
    hsv = cv2.cvtColor(ctx.img, cv2.COLOR_BGR2HSV)
    out = np.zeros((ctx.h, ctx.w), np.uint8)
    ranges = step.get("ranges") or []
    if isinstance(ranges, dict):
        ranges = [ranges]
    for item in ranges:
        h0, h1 = item.get("h", [0, 360])
        s0, s1 = item.get("s", [0, 100])
        v0, v1 = item.get("v", [0, 100])
        lo_s, hi_s = int(round(s0 * 2.55)), int(round(s1 * 2.55))
        lo_v, hi_v = int(round(v0 * 2.55)), int(round(v1 * 2.55))
        a = int(round(max(0.0, min(360.0, float(h0))) / 2.0))
        b = min(180, int(round(max(0.0, min(360.0, float(h1))) / 2.0)))
        if h0 <= h1:
            out |= cv2.inRange(hsv, (a, lo_s, lo_v), (b, hi_s, hi_v))
        else:                                   # 跨过 0 度（红色）
            out |= cv2.inRange(hsv, (a, lo_s, lo_v), (180, hi_s, hi_v))
            out |= cv2.inRange(hsv, (0, lo_s, lo_v), (b, hi_s, hi_v))
    return out


def _mask_exg(ctx, step):
    """超绿指数 ExG = 2g - r - b（按 r+g+b 归一化），用来从土壤背景里分出绿色植物。"""
    img = ctx.img.astype(np.float32)
    total = img.sum(axis=2) + 1e-6
    b, g, r = img[:, :, 0] / total, img[:, :, 1] / total, img[:, :, 2] / total
    exg = 2 * g - r - b
    threshold = step.get("threshold", "otsu")
    if threshold == "otsu":
        scaled = np.clip((exg + 1) * 127.5, 0, 255).astype(np.uint8)
        value, out = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        floor = float(step.get("min_threshold", 0.05))
        if value / 127.5 - 1 < floor:           # 画面里几乎没有植物时，大津法会切在噪声上
            out = ((exg > floor) * 255).astype(np.uint8)
        return out
    return ((exg > float(threshold)) * 255).astype(np.uint8)


def _mask_gray(ctx, step):
    ch = ctx.channel(step.get("channel", "gray"))
    if "otsu" in step:
        flag = cv2.THRESH_BINARY_INV if step["otsu"] == "dark" else cv2.THRESH_BINARY
        return cv2.threshold(ch, 0, 255, flag + cv2.THRESH_OTSU)[1]
    out = np.full((ctx.h, ctx.w), 255, np.uint8)
    scale = 2.55 if step.get("percent", True) and step.get("channel", "gray") in ("gray", "s", "v", "l") else 1.0
    if _num(step.get("below")):
        out &= ((ch < step["below"] * scale) * 255).astype(np.uint8)
    if _num(step.get("above")):
        out &= ((ch > step["above"] * scale) * 255).astype(np.uint8)
    return out


def _robust_sigma(values):
    if values.size == 0:
        return 0.0
    median = float(np.median(values))
    return 1.4826 * float(np.median(np.abs(values - median)))


def _mask_anomaly(ctx, step):
    """和局部背景差得多的地方。先用 pre_blur 抹掉细纹理（织物的经纬、拉丝纹），
    再减去背景（默认是大尺度高斯模糊，background="median" 时用大核中值滤波），
    差值超过 k 倍稳健标准差（且超过 min_delta）的算异常。"""
    ch = ctx.channel(step.get("channel", "gray")).astype(np.float32)
    within = ctx.mask(step.get("within")) if step.get("within") else None
    pre = float(step.get("pre_blur", 0))
    if pre > 0:
        ch = cv2.GaussianBlur(ch, (0, 0), pre)
    sigma = float(step.get("sigma", 25))
    if step.get("background") == "median":      # 中值背景：细长或很小的缺陷不会被算进背景，适合有明暗渐变的金属面
        size = int(step.get("ksize", 41)) | 1
        background = cv2.medianBlur(np.clip(ch, 0, 255).astype(np.uint8), size).astype(np.float32)
    elif within is not None:                    # 只在区域内取背景，避免区域外的暗背景把边缘拉低
        weight = (within > 0).astype(np.float32)
        background = cv2.GaussianBlur(ch * weight, (0, 0), sigma) / (cv2.GaussianBlur(weight, (0, 0), sigma) + 1e-6)
    else:
        background = cv2.GaussianBlur(ch, (0, 0), sigma)
    diff = ch - background
    sample = diff[within > 0] if within is not None else diff.ravel()
    spread = _robust_sigma(sample)
    limit = max(float(step.get("k", 5)) * spread, float(step.get("min_delta", 6)))
    polarity = step.get("polarity", "both")
    if polarity == "dark":
        hit = diff < -limit
    elif polarity == "bright":
        hit = diff > limit
    else:
        hit = np.abs(diff) > limit
    return (hit * 255).astype(np.uint8)


def _mask_chroma(ctx, step):
    """颜色偏离主色调的地方（污渍、锈迹）：Lab 的 a、b 离区域中位数的距离超过阈值。"""
    a = ctx.channel("a").astype(np.float32)
    b = ctx.channel("b").astype(np.float32)
    pre = float(step.get("pre_blur", 2))
    if pre > 0:
        a, b = cv2.GaussianBlur(a, (0, 0), pre), cv2.GaussianBlur(b, (0, 0), pre)
    within = ctx.mask(step.get("within")) if step.get("within") else None
    sel = within > 0 if within is not None else np.ones((ctx.h, ctx.w), bool)
    if not sel.any():
        return np.zeros((ctx.h, ctx.w), np.uint8)
    dist = np.sqrt((a - np.median(a[sel])) ** 2 + (b - np.median(b[sel])) ** 2)
    limit = max(float(step.get("k", 6)) * _robust_sigma(dist[sel]), float(step.get("min_delta", 8)))
    return ((dist > limit) * 255).astype(np.uint8)


def _mask_rows(ctx, step):
    """从植被掩膜里找出作物行，返回覆盖各行的条带。行以外的植被就是行间杂草。

    做法：把植被沿行的方向投影成一条曲线，取明显的峰作为行的位置，条带从峰向两侧延伸到曲线回落为止。
    默认行是竖直的；有夹角时用 angle（度，逆时针）先把掩膜转正。
    """
    veg = ctx.mask(step.get("from"))
    angle = float(step.get("angle", 0))
    horizontal = step.get("axis") == "horizontal"
    work = veg
    matrix = None
    if angle:
        matrix = cv2.getRotationMatrix2D((ctx.w / 2.0, ctx.h / 2.0), angle, 1.0)
        work = cv2.warpAffine(veg, matrix, (ctx.w, ctx.h), flags=cv2.INTER_NEAREST)
    profile = (work > 0).sum(axis=1 if horizontal else 0).astype(np.float32)
    length = profile.size
    smooth = max(3, int(length * float(step.get("smooth", 0.02))) | 1)
    profile = cv2.GaussianBlur(profile.reshape(1, -1), (smooth, 1), 0).ravel()
    bands = np.zeros(length, bool)
    peak_max = float(profile.max()) if length else 0.0
    if peak_max > 0:
        min_gap = max(4, int(length * float(step.get("min_spacing", 0.1))))
        floor = peak_max * float(step.get("min_height", 0.35))
        order = np.argsort(-profile)
        peaks = []
        for idx in order:
            if profile[idx] < floor:
                break
            if all(abs(int(idx) - p) >= min_gap for p in peaks):
                left, right = max(0, idx - 1), min(length - 1, idx + 1)
                if profile[idx] >= profile[left] and profile[idx] >= profile[right]:
                    peaks.append(int(idx))
        widen = float(step.get("widen", 1.1))
        edge = float(step.get("edge", 0.12))
        ordered = sorted(peaks)
        for i, p in enumerate(ordered):           # 条带从峰向两侧延伸到曲线降到峰高的 edge 倍为止，但不越过相邻两行的中线
            left_stop = (ordered[i - 1] + p) // 2 if i > 0 else 0
            right_stop = (p + ordered[i + 1]) // 2 if i < len(ordered) - 1 else length - 1
            low = profile[p] * edge
            lo = p
            while lo > left_stop and profile[lo - 1] >= low:
                lo -= 1
            hi = p
            while hi < right_stop and profile[hi + 1] >= low:
                hi += 1
            half = max(hi - p, p - lo, 2) * widen
            bands[max(left_stop, int(p - half)):min(right_stop, int(p + half)) + 1] = True
        ctx.notes.append("rows: %d" % len(peaks))
    out = np.zeros((ctx.h, ctx.w), np.uint8)
    if horizontal:
        out[bands, :] = 255
    else:
        out[:, bands] = 255
    if matrix is not None:
        out = cv2.warpAffine(out, cv2.invertAffineTransform(matrix), (ctx.w, ctx.h), flags=cv2.INTER_NEAREST)
    return out


def _mask_combine(ctx, step):
    names = step.get("of") or []
    if not names:
        raise VisionError("combine needs 'of'")
    kind = step.get("how", "or")
    out = ctx.mask(names[0]).copy()
    if kind == "not":
        return cv2.bitwise_not(out)
    for name in names[1:]:
        other = ctx.mask(name)
        if kind == "and":
            out &= other
        elif kind == "sub":
            out &= cv2.bitwise_not(other)
        else:
            out |= other
    return out


MASK_METHODS = {"hsv": _mask_hsv, "exg": _mask_exg, "gray": _mask_gray, "anomaly": _mask_anomaly,
                "chroma": _mask_chroma, "rows": _mask_rows, "combine": _mask_combine}


def _fill_holes(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, contours, -1, 255, cv2.FILLED)
    return out


def _drop_small(mask, min_area, keep_largest=0):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = areas >= max(1, min_area)
    if keep_largest:
        rank = np.argsort(-areas)[:int(keep_largest)]
        top = np.zeros_like(keep)
        top[rank] = True
        keep &= top
    table = np.zeros(count, np.uint8)
    table[1:][keep] = 255
    return table[labels]


def step_mask(ctx, step):
    method = step.get("method", "hsv")
    if method not in MASK_METHODS:
        raise VisionError("unknown mask method '%s'" % method)
    mask = MASK_METHODS[method](ctx, step)
    if step.get("invert"):
        mask = cv2.bitwise_not(mask)
    if step.get("within") and method not in ("rows",):
        mask &= ctx.mask(step["within"])
    for name in ([step["exclude"]] if isinstance(step.get("exclude"), str) else step.get("exclude") or []):
        mask &= cv2.bitwise_not(ctx.mask(name))
    if step.get("open"):
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _kernel(step["open"]))
    if step.get("close"):
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _kernel(step["close"]))
    if step.get("dilate"):
        mask = cv2.dilate(mask, _kernel(step["dilate"]))
    if step.get("erode"):
        mask = cv2.erode(mask, _kernel(step["erode"]))
    if step.get("fill"):
        mask = _fill_holes(mask)
    if step.get("min_area") or step.get("keep_largest"):
        mask = _drop_small(mask, int(step.get("min_area", 1)), int(step.get("keep_largest", 0)))
    ctx.masks[step["name"]] = mask


# ----------------------------------------------------------------- 区域

OPERATORS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt,
             "==": operator.eq, "!=": operator.ne}


def matches(region, where):
    """where: {"elongation": [">=", 3], "label": "scratch", "area": {"min": 5, "max": 50}}"""
    for key, cond in (where or {}).items():
        value = region.get(key)
        if isinstance(cond, dict):
            if value is None or (_num(cond.get("min")) and value < cond["min"]) or (_num(cond.get("max")) and value > cond["max"]):
                return False
        elif isinstance(cond, (list, tuple)) and len(cond) == 2 and cond[0] in OPERATORS:
            if value is None or not OPERATORS[cond[0]](value, cond[1]):
                return False
        elif isinstance(cond, (list, tuple)):
            if value not in cond:
                return False
        elif value != cond:
            return False
    return True


def region_from_contour(ctx, contour, index):
    area_px = float(cv2.contourArea(contour))
    x, y, w, h = cv2.boundingRect(contour)
    if area_px < 1:
        area_px = float(max(1, len(contour)))
    (cx, cy), (rw, rh), _ = cv2.minAreaRect(contour)
    long_px, short_px = max(rw, rh, 1.0), max(min(rw, rh), 1.0)
    perimeter = float(cv2.arcLength(contour, True))
    hull_area = float(cv2.contourArea(cv2.convexHull(contour))) or area_px
    return {
        "id": index, "bbox": [int(x), int(y), int(w), int(h)], "center": [round(float(cx), 1), round(float(cy), 1)],
        "area_px": round(area_px, 1),
        "area": round(ctx.scale_area(area_px), 3),
        "length": round(ctx.scale_len(long_px), 3),
        "width": round(ctx.scale_len(short_px), 3),
        "diameter": round(ctx.scale_len(math.sqrt(4 * area_px / math.pi)), 3),
        "elongation": round(long_px / short_px, 3),
        "circularity": round(min(1.0, 4 * math.pi * area_px / (perimeter * perimeter)) if perimeter > 0 else 0.0, 3),
        "solidity": round(min(1.0, area_px / hull_area), 3),
    }


def step_regions(ctx, step):
    mask = ctx.mask(step.get("from"))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    regions, kept = [], []
    min_area, max_area = float(step.get("min_area", 4)), step.get("max_area")
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or (_num(max_area) and area > max_area):
            continue
        region = region_from_contour(ctx, contour, len(regions) + 1)
        if not matches(region, step.get("where")):
            continue
        regions.append(region)
        kept.append(contour)
        if len(regions) >= int(step.get("max_count", 300)):
            ctx.notes.append("regions '%s' truncated at %d" % (step["name"], len(regions)))
            break
    ctx.regions[step["name"]] = regions
    ctx._cache["contours:" + step["name"]] = kept
    if step.get("mask"):                         # 可选：把保留下来的区域再存成一张掩膜
        out = np.zeros_like(mask)
        cv2.drawContours(out, kept, -1, 255, cv2.FILLED)
        ctx.masks[step["mask"]] = out


def crop_region(ctx, bbox, pad=0.15):
    x, y, w, h = bbox
    px, py = int(round(w * pad)) + 1, int(round(h * pad)) + 1
    x0, y0, x1, y1 = max(0, x - px), max(0, y - py), min(ctx.w, x + w + px), min(ctx.h, y + h + py)
    return ctx.img[y0:y1, x0:x1]


def step_classify(ctx, step):
    name = step.get("model")
    model = ctx.models(name) if ctx.models else None
    target = str(step.get("on", "image"))
    into = step.get("into") or step.get("name") or name
    if model is None:
        ctx.notes.append("model_missing:%s" % name)
        if target == "tiles":                    # 切块分类没有模型就没有结果：相关测量值记为「没有测到」，而不是 0
            ctx.regions.setdefault(into, [])
            ctx.unavailable.add(into)
        return
    min_prob = float(step.get("min_prob", 0))
    if target == "image":
        label, prob, probs = model.predict([ctx.img])[0]
        ctx.labels[into] = {"label": label, "prob": prob, "probs": probs}
        return
    if target.startswith("regions:"):
        regions = ctx.regions.get(target.split(":", 1)[1])
        if regions is None:
            raise VisionError("classify: regions '%s' are not defined" % target.split(":", 1)[1])
        crops = [crop_region(ctx, r["bbox"], float(step.get("pad", 0.15))) for r in regions]
        ctx.classified.add(target.split(":", 1)[1])
        for region, (label, prob, probs) in zip(regions, model.predict(crops) if crops else []):
            region["label"] = label if prob >= min_prob else step.get("unknown", "unknown")
            region["prob"] = round(prob, 4)
            region["probs"] = probs
        return
    if target == "tiles":
        size = int(step.get("tile", 96))
        stride = int(step.get("stride", size))
        within = ctx.mask(step.get("within")) if step.get("within") else None
        boxes, crops = [], []
        for y in range(0, max(1, ctx.h - size + 1), stride):
            for x in range(0, max(1, ctx.w - size + 1), stride):
                if within is not None and (within[y:y + size, x:x + size] > 0).mean() < float(step.get("min_cover", 0.8)):
                    continue
                boxes.append((x, y))
                crops.append(ctx.img[y:y + size, x:x + size])
        normal = step.get("normal", "normal")
        results = model.predict(crops) if crops else []
        by_label = {}
        for (x, y), (label, prob, _) in zip(boxes, results):
            if label == normal or prob < min_prob:
                continue
            by_label.setdefault(label, np.zeros((ctx.h, ctx.w), np.uint8))[y:y + size, x:x + size] = 255
        regions = []
        combined = np.zeros((ctx.h, ctx.w), np.uint8)
        for label, mask in sorted(by_label.items()):
            combined |= mask
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                region = region_from_contour(ctx, contour, len(regions) + 1)
                region["label"] = label
                regions.append(region)
        ctx.regions[into] = regions
        ctx.classified.add(into)
        ctx.masks[into] = combined
        ctx.labels[into] = {"tiles": len(boxes), "flagged": int(sum(1 for r in results if r[0] != normal))}
        return
    raise VisionError("classify: unknown target '%s'" % target)


def decode_yolo(output, size, classes, conf=0.25, iou=0.45, scale=(1.0, 1.0)):
    """解析 YOLO 系列 ONNX 的输出（v5 的 [N, 5+nc] 和 v8/v11 的 [4+nc, N] 两种排布都认）。"""
    out = np.squeeze(np.asarray(output))
    if out.ndim != 2:
        raise VisionError("unsupported detector output shape %s" % (np.asarray(output).shape,))
    nc = len(classes)
    if out.shape[0] in (4 + nc, 5 + nc) and out.shape[1] not in (4 + nc, 5 + nc):
        out = out.T
    if out.shape[1] == 5 + nc:                   # v5：cx cy w h obj cls...
        scores = out[:, 5:] * out[:, 4:5]
    elif out.shape[1] == 4 + nc:                 # v8：cx cy w h cls...
        scores = out[:, 4:]
    else:
        raise VisionError("detector output has %d columns, expected %d or %d for %d classes" % (out.shape[1], 4 + nc, 5 + nc, nc))
    ids = scores.argmax(axis=1)
    best = scores[np.arange(len(ids)), ids]
    keep = best >= conf
    boxes, best, ids = out[keep, :4], best[keep], ids[keep]
    if not len(boxes):
        return []
    if boxes.max() <= 1.5:                        # 归一化坐标
        boxes = boxes * size
    xywh = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2, boxes[:, 2], boxes[:, 3]], axis=1)
    picked = cv2.dnn.NMSBoxes(xywh.tolist(), best.tolist(), conf, iou)
    found = []
    for i in np.array(picked).reshape(-1):
        x, y, w, h = xywh[i]
        found.append({"bbox": [int(round(x * scale[0])), int(round(y * scale[1])), int(round(w * scale[0])), int(round(h * scale[1]))],
                      "label": classes[int(ids[i])], "prob": round(float(best[i]), 4)})
    return found


def _detect_target(step):
    """结果存到哪个区域组：as: "regions:名字"（契约写法）、into、name，默认 objects。"""
    target = step.get("as") or step.get("into") or step.get("name") or "objects"
    target = str(target)
    return target.split(":", 1)[1] if target.startswith("regions:") else target


def regions_from_boxes(ctx, found, index_from=1):
    """把检测框 [{bbox, label, prob|score}] 变成和分割产出一样结构的区域（矩形轮廓）。"""
    regions = []
    for item in found:
        x, y, w, h = [int(round(v)) for v in item["bbox"]]
        x, y = max(0, min(ctx.w - 1, x)), max(0, min(ctx.h - 1, y))
        w, h = max(1, min(ctx.w - x, w)), max(1, min(ctx.h - y, h))
        contour = np.array([[[x, y]], [[x + w - 1, y]], [[x + w - 1, y + h - 1]], [[x, y + h - 1]]], np.int32)
        region = region_from_contour(ctx, contour, len(regions) + index_from)
        region["bbox"] = [x, y, w, h]
        region["area_px"] = float(w * h)
        region["area"] = round(ctx.scale_area(w * h), 3)
        region["label"] = str(item.get("label", ""))
        prob = item.get("prob", item.get("score"))
        region["prob"] = round(float(prob), 4) if _num(prob) else None
        regions.append(region)
    return regions


def step_detect(ctx, step):
    into = _detect_target(step)
    if step.get("model") and not step.get("model_file"):            # 本项目训练的检测模型（torchvision，惰性加载）
        name = str(step["model"])
        detector = ctx.detectors(name) if ctx.detectors else None
        if detector is None:
            ctx.notes.append("model_missing:%s" % name)
            ctx.regions[into] = []
            ctx.unavailable.add(into)            # 数量不能当成 0：没有检测模型就是没有测
            return
        classes = [str(c) for c in step.get("classes") or []] or None
        found = detector.predict(ctx.img, float(step.get("conf", 0.4)), classes)
        ctx.regions[into] = regions_from_boxes(ctx, found)[:int(step.get("max_count", 300))]
        ctx.classified.add(into)
        ctx.detected.add(into)
        return
    path = str(step.get("model_file") or "")
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.isfile(full):
        ctx.notes.append("onnx_missing:%s" % path)
        ctx.regions[into] = []
        ctx.unavailable.add(into)                # 数量不能当成 0：没有检测模型就是没有测
        return
    key = (full, os.path.getmtime(full))
    net = NET_CACHE.get(key)
    if net is None:
        NET_CACHE.clear()
        net = NET_CACHE[key] = cv2.dnn.readNetFromONNX(full)
    size = int(step.get("size", 640))
    classes = [str(c) for c in step.get("classes") or []]
    if not classes:
        raise VisionError("detect: 'classes' is required (the class names the model was trained with, in order)")
    # 等比缩放后补灰边（letterbox），和 YOLO 系列训练时的预处理一致；"letterbox": false 时直接拉伸
    if step.get("letterbox", True):
        ratio = min(size / float(ctx.w), size / float(ctx.h))
        new_w, new_h = max(1, int(round(ctx.w * ratio))), max(1, int(round(ctx.h * ratio)))
        pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
        canvas = np.full((size, size, 3), 114, np.uint8)
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = cv2.resize(ctx.img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        ratio_x = ratio_y = ratio
    else:
        canvas = cv2.resize(ctx.img, (size, size), interpolation=cv2.INTER_LINEAR)
        pad_x = pad_y = 0
        ratio_x, ratio_y = size / float(ctx.w), size / float(ctx.h)
    blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (size, size), swapRB=True, crop=False)
    net.setInput(blob)
    output = net.forward()
    found = decode_yolo(output, size, classes, float(step.get("conf", 0.25)), float(step.get("iou", 0.45)))
    for item in found:                           # 从模型输入的坐标换回图像坐标
        x, y, w, h = item["bbox"]
        item["bbox"] = [int(round((x - pad_x) / ratio_x)), int(round((y - pad_y) / ratio_y)),
                        int(round(w / ratio_x)), int(round(h / ratio_y))]
    ctx.regions[into] = regions_from_boxes(ctx, found)
    ctx.classified.add(into)
    ctx.detected.add(into)


STEPS = {"mask": step_mask, "regions": step_regions, "classify": step_classify, "detect": step_detect}


# ----------------------------------------------------------------- 测量

_ALLOWED = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round, "sqrt": math.sqrt}


def safe_expr(text, names):
    """只允许四则运算、括号和 min / max / abs / round / sqrt 的算式，变量是其它测量值的名字。"""
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and _num(node.value):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in names or names[node.id] is None:
                raise VisionError("expr: '%s' has no value" % node.id)
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                return 0.0
            return _ALLOWED[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED:
            return _ALLOWED[type(node.op)](walk(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[walk(arg) for arg in node.args])
        raise VisionError("expr: unsupported syntax in '%s'" % text)
    try:
        return float(walk(ast.parse(str(text), mode="eval")))
    except SyntaxError:
        raise VisionError("expr: cannot parse '%s'" % text)


def _area(mask):
    return float(cv2.countNonZero(mask))


def _regions(ctx, comp):
    name = comp.get("regions")
    if name in ctx.unavailable:
        raise Unavailable(name)
    if name not in ctx.regions:
        raise VisionError("measurement uses unknown regions '%s'" % name)
    return [r for r in ctx.regions[name] if matches(r, comp.get("where"))]


def measure_one(ctx, name, comp, values, details):
    kind = comp.get("type")
    if kind == "input":
        value = ctx.inputs.get(name, comp.get("default"))
        return float(value) if _num(value) else value
    if kind in ("area_ratio", "coverage"):
        mask = ctx.mask(comp.get("mask"))
        if comp.get("within"):
            base = ctx.mask(comp["within"])
            total = _area(base)
            return 100.0 * _area(mask & base) / total if total else 0.0
        return 100.0 * _area(mask) / float(ctx.w * ctx.h)
    if kind == "area":
        return ctx.scale_area(_area(ctx.mask(comp.get("mask"))))
    if kind == "count":
        return float(len(_regions(ctx, comp)))
    if kind in ("sum", "max", "min", "mean"):
        attr = comp.get("attr", "area")
        items = [r[attr] for r in _regions(ctx, comp) if _num(r.get(attr))]
        if not items:
            return 0.0
        return float({"sum": sum, "max": max, "min": min, "mean": lambda xs: sum(xs) / len(xs)}[kind](items))
    if kind == "density":
        count = len(_regions(ctx, comp))
        per = comp.get("per", "m2")
        if per == "image" or not ctx.mm_per_px:
            return float(count)
        if comp.get("within"):
            area_mm2 = ctx.scale_area(_area(ctx.mask(comp["within"])))
        else:
            area_mm2 = ctx.scale_area(ctx.w * ctx.h)
        unit = {"m2": 1e6, "dm2": 1e4, "cm2": 1e2}.get(per, 1e6)
        return count / (area_mm2 / unit) if area_mm2 else 0.0
    if kind == "mean_channel":
        ch = ctx.channel(comp.get("channel", "gray"))
        mask = ctx.mask(comp["mask"]) if comp.get("mask") else None
        sel = ch[mask > 0] if mask is not None else ch.ravel()
        if sel.size == 0:
            return 0.0
        value = float(sel.mean())
        if comp.get("channel", "gray") == "h":
            return value * 2.0
        return value / 2.55 if comp.get("channel", "gray") in ("gray", "s", "v", "l") else value
    if kind in ("class_count", "class_ratio", "top_label") and comp.get("regions") not in ctx.classified:
        return None                              # 还没有识别模型：这一项没有值，而不是 0
    if kind in ("class_count", "class_ratio"):
        regions = _regions(ctx, comp)
        hit = [r for r in regions if r.get("label") == comp.get("label")]
        if kind == "class_count":
            return float(len(hit))
        return 100.0 * len(hit) / len(regions) if regions else 0.0
    if kind == "top_label":
        regions = [r for r in _regions(ctx, comp) if r.get("label")]
        if not regions:
            return comp.get("empty")
        counts = {}
        for r in regions:
            counts[r["label"]] = counts.get(r["label"], 0) + 1
        label = max(counts, key=counts.get)
        probs = [r["prob"] for r in regions if r["label"] == label and _num(r.get("prob"))]
        details[name] = {"counts": counts, "prob": round(sum(probs) / len(probs), 4) if probs else None}
        return label
    if kind == "label":
        got = ctx.labels.get(comp.get("from"))
        if not got or "label" not in got:
            return comp.get("empty")
        details[name] = {"prob": got.get("prob"), "probs": got.get("probs")}
        return got["label"]
    if kind == "expr":
        return safe_expr(comp.get("expr", "0"), values)
    raise VisionError("measurement '%s' has unknown type '%s'" % (name, kind))


def quality_metrics(ctx):
    gray = ctx.channel("gray")
    return {"_sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
            "_brightness": round(float(gray.mean()), 2)}


# ----------------------------------------------------------------- 标注图

def annotate(ctx):
    recipe = ctx.recipe
    canvas = ctx.img.copy()
    draw = recipe.get("draw")
    if not isinstance(draw, list):
        draw = [{"regions": name} for name in ctx.regions]
    thick = max(1, int(round(max(ctx.w, ctx.h) / 500.0)))
    font_scale = max(0.4, max(ctx.w, ctx.h) / 1400.0)
    legend = []
    for index, item in enumerate(draw):
        color = color_bgr(item.get("color") or PALETTE[index % len(PALETTE)])
        if item.get("mask") and item["mask"] in ctx.masks:
            mask = ctx.masks[item["mask"]]
            alpha = float(item.get("alpha", 0.35))
            if alpha > 0:
                tint = np.zeros_like(canvas)
                tint[:] = color
                blended = cv2.addWeighted(canvas, 1 - alpha, tint, alpha, 0)
                canvas[mask > 0] = blended[mask > 0]
            if item.get("outline", True):
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(canvas, contours, -1, color, thick)
            legend.append({"name": item["mask"], "label": item.get("label") or item["mask"], "color": "#%02x%02x%02x" % color[::-1], "kind": "mask"})
        if item.get("regions") and item["regions"] in ctx.regions:
            colors = item.get("colors") or {}
            for region in ctx.regions[item["regions"]]:
                x, y, w, h = region["bbox"]
                c = color_bgr(colors.get(region.get("label")), color) if region.get("label") else color
                cv2.rectangle(canvas, (x, y), (x + w, y + h), c, thick)
                if item.get("number", True):
                    text = str(region["id"])
                    if item.get("show_label", True) and region.get("label") and item["regions"] in ctx.detected:
                        text += " " + str(region["label"]) + ("" if region.get("prob") is None else " %.2f" % region["prob"])
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
                    ty = y - 3 if y - th - 4 > 0 else y + h + th + 3
                    cv2.rectangle(canvas, (x, ty - th - 2), (x + tw + 4, ty + 2), c, cv2.FILLED)
                    cv2.putText(canvas, text, (x + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), thick, cv2.LINE_AA)
            legend.append({"name": item["regions"], "label": item.get("label") or item["regions"], "color": "#%02x%02x%02x" % color[::-1],
                           "kind": "regions", "colors": colors})
    return canvas, legend


# ----------------------------------------------------------------- 入口

def analyze(recipe, image, models=None, inputs=None, want_image=True, detectors=None):
    """按方案处理一张图。返回测量值、区域列表、标注图和处理说明。

    models(name) 给出「区域分类」模型，detectors(name) 给出「目标检测」模型；都可以不传。"""
    started = time.time()
    img = decode_image(image)
    img, factor = resize_max(img, int(recipe.get("max_side", 1280)))
    ctx = Context(img, recipe, models, inputs, detectors)
    if ctx.mm_per_px and factor != 1.0:          # 图被缩小了：每个像素代表的毫米数相应变大
        ctx.mm_per_px = ctx.mm_per_px / factor
    for index, step in enumerate(recipe.get("pipeline") or []):
        if not isinstance(step, dict):
            raise VisionError("pipeline step %d must be an object" % (index + 1))
        op = step.get("op")
        if op not in STEPS:
            raise VisionError("pipeline step %d: unknown op '%s'" % (index + 1, op))
        if op in ("mask", "regions") and not step.get("name"):
            raise VisionError("pipeline step %d (%s) needs a 'name'" % (index + 1, op))
        try:
            STEPS[op](ctx, step)
        except VisionError:
            raise
        except cv2.error as error:
            raise VisionError("pipeline step %d (%s): %s" % (index + 1, op, str(error).strip().splitlines()[-1]))

    values, details = dict(quality_metrics(ctx)), {}
    if ctx.mm_per_px:
        values["_area_m2"] = round(ctx.scale_area(ctx.w * ctx.h) / 1e6, 6)
    specs = recipe.get("measurements") or {}
    pending = [name for name, spec in specs.items() if isinstance(spec, dict) and isinstance(spec.get("compute"), dict)]
    for _ in range(3):                           # expr 可以引用排在后面的测量值，多算几轮
        later = []
        for name in pending:
            comp = specs[name]["compute"]
            try:
                value = measure_one(ctx, name, comp, values, details)
            except Unavailable:
                value = None
            except VisionError as error:
                if comp.get("type") == "expr" and "has no value" in str(error):
                    later.append(name)
                    continue
                raise
            if _num(value):
                value = round(float(value), max(0, min(6, int(specs[name].get("decimals", 2)))))
            values[name] = value
        if not later or len(later) == len(pending):
            for name in later:
                values[name] = None
            break
        pending = later

    out = {"width": ctx.w, "height": ctx.h, "mm_per_px": ctx.mm_per_px, "values": values, "details": details,
           "regions": {name: [{k: v for k, v in r.items() if k != "probs"} for r in items[:200]] for name, items in ctx.regions.items()},
           "labels": ctx.labels, "notes": ctx.notes}
    if want_image:
        canvas, legend = annotate(ctx)
        out["annotated"] = data_url(canvas)
        out["legend"] = legend
    out["ms"] = round((time.time() - started) * 1000, 1)
    return out
