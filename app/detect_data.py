# -*- coding: utf-8 -*-
"""目标检测的数据集存取和模型查找。只依赖 OpenCV + numpy（标准库之外）；torch 只在真正推理时按需导入。

目录（在 LAYA_WB_DATA 下）：
  det/datasets/<name>/images/*.jpg      图片
  det/datasets/<name>/labels/*.txt      YOLO 格式标注，每行 `class_id cx cy w h`（归一化 0~1）
  det/datasets/<name>/classes.json      ["类别0", "类别1", ...]
  det/models/<name>/model.pt + meta.json   由 detect_train.py 训练得到

对外的框一律用像素坐标 [x, y, w, h]，读写文件时在这里换成 YOLO 的归一化中心坐标。
"""
import importlib.util
import json
import os
import shutil
import threading
import time

import cv2

import vision_core
import vision_demo
from vision_train import DATA, TrainError, read_image, safe_name, write_image

DET = os.path.join(DATA, "det")
DET_DATASETS = os.path.join(DET, "datasets")
DET_MODELS = os.path.join(DET, "models")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

_SEQ = [0]
_SEQ_LOCK = threading.Lock()


# ----------------------------------------------------------------- 路径

def dataset_dir(name, must_exist=False):
    name = safe_name(name)
    if not name:
        raise TrainError("dataset name is required")
    folder = os.path.join(DET_DATASETS, name)
    if must_exist and not os.path.isdir(folder):
        raise TrainError("detection dataset '%s' does not exist" % name)
    return folder


def _file_in(folder, sub, filename):
    path = os.path.join(folder, sub, os.path.basename(str(filename or "")))
    if not os.path.abspath(path).startswith(os.path.abspath(os.path.join(folder, sub)) + os.sep):
        raise TrainError("bad path")
    return path


def _label_path(folder, filename):
    return _file_in(folder, "labels", os.path.splitext(os.path.basename(str(filename)))[0] + ".txt")


def read_classes(folder):
    path = os.path.join(folder, "classes.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [str(c) for c in data] if isinstance(data, list) else []


def write_classes(folder, classes):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "classes.json"), "w", encoding="utf-8") as handle:
        json.dump([str(c) for c in classes], handle, ensure_ascii=False, indent=2)


def _clean_classes(classes):
    out = []
    for item in classes or []:
        label = safe_name(item)
        if label and label not in out:
            out.append(label)
    return out


# ----------------------------------------------------------------- YOLO 读写

def boxes_to_yolo(boxes, size, classes, add_classes=True):
    """像素框 [{label, bbox:[x,y,w,h]}] → YOLO 文本行。遇到没见过的类别时追加到 classes（原地修改）。"""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    lines = []
    for item in boxes or []:
        if not isinstance(item, dict) or not isinstance(item.get("bbox"), (list, tuple)) or len(item["bbox"]) < 4:
            continue
        label = safe_name(item.get("label"))
        if not label:
            continue
        if label not in classes:
            if not add_classes:
                continue
            classes.append(label)
        x, y, w, h = [float(v) for v in item["bbox"][:4]]
        x0, y0 = max(0.0, min(width, x)), max(0.0, min(height, y))
        x1, y1 = max(0.0, min(width, x + w)), max(0.0, min(height, y + h))
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        lines.append("%d %.6f %.6f %.6f %.6f" % (classes.index(label), (x0 + x1) / 2.0 / width, (y0 + y1) / 2.0 / height,
                                                (x1 - x0) / width, (y1 - y0) / height))
    return lines


