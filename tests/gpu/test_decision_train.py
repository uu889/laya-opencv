# -*- coding: utf-8 -*-
"""决策训练 CLI 与服务端的端到端测试：需要 torch + laya（+ peft 测 lora），没装就整体跳过。

全程离线、CPU：用一个随机初始化的迷你 XLM-R 编码器（和 docs/verify/new_model.py 一样）代替 Hugging Face 上的模型。
    <venv python> -m unittest tests.gpu.test_decision_train -v
"""
import importlib.util
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "app")
TRAIN = os.path.join(APP, "decision_train.py")
SERVER = os.path.join(APP, "decision_server.py")
HAVE_TORCH = importlib.util.find_spec("torch") is not None and importlib.util.find_spec("laya") is not None
HAVE_PEFT = importlib.util.find_spec("peft") is not None
ENV = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONIOENCODING="utf-8")


def make_rows(n_pairs=40, seed=7):
    """和 docs/verify/make_data.py 同样的双语「钢管检测」数据。"""
    rng = random.Random(seed)
    rows = []
    for _ in range(n_pairs):
        defect, count = round(rng.uniform(0, 12), 1), rng.randint(0, 40)
        zh = "钢管表面检测：缺陷占比 %s%%，缺陷数量 %d 个。阈值：缺陷占比超过 5%% 判为不合格。" % (defect, count)
        en = "Steel pipe inspection: defect ratio %s%%, defect count %d. Threshold: ratio above 5%% is a reject." % (defect, count)
        for state in (zh, en):
            rows.append({"state": state,
                         "questions": {"pass": {"type": "noul", "instructions": "Is the pipe acceptable? / 该钢管是否合格？"},
                                       "grade": {"type": "choice", "instructions": "Defect count level / 缺陷数量等级",
                                                 "criteria": {"few": "20 or fewer / 不超过 20 个", "many": "more than 20 / 超过 20 个"}}},
                         "expected": {"pass": defect <= 5.0, "grade": "many" if count > 20 else "few"}})
    rng.shuffle(rows)
    return rows


def make_encoder(texts, path):
    """随机初始化的迷你 XLMRobertaModel + 在样本上训练的 Unigram 分词器，保存成本地 HF 目录。"""
    import torch
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, trainers
    from tokenizers.processors import TemplateProcessing
    from transformers import PreTrainedTokenizerFast, XLMRobertaConfig, XLMRobertaModel

    tok = Tokenizer(models.Unigram())
    tok.normalizer = normalizers.NFKC()
    tok.pre_tokenizer = pre_tokenizers.Metaspace()
    specials = ["<s>", "<pad>", "</s>", "<unk>", "<mask>"]
    tok.train_from_iterator(list(texts) + ["yes no true false few many 合格 不合格 缺陷 数量"],
                            trainers.UnigramTrainer(vocab_size=600, special_tokens=specials, unk_token="<unk>"))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, bos_token="<s>", eos_token="</s>", pad_token="<pad>",
                                   unk_token="<unk>", mask_token="<mask>", cls_token="<s>", sep_token="</s>",
                                   model_max_length=512)
    fast.backend_tokenizer.post_processor = TemplateProcessing(
        single="<s> $A </s>", pair="<s> $A </s> </s> $B </s>",
        special_tokens=[("<s>", fast.convert_tokens_to_ids("<s>")), ("</s>", fast.convert_tokens_to_ids("</s>"))])
    cfg = XLMRobertaConfig(vocab_size=len(fast), hidden_size=64, num_hidden_layers=2, num_attention_heads=4,
                           intermediate_size=128, max_position_embeddings=514, pad_token_id=fast.pad_token_id,
                           bos_token_id=fast.bos_token_id, eos_token_id=fast.eos_token_id)
    torch.manual_seed(0)
    XLMRobertaModel(cfg).save_pretrained(path)
    fast.save_pretrained(path)
    return path


