# -*- coding: utf-8 -*-
"""决策训练的数据集 / 任务管理测试（decision_jobs）和启动器的 /v1/decision/* 接口测试。

子进程用 tests/fake_decision_train.py 顶替真的训练脚本，所以不需要 torch / laya。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
FAKE = os.path.join(ROOT, "tests", "fake_decision_train.py")

DATA = tempfile.mkdtemp(prefix="laya-workbench-decision-")
os.environ["LAYA_WB_DATA"] = DATA
os.environ["LAYA_WB_CONFIG"] = os.path.join(DATA, "config.json")
os.environ["LAYA_WB_LANG"] = "zh"
os.environ["LAYA_WB_DECISION_CLI"] = FAKE

import decision_jobs as DJ  # noqa: E402
import launcher  # noqa: E402

ROW = {"state": "钢管表面检测：缺陷占比 8.3%，缺陷数量 31 个。",
       "questions": {"pass": {"type": "noul", "instructions": "该钢管是否合格？"},
                     "grade": {"type": "choice", "instructions": "缺陷数量等级", "criteria": {"few": "不超过 20 个", "many": "超过 20 个"}},
                     "score": {"type": "score", "instructions": "外观评分", "levels": ["差", "中", "好"]}},
       "expected": {"pass": False, "grade": "many", "score": 1}}


def wait_job(store, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get_job(job_id)
        if job["state"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("job %s did not finish: %s" % (job_id, store.get_job(job_id)))


class PureTest(unittest.TestCase):
    def test_parse_event(self):
        self.assertEqual(DJ.parse_event('{"event":"log","message":"x"}')["message"], "x")
        self.assertEqual(DJ.parse_event(b'{"event":"progress","progress":0.5}\n')["progress"], 0.5)
        self.assertIsNone(DJ.parse_event("plain text"))
        self.assertIsNone(DJ.parse_event('{"no_event": 1}'))
        self.assertIsNone(DJ.parse_event("{broken"))

    def test_valid_name(self):
        for ok in ("steel", "钢管-v2", "a.b_c", "x" * 64):
            self.assertTrue(DJ.valid_name(ok), ok)
        for bad in ("", "..", "a/b", "a b", ".hidden", "x" * 65, "a\\b"):
            self.assertFalse(DJ.valid_name(bad), bad)

    def test_validate_row_normalizes(self):
        row = DJ.validate_row(dict(ROW, expected={"pass": "否", "grade": "many", "score": "中"}))
        self.assertEqual(row["expected"], {"pass": False, "grade": "many", "score": 1})
        self.assertEqual(row["questions"]["score"]["levels"], ["差", "中", "好"])
        self.assertEqual(row["questions"]["score"]["criteria"], ["差", "中", "好"])     # Laya 原生写法也一并写上
        # score 的等级给成 criteria 列表、choice 给成列表，也认
        alt = {"state": "s", "questions": {"s": {"type": "score", "instructions": "q", "criteria": ["a", "b"]}, "c": {"type": "choice", "instructions": "q", "criteria": ["x", "y"]}},
               "expected": {"s": 1, "c": "y"}}
        row = DJ.validate_row(alt)
        self.assertEqual(row["questions"]["s"]["levels"], ["a", "b"])
        self.assertEqual(row["questions"]["c"]["criteria"], {"x": None, "y": None})
        # 没有答案的题目被丢掉
        row = DJ.validate_row(dict(ROW, expected={"pass": True}))
        self.assertEqual(list(row["questions"]), ["pass"])

    def test_validate_row_errors(self):
        cases = [
            ("not a dict", "JSON 对象"),
            ({"state": "", "questions": ROW["questions"], "expected": ROW["expected"]}, "素材"),
            ({"state": "x", "questions": {}, "expected": {}}, "questions"),
            ({"state": "x", "questions": ROW["questions"]}, "expected"),
            ({"state": "x", "questions": {"q": {"type": "maybe", "instructions": "?"}}, "expected": {"q": 1}}, "noul / choice / score"),
            ({"state": "x", "questions": {"q": {"type": "noul"}}, "expected": {"q": True}}, "instructions"),
            ({"state": "x", "questions": {"q": {"type": "choice", "instructions": "?", "criteria": {"a": ""}}}, "expected": {"q": "a"}}, "至少 2 个选项"),
            ({"state": "x", "questions": {"q": {"type": "score", "instructions": "?", "levels": ["a"]}}, "expected": {"q": 0}}, "至少 2 个等级"),
            ({"state": "x", "questions": {"q": {"type": "noul", "instructions": "?"}}, "expected": {"q": "maybe"}}, "不是是 / 否"),
            ({"state": "x", "questions": {"q": {"type": "choice", "instructions": "?", "criteria": {"a": "", "b": ""}}}, "expected": {"q": "c"}}, "不在选项"),
            ({"state": "x", "questions": {"q": {"type": "score", "instructions": "?", "levels": ["a", "b"]}}, "expected": {"q": 5}}, "等级下标"),
            ({"state": "x", "questions": ROW["questions"], "expected": {"other": 1}}, "没有一道题目"),
        ]
        for row, fragment in cases:
            with self.assertRaises(DJ.RowError) as caught:
                DJ.validate_row(row, "zh")
            self.assertIn(fragment, str(caught.exception), row)
        with self.assertRaises(DJ.RowError) as caught:
            DJ.validate_row({"state": "x", "questions": {"q": {"type": "noul"}}, "expected": {"q": True}}, "en")
        self.assertIn("no instructions", str(caught.exception))

    def test_gold_to_expected(self):
        rec = {"state": "s", "questions": ROW["questions"], "gold": {"pass": {"answer": True}, "grade": "few", "score": {"probabilities": {"0": 0.1, "2": 0.8}}}}
        out = DJ.gold_to_expected(rec)
        self.assertNotIn("gold", out)
        self.assertEqual(out["expected"], {"pass": True, "grade": "few", "score": "2"})
        row = DJ.validate_row(rec)
        self.assertEqual(row["expected"], {"pass": True, "grade": "few", "score": 2})

    def test_csv_to_rows(self):
        text = "text,label\n这个产品很好,正面\n太差了,负面\n,忽略\n再买一次,正面\n"
        rows, labels = DJ.csv_to_rows(text, "text", "label", "sentiment", "这条评价的情绪是？")
        self.assertEqual(labels, ["正面", "负面"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["questions"]["sentiment"]["criteria"], {"正面": None, "负面": None})
        self.assertEqual(rows[1]["expected"], {"sentiment": "负面"})
        self.assertEqual(rows[0]["questions"]["sentiment"]["instructions"], "这条评价的情绪是？")
        with self.assertRaises(DJ.RowError) as caught:
            DJ.csv_to_rows("a,b\n1,2\n", "text", "label")
        self.assertIn("找不到列", str(caught.exception))
        with self.assertRaises(DJ.RowError):
            DJ.csv_to_rows("text,label\nx,only\ny,only\n")

    def test_merge_template(self):
        tpl = DJ.merge_template({}, {"a": {"type": "noul", "instructions": "1"}})
        tpl = DJ.merge_template(tpl, {"a": {"type": "noul", "instructions": "changed"}, "b": {"type": "noul", "instructions": "2"}})
        self.assertEqual(tpl["a"]["instructions"], "1")
        self.assertEqual(sorted(tpl), ["a", "b"])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="laya-store-")
        self.store = DJ.Store(self.dir, lang=lambda: "zh", cli=FAKE)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_dataset_round_trip(self):
        meta = self.store.create_dataset("steel", "钢管", "备注")
        self.assertEqual(meta["rows"], 0)
        with self.assertRaises(DJ.DJError) as caught:
            self.store.create_dataset("steel")
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(DJ.DJError):
            self.store.create_dataset("bad/name")
        out = self.store.append_rows("steel", [ROW, dict(ROW, expected={"pass": True, "grade": "few", "score": "好"})])
        self.assertEqual(out["rows"], 2)
        self.assertEqual(sorted(out["questions"]), ["grade", "pass", "score"])
        with self.assertRaises(DJ.DJError) as caught:
            self.store.append_rows("steel", [dict(ROW, expected={"pass": "maybe"})])
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("第 1 行", caught.exception.detail)
        listed = self.store.list_datasets()
        self.assertEqual([(d["name"], d["rows"], d["title"]) for d in listed], [("steel", 2, "钢管")])
        # 导入 JSONL（含一行坏的和一行 gold 格式）
        text = json.dumps(ROW, ensure_ascii=False) + "\n{broken\n" + json.dumps({"state": "s", "questions": ROW["questions"], "gold": {"pass": {"answer": False}}}, ensure_ascii=False) + "\n"
        out = self.store.import_text("steel", "jsonl", text)
        self.assertEqual((out["added"], out["skipped_total"]), (2, 1))
        self.assertIn("第 2 行", out["skipped"][0]["error"])
        # CSV 导入到一个新数据集
        out = self.store.import_text("reviews", "csv", "text,label\n好,正面\n差,负面\n", {"text_column": "text", "label_column": "label", "question": "mood"})
        self.assertEqual(out["added"], 2)
        self.assertEqual(out["labels"], ["正面", "负面"])
        self.assertEqual(self.store.rows("reviews")["items"][0]["row"]["expected"], {"mood": "正面"})
        # 分页
        page = self.store.rows("steel", offset=1, limit=2)
        self.assertEqual((page["total"], page["offset"], [i["index"] for i in page["items"]]), (4, 1, [1, 2]))
        # 导出
        lines = [json.loads(l) for l in self.store.export_text("steel").splitlines()]
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(set(l) == {"state", "questions", "expected"} for l in lines))
        # 删一行 → 模板重建
        out = self.store.delete("steel", 3)
        self.assertEqual(out["rows"], 3)
        self.assertEqual(sorted(out["questions"]), ["grade", "pass", "score"])
        with self.assertRaises(DJ.DJError):
            self.store.delete("steel", 99)
        # 删整个数据集
        self.store.delete("steel")
        self.assertEqual([d["name"] for d in self.store.list_datasets()], ["reviews"])
        with self.assertRaises(DJ.DJError) as caught:
            self.store.rows("steel")
        self.assertEqual(caught.exception.status, 404)

    def test_import_gold_records(self):
        recs = [{"state": "s1", "questions": ROW["questions"], "gold": {"pass": {"answer": True}}}, {"state": "s2", "questions": ROW["questions"], "gold": {}}]
        out = self.store.import_rows("from-reviews", recs)
        self.assertEqual((out["added"], out["skipped_total"]), (1, 1))
        with self.assertRaises(DJ.DJError):
            self.store.import_rows("none", [{"state": "x"}])

    def test_env_without_torch(self):
        env = self.store.env()
        self.assertIn("probe", env)
        self.assertIn("encoders", env)
        self.assertTrue(any(e["id"] == "intfloat/multilingual-e5-small" for e in env["encoders"]))   # 内置表或假脚本的列表都有它
        self.assertEqual(set(env["installed"]), {"torch", "laya", "peft", "torchvision"})
        self.assertTrue(env["cli"])

    def test_job_runner(self):
        self.store.create_dataset("ds")
        self.store.append_rows("ds", [ROW] * 3)
        hooks = []
        self.store.before_start = lambda kind: hooks.append("before:" + kind)
        self.store.after_finish = lambda kind: hooks.append("after:" + kind)
        env_backup = dict(os.environ)
        os.environ["FAKE_DECISION_STEPS"] = "4"
        try:
            # 没装 torch 时 start_train 会拒绝；这里直接用底层 start 测契约
            job = self.store.start("train", ["--data", str(self.store.dataset_path("ds")), "--base", "multilingual", "--out", str(self.store.models_dir / "m1"), "--epochs", "2"], {"name": "m1"})
            self.assertEqual(job["kind"], "train")
            self.assertIn(job["state"], ("queued", "running"))
            with self.assertRaises(DJ.DJError) as caught:
                self.store.start("evaluate", ["--data", "x", "--model", "y"])
            self.assertEqual(caught.exception.status, 409)
            done = wait_job(self.store, job["id"])
            self.assertEqual(done["state"], "done", done)
            self.assertEqual(done["progress"], 1.0)
            self.assertEqual(done["result"]["epochs_done"], 2)
            self.assertEqual((done["epoch"], done["epochs"], done["step"], done["steps"]), (2, 2, 4, 4))
            self.assertEqual(done["stage"], "save")
            self.assertTrue(len(done["loss_curve"]) >= 8)
            self.assertTrue(any("plain text" not in l and "loaded 3 rows" in l for l in done["log_tail"]))
            self.assertTrue(os.path.isfile(done["log_file"]))
            with open(done["log_file"], encoding="utf-8") as handle:
                self.assertIn("loaded 3 rows", handle.read())
            for key in ("id", "kind", "state", "progress", "stage", "epoch", "epochs", "step", "steps", "loss", "eta_seconds", "log_tail", "result", "error", "started", "seconds"):
                self.assertIn(key, done)
            self.assertEqual(hooks, ["before:train", "after:train"])
            # 模型目录被假脚本写出来了 → 模型列表能读到
            models = self.store.list_models()
            self.assertEqual([m["name"] for m in models], ["m1"])
            self.assertTrue(models[0]["fine_tuned"])
            self.assertEqual(models[0]["accuracy"], 0.88)
            self.assertEqual(self.store.model_info("m1")["result"]["epochs_done"], 2)
            # 出错路径（含 oom 事件 + 非 JSON 行）
            os.environ["FAKE_DECISION_FAIL"] = "1"
            os.environ["FAKE_DECISION_OOM"] = "1"
            job = self.store.start("train", ["--data", str(self.store.dataset_path("ds")), "--base", "m1", "--out", str(self.store.models_dir / "m2")], {"name": "m2"})
            done = wait_job(self.store, job["id"])
            self.assertEqual(done["state"], "error")
            self.assertIn("simulated", done["error"])
            self.assertEqual(done["oom"], 1)
            self.assertTrue(any("显存不足" in l for l in done["log_tail"]))
            del os.environ["FAKE_DECISION_FAIL"]
            del os.environ["FAKE_DECISION_OOM"]
            job = self.store.start("new", ["--encoder", "e", "--out", str(self.store.models_dir / "m3")], {"name": "m3"})
            done = wait_job(self.store, job["id"])
            self.assertEqual(done["state"], "done")
            self.assertTrue(any("plain text line" in l for l in done["log_tail"]))
            # 取消
            os.environ["FAKE_DECISION_DELAY"] = "0.3"
            job = self.store.start("train", ["--data", str(self.store.dataset_path("ds")), "--base", "multilingual", "--out", str(self.store.models_dir / "m4"), "--epochs", "5"], {"name": "m4"})
            time.sleep(0.8)
            self.store.cancel(job["id"])
            done = wait_job(self.store, job["id"])
            self.assertEqual(done["state"], "cancelled")
            self.assertEqual(len(hooks), 8)
            # 删模型
            self.store.delete_model("m1")
            self.assertNotIn("m1", self.store.model_names())
            with self.assertRaises(DJ.DJError) as caught:
                self.store.delete_model("m1")
            self.assertEqual(caught.exception.status, 404)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_start_train_validation(self):
        self.store.create_dataset("ds")
        if self.store.installed()["torch"]:
            self.skipTest("torch installed; validation path differs")
        with self.assertRaises(DJ.DJError) as caught:
            self.store.start_train({"name": "x", "base": "multilingual", "dataset": "ds"})
        self.assertEqual(caught.exception.status, 503)


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        launcher.DJ._cli = FAKE

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(DATA, ignore_errors=True)

    def call(self, path, body=None, lang="zh"):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "X-WB-Lang": lang}, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw, status, ctype = resp.read(), resp.status, resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            raw, status, ctype = error.read(), error.code, error.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return status, json.loads(raw.decode("utf-8"))
        return status, raw.decode("utf-8")

    def test_status_and_pages(self):
        status, page = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn('data-view="decision"', page)
        self.assertIn("/_wb/decision.js", page)
        self.assertIn("laya-opencv", page)
        status, js = self.call("/_wb/decision.js")
        self.assertEqual(status, 200)
        self.assertIn("window.WBD", js)
        status, st = self.call("/_wb/status")
        self.assertEqual(st["version"], "3.0")
        dec = st["decision"]
        for key in ("active", "custom_models", "training", "paused"):
            self.assertIn(key, dec)
        self.assertEqual(dec["training"], None)
        self.assertFalse(dec["paused"])
        self.assertEqual(launcher.VERSION, "3.0")

    def test_dataset_round_trip_over_http(self):
        status, out = self.call("/v1/decision/datasets/create", {"name": "http-ds", "title": "HTTP"})
        self.assertEqual(status, 200)
        status, out = self.call("/v1/decision/datasets/create", {"name": "http-ds"})
        self.assertEqual(status, 409)
        self.assertIn("已经存在", out["detail"])
        status, out = self.call("/v1/decision/datasets/create", {"name": "bad name"}, lang="en")
        self.assertEqual(status, 400)
        self.assertIn("Invalid name", out["detail"])
        status, out = self.call("/v1/decision/datasets/append", {"name": "http-ds", "rows": [ROW, ROW]})
        self.assertEqual((status, out["rows"]), (200, 2))
        status, out = self.call("/v1/decision/datasets/import", {"name": "http-ds", "format": "csv", "text": "text,label\na,x\nb,y\n", "csv": {"question": "cls"}})
        self.assertEqual((status, out["added"]), (200, 2))
        status, out = self.call("/v1/decision/datasets")
        self.assertEqual([(d["name"], d["rows"]) for d in out], [("http-ds", 4)])
        status, out = self.call("/v1/decision/datasets/rows?name=http-ds&offset=2&limit=1")
        self.assertEqual((out["total"], out["items"][0]["index"]), (4, 2))
        status, out = self.call("/v1/decision/datasets/export?name=http-ds")
        self.assertEqual(status, 200)
        self.assertEqual(len(out.strip().splitlines()), 4)
        status, out = self.call("/v1/decision/datasets/delete", {"name": "http-ds", "index": 0})
        self.assertEqual((status, out["rows"]), (200, 3))
        # from_reviews 复用 export_finetune
        status, out = self.call("/v1/decision/datasets/from_reviews", {"name": "from-recipe", "recipe": "steel-pipe"})
        self.assertEqual(status, 200, out)
        self.assertGreater(out["added"], 10)
        status, out = self.call("/v1/decision/datasets/from_reviews", {"name": "from-recipe", "recipe": "no-such"})
        self.assertEqual(status, 404)
        status, out = self.call("/v1/decision/datasets/delete", {"name": "http-ds"})
        self.assertEqual(status, 200)
        self.call("/v1/decision/datasets/delete", {"name": "from-recipe"})

    def test_env_models_jobs(self):
        status, env = self.call("/v1/decision/env")
        self.assertEqual(status, 200)
        self.assertIn("encoders", env)
        self.assertIn("installed", env)
        status, models = self.call("/v1/decision/models")
        self.assertEqual((status, models), (200, []))
        status, out = self.call("/v1/decision/models/info?name=nope")
        self.assertEqual(status, 404)
        status, out = self.call("/v1/decision/jobs?id=nope")
        self.assertEqual(status, 404)
        status, out = self.call("/v1/decision/jobs")
        self.assertEqual(status, 200)
        status, out = self.call("/v1/decision/models/activate", {"name": "nope"})
        self.assertEqual(status, 404)
        # 建一个假模型目录 → 自定义模型名进入 is_laya_model / list_models / status
        model_dir = os.path.join(str(launcher.DATA), "decision", "models", "my-custom")   # launcher 可能已被别的测试先导入
        os.makedirs(model_dir, exist_ok=True)
        with open(os.path.join(model_dir, "rl_agent_config.json"), "w", encoding="utf-8") as f:
            json.dump({"encoder": "x", "fine_tuned": True}, f)
        with open(os.path.join(model_dir, "model.safetensors"), "wb") as f:
            f.write(b"\0" * 16)
        self.assertTrue(launcher.is_laya_model("my-custom"))
        self.assertTrue(launcher.is_laya_model("MY-Custom"))
        self.assertFalse(launcher.is_laya_model("jev-latest"))
        self.assertIn("my-custom", launcher.list_models("local")[0])
        status, st = self.call("/_wb/status")
        self.assertEqual(st["decision"]["custom_models"], ["my-custom"])
        status, models = self.call("/v1/decision/models")
        self.assertEqual([(m["name"], m["active"], m["loaded"]) for m in models], [("my-custom", False, False)])
        args, default = launcher.decision_server_args()
        self.assertIn("--custom", args)
        self.assertEqual(default, "multilingual")
        # 设为默认：写 config.json；服务不是我们拉起的，所以不会重启
        status, out = self.call("/v1/decision/models/activate", {"name": "my-custom"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["active"], "my-custom")
        self.assertEqual(json.load(open(str(launcher.CONFIG_FILE), encoding="utf-8"))["decision_active"], "my-custom")
        args, default = launcher.decision_server_args()
        self.assertEqual(default, "my-custom")
        self.assertIn("--pin-default", args)
        status, models = self.call("/v1/decision/models")
        self.assertTrue(models[0]["active"])
        status, out = self.call("/v1/decision/models/activate", {"name": ""})
        self.assertEqual(out["active"], None)
        status, out = self.call("/v1/decision/models/delete", {"name": "my-custom"})
        self.assertEqual(status, 200)
        self.assertFalse(launcher.is_laya_model("my-custom"))

    def test_pause_and_resume_around_training(self):
        """训练前暂停本启动器拉起的模型服务（用一个 sleep 子进程顶替），训练后恢复。"""
        import subprocess
        started = []
        real_start, real_child, real_mode = launcher.start_laya, launcher.CHILD, dict(launcher.SERVICE)
        dummy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        launcher.CHILD = dummy
        launcher.SERVICE["mode"] = "running"
        launcher.start_laya = lambda: (started.append(1), launcher.SERVICE.__setitem__("mode", "starting"))
        try:
            if launcher.DJ.gpu_file.exists():                    # 别的测试可能已经探测过（CPU）；这里要的是「设备不明」的情况
                launcher.DJ.gpu_file.unlink()
            self.assertTrue(launcher.needs_pause())              # 没有探测结果 → 按需要暂停处理
            launcher.before_job("train")
            self.assertEqual(launcher.SERVICE["mode"], "paused")
            self.assertIsNotNone(dummy.poll())                  # 子进程已被结束
            status, raw, _ = launcher.call_local("/health", timeout=0.5)
            self.assertEqual(status, 503)
            self.assertIn("已暂停", json.loads(raw.decode("utf-8"))["detail"])
            status, st = self.call("/_wb/status")
            self.assertTrue(st["decision"]["paused"])
            self.assertEqual(st["service"], "paused")
            launcher.after_job("train")
            self.assertEqual(started, [1])
            self.assertEqual(launcher.SERVICE["mode"], "starting")
            # 服务不是我们拉起的（external）时不暂停
            launcher.SERVICE["mode"] = "external"
            launcher.CHILD = None
            launcher.before_job("train")
            self.assertEqual(launcher.SERVICE["mode"], "external")
            launcher.after_job("train")
            self.assertEqual(started, [1])
        finally:
            if dummy.poll() is None:
                dummy.kill()
            dummy.wait()
            launcher.start_laya, launcher.CHILD = real_start, real_child
            launcher.SERVICE.update(real_mode)

    def test_train_over_http_with_fake(self):
        if launcher.DJ.installed()["torch"]:
            real = launcher.DJ.installed
            launcher.DJ.installed = lambda: dict(real(), torch=True)
        else:
            real = launcher.DJ.installed
            launcher.DJ.installed = lambda: dict(real(), torch=True)   # 假脚本不需要 torch，绕过检查
        try:
            self.call("/v1/decision/datasets/create", {"name": "tr-ds"})
            self.call("/v1/decision/datasets/append", {"name": "tr-ds", "rows": [ROW] * 4})
            status, out = self.call("/v1/decision/train", {"name": "http-model", "base": "multilingual", "dataset": "tr-ds", "mode": "lora", "epochs": 1, "holdout": 0.1})
            self.assertEqual(status, 200, out)
            job_id = out["id"]
            status, out = self.call("/v1/decision/train", {"name": "http-model2", "base": "multilingual", "dataset": "tr-ds"})
            self.assertEqual(status, 409)
            status, st = self.call("/_wb/status")
            self.assertEqual(st["decision"]["training"], job_id)
            status, out = self.call("/v1/decision/models/activate", {"name": ""})
            self.assertEqual(status, 409)
            done = wait_job(launcher.DJ, job_id)
            self.assertEqual(done["state"], "done", done)
            status, job = self.call("/v1/decision/jobs?id=" + job_id)
            self.assertEqual(job["state"], "done")
            self.assertEqual(job["result"]["mode"], "lora")
            status, models = self.call("/v1/decision/models")
            self.assertEqual([m["name"] for m in models], ["http-model"])
            # 同名再训且不续训 → 409；续训 → 可以
            status, out = self.call("/v1/decision/train", {"name": "http-model", "base": "multilingual", "dataset": "tr-ds"})
            self.assertEqual(status, 409)
            status, out = self.call("/v1/decision/evaluate", {"model": "http-model", "dataset": "tr-ds"})
            self.assertEqual(status, 200, out)
            done = wait_job(launcher.DJ, out["id"])
            self.assertEqual(done["result"]["accuracy"]["all"], 0.86)
            status, out = self.call("/v1/decision/new", {"name": "blank", "encoder": "intfloat/multilingual-e5-small"})
            self.assertEqual(status, 200, out)
            done = wait_job(launcher.DJ, out["id"])
            self.assertEqual(done["state"], "done")
            status, out = self.call("/v1/decision/train", {"name": "x", "base": "multilingual", "dataset": "tr-ds", "mode": "weird"})
            self.assertEqual(status, 400)
            status, out = self.call("/v1/decision/train", {"name": "x", "base": "multilingual", "dataset": "tr-ds", "epochs": "abc"})
            self.assertEqual(status, 400)
            status, out = self.call("/v1/decision/jobs/cancel", {"id": job_id})
            self.assertEqual(status, 200)                      # 已结束的任务：取消是空操作
        finally:
            launcher.DJ.installed = real
            self.call("/v1/decision/models/delete", {"name": "http-model"})
            self.call("/v1/decision/models/delete", {"name": "blank"})
            self.call("/v1/decision/datasets/delete", {"name": "tr-ds"})


if __name__ == "__main__":
    unittest.main()
