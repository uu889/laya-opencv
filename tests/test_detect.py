# -*- coding: utf-8 -*-
"""目标检测（数据集、detect 步骤、任务解析、健康信息）的测试。只需要 OpenCV + numpy，不需要 torch。

训练子进程用 tests/fake_detect_train.py 顶替（环境变量 LAYA_WB_DETECT_CLI）；
LAYA_WB_NO_TORCH=1 让「没装 torch」的分支在装了 torch 的机器上也能测到。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

if cv2 is not None:
    DATA = tempfile.mkdtemp(prefix="laya-wb-detect-")
    os.environ["LAYA_WB_DATA"] = DATA
    os.environ["LAYA_WB_DETECT_CLI"] = os.path.join(ROOT, "tests", "fake_detect_train.py")
    import detect_data as DD  # noqa: E402
    import vision_core as C  # noqa: E402
    import vision_demo as D  # noqa: E402
    import vision_server as VS  # noqa: E402


def wait_job(job, timeout=20):
    deadline = time.time() + timeout
    while job["state"] in ("queued", "running") and time.time() < deadline:
        time.sleep(0.05)
    return job


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class DatasetTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(DATA, ignore_errors=True)

    def test_round_trip_pixels_to_yolo_and_back(self):
        DD.create("my set", ["cat", "dog"])
        img = np.full((300, 400, 3), 120, np.uint8)
        saved = DD.add_image("my set", img, [{"label": "cat", "bbox": [10, 20, 100, 50]}, {"label": "bird", "bbox": [200, 100, 33, 47]},
                                             {"label": "", "bbox": [1, 1, 5, 5]}, {"label": "dog", "bbox": [390, 290, 50, 50]}])   # 越界的框会被裁到图内
        self.assertEqual(saved["classes"], ["cat", "dog", "bird"])                 # 新类别自动追加
        folder = DD.dataset_dir("my set")
        with open(os.path.join(folder, "labels", os.path.splitext(saved["file"])[0] + ".txt"), encoding="utf-8") as handle:
            lines = handle.read().strip().splitlines()
        self.assertEqual(len(lines), 3)
        first = lines[0].split()
        self.assertEqual(first[0], "0")
        self.assertAlmostEqual(float(first[1]), 60 / 400.0, places=5)              # cx = (10 + 110) / 2
        self.assertAlmostEqual(float(first[2]), 45 / 300.0, places=5)
        self.assertAlmostEqual(float(first[3]), 100 / 400.0, places=5)
        self.assertAlmostEqual(float(first[4]), 50 / 300.0, places=5)
        self.assertEqual(lines[1].split()[0], "2")
        listed = DD.items("my set")
        self.assertEqual(listed["total"], 1)
        item = listed["items"][0]
        self.assertEqual(item["size"], [400, 300])
        got = {b["label"]: b["bbox"] for b in item["boxes"]}
        for label, expected in (("cat", [10, 20, 100, 50]), ("bird", [200, 100, 33, 47]), ("dog", [390, 290, 10, 10])):
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(got[label], expected)), "%s: %s vs %s" % (label, got[label], expected))

        changed = DD.set_labels("my set", item["file"], [{"label": "dog", "bbox": [5, 5, 20, 30]}])
        self.assertEqual(changed["boxes"][0]["label"], "dog")
        self.assertEqual(DD.describe("my set")["boxes"], 1)
        data, ctype = DD.image_bytes("my set", item["file"], 48)
        self.assertEqual(ctype, "image/jpeg")
        self.assertLessEqual(max(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2]), 48)
        self.assertIn("my_set", [d["name"] for d in DD.list_datasets()])

        DD.delete("my set", item["file"])
        self.assertEqual(DD.describe("my set")["images"], 0)
        DD.delete("my set")
        self.assertFalse(any(d["name"] == "my_set" for d in DD.list_datasets()))
        with self.assertRaises(DD.TrainError):
            DD.items("no-such-set")

    def test_demo_dataset_has_labels(self):
        info = DD.make_demo("pest", "demo pest", 6, seed=3)
        self.assertEqual(info["images"], 6)
        self.assertGreater(info["boxes"], 20)
        self.assertEqual(info["classes"], ["fly", "thrips", "whitefly"])
        folder = DD.dataset_dir("demo pest")
        self.assertEqual(len(os.listdir(os.path.join(folder, "labels"))), 6)
        item = DD.items("demo pest", 0, 1)["items"][0]
        self.assertTrue(all(0 <= b["bbox"][0] and b["bbox"][0] + b["bbox"][2] <= 640 for b in item["boxes"]))
        with self.assertRaises(DD.TrainError):
            DD.make_demo("nope", "x", 2)

    def test_prelabel_uses_recipe_regions(self):
        DD.make_demo("steel", "steel-pre", 2, seed=9)
        item = DD.items("steel-pre", 0, 1)["items"][0]
        out = DD.prelabel("steel-pre", item["file"], "steel-pipe")                  # 按 id 找内置方案
        self.assertEqual(out["size"], [640, 480])
        self.assertTrue(all("bbox" in b and "label" in b for b in out["boxes"]))
        self.assertIn("model_missing:steel-defects", out["notes"])
        with self.assertRaises(DD.TrainError):
            DD.prelabel("steel-pre", item["file"], "no-such-recipe")


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class DetectOpTest(unittest.TestCase):
    RECIPE = {"max_side": 640,
              "pipeline": [{"op": "detect", "model": "ghost", "conf": 0.3, "classes": ["weed"], "as": "regions:weeds"},
                           {"op": "mask", "name": "veg", "method": "exg", "threshold": "otsu"}],
              "measurements": {"n": {"decimals": 0, "compute": {"type": "count", "regions": "weeds"}},
                               "cover": {"decimals": 1, "compute": {"type": "area_ratio", "mask": "veg"}}}}

    def test_missing_model_keeps_pipeline_running(self):
        img, _, _ = D.render("weed", "heavy", 4)
        result = C.analyze(self.RECIPE, img, want_image=False)
        self.assertIn("model_missing:ghost", result["notes"])
        self.assertEqual(result["regions"]["weeds"], [])
        self.assertIsNone(result["values"]["n"])                                   # 没有模型：没有值，而不是 0
        self.assertGreater(result["values"]["cover"], 1)                           # 后面的步骤照常
        self.assertIsNone(DD.get_detector("ghost"))
        result = C.analyze(self.RECIPE, img, want_image=False, detectors=DD.get_detector)
        self.assertIn("model_missing:ghost", result["notes"])

    def test_fake_detector_produces_regions_like_segmentation(self):
        class Fake:
            classes = ["crop", "weed"]

            def predict(self, img, conf, classes=None):
                boxes = [{"label": "weed", "score": 0.9, "bbox": [10, 20, 40, 30]}, {"label": "crop", "score": 0.8, "bbox": [100, 100, 20, 60]}]
                return [b for b in boxes if not classes or b["label"] in classes]
        img, _, _ = D.render("weed", "heavy", 4)
        result = C.analyze(self.RECIPE, img, detectors=lambda name: Fake() if name == "ghost" else None)
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["values"]["n"], 1)                                 # classes 过滤只留 weed
        region = result["regions"]["weeds"][0]
        for key in ("id", "bbox", "center", "area", "area_px", "length", "width", "diameter", "elongation", "circularity", "solidity", "label", "prob"):
            self.assertIn(key, region)
        self.assertEqual(region["bbox"], [10, 20, 40, 30])
        self.assertEqual(region["label"], "weed")
        self.assertEqual(region["area_px"], 1200.0)
        self.assertTrue(result["annotated"].startswith("data:image/jpeg"))
        recipe = dict(self.RECIPE, pipeline=[{"op": "detect", "model": "ghost", "as": "regions:objs"}],
                      measurements={"top": {"compute": {"type": "top_label", "regions": "objs"}},
                                    "crops": {"decimals": 0, "compute": {"type": "class_count", "regions": "objs", "label": "crop"}}})
        values = C.analyze(recipe, img, want_image=False, detectors=lambda name: Fake())["values"]
        self.assertEqual(values["crops"], 1)
        self.assertIn(values["top"], ("weed", "crop"))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class ServerTest(unittest.TestCase):
    def setUp(self):
        self.had = os.environ.get("LAYA_WB_NO_TORCH")
        os.environ["LAYA_WB_NO_TORCH"] = "1"                                       # 这些测试走「没装 torch」的分支

    def tearDown(self):
        if self.had is None:
            os.environ.pop("LAYA_WB_NO_TORCH", None)
        else:
            os.environ["LAYA_WB_NO_TORCH"] = self.had

    def test_health_has_detect_block(self):
        info = VS.health()["detect"]
        self.assertFalse(info["available"])                                        # LAYA_WB_NO_TORCH=1
        self.assertIn("LAYA_WB_NO_TORCH", info["reason"])
        self.assertIsNone(info["torch"])
        self.assertEqual(info["archs"], ["ssdlite", "fasterrcnn_mobile"])
        self.assertIn("device", info)
        for key in ("available", "reason", "torch", "torchvision"):
            self.assertIn(key, info)

    def test_train_job_parses_fake_cli_events(self):
        DD.make_demo("weed", "job-weed", 3, seed=1)
        real = DD.detect_info
        DD.detect_info = lambda: {"available": True, "reason": None, "torch": "x", "torchvision": "y"}   # 让接口放行到假脚本
        try:
            job = wait_job(VS.api_det_train({"dataset": "job-weed", "name": "weed det", "epochs": 2, "batch": 4}))
            self.assertEqual(job["state"], "done", job)
            self.assertEqual(job["epoch"], 2)
            self.assertEqual(job["epochs"], 2)
            self.assertEqual(job["steps"], 3)
            self.assertIsNotNone(job["loss"])
            self.assertEqual(job["eta_seconds"], 0)
            self.assertTrue(any("epoch 2/2" in line for line in job["log_tail"]))
            self.assertEqual(job["result"]["map50"], 0.5)
            self.assertEqual(job["result"]["classes"], ["crop", "weed"])
            self.assertEqual(job["result"]["name"], "weed_det")
            self.assertEqual(job["model"], "weed_det")
            models = DD.list_models()
            self.assertEqual([m["name"] for m in models], ["weed_det"])
            self.assertEqual(models[0]["map50"], 0.5)
            json.dumps(job)                                                        # 任务要能原样变成 JSON

            os.environ["FAKE_DETECT_FAIL"] = "1"
            try:
                job = wait_job(VS.api_det_train({"dataset": "job-weed", "name": "fails"}))
            finally:
                os.environ.pop("FAKE_DETECT_FAIL", None)
            self.assertEqual(job["state"], "error")
            self.assertIn("fake failure", job["error"])

            os.environ["FAKE_DETECT_OOM"] = "1"
            try:
                job = wait_job(VS.api_det_train({"dataset": "job-weed", "name": "oom", "batch": 8}))
            finally:
                os.environ.pop("FAKE_DETECT_OOM", None)
            self.assertEqual(job["state"], "done")
            self.assertTrue(any(line.startswith("oom:") for line in job["log_tail"]))
            self.assertEqual(job["result"]["batch"], 4)

            os.environ["FAKE_DETECT_DELAY"] = "0.3"
            try:
                job = VS.api_det_train({"dataset": "job-weed", "name": "slow", "epochs": 20})
                time.sleep(0.8)
                self.assertEqual(VS.cancel_job(job["id"])["state"], "running")
                job = wait_job(job)
            finally:
                os.environ.pop("FAKE_DETECT_DELAY", None)
            self.assertEqual(job["state"], "cancelled")
            self.assertFalse(os.path.isdir(DD.model_dir("slow")))
            with self.assertRaises(VS.ApiError):
                VS.cancel_job("no-such-job")

            VS.api_det_delete_model({"name": "weed det"})
            self.assertEqual([m["name"] for m in DD.list_models()], ["oom"])
        finally:
            DD.detect_info = real

    def test_train_refused_without_torch(self):
        DD.create("empty", ["a"])
        with self.assertRaises(VS.ApiError) as caught:
            VS.api_det_train({"dataset": "empty", "name": "x"})
        self.assertEqual(caught.exception.status, 422)
        with self.assertRaises(VS.ApiError) as caught:
            VS.api_det_predict({"model": "nothing", "image": ""})
        self.assertEqual(caught.exception.status, 404)

    def test_add_endpoint_rescales_boxes_to_the_decoded_image(self):
        img = np.full((100, 200, 3), 90, np.uint8)
        body = {"name": "scaled", "image": C.data_url(img, ".png"), "boxes": [{"label": "a", "bbox": [20, 10, 40, 20]}], "size": [400, 200]}
        saved = VS.api_det_add(body)                                               # 前端按 2 倍尺寸画的框
        self.assertEqual(saved["boxes"][0]["bbox"], [10, 5, 20, 10])
        self.assertEqual(saved["dataset"]["images"], 1)


if __name__ == "__main__":
    unittest.main()
