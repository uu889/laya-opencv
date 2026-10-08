# -*- coding: utf-8 -*-
"""决策模型训练 CLI（「开源版 JEV」）。由启动器在子进程里调用，stdout 每行一个 JSON 事件。

  python app/decision_train.py probe                       探测硬件、档位与推荐参数（不加载模型）
  python app/decision_train.py encoders                    列出内置推荐编码器（不联网）
  python app/decision_train.py new --encoder <hf_id|dir> --out <dir>
                                                           从任意 HF 编码器新建空白 Laya 格式 checkpoint
  python app/decision_train.py train --data <jsonl> --base <dir|hf_id|multilingual> --out <dir> [...]
                                                           训练 / 微调（full、freeze、lora 三种模式，自动 OOM 降档）
  python app/decision_train.py evaluate --data <jsonl> --model <dir>
  python app/decision_train.py info --model <dir>          读元信息，不加载权重

事件格式见 docs/CONTRACT.md §2：start / log / progress / oom / result / error。
退出码 0 成功；失败时最后一个事件是 {"event":"error","message":...,"kind":...} 且退出码非 0。

依赖：torch、laya（锁定版本）、transformers；lora 模式另需 peft。
本模块顶层只用标准库，torch / laya 都在函数内按需导入，所以 `import decision_train` 在没有 torch 的
环境里也能成功（probe 会如实报告 torch 缺失）；纯函数（档位推荐、LoRA 目标层选择、参数解析）可以在
CI 里不装 torch 直接测。

官方 Laya 权重（multilingual / english / typed-decisions 或 convaiinnovations/laya-*）不需要 `new`：
直接 `train --base multilingual`，由 `laya.train.resolve_checkpoint_dir` 下载并解析（走 HF_ENDPOINT）。

仅供测试的环境变量：
  LAYA_WB_FAKE_OOM=<n>   让前 n 次前向传播抛出 torch.cuda.OutOfMemoryError，用来在 CPU 上测试 OOM 降档路径。
  LAYA_WB_LANG=zh|en     人类可读日志的语言（默认中文）。
"""
import argparse
import gc
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import random
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.0"

# 每条消息: (中文, English)
MSG = {
    "probe_no_torch": ("当前环境没有安装 torch，只能探测显卡，训练不可用。请运行安装脚本补装训练组件。",
                       "torch is not installed; only the GPU can be probed and training is unavailable. Run the installer to add the training components."),
    "probe_cpu_build": ("检测到显卡 %s，但当前 torch 是 CPU 版本，训练会在 CPU 上进行。请重新运行安装脚本安装 CUDA 版 torch。",
                        "GPU %s detected, but this torch is a CPU-only build, so training runs on the CPU. Run the installer again to get the CUDA build of torch."),
    "probe_no_laya": ("当前环境没有安装 laya，决策模型训练不可用。", "laya is not installed; decision-model training is unavailable."),
    "rec_cpu": ("没有可用的显卡：用最小的多语编码器 e5-small，在 CPU 上以较短的序列训练；数据量不大时几分钟到几十分钟可以完成。",
                "No usable GPU: use the smallest multilingual encoder (e5-small) on the CPU with shorter sequences; a small dataset trains in minutes to tens of minutes."),
    "rec_small": ("显存不到 6 GB：默认 e5-small 全参数训练，micro batch 2；想用 base 级编码器请选 lora 模式。",
                  "Less than 6 GB of GPU memory: train e5-small fully with micro batch 2; pick lora mode for a base-size encoder."),
    "rec_base": ("显存 6–11 GB：可以全参数训练 e5-base / mmBERT-base；large 级编码器请用 lora。",
                 "6-11 GB of GPU memory: e5-base / mmBERT-base train fully; use lora for a large encoder."),
    "rec_large": ("显存 11 GB 以上：可以全参数训练 ModernBERT-large 或微调官方 Laya 权重。",
                  "11 GB or more of GPU memory: ModernBERT-large and the official Laya checkpoints train fully."),
    "need_torch": ("这个命令需要 torch 和 laya，当前环境没有安装：%s", "This command needs torch and laya, which are not installed: %s"),
    "need_peft": ("lora 模式需要 peft，请先安装：pip install peft", "lora mode needs peft; install it first: pip install peft"),
    "loading_encoder": ("正在加载编码器 %s（首次使用会从 Hugging Face 下载）…", "Loading encoder %s (downloaded from Hugging Face on first use)..."),
    "saved_blank": ("已保存空白模型到 %s：共 %.1fM 参数（编码器 %.1fM，hidden=%d）", "Saved the blank model to %s: %.1fM parameters (encoder %.1fM, hidden=%d)"),
    "resolving_base": ("正在解析起点模型 %s…", "Resolving the base checkpoint %s..."),
    "resume_missing": ("找不到 %s，无法续训；请先正常训练一次。", "%s not found; cannot resume. Run a normal training first."),
    "resume_done": ("续训：之前已完成 %d 轮，目标 %d 轮，本次再训 %d 轮。", "Resuming: %d epoch(s) done before, target %d, training %d more now."),
    "resume_nothing": ("之前已完成 %d 轮，不少于 --epochs %d，没有需要训练的轮数；把 --epochs 调大再续训。",
                       "%d epoch(s) were already done, which is not fewer than --epochs %d; raise --epochs to continue."),
    "data_rows": ("读取 %s：%d 行，训练 %d 行，留出 %d 行。", "Read %s: %d rows, %d for training, %d held out."),
    "items": ("训练样本 %d，校准样本 %d，跳过 %s，设备 %s，模式 %s。", "Train items %d, calibration items %d, skipped %s, device %s, mode %s."),
    "no_items": ("数据里没有可训练的样本（跳过原因：%s）。请检查 questions / expected 字段。",
                 "The data produced no trainable items (skipped: %s). Check the questions / expected fields."),
    "lora_targets": ("LoRA：编码器 %s，目标层 %s，r=%d，可训练参数 %.2fM / %.2fM。", "LoRA: encoder %s, target modules %s, r=%d, trainable %.2fM / %.2fM parameters."),
    "freeze_emb": ("已冻结编码器词嵌入（%.1fM 参数）。", "Froze the encoder's input embeddings (%.1fM parameters)."),
    "freeze_none": ("这个编码器没有 get_input_embeddings()，freeze 模式退化为全参数训练。", "This encoder has no get_input_embeddings(); freeze mode falls back to full training."),
    "oom": ("显存不足（第 %d 次重试）：micro batch → %d，grad accum → %d，max_len → %d。", "Out of GPU memory (retry %d): micro batch -> %d, grad accum -> %d, max_len -> %d."),
    "oom_give_up": ("显存不足：micro batch 已降到 1、max_len 已降到 %d 仍然 OOM。请改用 lora 模式或更小的编码器。",
                    "Out of GPU memory even with micro batch 1 and max_len %d. Try lora mode or a smaller encoder."),
    "epoch_done": ("第 %d/%d 轮结束，平均 loss %.4f，已保存 checkpoint_latest。", "Epoch %d/%d done, mean loss %.4f, checkpoint_latest saved."),
    "calibrating": ("正在用 %d 条校准样本拟合温度…", "Fitting temperatures on %d calibration items..."),
    "calib_issue": ("校准提示（%s）：%s", "Calibration note (%s): %s"),
    "saving": ("正在保存模型到 %s…", "Saving the model to %s..."),
    "evaluating": ("正在评估 %d 行留出数据…", "Evaluating %d held-out rows..."),
    "done": ("训练完成，用时 %.1f 秒，显存峰值 %d MB。", "Training finished in %.1f s, peak GPU memory %d MB."),
    "eval_rows": ("评估 %s：%d 行。", "Evaluating %s: %d rows."),
    "bad_data": ("读取数据失败：%s", "Could not read the data: %s"),
    "download_failed": ("下载失败（检查网络或 HF_ENDPOINT 设置）：%s", "Download failed (check the network or the HF_ENDPOINT setting): %s"),
    "no_model_dir": ("找不到模型目录或 rl_agent_config.json：%s", "Model directory or rl_agent_config.json not found: %s"),
}
LANG = (os.environ.get("LAYA_WB_LANG") or "zh").lower()


