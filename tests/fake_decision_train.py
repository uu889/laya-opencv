# -*- coding: utf-8 -*-
"""测试用的假训练脚本：按 docs/CONTRACT.md §2 的格式往 stdout 打事件流，不需要 torch。

    python tests/fake_decision_train.py probe | encoders | new ... | train ... | evaluate ... | info ...

模拟出错的开关（命令行或环境变量都行）：
    --fail            / FAKE_DECISION_FAIL=1     最后发一个 error 事件并以退出码 1 结束
    --oom             / FAKE_DECISION_OOM=1      训练时先发一个 oom 事件再继续
    --delay 0.5       / FAKE_DECISION_DELAY=0.5  每个进度事件之间的间隔（秒），用来测取消
    --steps 12        / FAKE_DECISION_STEPS=12   每个 epoch 的步数

train / new 会真的在 --out 目录里写出 rl_agent_config.json、train.json、encoder/config.json、questions.json，
这样模型列表的代码也能一起测。
"""
import json
import os
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def parse(argv):
    """最简单的参数解析：--key value 或 --flag。"""
    opts, key = {}, None
    for item in argv:
        if item.startswith("--"):
            key = item[2:].replace("-", "_")
            opts[key] = True
        elif key is not None:
            opts[key] = item
            key = None
    return opts


def knob(opts, name, env, default=None):
    if name in opts:
        return opts[name]
    return os.environ.get(env, default)


PROBE = {"device": "cpu", "gpu_name": None, "vram_mb": 0, "torch": "2.14.1", "cuda": None, "bf16": False, "laya": "0.3.28",
         "peft": True, "torchvision": "0.29", "tier": "small",
         "recommend": {"encoder": "intfloat/multilingual-e5-small", "mode": "full", "micro_batch": 4, "grad_accum": 16, "max_len": 256,
                       "amp": False, "grad_ckpt": False, "note_zh": "没有检测到显卡，用 CPU 训练小模型。", "note_en": "No GPU detected; training a small model on the CPU."}}

ENCODERS = [
    {"id": "intfloat/multilingual-e5-small", "tier": "small", "params_m": 118, "langs": "multi", "note_zh": "多语，4G 显卡默认", "note_en": "Multilingual, default for 4 GB GPUs"},
    {"id": "BAAI/bge-small-zh-v1.5", "tier": "small", "params_m": 24, "langs": "zh", "note_zh": "中文", "note_en": "Chinese"},
    {"id": "intfloat/multilingual-e5-base", "tier": "base", "params_m": 278, "langs": "multi", "note_zh": "多语", "note_en": "Multilingual"},
    {"id": "answerdotai/ModernBERT-large", "tier": "large", "params_m": 395, "langs": "en", "note_zh": "英文", "note_en": "English"},
    {"id": "convaiinnovations/laya-multilingual", "tier": "base", "params_m": 307, "langs": "multi", "official": True, "note_zh": "官方权重", "note_en": "Official weights"},
]


