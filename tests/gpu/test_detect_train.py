# -*- coding: utf-8 -*-
"""目标检测训练 CLI 的端到端测试：需要 torch + torchvision（+ OpenCV），没装就整体跳过。全程离线、CPU、不下载权重。

    <venv python> -m unittest tests.gpu.test_detect_train -v
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "app")
CLI = os.path.join(APP, "detect_train.py")
HAVE = all(importlib.util.find_spec(name) is not None for name in ("torch", "torchvision", "cv2", "numpy"))
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
ENV.pop("LAYA_WB_NO_TORCH", None)

if HAVE:
    DATA = tempfile.mkdtemp(prefix="laya-wb-dettrain-")
    os.environ["LAYA_WB_DATA"] = DATA
    os.environ.pop("LAYA_WB_NO_TORCH", None)
    sys.path.insert(0, APP)
    import detect_data as DD  # noqa: E402
    import vision_core as C  # noqa: E402
    import vision_demo as D  # noqa: E402


def run_cli(args, env=None):
    proc = subprocess.run([sys.executable, CLI] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or ENV, timeout=900)
    events = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return proc.returncode, events, proc.stderr.decode("utf-8", "replace")


@unittest.skipUnless(HAVE, "torch / torchvision / OpenCV are not installed")
class DetectTrainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("LAYA_WB_NO_TORCH", None)
        DD.make_demo("weed", "tiny-weed", 12, seed=21)                            # 12 张合成图，2 类
        cls.dataset = DD.dataset_dir("tiny-weed")
        cls.out = DD.model_dir("tiny-det")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(DATA, ignore_errors=True)

    def test_probe(self):
        code, events, _ = run_cli(["probe"])
        self.assertEqual(code, 0)
        result = events[-1]
        self.assertEqual(result["event"], "result")
        self.assertTrue(result["torch"])
        self.assertIn(result["device"], ("cpu", "cuda", "mps"))

    def test_train_predict_and_use_from_server_path(self):
        started = time.time()
        code, events, stderr = run_cli(["train", "--dataset", self.dataset, "--out", self.out, "--pretrained", "no", "--epochs", "1",
                                        "--batch", "2", "--imgsz", "160", "--holdout", "0.25", "--device", "cpu"])
        self.assertEqual(code, 0, stderr[-800:])
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds[0], "start")
        self.assertIn("progress", kinds)
        self.assertEqual(kinds[-1], "result")
        steps = [e for e in events if e["event"] == "progress" and e.get("stage") == "train"]
        self.assertTrue(steps and all(k in steps[-1] for k in ("epoch", "epochs", "step", "steps", "loss", "eta_seconds")))
        result = events[-1]
        self.assertEqual(result["classes"], ["crop", "weed"])
        self.assertEqual(result["epochs_done"], 1)
        self.assertEqual(result["holdout_images"], 3)
        self.assertIn("map50", result)                                             # 一轮之后大概是 0，但必须有这个字段
        self.assertTrue(result["map50"] is None or 0 <= result["map50"] <= 1)
        self.assertEqual(sorted(result["per_class"]), ["crop", "weed"])
        self.assertFalse(result["pretrained_used"])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "model.pt")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "last.pt")))
        with open(os.path.join(self.out, "meta.json"), encoding="utf-8") as handle:
            meta = json.load(handle)
        for key in ("arch", "classes", "imgsz", "map50", "per_class", "created", "torchvision", "pretrained_used", "epochs_done"):
            self.assertIn(key, meta)
        print("\n  train 1 epoch: %.1f s" % (time.time() - started))

        # 续训：从 last.pt 再训一轮
        code, events, stderr = run_cli(["train", "--dataset", self.dataset, "--out", self.out, "--pretrained", "no", "--epochs", "2",
                                        "--batch", "4", "--imgsz", "160", "--resume", "--device", "cpu"])
        self.assertEqual(code, 0, stderr[-800:])
        self.assertTrue(any("last.pt" in e.get("message", "") for e in events if e["event"] == "log"))
        self.assertEqual(events[-1]["epochs_done"], 2)

        # predict 命令
        image = os.path.join(self.dataset, "images", sorted(os.listdir(os.path.join(self.dataset, "images")))[0])
        code, events, stderr = run_cli(["predict", "--model", self.out, "--image", image, "--conf", "0.01", "--device", "cpu"])
        self.assertEqual(code, 0, stderr[-800:])
        boxes = events[-1]["boxes"]
        self.assertIsInstance(boxes, list)
        for box in boxes:
            self.assertIn(box["label"], ("crop", "weed"))
            self.assertEqual(len(box["bbox"]), 4)
            self.assertGreaterEqual(box["score"], 0.01)

        # 服务端的推理路径：detect_data.get_detector + vision_core 的 detect 步骤
        os.environ["LAYA_WB_DETECT_DEVICE"] = "cpu"
        detector = DD.get_detector("tiny-det")
        self.assertIsNotNone(detector)
        img, _, _ = D.render("weed", "heavy", 33)
        found = detector.predict(img, 0.01)
        self.assertIsInstance(found, list)
        recipe = {"max_side": 640, "pipeline": [{"op": "detect", "model": "tiny-det", "conf": 0.01, "as": "regions:objs"}],
                  "measurements": {"n": {"decimals": 0, "compute": {"type": "count", "regions": "objs"}}}}
        result = C.analyze(recipe, img, detectors=DD.get_detector)
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["values"]["n"], len(found))
        self.assertTrue(result["annotated"].startswith("data:image/jpeg"))
        self.assertIs(DD.get_detector("tiny-det"), detector)                      # 按名字缓存

    def test_fake_oom_backs_off(self):
        out = DD.model_dir("oom-det")
        code, events, stderr = run_cli(["train", "--dataset", self.dataset, "--out", out, "--pretrained", "no", "--epochs", "1",
                                        "--batch", "4", "--imgsz", "128", "--holdout", "0", "--device", "cpu"], dict(ENV, LAYA_WB_FAKE_OOM="2"))
        self.assertEqual(code, 0, stderr[-800:])
        ooms = [e for e in events if e["event"] == "oom"]
        self.assertEqual([e["batch"] for e in ooms], [2, 1])
        self.assertEqual(events[-1]["batch"], 1)
        self.assertEqual(events[-1]["oom_retries"], 2)
        self.assertIsNone(events[-1]["map50"])                                     # 没有留出集就不评估
        code, events, _ = run_cli(["train", "--dataset", self.dataset, "--out", out, "--pretrained", "no", "--epochs", "1",
                                   "--batch", "1", "--imgsz", "128", "--device", "cpu"], dict(ENV, LAYA_WB_FAKE_OOM="1"))
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["kind"], "oom")

    def test_bad_dataset_is_a_data_error(self):
        empty = os.path.join(DATA, "empty-set")
        os.makedirs(os.path.join(empty, "images"), exist_ok=True)
        code, events, _ = run_cli(["train", "--dataset", empty, "--out", os.path.join(DATA, "x"), "--pretrained", "no", "--device", "cpu"])
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["kind"], "data")


if __name__ == "__main__":
    unittest.main()
