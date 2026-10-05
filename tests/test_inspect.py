# -*- coding: utf-8 -*-
"""检测流程的测试：启动器里的编排（数值层 + 判定模型 + 交叉核对），判定模型用 mock_laya 顶替，不需要 OpenCV。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

DATA = tempfile.mkdtemp(prefix="laya-wb-inspect-")
os.environ["LAYA_WB_DATA"] = DATA
os.environ["LAYA_WB_LANG"] = "zh"

import launcher  # noqa: E402
import mock_laya  # noqa: E402

GOOD = {"ripe_ratio": 91.26, "blemish_ratio": 0.44, "diameter": 70.4, "fruit_count": 1}


def fake_decide(mode):
    """顶替 launcher.safe_decide：ok = 假模型照常回答，down = 连不上，wrong = 是非题全部答反。"""
    def decide(target, body, batch=False):
        if mode == "down":
            return {"ok": False, "status": 503, "data": {"detail": "offline"}, "provider": None, "tried": [], "ms": 0, "error": "offline"}

        def one(state):
            out = mock_laya.predict(state, body["questions"])
            if mode == "wrong":
                for answer in out["answers"].values():
                    if "noul" in answer:
                        answer["noul"] = 1 - answer["noul"]
            return out
        data = {"results": [one(s) for s in body["states"]]} if batch else one(body["state"])
        return {"ok": True, "status": 200, "data": data, "provider": "local", "tried": [], "ms": 1.0, "error": None, "request": body}
    return decide


class InspectTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(DATA, ignore_errors=True)

    def setUp(self):
        self.real = launcher.safe_decide
        launcher.safe_decide = fake_decide("ok")

    def tearDown(self):
        launcher.safe_decide = self.real

    def test_recipes_are_listed_in_both_languages(self):
        for lang in ("zh", "en"):
            items = launcher.read_recipes(lang)
            self.assertEqual([i["id"] for i in items][:5], ["fruit-picking", "weed-control", "pest-trap", "steel-pipe", "textile"])
            self.assertTrue(all(not i["problems"] for i in items))

    def test_values_only_flow(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD, "context": "订单要求一级果"}, "auto")
        self.assertIsNone(out["analysis"])
        self.assertEqual(out["values"]["ripe_ratio"], 91.3)                 # 已按规格四舍五入
        self.assertIn("订单要求一级果", json.dumps(out["state"], ensure_ascii=False))
        self.assertIn("判定标准", out["questions"]["pick"]["instructions"])
        self.assertIs(out["verdicts"]["pick"]["final"], True)
        self.assertEqual(out["verdicts"]["pick"]["source"], "rule")
        self.assertIs(out["verdicts"]["pick"]["agree"], True)
        self.assertEqual(out["verdicts"]["grade"]["final"], "一级")
        self.assertEqual(out["verdicts"]["use"]["source"], "model")
        self.assertFalse(out["verdicts"]["pick"]["review"])

    def test_rule_wins_when_model_disagrees(self):
        launcher.safe_decide = fake_decide("wrong")
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD}, "auto")
        self.assertIs(out["verdicts"]["pick"]["final"], True)
        self.assertIs(out["verdicts"]["pick"]["agree"], False)
        self.assertTrue(out["review"])

    def test_model_down_falls_back_to_rules(self):
        launcher.safe_decide = fake_decide("down")
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD}, "auto")
        self.assertFalse(out["model"]["ok"])
        self.assertIs(out["verdicts"]["pick"]["final"], True)
        self.assertIsNone(out["verdicts"]["use"]["final"])
        self.assertTrue(out["review"])

    def test_rules_only(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": GOOD, "use_model": False}, "auto")
        self.assertIsNone(out["model"])
        self.assertEqual(sorted(out["verdicts"]), ["grade", "pick"])        # 没绑定规则的题目不列出
        self.assertFalse(out["review"])
        self.assertEqual(out["reasons"], [])

    def test_borderline_value_asks_for_review(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": dict(GOOD, ripe_ratio=70.8)}, "auto")
        self.assertIs(out["verdicts"]["pick"]["final"], True)
        self.assertTrue(out["verdicts"]["pick"]["rule"]["marginal"])
        self.assertTrue(out["review"])

    def test_missing_measurement_asks_for_review(self):
        out = launcher.inspect({"recipe": "fruit-picking", "values": {"ripe_ratio": 90, "blemish_ratio": 0}, "use_model": False}, "auto")
        self.assertIsNone(out["verdicts"]["pick"]["final"])
        self.assertTrue(out["review"])

    def test_bad_requests(self):
        for body, status in (({"recipe": "no-such-recipe", "values": GOOD}, 404), ({"recipe": "fruit-picking"}, 400), ({"values": GOOD}, 400)):
            with self.assertRaises(launcher.WBError) as caught:
                launcher.inspect(body, "auto")
            self.assertEqual(caught.exception.status, status)
        broken = dict(launcher.find_recipe("fruit-picking", "zh"))
        broken["bindings"] = {"pick": {"rule": "nope"}}
        with self.assertRaises(launcher.WBError) as caught:
            launcher.inspect({"recipe": broken, "values": GOOD}, "auto")
        self.assertEqual(caught.exception.status, 422)

    def test_selftest_review_and_export(self):
        report = launcher.selftest({"recipe": "steel-pipe", "limit": 24}, "auto")
        self.assertEqual(report["levels"]["compared"]["verdict"]["accuracy"], 1.0)
        self.assertLess(report["levels"]["raw"]["verdict"]["accuracy"], 1.0)
        self.assertEqual(report["advice"], {"verdict": "advise", "pass": "advise"})
        self.assertEqual(launcher.read_selftest("steel-pipe")["cases"], report["cases"])

        launcher.safe_decide = fake_decide("wrong")
        report = launcher.selftest({"recipe": "steel-pipe", "limit": 24}, "auto")
        self.assertEqual(report["advice"]["pass"], "enforce")               # 模型答错的题目：保持规则裁决

        launcher.safe_decide = fake_decide("ok")
        out = launcher.inspect({"recipe": "steel-pipe", "values": {"defect_count": 1, "scratch_len": 8, "pit_count": 0, "rust_ratio": 0}}, "auto")
        count = launcher.save_review({"recipe": out["recipe"], "state": out["state"], "questions": out["questions"], "gold": {"action": "打磨修复"}})
        self.assertEqual(count, 1)
        lines = [json.loads(line) for line in launcher.export_finetune("steel-pipe", "zh").splitlines()]
        self.assertTrue(all(set(line) == {"state", "questions", "gold"} for line in lines))
        self.assertEqual(lines[-1]["gold"], {"action": "打磨修复"})

    def test_custom_recipes(self):
        recipe = dict(launcher.find_recipe("textile", "zh"))
        try:
            slug = launcher.save_recipe({"recipe": recipe, "title": "我的方案"})
            self.assertEqual(slug, "my-textile")
            self.assertTrue(any(i["id"] == slug and i["custom"] for i in launcher.read_recipes("en")))
            with self.assertRaises(launcher.WBError):
                launcher.delete_recipe({"file": "../config.json"})
            with self.assertRaises(launcher.WBError):
                launcher.delete_recipe({"file": "zh/05-textile.json"})      # 内置方案删不掉
        finally:
            launcher.delete_recipe({"file": "my-textile.json"})
        self.assertFalse(any(i["custom"] for i in launcher.read_recipes("zh")))


if __name__ == "__main__":
    unittest.main()
