# -*- coding: utf-8 -*-
"""视觉服务：把 OpenCV 的分析和训练做成本机 HTTP 接口，由启动器拉起并转发。

只监听本机地址。除了 OpenCV 和 numpy 没有别的依赖（HTTP 用标准库）。

  GET  /v1/vision/health                 版本、是否带 cv2.ml、骨干网络是否就绪
  GET  /v1/vision/demo                   合成示例图   ?scene=fruit&variant=ripe&seed=3
  POST /v1/vision/analyze                按检测方案分析一张图   {recipe, image, inputs}
  GET  /v1/vision/datasets               数据集列表
  POST /v1/vision/datasets/add           往某个类别里加图   {dataset, label, images: [dataURL]}
  POST /v1/vision/datasets/add_regions   把一张图里的若干个框裁出来加进类别   {dataset, label, image, boxes, max_side}
  POST /v1/vision/datasets/delete        删除数据集 / 类别 / 单张图   {dataset, label?, file?}
  GET  /v1/vision/datasets/thumb         缩略图   ?dataset=&label=&file=
  POST /v1/vision/datasets/demo          生成合成训练样本（后台任务）   {scene, dataset, per_class}
  POST /v1/vision/train                  训练（后台任务）   {dataset, name, features, algo, augment, rotate}
  POST /v1/vision/demo/prepare           一步到位：生成合成样本并训练（后台任务）   {scene, model, features, algo}
  POST /v1/vision/backbone/download      下载预训练骨干网络（后台任务）
  GET  /v1/vision/jobs                   后台任务进度   ?id=
  GET  /v1/vision/models                 模型列表
  POST /v1/vision/models/delete          删除模型   {name}
  POST /v1/vision/predict                用模型给一张图分类   {model, image}
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import cv2
    import numpy as np
except ImportError as error:                     # 没装视觉组件：让启动器知道原因
    print("[vision] OpenCV / numpy not installed: %s" % error)
    raise SystemExit(3)

import vision_core  # noqa: E402
import vision_demo  # noqa: E402
import vision_train  # noqa: E402

MAX_BODY = 96 * 1024 * 1024
JOBS = {}
JOBS_LOCK = threading.Lock()
WORK_LOCK = threading.Lock()                     # 训练和生成样本一次只跑一个
ANALYZE_LOCK = threading.Lock()
JOB_SEQ = [0]


class ApiError(Exception):
    def __init__(self, status, detail):
        Exception.__init__(self, detail)
        self.status = status
        self.detail = detail


# ----------------------------------------------------------------- 后台任务

def start_job(kind, func):
    with JOBS_LOCK:
        JOB_SEQ[0] += 1
        job_id = "%s-%d" % (kind, JOB_SEQ[0])
        job = {"id": job_id, "kind": kind, "state": "queued", "stage": "", "progress": 0.0, "error": None,
               "result": None, "started": time.time(), "seconds": 0.0}
        JOBS[job_id] = job
        for old in sorted(JOBS, key=lambda k: JOBS[k]["started"])[:-30]:      # 只保留最近 30 个
            JOBS.pop(old, None)

    def progress(stage, done):
        job["stage"], job["progress"] = stage, round(float(done), 3)
        job["seconds"] = round(time.time() - job["started"], 1)

    def runner():
        with WORK_LOCK:
            job["state"] = "running"
            try:
                job["result"] = func(progress)
                job["state"] = "done"
                job["progress"] = 1.0
            except (vision_train.TrainError, vision_core.VisionError, ValueError) as error:
                job["state"], job["error"] = "error", str(error)
            except Exception as error:              # 没预料到的错误：留下堆栈方便排查
                traceback.print_exc()
                job["state"], job["error"] = "error", "%s: %s" % (type(error).__name__, error)
            job["seconds"] = round(time.time() - job["started"], 1)

    threading.Thread(target=runner, daemon=True).start()
    return job


def make_demo_dataset(scene, dataset, per_class, progress):
    progress("generate", 0.0)
    samples = vision_demo.dataset(scene, per_class)
    vision_train.delete_item(dataset)               # 重新生成时先清空，避免新旧样本混在一起
    total = sum(len(v) for v in samples.values()) or 1
    done = 0
    for label, images in samples.items():
        vision_train.add_images(dataset, label, images)
        done += len(images)
        progress("generate", done / float(total))
    return {"dataset": dataset, "classes": {label: len(images) for label, images in samples.items()}}


def backbone_urls():
    text = os.environ.get("LAYA_WB_BACKBONE_URLS", "").strip()
    return [u for u in text.split(",") if u.strip()] or None


# ----------------------------------------------------------------- 接口实现

def health():
    return {"status": "ok", "opencv": cv2.__version__, "has_ml": vision_train.HAS_ML, "backbone": vision_train.backbone_info(),
            "features": list(vision_train.FEATURES), "algos": list(vision_train.ALGOS),
            "scenes": {name: list(item[1]) for name, item in vision_demo.SCENES.items()}}


def api_analyze(body):
    recipe = body.get("recipe")
    if not isinstance(recipe, dict):
        raise ApiError(400, "'recipe' must be an object")
    if not body.get("image"):
        raise ApiError(400, "'image' is required")
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
    with ANALYZE_LOCK:
        return vision_core.analyze(recipe, body["image"], models=vision_train.get_model, inputs=inputs,
                                   want_image=body.get("annotate", True))


def api_add(body):
    images = body.get("images")
    if not isinstance(images, list) or not images:
        raise ApiError(400, "'images' must be a non-empty list")
    decoded = [vision_core.decode_image(item) for item in images]
    saved = vision_train.add_images(body.get("dataset"), body.get("label"), decoded)
    return {"saved": saved, "datasets": vision_train.list_datasets()}


def api_add_regions(body):
    boxes = body.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        raise ApiError(400, "'boxes' must be a non-empty list of [x, y, w, h]")
    img = vision_core.decode_image(body.get("image"))
    img, _ = vision_core.resize_max(img, int(body.get("max_side") or 1280))    # 和分析时用同一个尺寸，框的坐标才对得上
    pad = float(body.get("pad", 0.15))
    crops = []
    for box in boxes:
        x, y, w, h = [int(v) for v in box[:4]]
        px, py = int(round(w * pad)) + 1, int(round(h * pad)) + 1
        piece = img[max(0, y - py):min(img.shape[0], y + h + py), max(0, x - px):min(img.shape[1], x + w + px)]
        if piece.size:
            crops.append(piece.copy())
    saved = vision_train.add_images(body.get("dataset"), body.get("label"), crops)
    return {"saved": saved, "datasets": vision_train.list_datasets()}


def api_predict(body):
    model = vision_train.get_model(body.get("model"))
    if model is None:
        raise ApiError(404, "model '%s' has not been trained" % body.get("model"))
    label, prob, probs = model.predict([vision_core.decode_image(body.get("image"))])[0]
    return {"label": label, "prob": round(prob, 4), "probs": probs}


def api_train(body):
    dataset, name = body.get("dataset"), body.get("name") or body.get("dataset")
    features = body.get("features") or ["color", "texture", "shape"]
    algo = body.get("algo") or "svm"
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    def work(progress):
        return vision_train.train(dataset, name, features, algo, int(body.get("folds", 5)), bool(body.get("augment", True)),
                                  bool(body.get("rotate", False)), params, progress)
    return start_job("train", work)


def api_prepare(body):
    scene = body.get("scene")
    if scene not in vision_demo.SCENES:
        raise ApiError(400, "unknown scene '%s'" % scene)
    model = body.get("model") or ("demo-" + scene)
    dataset = body.get("dataset") or ("demo-" + scene)
    features = body.get("features") or ["color", "texture", "shape"]
    algo = body.get("algo") or "svm"
    per_class = int(body.get("per_class", 40))

    def work(progress):
        made = make_demo_dataset(scene, dataset, per_class, lambda stage, done: progress(stage, done * 0.5))
        meta = vision_train.train(dataset, model, features, algo, progress=lambda stage, done: progress(stage, 0.5 + done * 0.5))
        return {"dataset": made, "model": meta}
    return start_job("prepare", work)


def api_demo_dataset(body):
    scene = body.get("scene")
    if scene not in vision_demo.SCENES:
        raise ApiError(400, "unknown scene '%s'" % scene)
    dataset = body.get("dataset") or ("demo-" + scene)
    return start_job("dataset", lambda progress: make_demo_dataset(scene, dataset, int(body.get("per_class", 40)), progress))


def api_backbone(body):
    def work(progress):
        return vision_train.download_backbone(backbone_urls(), os.environ.get("LAYA_WB_PROXY") or None,
                                              lambda done, total: progress("download", done / float(total) if total else 0.0))
    return start_job("backbone", work)


def api_delete_dataset(body):
    vision_train.delete_item(body.get("dataset"), body.get("label"), body.get("file"))
    return {"datasets": vision_train.list_datasets()}


def api_delete_model(body):
    vision_train.delete_model(body.get("name"))
    return {"models": vision_train.list_models()}


POST = {
    "/v1/vision/analyze": api_analyze,
    "/v1/vision/datasets/add": api_add,
    "/v1/vision/datasets/add_regions": api_add_regions,
    "/v1/vision/datasets/delete": api_delete_dataset,
    "/v1/vision/datasets/demo": api_demo_dataset,
    "/v1/vision/train": api_train,
    "/v1/vision/demo/prepare": api_prepare,
    "/v1/vision/backbone/download": api_backbone,
    "/v1/vision/models/delete": api_delete_model,
    "/v1/vision/predict": api_predict,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _local(self):
        host = (self.headers.get("Host") or "").strip().lower().rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "[::1]") and not self.headers.get("Origin")

    def do_GET(self):
        if not self._local():
            return self._json(403, {"detail": "forbidden"})
        parsed = urllib.parse.urlsplit(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        path = parsed.path
        try:
            if path == "/v1/vision/health":
                return self._json(200, health())
            if path == "/v1/vision/datasets":
                return self._json(200, {"datasets": vision_train.list_datasets()})
            if path == "/v1/vision/models":
                return self._json(200, {"models": vision_train.list_models()})
            if path == "/v1/vision/jobs":
                with JOBS_LOCK:
                    if query.get("id"):
                        job = JOBS.get(query["id"])
                        return self._json(200 if job else 404, job or {"detail": "unknown job"})
                    return self._json(200, {"jobs": sorted(JOBS.values(), key=lambda j: -j["started"])})
            if path == "/v1/vision/demo":
                seed = int(query.get("seed") or int(time.time() * 1000) % 100000)
                img, notes, variant = vision_demo.render(query.get("scene"), query.get("variant"), seed)
                return self._send(200, vision_core.encode_image(img, ".jpg", 92), "image/jpeg",
                                  {"X-Variant": variant, "X-Seed": str(seed), "X-Objects": str(len(notes))})
            if path == "/v1/vision/datasets/thumb":
                data = vision_train.thumbnail(query.get("dataset"), query.get("label"), query.get("file"), int(query.get("size") or 96))
                if data is None:
                    return self._json(404, {"detail": "not found"})
                return self._send(200, data, "image/jpeg")
        except (vision_train.TrainError, vision_core.VisionError, ValueError) as error:
            return self._json(400, {"detail": str(error)})
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self._json(413, {"detail": "request body too large"})
        data = self.rfile.read(length) if length > 0 else b""
        if not self._local():
            return self._json(403, {"detail": "forbidden"})
        path = urllib.parse.urlsplit(self.path).path
        func = POST.get(path)
        if func is None:
            return self._json(404, {"detail": "not found"})
        try:
            body = json.loads(data.decode("utf-8")) if data else {}
            if not isinstance(body, dict):
                raise ApiError(400, "request body must be a JSON object")
            self._json(200, func(body))
        except ValueError as error:
            self._json(400, {"detail": str(error) or "invalid JSON"})
        except ApiError as error:
            self._json(error.status, {"detail": error.detail})
        except (vision_train.TrainError, vision_core.VisionError) as error:
            self._json(422, {"detail": str(error)})
        except cv2.error as error:
            self._json(422, {"detail": str(error).strip().splitlines()[-1]})
        except Exception as error:
            traceback.print_exc()
            self._json(500, {"detail": "%s: %s" % (type(error).__name__, error)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    cv2.setNumThreads(max(1, min(4, os.cpu_count() or 1)))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("[vision] OpenCV %s, cv2.ml %s, listening on http://%s:%d" % (cv2.__version__, "yes" if vision_train.HAS_ML else "NO", args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
