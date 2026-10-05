# -*- coding: utf-8 -*-
"""数值层的测试。只用标准库：python -m unittest discover -s tests"""
import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numeric as N  # noqa: E402
import mock_laya  # noqa: E402

RECIPE = {
    "subject": "番茄",
    "measurements": {
        "ripe": {"label": "成熟色占比", "unit": "%", "decimals": 1, "guard": 2,
                 "bands": [{"max": 30, "label": "未熟"}, {"max": 70, "label": "转色"}, {"label": "成熟"}]},
        "spot": {"label": "病斑占比", "unit": "%", "decimals": 1},
        "dia": {"label": "果径", "unit": "mm", "decimals": 0, "range": [0, 150]},
        "kind": {"label": "识别类别"},
    },
    "rules": {
        "pick": {"label": "可采摘", "when": {"all": [{"m": "ripe", "op": ">=", "value": 70}, {"m": "spot", "op": "<=", "value": 3},
                                                     {"m": "dia", "op": ">=", "value": 50}]}},
        "grade": {"label": "等级", "cases": [
            {"value": "A", "when": {"all": [{"m": "ripe", "op": ">=", "value": 85}, {"m": "spot", "op": "<=", "value": 1}]}},
            {"value": "B", "when": {"m": "ripe", "op": ">=", "value": 70}},
            {"value": "C"}]},
    },
    "questions": {
        "pick": {"type": "noul", "instructions": "是否可以采摘？"},
        "grade": {"type": "choice", "instructions": "等级？", "criteria": {"A": "", "B": "", "C": ""}},
        "free": {"type": "noul", "instructions": "外观是否适合鲜食？"},
    },
    "bindings": {"pick": {"rule": "pick"}, "grade": {"rule": "grade", "mode": "advise"}},
}


def shipped_recipes():
    out = []
    for lang in ("zh", "en"):
        for path in sorted(glob.glob(os.path.join(ROOT, "recipes", lang, "*.json"))):
            with open(path, encoding="utf-8") as handle:
                out.append((lang, os.path.basename(path), json.load(handle)))
    return out


class CompareTest(unittest.TestCase):
    def test_operators(self):
        for op, value, expected in ((">=", 70, True), (">", 70, False), ("<=", 70, True), ("<", 70, False), ("==", 70, True), ("!=", 70, False)):
            got = N.compare(RECIPE, {"m": "spot", "op": op, "value": 70}, {"spot": 70})
            self.assertEqual(got["ok"], expected, op)
        self.assertTrue(N.compare(RECIPE, {"m": "spot", "op": "between", "value": [1, 3]}, {"spot": 2})["ok"])
        self.assertFalse(N.compare(RECIPE, {"m": "spot", "op": "between", "value": [1, 3]}, {"spot": 3.1})["ok"])
        self.assertTrue(N.compare(RECIPE, {"m": "kind", "op": "in", "value": ["ripe", "turning"]}, {"kind": "Ripe"})["ok"])
        self.assertIsNone(N.compare(RECIPE, {"m": "spot", "op": ">=", "value": 1}, {})["ok"])

    def test_guard_band(self):
        self.assertTrue(N.compare(RECIPE, {"m": "ripe", "op": ">=", "value": 70}, {"ripe": 71.5})["edge"])
        self.assertTrue(N.compare(RECIPE, {"m": "ripe", "op": ">=", "value": 70}, {"ripe": 68.2})["edge"])
        self.assertFalse(N.compare(RECIPE, {"m": "ripe", "op": ">=", "value": 70}, {"ripe": 75})["edge"])
        self.assertFalse(N.compare(RECIPE, {"m": "spot", "op": "<=", "value": 3}, {"spot": 3})["edge"])   # 没设 guard 的测量值没有临界带

    def test_rules(self):
        good = {"ripe": 90, "spot": 0.5, "dia": 60}
        self.assertTrue(N.run_rule(RECIPE, "pick", good)["result"])
        self.assertEqual(N.run_rule(RECIPE, "grade", good)["result"], "A")
        self.assertEqual(N.run_rule(RECIPE, "grade", dict(good, spot=2))["result"], "B")
        self.assertEqual(N.run_rule(RECIPE, "grade", dict(good, ripe=40))["result"], "C")
        self.assertFalse(N.run_rule(RECIPE, "pick", dict(good, dia=49))["result"])
        edge = N.run_rule(RECIPE, "pick", dict(good, ripe=71))
        self.assertTrue(edge["result"])
        self.assertTrue(edge["marginal"])
        self.assertFalse(N.run_rule(RECIPE, "pick", dict(good, ripe=71, dia=10))["marginal"])    # 果径已经不合格，成熟度临界不影响结论
        missing = N.run_rule(RECIPE, "pick", {"ripe": 90, "spot": 1})
        self.assertIsNone(missing["result"])
        self.assertEqual(missing["missing"], ["dia"])

    def test_not_and_any(self):
        recipe = {"measurements": {"a": {"guard": 1}, "b": {}},
                  "rules": {"r": {"when": {"not": {"any": [{"m": "a", "op": ">", "value": 10}, {"m": "b", "op": ">=", "value": 2}]}}}}}
        self.assertTrue(N.run_rule(recipe, "r", {"a": 5, "b": 1})["result"])
        self.assertFalse(N.run_rule(recipe, "r", {"a": 5, "b": 2})["result"])
        self.assertTrue(N.run_rule(recipe, "r", {"a": 9.5, "b": 1})["marginal"])

    def test_normalize(self):
        values = N.normalize(RECIPE, {"ripe": 69.96, "dia": 54.5, "kind": "ripe", "_sharpness": 12.345})
        self.assertEqual(values["ripe"], 70.0)
        self.assertEqual(values["kind"], "ripe")
        self.assertEqual(values["_sharpness"], 12.345)
        self.assertTrue(N.run_rule(RECIPE, "pick", dict(values, spot=0, dia=60))["result"])