def run_cli(*args, env=None, timeout=600):
    """跑一次 decision_train.py，返回 (returncode, events, stderr)。stdout 每行必须是 JSON。"""
    proc = subprocess.run([sys.executable, TRAIN] + [str(a) for a in args], capture_output=True, text=True,
                          encoding="utf-8", env=env or ENV, timeout=timeout)
    events = []
    for line in proc.stdout.splitlines():
        if line.strip():
            events.append(json.loads(line))     # 非 JSON 行直接让测试失败
    return proc.returncode, events, proc.stderr


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(HAVE_TORCH, "torch / laya not installed")
class DecisionTrainCLITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="laya-dt-")
        cls.data = os.path.join(cls.tmp, "data.jsonl")
        rows = make_rows()
        with open(cls.data, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        cls.encoder = make_encoder([r["state"] for r in rows], os.path.join(cls.tmp, "enc"))
        cls.blank = os.path.join(cls.tmp, "blank")
        rc, events, err = run_cli("new", "--encoder", cls.encoder, "--out", cls.blank)
        assert rc == 0, err
        cls.new_events = events

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- 工具
    def _last(self, events, kind="result"):
        matching = [e for e in events if e["event"] == kind]
        self.assertTrue(matching, "no %s event in %r" % (kind, events[-3:]))
        return matching[-1]

    def _common_train_args(self, out, **over):
        args = {"--data": self.data, "--out": out, "--epochs": 1, "--micro-batch": 8, "--grad-accum": 1,
                "--loss": "soft-ce", "--amp": "off", "--grad-ckpt": "off", "--encoder-lr": "5e-4", "--head-lr": "1e-3"}
        args.update(over)
        flat = ["train"]
        for k, v in args.items():
            if v is None:
                continue
            flat.append(k)
            if v is not True:
                flat.append(str(v))
        return flat

    # ---- 测试
    def test_01_probe_and_encoders(self):
        rc, events, _ = run_cli("probe")
        self.assertEqual(rc, 0)
        r = self._last(events)
        for key in ("device", "gpu_name", "vram_mb", "torch", "cuda", "bf16", "laya", "peft", "torchvision", "tier", "recommend"):
            self.assertIn(key, r)
        self.assertIn(r["device"], ("cuda", "cpu", "mps"))
        self.assertIn(r["tier"], ("small", "base", "large"))
        self.assertIsNotNone(r["laya"])
        rc, events, _ = run_cli("encoders")
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(len(self._last(events)["encoders"]), 11)

    def test_02_new_and_info(self):
        r = self._last(self.new_events)
        self.assertEqual(r["encoder_type"], "XLMRobertaModel")
        self.assertEqual(r["hidden"], 64)
        self.assertGreater(r["params_m"], r["encoder_params_m"])
        for name in ("model.safetensors", "rl_agent_config.json", "encoder", "tokenizer", "train.json"):
            self.assertTrue(os.path.exists(os.path.join(self.blank, name)), name)
        stages = [e["stage"] for e in self.new_events if e["event"] == "progress"]
        self.assertIn("download", stages)
        rc, events, _ = run_cli("info", "--model", self.blank)
        self.assertEqual(rc, 0)
        info = self._last(events)
        self.assertEqual(info["encoder_type"], "XLMRobertaModel")
        self.assertFalse(info["fine_tuned"])
        self.assertEqual(info["max_len"], 512)
        self.assertAlmostEqual(info["params_m"], r["params_m"], places=1)
        self.assertGreater(info["size_mb"], 0)
        self.assertEqual(info["train"]["command"], "new")

    def test_03_dry_run(self):
        rc, events, _ = run_cli("train", "--data", self.data, "--base", self.blank, "--out", os.path.join(self.tmp, "dry"), "--dry-run")
        self.assertEqual(rc, 0)
        r = self._last(events)
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["rows_read"], 80)
        self.assertEqual(r["valid_items"], 160)

    def test_04_train_full_holdout_resume_evaluate(self):
        out = os.path.join(self.tmp, "m_full")
        rc, events, err = run_cli(*self._common_train_args(out, **{"--base": self.blank, "--epochs": 2, "--holdout": 0.2, "--micro-batch": 4}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(events[0]["event"], "start")
        self.assertEqual(events[0]["command"], "train")
        progress = [e for e in events if e["event"] == "progress" and e["stage"] == "train"]
        self.assertTrue(progress)
        for p in progress:
            for key in ("progress", "epoch", "epochs", "step", "steps", "loss", "lr", "eta_seconds"):
                self.assertIn(key, p)
            self.assertIsInstance(p["loss"], float)
        self.assertEqual(progress[-1]["epoch"], 2)
        self.assertEqual(progress[-1]["epochs"], 2)
        steps = progress[0]["steps"]
        gaps = [b["step"] - a["step"] for a, b in zip(progress, progress[1:]) if b["step"] > a["step"]]
        self.assertTrue(all(g <= 10 for g in gaps), gaps)
        self.assertEqual(progress[-1]["step"], steps)
        r = self._last(events)
        self.assertEqual(r["epochs_done"], 2)
        self.assertEqual(r["mode"], "full")
        self.assertEqual(len(r["epoch_loss"]), 2)
        self.assertEqual(r["holdout"]["rows"], 16)
        self.assertEqual(r["holdout"]["items"], 32)
        for key in ("noul", "choice", "score", "all"):
            self.assertIn(key, r["holdout"]["accuracy"])
        self.assertIsNone(r["holdout"]["accuracy"]["score"])
        self.assertIn("pass", r["holdout"]["per_question"])
        self.assertIn("grade", r["holdout"]["confusion"])
        self.assertIn("calibration", r)
        self.assertEqual(r["peak_vram_mb"], 0 if r["device"] == "cpu" else r["peak_vram_mb"])
        for name in ("train.json", "questions.json", "checkpoint_latest"):
            self.assertTrue(os.path.exists(os.path.join(out, name)), name)
        with open(os.path.join(out, "train.json"), encoding="utf-8") as f:
            tj = json.load(f)
        self.assertEqual(tj["epochs_done"], 2)
        self.assertEqual(tj["data"], "data.jsonl")
        self.assertEqual(tj["result"]["epochs_done"], 2)
        self.assertTrue(tj["finished"])

        # 续训：目标 3 轮 → 再训 1 轮，从 checkpoint_latest 起
        rc, events, err = run_cli(*self._common_train_args(out, **{"--epochs": 3, "--holdout": 0.2, "--micro-batch": 4, "--resume": True}))
        self.assertEqual(rc, 0, err)
        r = self._last(events)
        self.assertEqual(r["epochs_done"], 3)
        self.assertEqual(len(r["epoch_loss"]), 3)
        self.assertTrue(r["base"].endswith("checkpoint_latest"))
        progress = [e for e in events if e["event"] == "progress" and e["stage"] == "train"]
        self.assertEqual(progress[0]["epoch"], 3)
        self.assertEqual(progress[0]["epochs"], 3)
        with open(os.path.join(out, "train.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["epochs_done"], 3)
        # 没有可训的轮数 → error kind=data
        rc, events, _ = run_cli(*self._common_train_args(out, **{"--epochs": 3, "--resume": True}))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self._last(events, "error")["kind"], "data")

        # 评估
        rc, events, err = run_cli("evaluate", "--data", self.data, "--model", out)
        self.assertEqual(rc, 0, err)
        r = self._last(events)
        self.assertEqual(r["items"], 160)
        self.assertEqual(r["per_question"]["pass"]["n"], 80)
        self.assertEqual(sum(sum(v.values()) for v in r["confusion"]["grade"].values()), 80)
        self.assertIsInstance(r["accuracy"]["all"], float)

        # 训练出来的模型能被 Laya 原样加载
        from laya.train import load_checkpoint
        model, _tok, cfg = load_checkpoint(out)
        self.assertTrue(cfg["fine_tuned"])
        self.assertEqual(len(cfg["temperature"]), 3)

        # info 读到训练记录
        rc, events, _ = run_cli("info", "--model", out)
        info = self._last(events)
        self.assertTrue(info["fine_tuned"])
        self.assertEqual(info["train"]["epochs_done"], 3)
        self.assertTrue(info["has_latest"])
        self.assertEqual(sorted(info["questions"]), ["grade", "pass"])

    def test_05_train_freeze(self):
        out = os.path.join(self.tmp, "m_freeze")
        rc, events, err = run_cli(*self._common_train_args(out, **{"--base": self.blank, "--mode": "freeze"}))
        self.assertEqual(rc, 0, err)
        r = self._last(events)
        self.assertEqual(r["mode"], "freeze")
        self.assertGreater(r["frozen_params_m"], 0)

    @unittest.skipUnless(HAVE_PEFT, "peft not installed")
    def test_06_train_lora_saves_plain_checkpoint(self):
        out = os.path.join(self.tmp, "m_lora")
        rc, events, err = run_cli(*self._common_train_args(out, **{"--base": self.blank, "--mode": "lora", "--lora-r": 4, "--holdout": 0.1}))
        self.assertEqual(rc, 0, err)
        r = self._last(events)
        self.assertEqual(r["mode"], "lora")
        self.assertEqual(r["lora_targets"], ["query", "key", "value", "dense"])
        self.assertGreater(r["trainable_params_m"], 0)
        from laya.train import load_checkpoint
        for path in (out, os.path.join(out, "checkpoint_latest")):
            model, _tok, _cfg = load_checkpoint(path)          # strict=True
            keys = list(model.state_dict())
            self.assertFalse(any("lora" in k for k in keys), path)
            self.assertEqual(type(model.encoder).__name__, "XLMRobertaModel")
        import laya
        laya.load(out)

    def test_07_lora_without_peft(self):
        out = os.path.join(self.tmp, "m_nopeft")
        code = ("import sys; sys.modules['peft'] = None; sys.path.insert(0, %r); import decision_train as d; "
                "sys.exit(d.main(%r))" % (APP, self._common_train_args(out, **{"--base": self.blank, "--mode": "lora"})))
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=300)
        self.assertNotEqual(proc.returncode, 0)
        last = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(last["event"], "error")
        self.assertIn("peft", last["message"])

    def test_08_oom_backoff(self):
        out = os.path.join(self.tmp, "m_oom")
        env = dict(ENV, LAYA_WB_FAKE_OOM="3")
        rc, events, err = run_cli(*self._common_train_args(out, **{"--base": self.blank, "--micro-batch": 4, "--grad-accum": 2}), env=env)
        self.assertEqual(rc, 0, err)
        ooms = [e for e in events if e["event"] == "oom"]
        self.assertEqual([(o["retry"], o["micro_batch"], o["grad_accum"], o["max_len"]) for o in ooms],
                         [(1, 2, 4, 512), (2, 1, 8, 512), (3, 1, 8, 384)])
        r = self._last(events)
        self.assertEqual((r["micro_batch"], r["grad_accum"], r["max_len"], r["oom_retries"]), (1, 8, 384, 3))
        # 降无可降 → error kind=oom
        env = dict(ENV, LAYA_WB_FAKE_OOM="99")
        rc, events, _ = run_cli(*self._common_train_args(os.path.join(self.tmp, "m_oom2"),
                                                         **{"--base": self.blank, "--micro-batch": 1, "--max-len": 256}), env=env)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self._last(events, "error")["kind"], "oom")

    def test_09_errors(self):
        rc, events, _ = run_cli("train", "--data", self.data, "--base", os.path.join(self.tmp, "nope"), "--out", os.path.join(self.tmp, "x"))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self._last(events, "error")["kind"], "data")
        bad = os.path.join(self.tmp, "bad.jsonl")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(json.dumps({"state": "x", "questions": {"q": {"type": "choice", "instructions": "?", "criteria": {"a": "", "b": ""}}}, "expected": {"q": "zzz"}}) + "\n")
        rc, events, _ = run_cli("train", "--data", bad, "--base", self.blank, "--out", os.path.join(self.tmp, "x2"), "--amp", "off")
        self.assertNotEqual(rc, 0)
        e = self._last(events, "error")
        self.assertEqual(e["kind"], "data")
        self.assertIn("invalid_target", e["message"])


