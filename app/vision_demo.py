# -*- coding: utf-8 -*-
"""合成示例图：没有真实样本时，用程序画出五个场景的演示图片和训练样本。

这些图只是为了装好就能把流程跑通（分割 → 测量 → 规则 → 判定，以及训练一个识别模型），
画得比真实照片干净得多。用在真实场景前，请换成自己拍的图片，并按实际情况调整方案里的参数。

每个场景函数返回 (图像, 标注)。标注是 [{"label": 类别, "bbox": [x, y, w, h]}]，用来裁出训练样本。
"""
import math

import cv2
import numpy as np

W, H = 640, 480


def _rng(seed):
    return np.random.default_rng(int(seed) & 0x7FFFFFFF)


def _noise(rng, shape, sigma):
    return rng.normal(0, sigma, shape).astype(np.float32)


def _smooth_noise(rng, h, w, scale, amp):
    """低频噪声：小图放大得到的平滑起伏。"""
    small = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale))).astype(np.float32)
    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
    return big * amp


def _clip(img):
    return np.clip(img, 0, 255).astype(np.uint8)


def _blend(img, mask, color, alpha=1.0):
    """按 mask（0~1 的浮点图）把 color 混进 img。"""
    m = (mask * alpha)[:, :, None]
    return img * (1 - m) + np.array(color, np.float32)[None, None, :] * m


def _soft_ellipse(h, w, cx, cy, rx, ry, angle=0.0, edge=1.5):
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (int(cx), int(cy)), (max(1, int(rx)), max(1, int(ry))), angle, 0, 360, 255, cv2.FILLED, cv2.LINE_AA)
    out = mask.astype(np.float32) / 255.0
    return cv2.GaussianBlur(out, (0, 0), edge) if edge > 0 else out