def write_checkpoint(out, encoder, base=None, result=None, args=None):
    os.makedirs(os.path.join(out, "encoder"), exist_ok=True)
    with open(os.path.join(out, "rl_agent_config.json"), "w", encoding="utf-8") as f:
        json.dump({"encoder": encoder, "head_layers": 2, "max_len": 512, "head_max_len": 192, "fine_tuned": result is not None}, f)
    with open(os.path.join(out, "encoder", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "bert", "architectures": ["BertModel"], "hidden_size": 384, "_name_or_path": encoder}, f)
    with open(os.path.join(out, "model.safetensors"), "wb") as f:
        f.write(b"\0" * 2048)
    if result is not None:
        with open(os.path.join(out, "train.json"), "w", encoding="utf-8") as f:
            json.dump({"args": args or {}, "base": base, "encoder": encoder, "dataset": os.path.basename(str((args or {}).get("data") or "")),
                       "mode": (args or {}).get("mode", "full"), "epochs": int((args or {}).get("epochs", 2)), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "result": result, "params_m": 118.3}, f, ensure_ascii=False)
        with open(os.path.join(out, "questions.json"), "w", encoding="utf-8") as f:
            json.dump({"pass": {"type": "noul", "instructions": "是否合格？"}}, f, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        emit({"event": "error", "message": "no command", "kind": "other"})
        return 2
    cmd, opts = sys.argv[1], parse(sys.argv[2:])
    fail = str(knob(opts, "fail", "FAKE_DECISION_FAIL", "")).lower() in ("1", "true", "yes")
    oom = str(knob(opts, "oom", "FAKE_DECISION_OOM", "")).lower() in ("1", "true", "yes")
    delay = float(knob(opts, "delay", "FAKE_DECISION_DELAY", "0.01"))
    steps = int(knob(opts, "steps", "FAKE_DECISION_STEPS", "6"))
    emit({"event": "start", "command": cmd, "config": {k: v for k, v in opts.items() if k not in ("fail", "oom", "delay", "steps")}})

    if cmd == "probe":
        emit({"event": "log", "message": "probing hardware"})
        emit(dict({"event": "result"}, **PROBE))
        return 0
    if cmd == "encoders":
        emit({"event": "result", "encoders": ENCODERS})
        return 0
    if cmd == "info":
        model = opts.get("model")
        if not model or not os.path.isdir(str(model)):
            emit({"event": "error", "message": "model dir not found: %s" % model, "kind": "data"})
            return 1
        emit({"event": "result", "encoder": "intfloat/multilingual-e5-small", "encoder_type": "BertModel", "params_m": 118.3, "max_len": 512,
              "fine_tuned": os.path.exists(os.path.join(model, "train.json")), "train": {}, "size_mb": 0.1})
        return 0
    if cmd == "new":
        out, encoder = opts.get("out"), opts.get("encoder")
        if not out or not encoder:
            emit({"event": "error", "message": "--encoder and --out are required", "kind": "other"})
            return 2
        for i in range(1, 4):
            time.sleep(delay)
            emit({"event": "progress", "stage": "download", "progress": i / 4.0})
        print("plain text line from a library")          # 非 JSON 行，应当被当成日志
        if fail:
            emit({"event": "error", "message": "download failed (simulated)", "kind": "download"})
            return 1
        write_checkpoint(out, encoder)
        emit({"event": "progress", "stage": "save", "progress": 1.0})
        emit({"event": "result", "out": out, "encoder": encoder, "params_m": 118.3, "encoder_params_m": 117.6, "hidden": 384})
        return 0
    if cmd == "train":
        out, data, base = opts.get("out"), opts.get("data"), opts.get("base")
        if not out or not data or not base:
            emit({"event": "error", "message": "--data, --base and --out are required", "kind": "other"})
            return 2
        if not os.path.isfile(str(data)):
            emit({"event": "error", "message": "data file not found: %s" % data, "kind": "data"})
            return 1
        with open(str(data), encoding="utf-8") as handle:
            rows = [line for line in handle if line.strip()]
        epochs = int(opts.get("epochs", 2))
        emit({"event": "log", "message": "loaded %d rows" % len(rows)})
        emit({"event": "progress", "stage": "prepare", "progress": 0.02})
        if oom:
            emit({"event": "oom", "retry": 1, "micro_batch": 2, "max_len": 384})
        total = epochs * steps
        for epoch in range(1, epochs + 1):
            for step in range(1, steps + 1):
                time.sleep(delay)
                done = (epoch - 1) * steps + step
                if fail and done == total // 2:
                    emit({"event": "error", "message": "training failed (simulated)", "kind": "other"})
                    return 1
                emit({"event": "progress", "stage": "train", "progress": round(0.05 + 0.85 * done / total, 4), "epoch": epoch, "epochs": epochs,
                      "step": step, "steps": steps, "loss": round(1.2 * (1 - done / float(total)) + 0.1, 4), "lr": 2.4e-5, "eta_seconds": int((total - done) * delay)})
        emit({"event": "progress", "stage": "calibrate", "progress": 0.93})
        emit({"event": "progress", "stage": "save", "progress": 0.97})
        result = {"out": out, "epochs_done": epochs, "train_items": max(0, len(rows) - 2), "calib_items": min(2, len(rows)), "skipped": {},
                  "holdout": {"items": 4, "accuracy": {"noul": 0.9, "choice": 0.85, "score": None, "all": 0.88}},
                  "calibration": {"temperature": [1.0, 1.0, 1.0]}, "seconds": 1.5, "peak_vram_mb": 0, "mode": opts.get("mode", "full")}
        write_checkpoint(out, "intfloat/multilingual-e5-small", base=base, result=result, args=opts)
        emit(dict({"event": "result"}, **result))
        return 0
    if cmd == "evaluate":
        model, data = opts.get("model"), opts.get("data")
        if not model or not data:
            emit({"event": "error", "message": "--data and --model are required", "kind": "other"})
            return 2
        for i in range(1, 4):
            time.sleep(delay)
            emit({"event": "progress", "stage": "evaluate", "progress": i / 3.0})
        if fail:
            emit({"event": "error", "message": "evaluation failed (simulated)", "kind": "other"})
            return 1
        emit({"event": "result", "items": 12, "accuracy": {"noul": 0.92, "choice": 0.8, "score": None, "all": 0.86},
              "per_question": {"pass": {"n": 12, "accuracy": 0.92}}, "confusion": {"pass": {"true": {"true": 6, "false": 1}, "false": {"true": 0, "false": 5}}}})
        return 0
    emit({"event": "error", "message": "unknown command %s" % cmd, "kind": "other"})
    return 2


if __name__ == "__main__":
    sys.exit(main())