@unittest.skipUnless(HAVE_TORCH, "torch / laya not installed")
class DecisionServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="laya-ds-")
        rows = make_rows(n_pairs=10)
        data = os.path.join(cls.tmp, "data.jsonl")
        with open(data, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        enc = make_encoder([r["state"] for r in rows], os.path.join(cls.tmp, "enc"))
        cls.ckpt = os.path.join(cls.tmp, "demo")
        rc, _ev, err = run_cli("new", "--encoder", enc, "--out", cls.ckpt)
        assert rc == 0, err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _start(self, *extra):
        port = free_port()
        proc = subprocess.Popen([sys.executable, SERVER, "--port", str(port), "--device", "cpu",
                                 "--custom", "demo=" + self.ckpt, "--default", "demo"] + list(extra),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=ENV)
        deadline = time.time() + 180
        while time.time() < deadline:
            if proc.poll() is not None:
                self.fail("server exited: %s" % proc.stderr.read()[-2000:])
            try:
                self._get(port, "/health")
                return proc, port
            except (urllib.error.URLError, ConnectionError, socket.timeout):
                time.sleep(0.3)
        proc.kill()
        self.fail("server did not come up")

    @staticmethod
    def _get(port, path):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=30) as r:
            return json.loads(r.read())

    @staticmethod
    def _post(port, body):
        req = urllib.request.Request("http://127.0.0.1:%d/v1/systemone" % port, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def _stop(self, proc):
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        err = proc.stderr.read()
        proc.stderr.close()
        return err

    Q = {"pass": {"type": "noul", "instructions": "Is the pipe acceptable?"}}

    def test_pinned_custom_only(self):
        proc, port = self._start("--pin-default", "--builtin", "")
        try:
            health = self._get(port, "/health")
            self.assertEqual(health["status"], "ok")
            self.assertEqual(health["loaded"], ["demo"])
            models = self._get(port, "/v1/models")
            self.assertEqual([m["id"] for m in models["data"]], ["demo"])
            self.assertTrue(models["data"][0]["custom"] and models["data"][0]["loaded"] and models["data"][0]["default"])
            self.assertEqual(models["data"][0]["source"], self.ckpt)
            for body in ({"state": "defect ratio 8%", "questions": self.Q, "model": "demo"},
                         {"state": "defect ratio 8%", "questions": self.Q, "model": "jev-1"},
                         {"state": "defect ratio 8%", "questions": self.Q},
                         {"state": "钢管表面检测：缺陷占比 8.3%，缺陷数量 31 个。", "questions": self.Q},
                         {"state": "钢管表面检测", "questions": self.Q, "model": "multilingual"}):
                status, r = self._post(port, body)
                self.assertEqual(status, 200, r)
                self.assertIn("pass", r["answers"])
                reason = r["routing"]["reason"]
                self.assertTrue("demo" in reason, reason)
            self.assertEqual(self._get(port, "/health")["loaded"], ["demo"])   # 没有偷偷加载别的
            status, r = self._post(port, {"state": "x", "questions": self.Q, "model": "/some/path"})
            self.assertEqual(status, 422)
        finally:
            err = self._stop(proc)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("snapshot_download", err)

    def test_builtin_registered_lazily(self):
        proc, port = self._start("--builtin", "multilingual")
        try:
            models = self._get(port, "/v1/models")
            by_id = {m["id"]: m for m in models["data"]}
            self.assertEqual(set(by_id), {"demo", "multilingual"})
            self.assertFalse(by_id["multilingual"]["loaded"])
            self.assertFalse(by_id["multilingual"]["custom"])
            self.assertTrue(by_id["demo"]["default"])
            status, r = self._post(port, {"state": "defect ratio 8%", "questions": self.Q, "model": "demo"})
            self.assertEqual(status, 200)
            self.assertIn("explicit model='demo'", r["routing"]["reason"])
            # 未指定 model 的拉丁文本：语言识别不出 → 默认模型 demo，不碰官方权重
            status, r = self._post(port, {"state": "defect ratio 8%", "questions": self.Q})
            self.assertEqual(status, 200)
            self.assertIn("demo", r["routing"]["reason"])
            self.assertEqual(self._get(port, "/health")["loaded"], ["demo"])
        finally:
            err = self._stop(proc)
        self.assertNotIn("snapshot_download", err)      # 启动和以上请求都没有去下载


if __name__ == "__main__":
    unittest.main()
