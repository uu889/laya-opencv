# -*- coding: utf-8 -*-
"""决策训练 CLI 的纯函数测试：不需要 torch / laya / peft（CI 只装 opencv + numpy）。

python -m unittest discover -s tests
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import decision_train as DT  # noqa: E402
import decision_server as DS  # noqa: E402


class ImportTest(unittest.TestCase):
    def test_import_does_not_pull_torch(self):
        """模块顶层只用标准库：在干净的解释器里 import 之后 torch / laya 不应出现在 sys.modules。"""
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import decision_train, decision_server; "
                "print(sorted(m for m in ('torch', 'laya', 'transformers', 'peft') if m in sys.modules))" % os.path.join(ROOT, "app"))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_messages_bilingual(self):
        for key, pair in DT.MSG.items():
            self.assertEqual(len(pair), 2, key)
            self.assertTrue(pair[0] and pair[1], key)
        for key, pair in DS.MSG.items():
            self.assertEqual(len(pair), 2, key)


class TierTest(unittest.TestCase):
    def test_tier_from_vram(self):
        self.assertEqual(DT.tier_from_vram(None), "small")
        self.assertEqual(DT.tier_from_vram(0), "small")
        self.assertEqual(DT.tier_from_vram(4096), "small")
        self.assertEqual(DT.tier_from_vram(5999), "small")
        self.assertEqual(DT.tier_from_vram(6000), "base")
        self.assertEqual(DT.tier_from_vram(8192), "base")
        self.assertEqual(DT.tier_from_vram(10999), "base")
        self.assertEqual(DT.tier_from_vram(11000), "large")
        self.assertEqual(DT.tier_from_vram(24576), "large")

    def test_recommend_rows(self):
        keys = {"encoder", "mode", "micro_batch", "grad_accum", "max_len", "amp", "grad_ckpt", "note_zh", "note_en"}
        cpu = DT.recommend("small", "cpu")
        self.assertEqual(set(cpu), keys)
        self.assertEqual((cpu["micro_batch"], cpu["grad_accum"], cpu["max_len"], cpu["amp"]), (4, 16, 256, False))
        # 没有可用显卡时不管档位都按 CPU 一行
        self.assertEqual(DT.recommend("large", "cpu")["max_len"], 256)
        small = DT.recommend("small", "cuda")
        self.assertEqual((small["micro_batch"], small["grad_accum"], small["max_len"], small["amp"]), (2, 32, 384, True))
        self.assertEqual(small["encoder"], DT.E5_SMALL)
        base = DT.recommend("base", "cuda")
        self.assertEqual((base["micro_batch"], base["grad_accum"], base["max_len"]), (4, 16, 512))
        large = DT.recommend("large", "cuda")
        self.assertEqual((large["micro_batch"], large["grad_accum"], large["max_len"]), (8, 8, 512))
        self.assertEqual(large["encoder"], DT.MODERNBERT_LARGE)

    def test_parse_nvidia_smi(self):
        self.assertEqual(DT.parse_nvidia_smi("NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB\n"),
                         ("NVIDIA GeForce RTX 3050 Laptop GPU", 4096))
        self.assertEqual(DT.parse_nvidia_smi("Tesla T4, 15360 MiB"), ("Tesla T4", 15360))
        self.assertIsNone(DT.parse_nvidia_smi(""))
        self.assertIsNone(DT.parse_nvidia_smi("No devices were found"))

    def test_encoders_table(self):
        ids = [e["id"] for e in DT.ENCODERS]
        for required in ("intfloat/multilingual-e5-small", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                         "BAAI/bge-small-zh-v1.5", "BAAI/bge-base-zh-v1.5", "intfloat/multilingual-e5-base",
                         "jhu-clsp/mmBERT-base", "answerdotai/ModernBERT-base", "answerdotai/ModernBERT-large",
                         "convaiinnovations/laya-multilingual", "convaiinnovations/laya", "convaiinnovations/laya-typed-decisions"):
            self.assertIn(required, ids)
        for e in DT.ENCODERS:
            self.assertIn(e["tier"], ("small", "base", "large"))
            for k in ("params_m", "langs", "note_zh", "note_en"):
                self.assertIn(k, e)
        laya = {e["id"]: e for e in DT.ENCODERS if e.get("laya")}
        self.assertEqual(len(laya), 3)
        self.assertEqual(laya["convaiinnovations/laya-multilingual"]["tier"], "base")
        self.assertEqual(laya["convaiinnovations/laya"]["tier"], "large")


class LoraTest(unittest.TestCase):
    def test_bert_family(self):
        self.assertEqual(DT.lora_target_modules("XLMRobertaModel"), ["query", "key", "value", "dense"])
        self.assertEqual(DT.lora_target_modules("BertModel"), ["query", "key", "value", "dense"])
        self.assertEqual(DT.lora_target_modules("MMBertModel"), ["query", "key", "value", "dense"])

    def test_modernbert(self):
        self.assertEqual(DT.lora_target_modules("ModernBertModel"), ["Wqkv", "Wo", "Wi"])

    def test_fallback_all_linear(self):
        names = ["layers.0.attn.q_proj", "layers.0.attn.k_proj", "layers.1.attn.q_proj", "layers.1.mlp.up"]
        self.assertEqual(DT.lora_target_modules("SomethingNew", names), ["q_proj", "k_proj", "up"])
        self.assertEqual(DT.lora_target_modules("SomethingNew", []), [])
        self.assertEqual(DT.lora_target_modules(None, None), [])


class BackoffTest(unittest.TestCase):
    def test_ladder(self):
        self.assertEqual(DT.next_backoff(8, 8, 512), (4, 16, 512))
        self.assertEqual(DT.next_backoff(4, 16, 512), (2, 32, 512))
        self.assertEqual(DT.next_backoff(1, 64, 512), (1, 64, 384))
        self.assertEqual(DT.next_backoff(1, 64, 384), (1, 64, 256))
        self.assertIsNone(DT.next_backoff(1, 64, 256))
        self.assertEqual(DT.next_backoff(1, 2, 300), (1, 2, 256))

    def test_cosine_lr(self):
        self.assertAlmostEqual(DT.cosine_lr(1e-3, 1e-6, 0, 10), 1e-3)
        self.assertAlmostEqual(DT.cosine_lr(1e-3, 1e-6, 10, 10), 1e-6)
        mid = DT.cosine_lr(1e-3, 1e-6, 5, 10)
        self.assertTrue(1e-6 < mid < 1e-3)

    def test_split_holdout(self):
        rows = [{"i": i} for i in range(20)]
        train, held = DT.split_holdout(rows, 0.2, seed=1)
        self.assertEqual((len(train), len(held)), (16, 4))
        self.assertEqual(sorted(r["i"] for r in train + held), list(range(20)))
        self.assertEqual(DT.split_holdout(rows, 0.0), (rows, []))
        train, held = DT.split_holdout(rows[:2], 0.9)
        self.assertEqual(len(train), 1)       # 至少留一行给训练
        # 同一个 seed 切出同样的行（续训时留出集不变）
        self.assertEqual(DT.split_holdout(rows, 0.2, seed=1), DT.split_holdout(rows, 0.2, seed=1))


class EventTest(unittest.TestCase):
    def test_format_event(self):
        line = DT.format_event("progress", stage="train", progress=0.5, loss=float("nan"), epoch=1, note="中文")
        self.assertNotIn("\n", line)
        d = json.loads(line)
        self.assertEqual(d["event"], "progress")
        self.assertIsNone(d["loss"])          # NaN → null
        self.assertEqual(d["note"], "中文")
        self.assertIn("中文", line)           # ensure_ascii=False

    def test_emit_one_json_per_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            DT.emit("start", command="train", config={"epochs": 2})
            DT.log("hello")
            DT.emit("result", out="x", holdout=None)
        lines = buf.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        events = [json.loads(l) for l in lines]
        self.assertEqual([e["event"] for e in events], ["start", "log", "result"])
        self.assertEqual(events[1]["message"], "hello")

    def test_jsonable(self):
        class Scalar:
            def item(self):
                return 3
        self.assertEqual(DT._jsonable({"a": (1, 2), "b": Scalar(), 3: float("inf")}), {"a": [1, 2], "b": 3, "3": None})


class ArgsTest(unittest.TestCase):
    def test_train_defaults(self):
        a = DT.parse_args(["train", "--data", "d.jsonl", "--base", "multilingual", "--out", "o"])
        self.assertEqual(a.command, "train")
        self.assertEqual((a.mode, a.epochs, a.micro_batch, a.grad_accum, a.loss), ("full", 4, 8, 8, "rlcd"))
        self.assertEqual((a.amp, a.grad_ckpt, a.device, a.holdout, a.resume, a.dry_run), ("auto", "auto", "auto", 0.0, False, False))
        self.assertIsNone(a.max_len)

    def test_train_all_flags(self):
        a = DT.parse_args(["train", "--data", "d", "--out", "o", "--mode", "lora", "--lora-r", "8", "--epochs", "6",
                           "--micro-batch", "2", "--grad-accum", "32", "--encoder-lr", "1e-5", "--head-lr", "2e-4",
                           "--loss", "soft-ce", "--max-len", "384", "--head-max-len", "128", "--amp", "on",
                           "--grad-ckpt", "off", "--calib-frac", "0.2", "--seed", "3", "--resume", "--holdout", "0.1",
                           "--device", "cuda", "--dry-run", "--hf-endpoint", "https://hf-mirror.com"])
        self.assertEqual(a.mode, "lora")
        self.assertEqual(a.lora_r, 8)
        self.assertEqual(a.max_len, 384)
        self.assertEqual(a.encoder_lr, 1e-5)
        self.assertTrue(a.resume and a.dry_run)
        self.assertEqual(a.hf_endpoint, "https://hf-mirror.com")
        self.assertIsNone(a.base)              # --resume 时不需要 --base

    def test_other_commands(self):
        self.assertEqual(DT.parse_args(["probe"]).command, "probe")
        self.assertEqual(DT.parse_args(["encoders"]).command, "encoders")
        a = DT.parse_args(["new", "--encoder", "intfloat/multilingual-e5-small", "--out", "o"])
        self.assertEqual((a.head_layers, a.max_len, a.head_max_len), (2, 512, 192))
        a = DT.parse_args(["evaluate", "--data", "d", "--model", "m"])
        self.assertEqual(a.device, "auto")
        self.assertEqual(DT.parse_args(["info", "--model", "m"]).model, "m")
        with self.assertRaises(SystemExit):
            DT.parse_args(["train", "--data", "d"])          # 缺 --out
        with self.assertRaises(SystemExit):
            DT.parse_args(["train", "--data", "d", "--out", "o", "--mode", "bogus"])
        self.assertEqual(DT._tri("auto"), None)
        self.assertEqual(DT._tri("on"), True)
        self.assertEqual(DT._tri("off"), False)


class ProbeWithoutTorchTest(unittest.TestCase):
    def _run_probe(self, smi):
        buf = io.StringIO()
        with mock.patch.object(DT, "_try_import", return_value=None), \
                mock.patch.object(DT, "query_nvidia_smi", return_value=smi), \
                redirect_stdout(buf):
            rc = DT.main(["probe"])
        self.assertEqual(rc, 0)
        lines = [json.loads(l) for l in buf.getvalue().splitlines()]
        self.assertEqual(lines[-1]["event"], "result")
        return lines[-1]

    def test_no_torch_no_gpu(self):
        r = self._run_probe(None)
        self.assertEqual(r["device"], "cpu")
        self.assertIsNone(r["torch"])
        self.assertIsNone(r["vram_mb"])
        self.assertEqual(r["tier"], "small")
        self.assertEqual(r["recommend"]["max_len"], 256)
        self.assertTrue(r["warnings"])

    def test_no_torch_but_gpu(self):
        r = self._run_probe(("NVIDIA GeForce RTX 3050 Laptop GPU", 4096))
        self.assertEqual(r["device"], "cpu")
        self.assertEqual(r["gpu_name"], "NVIDIA GeForce RTX 3050 Laptop GPU")
        self.assertEqual(r["vram_mb"], 4096)
        self.assertEqual(r["tier"], "small")
        self.assertIsNone(r["torch"])
        r = self._run_probe(("RTX 3090", 24576))
        self.assertEqual(r["tier"], "large")

    def test_encoders_command(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = DT.main(["encoders"])
        self.assertEqual(rc, 0)
        d = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(d["event"], "result")
        self.assertEqual(len(d["encoders"]), len(DT.ENCODERS))
        self.assertTrue(all("laya" in e for e in d["encoders"]))

    def test_train_without_torch_is_a_clean_error(self):
        buf = io.StringIO()
        with mock.patch.object(DT.importlib.util, "find_spec", return_value=None), redirect_stdout(buf):
            rc = DT.main(["train", "--data", "d.jsonl", "--base", "multilingual", "--out", "o"])
        self.assertNotEqual(rc, 0)
        d = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(d["event"], "error")
        self.assertEqual(d["kind"], "other")

    def test_info_missing_dir(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = DT.main(["info", "--model", os.path.join(ROOT, "no-such-dir")])
        self.assertEqual(rc, 2)
        d = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual((d["event"], d["kind"]), ("error", "data"))


class SafetensorsHeaderTest(unittest.TestCase):
    def test_param_count_from_header(self):
        import struct
        import tempfile
        header = {"__metadata__": {"format": "pt"},
                  "a": {"dtype": "F16", "shape": [3, 4], "data_offsets": [0, 24]},
                  "b": {"dtype": "F16", "shape": [5], "data_offsets": [24, 34]}}
        raw = json.dumps(header).encode("utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "model.safetensors")
            with open(p, "wb") as f:
                f.write(struct.pack("<Q", len(raw)) + raw + b"\0" * 34)
            self.assertEqual(DT.safetensors_param_count(p), 17)


class ServerPureTest(unittest.TestCase):
    """decision_server 里不需要 laya 的部分。"""

    def test_parse_list_and_args(self):
        self.assertEqual(DS.parse_list(" multilingual, english ,"), ["multilingual", "english"])
        self.assertEqual(DS.parse_list(""), [])
        a = DS.build_parser().parse_args(["--custom", "demo=/x", "--custom", "b=/y", "--builtin", "", "--pin-default"])
        self.assertEqual(a.custom, ["demo=/x", "b=/y"])
        self.assertTrue(a.pin_default)
        self.assertEqual(a.max_loaded, 1)

    def test_parse_custom(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "rl_agent_config.json"), "w") as f:
                f.write("{}")
            self.assertEqual(DS.parse_custom(["Demo=" + d]), {"demo": os.path.abspath(d)})
            with self.assertRaises(SystemExit):
                DS.parse_custom(["nodir=" + os.path.join(d, "missing")])
            with self.assertRaises(SystemExit):
                DS.parse_custom(["no-equals-sign"])

    def test_preload_names(self):
        a = DS.build_parser().parse_args([])
        self.assertEqual(DS.preload_names(a, "demo", ["demo", "multilingual"]), ["demo"])
        a = DS.build_parser().parse_args(["--preload", "none"])
        self.assertEqual(DS.preload_names(a, "demo", ["demo"]), [])
        a = DS.build_parser().parse_args(["--preload", "demo,multilingual"])
        self.assertEqual(DS.preload_names(a, "demo", ["demo", "multilingual"]), ["demo", "multilingual"])
        a = DS.build_parser().parse_args(["--preload", "english"])
        with self.assertRaises(SystemExit):
            DS.preload_names(a, "demo", ["demo"])

    def test_resolve_model_patch(self):
        class FakeRouter:
            models = {"english": 1, "multilingual": 2, "typed-decisions": 3, "demo": "/p"}

            def resolve(self, name):
                key = str(name).strip().lower()
                if key in self.models:
                    return key
                raise ValueError(name)

        def original(model):
            # 模拟 laya.serve._resolve_model：官方名通过，jev-1 → None
            return {"multilingual": "multilingual", "english": "english"}.get(str(model).lower())

        resolve = DS.make_resolve_model(FakeRouter(), {"demo"}, original)
        self.assertEqual(resolve("demo"), "demo")
        self.assertEqual(resolve("DEMO"), "demo")
        self.assertIsNone(resolve("multilingual"))      # 没在 --builtin 里 → 当作未指定（钩子再钉到默认）
        self.assertIsNone(resolve("jev-1"))
        self.assertIsNone(resolve(None))
        resolve = DS.make_resolve_model(FakeRouter(), {"demo", "multilingual"}, original)
        self.assertEqual(resolve("multilingual"), "multilingual")
        self.assertIsNone(resolve("english"))

    def test_pin_hook(self):
        class Ctx:
            def __init__(self, decision):
                self.decision = decision

        class FakeDecision(dict):
            pass

        with mock.patch.dict(sys.modules, {"laya": mock.MagicMock(), "laya.router": mock.MagicMock(RouteDecision=lambda **kw: FakeDecision(kw))}):
            hook = DS.PinHook("demo", "/p", ["demo"], pin_default=True)
            ctx = Ctx({"model": "multilingual", "reason": "non-Latin script", "detection": {"script": "han"}, "workflow": None})
            hook.on_route(ctx)
            self.assertEqual(ctx.decision["model"], "demo")
            self.assertIn("pinned to 'demo'", ctx.decision["reason"])
            self.assertEqual(ctx.decision["detection"], {"script": "han"})
            # 显式指定且允许 → 不动
            hook2 = DS.PinHook("demo", "/p", ["demo", "multilingual"], pin_default=True)
            ctx = Ctx({"model": "multilingual", "reason": "explicit model='multilingual'"})
            hook2.on_route(ctx)
            self.assertEqual(ctx.decision["model"], "multilingual")
            # 不 pin 但路由到了不允许的名字 → 仍改成默认
            hook3 = DS.PinHook("demo", "/p", ["demo"], pin_default=False)
            ctx = Ctx({"model": "english", "reason": "English Latin text"})
            hook3.on_route(ctx)
            self.assertEqual(ctx.decision["model"], "demo")
            # 不 pin 且允许 → 不动
            hook4 = DS.PinHook("demo", "/p", ["demo", "english"], pin_default=False)
            ctx = Ctx({"model": "english", "reason": "English Latin text"})
            hook4.on_route(ctx)
            self.assertEqual(ctx.decision["model"], "english")


if __name__ == "__main__":
    unittest.main()