def T(key, *args):
    """取一条消息（语言由 LAYA_WB_LANG 决定，默认中文）。"""
    text = MSG[key][1 if LANG == "en" else 0]
    return text % args if args else text


# ------------------------------------------------------------------------------ 事件流

def format_event(event, **fields):
    """一条事件的 JSON 文本（单行，非 ASCII 原样输出，None/NaN 安全）。"""
    payload = {"event": event}
    payload.update(fields)
    return json.dumps(_jsonable(payload), ensure_ascii=False, default=str)


def _jsonable(x):
    """把 numpy 标量、Path、NaN 等转成 json 能写出的值。"""
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    if hasattr(x, "item"):          # numpy 标量 / 0 维 tensor
        try:
            return _jsonable(x.item())
        except Exception:
            pass
    if hasattr(x, "tolist"):
        return _jsonable(x.tolist())
    return str(x)


# 事件流写到这里。main() 运行命令期间把 sys.stdout 指到 stderr，这样 laya / transformers 里零散的 print
# 不会混进事件流（stdout 必须每行都是 JSON）。
_EVENT_OUT = None


def emit(event, **fields):
    out = _EVENT_OUT or sys.stdout
    out.write(format_event(event, **fields) + "\n")
    out.flush()


def log(message):
    emit("log", message=message)


class CommandError(Exception):
    """带 kind 的失败：会变成 {"event":"error","kind":...}。"""

    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------------------ 纯函数：档位与推荐

TIER_SMALL, TIER_BASE, TIER_LARGE = "small", "base", "large"
E5_SMALL = "intfloat/multilingual-e5-small"
E5_BASE = "intfloat/multilingual-e5-base"
MODERNBERT_LARGE = "answerdotai/ModernBERT-large"

# 内置推荐编码器（不联网）。params_m 是参数量（百万）。
ENCODERS = [
    {"id": E5_SMALL, "tier": TIER_SMALL, "params_m": 118, "langs": "multi",
     "note_zh": "1.18 亿，多语，4G 显卡默认", "note_en": "118M, multilingual, default for 4 GB GPUs"},
    {"id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "tier": TIER_SMALL, "params_m": 118, "langs": "multi",
     "note_zh": "1.18 亿，多语", "note_en": "118M, multilingual"},
    {"id": "BAAI/bge-small-zh-v1.5", "tier": TIER_SMALL, "params_m": 24, "langs": "zh",
     "note_zh": "0.24 亿，中文", "note_en": "24M, Chinese"},
    {"id": "BAAI/bge-base-zh-v1.5", "tier": TIER_BASE, "params_m": 102, "langs": "zh",
     "note_zh": "1.02 亿，中文", "note_en": "102M, Chinese"},
    {"id": E5_BASE, "tier": TIER_BASE, "params_m": 278, "langs": "multi",
     "note_zh": "2.78 亿，多语", "note_en": "278M, multilingual"},
    {"id": "jhu-clsp/mmBERT-base", "tier": TIER_BASE, "params_m": 307, "langs": "multi",
     "note_zh": "3.07 亿，多语，Laya multilingual 用的底座", "note_en": "307M, multilingual, the base of Laya multilingual"},
    {"id": "answerdotai/ModernBERT-base", "tier": TIER_BASE, "params_m": 149, "langs": "en",
     "note_zh": "1.49 亿，英文", "note_en": "149M, English"},
    {"id": MODERNBERT_LARGE, "tier": TIER_LARGE, "params_m": 395, "langs": "en",
     "note_zh": "3.95 亿，英文", "note_en": "395M, English"},
    # 官方 Laya 权重：作为微调起点（train --base <name>），不需要 new
    {"id": "convaiinnovations/laya-multilingual", "tier": TIER_BASE, "params_m": 307, "langs": "multi", "laya": True,
     "alias": "multilingual", "note_zh": "官方 Laya 多语权重（mmBERT-base 底座），微调起点", "note_en": "Official Laya multilingual checkpoint (mmBERT-base), a fine-tuning start"},
    {"id": "convaiinnovations/laya", "tier": TIER_LARGE, "params_m": 395, "langs": "en", "laya": True,
     "alias": "english", "note_zh": "官方 Laya 英文权重（ModernBERT-large 底座），微调起点", "note_en": "Official Laya English checkpoint (ModernBERT-large), a fine-tuning start"},
    {"id": "convaiinnovations/laya-typed-decisions", "tier": TIER_LARGE, "params_m": 395, "langs": "en", "laya": True,
     "alias": "typed-decisions", "note_zh": "官方 Laya typed-decisions 英文权重，微调起点", "note_en": "Official Laya typed-decisions English checkpoint, a fine-tuning start"},
]
LAYA_ALIASES = {"multilingual", "english", "typed-decisions"}