def _patch(shape, cx, cy, rx, ry, angle=0.0, edge=1.0):
    """只在椭圆附近的小窗口里画，返回 (窗口内的 0~1 掩膜, x0, y0)。比整幅图画一遍快得多。"""
    h, w = shape[:2]
    reach = int(max(rx, ry) + 3 * edge + 3)
    x0, y0 = max(0, int(cx) - reach), max(0, int(cy) - reach)
    x1, y1 = min(w, int(cx) + reach + 1), min(h, int(cy) + reach + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.ellipse(mask, (int(cx) - x0, int(cy) - y0), (max(1, int(round(rx))), max(1, int(round(ry)))), angle, 0, 360, 255,
                cv2.FILLED, cv2.LINE_AA)
    out = mask.astype(np.float32) / 255.0
    if edge > 0:
        out = cv2.GaussianBlur(out, (0, 0), edge)
    return out, x0, y0


def _paint(img, patch, color, alpha=1.0):
    """把窗口掩膜按 color 混进 img（原地修改），返回这块图形的外接框。"""
    if patch is None:
        return None
    mask, x0, y0 = patch
    h, w = mask.shape
    m = (mask * alpha)[:, :, None]
    view = img[y0:y0 + h, x0:x0 + w]
    view[:] = view * (1 - m) + np.array(color, np.float32)[None, None, :] * m
    box = _bbox_of(mask, 0)
    return [box[0] + x0, box[1] + y0, box[2], box[3]] if box else None


def _union(boxes, pad, shape):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    x0 = max(0, min(b[0] for b in boxes) - pad)
    y0 = max(0, min(b[1] for b in boxes) - pad)
    x1 = min(shape[1], max(b[0] + b[2] for b in boxes) + pad)
    y1 = min(shape[0], max(b[1] + b[3] for b in boxes) + pad)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def _bbox_of(mask, pad=2):
    ys, xs = np.where(mask > 0.3)
    if not len(xs):
        return None
    x0, y0, x1, y1 = xs.min() - pad, ys.min() - pad, xs.max() + pad, ys.max() + pad
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(mask.shape[1] - 1, int(x1)), min(mask.shape[0] - 1, int(y1))
    return [x0, y0, x1 - x0 + 1, y1 - y0 + 1]


# ----------------------------------------------------------------- 水果

FRUIT_VARIANTS = ("ripe", "turning", "unripe", "blemished")


def fruit(variant="ripe", seed=0):
    """枝叶背景前的一个果实（近景）。variant: ripe / turning / unripe / blemished。"""
    rng = _rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = (26, 58, 28)
    for _ in range(70):                          # 叶片：深浅不一的绿色椭圆
        cx, cy = rng.integers(0, W), rng.integers(0, H)
        tone = rng.uniform(0.7, 1.5)
        color = (24 * tone, 62 * tone + rng.uniform(-6, 10), 26 * tone)
        _paint(img, _patch(img.shape, cx, cy, rng.integers(30, 80), rng.integers(12, 30), float(rng.uniform(0, 180)), 1.2), color, 0.9)
    img += _noise(rng, (H, W, 1), 3)

    radius = int(rng.integers(98, 124))
    cx = W // 2 + int(rng.integers(-60, 60))
    cy = H // 2 + int(rng.integers(-25, 30))
    body = _soft_ellipse(H, W, cx, cy, radius, int(radius * rng.uniform(0.9, 0.98)), 0, 1.0)

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    level = {"ripe": 1.45, "blemished": 1.35, "turning": 0.6, "unripe": -0.45}.get(variant, 1.45)
    level += float(rng.uniform(-0.08, 0.08))
    ripeness = level + 0.42 * (yy - cy) / radius + _smooth_noise(rng, H, W, 40, 0.16)
    t = np.clip(ripeness, 0, 1)
    t = t * t * (3 - 2 * t)
    green, orange, red = np.array((118, 202, 168), np.float32), np.array((62, 152, 236), np.float32), np.array((44, 42, 204), np.float32)
    low = np.clip(t * 2, 0, 1)[..., None]
    high = np.clip(t * 2 - 1, 0, 1)[..., None]
    skin = (green * (1 - low) + orange * low) * (1 - high) + red * high

    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
    shade = 0.74 + 0.30 * np.sqrt(np.clip(1 - dist ** 2, 0, 1))
    skin = skin * shade[..., None]
    glint = np.exp(-(((xx - (cx - radius * 0.35)) ** 2 + (yy - (cy - radius * 0.4)) ** 2) / (2 * (radius * 0.16) ** 2)))
    skin = skin + (glint * 38)[..., None]
    img = img * (1 - body[..., None]) + skin * body[..., None]

    stem = np.zeros((H, W), np.uint8)             # 果柄画在果实上方，不压在果面上
    cv2.line(stem, (cx, cy - radius - 2), (cx + int(rng.integers(-14, 14)), cy - radius - 34), 255, 7, cv2.LINE_AA)
    img = _blend(img, stem.astype(np.float32) / 255.0, (30, 78, 40), 1.0)

    spots = 0
    if variant == "blemished":
        spots = int(rng.integers(4, 7))
    elif rng.random() < 0.25:
        spots = 1
    for _ in range(spots):
        ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(0.1, 0.62) * radius
        size = rng.uniform(13, 24) if variant == "blemished" else rng.uniform(4, 7)
        _paint(img, _patch(img.shape, cx + rad * math.cos(ang), cy + rad * math.sin(ang), size, size * rng.uniform(0.6, 1.0),
                           float(rng.uniform(0, 180)), 1.6), (22, 34, 48), 0.95)

    box = _bbox_of(body, 4)
    return _clip(img), [{"label": variant, "bbox": box}]


# ----------------------------------------------------------------- 杂草

WEED_VARIANTS = ("clean", "light", "heavy")


def _plant(rng, canvas, cx, cy, leaves, length, width, color):
    """一株植物：若干片叶子围着中心。返回外接框。"""
    start = rng.uniform(0, 360)
    tone = rng.uniform(0.85, 1.15)
    shade = tuple(c * tone for c in color)
    boxes = []
    for i in range(leaves):
        ang = start + i * 360.0 / leaves + rng.uniform(-18, 18)
        ln = length * rng.uniform(0.7, 1.1)
        ox, oy = cx + math.cos(math.radians(ang)) * ln * 0.55, cy + math.sin(math.radians(ang)) * ln * 0.55
        boxes.append(_paint(canvas, _patch(canvas.shape, ox, oy, ln * 0.6, width, ang, 0.8), shade, 0.97))
    return _union(boxes, 1, canvas.shape)


def weed(variant="light", seed=0):
    """俯视的垄行作物田：四行作物，行间有数量不等的杂草。variant: clean / light / heavy。"""
    rng = _rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = (66, 92, 124)
    img += _smooth_noise(rng, H, W, 24, 9)[..., None]
    img += _noise(rng, (H, W, 1), 7)
    for _ in range(90):                          # 小石子和土块
        x, y, r = rng.integers(0, W), rng.integers(0, H), rng.integers(1, 4)
        tone = rng.uniform(-22, 26)
        cv2.circle(img, (int(x), int(y)), int(r), (66 + tone, 92 + tone, 124 + tone), cv2.FILLED, cv2.LINE_AA)

    notes = []
    rows = [80 + 160 * i + int(rng.integers(-5, 6)) for i in range(4)]
    for rx in rows:
        y = int(rng.integers(8, 30))
        while y < H - 6:
            cx = rx + int(rng.integers(-7, 8))
            box = _plant(rng, img, cx, y, int(rng.integers(5, 8)), rng.uniform(19, 26), rng.uniform(6.5, 9), (38, 148, 58))
            if box:
                notes.append({"label": "crop", "bbox": box})
            y += int(rng.integers(44, 60))

    count = {"clean": int(rng.integers(0, 2)), "light": int(rng.integers(4, 8)), "heavy": int(rng.integers(18, 28))}.get(variant, 5)
    placed = 0
    for _ in range(count * 30):
        if placed >= count:
            break
        cx, cy = int(rng.integers(12, W - 12)), int(rng.integers(12, H - 12))
        if min(abs(cx - rx) for rx in rows) < 44:
            continue
        box = _plant(rng, img, cx, cy, int(rng.integers(3, 6)), rng.uniform(8, 15), rng.uniform(2.2, 3.6), (58, 172, 118))
        if box:
            notes.append({"label": "weed", "bbox": box})
        placed += 1
    return _clip(img), notes


# ----------------------------------------------------------------- 害虫（粘虫板）

PEST_VARIANTS = ("low", "medium", "high")


def _insect(rng, img, kind, cx, cy):
    ang = float(rng.uniform(0, 180))
    if kind == "whitefly":                       # 很小的近圆形虫体
        box = _paint(img, _patch(img.shape, cx, cy, rng.uniform(3.0, 4.2), rng.uniform(2.4, 3.2), ang, 0.6), (34, 36, 38), 0.95)
    elif kind == "thrips":                       # 细长
        box = _paint(img, _patch(img.shape, cx, cy, rng.uniform(7.5, 10), rng.uniform(1.6, 2.2), ang, 0.5), (30, 44, 62), 0.95)
    else:                                        # fly：较大的虫体带两片半透明的翅
        length = rng.uniform(9, 13)
        for side in (-1, 1):
            wx = cx + math.cos(math.radians(ang + side * 38)) * length * 0.75
            wy = cy + math.sin(math.radians(ang + side * 38)) * length * 0.75
            _paint(img, _patch(img.shape, wx, wy, length * 0.85, length * 0.34, ang + side * 38, 0.8), (150, 168, 172), 0.45)
        box = _paint(img, _patch(img.shape, cx, cy, length, length * 0.42, ang, 0.7), (24, 26, 28), 0.97)
    return _union([box], 3, img.shape)


def pest(variant="medium", seed=0):
    """黄色粘虫板。虫子有三种：whitefly（小而圆）、thrips（细长）、fly（大、带翅）。variant: low / medium / high。"""
    rng = _rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = (38, 36, 34)
    board = np.zeros((H, W), np.float32)
    cv2.rectangle(board, (20, 20), (W - 20, H - 20), 1.0, cv2.FILLED)
    yellow = np.zeros((H, W, 3), np.float32)
    yellow[:] = (42, 214, 240)
    yellow += _smooth_noise(rng, H, W, 60, 7)[..., None]
    yellow += _noise(rng, (H, W, 1), 3)
    img = img * (1 - board[..., None]) + yellow * board[..., None]

    total = {"low": int(rng.integers(2, 7)), "medium": int(rng.integers(13, 22)), "high": int(rng.integers(38, 62))}.get(variant, 15)
    notes, centers = [], []
    for _ in range(total * 20):
        if len(notes) >= total:
            break
        cx, cy = int(rng.integers(44, W - 44)), int(rng.integers(44, H - 44))
        if any((cx - a) ** 2 + (cy - b) ** 2 < 30 ** 2 for a, b in centers):
            continue
        kind = rng.choice(["whitefly", "thrips", "fly"], p=[0.55, 0.2, 0.25])
        box = _insect(rng, img, str(kind), cx, cy)
        centers.append((cx, cy))
        if box:
            notes.append({"label": str(kind), "bbox": box})
    return _clip(img), notes


def _place(rng, taken, x0, x1, y0, y1, gap):
    """挑一个和已有缺陷保持距离的位置，免得缺陷叠在一起。"""
    best = None
    for _ in range(40):
        x, y = int(rng.integers(x0, x1)), int(rng.integers(y0, y1))
        near = min([math.hypot(x - a, y - b) for a, b in taken] or [1e9])
        if best is None or near > best[0]:
            best = (near, x, y)
        if near >= gap:
            break
    taken.append((best[1], best[2]))
    return best[1], best[2]


# ----------------------------------------------------------------- 钢管

STEEL_VARIANTS = ("ok", "minor", "reject")


def _blob(rng, h, w, cx, cy, radius, parts=6):
    mask = np.zeros((h, w), np.float32)
    for _ in range(parts):
        ox, oy = rng.uniform(-radius, radius) * 0.6, rng.uniform(-radius, radius) * 0.6
        mask = np.maximum(mask, _soft_ellipse(h, w, cx + ox, cy + oy, radius * rng.uniform(0.45, 0.8), radius * rng.uniform(0.4, 0.75),
                                              float(rng.uniform(0, 180)), 1.5))
    return mask


def steel(variant="minor", seed=0):
    """横放的钢管表面。缺陷：scratch（划痕）、pit（凹坑）、rust（锈斑）。variant: ok / minor / reject。"""
    rng = _rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    top, bottom = 70, 410
    cy, radius = (top + bottom) / 2.0, (bottom - top) / 2.0
    rel = np.clip((yy - cy) / radius, -1, 1)
    gray = 92 + 108 * np.sqrt(1 - rel ** 2)
    gray += 26 * np.exp(-((rel + 0.32) ** 2) / (2 * 0.06 ** 2))          # 一条高光带
    gray += np.repeat(rng.normal(0, 3.2, (H, 1)).astype(np.float32), W, axis=1)   # 沿管轴方向的拉丝纹
    gray += _noise(rng, (H, W), 2.4)
    pipe = ((yy >= top) & (yy <= bottom)).astype(np.float32)
    img = np.stack([gray * 1.02, gray, gray * 0.985], axis=2) * pipe[..., None] + 24 * (1 - pipe[..., None])

    plan = {"ok": [], "minor": ["scratch_short"] + (["pit"] if rng.random() < 0.6 else []),
            "reject": ["scratch_long", "pit", "pit", "rust"] + (["scratch_short"] if rng.random() < 0.5 else [])}.get(variant, [])
    notes, spots = [], []
    for kind in plan:
        cx, y = _place(rng, spots, 90, W - 90, top + 45, bottom - 45, 110)
        if kind.startswith("scratch"):
            length = rng.uniform(150, 240) if kind.endswith("long") else rng.uniform(34, 52)
            ang = math.radians(rng.uniform(-14, 14))
            p0 = (int(cx - math.cos(ang) * length / 2), int(y - math.sin(ang) * length / 2))
            p1 = (int(cx + math.cos(ang) * length / 2), int(y + math.sin(ang) * length / 2))
            line = np.zeros((H, W), np.uint8)
            cv2.line(line, p0, p1, 255, 2, cv2.LINE_AA)
            mask = cv2.GaussianBlur(line.astype(np.float32) / 255.0, (0, 0), 0.7)
            img += (mask * (58 if rng.random() < 0.6 else -52))[..., None]
            label = "scratch"
        elif kind == "pit":
            r = rng.uniform(5, 9)
            mask = _soft_ellipse(H, W, cx, y, r, r * rng.uniform(0.8, 1.0), float(rng.uniform(0, 180)), 1.0)
            rim = _soft_ellipse(H, W, cx - 1, y - 1, r + 2.5, r + 2.5, 0, 1.0) - mask
            img += (np.clip(rim, 0, 1) * 30)[..., None]
            img = img * (1 - 0.68 * mask[..., None])
            label = "pit"
        else:
            mask = _blob(rng, H, W, cx, y, rng.uniform(20, 32))
            speck = 1 + _noise(rng, (H, W), 0.18)
            rust = np.stack([34 * speck, 78 * speck, 152 * speck], axis=2)
            img = img * (1 - 0.82 * mask[..., None]) + rust * (0.82 * mask[..., None])
            label = "rust"
        box = _bbox_of(mask, 3)
        if box:
            notes.append({"label": label, "bbox": box})
    return _clip(img), notes


# ----------------------------------------------------------------- 纺织物

TEXTILE_VARIANTS = ("ok", "minor", "reject")


def textile(variant="minor", seed=0):
    """平纹织物表面。缺陷：hole（破洞）、stain（污渍）、broken_yarn（断纱）、slub（粗节）。variant: ok / minor / reject。"""
    rng = _rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    period = 5.0
    weave = 0.085 * np.sin(2 * math.pi * xx / period) + 0.085 * np.sin(2 * math.pi * yy / period)
    weave += 0.05 * np.sin(2 * math.pi * xx / period) * np.sin(2 * math.pi * yy / period)
    weave += np.repeat(rng.normal(0, 0.012, (1, W)).astype(np.float32), H, axis=0)      # 每根经纱略有粗细差异
    weave += np.repeat(rng.normal(0, 0.012, (H, 1)).astype(np.float32), W, axis=1)
    light = 1 + 0.05 * (xx / W - 0.5) + 0.04 * (yy / H - 0.5)
    base = np.array((152, 126, 98), np.float32)
    img = base[None, None, :] * ((1 + weave) * light)[..., None]
    img += _noise(rng, (H, W, 1), 2.6)

    plan = {"ok": [], "minor": [str(rng.choice(["stain_small", "slub"]))],
            "reject": ["hole", "broken_yarn", "stain"] + (["slub"] if rng.random() < 0.5 else [])}.get(variant, [])
    notes, spots = [], []
    for kind in plan:
        cx, cy = _place(rng, spots, 90, W - 90, 70, H - 70, 130)
        if kind == "hole":
            mask = _blob(rng, H, W, cx, cy, rng.uniform(14, 22), 5)
            mask = np.clip(mask + _noise(rng, (H, W), 0.12) * (mask > 0.05), 0, 1)
            img = img * (1 - 0.8 * mask[..., None]) + 18 * (0.8 * mask[..., None])
            label = "hole"
        elif kind.startswith("stain"):
            r = rng.uniform(16, 22) if kind.endswith("small") else rng.uniform(30, 46)
            mask = _soft_ellipse(H, W, cx, cy, r, r * rng.uniform(0.7, 1.0), float(rng.uniform(0, 180)), r * 0.28)
            img = _blend(img, mask, (62, 112, 150), 0.5)
            label = "stain"
        elif kind == "broken_yarn":
            length = rng.uniform(170, 330)
            horizontal = rng.random() < 0.6
            line = np.zeros((H, W), np.uint8)
            if horizontal:
                cv2.line(line, (int(cx - length / 2), cy), (int(cx + length / 2), cy), 255, 3)
            else:
                cv2.line(line, (cx, int(cy - length / 2.6)), (cx, int(cy + length / 2.6)), 255, 3)
            mask = cv2.GaussianBlur(line.astype(np.float32) / 255.0, (0, 0), 0.6)
            img = img * (1 + 0.34 * mask[..., None])
            label = "broken_yarn"
        else:
            mask = _soft_ellipse(H, W, cx, cy, rng.uniform(14, 20), rng.uniform(3.2, 4.4), 0 if rng.random() < 0.6 else 90, 0.9)
            img = img * (1 + 0.3 * mask[..., None])
            label = "slub"
        box = _bbox_of(mask, 3)
        if box:
            notes.append({"label": label, "bbox": box})
    return _clip(img), notes


# ----------------------------------------------------------------- 统一入口

SCENES = {
    "fruit": (fruit, FRUIT_VARIANTS),
    "weed": (weed, WEED_VARIANTS),
    "pest": (pest, PEST_VARIANTS),
    "steel": (steel, STEEL_VARIANTS),
    "textile": (textile, TEXTILE_VARIANTS),
}


def render(kind, variant=None, seed=0):
    if kind not in SCENES:
        raise ValueError("unknown demo scene '%s'" % kind)
    func, variants = SCENES[kind]
    if variant not in variants:
        variant = variants[int(seed) % len(variants)]
    img, notes = func(variant, seed)
    return img, notes, variant


def crop(img, bbox, pad=0.15, min_side=12):
    x, y, w, h = bbox
    px, py = int(round(w * pad)) + 1, int(round(h * pad)) + 1
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(img.shape[1], x + w + px), min(img.shape[0], y + h + py)
    if x1 - x0 < min_side or y1 - y0 < min_side:
        return None
    return img[y0:y1, x0:x1].copy()


def dataset(kind, per_class=40, seed=1000):
    """为一个场景生成训练样本：{类别: [小图, ...]}，每类 per_class 张，裁自合成的场景图。"""
    if kind not in SCENES:
        raise ValueError("unknown demo scene '%s'" % kind)
    _, variants = SCENES[kind]
    out = {}
    current = int(seed)
    for _ in range(per_class * 60):
        current += 1
        img, notes, _ = render(kind, variants[current % len(variants)], current)
        for note in notes:
            bucket = out.setdefault(note["label"], [])
            if len(bucket) >= per_class:
                continue
            piece = crop(img, note["bbox"])
            if piece is not None:
                bucket.append(piece)
        if out and len(out) >= expected_classes(kind) and all(len(v) >= per_class for v in out.values()):
            break
    return out


def expected_classes(kind):
    return {"fruit": 4, "weed": 2, "pest": 3, "steel": 3, "textile": 4}.get(kind, 2)
