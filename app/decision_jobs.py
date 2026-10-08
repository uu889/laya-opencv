# -*- coding: utf-8 -*-
"""决策模型训练的数据集 / 模型 / 后台任务管理（只用标准库，由 launcher 导入）。

真正需要 torch 的工作都在子进程 `app/decision_train.py` 里完成（见 docs/CONTRACT.md §2）；
这里只负责：
  1. 数据集：data/decision/datasets/<name>.jsonl（Laya 原生 {state, questions, expected}）+ <name>.meta.json
  2. 模型目录：data/decision/models/<name>/（Laya 格式 checkpoint）
  3. 任务：拉起子进程，逐行解析 stdout 里的 JSON 事件流，更新任务状态，日志落盘 data/decision/jobs/<id>.log
  4. 环境探测：probe 结果缓存到 data/decision/gpu.json

子进程脚本的位置可以用环境变量 LAYA_WB_DECISION_CLI 覆盖（测试时指向 tests/fake_decision_train.py）。
"""
import copy
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
TYPES = ("noul", "choice", "score")
OFFICIAL = ("multilingual", "english", "typed-decisions")
OFFICIAL_REPOS = {"multilingual": "convaiinnovations/laya-multilingual", "english": "convaiinnovations/laya",
                  "typed-decisions": "convaiinnovations/laya-typed-decisions"}
JOB_KINDS = ("new", "train", "evaluate")
LOG_TAIL = 60
KEEP_JOBS = 30
TRUE_WORDS = ("true", "1", "yes", "y", "是", "对", "合格", "通过")
FALSE_WORDS = ("false", "0", "no", "n", "否", "不是", "不合格", "不通过")

# 没装 torch、或者子进程脚本还不存在时，页面仍然要能列出推荐编码器（和 CONTRACT §2 的内置表一致）
BUILTIN_ENCODERS = [
    {"id": "intfloat/multilingual-e5-small", "tier": "small", "params_m": 118, "langs": "multi",
     "note_zh": "多语，4G 显卡的默认选择", "note_en": "Multilingual; the default for 4 GB GPUs"},
    {"id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "tier": "small", "params_m": 118, "langs": "multi",
     "note_zh": "多语，句向量模型", "note_en": "Multilingual sentence-embedding model"},
    {"id": "BAAI/bge-small-zh-v1.5", "tier": "small", "params_m": 24, "langs": "zh", "note_zh": "中文，最小", "note_en": "Chinese; smallest"},
    {"id": "BAAI/bge-base-zh-v1.5", "tier": "base", "params_m": 102, "langs": "zh", "note_zh": "中文", "note_en": "Chinese"},
    {"id": "intfloat/multilingual-e5-base", "tier": "base", "params_m": 278, "langs": "multi", "note_zh": "多语", "note_en": "Multilingual"},
    {"id": "jhu-clsp/mmBERT-base", "tier": "base", "params_m": 307, "langs": "multi",
     "note_zh": "多语，Laya multilingual 用的底座", "note_en": "Multilingual; the base of Laya multilingual"},
    {"id": "answerdotai/ModernBERT-base", "tier": "base", "params_m": 149, "langs": "en", "note_zh": "英文", "note_en": "English"},
    {"id": "answerdotai/ModernBERT-large", "tier": "large", "params_m": 395, "langs": "en", "note_zh": "英文，大", "note_en": "English; large"},
    {"id": "convaiinnovations/laya-multilingual", "tier": "base", "params_m": 307, "langs": "multi", "official": True,
     "note_zh": "官方 Laya 多语权重（微调起点）", "note_en": "Official Laya multilingual weights (fine-tuning start)"},
    {"id": "convaiinnovations/laya", "tier": "large", "params_m": 395, "langs": "en", "official": True,
     "note_zh": "官方 Laya 英文权重（微调起点）", "note_en": "Official Laya English weights (fine-tuning start)"},
    {"id": "convaiinnovations/laya-typed-decisions", "tier": "large", "params_m": 395, "langs": "en", "official": True,
     "note_zh": "官方 Laya typed-decisions 权重（微调起点）", "note_en": "Official Laya typed-decisions weights (fine-tuning start)"},
]

