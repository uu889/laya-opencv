"""Step 2: fine-tune the blank checkpoint with Laya's own trainer (CPU, a few epochs)."""
import json
import sys
import time

from laya.train import TrainConfig, dry_run, finetune

data, ckpt_in, ckpt_out = sys.argv[1:4]
loss = sys.argv[4] if len(sys.argv) > 4 else "rlcd"

print("dry run:", dry_run(data, ckpt_in))
cfg = TrainConfig(
    epochs=int(sys.argv[5]) if len(sys.argv) > 5 else 6,
    micro_batch=4, grad_accum=2,
    loss=loss,                     # "rlcd" (Laya default) or soft cross-entropy
    encoder_lr=5e-4, head_lr=1e-3, # random tiny encoder: higher lr than a pretrained one
    amp=False, gradient_checkpointing=False,
    calib_frac=0.2, log_every=10,
)
t0 = time.time()
summary = finetune(data, ckpt_in, ckpt_out, cfg)
print("took %.1fs" % (time.time() - t0))
print(json.dumps(summary, indent=1, ensure_ascii=False, default=str)[:1500])