def tier_from_vram(vram_mb):
    """显存（MB）→ 档位。None / 0 表示没有显卡 → small。见 CONTRACT §4。"""
    if not vram_mb or vram_mb <= 0:
        return TIER_SMALL
    if vram_mb < 6000:
        return TIER_SMALL
    if vram_mb < 11000:
        return TIER_BASE
    return TIER_LARGE


def recommend(tier, device="cuda"):
    """档位 + 实际可用设备 → 推荐参数（CONTRACT §4 的表）。device 不是 cuda 时按「无 GPU」一行。"""
    if device != "cuda":
        return {"encoder": E5_SMALL, "mode": "full", "micro_batch": 4, "grad_accum": 16, "max_len": 256,
                "amp": False, "grad_ckpt": False, "note_zh": MSG["rec_cpu"][0], "note_en": MSG["rec_cpu"][1]}
    if tier == TIER_SMALL:
        return {"encoder": E5_SMALL, "mode": "full", "micro_batch": 2, "grad_accum": 32, "max_len": 384,
                "amp": True, "grad_ckpt": True, "note_zh": MSG["rec_small"][0], "note_en": MSG["rec_small"][1]}
    if tier == TIER_BASE:
        return {"encoder": E5_BASE, "mode": "full", "micro_batch": 4, "grad_accum": 16, "max_len": 512,
                "amp": True, "grad_ckpt": True, "note_zh": MSG["rec_base"][0], "note_en": MSG["rec_base"][1]}
    return {"encoder": MODERNBERT_LARGE, "mode": "full", "micro_batch": 8, "grad_accum": 8, "max_len": 512,
            "amp": True, "grad_ckpt": False, "note_zh": MSG["rec_large"][0], "note_en": MSG["rec_large"][1]}


def parse_nvidia_smi(text):
    """解析 `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` 的输出 → (name, vram_mb) 或 None。"""
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        m = re.search(r"([\d.]+)\s*(MiB|GiB|MB|GB)?", parts[1], re.I)
        if not m:
            continue
        value = float(m.group(1))
        unit = (m.group(2) or "MiB").lower()
        if unit in ("gib", "gb"):
            value *= 1024
        return parts[0], int(round(value))
    return None


def query_nvidia_smi():
    """调用 nvidia-smi（没有或失败返回 None）。"""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return parse_nvidia_smi(out.stdout)


# ------------------------------------------------------------------------------ 纯函数：LoRA 目标层

# 编码器类名（小写包含匹配）→ LoRA 目标线性层名
_LORA_TARGETS = (
    (("modernbert",), ["Wqkv", "Wo", "Wi"]),
    (("mmbert", "bert", "roberta", "xlmroberta", "electra", "deberta", "camembert", "distilbert"),
     ["query", "key", "value", "dense"]),
)


def lora_target_modules(encoder_class_name, linear_names=None):
    """按编码器类名选 LoRA 目标层；未知类型时退回传入的全部 nn.Linear 名（去重、去路径）。

    BERT / XLM-R / mmBERT 一族：query/key/value/dense；ModernBERT：Wqkv/Wo/Wi；
    其他：linear_names（调用方遍历 encoder.named_modules() 收集的 nn.Linear 末级名字）。
    """
    name = (encoder_class_name or "").lower()
    for keys, targets in _LORA_TARGETS:
        if any(k in name for k in keys):
            return list(targets)
    leafs = []
    for n in linear_names or []:
        leaf = n.rsplit(".", 1)[-1]
        if leaf and leaf not in leafs:
            leafs.append(leaf)
    return leafs