def yolo_to_boxes(text, size, classes):
    """YOLO 文本 → 像素框 [{label, bbox:[x,y,w,h]}]。"""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    out = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cid = int(float(parts[0]))
            cx, cy, w, h = [float(v) for v in parts[1:5]]
        except ValueError:
            continue
        label = classes[cid] if 0 <= cid < len(classes) else str(cid)
        x0, y0 = (cx - w / 2.0) * width, (cy - h / 2.0) * height
        x1, y1 = (cx + w / 2.0) * width, (cy + h / 2.0) * height
        x0, y0 = int(round(max(0.0, x0))), int(round(max(0.0, y0)))
        x1, y1 = int(round(min(width, x1))), int(round(min(height, y1)))
        out.append({"label": label, "bbox": [x0, y0, max(1, x1 - x0), max(1, y1 - y0)]})
    return out


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _image_size(path):
    """只读尺寸：解码一次。图片不大（训练用），直接解码即可。"""
    img = read_image(path)
    return None if img is None else (int(img.shape[1]), int(img.shape[0]))


# ----------------------------------------------------------------- 数据集

def create(name, classes=None):
    folder = dataset_dir(name)
    os.makedirs(os.path.join(folder, "images"), exist_ok=True)
    os.makedirs(os.path.join(folder, "labels"), exist_ok=True)
    existing = read_classes(folder)
    for label in _clean_classes(classes):
        if label not in existing:
            existing.append(label)
    write_classes(folder, existing)
    return describe(os.path.basename(folder))


def _image_files(folder):
    sub = os.path.join(folder, "images")
    if not os.path.isdir(sub):
        return []
    return sorted(f for f in os.listdir(sub) if f.lower().endswith(IMAGE_EXT))


def describe(name):
    folder = dataset_dir(name, must_exist=True)
    files = _image_files(folder)
    boxes = 0
    for filename in files:
        boxes += sum(1 for line in _read_text(_label_path(folder, filename)).splitlines() if len(line.split()) >= 5)
    return {"name": os.path.basename(folder), "images": len(files), "boxes": boxes, "classes": read_classes(folder)}


def list_datasets():
    out = []
    if not os.path.isdir(DET_DATASETS):
        return out
    for name in sorted(os.listdir(DET_DATASETS)):
        if os.path.isdir(os.path.join(DET_DATASETS, name)):
            try:
                out.append(describe(name))
            except TrainError:
                continue
    return out


def add_image(name, img, boxes, ext=None):
    """存一张图和它的标注（像素框）。返回 {file, size, boxes, classes}。"""
    if img is None or getattr(img, "size", 0) == 0:
        raise TrainError("empty image")
    folder = dataset_dir(name)
    if not os.path.isdir(folder):
        create(name)
    classes = read_classes(folder)
    height, width = img.shape[:2]
    lines = boxes_to_yolo(boxes, (width, height), classes)
    with _SEQ_LOCK:
        _SEQ[0] += 1
        seq = _SEQ[0]
    kind = ext or (".png" if max(width, height) <= 320 else ".jpg")
    filename = "%d_%04d%s" % (int(time.time() * 1000), seq % 10000, kind)
    write_image(os.path.join(folder, "images", filename), img)
    os.makedirs(os.path.join(folder, "labels"), exist_ok=True)
    with open(_label_path(folder, filename), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + ("\n" if lines else ""))
    write_classes(folder, classes)
    return {"file": filename, "size": [int(width), int(height)], "boxes": yolo_to_boxes("\n".join(lines), (width, height), classes),
            "classes": classes}


def set_labels(name, filename, boxes):
    """改一张图的标注。"""
    folder = dataset_dir(name, must_exist=True)
    path = _file_in(folder, "images", filename)
    size = _image_size(path)
    if size is None:
        raise TrainError("image '%s' not found in dataset '%s'" % (filename, name))
    classes = read_classes(folder)
    lines = boxes_to_yolo(boxes, size, classes)
    with open(_label_path(folder, filename), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + ("\n" if lines else ""))
    write_classes(folder, classes)
    return {"file": os.path.basename(path), "size": list(size), "boxes": yolo_to_boxes("\n".join(lines), size, classes), "classes": classes}