# 每条消息: (中文, English)
MSG = {
    "name_bad": ("名字「%s」不合法：只能用字母、数字、中文、下划线、短横线和点，不超过 64 个字符",
                 'Invalid name "%s": use letters, digits, Chinese characters, underscore, dash or dot, at most 64 characters'),
    "ds_exists": ("数据集「%s」已经存在", 'Dataset "%s" already exists'),
    "ds_missing": ("找不到数据集「%s」", 'Dataset "%s" not found'),
    "ds_empty": ("数据集「%s」里还没有数据", 'Dataset "%s" has no rows yet'),
    "rows_bad": ("rows 必须是非空数组", "rows must be a non-empty list"),
    "row_obj": ("每一行必须是一个 JSON 对象", "Each row must be a JSON object"),
    "row_state": ("缺少素材（state）", "The material (state) is missing"),
    "row_questions": ("questions 必须是非空对象", "questions must be a non-empty object"),
    "row_q_obj": ("题目「%s」必须是对象", 'Question "%s" must be an object'),
    "row_q_type": ("题目「%s」的 type 必须是 noul / choice / score", 'Question "%s": type must be noul, choice or score'),
    "row_q_ins": ("题目「%s」缺少 instructions（题目文本）", 'Question "%s" has no instructions (question text)'),
    "row_q_crit": ("题目「%s」是单选题，criteria 必须是至少 2 个选项的对象", 'Question "%s" is a choice question; criteria must be an object with at least 2 options'),
    "row_q_levels": ("题目「%s」是打分题，levels 必须是至少 2 个等级说明的数组", 'Question "%s" is a score question; levels must be a list of at least 2 level descriptions'),
    "row_q_noul": ("题目「%s」是是非题，criteria 只能有 true / false 两个键", 'Question "%s" is a yes/no question; criteria may only have the keys true / false'),
    "row_expected": ("缺少 expected（正确答案）对象", "The expected (correct answers) object is missing"),
    "row_expected_none": ("没有一道题目带有正确答案", "No question has an expected answer"),
    "row_exp_noul": ("题目「%s」的答案 %r 不是是 / 否", 'Question "%s": answer %r is not yes / no'),
    "row_exp_choice": ("题目「%s」的答案 %r 不在选项 %s 里", 'Question "%s": answer %r is not one of the options %s'),
    "row_exp_score": ("题目「%s」的答案 %r 不是等级下标（0~%d）或等级文本", 'Question "%s": answer %r is neither a level index (0-%d) nor a level text'),
    "line_bad": ("第 %d 行：%s", "Line %d: %s"),
    "not_json": ("不是合法的 JSON", "not valid JSON"),
    "format_bad": ("format 必须是 jsonl 或 csv", "format must be jsonl or csv"),
    "text_empty": ("没有内容可导入", "There is nothing to import"),
    "csv_columns": ("CSV 里找不到列「%s」或「%s」，现有的列：%s", 'Column "%s" or "%s" not found in the CSV; available columns: %s'),
    "csv_no_rows": ("CSV 里没有可用的数据行", "The CSV has no usable data rows"),
    "csv_one_label": ("CSV 里只有一种标签「%s」，单选题至少需要 2 个选项", 'The CSV has only one label ("%s"); a choice question needs at least 2 options'),
    "index_bad": ("行号 %s 超出范围", "Row index %s is out of range"),
    "nothing_imported": ("没有导入任何一行；%d 行有问题，第一条：%s", "Nothing was imported; %d rows had problems, the first: %s"),
    "model_missing": ("找不到模型「%s」", 'Model "%s" not found'),
    "model_exists": ("模型「%s」已经存在，换一个名字，或勾选「续训」", 'Model "%s" already exists; pick another name or tick "resume"'),
    "model_busy": ("模型「%s」正在被任务 %s 使用", 'Model "%s" is in use by job %s'),
    "job_busy": ("已有训练类任务在运行（%s），请等它结束或先取消", "A training job is already running (%s); wait for it or cancel it first"),
    "job_missing": ("找不到任务 %s", "Job %s not found"),
    "cli_missing": ("找不到训练脚本 %s", "Training script %s not found"),
    "no_torch": ("当前环境没有安装 torch / laya，无法训练。重新运行安装脚本（install.bat / install.sh）即可补装。",
                 "torch / laya are not installed in this environment, so training is unavailable. Run the installer (install.bat / install.sh) again to add them."),
    "need": ("请填写 %s", "Please fill in %s"),
    "number_bad": ("%s 要填数字", "%s must be a number"),
    "mode_bad": ("mode 必须是 full / freeze / lora", "mode must be full, freeze or lora"),
    "loss_bad": ("loss 必须是 rlcd / soft-ce", "loss must be rlcd or soft-ce"),
    "cancelled": ("已取消", "Cancelled"),
    "exit_code": ("子进程退出，退出码 %s", "The subprocess exited with code %s"),
    "spawn_failed": ("无法启动子进程：%s", "Could not start the subprocess: %s"),
    "oom_line": ("显存不足，自动降档重试（第 %s 次）：micro_batch=%s max_len=%s", "Out of GPU memory; retrying with smaller settings (attempt %s): micro_batch=%s max_len=%s"),
    "probe_failed": ("探测失败：%s", "Probe failed: %s"),
}


def text(key, lang, *args):
    msg = MSG[key][1 if lang == "en" else 0]
    return msg % args if args else msg


class DJError(Exception):
    """带 HTTP 状态码的错误；detail 已经是当前语言的文案。"""

    def __init__(self, status, detail):
        Exception.__init__(self, detail)
        self.status = status
        self.detail = detail


class RowError(ValueError):
    pass


# ----------------------------------------------------------------- 纯函数（可以不起子进程直接测）

def parse_event(line):
    """一行 stdout → 事件 dict；不是 JSON 对象（或没有 event 字段）就返回 None。"""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("event"), str):
        return obj
    return None


def valid_name(name):
    name = str(name or "").strip()
    if not name or name in (".", "..") or len(name) > 64:
        return False
    return re.fullmatch(r"[\w一-鿿][\w一-鿿.\-]*", name) is not None


def merge_template(template, questions):
    """题目模板 = 所有行题目 id 的并集，每个 id 保留第一次见到的定义。"""
    template = dict(template or {})
    for qid, spec in (questions or {}).items():
        if qid not in template:
            template[qid] = copy.deepcopy(spec)
    return template


def gold_to_expected(record):
    """laya-opencv 复核导出的 {state, questions, gold} → {state, questions, expected}。gold 的值可以是 {"answer": x} 或直接答案。"""
    gold = record.get("gold")
    expected = {}
    if isinstance(gold, dict):
        for qid, value in gold.items():
            if isinstance(value, dict):
                if "answer" in value:
                    value = value["answer"]
                elif "choice" in value:
                    value = value["choice"]
                elif "noul" in value:
                    value = bool(value["noul"] >= 0.5) if isinstance(value["noul"], (int, float)) else value["noul"]
                elif "score" in value:
                    value = value["score"]
                elif isinstance(value.get("probabilities"), dict) and value["probabilities"]:
                    probs = value["probabilities"]
                    value = max(probs, key=lambda k: probs[k])
                else:
                    continue
            expected[qid] = value
    out = {k: v for k, v in record.items() if k != "gold"}
    out["expected"] = expected
    return out


