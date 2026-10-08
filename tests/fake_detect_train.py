# -*- coding: utf-8 -*-
"""测试用的假检测训练脚本：按 docs/CONTRACT.md §2 / §7 的格式往 stdout 打事件流，不需要 torch。

    python tests/fake_detect_train.py probe | train --dataset D --out O ... | predict --model M --image I

模拟开关（环境变量）：
    FAKE_DETECT_FAIL=1        最后发 error 事件并以退出码 1 结束
    FAKE_DETECT_OOM=1         先发一个 oom 事件再继续
    FAKE_DETECT_DELAY=0.3     每个进度事件之间的间隔（秒），用来测取消
    FAKE_DETECT_EPOCHS=2      轮数（忽略 --epochs）

train 会在 --out 里写出 model.pt（假内容）和 meta.json，这样模型列表的代码也能一起测。
"""
import argparse
import json
import os
import sys
import time


def emit(event, **fields):
    fields["event"] = event
    sys.stdout.write(json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--dataset")
    parser.add_argument("--out")
    parser.add_argument("--model")
    parser.add_argument("--image")
    parser.add_argument("--arch", default="ssdlite")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--pretrained", default="auto")
    parser.add_argument("--conf", type=float, default=0.4)
    args, _ = parser.parse_known_args()
    delay = float(os.environ.get("FAKE_DETECT_DELAY") or 0)
    if args.command == "probe":
        emit("start", command="probe", config={})
        emit("result", torch=None, torchvision=None, device=None, vram_mb=None)
        return 0
    if args.command == "predict":
        emit("start", command="predict", config={"model": args.model})
        emit("result", boxes=[{"label": "a", "score": 0.9, "bbox": [1, 2, 3, 4]}])
        return 0
    emit("start", command="train", config={"dataset": args.dataset, "out": args.out, "arch": args.arch})
    emit("log", message="假训练开始 / fake training started")
    classes = ["a", "b"]
    try:
        with open(os.path.join(args.dataset, "classes.json"), encoding="utf-8") as handle:
            classes = json.load(handle)
    except (OSError, ValueError):
        pass
    epochs = int(os.environ.get("FAKE_DETECT_EPOCHS") or args.epochs or 2)
    batch = args.batch
    if os.environ.get("FAKE_DETECT_OOM"):
        batch = max(1, batch // 2)
        emit("oom", retry=1, batch=batch, imgsz=args.imgsz)
    steps = 3
    for epoch in range(1, epochs + 1):
        for step in range(1, steps + 1):
            done = ((epoch - 1) * steps + step) / float(epochs * steps)
            emit("progress", stage="train", progress=round(done * 0.95, 3), epoch=epoch, epochs=epochs, step=step, steps=steps,
                 loss=round(3.0 - done * 2, 3), eta_seconds=int((1 - done) * 10))
            if delay:
                time.sleep(delay)
        emit("log", message="第 %d/%d 轮完成 / epoch %d/%d done" % (epoch, epochs, epoch, epochs))
    if os.environ.get("FAKE_DETECT_FAIL"):
        emit("error", message="假的失败 / fake failure", kind="other")
        return 1
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "model.pt"), "wb") as handle:
        handle.write(b"fake")
    meta = {"arch": args.arch, "classes": classes, "imgsz": args.imgsz, "map50": 0.5, "per_class": {c: 0.5 for c in classes},
            "created": "2026-01-01 00:00:00", "torchvision": "fake", "pretrained_used": False, "epochs_done": epochs}
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False)
    emit("result", out=args.out, classes=classes, epochs_done=epochs, map50=0.5, per_class=meta["per_class"], seconds=0.1,
         peak_vram_mb=None, batch=batch, oom_retries=1 if os.environ.get("FAKE_DETECT_OOM") else 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
