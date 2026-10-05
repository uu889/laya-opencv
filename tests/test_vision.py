# -*- coding: utf-8 -*-
"""视觉核心和训练的测试。需要 OpenCV 4.x 和 numpy；没装时整个文件跳过。"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

if cv2 is not None:
    DATA = tempfile.mkdtemp(prefix="laya-wb-test-")
    os.environ["LAYA_WB_DATA"] = DATA
    import numeric as N  # noqa: E402
    import vision_core as C  # noqa: E402
    import vision_demo as D  # noqa: E402
    import vision_train as T  # noqa: E402

# (方案, 示例图的种类) -> 规则应该给出的结论
EXPECTED = {
    ("fruit-picking", "ripe"): ("pick", True), ("fruit-picking", "turning"): ("pick", False),
    ("fruit-picking", "unripe"): ("pick", False), ("fruit-picking", "blemished"): ("pick", False),
    ("weed-control", "clean"): ("need", False), ("weed-control", "light"): ("need", True), ("weed-control", "heavy"): ("method", "全面除草"),
    ("pest-trap", "low"): ("level", "正常"), ("pest-trap", "medium"): ("level", "加强监测"), ("pest-trap", "high"): ("level", "立即防治"),
    ("steel-pipe", "ok"): ("verdict", "合格"), ("steel-pipe", "minor"): ("verdict", "让步接收"), ("steel-pipe", "reject"): ("verdict", "不合格"),
    ("textile", "ok"): ("verdict", "合格"), ("textile", "minor"): ("verdict", "降等"), ("textile", "reject"): ("verdict", "不合格"),
}


def recipes():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "recipes", "zh", "*.json"))):
        with open(path, encoding="utf-8") as handle:
            recipe = json.load(handle)
        out[recipe["id"]] = recipe
    return out


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class RecipeTest(unittest.TestCase):
    def test_demo_images_get_expected_verdicts(self):
        all_recipes = recipes()
        self.assertEqual(len(all_recipes), 5)
        for (recipe_id, variant), (question, expected) in EXPECTED.items():
            recipe = all_recipes[recipe_id]
            for seed in (3, 4, 5):
                img, _, _ = D.render(recipe["demo"]["scene"], variant, seed)
                result = C.analyze(recipe, img, want_image=False)
                values = N.normalize(recipe, result["values"])
                verdict = N.decide(recipe, values, None)["verdicts"][question]
                self.assertEqual(verdict["final"], expected, "%s %s seed %d: %s" % (recipe_id, variant, seed, values))

    def test_counts_match_ground_truth(self):
        recipe = recipes()["pest-trap"]
        for seed in (11, 12, 13):
            img, notes, _ = D.render("pest", "medium", seed)
            result = C.analyze(recipe, img, want_image=False)
            self.assertEqual(result["values"]["total"], len(notes))

    def test_analysis_output(self):
        recipe = recipes()["steel-pipe"]
        img, _, _ = D.render("steel", "reject", 7)
        result = C.analyze(recipe, C.encode_image(img, ".png"))          # 也接受编码后的字节
        self.assertTrue(result["annotated"].startswith("data:image/jpeg;base64,"))
        self.assertIn("model_missing:steel-defects", result["notes"])
        self.assertIsNone(result["values"]["main_defect"])               # 没有识别模型：没有值，而不是 0
        region = result["regions"]["defects"][0]
        for key in ("id", "bbox", "area", "length", "width", "elongation", "circularity"):
            self.assertIn(key, region)
        self.assertAlmostEqual(result["mm_per_px"], 0.2)

    def test_calibration_follows_resize(self):
        """mm_per_px 是按原图写的；图被缩小到 max_side 处理时，量出来的毫米数不应该变。"""
        img = np.full((960, 1280, 3), 200, np.uint8)
        cv2.line(img, (200, 480), (599, 480), (0, 0, 0), 8)                  # 400 px × 0.1 mm = 40 mm
        recipe = {"calibration": {"mm_per_px": 0.1},
                  "pipeline": [{"op": "mask", "name": "dark", "method": "gray", "below": 30},
                               {"op": "regions", "name": "lines", "from": "dark"}],
                  "measurements": {"length": {"decimals": 1, "compute": {"type": "max", "regions": "lines", "attr": "length"}}}}
        full = C.analyze(dict(recipe, max_side=1280), img, want_image=False)
        half = C.analyze(dict(recipe, max_side=640), img, want_image=False)
        self.assertAlmostEqual(full["mm_per_px"], 0.1)
        self.assertAlmostEqual(half["mm_per_px"], 0.2)
        self.assertAlmostEqual(full["values"]["length"], 40.0, delta=1.0)
        self.assertAlmostEqual(half["values"]["length"], 40.0, delta=1.5)


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class CoreTest(unittest.TestCase):
    def test_hsv_wraps_around_red(self):
        img = np.zeros((10, 30, 3), np.uint8)
        img[:, :10] = (0, 0, 255)          # 红
        img[:, 10:20] = (0, 255, 0)        # 绿
        img[:, 20:] = (255, 0, 255)        # 品红，色相 300 度
        recipe = {"pipeline": [{"op": "mask", "name": "red", "method": "hsv", "ranges": [{"h": [340, 20], "s": [50, 100], "v": [50, 100]}]}],
                  "measurements": {"share": {"decimals": 1, "compute": {"type": "area_ratio", "mask": "red"}}}}
        self.assertAlmostEqual(C.analyze(recipe, img, want_image=False)["values"]["share"], 33.3, delta=0.1)

    def test_measurement_types(self):
        img = np.full((100, 200, 3), 200, np.uint8)
        cv2.rectangle(img, (10, 10), (29, 29), (0, 0, 0), cv2.FILLED)        # 20 × 20
        cv2.rectangle(img, (100, 40), (179, 49), (0, 0, 0), cv2.FILLED)      # 80 × 10
        recipe = {"calibration": {"mm_per_px": 0.5},
                  "pipeline": [{"op": "mask", "name": "dark", "method": "gray", "below": 20},
                               {"op": "regions", "name": "blobs", "from": "dark", "min_area": 10}],
                  "measurements": {
                      "n": {"decimals": 0, "compute": {"type": "count", "regions": "blobs"}},
                      "long": {"decimals": 0, "compute": {"type": "count", "regions": "blobs", "where": {"elongation": [">=", 4]}}},
                      "longest": {"decimals": 1, "compute": {"type": "max", "regions": "blobs", "attr": "length"}},
                      "cover": {"decimals": 1, "compute": {"type": "area_ratio", "mask": "dark"}},
                      "area": {"decimals": 0, "compute": {"type": "area", "mask": "dark"}},
                      "per_dm2": {"decimals": 1, "compute": {"type": "density", "regions": "blobs", "per": "dm2"}},
                      "weight": {"decimals": 1, "compute": {"type": "input", "default": 1.5}},
                      "ratio": {"decimals": 2, "compute": {"type": "expr", "expr": "longest / max(n, 1) + weight"}},
                  }}
        values = C.analyze(recipe, img, inputs={"weight": 2.0}, want_image=False)["values"]
        self.assertEqual(values["n"], 2)
        self.assertEqual(values["long"], 1)
        self.assertAlmostEqual(values["longest"], 40.0, delta=1.0)           # 80 px × 0.5 mm
        self.assertAlmostEqual(values["cover"], 6.0, delta=0.2)
        self.assertAlmostEqual(values["area"], 300, delta=12)                # 1200 px² × 0.25
        self.assertAlmostEqual(values["per_dm2"], 4.0, delta=0.1)            # 2 个 / (100 mm × 50 mm)
        self.assertAlmostEqual(values["ratio"], values["longest"] / 2 + 2.0, delta=0.01)

    def test_expr_is_restricted(self):
        self.assertEqual(C.safe_expr("(a + 2) * 3 - min(a, 1)", {"a": 4}), 17)
        for text in ("__import__('os')", "a.b", "open('x')", "a if a else 1", "[1][0]"):
            with self.assertRaises(C.VisionError):
                C.safe_expr(text, {"a": 1})

    def test_errors_name_the_step(self):
        img = np.zeros((20, 20, 3), np.uint8)
        with self.assertRaises(C.VisionError) as caught:
            C.analyze({"pipeline": [{"op": "regions", "name": "r", "from": "nope"}]}, img)
        self.assertIn("nope", str(caught.exception))
        with self.assertRaises(C.VisionError):
            C.analyze({"pipeline": []}, b"not an image")

    def test_yolo_decoding(self):
        classes = ["a", "b"]
        v8 = np.zeros((1, 6, 5), np.float32)                                 # [1, 4 + nc, N]
        v8[0, :, 0] = (100, 100, 40, 20, 0.9, 0.1)
        v8[0, :, 1] = (102, 101, 40, 20, 0.8, 0.1)                           # 和第一个几乎重合：应被 NMS 去掉
        v8[0, :, 2] = (300, 200, 30, 30, 0.2, 0.7)
        found = C.decode_yolo(v8, 640, classes, 0.25, 0.45, (0.5, 0.5))
        self.assertEqual(sorted(f["label"] for f in found), ["a", "b"])
        self.assertEqual([f for f in found if f["label"] == "a"][0]["bbox"], [40, 45, 20, 10])
        v5 = np.zeros((1, 3, 7), np.float32)                                 # [1, N, 5 + nc]
        v5[0, 0] = (100, 100, 40, 20, 0.9, 0.9, 0.1)
        v5[0, 1] = (300, 200, 30, 30, 0.1, 0.9, 0.1)                         # 置信度 = obj × cls，太低
        found = C.decode_yolo(v5, 640, classes)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["label"], "a")


@unittest.skipIf(cv2 is None or not T.HAS_ML, "this OpenCV build has no cv2.ml (use 4.x)")
class TrainTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(DATA, ignore_errors=True)

    def test_train_predict_and_use_in_recipe(self):
        samples = D.dataset("pest", per_class=14)
        for label, images in samples.items():
            T.add_images("试验 数据", label, images)
        listed = T.list_datasets()
        self.assertEqual(listed[0]["name"], "试验_数据")
        self.assertEqual(sorted(c["label"] for c in listed[0]["classes"]), ["fly", "thrips", "whitefly"])
        for algo in T.ALGOS:
            meta = T.train("试验 数据", "pest-" + algo, ["shape", "texture", "color"], algo, folds=4)
            self.assertGreaterEqual(meta["metrics"]["accuracy"], 0.9, algo)
            self.assertEqual(len(meta["metrics"]["confusion"]), 3)
            T._CACHE.clear()                                                # 从磁盘重新加载
            model = T.get_model("pest-" + algo)
            label, prob, probs = model.predict([samples["fly"][0]])[0]
            self.assertEqual(label, "fly", algo)
            self.assertAlmostEqual(sum(probs.values()), 1.0, delta=0.01)
        self.assertIsNone(T.get_model("no-such-model"))

        shutil.copytree(os.path.join(T.MODELS, "pest-svm"), os.path.join(T.MODELS, "pest-types"))
        recipe = recipes()["pest-trap"]
        img, notes, _ = D.render("pest", "medium", 21)
        result = C.analyze(recipe, img, models=T.get_model, want_image=False)
        truth = {}
        for note in notes:
            truth[note["label"]] = truth.get(note["label"], 0) + 1
        got = {name: int(result["values"][name]) for name in ("whitefly", "thrips", "fly")}
        self.assertLessEqual(sum(abs(got[k] - truth.get(k, 0)) for k in got), 2, "%s vs %s" % (got, truth))
        self.assertEqual(result["values"]["main_type"], max(truth, key=truth.get))

    def test_training_needs_enough_data(self):
        T.add_images("tiny", "a", [np.zeros((16, 16, 3), np.uint8)] * 3)
        with self.assertRaises(T.TrainError):
            T.train("tiny", "tiny", ["color"], "svm")                       # 只有一个类别
        T.add_images("tiny", "b", [np.full((16, 16, 3), 255, np.uint8)])
        with self.assertRaises(T.TrainError):
            T.train("tiny", "tiny", ["color"], "svm")                       # 有一个类别只有 1 张
        with self.assertRaises(T.TrainError):
            T.train("tiny", "tiny", ["deep"], "svm")                        # 没有骨干网络

    def test_names_are_sanitised(self):
        self.assertEqual(T.safe_name("../..\\etc/passwd"), "....etcpasswd".strip("."))
        self.assertEqual(T.safe_name("钢管 缺陷"), "钢管_缺陷")
        self.assertEqual(T.safe_name("con"), "_con")
        self.assertTrue(os.path.abspath(T.dataset_path("../x", "../y", "../../z.png")).startswith(os.path.abspath(T.DATASETS)))


if __name__ == "__main__":
    unittest.main()
