# Decision-model training reference

[中文](decision-training.md) | **English**

This is the full reference for the two scripts behind the Decision training tab: `app/decision_train.py` (the training CLI) and `app/decision_server.py` (the model server). For the page itself see [README, "Decision-model training"](../README.en.md#decision-model-training).

Both scripts run with the virtual environment's Python (`.venv/bin/python` on Linux, `.venv\Scripts\python.exe` on Windows) and need torch, laya (pinned version) and transformers; lora mode also needs peft. The launcher `app/launcher.py` uses only the standard library; everything that needs torch happens in these two scripts, run as subprocesses.

## 1. Overall flow

```
probe ──→ tier and suggested parameters
encoders → pick an encoder
new ─────→ data/decision/models/<name>/        blank Laya-format model (pretrained encoder + randomly initialised decision head)
train ───→ data/decision/models/<name>-v1/     training; --base is a folder from new, an official checkpoint name or any HF id
evaluate → accuracy and confusion matrices on held-out data
decision_server.py --custom name=<dir> → /v1/systemone
```

The official checkpoints (`multilingual` / `english` / `typed-decisions`, or the full ids `convaiinnovations/laya-*`) need no `new`: run `train --base multilingual` directly.

## 2. `decision_train.py` commands

### Event stream

stdout carries **one JSON object per line**; stderr is free text (transformers / laya's own output). Exit code 0 means success; on failure the last event is `error` and the exit code is non-zero (2 for a `CommandError`, 1 for other exceptions, 130 for Ctrl+C).

```json
{"event":"start","command":"train","config":{...all arguments...}}
{"event":"log","message":"human-readable log line"}
{"event":"progress","stage":"download|prepare|train|calibrate|save|evaluate","progress":0.42,
 "epoch":2,"epochs":6,"step":120,"steps":480,"loss":0.61,"lr":2.4e-5,"eta_seconds":300}
{"event":"oom","retry":1,"micro_batch":2,"grad_accum":64,"max_len":384}
{"event":"result", ...}
{"event":"error","message":"...","kind":"oom|data|download|other"}
```

The language of `log` lines follows `LAYA_WB_LANG=zh|en` (Chinese by default); the launcher passes the page language.

### `probe` — hardware probe (loads no model)

```
result: {"device":"cuda|cpu|mps","gpu_name":"NVIDIA GeForce RTX 3050 Laptop GPU","vram_mb":4096,
         "torch":"2.14.1+cu130","cuda":"13.0","bf16":true,"torch_cuda_build":true,"gpu_usable":true,
         "laya":"0.4.0","peft":true,"torchvision":"0.29.1","transformers":"...","python":"3.12.x","platform":"...",
         "tier":"small|base|large","recommend":{...§4...},"warnings":["..."]}
```

It runs without torch as well (the GPU name and memory come from `nvidia-smi`, and `warnings` says torch is missing). With an NVIDIA GPU but a CPU build of torch, `gpu_name` / `vram_mb` come from `nvidia-smi`, `device` is `cpu` and a warning explains why. The installer and `GET /v1/decision/env` both call it; the result is cached in `data/decision/gpu.json`.

### `encoders` — built-in encoders (offline)

```
result: {"encoders":[{"id":"intfloat/multilingual-e5-small","tier":"small","params_m":118,"langs":"multi",
                      "note_zh":"...","note_en":"...","laya":false}, ...]}
```

The official checkpoints carry `"laya": true` and an `"alias"` (`multilingual` and so on). The list is in the README's encoder table.

### `new` — create a blank model from an encoder

```
new --encoder <hf_id | local dir> --out <dir> [--head-layers 2] [--max-len 512] [--head-max-len 192] [--hf-endpoint URL]
result: {"out":"...","encoder":"...","encoder_type":"XLMRobertaModel","params_m":118.3,"encoder_params_m":117.6,"hidden":384}
```

| Flag | Meaning |
|---|---|
| `--encoder` | Hugging Face model id or local folder (any bidirectional encoder `AutoModel` can load: BERT / RoBERTa / XLM-R / ModernBERT / mmBERT / E5 / BGE …) |
| `--out` | Output folder; receives `model.safetensors`, `rl_agent_config.json`, `encoder/`, `tokenizer/`, `train.json` (`epochs_done: 0`) |
| `--head-layers` | Layers in the decision head, default 2 |
| `--max-len` | Maximum tokens of the material (state), default 512 |
| `--head-max-len` | Maximum tokens of the question text, default 192 |
| `--hf-endpoint` | Download endpoint; otherwise the `HF_ENDPOINT` environment variable (the launcher sets it from `hf_endpoint` in `config.json`) |

The download phase emits `progress stage=download`. `params_m` is the total parameter count in millions, `hidden` the encoder's hidden size.

### `train` — train / fine-tune

```
train --data <jsonl> --base <checkpoint_dir | hf_id | multilingual|english|typed-decisions> --out <dir>
      [--mode full|freeze|lora] [--lora-r 16] [--lora-alpha 2r] [--lora-dropout 0.05]
      [--epochs 4] [--micro-batch 8] [--grad-accum 8]
      [--encoder-lr 2.5e-5] [--head-lr 1e-4] [--loss rlcd|soft-ce]
      [--max-len N] [--head-max-len N] [--amp auto|on|off] [--grad-ckpt auto|on|off]
      [--calib-frac 0.1] [--holdout 0.0] [--seed 0] [--device auto|cuda|cpu]
      [--resume] [--dry-run] [--hf-endpoint URL]
```

| Flag | Meaning |
|---|---|
| `--data` | JSONL training data (§3) |
| `--base` | Starting point: a folder from `new`, a trained model folder, an official checkpoint name, or any Laya-format HF repo id. Not needed with `--resume` |
| `--out` | Output folder. May equal `--base` (train in place) |
| `--mode` | `full` (default) all parameters; `freeze` freezes the encoder's input embeddings (`get_input_embeddings()`); `lora` adds LoRA adapters with peft (§5) |
| `--lora-r` / `--lora-alpha` / `--lora-dropout` | LoRA rank (default 16), alpha (default 2×r), dropout (default 0.05) |
| `--epochs` | Target total epochs (including the ones already done when resuming) |
| `--micro-batch` × `--grad-accum` | Samples per forward pass × gradient-accumulation steps = effective batch. Suggestions in §4 |
| `--encoder-lr` / `--head-lr` | Learning rates of the encoder and the decision head (cosine schedule) |
| `--loss` | `rlcd` (Laya's default reinforcement-style loss) or `soft-ce` (soft cross-entropy) |
| `--max-len` / `--head-max-len` | Override the sequence lengths stored in the checkpoint; otherwise they are kept |
| `--amp` | Mixed precision: `auto` lets Laya decide by device (on with cuda); `on` / `off` force it |
| `--grad-ckpt` | Gradient checkpointing (saves memory, slower): same three states |
| `--calib-frac` | Fraction held out for temperature calibration (default 0.1; with too few calibration items the temperature stays 1.0 and the result says so) |
| `--holdout` | Fraction held out for validation (default 0 = none); `evaluate` runs on it after training |
| `--seed` | Random seed for splits and initialisation |
| `--device` | `auto` (cuda when available) / `cuda` / `cpu` |
| `--resume` | Continue from `<out>/checkpoint_latest` (§6) |
| `--dry-run` | Only read the data, count trainable items and skip reasons; loads no model |

Result:

```
result: {"out":"...","base":"...","mode":"lora","epochs_done":4,"epochs":4,
         "train_items":192,"calib_items":48,"skipped":{"reason":count},
         "holdout":{"items":48,"rows":24,"accuracy":{"noul":0.9,"choice":0.85,"score":null,"all":0.88},
                    "per_question":{...},"confusion":{...}},
         "calibration":{...laya's calibration report...},"temperature":[...],"epoch_loss":[...],
         "micro_batch":2,"grad_accum":32,"max_len":384,"oom_retries":1,
         "seconds":812.3,"peak_vram_mb":2890,"device":"cuda","encoder":"...","encoder_type":"..."}
```

`train_items` counts questions, not rows (a row with three questions is three items). `peak_vram_mb` comes from `torch.cuda.max_memory_allocated()`. `skipped` records questions that were skipped for a missing answer, an answer outside the options, and so on.

`<out>/train.json` records the command line, data file name, starting point, `epochs_done`, the per-epoch loss history, mode details (LoRA target modules, frozen parameter count) and the full result; `<out>/questions.json` is the question template collected from the data (used by "Load template" on the page).

### `evaluate`

```
evaluate --data <jsonl> --model <dir> [--device auto] [--batch-size 16]
result: {"model":"...","data":"...","items":120,"rows":60,
         "accuracy":{"noul":0.93,"choice":0.85,"score":0.7,"all":0.86},
         "per_question":{"pass":{"n":60,"correct":56,"type":"noul","accuracy":0.93},...},
         "confusion":{"pass":{"true":{"true":28,"false":2},"false":{"true":2,"false":28}},...},"skipped":{...}}
```

`confusion[q][expected][predicted]` = count. Score questions are compared by level index.

### `info` — checkpoint metadata (loads no weights)

```
info --model <dir>
result: {"model":"...","encoder":"...","encoder_type":"XLMRobertaModel","hidden":384,"params_m":118.3,
         "max_len":512,"head_max_len":192,"head_layers":2,"fine_tuned":true,"temperature":[...],
         "train":{...train.json...},"questions":{...questions.json...},"has_latest":true,"size_mb":450,"created":"..."}
```

`fine_tuned` comes from `rl_agent_config.json` (Laya writes it after training); `has_latest` says a `checkpoint_latest` exists to resume from. `params_m` is read from the header of `model.safetensors` without loading the tensors.

## 3. Data format

JSONL, one object per line, Laya's native format:

```json
{"state": "the material: text, or a JSON object or message list (as in /v1/systemone)",
 "questions": {
   "pass":  {"type": "noul",   "instructions": "Is this pipe acceptable?"},
   "grade": {"type": "choice", "instructions": "Defect count level", "criteria": {"few": "20 or fewer", "many": "more than 20"}},
   "score": {"type": "score",  "instructions": "Appearance score", "levels": ["poor", "fair", "good"]}
 },
 "expected": {"pass": false, "grade": "many", "score": 1}}
```

- `type`: `noul` (yes/no, expected is a bool), `choice` (expected is a key of `criteria`), `score` (expected is an index into `levels` or a level text)
- The field is called `instructions` (not `question`); choice options are an **object** `criteria` (not a list)
- `expected` may cover only some of the questions; the others are skipped (and counted in `skipped`)
- laya-opencv's exported `{state, questions, gold}` is accepted too (`gold` values are `{"answer": ...}` or the bare answer). The launcher converts to `expected` on import; the CLI reads both (Laya's `read_data` accepts both)
- CSV import on the page: columns `text,label` (or named columns) → each row becomes one choice question; `criteria` is collected from the labels seen and the question text (`instructions`) is typed by the user

The launcher stores datasets at `data/decision/datasets/<name>.jsonl` with `<name>.meta.json` beside it: `{"title","note","created","rows","questions"}` (`questions` is the collected template).

## 4. GPU-memory tiers and suggested parameters

`probe` picks a tier by memory (`tier_from_vram`) and returns `recommend` (`recommend(tier, device)`; both are pure functions with unit tests in `tests/test_decision_pure.py`):

| vram_mb | tier | encoder | mode | micro_batch × grad_accum | max_len | amp | grad_ckpt |
|---|---|---|---|---|---|---|---|
| no GPU / device not cuda | small | multilingual-e5-small | full | 4 × 16 | 256 | off | off |
| < 6000 | small | multilingual-e5-small | full (lora for base-size encoders) | 2 × 32 | 384 | on | on |
| 6000 – 11000 | base | multilingual-e5-base | full (lora for large encoders) | 4 × 16 | 512 | on | on |
| ≥ 11000 | large | ModernBERT-large | full | 8 × 8 | 512 | on | off |

`recommend` fields: `{"encoder","mode","micro_batch","grad_accum","max_len","amp","grad_ckpt","note_zh","note_en"}`.

These numbers are estimates from parameter counts, sequence length and mixed precision, not measurements on the respective cards (see "Verified vs. estimated" below). Training backs off automatically on OOM, so the suggestions lean towards "try this first" rather than conservative values.

## 5. The three modes

**full**: every parameter trains. Small encoders (e5-small 118M, bge-small 24M) work on 4 GB with the suggested parameters.

**freeze**: the encoder's input-embedding matrix is frozen (`encoder.get_input_embeddings().weight.requires_grad = False`); all other layers train. The embeddings are usually the largest block of a (multilingual) encoder — about 96M of e5-small's 118M parameters are vocabulary — so freezing them removes a large share of the optimizer state and gradients, without the loss of capacity of Laya's own `freeze_encoder` (which freezes the whole encoder). If the encoder has no `get_input_embeddings()`, the mode falls back to full with a log line.

**lora**: [peft](https://github.com/huggingface/peft) adds LoRA adapters to the encoder's linear layers; only the adapters and the decision head train.

- Target modules are chosen by encoder class: ModernBERT-style → `Wqkv`, `Wo`, `Wi`; BERT / RoBERTa / XLM-R / mmBERT / ELECTRA / DeBERTa … → `query`, `key`, `value`, `dense`; unknown encoders get adapters on every `nn.Linear` (`lora_target_modules()`, unit-tested)
- `r` 16 by default, `alpha` 2r, dropout 0.05, `bias="none"`
- The log reports trainable / total parameters
- **`merge_and_unload()` before saving**: the LoRA weights are merged into the original matrices, so the saved `model.safetensors` is an ordinary Laya checkpoint and neither the server nor `evaluate` needs peft
- The `checkpoint_latest` written after each epoch is merged too; `--resume` adds a fresh LoRA layer on top of the merged weights
- Without peft: `{"event":"error","kind":"other","message":"lora mode needs peft…"}`

## 6. OOM back-off and resuming

**OOM**: after catching `torch.cuda.OutOfMemoryError` (or a RuntimeError whose message contains "out of memory"):

1. `micro_batch` is halved and `grad_accum` doubled (effective batch unchanged), down to 1
2. Once micro_batch is 1, `max_len` steps down 512 → 384 → 256
3. If that fails too → `error kind=oom`, suggesting lora or a smaller encoder

Every retry emits `{"event":"oom","retry":n,"micro_batch":..,"grad_accum":..,"max_len":..}`, frees the GPU memory, reloads the model from the starting point and restarts the epochs of this run from the beginning (a `checkpoint_latest` written by earlier epochs of the same run is overwritten). `next_backoff()` is a pure function with unit tests; the environment variable `LAYA_WB_FAKE_OOM=<n>` makes the first n forward passes raise OOM, which is how this path is tested on a CPU.

**Resume**: `<out>/checkpoint_latest` is saved after every epoch (Laya's `finetune` does this) and `epochs_done` is written to `<out>/train.json`. `train --out <same folder> --epochs N --resume` starts from `checkpoint_latest` and trains `N - epochs_done` more epochs; if `N` is not larger than the epochs already done, it errors and asks you to raise it. The learning-rate schedule is recomputed for the remaining epochs, so strictly speaking this is "continue from the latest checkpoint for the remaining epochs", not a bit-exact restore.

## 7. `decision_server.py` — the model server

Replaces `python -m laya.serve`, built on `laya.router.Router` + `laya.serve.create_app` + uvicorn, and serves official weights and your own models together.

```
decision_server.py --host 127.0.0.1 --port 8000 --device auto
                   [--builtin multilingual,english]      # official models to register; may be empty (self-trained only; never downloads official weights)
                   [--custom name=/abs/path ...]          # trained models (Laya-format folders), repeatable
                   [--default <name>]                     # default model (otherwise the first custom, then the first builtin)
                   [--pin-default]                        # requests without model= all use the default (language routing off)
                   [--preload name,name] [--max-loaded 1] [--api-key KEY]
```

- The request's `model` field accepts custom names (the native `laya.serve._resolve_model` only knows the official names; this process replaces it with "any name registered on the Router passes")
- `GET /health` is unchanged (the launcher uses it for readiness); `GET /v1/models` returns `{"data":[{"id","custom","loaded","source","default"}]}`
- `HF_ENDPOINT` is passed through to Laya's downloads; `LAYA_WB_LANG` sets the language of the start-up log

The launcher assembles the command line from `config.json`: `decision_builtin` → `--builtin`, `data/decision/models/*` → `--custom`, `decision_active` → `--default` + `--pin-default` (while `decision_pin_default` is true), `preload` → `--preload`, `api_key` → `--api-key`.

## 8. Launcher API

The page talks to the launcher (`127.0.0.1:8090`) under `/v1/decision/`, JSON, errors as `{"detail": "..."}`:

```
GET  /v1/decision/env                 probe result (cached; ?refresh=1 re-probes) + encoder list + training-environment status
GET  /v1/decision/datasets            [{name,title,note,rows,created,questions}]
POST /v1/decision/datasets/create     {name,title,note}
POST /v1/decision/datasets/append     {name, rows:[{state,questions,expected}]}
POST /v1/decision/datasets/import     {name, format:"jsonl|csv", text, csv:{text_column,label_column,question,instructions}}
POST /v1/decision/datasets/from_reviews {name, recipe}       self-test cases + review records → dataset
GET  /v1/decision/datasets/rows       ?name=&offset=&limit=
POST /v1/decision/datasets/delete     {name} or {name,index}
GET  /v1/decision/datasets/export     ?name=                  download JSONL
POST /v1/decision/new                 {name, encoder, head_layers, max_len}            → background job
POST /v1/decision/train               {name, base, dataset, mode, epochs, micro_batch, grad_accum, encoder_lr, head_lr, loss, max_len, holdout, resume} → background job
POST /v1/decision/evaluate            {model, dataset}                                 → background job
GET  /v1/decision/jobs                ?id=   {id,kind,state:queued|running|done|error|cancelled,progress,stage,epoch,epochs,step,steps,loss,eta_seconds,log_tail,result,error,started,seconds,loss_curve,oom}
POST /v1/decision/jobs/cancel         {id}
GET  /v1/decision/models              [{name,encoder,params_m,size_mb,fine_tuned,created,train,active,loaded}]
POST /v1/decision/models/delete       {name}
POST /v1/decision/models/activate     {name | ""}       writes decision_active and restarts the model service
GET  /v1/decision/models/info         ?name=
```

Rules: only one training-type job at a time; before training on the GPU the launcher terminates the local model service to free the memory (`decision.paused` in `/_wb/status` becomes true) and restarts it afterwards; job logs are in `data/decision/jobs/<id>.log`.

## 9. Environment variables

| Variable | Meaning |
|---|---|
| `HF_ENDPOINT` | Download endpoint for encoders and official weights (the launcher sets it from `hf_endpoint`; hf-mirror.com by default in a Chinese environment) |
| `LAYA_WB_LANG` | Log language `zh` / `en` |
| `LAYA_WB_DATA` | Location of `data/` |
| `LAYA_WB_CONFIG` | Location of `config.json` (launcher) |
| `LAYA_WB_DECISION_CLI` | Location of the training script (default `app/decision_train.py`; tests use `tests/fake_decision_train.py`) |
| `LAYA_WB_FAKE_OOM` | Tests only: the first n forward passes raise OOM |
| `HF_HUB_OFFLINE=1` | Fully offline (when the encoder is already cached or given as a local folder) |

## 10. Verified vs. estimated

The project was developed without a GPU. Verified end to end on a CPU:

- `new` from a small encoder, `train` in full and lora mode (`docs/verify/` holds the earliest verification scripts), the freezing logic of `freeze`
- OOM back-off (simulated with `LAYA_WB_FAKE_OOM`), `--resume`, `--holdout` + `evaluate`, `info`
- `decision_server.py` registering trained and official models together, `model=` selecting a custom model, `--pin-default` (`docs/verify/serve_custom.py`)
- The launcher's job flow, dataset imports, service pause / resume (`tests/` runs the subprocess contract against the fake script `tests/fake_decision_train.py`)

**Estimated**: the tiers and suggested parameters in §4, and statements such as "e5-small in full mode with micro batch 2 × max_len 384 fits in 4 GB". They rest on parameter counts and common experience; on a real card, trust the actual OOM back-off, and real numbers are welcome as feedback.

## 11. Troubleshooting

**Out of GPU memory (`error kind=oom`)**
The trainer already went down to micro batch 1 and max_len 256 and still ran out. Switch to `--mode lora`, a smaller encoder (`BAAI/bge-small-zh-v1.5` has only 24M parameters), `--grad-ckpt on`, or `--device cpu`. Close other programs that hold GPU memory (the local model service is paused automatically while training on the GPU, but browsers and other Python processes are not).

**Download failed (`error kind=download`)**
The encoder or the official weights could not be downloaded. A Chinese environment uses hf-mirror.com by default; change `hf_endpoint` in `config.json` or set the `HF_ENDPOINT` environment variable; or run `huggingface-cli download <id> --local-dir <dir>` on a machine with access, copy the folder over and pass it as `--encoder <dir>` / `--base <dir>`. For a proxy, set `HTTPS_PROXY` (transformers / huggingface_hub honour it).

**peft is not installed**
lora mode reports "lora mode needs peft". Run the installer again (with `install_training` true) or `.venv/bin/python -m pip install peft`. full / freeze mode do not need peft.

**torchvision will not install / torch became the CPU build after installing it**
torchvision must come from the same build as torch. The installer picks the build from the installed torch's `torch.version.cuda` (for example `cu130`), uses uv's `--torch-backend` or pip's `--index-url https://download.pytorch.org/whl/cu130`, and pins `torch==<installed version>`. Do the same by hand; do not run a bare `pip install torchvision` (on Linux, PyPI's torchvision replaces torch with PyPI's CUDA build).

**Why the laya version is pinned**
`decision_train.py` uses `laya.common.build_model` and `TrainConfig / finetune / save_checkpoint / load_checkpoint / read_data / items_from_rows / dry_run` from `laya.train`; `decision_server.py` replaces `laya.serve._resolve_model`. None of these is a public Laya API and a newer version may rename them. Hence `laya_version: "0.4.0"` by default in `config.json`: the installer installs `laya[serve]==0.4.0` and automatic updates only report. To move to another version: change `laya_version`, run the installer again, then run `probe` and a small training run to confirm compatibility. Clearing `laya_version` restores automatic upgrades at your own risk.

**Training is slow**
On a CPU, e5-small with max_len 256 and a few hundred rows takes a few minutes per epoch; that is normal. On a GPU, check that `probe` reports `device: cuda` (otherwise run the installer again to get the GPU build of torch), keep `amp` on and the micro batch as large as it fits.

**Low accuracy / calibration temperature not fitted**
With fewer than 10 calibration items the temperature stays 1.0 (`calibration.issues` in the result says so); with fewer than one or two hundred rows accuracy varies a lot. Check that the questions' `instructions` and option descriptions are clear, that the answers are balanced, and that `expected` is right; use `evaluate`'s `per_question` and `confusion` to find the question that fails.
