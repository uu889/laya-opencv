# 决策模型训练参考

**中文** | [English](decision-training.en.md)

这份文档是「决策训练」页背后两个脚本的完整参考：`app/decision_train.py`（训练 CLI）和 `app/decision_server.py`（模型服务）。页面上的用法见 [README「决策模型训练」](../README.md#决策模型训练)。

两个脚本都用虚拟环境里的 Python 运行（Linux `.venv/bin/python`，Windows `.venv\Scripts\python.exe`），依赖 torch、laya（锁定版本）、transformers；lora 模式另需 peft。启动器 `app/launcher.py` 只用标准库，所有需要 torch 的工作都在这两个脚本的子进程里完成。

## 1. 整体流程

```
probe ──→ 看档位与推荐参数
encoders → 选一个编码器
new ─────→ data/decision/models/<name>/        空白 Laya 格式模型（编码器预训练权重 + 随机初始化的决策头）
train ───→ data/decision/models/<name>-v1/     训练；--base 可以是 new 建的目录、官方权重名或任意 HF id
evaluate → 留出数据上的准确率、混淆矩阵
decision_server.py --custom name=<dir> → /v1/systemone
```

官方权重（`multilingual` / `english` / `typed-decisions`，或完整 id `convaiinnovations/laya-*`）不需要 `new`，直接 `train --base multilingual`。

## 2. `decision_train.py` 命令

### 事件流

stdout **每行一个 JSON 对象**，stderr 是自由文本（transformers / laya 自己的输出）。退出码 0 成功；失败时最后一个事件是 `error` 且退出码非 0（`CommandError` 为 2，其他异常为 1，Ctrl+C 为 130）。

```json
{"event":"start","command":"train","config":{...全部参数...}}
{"event":"log","message":"人类可读日志"}
{"event":"progress","stage":"download|prepare|train|calibrate|save|evaluate","progress":0.42,
 "epoch":2,"epochs":6,"step":120,"steps":480,"loss":0.61,"lr":2.4e-5,"eta_seconds":300}
{"event":"oom","retry":1,"micro_batch":2,"grad_accum":64,"max_len":384}
{"event":"result", ...}
{"event":"error","message":"...","kind":"oom|data|download|other"}
```

`log` 的语言由环境变量 `LAYA_WB_LANG=zh|en` 决定（默认中文）；启动器按页面语言传。

### `probe` — 探测硬件（不加载模型）

```
result: {"device":"cuda|cpu|mps","gpu_name":"NVIDIA GeForce RTX 3050 Laptop GPU","vram_mb":4096,
         "torch":"2.14.1+cu130","cuda":"13.0","bf16":true,"torch_cuda_build":true,"gpu_usable":true,
         "laya":"0.3.28","peft":true,"torchvision":"0.29.1","transformers":"...","python":"3.12.x","platform":"...",
         "tier":"small|base|large","recommend":{...§4...},"warnings":["..."]}
```

没装 torch 时也能运行（用 `nvidia-smi` 读显卡名和显存，`warnings` 里说明 torch 缺失）。有 NVIDIA 显卡但 torch 是 CPU 构建时，`gpu_name` / `vram_mb` 来自 `nvidia-smi`，`device` 是 `cpu`，并给出提示。安装脚本和 `GET /v1/decision/env` 都调用它，结果缓存在 `data/decision/gpu.json`。

### `encoders` — 内置编码器（不联网）

```
result: {"encoders":[{"id":"intfloat/multilingual-e5-small","tier":"small","params_m":118,"langs":"multi",
                      "note_zh":"...","note_en":"...","laya":false}, ...]}
```

官方权重带 `"laya": true` 和 `"alias"`（`multilingual` 等）。列表见 README 的编码器表。

### `new` — 从编码器新建空白模型

```
new --encoder <hf_id | 本地目录> --out <dir> [--head-layers 2] [--max-len 512] [--head-max-len 192] [--hf-endpoint URL]
result: {"out":"...","encoder":"...","encoder_type":"XLMRobertaModel","params_m":118.3,"encoder_params_m":117.6,"hidden":384}
```

| 参数 | 说明 |
|---|---|
| `--encoder` | Hugging Face 模型 id 或本地目录（`AutoModel` 能加载的双向编码器：BERT / RoBERTa / XLM-R / ModernBERT / mmBERT / E5 / BGE 等） |
| `--out` | 输出目录；会写 `model.safetensors`、`rl_agent_config.json`、`encoder/`、`tokenizer/`、`train.json`（`epochs_done: 0`） |
| `--head-layers` | 决策头的层数，默认 2 |
| `--max-len` | 素材（state）的最大 token 数，默认 512 |
| `--head-max-len` | 题目文本的最大 token 数，默认 192 |
| `--hf-endpoint` | 下载地址；不给则用环境变量 `HF_ENDPOINT`（启动器按 `config.json` 的 `hf_endpoint` 设置） |

下载阶段发 `progress stage=download`。`params_m` 是总参数量（百万），`hidden` 是编码器的隐藏维度。

### `train` — 训练 / 微调

```
train --data <jsonl> --base <checkpoint_dir | hf_id | multilingual|english|typed-decisions> --out <dir>
      [--mode full|freeze|lora] [--lora-r 16] [--lora-alpha 2r] [--lora-dropout 0.05]
      [--epochs 4] [--micro-batch 8] [--grad-accum 8]
      [--encoder-lr 2.5e-5] [--head-lr 1e-4] [--loss rlcd|soft-ce]
      [--max-len N] [--head-max-len N] [--amp auto|on|off] [--grad-ckpt auto|on|off]
      [--calib-frac 0.1] [--holdout 0.0] [--seed 0] [--device auto|cuda|cpu]
      [--resume] [--dry-run] [--hf-endpoint URL]
```

| 参数 | 说明 |
|---|---|
| `--data` | JSONL 训练数据（§3） |
| `--base` | 起点：`new` 建的目录、训练过的模型目录、官方权重名或任何 Laya 格式的 HF 仓库 id。`--resume` 时不需要 |
| `--out` | 输出目录。可以和 `--base` 相同（原地继续训练） |
| `--mode` | `full`（默认）全参数；`freeze` 冻结编码器词嵌入（`get_input_embeddings()`）；`lora` 用 peft 加 LoRA 适配层（§5） |
| `--lora-r` / `--lora-alpha` / `--lora-dropout` | LoRA 秩（默认 16）、alpha（默认 2×r）、dropout（默认 0.05） |
| `--epochs` | 目标总轮数（续训时含已完成的轮数） |
| `--micro-batch` × `--grad-accum` | 每步前向的样本数 × 梯度累积步数 = 有效 batch。推荐值见 §4 |
| `--encoder-lr` / `--head-lr` | 编码器和决策头的学习率（余弦退火） |
| `--loss` | `rlcd`（Laya 默认的强化学习式损失）或 `soft-ce`（软交叉熵） |
| `--max-len` / `--head-max-len` | 覆盖 checkpoint 里的序列长度；不给则沿用 |
| `--amp` | 混合精度：`auto` 由 Laya 按设备决定（cuda 上开），`on` / `off` 强制 |
| `--grad-ckpt` | 梯度检查点（省显存、慢一些）：同上三态 |
| `--calib-frac` | 切出多少比例做温度校准（默认 0.1；校准样本太少时温度保持 1.0 并在结果里说明） |
| `--holdout` | 切出多少比例做验证（默认 0 = 不切），训完自动 `evaluate` |
| `--seed` | 切分和初始化的随机种子 |
| `--device` | `auto`（有 cuda 用 cuda）/ `cuda` / `cpu` |
| `--resume` | 从 `<out>/checkpoint_latest` 继续（§6） |
| `--dry-run` | 只读数据、统计可训练样本和跳过原因，不加载模型 |

结果：

```
result: {"out":"...","base":"...","mode":"lora","epochs_done":4,"epochs":4,
         "train_items":192,"calib_items":48,"skipped":{"原因":次数},
         "holdout":{"items":48,"rows":24,"accuracy":{"noul":0.9,"choice":0.85,"score":null,"all":0.88},
                    "per_question":{...},"confusion":{...}},
         "calibration":{...laya 的校准报告...},"temperature":[...],"epoch_loss":[...],
         "micro_batch":2,"grad_accum":32,"max_len":384,"oom_retries":1,
         "seconds":812.3,"peak_vram_mb":2890,"device":"cuda","encoder":"...","encoder_type":"..."}
```

`train_items` 是「题目」数而不是行数（一行有几道题就是几个样本）。`peak_vram_mb` 来自 `torch.cuda.max_memory_allocated()`。`skipped` 记录因为缺答案、答案不在选项里等原因跳过的题。

`<out>/train.json` 记录命令行、数据文件名、起点、`epochs_done`、每轮 loss 历史、模式信息（LoRA 目标层、冻结参数量）和完整的 result；`<out>/questions.json` 是题目模板（由数据里的题目汇总，页面「载入模板」用）。

### `evaluate` — 评估

```
evaluate --data <jsonl> --model <dir> [--device auto] [--batch-size 16]
result: {"model":"...","data":"...","items":120,"rows":60,
         "accuracy":{"noul":0.93,"choice":0.85,"score":0.7,"all":0.86},
         "per_question":{"pass":{"n":60,"correct":56,"type":"noul","accuracy":0.93},...},
         "confusion":{"pass":{"true":{"true":28,"false":2},"false":{"true":2,"false":28}},...},"skipped":{...}}
```

`confusion[q][正确答案][模型答案]` = 次数。打分题按等级下标比较。

### `info` — 读元信息（不加载权重）

```
info --model <dir>
result: {"model":"...","encoder":"...","encoder_type":"XLMRobertaModel","hidden":384,"params_m":118.3,
         "max_len":512,"head_max_len":192,"head_layers":2,"fine_tuned":true,"temperature":[...],
         "train":{...train.json...},"questions":{...questions.json...},"has_latest":true,"size_mb":450,"created":"..."}
```

`fine_tuned` 来自 `rl_agent_config.json`（Laya 训练后写入）；`has_latest` 表示有 `checkpoint_latest` 可以续训。`params_m` 从 `model.safetensors` 的头部读出，不加载张量。

## 3. 数据格式

JSONL，每行一个对象，Laya 原生格式：

```json
{"state": "素材文本，也可以是 JSON 对象或消息列表（和 /v1/systemone 一样）",
 "questions": {
   "pass":  {"type": "noul",   "instructions": "该钢管是否合格？"},
   "grade": {"type": "choice", "instructions": "缺陷数量等级", "criteria": {"few": "不超过 20 个", "many": "超过 20 个"}},
   "score": {"type": "score",  "instructions": "外观评分", "levels": ["差", "中", "好"]}
 },
 "expected": {"pass": false, "grade": "many", "score": 1}}
```

- `type`：`noul`（是非，expected 为 bool）、`choice`（expected 是 `criteria` 的 key）、`score`（expected 是 `levels` 的下标或等级文本）
- 字段名是 `instructions`（不是 `question`）；choice 的选项是 **对象** `criteria`（不是数组）
- `expected` 里可以只给一部分题的答案；没有答案的题会跳过（计入 `skipped`）
- 也接受 laya-opencv 导出的 `{state, questions, gold}`（`gold` 的值形如 `{"answer": ...}` 或直接答案）。启动器导入时统一转成 `expected` 存盘；CLI 直接读两种都行（Laya 的 `read_data` 两种都认）
- 页面的 CSV 导入：列 `text,label`（或指定列名）→ 每行变成一道 choice 题；`criteria` 由出现过的 label 汇总，题目文本（`instructions`）由用户填写

启动器把数据集存在 `data/decision/datasets/<name>.jsonl`，旁边的 `<name>.meta.json` 记 `{"title","note","created","rows","questions"}`（`questions` 是汇总出的题目模板）。

## 4. 显存档位与推荐参数

`probe` 按显存分档（`tier_from_vram`）并给出 `recommend`（`recommend(tier, device)`，两者都是纯函数，`tests/test_decision_pure.py` 有单测）：

| vram_mb | tier | encoder | mode | micro_batch × grad_accum | max_len | amp | grad_ckpt |
|---|---|---|---|---|---|---|---|
| 无 GPU / device 不是 cuda | small | multilingual-e5-small | full | 4 × 16 | 256 | off | off |
| < 6000 | small | multilingual-e5-small | full（base 级编码器用 lora） | 2 × 32 | 384 | on | on |
| 6000 – 11000 | base | multilingual-e5-base | full（large 级用 lora） | 4 × 16 | 512 | on | on |
| ≥ 11000 | large | ModernBERT-large | full | 8 × 8 | 512 | on | off |

`recommend` 字段：`{"encoder","mode","micro_batch","grad_accum","max_len","amp","grad_ckpt","note_zh","note_en"}`。

这些数字是按参数量、序列长度和混合精度估算的，不是在对应显卡上实测的（见下面「实测与估算」）。显存不足时训练会自动降档，所以推荐值偏「先试试」而不是保守值。

## 5. 三种模式

**full**：所有参数参与训练。小编码器（e5-small 1.18 亿、bge-small 0.24 亿）在 4 GB 上用推荐参数即可。

**freeze**：冻结编码器的词嵌入矩阵（`encoder.get_input_embeddings().weight.requires_grad = False`），其余层照常训练。词嵌入通常是编码器里最大的一块参数（多语模型尤其如此，e5-small 的 1.18 亿里约 0.96 亿是词表），冻结后优化器状态和梯度都省了一大截，又不像 Laya 自带的 `freeze_encoder`（整个编码器不动）那样损失表达能力。编码器没有 `get_input_embeddings()` 时退化成 full 并写日志。

**lora**：用 [peft](https://github.com/huggingface/peft) 给编码器的线性层加 LoRA 适配层，只训练适配层和决策头。

- 目标层按编码器类名自动选：ModernBERT 系 → `Wqkv`、`Wo`、`Wi`；BERT / RoBERTa / XLM-R / mmBERT / ELECTRA / DeBERTa 等 → `query`、`key`、`value`、`dense`；认不出来就对编码器里所有 `nn.Linear` 加（`lora_target_modules()`，有单测）
- `r` 默认 16，`alpha` 默认 2r，dropout 0.05，`bias="none"`
- 日志里会写可训练参数量 / 总参数量
- **保存前 `merge_and_unload()`**：LoRA 权重合并回原矩阵，落盘的 `model.safetensors` 是普通 Laya checkpoint，服务端和 `evaluate` 不需要 peft
- 每轮结束保存的 `checkpoint_latest` 同样是合并后的；`--resume` 续训时会在合并后的权重上重新加一层 LoRA
- peft 没装 → `{"event":"error","kind":"other","message":"lora 模式需要 peft…"}`

## 6. OOM 自动降档与断点续训

**OOM**：捕获 `torch.cuda.OutOfMemoryError`（以及 message 里带 "out of memory" 的 RuntimeError）后：

1. `micro_batch` 减半、`grad_accum` 翻倍（有效 batch 不变），最小到 1
2. micro_batch 已经是 1 时，`max_len` 沿 512 → 384 → 256 降
3. 都不行 → `error kind=oom`，建议换 lora 或更小的编码器

每次重试发 `{"event":"oom","retry":n,"micro_batch":..,"grad_accum":..,"max_len":..}`，然后释放显存、从起点重新加载模型、把本次要训的轮数从头再来（之前几轮写下的 `checkpoint_latest` 会被覆盖）。`next_backoff()` 是纯函数，有单测；环境变量 `LAYA_WB_FAKE_OOM=<n>` 让前 n 次前向抛 OOM，用来在 CPU 上测试这条路径。

**续训**：每个 epoch 结束保存 `<out>/checkpoint_latest`（Laya 的 `finetune` 自带），并把 `epochs_done` 写进 `<out>/train.json`。`train --out <同一目录> --epochs N --resume`：以 `checkpoint_latest` 为起点，再训 `N - epochs_done` 轮；`N` 不大于已完成轮数时报错提示调大。学习率调度按剩余轮数重新算，所以严格说是「从最新 checkpoint 作为起点再训剩余轮数」，不是逐步精确恢复。

## 7. `decision_server.py` — 模型服务

替代 `python -m laya.serve`，用 `laya.router.Router` + `laya.serve.create_app` + uvicorn，能同时提供官方权重和自训模型。

```
decision_server.py --host 127.0.0.1 --port 8000 --device auto
                   [--builtin multilingual,english]      # 要注册的官方模型，可为空（纯自训，绝不会下载官方权重）
                   [--custom name=/abs/path ...]          # 自训模型（Laya 格式目录），可多个
                   [--default <name>]                     # 默认模型（不给：第一个 custom，再第一个 builtin）
                   [--pin-default]                        # 没指定 model 的请求一律用默认模型（关掉按语言路由）
                   [--preload name,name] [--max-loaded 1] [--api-key KEY]
```

- 请求体的 `model` 字段可以写自定义模型名（原生 `laya.serve._resolve_model` 只认官方名，这里在本进程里替换成「Router 注册过的名字直接通过」）
- `GET /health` 原样（启动器靠它判断就绪）；`GET /v1/models` 返回 `{"data":[{"id","custom","loaded","source","default"}]}`
- `HF_ENDPOINT` 透传给 Laya 下载；`LAYA_WB_LANG` 决定启动日志语言

启动器按 `config.json` 组装命令行：`decision_builtin` → `--builtin`，`data/decision/models/*` → `--custom`，`decision_active` → `--default` + `--pin-default`（`decision_pin_default` 为 true 时），`preload` → `--preload`，`api_key` → `--api-key`。

## 8. 启动器接口

页面用的 HTTP 接口都挂在启动器（`127.0.0.1:8090`）的 `/v1/decision/` 下，JSON，错误格式 `{"detail": "..."}`：

```
GET  /v1/decision/env                 probe 结果（缓存；?refresh=1 重新探测）+ 编码器列表 + 训练环境状态
GET  /v1/decision/datasets            [{name,title,note,rows,created,questions}]
POST /v1/decision/datasets/create     {name,title,note}
POST /v1/decision/datasets/append     {name, rows:[{state,questions,expected}]}
POST /v1/decision/datasets/import     {name, format:"jsonl|csv", text, csv:{text_column,label_column,question,instructions}}
POST /v1/decision/datasets/from_reviews {name, recipe}       自检用例 + 复核记录 → 数据集
GET  /v1/decision/datasets/rows       ?name=&offset=&limit=
POST /v1/decision/datasets/delete     {name} 或 {name,index}
GET  /v1/decision/datasets/export     ?name=                  下载 JSONL
POST /v1/decision/new                 {name, encoder, head_layers, max_len}            → 后台任务
POST /v1/decision/train               {name, base, dataset, mode, epochs, micro_batch, grad_accum, encoder_lr, head_lr, loss, max_len, holdout, resume} → 后台任务
POST /v1/decision/evaluate            {model, dataset}                                 → 后台任务
GET  /v1/decision/jobs                ?id=   {id,kind,state:queued|running|done|error|cancelled,progress,stage,epoch,epochs,step,steps,loss,eta_seconds,log_tail,result,error,started,seconds,loss_curve,oom}
POST /v1/decision/jobs/cancel         {id}
GET  /v1/decision/models              [{name,encoder,params_m,size_mb,fine_tuned,created,train,active,loaded}]
POST /v1/decision/models/delete       {name}
POST /v1/decision/models/activate     {name | ""}       写 decision_active 并重启模型服务
GET  /v1/decision/models/info         ?name=
```

规则：同时只跑一个训练类任务；GPU 上训练前启动器会 `terminate` 本地模型服务释放显存（`/_wb/status` 的 `decision.paused` 为 true），结束后重新拉起；任务日志在 `data/decision/jobs/<id>.log`。

## 9. 环境变量

| 变量 | 作用 |
|---|---|
| `HF_ENDPOINT` | 编码器和官方权重的下载地址（启动器按 `hf_endpoint` 设置；中文环境默认 hf-mirror.com） |
| `LAYA_WB_LANG` | 日志语言 `zh` / `en` |
| `LAYA_WB_DATA` | `data/` 的位置 |
| `LAYA_WB_CONFIG` | `config.json` 的位置（启动器） |
| `LAYA_WB_DECISION_CLI` | 训练脚本的位置（默认 `app/decision_train.py`；测试用 `tests/fake_decision_train.py`） |
| `LAYA_WB_FAKE_OOM` | 仅测试：前 n 次前向抛 OOM |
| `HF_HUB_OFFLINE=1` | 完全离线（编码器已在缓存或本地目录时） |

## 10. 实测与估算

本项目开发环境没有 GPU。在 CPU 上实测通过的：

- `new` 从一个小编码器建模，`train` 的 full / lora 两种模式（`docs/verify/` 里是最早的验证脚本），`freeze` 的冻结逻辑
- OOM 降档（`LAYA_WB_FAKE_OOM` 模拟）、`--resume`、`--holdout` + `evaluate`、`info`
- `decision_server.py` 同时注册自训模型和官方名、`model=` 指定自定义模型、`--pin-default`（`docs/verify/serve_custom.py`）
- 启动器的任务流、数据集导入、服务暂停 / 恢复（`tests/` 用假脚本 `tests/fake_decision_train.py` 跑子进程契约）

**估算**的部分：§4 的显存档位和推荐参数、「4 GB 显卡上 e5-small full 模式 micro batch 2 × max_len 384 能跑」这类说法。它们基于参数量和常见经验，第一次在真机上训练时请以实际 OOM 降档的结果为准，并欢迎反馈真实数字。

## 11. 故障排查

**显存不足（`error kind=oom`）**
程序已经降到 micro batch 1、max_len 256 仍然 OOM。换 `--mode lora`、换更小的编码器（`BAAI/bge-small-zh-v1.5` 只有 0.24 亿）、`--grad-ckpt on`、或 `--device cpu`。关掉其他占显存的程序（本地模型服务在 GPU 训练时已自动暂停，但浏览器、其他 Python 进程不会）。

**下载失败（`error kind=download`）**
编码器或官方权重下载不下来。中文环境默认走 hf-mirror.com；可以改 `config.json` 的 `hf_endpoint`，或者设置 `HF_ENDPOINT` 环境变量；也可以在有网的机器上 `huggingface-cli download <id> --local-dir <dir>` 后把目录拷过来，`--encoder <dir>` / `--base <dir>`。代理用 `HTTPS_PROXY` 环境变量（transformers / huggingface_hub 认它）。

**peft 没有安装**
`lora` 模式报 `lora 模式需要 peft`。重新运行安装脚本（`install_training` 为 true）或 `.venv/bin/python -m pip install peft`。full / freeze 模式不需要 peft。

**torchvision 装不上 / 装完 torch 变成 CPU 版**
torchvision 必须和 torch 是同一个构建。安装脚本按已装 torch 的 `torch.version.cuda` 选构建（例如 `cu130`），用 uv 的 `--torch-backend` 或 pip 的 `--index-url https://download.pytorch.org/whl/cu130`，并用 `torch==<已装版本>` 固定住 torch。手动装时照这个做，不要直接 `pip install torchvision`（Linux 上 PyPI 的 torchvision 会把 torch 换成 PyPI 的 CUDA 版本）。

**为什么锁定 laya 版本**
`decision_train.py` 用到 `laya.common.build_model` 和 `laya.train` 里的 `TrainConfig / finetune / save_checkpoint / load_checkpoint / read_data / items_from_rows / dry_run`，`decision_server.py` 替换了 `laya.serve._resolve_model`。这些不是 Laya 的公开 API，新版本可能改名。所以 `config.json` 默认 `laya_version: "0.3.28"`：安装脚本装 `laya[serve]==0.3.28`，自动更新只提示不升级。要换版本：改 `laya_version`，重新运行安装脚本，然后跑 `probe` 和一次小数据训练确认兼容；清空 `laya_version` 则恢复自动升级，风险自负。

**训练很慢**
CPU 上 e5-small、max_len 256、几百条数据每轮几分钟属于正常。GPU 上确认 `probe` 的 `device` 是 `cuda`（不是就重新运行安装脚本装 GPU 版 torch），`amp` 开着，micro batch 尽量大。

**准确率低 / 校准温度没拟合**
校准样本不足 10 条时温度保持 1.0（结果的 `calibration.issues` 会说明）；数据少于一两百条时准确率波动很大。先检查题目的 `instructions` 和选项说明是否清楚、各类答案是否均衡、`expected` 是否写错；用 `evaluate` 看 `per_question` 和 `confusion` 定位是哪道题的问题。