def _normalize_question(qid, spec, lang):
    if not isinstance(spec, dict):
        raise RowError(text("row_q_obj", lang, qid))
    qtype = spec.get("type")
    if qtype not in TYPES:
        raise RowError(text("row_q_type", lang, qid))
    ins = spec.get("instructions")
    if ins is None:
        ins = spec.get("question")
    if not isinstance(ins, str) or not ins.strip():
        raise RowError(text("row_q_ins", lang, qid))
    out = {"type": qtype, "instructions": ins}
    if qtype == "choice":
        crit = spec.get("criteria")
        if isinstance(crit, list):
            crit = {str(k): None for k in crit}
        if not isinstance(crit, dict) or len(crit) < 2:
            raise RowError(text("row_q_crit", lang, qid))
        out["criteria"] = {str(k): (v if isinstance(v, str) or v is None else str(v)) for k, v in crit.items()}
    elif qtype == "score":
        levels = spec.get("levels")
        if levels is None:
            levels = spec.get("criteria")
        if not isinstance(levels, list) or len(levels) < 2 or any(v is None for v in levels):
            raise RowError(text("row_q_levels", lang, qid))
        levels = [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in levels]
        out["levels"] = levels
        out["criteria"] = list(levels)        # Laya 原生写法：score 的等级放在 criteria 列表里；两种键都存，训练器和页面都能读
    else:
        crit = spec.get("criteria")
        if crit is not None:
            if not isinstance(crit, dict) or not {str(k).lower() for k in crit} <= {"true", "false"}:
                raise RowError(text("row_q_noul", lang, qid))
            out["criteria"] = {str(k).lower(): v for k, v in crit.items()}
        if "labels" in spec:
            out["labels"] = spec["labels"]
    return out