class TextTest(unittest.TestCase):
    def test_state_mirrors_standard(self):
        values = {"ripe": 71.2, "spot": 4.7, "dia": 62}
        for lang in ("zh", "en"):
            state = N.build_state(RECIPE, values, lang)
            block = [v for v in state.values() if isinstance(v, dict)][0]
            questions = N.bound_questions(RECIPE, lang)
            for rule_id in RECIPE["rules"]:
                rule = RECIPE["rules"][rule_id]
                nodes = [rule.get("when")] + [c.get("when") for c in rule.get("cases") or []]
                for node in nodes:
                    for leaf in N.leaves(node):
                        clause = N.threshold_text(RECIPE, leaf["m"], leaf["op"], leaf["value"])
                        self.assertIn(clause, block[N.label_of(RECIPE, leaf["m"])])
                        self.assertIn(clause, questions["pick"]["instructions"] + questions["grade"]["instructions"])
            self.assertNotIn(N.tx(lang, "standard"), questions["free"]["instructions"])

    def test_phrases(self):
        text = N.describe(RECIPE, "ripe", 71.2, "zh")
        self.assertIn("≥ 70 %：是，高出 1.2，临界", text)
        self.assertIn("≥ 85 %：否，低 13.8", text)
        self.assertIn("档位：成熟", text)
        self.assertEqual(N.describe(RECIPE, "ripe", 71.2, "zh", "raw"), "71.2 %")
        self.assertIn("≤ 3 %: no, 1.7 above", N.describe(RECIPE, "spot", 4.7, "en"))
        self.assertIn("正好相等", N.describe(RECIPE, "dia", 50, "zh"))
        self.assertEqual(N.describe(RECIPE, "kind", "ripe", "zh", detail={"prob": 0.934}), "ripe（置信度 0.93）")

    def test_state_skips_unmeasured_optional(self):
        state = N.build_state(RECIPE, {"ripe": 80, "spot": 1, "dia": None, "kind": None}, "zh")
        block = [v for v in state.values() if isinstance(v, dict)][0]
        self.assertNotIn("识别类别", block)          # 规则用不到、又没有值：不写
        self.assertIn("果径", block)                 # 规则要用：写明没有测到


class DecideTest(unittest.TestCase):
    values = {"ripe": 90, "spot": 0.5, "dia": 60}

    def test_agree(self):
        out = N.decide(RECIPE, self.values, {"pick": {"noul": 0.95}, "grade": {"choice": "A"}, "free": {"noul": 0.8}})
        self.assertEqual(out["verdicts"]["pick"]["source"], "rule")
        self.assertTrue(out["verdicts"]["pick"]["agree"])
        self.assertEqual(out["verdicts"]["grade"]["source"], "model")       # advise：模型为准
        self.assertEqual(out["verdicts"]["free"]["source"], "model")
        self.assertFalse(out["review"])

    def test_conflict_rule_wins(self):
        out = N.decide(RECIPE, self.values, {"pick": {"noul": 0.1}, "grade": {"choice": "A"}, "free": {"noul": 0.8}})
        item = out["verdicts"]["pick"]
        self.assertIs(item["final"], True)
        self.assertIs(item["agree"], False)
        self.assertTrue(out["review"])

    def test_low_confidence_only_matters_for_model_verdicts(self):
        answers = {"pick": {"noul": 0.55}, "grade": {"choice": "A", "probabilities": {"A": 0.5, "B": 0.3, "C": 0.2}}, "free": {"noul": 0.9}}
        out = N.decide(RECIPE, self.values, answers, min_confidence=0.7)
        self.assertFalse(out["verdicts"]["pick"]["review"])
        self.assertTrue(out["verdicts"]["grade"]["review"])

    def test_model_down(self):
        out = N.decide(RECIPE, self.values, None, model_error=True)
        self.assertIs(out["verdicts"]["pick"]["final"], True)
        self.assertEqual(out["verdicts"]["grade"]["final"], "A")            # advise 模式下模型没答：退回规则
        self.assertIsNone(out["verdicts"]["free"]["final"])
        self.assertTrue(out["review"])

    def test_quality_forces_review(self):
        quality = N.check_quality({"quality": {"min_sharpness": 50, "brightness": [40, 220]}}, {"_sharpness": 10, "_brightness": 30})
        self.assertFalse(quality["ok"])
        self.assertEqual(len(quality["problems"]), 2)
        out = N.decide(RECIPE, self.values, {"pick": {"noul": 0.95}, "grade": {"choice": "A"}, "free": {"noul": 0.8}}, quality=quality)
        self.assertTrue(out["review"])