def items(name, offset=0, limit=60):
    folder = dataset_dir(name, must_exist=True)
    files = _image_files(folder)
    classes = read_classes(folder)
    offset, limit = max(0, int(offset or 0)), max(1, min(500, int(limit or 60)))
    out = []
    for filename in files[offset:offset + limit]:
        size = _image_size(os.path.join(folder, "images", filename))
        if size is None:
            continue
        out.append({"file": filename, "size": list(size), "boxes": yolo_to_boxes(_read_text(_label_path(folder, filename)), size, classes)})
    return {"name": os.path.basename(folder), "total": len(files), "offset": offset, "items": out, "classes": classes}


def image_bytes(name, filename, thumb=0):
    folder = dataset_dir(name, must_exist=True)
    path = _file_in(folder, "images", filename)
    if not os.path.isfile(path):
        return None, None
    if not thumb:
        with open(path, "rb") as handle:
            data = handle.read()
        ext = os.path.splitext(path)[1].lower()
        return data, {".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp"}.get(ext, "image/jpeg")
    img = read_image(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    factor = float(thumb) / max(h, w)
    if factor < 1:
        img = cv2.resize(img, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes(), "image/jpeg"


def delete(name, filename=None):
    folder = dataset_dir(name)
    if not os.path.abspath(folder).startswith(os.path.abspath(DET_DATASETS) + os.sep):
        raise TrainError("bad path")
    if filename is None:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        return
    for path in (_file_in(folder, "images", filename), _label_path(folder, filename)):
        if os.path.isfile(path):
            os.remove(path)


# ----------------------------------------------------------------- 合成样本 / 预标注

def make_demo(scene, name, count=40, seed=1000, progress=None):
    """用合成场景图做一个检测数据集：场景函数本来就返回每个目标的框，直接存成标注。"""
    if scene not in vision_demo.SCENES:
        raise TrainError("unknown scene '%s'" % scene)
    _, variants = vision_demo.SCENES[scene]
    count = max(1, min(2000, int(count or 40)))
    delete(name)                                 # 重新生成时先清空
    rendered = []
    labels = set()
    for i in range(count):
        current = int(seed) + i
        img, notes, _ = vision_demo.render(scene, variants[current % len(variants)], current)
        boxes = [{"label": n["label"], "bbox": n["bbox"]} for n in notes if n.get("bbox")]
        labels.update(b["label"] for b in boxes)
        rendered.append((img, boxes))
        if progress:
            progress("generate", 0.5 * (i + 1) / count)
    create(name, sorted(labels))                 # 类别顺序固定，和图片顺序无关
    for i, (img, boxes) in enumerate(rendered):
        add_image(name, img, boxes, ".jpg")
        if progress:
            progress("save", 0.5 + 0.5 * (i + 1) / count)
    return describe(name)


def find_recipe(recipe):
    """接受方案对象，或方案 id（在 recipes/ 下查找）。"""
    if isinstance(recipe, dict):
        return recipe
    wanted = str(recipe or "").strip()
    if not wanted:
        raise TrainError("'recipe' is required")
    base = os.path.join(vision_core.ROOT, "recipes")
    for sub in ("zh", "en", ""):
        folder = os.path.join(base, sub)
        if not os.path.isdir(folder):
            continue
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, filename), encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("id") == wanted:
                return data
    raise TrainError("recipe '%s' not found" % wanted)


def prelabel(name, filename, recipe, models=None, detectors=None):
    """用方案的分割 / 识别步骤给一张图生成候选框（不落盘，由用户确认后再保存）。"""
    folder = dataset_dir(name, must_exist=True)
    img = read_image(_file_in(folder, "images", filename))
    if img is None:
        raise TrainError("image '%s' not found in dataset '%s'" % (filename, name))
    recipe = dict(find_recipe(recipe))
    recipe["max_side"] = max(img.shape[:2])      # 不缩放，框的坐标直接对应原图
    result = vision_core.analyze(recipe, img, models=models, detectors=detectors, want_image=False)
    boxes = []
    for group, regions in result["regions"].items():
        for region in regions:
            boxes.append({"label": region.get("label") or group, "bbox": [int(v) for v in region["bbox"]], "group": group})
    return {"file": os.path.basename(filename), "size": [int(img.shape[1]), int(img.shape[0])], "boxes": boxes, "notes": result["notes"]}


# ----------------------------------------------------------------- 模型

def torch_available():
    """不导入 torch（启动要快），只看包装了没有。返回 (可用, 原因, torch 版本, torchvision 版本)。"""
    if os.environ.get("LAYA_WB_NO_TORCH"):
        return False, "LAYA_WB_NO_TORCH is set (test only)", None, None
    missing = [name for name in ("torch", "torchvision") if importlib.util.find_spec(name) is None]
    if missing:
        return False, "%s not installed" % " and ".join(missing), None, None
    versions = []
    for name in ("torch", "torchvision"):
        try:
            from importlib.metadata import version
            versions.append(version(name))
        except Exception:
            versions.append("?")
    return True, None, versions[0], versions[1]


def detect_info():
    ok, reason, torch_v, tv_v = torch_available()
    return {"available": ok, "reason": reason, "torch": torch_v, "torchvision": tv_v}


def list_models():
    out = []
    if not os.path.isdir(DET_MODELS):
        return out
    for name in sorted(os.listdir(DET_MODELS)):
        path = os.path.join(DET_MODELS, name, "meta.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    meta = json.load(handle)
            except (OSError, ValueError):
                continue
            meta["name"] = name
            meta["size_mb"] = round(sum(os.path.getsize(os.path.join(DET_MODELS, name, f)) for f in os.listdir(os.path.join(DET_MODELS, name))) / 1048576.0, 1)
            out.append(meta)
    return out


def model_dir(name):
    name = safe_name(name)
    return os.path.join(DET_MODELS, name) if name else ""


def delete_model(name):
    folder = model_dir(name)
    if folder and os.path.isdir(folder) and os.path.abspath(folder).startswith(os.path.abspath(DET_MODELS) + os.sep):
        shutil.rmtree(folder)
    with _CACHE_LOCK:
        _CACHE.pop(os.path.basename(folder), None)


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def get_detector(name):
    """按名字取检测模型（惰性加载 torch）。模型没训练过、或没装 torch → None（方案里记 model_missing）。"""
    folder = model_dir(name)
    meta = os.path.join(folder, "meta.json")
    if not folder or not os.path.isfile(meta) or not os.path.isfile(os.path.join(folder, "model.pt")):
        return None
    if not torch_available()[0]:
        return None
    stamp = os.path.getmtime(meta)
    with _CACHE_LOCK:
        hit = _CACHE.get(os.path.basename(folder))
        if hit and hit[0] == stamp:
            return hit[1]
        import detect_train
        model = detect_train.Detector(folder)
        _CACHE.clear()                           # 一次只缓存一个，省内存
        _CACHE[os.path.basename(folder)] = (stamp, model)
        return model


def draw_boxes(img, boxes):
    """把检测框画到图上（带类别和分数）。"""
    canvas = img.copy()
    thick = max(1, int(round(max(canvas.shape[:2]) / 500.0)))
    scale = max(0.4, max(canvas.shape[:2]) / 1400.0)
    for i, item in enumerate(boxes):
        x, y, w, h = [int(v) for v in item["bbox"]]
        color = vision_core.color_bgr(vision_core.PALETTE[i % len(vision_core.PALETTE)])
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, thick)
        text = "%s %.2f" % (item.get("label", ""), float(item.get("score", item.get("prob", 0)) or 0))
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        ty = y - 3 if y - th - 4 > 0 else y + h + th + 3
        cv2.rectangle(canvas, (x, ty - th - 2), (x + tw + 4, ty + 2), color, cv2.FILLED)
        cv2.putText(canvas, text, (x + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return canvas