def _normalize_expected(qid, spec, value, lang):
    qtype = spec["type"]
    if qtype == "noul":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in TRUE_WORDS:
                return True
            if low in FALSE_WORDS:
                return False
        raise RowError(text("row_exp_noul", lang, qid, value))
    if qtype == "choice":
        keys = list(spec["criteria"])
        if isinstance(value, bool):
            value = str(value).lower()
        if value in keys:
            return value
        if str(value) in keys:
            return str(value)
        raise RowError(text("row_exp_choice", lang, qid, value, "/".join(keys)))
    levels = spec["levels"]
    if isinstance(value, bool):
        raise RowError(text("row_exp_score", lang, qid, value, len(levels) - 1))
    if isinstance(value, str) and value in levels:
        return levels.index(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = None
    if number is None or not 0 <= number <= len(levels) - 1:
        raise RowError(text("row_exp_score", lang, qid, value, len(levels) - 1))
    return int(number) if number == int(number) else number


def validate_row(row, lang="zh"):
    """校验并整理一行训练数据；返回规范化后的 {state, questions, expected}，有问题时抛 RowError（文案已按语言）。

    没有正确答案的题目会被丢掉（复核记录往往只记了其中一道题）；一道都不剩才算错。
    """
    if not isinstance(row, dict):
        raise RowError(text("row_obj", lang))
    if "expected" not in row and "gold" in row:
        row = gold_to_expected(row)
    state = row.get("state")
    if state is None or (isinstance(state, str) and not state.strip()) or (isinstance(state, (dict, list)) and not state):
        raise RowError(text("row_state", lang))
    questions = row.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise RowError(text("row_questions", lang))
    expected = row.get("expected")
    if not isinstance(expected, dict):
        raise RowError(text("row_expected", lang))
    out_q, out_e = {}, {}
    for qid, spec in questions.items():
        qid = str(qid)
        if qid not in expected or expected[qid] is None:
            continue
        norm = _normalize_question(qid, spec, lang)
        out_q[qid] = norm
        out_e[qid] = _normalize_expected(qid, norm, expected[qid], lang)
    if not out_q:
        raise RowError(text("row_expected_none", lang))
    return {"state": state, "questions": out_q, "expected": out_e}


def csv_to_rows(text_data, text_column="text", label_column="label", question="label", instructions="", lang="zh"):
    """CSV（text, label 两列）→ 每行一个 choice 题。返回 (rows, labels)。列名找不到时抛 RowError。"""
    text_column = str(text_column or "text").strip()
    label_column = str(label_column or "label").strip()
    question = str(question or "label").strip() or "label"
    reader = csv.DictReader(io.StringIO(str(text_data or "").lstrip("﻿")))
    fields = [f.strip() for f in (reader.fieldnames or [])]
    if text_column not in fields or label_column not in fields:
        raise RowError(text("csv_columns", lang, text_column, label_column, ", ".join(fields) or "-"))
    pairs = []
    for rec in reader:
        rec = {str(k).strip(): v for k, v in rec.items() if k is not None}
        state = (rec.get(text_column) or "").strip()
        label = (rec.get(label_column) or "").strip()
        if state and label:
            pairs.append((state, label))
    if not pairs:
        raise RowError(text("csv_no_rows", lang))
    labels = []
    for _, label in pairs:
        if label not in labels:
            labels.append(label)
    if len(labels) < 2:
        raise RowError(text("csv_one_label", lang, labels[0]))
    spec = {"type": "choice", "instructions": str(instructions or "").strip() or question, "criteria": {k: None for k in labels}}
    rows = [{"state": state, "questions": {question: copy.deepcopy(spec)}, "expected": {question: label}} for state, label in pairs]
    return rows, labels


def parse_jsonl(text_data, lang="zh"):
    """JSONL 文本 → (rows, errors)。每一行都要过 validate_row。"""
    rows, errors = [], []
    for number, line in enumerate(str(text_data or "").splitlines(), 1):
        line = line.strip().lstrip("﻿")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            errors.append({"line": number, "error": text("line_bad", lang, number, text("not_json", lang))})
            continue
        try:
            rows.append(validate_row(obj, lang))
        except RowError as error:
            errors.append({"line": number, "error": text("line_bad", lang, number, str(error))})
    return rows, errors


def dir_size(path):
    total = 0
    for root, _, files in os.walk(str(path)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def read_json(path, default=None):
    try:
        with open(str(path), encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if data is not None else default
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def to_number(value, name, lang, integer=False, minimum=None):
    if value is None or value == "":
        return None
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError):
        raise DJError(400, text("number_bad", lang, name))
    if minimum is not None and number < minimum:
        raise DJError(400, text("number_bad", lang, name))
    return number


# ----------------------------------------------------------------- 存储 + 任务

class Store(object):
    """一个 data 目录对应一个 Store。launcher 建一个全局实例；测试各建各的。"""

    def __init__(self, data_dir, lang=None, hf_endpoint=None, python=None, cli=None, env_extra=None):
        self.data = Path(data_dir)
        self.ds_dir = self.data / "decision" / "datasets"
        self.models_dir = self.data / "decision" / "models"
        self.jobs_dir = self.data / "decision" / "jobs"
        self.gpu_file = self.data / "decision" / "gpu.json"
        self._lang = lang or (lambda: "zh")
        self._hf = hf_endpoint or (lambda: "")
        self.python = python or sys.executable
        self._cli = cli
        self.env_extra = dict(env_extra or {})
        self.lock = threading.Lock()          # 保护数据集文件和任务列表
        self.worker = threading.Lock()        # new / train / evaluate 共用的一把锁：同时只跑一个
        self.jobs = []                        # 最近的任务，新的在前
        self.before_start = None              # hook(kind)：训练前暂停模型服务
        self.after_finish = None              # hook(kind)：训练后恢复模型服务
        self._encoders = None

    # ---- 通用
    @property
    def lang(self):
        return self._lang() or "zh"

    def T(self, key, *args):
        return text(key, self.lang, *args)

    def cli(self):
        return Path(self._cli or os.environ.get("LAYA_WB_DECISION_CLI") or (APP / "decision_train.py"))

    def cli_ready(self):
        return self.cli().is_file()

    def check_name(self, name):
        name = str(name or "").strip()
        if not valid_name(name):
            raise DJError(400, self.T("name_bad", name))
        return name

    # ---- 数据集
    def _ds_paths(self, name):
        return self.ds_dir / (name + ".jsonl"), self.ds_dir / (name + ".meta.json")

    def _read_meta(self, name):
        meta = read_json(self._ds_paths(name)[1], {}) or {}
        meta.setdefault("title", name)
        meta.setdefault("note", "")
        meta.setdefault("created", "")
        meta.setdefault("rows", 0)
        meta.setdefault("questions", {})
        return meta

    def _read_rows(self, name):
        rows = []
        try:
            with open(str(self._ds_paths(name)[0]), encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass
        return rows

    def _require_ds(self, name):
        name = self.check_name(name)
        if not self._ds_paths(name)[0].is_file():
            raise DJError(404, self.T("ds_missing", name))
        return name

    def list_datasets(self):
        items = []
        if self.ds_dir.is_dir():
            for path in sorted(self.ds_dir.glob("*.jsonl")):
                name = path.name[:-len(".jsonl")]
                meta = self._read_meta(name)
                items.append({"name": name, "title": meta["title"], "note": meta["note"], "rows": meta["rows"],
                              "created": meta["created"], "questions": meta["questions"]})
        return items

    def create_dataset(self, name, title="", note=""):
        name = self.check_name(name)
        with self.lock:
            jsonl, meta_path = self._ds_paths(name)
            if jsonl.exists():
                raise DJError(409, self.T("ds_exists", name))
            self.ds_dir.mkdir(parents=True, exist_ok=True)
            jsonl.write_text("", encoding="utf-8")
            meta = {"title": str(title or "").strip() or name, "note": str(note or ""), "created": now_text(), "rows": 0, "questions": {}}
            write_json(meta_path, meta)
        return dict(meta, name=name)

    def _append_valid(self, name, rows, create=False):
        """把已经过校验的行追加进数据集，更新 meta。返回 meta。"""
        with self.lock:
            jsonl, meta_path = self._ds_paths(name)
            if not jsonl.exists():
                if not create:
                    raise DJError(404, self.T("ds_missing", name))
                self.ds_dir.mkdir(parents=True, exist_ok=True)
                jsonl.write_text("", encoding="utf-8")
                write_json(meta_path, {"title": name, "note": "", "created": now_text(), "rows": 0, "questions": {}})
            meta = self._read_meta(name)
            with open(str(jsonl), "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    meta["questions"] = merge_template(meta["questions"], row["questions"])
            meta["rows"] = int(meta.get("rows") or 0) + len(rows)
            write_json(meta_path, meta)
        return meta

    def append_rows(self, name, rows):
        """标注界面逐条加：任何一行有问题就整批拒绝（400）。"""
        name = self._require_ds(name)
        if not isinstance(rows, list) or not rows:
            raise DJError(400, self.T("rows_bad"))
        valid = []
        for index, row in enumerate(rows):
            try:
                valid.append(validate_row(row, self.lang))
            except RowError as error:
                raise DJError(400, self.T("line_bad", index + 1, str(error)))
        meta = self._append_valid(name, valid)
        return {"name": name, "added": len(valid), "rows": meta["rows"], "questions": meta["questions"]}

    def import_rows(self, name, records, create=True):
        """导入一批原始记录（expected 或 gold 格式都行）：能用的导入，有问题的记下来；一行都没导入才算错。"""
        name = self.check_name(name)
        valid, errors = [], []
        for index, rec in enumerate(records):
            try:
                valid.append(validate_row(rec, self.lang))
            except RowError as error:
                errors.append({"line": index + 1, "error": self.T("line_bad", index + 1, str(error))})
        if not valid:
            raise DJError(400, self.T("nothing_imported", len(errors), errors[0]["error"] if errors else "-"))
        meta = self._append_valid(name, valid, create=create)
        return {"name": name, "added": len(valid), "skipped": errors[:50], "skipped_total": len(errors), "rows": meta["rows"], "questions": meta["questions"]}

    def import_text(self, name, fmt, text_data, csv_opts=None):
        name = self.check_name(name)
        fmt = str(fmt or "jsonl").strip().lower()
        if not str(text_data or "").strip():
            raise DJError(400, self.T("text_empty"))
        if fmt == "jsonl":
            rows, errors = parse_jsonl(text_data, self.lang)
            labels = None
        elif fmt == "csv":
            opts = csv_opts if isinstance(csv_opts, dict) else {}
            try:
                rows, labels = csv_to_rows(text_data, opts.get("text_column"), opts.get("label_column"), opts.get("question"),
                                           opts.get("instructions"), self.lang)
            except RowError as error:
                raise DJError(400, str(error))
            errors = []
        else:
            raise DJError(400, self.T("format_bad"))
        if not rows:
            raise DJError(400, self.T("nothing_imported", len(errors), errors[0]["error"] if errors else "-"))
        meta = self._append_valid(name, rows, create=True)
        out = {"name": name, "added": len(rows), "skipped": errors[:50], "skipped_total": len(errors), "rows": meta["rows"], "questions": meta["questions"]}
        if labels is not None:
            out["labels"] = labels
        return out

    def rows(self, name, offset=0, limit=20):
        name = self._require_ds(name)
        offset = max(0, int(offset or 0))
        limit = max(1, min(200, int(limit or 20)))
        with self.lock:
            rows = self._read_rows(name)
        items = [{"index": offset + i, "row": row} for i, row in enumerate(rows[offset:offset + limit])]
        return {"name": name, "total": len(rows), "offset": offset, "limit": limit, "items": items}

    def delete(self, name, index=None):
        """index 为空 → 删除整个数据集；否则只删那一行（重写文件并重建题目模板）。"""
        name = self._require_ds(name)
        with self.lock:
            jsonl, meta_path = self._ds_paths(name)
            if index is None or index == "":
                for path in (jsonl, meta_path):
                    try:
                        path.unlink()
                    except OSError:
                        pass
                return {"name": name, "deleted": True}
            try:
                index = int(index)
            except (TypeError, ValueError):
                raise DJError(400, self.T("index_bad", index))
            rows = self._read_rows(name)
            if not 0 <= index < len(rows):
                raise DJError(400, self.T("index_bad", index))
            rows.pop(index)
            meta = self._read_meta(name)
            tmp = jsonl.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            os.replace(str(tmp), str(jsonl))
            meta["rows"] = len(rows)
            template = {}
            for row in rows:
                template = merge_template(template, row.get("questions") or {})
            meta["questions"] = template
            write_json(meta_path, meta)
        return {"name": name, "deleted": index, "rows": meta["rows"], "questions": meta["questions"]}

    def export_text(self, name):
        name = self._require_ds(name)
        with self.lock:
            return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._read_rows(name))

    def dataset_path(self, name):
        name = self._require_ds(name)
        if not self._read_meta(name)["rows"]:
            raise DJError(400, self.T("ds_empty", name))
        return self._ds_paths(name)[0]

    # ---- 模型
    def model_dir(self, name):
        return self.models_dir / self.check_name(name)

    def model_names(self):
        if not self.models_dir.is_dir():
            return []
        return sorted(p.name for p in self.models_dir.iterdir() if p.is_dir() and self._is_checkpoint(p))

    @staticmethod
    def _is_checkpoint(path):
        return any((path / f).exists() for f in ("rl_agent_config.json", "model.safetensors", "train.json"))

    def _model_entry(self, path, detail=False):
        cfg = read_json(path / "rl_agent_config.json", {}) or {}
        train = read_json(path / "train.json", {}) or {}
        enc_cfg = read_json(path / "encoder" / "config.json", {}) or {}
        result = train.get("result") if isinstance(train.get("result"), dict) else {}
        accuracy = None
        holdout = result.get("holdout") if isinstance(result, dict) else None
        if isinstance(holdout, dict) and isinstance(holdout.get("accuracy"), dict):
            accuracy = holdout["accuracy"].get("all")
        created = train.get("time") or train.get("created") or ""
        if not created:
            try:
                created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
            except OSError:
                created = ""
        running = self.running_job()
        entry = {
            "name": path.name,
            "encoder": train.get("encoder") or cfg.get("encoder") or enc_cfg.get("_name_or_path") or "",
            "encoder_type": (enc_cfg.get("architectures") or [None])[0] or enc_cfg.get("model_type") or "",
            "params_m": train.get("params_m") or result.get("params_m") or cfg.get("params_m"),
            "size_mb": round(dir_size(path) / 1048576.0, 1),
            "fine_tuned": bool(cfg.get("fine_tuned") or train.get("fine_tuned") or result.get("epochs_done")),
            "max_len": cfg.get("max_len"),
            "created": created,
            "accuracy": accuracy,
            "base": train.get("base") or "",
            "dataset": train.get("dataset") or "",
            "epochs_done": result.get("epochs_done") if result else train.get("epochs_done"),
            "complete": (path / "model.safetensors").exists(),
            "training": bool(running and running.get("name") == path.name),
            "train": train if detail else {k: train[k] for k in ("base", "dataset", "mode", "epochs", "time", "args") if k in train},
        }
        if detail:
            entry["config"] = cfg
            entry["questions"] = read_json(path / "questions.json", None)
            entry["encoder_config"] = {k: enc_cfg[k] for k in ("model_type", "architectures", "hidden_size", "num_hidden_layers", "vocab_size", "_name_or_path") if k in enc_cfg}
            entry["files"] = sorted(p.name for p in path.iterdir())
            entry["result"] = result
        return entry

    def list_models(self):
        return [self._model_entry(self.models_dir / name) for name in self.model_names()]

    def model_info(self, name):
        path = self.model_dir(name)
        if not path.is_dir():
            raise DJError(404, self.T("model_missing", name))
        return self._model_entry(path, detail=True)

    def delete_model(self, name):
        path = self.model_dir(name)
        if not path.is_dir():
            raise DJError(404, self.T("model_missing", name))
        running = self.running_job()
        if running and (running.get("name") == path.name or running.get("base") == path.name or running.get("model") == path.name):
            raise DJError(409, self.T("model_busy", path.name, running["id"]))
        shutil.rmtree(str(path))
        return {"name": path.name, "deleted": True}

    # ---- 环境
    def installed(self):
        out = {}
        for mod in ("torch", "laya", "peft", "torchvision"):
            try:
                out[mod] = importlib.util.find_spec(mod) is not None
            except (ImportError, ValueError):
                out[mod] = False
        return out

    def _run_cli(self, args, timeout=180):
        """同步跑一个不训练的命令（probe / encoders），返回 (result, error_text)。"""
        if not self.cli_ready():
            return None, self.T("cli_missing", str(self.cli()))
        try:
            proc = subprocess.run([self.python, str(self.cli())] + list(args), capture_output=True, timeout=timeout,
                                  env=self._env(), cwd=str(self.cli().parent.parent))
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, str(error)
        result, error = None, None
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            event = parse_event(line)
            if not event:
                continue
            if event["event"] == "result":
                result = {k: v for k, v in event.items() if k != "event"}
            elif event["event"] == "error":
                error = str(event.get("message") or "")
        if result is None and error is None:
            error = (proc.stderr.decode("utf-8", "replace").strip().splitlines() or ["exit %s" % proc.returncode])[-1]
        return result, error

    def probe(self, refresh=False):
        if not refresh:
            cached = read_json(self.gpu_file, None)
            if isinstance(cached, dict) and cached.get("device"):
                return cached
        inst = self.installed()
        if not inst["torch"]:
            return {"device": None, "error": self.T("no_torch"), "time": now_text()}
        result, error = self._run_cli(["probe"])
        if result is None:
            return {"device": None, "error": self.T("probe_failed", error), "time": now_text()}
        result["time"] = now_text()
        try:
            write_json(self.gpu_file, result)
        except OSError:
            pass
        return result

    def cached_device(self):
        cached = read_json(self.gpu_file, None)
        return cached.get("device") if isinstance(cached, dict) else None

    def encoders(self):
        if self._encoders is None:
            result, _ = self._run_cli(["encoders"], timeout=120) if (self.cli_ready() and self.installed()["torch"]) else (None, None)
            items = result.get("encoders") if isinstance(result, dict) else None
            self._encoders = items if isinstance(items, list) and items else copy.deepcopy(BUILTIN_ENCODERS)
        return self._encoders

    def env(self, refresh=False):
        inst = self.installed()
        probe = self.probe(refresh)
        return {"probe": probe, "encoders": self.encoders(), "installed": inst, "cli": self.cli_ready(), "cli_path": str(self.cli()),
                "available": bool(self.cli_ready() and inst["torch"] and inst["laya"]), "python": self.python}

    # ---- 任务
    def _env(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        env["LAYA_WB_DATA"] = str(self.data)
        hf = self._hf() or ""
        if hf and not env.get("HF_ENDPOINT"):
            env["HF_ENDPOINT"] = hf
        env.update(self.env_extra)
        return env

    def running_job(self):
        for job in self.jobs:
            if job["state"] in ("queued", "running"):
                return job
        return None

    def find_job(self, job_id):
        for job in self.jobs:
            if job["id"] == str(job_id):
                return job
        return None

    def public(self, job):
        out = {k: v for k, v in job.items() if not k.startswith("_")}
        if job["state"] in ("queued", "running") and job.get("_t0"):
            out["seconds"] = round(time.time() - job["_t0"], 1)
        return out

    def list_jobs(self):
        return [self.public(j) for j in self.jobs]

    def get_job(self, job_id):
        job = self.find_job(job_id)
        if job is None:
            raise DJError(404, self.T("job_missing", job_id))
        return self.public(job)

    def _new_job(self, kind, args, extra):
        job = {"id": "%s-%s" % (kind, time.strftime("%Y%m%d-%H%M%S")), "kind": kind, "state": "queued", "progress": 0.0, "stage": "",
               "epoch": None, "epochs": None, "step": None, "steps": None, "loss": None, "lr": None, "eta_seconds": None,
               "log_tail": [], "result": None, "error": None, "error_kind": None, "started": now_text(), "seconds": 0.0,
               "loss_curve": [], "oom": 0, "args": [str(a) for a in args], "log_file": str(self.jobs_dir / "%s.log"),
               "_t0": time.time(), "_proc": None, "_cancel": False}
        n = 2
        while self.find_job(job["id"]):
            job["id"] = "%s-%s-%d" % (kind, time.strftime("%Y%m%d-%H%M%S"), n)
            n += 1
        job["log_file"] = str(self.jobs_dir / (job["id"] + ".log"))
        job.update(extra or {})
        return job

    def start(self, kind, args, extra=None):
        """排一个 new / train / evaluate 任务。锁被占着就 409。返回任务的公开字段。"""
        if not self.cli_ready():
            raise DJError(503, self.T("cli_missing", str(self.cli())))
        with self.lock:
            running = self.running_job()
            if running or not self.worker.acquire(blocking=False):
                raise DJError(409, self.T("job_busy", running["id"] if running else "?"))
            job = self._new_job(kind, args, extra)
            self.jobs.insert(0, job)
            del self.jobs[KEEP_JOBS:]
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return self.public(job)

    def _log(self, job, handle, line):
        line = str(line).rstrip()
        if not line:
            return
        job["log_tail"].append(line)
        del job["log_tail"][:-LOG_TAIL]
        try:
            handle.write(line + "\n")
            handle.flush()
        except (OSError, ValueError):
            pass

    def _apply_event(self, job, event, handle):
        name = event["event"]
        if name == "log":
            self._log(job, handle, event.get("message", ""))
        elif name == "progress":
            for key in ("stage", "epoch", "epochs", "step", "steps", "loss", "lr", "eta_seconds"):
                if key in event:
                    job[key] = event[key]
            if isinstance(event.get("progress"), (int, float)):
                job["progress"] = max(0.0, min(1.0, float(event["progress"])))
            if isinstance(event.get("loss"), (int, float)) and event.get("stage", job["stage"]) == "train":
                curve = job["loss_curve"]
                x = event.get("step") if isinstance(event.get("step"), (int, float)) else len(curve)
                if isinstance(event.get("epoch"), (int, float)) and isinstance(event.get("steps"), (int, float)):
                    x = (max(1, int(event["epoch"])) - 1) * int(event["steps"]) + float(x)   # 跨 epoch 的全局步数
                curve.append([round(float(x), 1), round(float(event["loss"]), 5)])
                if len(curve) > 600:                              # 点太多就隔一个丢一个
                    job["loss_curve"] = curve[::2]
        elif name == "oom":
            job["oom"] = int(job.get("oom") or 0) + 1
            job["micro_batch"], job["max_len"] = event.get("micro_batch"), event.get("max_len")
            self._log(job, handle, self.T("oom_line", event.get("retry", job["oom"]), event.get("micro_batch"), event.get("max_len")))
        elif name == "result":
            job["result"] = {k: v for k, v in event.items() if k != "event"}
            job["progress"] = 1.0
        elif name == "error":
            job["error"] = str(event.get("message") or "")
            job["error_kind"] = event.get("kind") or "other"
            self._log(job, handle, "[error] " + job["error"])
        elif name == "start":
            cfg = event.get("config")
            if isinstance(cfg, dict):
                job["config"] = cfg
            self._log(job, handle, "[start] " + str(event.get("command") or job["kind"]))

    def _run(self, job):
        kind = job["kind"]
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        handle = None
        try:
            handle = open(job["log_file"], "a", encoding="utf-8")
        except OSError:
            handle = io.StringIO()
        try:
            if self.before_start:
                try:
                    self.before_start(kind)
                except Exception as error:          # 暂停服务失败不应该挡住训练
                    self._log(job, handle, "[hook] %s" % error)
            if job["_cancel"]:
                job["state"] = "cancelled"
                return
            cmd = [self.python, str(self.cli()), kind] + job["args"]
            self._log(job, handle, "> " + " ".join(cmd))
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self._env(),
                                        cwd=str(self.cli().parent.parent))
            except OSError as error:
                job["state"], job["error"], job["error_kind"] = "error", self.T("spawn_failed", error), "other"
                return
            job["_proc"] = proc
            job["state"] = "running"
            buffer = b""
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
                if not chunk:
                    break
                buffer += chunk
                parts = re.split(br"\r\n|\n|\r", buffer)
                buffer = parts.pop()
                for raw in parts:
                    self._line(job, raw, handle)
            if buffer.strip():
                self._line(job, buffer, handle)
            code = proc.wait()
            try:
                proc.stdout.close()
            except OSError:
                pass
            if job["_cancel"]:
                job["state"] = "cancelled"
                job["error"] = self.T("cancelled")
            elif job["error"]:
                job["state"] = "error"
            elif code != 0 or job["result"] is None:
                job["state"], job["error"], job["error_kind"] = "error", self.T("exit_code", code), "other"
            else:
                job["state"] = "done"
        finally:
            job["seconds"] = round(time.time() - job["_t0"], 1)
            job["_proc"] = None
            try:
                handle.close()
            except Exception:
                pass
            self.worker.release()
            if self.after_finish:
                try:
                    self.after_finish(kind)
                except Exception:
                    pass

    def _line(self, job, raw, handle):
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        if not line.strip():
            return
        event = parse_event(line)
        if event:
            self._apply_event(job, event, handle)
        else:
            self._log(job, handle, line)

    def cancel(self, job_id):
        job = self.find_job(job_id)
        if job is None:
            raise DJError(404, self.T("job_missing", job_id))
        if job["state"] not in ("queued", "running"):
            return self.public(job)
        job["_cancel"] = True
        proc = job["_proc"]
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            threading.Thread(target=self._kill_later, args=(proc,), daemon=True).start()
        return self.public(job)

    @staticmethod
    def _kill_later(proc, grace=5.0):
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.1)
        try:
            proc.kill()
        except OSError:
            pass

    # ---- 三种任务的参数整理
    def resolve_base(self, base):
        """起点：自定义模型名 → 目录；官方名 / HF id / 已有目录原样传给训练脚本。"""
        base = str(base or "").strip()
        if not base:
            raise DJError(400, self.T("need", "base"))
        if valid_name(base) and (self.models_dir / base).is_dir():
            return str(self.models_dir / base)
        return base

    def start_new(self, body):
        if not self.installed()["torch"]:
            raise DJError(503, self.T("no_torch"))
        name = self.check_name(body.get("name"))
        encoder = str(body.get("encoder") or "").strip()
        if not encoder:
            raise DJError(400, self.T("need", "encoder"))
        out = self.models_dir / name
        if out.exists():
            raise DJError(409, self.T("model_exists", name))
        args = ["--encoder", encoder, "--out", str(out)]
        layers = to_number(body.get("head_layers"), "head_layers", self.lang, integer=True, minimum=1)
        if layers:
            args += ["--head-layers", str(layers)]
        max_len = to_number(body.get("max_len"), "max_len", self.lang, integer=True, minimum=16)
        if max_len:
            args += ["--max-len", str(max_len)]
        head_max = to_number(body.get("head_max_len"), "head_max_len", self.lang, integer=True, minimum=16)
        if head_max:
            args += ["--head-max-len", str(head_max)]
        hf = self._hf() or ""
        if hf:
            args += ["--hf-endpoint", hf]
        return self.start("new", args, {"name": name, "encoder": encoder})

    def start_train(self, body):
        if not self.installed()["torch"]:
            raise DJError(503, self.T("no_torch"))
        name = self.check_name(body.get("name"))
        dataset = str(body.get("dataset") or "").strip()
        if not dataset:
            raise DJError(400, self.T("need", "dataset"))
        data_path = self.dataset_path(dataset)
        base = self.resolve_base(body.get("base"))
        out = self.models_dir / name
        resume = bool(body.get("resume"))
        if out.exists() and not resume and str(out) != base:
            raise DJError(409, self.T("model_exists", name))
        args = ["--data", str(data_path), "--base", base, "--out", str(out)]
        mode = str(body.get("mode") or "full").strip().lower()
        if mode not in ("full", "freeze", "lora"):
            raise DJError(400, self.T("mode_bad"))
        args += ["--mode", mode]
        for key, flag, integer, minimum in (("epochs", "--epochs", True, 1), ("micro_batch", "--micro-batch", True, 1), ("grad_accum", "--grad-accum", True, 1),
                                           ("encoder_lr", "--encoder-lr", False, 0), ("head_lr", "--head-lr", False, 0), ("max_len", "--max-len", True, 16),
                                           ("head_max_len", "--head-max-len", True, 16), ("lora_r", "--lora-r", True, 1), ("calib_frac", "--calib-frac", False, 0),
                                           ("holdout", "--holdout", False, 0), ("seed", "--seed", True, 0)):
            value = to_number(body.get(key), key, self.lang, integer=integer, minimum=minimum)
            if value is not None:
                args += [flag, str(value)]
        loss = str(body.get("loss") or "").strip().lower()
        if loss:
            if loss not in ("rlcd", "soft-ce"):
                raise DJError(400, self.T("loss_bad"))
            args += ["--loss", loss]
        for key, flag in (("amp", "--amp"), ("grad_ckpt", "--grad-ckpt"), ("device", "--device")):
            value = str(body.get(key) or "").strip().lower()
            if value and value != "auto":
                args += [flag, value]
        if resume:
            args.append("--resume")
        if body.get("dry_run"):
            args.append("--dry-run")
        hf = self._hf() or ""
        if hf:
            args += ["--hf-endpoint", hf]
        return self.start("train", args, {"name": name, "base": str(body.get("base") or "").strip(), "dataset": dataset, "mode": mode})

    def start_evaluate(self, body):
        if not self.installed()["torch"]:
            raise DJError(503, self.T("no_torch"))
        model = str(body.get("model") or "").strip()
        if not model:
            raise DJError(400, self.T("need", "model"))
        dataset = str(body.get("dataset") or "").strip()
        if not dataset:
            raise DJError(400, self.T("need", "dataset"))
        data_path = self.dataset_path(dataset)
        path = self.resolve_base(model)
        args = ["--data", str(data_path), "--model", path]
        device = str(body.get("device") or "").strip().lower()
        if device and device != "auto":
            args += ["--device", device]
        return self.start("evaluate", args, {"model": model, "dataset": dataset})
