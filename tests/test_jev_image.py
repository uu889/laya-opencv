# -*- coding: utf-8 -*-
"""Jev 看图的测试：图片检查（jev_image.py）和检测流程里的三种判定方式。不需要 OpenCV，也不联网。"""
import base64
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

DATA = tempfile.mkdtemp(prefix="laya-wb-jev-")
os.environ["LAYA_WB_DATA"] = DATA
os.environ["LAYA_WB_LANG"] = "zh"

import jev_image  # noqa: E402
import launcher  # noqa: E402
import mock_laya  # noqa: E402

GOOD = {"ripe_ratio": 91.26, "blemish_ratio": 0.44, "diameter": 70.4, "fruit_count": 1}


def png(w, h, animated=False):
    """只有文件头的 PNG：够 jev_image 读出尺寸。"""
    ihdr = struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"
    body = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0\0\0\0"
    if animated:
        body += struct.pack(">I", 8) + b"acTL" + b"\0" * 12
    return body + struct.pack(">I", 0) + b"IDAT" + b"\0\0\0\0"


def jpeg(w, h, progressive=False):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0" + b"\0" * 9
    sof = b"\xff" + (b"\xc2" if progressive else b"\xc0") + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def data_url(raw, mime="image/png"):
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


class ImageCheckTest(unittest.TestCase):
    def test_reads_png_and_jpeg(self):
        self.assertEqual(jev_image.inspect_image(png(640, 480))[("width")], 640)
        info = jev_image.inspect_image(jpeg(800, 600, progressive=True))
        self.assertEqual((info["format"], info["width"], info["height"], info["progressive"]), ("jpg", 800, 600, True))

    def test_rejects_what_typesafe_rejects(self):
        for raw, key in ((png(100, 400), "bad_size"), (png(2000, 800), "bad_size"), (png(640, 480, animated=True), "bad_format"),
                         (b"BM" + b"\0" * 64, "bad_format"), (b"GIF89a" + b"\0" * 20, "bad_format")):
            with self.assertRaises(jev_image.ImageError) as caught:
                jev_image.make_asset(data_url(raw))
            self.assertEqual(caught.exception.key, key)
        with self.assertRaises(jev_image.ImageError):
            jev_image.make_asset("")

    def test_asset_and_redact(self):
        ref, asset, info = jev_image.make_asset(data_url(jpeg(1568, 280), "image/jpeg"))
        self.assertTrue(ref.startswith("img-") and len(ref) > 20)
        self.assertEqual((asset["type"], asset["format"]), ("image", "jpg"))
        self.assertNotIn("data:", asset["data_base64"])
        shown = jev_image.redact({"state": {"x": ref}, "assets": {ref: asset}})
        self.assertIn("base64 chars", shown["assets"][ref]["data_base64"])
        self.assertEqual(asset["data_base64"][:4], "/9j/")                  # 原请求不受影响


def fake_decide(calls):
    def decide(target, body, batch=False, images=False):
        calls.append({"body": body, "images": images})
        out = mock_laya.predict(body["state"], body["questions"])
        return {"ok": True, "status": 200, "data": out, "provider": "typesafe", "tried": [], "ms": 1.0, "error": None,
                "request": jev_image.redact(body)}
    return decide


class ModesTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(DATA, ignore_errors=True)

    def setUp(self):
        self.calls = []
        self.real = launcher.safe_decide
        launcher.safe_decide = fake_decide(self.calls)
        self.vision = launcher.call_vision
        launcher.call_vision = lambda *a, **k: self.fail("OpenCV must not be called")
        self.providers = json.loads(json.dumps(launcher.CFG["providers"]))

    def tearDown(self):
        launcher.safe_decide = self.real
        launcher.call_vision = self.vision
        launcher.CFG["providers"] = self.providers

    def test_opencv_only_is_unchanged(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD}, "auto")
        self.assertEqual(out["vision_mode"], "opencv")
        self.assertNotIn("assets", self.calls[0]["body"])
        self.assertFalse(self.calls[0]["images"])

    def test_opencv_plus_jev(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD, "vision_mode": "opencv+jev",
                                "jev_image": data_url(png(640, 480)), "use_model": False}, "auto")
        call = self.calls[0]
        self.assertTrue(call["images"])
        ref = out["state"]["图片"]
        self.assertEqual(list(call["body"]["assets"]), [ref])
        self.assertIn("测量结果", out["state"])
        self.assertEqual(out["verdicts"]["pick"]["source"], "rule")          # 硬规则照常裁决
        self.assertIs(out["verdicts"]["pick"]["agree"], True)
        self.assertIn("base64 chars", out["model"]["request"]["assets"][ref]["data_base64"])

    def test_jev_only(self):
        out = launcher.inspect({"recipe": "fruit-picking", "vision_mode": "jev", "image": data_url(jpeg(1200, 900), "image/jpeg"),
                                "values": GOOD, "context": "订单要求一级果"}, "auto")
        self.assertIsNone(out["analysis"])
        self.assertEqual(out["values"], {})
        self.assertNotIn("测量结果", out["state"])
        self.assertIn("订单要求一级果", json.dumps(out["state"], ensure_ascii=False))
        self.assertIn("判定标准", out["questions"]["pick"]["instructions"])  # 标准照样写进题干
        self.assertTrue(all(v["source"] in ("model", "none") and v["rule"] is None for v in out["verdicts"].values()))
        self.assertTrue(self.calls[0]["images"])

    def test_recipe_default_mode_and_errors(self):
        recipe = dict(launcher.find_recipe("fruit-picking", "zh"), vision_mode="jev")
        out = launcher.inspect({"recipe": recipe, "image": data_url(png(400, 400))}, "auto")
        self.assertEqual(out["vision_mode"], "jev")
        for body, status in (({"recipe": "fruit-picking", "vision_mode": "jev"}, 400),
                             ({"recipe": "fruit-picking", "vision_mode": "x", "values": GOOD}, 400),
                             ({"recipe": "fruit-picking", "vision_mode": "jev", "image": data_url(png(4000, 3000))}, 400)):
            with self.assertRaises(launcher.WBError) as caught:
                launcher.inspect(body, "auto")
            self.assertEqual(caught.exception.status, status)

    def test_routing_only_to_image_interfaces(self):
        providers = launcher.CFG["providers"]
        providers["typesafe"]["api_key"] = "ts-key-0000"
        providers["aiask"]["api_key"] = "aa-key-0000"
        self.assertEqual(launcher.resolve_images("auto"), ["typesafe"])
        for target in ("local", "aiask"):
            with self.assertRaises(launcher.WBError):
                launcher.resolve_images(target)
        providers["aiask"]["supports_images"] = True
        self.assertEqual(launcher.resolve_images("auto"), ["aiask", "typesafe"])
        providers["typesafe"]["api_key"] = providers["aiask"]["api_key"] = ""
        providers["aiask"].pop("supports_images")
        with self.assertRaises(launcher.WBError):
            launcher.resolve_images("auto")

    def test_header_and_local_model_name(self):
        launcher.CFG["providers"]["typesafe"]["api_key"] = "ts-key-0000"
        sent = []
        real = launcher.call_remote
        launcher.call_remote = lambda pid, path, payload=None, method="GET", extra_headers=None: (
            sent.append((pid, payload, extra_headers)) or (200, json.dumps({"answers": {}}).encode("utf-8")))
        try:
            ref, asset, _ = jev_image.make_asset(data_url(png(640, 480)))
            got = launcher.laya_decide("auto", {"state": {"图片": ref}, "questions": {"q": {"type": "noul", "instructions": "?"}},
                                                "assets": {ref: asset}, "model": "multilingual"}, images=True)
        finally:
            launcher.call_remote = real
        pid, payload, headers = sent[0]
        self.assertTrue(got["ok"])
        self.assertEqual(pid, "typesafe")
        self.assertEqual(headers, {"TypeSafe-Danger-Zone-Images": "true"})
        self.assertEqual(payload["model"], "jev-latest")                     # 本地 Laya 的模型名换成接口的默认模型
        self.assertIn("base64 chars", got["request"]["assets"][ref]["data_base64"])


if __name__ == "__main__":
    unittest.main()