class ProbeTest(unittest.TestCase):
    def test_cases_follow_rules(self):
        cases = N.probe_cases(RECIPE, limit=48)
        self.assertGreaterEqual(len(cases), 24)
        seen = set()
        for case in cases:
            self.assertEqual(case["gold"]["pick"], N.run_rule(RECIPE, "pick", case["values"])["result"])
            self.assertEqual(case["gold"]["grade"], N.run_rule(RECIPE, "grade", case["values"])["result"])
            self.assertLessEqual(case["values"]["ripe"], 100)
            seen.add((case["gold"]["pick"], case["gold"]["grade"]))
        self.assertGreaterEqual(len(seen), 4)                               # 各种结果都有用例
        self.assertTrue(any(c["distance"] is not None and c["distance"] <= 0.01 for c in cases))

    def test_scoring(self):
        cases = N.probe_cases(RECIPE, limit=24)
        perfect = [{"pick": {"noul": 0.9 if c["gold"]["pick"] else 0.1}, "grade": {"choice": c["gold"]["grade"]}} for c in cases]
        report = N.score_probe(RECIPE, cases, perfect)
        self.assertEqual(report["pick"]["accuracy"], 1.0)
        self.assertEqual(report["grade"]["accuracy"], 1.0)
        always_yes = [{"pick": {"noul": 0.9}, "grade": {"choice": "A"}} for _ in cases]
        report = N.score_probe(RECIPE, cases, always_yes)
        self.assertLess(report["pick"]["accuracy"], 1.0)
        self.assertTrue(report["pick"]["misses"])

    def test_finetune_records(self):
        records = N.finetune_records(RECIPE, N.probe_cases(RECIPE, limit=8))
        self.assertTrue(records)
        self.assertEqual(set(records[0]), {"state", "questions", "gold"})
        self.assertEqual(set(records[0]["gold"]), set(records[0]["questions"]))


class ShippedRecipesTest(unittest.TestCase):
    def test_valid(self):
        recipes = shipped_recipes()
        self.assertEqual(len(recipes), 10)
        for lang, name, recipe in recipes:
            self.assertEqual(N.validate(recipe), [], "%s/%s" % (lang, name))
            self.assertTrue(N.probe_cases(recipe, limit=16), "%s/%s has no probe cases" % (lang, name))

    def test_same_structure_in_both_languages(self):
        by_file = {}
        for lang, name, recipe in shipped_recipes():
            by_file.setdefault(name, {})[lang] = recipe
        for name, pair in by_file.items():
            self.assertEqual(json.dumps(pair["zh"]["pipeline"], sort_keys=True), json.dumps(pair["en"]["pipeline"], sort_keys=True), name)
            self.assertEqual(list(pair["zh"]["measurements"]), list(pair["en"]["measurements"]), name)
            self.assertEqual(list(pair["zh"]["questions"]), list(pair["en"]["questions"]), name)

    def test_written_comparisons_are_machine_readable(self):
        """素材里的比较结论和题目里的判定标准必须能逐条对上：用一个只会查字面的假模型来验证。"""
        for lang, name, recipe in shipped_recipes():
            cases = N.probe_cases(recipe, limit=32)
            bound = {q: s for q, s in N.bound_questions(recipe, lang).items() if q in (recipe.get("bindings") or {})}
            answers = [mock_laya.predict(N.build_state(recipe, c["values"], lang, "compared"), bound)["answers"] for c in cases]
            report = N.score_probe(recipe, cases, answers)
            for qid, row in report.items():
                self.assertEqual(row["accuracy"], 1.0, "%s/%s %s: %s" % (lang, name, qid, row["misses"][:1]))
            raw = [mock_laya.predict(N.build_state(recipe, c["values"], lang, "raw"), bound)["answers"] for c in cases]
            worst = min(row["accuracy"] for row in N.score_probe(recipe, cases, raw).values())
            self.assertLess(worst, 1.0, "%s/%s: bare numbers should not be readable by a literal matcher" % (lang, name))


class ValidateTest(unittest.TestCase):
    def test_catches_mistakes(self):
        bad = json.loads(json.dumps(RECIPE))
        bad["rules"]["pick"]["when"]["all"][0]["m"] = "nope"
        bad["bindings"]["free"] = {"rule": "missing"}
        bad["bindings"]["grade"] = {"rule": "pick"}
        problems = "\n".join(N.validate(bad))
        self.assertIn("unknown measurement 'nope'", problems)
        self.assertIn("unknown rule 'missing'", problems)
        self.assertIn("returns yes/no", problems)


if __name__ == "__main__":
    unittest.main()