def next_backoff(micro_batch, grad_accum, max_len, ladder=(512, 384, 256)):
    """OOM 后的下一组参数：先把 micro_batch 减半（grad_accum 翻倍），到 1 以后再降 max_len；不能再降 → None。"""
    if micro_batch > 1:
        return max(1, micro_batch // 2), grad_accum * 2, max_len
    lower = [l for l in ladder if l < max_len]
    if lower:
        return micro_batch, grad_accum, lower[0]
    return None


def cosine_lr(base_lr, min_lr, update, total_updates):
    """CosineAnnealingLR 在第 update 次更新时的学习率（和 laya.train 的 scheduler 同一公式）。"""
    if total_updates <= 0:
        return base_lr
    frac = min(1.0, max(0.0, update / float(total_updates)))
    return min_lr + (base_lr - min_lr) * (1 + math.cos(math.pi * frac)) / 2


def split_holdout(rows, frac, seed=0):
    """按行切出留出集：(train_rows, holdout_rows)。frac<=0 → 不切。至少留一行给训练。"""
    if not frac or frac <= 0 or len(rows) < 2:
        return list(rows), []
    n = int(round(len(rows) * frac))
    n = max(0, min(n, len(rows) - 1))
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    held = set(order[:n])
    return [r for i, r in enumerate(rows) if i not in held], [r for i, r in enumerate(rows) if i in held]


def _dist_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _try_import(name):
    """按需导入；没装返回 None。"""
    if importlib.util.find_spec(name) is None:
        return None
    try:
        return importlib.import_module(name)
    except Exception:
        return None


# ------------------------------------------------------------------------------ 参数解析

def build_parser():
    p = argparse.ArgumentParser(prog="decision_train.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="探测硬件 / probe hardware")
    sub.add_parser("encoders", help="内置编码器列表 / built-in encoders")

    n = sub.add_parser("new", help="新建空白模型 / new blank checkpoint")
    n.add_argument("--encoder", required=True)
    n.add_argument("--out", required=True)
    n.add_argument("--head-layers", type=int, default=2)
    n.add_argument("--max-len", type=int, default=512)
    n.add_argument("--head-max-len", type=int, default=192)
    n.add_argument("--hf-endpoint", default=None)

    t = sub.add_parser("train", help="训练 / train")
    t.add_argument("--data", required=True)
    t.add_argument("--base", required=False, default=None)
    t.add_argument("--out", required=True)
    t.add_argument("--mode", choices=("full", "freeze", "lora"), default="full")
    t.add_argument("--lora-r", type=int, default=16)
    t.add_argument("--lora-alpha", type=int, default=None, help="默认 2*r")
    t.add_argument("--lora-dropout", type=float, default=0.05)
    t.add_argument("--epochs", type=int, default=4)
    t.add_argument("--micro-batch", type=int, default=8)
    t.add_argument("--grad-accum", type=int, default=8)
    t.add_argument("--encoder-lr", type=float, default=2.5e-5)
    t.add_argument("--head-lr", type=float, default=1e-4)
    t.add_argument("--loss", choices=("rlcd", "soft-ce"), default="rlcd")
    t.add_argument("--max-len", type=int, default=None)
    t.add_argument("--head-max-len", type=int, default=None)
    t.add_argument("--amp", choices=("auto", "on", "off"), default="auto")
    t.add_argument("--grad-ckpt", choices=("auto", "on", "off"), default="auto")
    t.add_argument("--calib-frac", type=float, default=0.1)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--resume", action="store_true")
    t.add_argument("--holdout", type=float, default=0.0)
    t.add_argument("--device", default="auto")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--hf-endpoint", default=None)

    e = sub.add_parser("evaluate", help="评估 / evaluate")
    e.add_argument("--data", required=True)
    e.add_argument("--model", required=True)
    e.add_argument("--device", default="auto")
    e.add_argument("--batch-size", type=int, default=16)

    i = sub.add_parser("info", help="模型元信息 / checkpoint info")
    i.add_argument("--model", required=True)
    return p


def parse_args(argv):
    return build_parser().parse_args(argv)


def _tri(value):
    """auto|on|off → None|True|False（TrainConfig 的三态开关）。"""
    return None if value == "auto" else (value == "on")


# ------------------------------------------------------------------------------ probe / encoders

def cmd_probe(_args):
    info = {"device": "cpu", "gpu_name": None, "vram_mb": None, "torch": None, "cuda": None, "bf16": False,
            "laya": _dist_version("laya"), "peft": _dist_version("peft") is not None,
            "torchvision": _dist_version("torchvision"), "transformers": _dist_version("transformers"),
            "torch_cuda_build": None, "gpu_usable": False, "python": platform.python_version(),
            "platform": platform.platform(), "warnings": []}
    torch = _try_import("torch")
    smi = None
    if torch is None:
        info["warnings"].append(T("probe_no_torch"))
        smi = query_nvidia_smi()
    else:
        info["torch"] = torch.__version__
        info["torch_cuda_build"] = torch.version.cuda is not None
        info["cuda"] = torch.version.cuda
        try:
            cuda_ok = torch.cuda.is_available()
        except Exception:
            cuda_ok = False
        if cuda_ok:
            props = torch.cuda.get_device_properties(0)
            info.update(device="cuda", gpu_name=props.name, vram_mb=int(props.total_memory // (1024 * 1024)),
                        gpu_usable=True)
            try:
                info["bf16"] = bool(torch.cuda.is_bf16_supported())
            except Exception:
                info["bf16"] = False
        else:
            mps = getattr(torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                info["device"] = "mps"
            smi = query_nvidia_smi()
            if smi and not info["torch_cuda_build"]:
                info["warnings"].append(T("probe_cpu_build", smi[0]))
    if smi:
        info["gpu_name"], info["vram_mb"] = smi
    if info["laya"] is None:
        info["warnings"].append(T("probe_no_laya"))
    info["tier"] = tier_from_vram(info["vram_mb"])
    info["recommend"] = recommend(info["tier"], info["device"])
    emit("result", **info)


def cmd_encoders(_args):
    emit("result", encoders=[dict(e, laya=bool(e.get("laya"))) for e in ENCODERS])


# ------------------------------------------------------------------------------ 公共：导入 torch/laya

def _require_training_libs():
    missing = [n for n in ("torch", "laya", "transformers") if importlib.util.find_spec(n) is None]
    if missing:
        raise CommandError(T("need_torch", ", ".join(missing)), "other")
    import torch  # noqa: F401
    import laya.train  # noqa: F401
    try:  # 进度条和告警只会弄脏 stderr，关掉
        import transformers.utils.logging as hf_logging
        hf_logging.disable_progress_bar()
        hf_logging.set_verbosity_error()
    except Exception:
        pass


def _set_hf_endpoint(url):
    if url:
        os.environ["HF_ENDPOINT"] = url


def _is_oom(exc):
    import torch
    oom_cls = getattr(torch.cuda, "OutOfMemoryError", None) or getattr(torch, "OutOfMemoryError", None)
    if oom_cls is not None and isinstance(exc, oom_cls):
        return True
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def _install_fake_oom():
    """LAYA_WB_FAKE_OOM=<n>：前 n 次 laya.train._forward 抛 OOM（仅测试）。"""
    n = int(os.environ.get("LAYA_WB_FAKE_OOM") or 0)
    if n <= 0:
        return
    import torch
    import laya.train as lt
    real = lt._forward
    state = {"left": n}

    def fake_forward(*a, **kw):
        if state["left"] > 0:
            state["left"] -= 1
            raise torch.cuda.OutOfMemoryError("CUDA out of memory (fake, LAYA_WB_FAKE_OOM)")
        return real(*a, **kw)

    lt._forward = fake_forward


def _param_count(module):
    return sum(p.numel() for p in module.parameters())


def _peak_vram_mb():
    import torch
    if torch.cuda.is_available():
        try:
            return int(torch.cuda.max_memory_allocated() // (1024 * 1024))
        except Exception:
            return 0
    return 0


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_jsonable(data), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ------------------------------------------------------------------------------ new

def cmd_new(a):
    _set_hf_endpoint(a.hf_endpoint)
    _require_training_libs()
    from transformers import AutoTokenizer
    from laya.common import build_model
    from laya.train import save_checkpoint

    emit("start", command="new", config={"encoder": a.encoder, "out": a.out, "head_layers": a.head_layers,
                                         "max_len": a.max_len, "head_max_len": a.head_max_len})
    cfg = {"encoder": a.encoder, "head_layers": a.head_layers, "max_len": a.max_len,
           "head_max_len": a.head_max_len, "option_layout": "sequential"}
    emit("progress", stage="download", progress=0.0)
    log(T("loading_encoder", a.encoder))
    try:
        model = build_model(cfg)
        tok = AutoTokenizer.from_pretrained(a.encoder)
    except Exception as exc:  # noqa: BLE001
        if os.path.isdir(a.encoder):
            raise
        raise CommandError(T("download_failed", "%s: %s" % (type(exc).__name__, exc)), "download")
    emit("progress", stage="download", progress=1.0)
    emit("progress", stage="save", progress=0.9)
    n_enc, n_all = _param_count(model.encoder), _param_count(model)
    hidden = int(model.encoder.config.hidden_size)
    save_checkpoint(model, tok, cfg, a.out)
    _write_json(os.path.join(a.out, "train.json"), {
        "command": "new", "encoder": a.encoder, "encoder_type": type(model.encoder).__name__,
        "head_layers": a.head_layers, "max_len": a.max_len, "head_max_len": a.head_max_len,
        "params_m": round(n_all / 1e6, 2), "encoder_params_m": round(n_enc / 1e6, 2), "hidden": hidden,
        "epochs_done": 0, "created": _now(), "updated": _now(), "history": [],
    })
    log(T("saved_blank", a.out, n_all / 1e6, n_enc / 1e6, hidden))
    emit("result", out=a.out, encoder=a.encoder, encoder_type=type(model.encoder).__name__,
         params_m=round(n_all / 1e6, 2), encoder_params_m=round(n_enc / 1e6, 2), hidden=hidden)


# ------------------------------------------------------------------------------ evaluate（train 的 holdout 也用）

def _option_labels(q):
    """内部题目 → 各选项的标签文本（confusion 用）。"""
    t, crit = q["t"], q.get("crit")
    if t == "choice":
        return [str(k) for k in crit.keys()]
    if t == "noul":
        return ["false", "true"]
    n = len(crit) if crit is not None else 0
    return [str(i) for i in range(n)]


def evaluate_rows(model, tok, rows, device, max_len, head_max_len, parallel=False, batch_size=16):
    """按 Laya 校准的方式前向，算每类型 / 每题准确率与混淆矩阵。"""
    import torch
    from laya.common import QTYPE_NAMES, collate_items
    from laya.train import _forward, encode_item, items_from_rows

    tagged, skipped = [], {}
    for row in rows:
        qs = row.get("questions") or {}
        if not isinstance(qs, dict):
            continue
        for qid in qs:
            single = {"state": row.get("state"), "questions": {qid: qs[qid]}}
            for key in ("expected", "gold"):
                if isinstance(row.get(key), dict) and qid in row[key]:
                    single[key] = {qid: row[key][qid]}
            if "expected" not in single and "gold" not in single:
                continue
            items, sk = items_from_rows(tok, [single], max_len, head_max_len)
            for k, v in sk.items():
                skipped[k] = skipped.get(k, 0) + v
            for it in items:
                tagged.append((qid, it))

    model.eval()
    by_type = {name: [0, 0] for name in QTYPE_NAMES.values()}
    per_q, confusion = {}, {}
    with torch.no_grad():
        for start in range(0, len(tagged), batch_size):
            chunk = tagged[start:start + batch_size]
            batch = collate_items([[encode_item(tok, it, max_len, head_max_len, parallel=parallel) for _, it in chunk]],
                                  tok.pad_token_id)
            logits = _forward(model, batch, device, amp=False, detach_encoder=False).cpu().numpy()
            for row_logits, (qid, it) in zip(logits, chunk):
                k = it["k"]
                pred = int(row_logits[:k].argmax())
                gold = int(max(range(k), key=lambda i: it["target"][i]))
                labels = _option_labels(it["q"])
                if len(labels) != k:
                    labels = [str(i) for i in range(k)]
                tname = QTYPE_NAMES[int(it["qtype"])]
                ok = int(pred == gold)
                by_type[tname][0] += ok
                by_type[tname][1] += 1
                pq = per_q.setdefault(qid, {"n": 0, "correct": 0, "type": tname})
                pq["n"] += 1
                pq["correct"] += ok
                conf = confusion.setdefault(qid, {})
                conf.setdefault(labels[gold], {})
                conf[labels[gold]][labels[pred]] = conf[labels[gold]].get(labels[pred], 0) + 1
    total_ok = sum(v[0] for v in by_type.values())
    total_n = sum(v[1] for v in by_type.values())
    accuracy = {name: (v[0] / v[1] if v[1] else None) for name, v in by_type.items()}
    accuracy["all"] = total_ok / total_n if total_n else None
    for pq in per_q.values():
        pq["accuracy"] = pq["correct"] / pq["n"] if pq["n"] else None
    return {"items": total_n, "rows": len(rows), "accuracy": accuracy, "per_question": per_q,
            "confusion": confusion, "skipped": skipped}


def cmd_evaluate(a):
    _require_training_libs()
    from laya.common import uses_parallel_layout
    from laya.train import load_checkpoint, read_data, resolve_device

    emit("start", command="evaluate", config={"data": a.data, "model": a.model, "device": a.device})
    try:
        rows = read_data(a.data)
    except (OSError, ValueError) as exc:
        raise CommandError(T("bad_data", exc), "data")
    log(T("eval_rows", os.path.basename(a.data), len(rows)))
    emit("progress", stage="prepare", progress=0.05)
    model, tok, cfg = _load_checkpoint_or_error(load_checkpoint, a.model)
    dev = resolve_device(a.device)
    model.to(dev)
    emit("progress", stage="evaluate", progress=0.2)
    res = evaluate_rows(model, tok, rows, dev, cfg.get("max_len", 512), cfg.get("head_max_len", 192),
                        parallel=uses_parallel_layout(cfg), batch_size=a.batch_size)
    emit("progress", stage="evaluate", progress=1.0)
    emit("result", model=a.model, data=a.data, **res)


def _load_checkpoint_or_error(load_checkpoint, path):
    try:
        return load_checkpoint(path)
    except FileNotFoundError as exc:
        raise CommandError(T("no_model_dir", exc), "data")


# ------------------------------------------------------------------------------ train

_STEP_RE = re.compile(r"^epoch (\d+)/(\d+) step (\d+) loss ([-+0-9.eE]+|nan|inf)")
_EPOCH_RE = re.compile(r"^epoch (\d+)/(\d+) mean loss")


class _ProgressTap:
    """替换 laya.train 模块里的 print，把「epoch i/n step k loss x」变成 progress 事件。"""

    def __init__(self, steps_per_epoch, epochs, grad_accum, encoder_lr, min_lr, epoch_offset, epochs_total,
                 every=None, span=(0.05, 0.9)):
        self.spe = max(1, steps_per_epoch)
        self.epochs = max(1, epochs)
        self.grad_accum = max(1, grad_accum)
        self.encoder_lr, self.min_lr = encoder_lr, min_lr
        self.epoch_offset, self.epochs_total = epoch_offset, epochs_total
        self.every = every or max(1, min(10, self.spe // 5 or 1))
        self.span = span
        self.t0 = time.time()
        self.total_steps = self.spe * self.epochs
        self.total_updates = max(1, math.ceil(self.spe / self.grad_accum) * self.epochs)
        self.last_loss = None

    def __call__(self, *args, **kwargs):
        text = " ".join(str(x) for x in args)
        m = _STEP_RE.match(text)
        if m:
            epoch, step = int(m.group(1)), int(m.group(3))
            try:
                loss = float(m.group(4))
            except ValueError:
                loss = None
            self.last_loss = loss
            if step % self.every == 0 or step == self.spe:
                done = (epoch - 1) * self.spe + step
                elapsed = time.time() - self.t0
                eta = (elapsed / done) * (self.total_steps - done) if done else None
                update = done // self.grad_accum
                frac = done / float(self.total_steps)
                emit("progress", stage="train", progress=round(self.span[0] + frac * (self.span[1] - self.span[0]), 4),
                     epoch=self.epoch_offset + epoch, epochs=self.epochs_total, step=step, steps=self.spe,
                     loss=loss, lr=cosine_lr(self.encoder_lr, self.min_lr, update, self.total_updates),
                     eta_seconds=None if eta is None else int(round(eta)))
            return
        if _EPOCH_RE.match(text):
            return          # on_epoch_end 里另发一条带中文的 log
        log(text)


def _apply_mode(model, mode, a):
    """按 --mode 改造模型；返回 (model, mode_info)。lora 时 model.encoder 变成 PeftModel。"""
    import torch
    info = {"mode": mode}
    if mode == "freeze":
        get_emb = getattr(model.encoder, "get_input_embeddings", None)
        emb = get_emb() if callable(get_emb) else None
        weight = getattr(emb, "weight", None)
        if weight is None:
            log(T("freeze_none"))
            info["frozen_params_m"] = 0.0
        else:
            weight.requires_grad_(False)
            info["frozen_params_m"] = round(weight.numel() / 1e6, 2)
            log(T("freeze_emb", weight.numel() / 1e6))
        return model, info
    if mode == "lora":
        if importlib.util.find_spec("peft") is None:
            raise CommandError(T("need_peft"), "other")
        from peft import LoraConfig, get_peft_model
        enc_name = type(model.encoder).__name__
        linear_names = [n for n, m in model.encoder.named_modules() if isinstance(m, torch.nn.Linear)]
        targets = lora_target_modules(enc_name, linear_names)
        # 目标名必须真的存在于这个编码器里，否则 peft 会报错；不存在就退回全部 Linear
        leafs = {n.rsplit(".", 1)[-1] for n in linear_names}
        targets = [t for t in targets if t in leafs] or lora_target_modules("", linear_names)
        if not targets:
            raise CommandError("no nn.Linear modules found in encoder %s for LoRA" % enc_name, "other")
        lcfg = LoraConfig(r=a.lora_r, lora_alpha=a.lora_alpha or 2 * a.lora_r, lora_dropout=a.lora_dropout,
                          target_modules=targets, bias="none")
        model.encoder = get_peft_model(model.encoder, lcfg)
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        info.update(lora_r=a.lora_r, lora_targets=targets, encoder_type=enc_name,
                    trainable_params_m=round(trainable / 1e6, 2))
        log(T("lora_targets", enc_name, ",".join(targets), a.lora_r, trainable / 1e6, _param_count(model) / 1e6))
    return model, info


def _merged_encoder_copy(encoder):
    """PeftModel 编码器 → 合并后的普通编码器（在 CPU 上深拷贝，不动训练中的权重）。"""
    import copy
    clone = copy.deepcopy(encoder).cpu()
    return clone.merge_and_unload()


def _save_plain(model, tok, cfg, path, is_lora, final):
    """保存普通 Laya checkpoint。lora：最终保存直接 merge_and_unload，中途保存用合并后的副本。"""
    from laya.train import save_checkpoint
    if not is_lora:
        save_checkpoint(model, tok, cfg, path)
        return model
    if final:
        model.encoder = model.encoder.merge_and_unload()
        save_checkpoint(model, tok, cfg, path)
        return model
    peft_encoder = model.encoder
    model.encoder = _merged_encoder_copy(peft_encoder)
    try:
        save_checkpoint(model, tok, cfg, path)
    finally:
        model.encoder = peft_encoder
    return model


def _resolve_base(base, hf_endpoint):
    from laya.train import resolve_checkpoint_dir
    _set_hf_endpoint(hf_endpoint)
    if base is None:
        raise CommandError("--base is required (checkpoint dir, HF id or multilingual|english|typed-decisions)", "data")
    log(T("resolving_base", base))
    try:
        return resolve_checkpoint_dir(base)
    except FileNotFoundError as exc:
        raise CommandError(T("no_model_dir", exc), "data")
    except Exception as exc:  # noqa: BLE001 -- Hub 下载失败
        raise CommandError(T("download_failed", "%s: %s" % (type(exc).__name__, exc)), "download")


def cmd_train(a):
    _set_hf_endpoint(a.hf_endpoint)
    _require_training_libs()
    import torch
    from laya.calibrate import fit_temperature_map
    from laya.common import uses_parallel_layout
    import laya.train as lt
    from laya.train import (TrainConfig, calibration_records, calibration_report, items_from_rows,
                            load_checkpoint, read_data, resolve_device, split_calibration)

    argv_config = {k: v for k, v in vars(a).items() if k != "command"}
    emit("start", command="train", config=argv_config)
    t_start = time.time()
    out = a.out
    train_json_path = os.path.join(out, "train.json")
    latest_dir = os.path.join(out, "checkpoint_latest")

    # ---- 起点与续训
    prev = _read_json(train_json_path, {}) if os.path.isdir(out) else {}
    epochs_done_before = 0
    if a.resume:
        if not os.path.exists(os.path.join(latest_dir, "rl_agent_config.json")):
            raise CommandError(T("resume_missing", latest_dir), "data")
        base_dir = latest_dir
        epochs_done_before = int(prev.get("epochs_done") or 0)
        if epochs_done_before >= a.epochs:
            raise CommandError(T("resume_nothing", epochs_done_before, a.epochs), "data")
        log(T("resume_done", epochs_done_before, a.epochs, a.epochs - epochs_done_before))
    else:
        base_dir = _resolve_base(a.base, a.hf_endpoint)
    epochs_todo = a.epochs - epochs_done_before

    # ---- dry run
    if a.dry_run:
        tcfg = TrainConfig(max_len=a.max_len, head_max_len=a.head_max_len)
        try:
            summary = lt.dry_run(a.data, base_dir, tcfg)
        except (OSError, ValueError) as exc:
            raise CommandError(T("bad_data", exc), "data")
        emit("result", dry_run=True, base=base_dir, **summary)
        return

    # ---- 数据
    emit("progress", stage="prepare", progress=0.0)
    try:
        rows = read_data(a.data)
    except (OSError, ValueError) as exc:
        raise CommandError(T("bad_data", exc), "data")
    train_rows, holdout_rows = split_holdout(rows, a.holdout, a.seed)
    log(T("data_rows", os.path.basename(a.data), len(rows), len(train_rows), len(holdout_rows)))
    if not train_rows:
        raise CommandError(T("no_items", "{}"), "data")

    _install_fake_oom()
    dev = resolve_device(a.device)
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    micro_batch, grad_accum, max_len_arg = a.micro_batch, a.grad_accum, a.max_len
    retry = 0
    is_lora = a.mode == "lora"
    # laya.train 里的 print 是全局名查找：往模块里放一个同名函数就能截获 step 级日志
    had_print = "print" in vars(lt)
    real_print = vars(lt).get("print")

    while True:
        model, tok, cfg = _load_checkpoint_or_error(load_checkpoint, base_dir)
        max_len = max_len_arg or cfg.get("max_len", 512)
        head_max_len = a.head_max_len or cfg.get("head_max_len", 192)
        parallel = uses_parallel_layout(cfg)
        enc_type = type(model.encoder).__name__
        model, mode_info = _apply_mode(model, a.mode, a)
        mode_info.update(encoder=cfg.get("encoder"), encoder_type=enc_type)
        items, skipped = items_from_rows(tok, train_rows, max_len, head_max_len)
        if not items:
            raise CommandError(T("no_items", json.dumps(skipped, ensure_ascii=False)), "data")
        tcfg = TrainConfig(epochs=epochs_todo, micro_batch=micro_batch, grad_accum=grad_accum,
                           encoder_lr=a.encoder_lr, head_lr=a.head_lr, loss=a.loss, calib_frac=a.calib_frac,
                           seed=a.seed, max_len=max_len, head_max_len=head_max_len, amp=_tri(a.amp),
                           gradient_checkpointing=_tri(a.grad_ckpt), log_every=1)
        try:
            tcfg.validate()
        except ValueError as exc:
            raise CommandError(str(exc), "data")
        train_items, calib_items = split_calibration(items, tcfg.calib_max, tcfg.calib_frac, tcfg.calib_seed)
        log(T("items", len(train_items), len(calib_items), json.dumps(skipped, ensure_ascii=False), dev, a.mode))
        emit("progress", stage="prepare", progress=0.05)
        steps_per_epoch = math.ceil(len(train_items) / micro_batch)
        tap = _ProgressTap(steps_per_epoch, epochs_todo, grad_accum, a.encoder_lr, tcfg.min_lr,
                           epochs_done_before, a.epochs)
        save_cfg = dict(cfg, max_len=max_len, head_max_len=head_max_len)
        state = {"epochs": epochs_done_before, "history": list(prev.get("history") or []) if a.resume else []}

        def on_epoch_end(epoch, mean_loss):
            state["epochs"] = epochs_done_before + epoch + 1
            state["history"].append(mean_loss)
            emit("progress", stage="save", progress=tap.span[0] + (epoch + 1) / float(epochs_todo) * (tap.span[1] - tap.span[0]),
                 epoch=state["epochs"], epochs=a.epochs, step=steps_per_epoch, steps=steps_per_epoch, loss=mean_loss)
            _save_plain(model, tok, save_cfg, latest_dir, is_lora, final=False)
            _write_json(train_json_path, _train_record(a, base_dir, state, prev, mode_info, result=None))
            log(T("epoch_done", state["epochs"], a.epochs, mean_loss))

        lt.print = tap
        try:
            history = lt.train_model(model, tok, train_items, tcfg, dev, max_len, head_max_len,
                                     on_epoch_end=on_epoch_end, parallel=parallel)
        except Exception as exc:  # noqa: BLE001
            if not _is_oom(exc):
                raise
            del model
            gc.collect()
            if dev.type == "cuda":
                torch.cuda.empty_cache()
            nxt = next_backoff(micro_batch, grad_accum, max_len)
            if nxt is None:
                raise CommandError(T("oom_give_up", max_len), "oom")
            retry += 1
            micro_batch, grad_accum, max_len_arg = nxt
            emit("oom", retry=retry, micro_batch=micro_batch, grad_accum=grad_accum, max_len=max_len_arg)
            log(T("oom", retry, micro_batch, grad_accum, max_len_arg))
            continue
        finally:
            if had_print:
                lt.print = real_print
            else:
                vars(lt).pop("print", None)
        break

    # ---- 校准（和 laya.train.finetune 一致）
    emit("progress", stage="calibrate", progress=0.9)
    log(T("calibrating", len(calib_items)))
    records = calibration_records(model, tok, calib_items, dev, max_len, head_max_len, parallel=parallel)
    fitted = fit_temperature_map(records)
    calibration = calibration_report(records, fitted["temperature"])
    for name, entry in calibration.items():
        for issue in entry["issues"]:
            log(T("calib_issue", name, issue))
    out_cfg = dict(cfg, max_len=max_len, head_max_len=head_max_len, fine_tuned=True, temperature=fitted["temperature"])
    out_cfg.pop("temperature_by_options", None)
    if fitted["temperature_by_options"]:
        out_cfg["temperature_by_options"] = fitted["temperature_by_options"]
    from dataclasses import asdict
    out_cfg["training"] = dict(out_cfg.get("training") or {}, laya_train=asdict(tcfg), laya_train_calibration=calibration,
                               laya_wb={"mode": a.mode, "base": base_dir, "epochs_done": state["epochs"]})

    # ---- 保存
    emit("progress", stage="save", progress=0.93)
    log(T("saving", out))
    model = _save_plain(model, tok, out_cfg, out, is_lora, final=True)
    _write_questions_json(rows, out, latest_dir)

    # ---- 留出评估
    holdout = None
    if holdout_rows:
        emit("progress", stage="evaluate", progress=0.95)
        log(T("evaluating", len(holdout_rows)))
        holdout = evaluate_rows(model, tok, holdout_rows, dev, max_len, head_max_len, parallel=parallel)

    seconds = round(time.time() - t_start, 1)
    peak = _peak_vram_mb()
    result = {
        "out": out, "base": base_dir, "mode": a.mode, "epochs_done": state["epochs"], "epochs": a.epochs,
        "train_items": len(train_items), "calib_items": len(calib_items), "skipped": skipped,
        "holdout": holdout, "calibration": calibration, "temperature": fitted["temperature"],
        "epoch_loss": state["history"], "micro_batch": micro_batch, "grad_accum": grad_accum, "max_len": max_len,
        "oom_retries": retry, "seconds": seconds, "peak_vram_mb": peak, "device": str(dev),
    }
    result.update({k: v for k, v in mode_info.items() if k != "mode"})
    _write_json(train_json_path, _train_record(a, base_dir, state, prev, mode_info, result=result))
    log(T("done", seconds, peak))
    emit("progress", stage="evaluate", progress=1.0)
    emit("result", **result)


def _train_record(a, base_dir, state, prev, mode_info, result):
    """<out>/train.json 的内容：参数、数据、起点、结果、时间戳。"""
    rec = {
        "command": "train", "argv": sys.argv[1:], "args": {k: v for k, v in vars(a).items() if k != "command"},
        "data": os.path.basename(a.data), "data_path": os.path.abspath(a.data),
        "base": base_dir if not a.resume else prev.get("base", base_dir), "mode": a.mode,
        "epochs_done": state["epochs"], "epochs_target": a.epochs, "history": state["history"],
        "mode_info": mode_info, "result": result, "finished": result is not None,
        "created": prev.get("created") or _now(), "updated": _now(),
        "encoder": prev.get("encoder"), "encoder_type": prev.get("encoder_type") or mode_info.get("encoder_type"),
        "laya": _dist_version("laya"), "version": VERSION,
    }
    if result and result.get("holdout"):
        rec["accuracy"] = result["holdout"]["accuracy"]
    elif prev.get("accuracy") and result is None:
        rec["accuracy"] = prev["accuracy"]
    return rec


def _write_questions_json(rows, *dirs):
    """题目模板（和 laya.train.finetune 一样取每题首次出现的定义）。"""
    sample = {}
    for r in rows:
        qs = r.get("questions")
        if isinstance(qs, dict):
            for qid, qdef in qs.items():
                sample.setdefault(qid, qdef)
    if not sample:
        return
    for d in dirs:
        if os.path.isdir(d):
            _write_json(os.path.join(d, "questions.json"), sample)


# ------------------------------------------------------------------------------ info

def safetensors_param_count(path):
    """只读 safetensors 文件头统计参数量（不加载权重，不需要 torch）。"""
    import struct
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n).decode("utf-8"))
    total = 0
    for key, meta in header.items():
        if key == "__metadata__" or not isinstance(meta, dict):
            continue
        count = 1
        for d in meta.get("shape") or []:
            count *= int(d)
        total += count
    return total


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def cmd_info(a):
    model_dir = a.model
    cfg_path = os.path.join(model_dir, "rl_agent_config.json")
    if not os.path.exists(cfg_path):
        raise CommandError(T("no_model_dir", model_dir), "data")
    cfg = _read_json(cfg_path, {})
    enc_cfg = _read_json(os.path.join(model_dir, "encoder", "config.json"), {}) or {}
    archs = enc_cfg.get("architectures") or []
    encoder_type = archs[0] if archs else enc_cfg.get("model_type")
    weights = os.path.join(model_dir, "model.safetensors")
    params_m = None
    if os.path.exists(weights):
        try:
            params_m = round(safetensors_param_count(weights) / 1e6, 2)
        except (OSError, ValueError, KeyError):
            params_m = None
    train = _read_json(os.path.join(model_dir, "train.json"), None)
    questions = _read_json(os.path.join(model_dir, "questions.json"), None)
    try:
        created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(cfg_path)))
    except OSError:
        created = None
    emit("result", model=model_dir, encoder=cfg.get("encoder"), encoder_type=encoder_type,
         hidden=enc_cfg.get("hidden_size"), params_m=params_m, max_len=cfg.get("max_len"),
         head_max_len=cfg.get("head_max_len"), head_layers=cfg.get("head_layers"),
         fine_tuned=bool(cfg.get("fine_tuned")), temperature=cfg.get("temperature"),
         train=train, questions=questions, has_latest=os.path.isdir(os.path.join(model_dir, "checkpoint_latest")),
         size_mb=round(_dir_size(model_dir) / (1024 * 1024), 1), created=created)


# ------------------------------------------------------------------------------ main

COMMANDS = {"probe": cmd_probe, "encoders": cmd_encoders, "new": cmd_new, "train": cmd_train,
            "evaluate": cmd_evaluate, "info": cmd_info}


def main(argv=None):
    global _EVENT_OUT
    a = parse_args(sys.argv[1:] if argv is None else argv)
    saved_out, saved_event_out = sys.stdout, _EVENT_OUT
    _EVENT_OUT = sys.stdout
    sys.stdout = sys.stderr
    try:
        return _run(a)
    finally:
        sys.stdout, _EVENT_OUT = saved_out, saved_event_out


def _run(a):
    try:
        COMMANDS[a.command](a)
    except CommandError as exc:
        emit("error", message=str(exc), kind=exc.kind)
        return 2
    except KeyboardInterrupt:
        emit("error", message="interrupted", kind="other")
        return 130
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc(file=sys.stderr)
        kind = "other"
        try:
            if _try_import("torch") is not None and _is_oom(exc):
                kind = "oom"
        except Exception:
            pass
        emit("error", message="%s: %s" % (type(exc).__name__, exc), kind=kind)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
