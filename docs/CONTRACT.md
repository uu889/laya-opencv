# laya-opencv — 模块接口约定（开发内部文档）

本项目在 laya-opencv 2.0 基础上扩展。保留原有全部功能；新增两大块：

1. **决策模型训练**（“开源版 JEV”）：用任意 Hugging Face 编码器新建 Laya 格式的决策模型，或微调官方 Laya 权重；训练好的模型由本项目自己的服务端提供 `/v1/systemone`。
2. **目标检测训练**：在原有 cv2.ml 区域分类之外，训练能框出物体的检测模型（torchvision，BSD 许可），并在检测方案（recipe）的 pipeline 里作为一步使用。

依赖原则不变：**启动器 `app/launcher.py` 只用 Python 标准库**；需要 torch 的工作都放在子进程里（`decision_train.py`、`decision_server.py`、`detect_train.py`）。视觉服务 `vision_server.py` 只依赖 OpenCV + numpy，torch 只在检测推理时**按需惰性导入**，没有就报 `model_missing`。

所有用户可见文案都要中英双语：Python 侧用 `MSG = {key: (中文, English)}` + `T(key)`，前端用 `I18N.zh / I18N.en`。

---

## 0. 目录与数据

```
app/
  launcher.py          启动器 + 工作台 HTTP（标准库）              [B 维护]
  decision_jobs.py     决策训练的数据集/任务/子进程管理（标准库）   [B]
  decision_train.py    决策模型训练 CLI（torch + laya，子进程）      [A]
  decision_server.py   决策模型服务端（替代 python -m laya.serve）   [A]
  decision.js          工作台「决策训练」页                          [B]
  detect_train.py      目标检测训练 CLI（torch + torchvision，子进程）[C]
  vision_server.py / vision_train.py / vision_core.py / vision.js   [C]
  numeric.py / wb_lang.py / workbench.html                           [B 为主]
  install.py                                                         [D]
data/                                  （不进版本库）
  datasets/<name>/<label>/*.jpg        区域分类数据集（原有）
  models/<name>.{json,xml}             区域分类模型（原有）
  det/datasets/<name>/images/*.jpg     检测数据集
  det/datasets/<name>/labels/*.txt     YOLO 格式标注：`class_id cx cy w h`（归一化 0~1）
  det/datasets/<name>/classes.json     ["类别0", "类别1", ...]
  det/models/<name>/model.pt + meta.json
  decision/datasets/<name>.jsonl       决策训练数据（每行 {state, questions, expected}）
  decision/datasets/<name>.meta.json   {"title", "note", "created", "rows", "questions": {...模板}}
  decision/models/<name>/              Laya 格式 checkpoint（model.safetensors, rl_agent_config.json, encoder/, tokenizer/, questions.json, train.json）
  decision/jobs/<job_id>.log           训练日志
  decision/gpu.json                    上次探测到的显卡信息
```

环境变量 `LAYA_WB_DATA` 覆盖 `data/` 位置（原有约定，继续沿用）。

---

## 1. 决策训练数据格式（Laya 原生）

JSONL，每行一个对象：

```json
{"state": "钢管表面检测：缺陷占比 8.3%，缺陷数量 31 个。",
 "questions": {
   "pass":  {"type": "noul",   "instructions": "该钢管是否合格？"},
   "grade": {"type": "choice", "instructions": "缺陷数量等级", "criteria": {"few": "不超过 20 个", "many": "超过 20 个"}},
   "score": {"type": "score",  "instructions": "外观评分", "levels": ["差", "中", "好"]}
 },
 "expected": {"pass": false, "grade": "many", "score": 1}}
```

- `type` 只能是 `noul`（是非，expected 为 bool）、`choice`（expected 为 criteria 的 key）、`score`（expected 为 levels 的下标或文本）。
- 字段名是 `instructions`，不是 `question`。choice 的选项是 **dict** `criteria`，不是 list。
- 也接受 laya-opencv 的复核导出格式 `{state, questions, gold}`（`gold` 的值形如 `{"answer": ...}` 或直接答案；Laya 训练器两种都认，但我们统一转成 `expected` 存盘）。
- CSV 导入：列 `text,label`（或在界面上指定列名）→ 自动变成一个 choice 题，题目文本由用户填写。

---

## 2. `decision_train.py` — CLI 契约（A 实现，B 调用）

运行方式：`<venv python> app/decision_train.py <命令> [参数]`。**stdout 每行一个 JSON 对象**（事件流），stderr 自由。退出码 0 成功，非 0 失败（最后一个事件是 `{"event":"error","message":...}`）。

### 事件类型

```json
{"event":"start","command":"train","config":{...}}
{"event":"log","message":"..."}                          // 人类可读日志（会写进任务日志）
{"event":"progress","stage":"download|prepare|train|calibrate|save|evaluate","progress":0.42,
 "epoch":2,"epochs":6,"step":120,"steps":480,"loss":0.61,"lr":2.4e-5,"eta_seconds":300}
{"event":"oom","retry":1,"micro_batch":2,"max_len":384}  // 显存不够，自动降档重试
{"event":"result", ...}                                   // 每个命令各自的结果字段
{"event":"error","message":"...","kind":"oom|data|download|other"}
```

### 命令

**`probe`** — 探测硬件，不加载模型。
```
result: {"device":"cuda|cpu|mps","gpu_name":"NVIDIA GeForce RTX 3050 Laptop GPU","vram_mb":4096,
         "torch":"2.14.1","cuda":"13.0","bf16":true,"laya":"0.3.28","peft":true|false,"torchvision":"0.29"|null,
         "tier":"small|base|large", "recommend": {...见 §4 推荐参数...}}
```

**`encoders`** — 列出内置推荐编码器（不联网）。
```
result: {"encoders":[{"id":"intfloat/multilingual-e5-small","tier":"small","params_m":118,"langs":"multi","note_zh":"...","note_en":"..."},...]}
```
内置列表（至少）：
| id | tier | 说明 |
|---|---|---|
| intfloat/multilingual-e5-small | small | 1.18 亿，多语，4G 显卡默认 |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | small | 1.18 亿，多语 |
| BAAI/bge-small-zh-v1.5 | small | 0.24 亿，中文 |
| BAAI/bge-base-zh-v1.5 | base | 1.02 亿，中文 |
| intfloat/multilingual-e5-base | base | 2.78 亿，多语 |
| jhu-clsp/mmBERT-base | base | 3.07 亿，多语，Laya multilingual 用的底座 |
| answerdotai/ModernBERT-base | base | 1.49 亿，英文 |
| answerdotai/ModernBERT-large | large | 3.95 亿，英文 |
以及三个官方 Laya 权重作为「微调起点」：`convaiinnovations/laya-multilingual`、`convaiinnovations/laya`、`convaiinnovations/laya-typed-decisions`（tier 分别 base/large/large）。

**`new`** — 从编码器新建空白 Laya 格式 checkpoint。
```
new --encoder <hf_id_or_local_dir> --out <dir> [--head-layers 2] [--max-len 512] [--head-max-len 192] [--hf-endpoint URL]
result: {"out":"...","encoder":"...","params_m":118.3,"encoder_params_m":117.6,"hidden":384}
```
下载用 `HF_ENDPOINT` 环境变量（B 会按 config 的 `hf_endpoint` 传）。进度事件 stage=`download`。

**`train`** — 训练（新建的空白模型或官方权重都走这里）。
```
train --data <jsonl> --base <checkpoint_dir | hf_id | multilingual|english|typed-decisions> --out <dir>
      [--mode full|freeze|lora] [--lora-r 16] [--epochs 4] [--micro-batch 8] [--grad-accum 8]
      [--encoder-lr 2.5e-5] [--head-lr 1e-4] [--loss rlcd|soft-ce] [--max-len 512] [--head-max-len 192]
      [--amp auto|on|off] [--grad-ckpt auto|on|off] [--calib-frac 0.1] [--seed 0]
      [--resume]           # 从 <out>/checkpoint_latest 继续
      [--holdout 0.1]      # 切出验证集，训完评估
      [--device auto|cuda|cpu]
      [--dry-run]          # 只统计数据，不加载模型
result: {"out":"...","epochs_done":4,"train_items":192,"calib_items":48,"skipped":{...},
         "holdout":{"items":20,"accuracy":{"noul":0.9,"choice":0.85,"score":null,"all":0.88}},
         "calibration":{...laya 原样...},"seconds":812.3,"peak_vram_mb":2890,"mode":"lora"}
```
要求：
- `--mode lora` 用 `peft`（`LoraConfig(target_modules=...)` 自动按编码器类型选 q/k/v/dense 等线性层）；**保存前 `merge_and_unload()`**，落盘的仍是普通 Laya checkpoint，推理端无感。peft 没装 → `error kind=other` 并提示安装。
- `--mode freeze` = 冻结编码器的词嵌入（`get_input_embeddings()`），其余照常训（比 Laya 自带的 `freeze_encoder` 温和，4G 上 base 模型可用）。
- OOM 处理：捕获 `torch.cuda.OutOfMemoryError` → micro_batch 减半（最小 1，同时 grad_accum 翻倍保持有效 batch）→ 仍 OOM 则 max_len 降到 384/256 → 仍 OOM 则报 `error kind=oom`。每次重试发 `oom` 事件。
- 断点：每个 epoch 结束后保存到 `<out>/checkpoint_latest`（Laya 的 `finetune` 已经这么做）；`--resume` 时以它为 `--base` 并从记录的 epoch 继续（在 `<out>/train.json` 里记 `epochs_done`）。做不到精确续训时，至少做到「从最新 checkpoint 作为起点再训剩余 epoch」。
- 训练结束写 `<out>/train.json`：命令行参数、数据文件名、起点、result 全部内容、时间戳；`<out>/questions.json` 由 Laya 生成（题目模板）。
- 进度：至少每 10 step 一次 `progress`，带 loss；用 Laya `TrainConfig(log_every=...)` 之外的方式拿到 step 级进度（例如包一层 `on_epoch_end` + 替换 `print` 或传 callback；读 `laya/train.py` 决定）。
- `peak_vram_mb` 用 `torch.cuda.max_memory_allocated()`。

**`evaluate`** — 用一份 JSONL 评估一个 checkpoint。
```
evaluate --data <jsonl> --model <dir> [--device]
result: {"items":120,"accuracy":{"noul":..,"choice":..,"score":..,"all":..},"per_question":{"pass":{"n":60,"accuracy":0.93},...},
         "confusion":{"pass":{"true":{"true":28,"false":2},...}}}
```

**`info`** — 读 checkpoint 元信息，不加载权重。
```
info --model <dir>
result: {"encoder":"...","encoder_type":"XLMRobertaModel","params_m":..,"max_len":512,"fine_tuned":true,"train":{...train.json...},"size_mb":450}
```

### 对 laya 内部 API 的依赖
用 `laya.common.build_model`、`laya.train.{TrainConfig, finetune, save_checkpoint, load_checkpoint, read_jsonl, items_from_rows, dry_run}`。这些不是公开 API，所以项目**锁定 laya 版本**（见 §6）。

---

## 3. `decision_server.py` — 模型服务（A 实现，B 启动）

替代 `python -m laya.serve`。用 `laya.router.Router` + `laya.serve.create_app` + uvicorn。

```
decision_server.py --host 127.0.0.1 --port 8000 --device auto
                   [--builtin multilingual,english]      # 要注册的官方模型（可为空）
                   [--custom name=/abs/path ...]          # 本项目训练的模型，可多个
                   [--default <name>]                     # 默认模型
                   [--pin-default]                        # 没指定 model 的请求一律用默认模型（关掉语言路由）
                   [--preload <name,name>] [--max-loaded 1] [--api-key KEY]
```
要求：
- 自定义模型名必须能通过 HTTP 的 `model` 字段指定（原生 `laya.serve._resolve_model` 会把未知名字丢掉）：在本进程里 monkeypatch `laya.serve._resolve_model`，让 Router 已注册的名字直接通过。
- `--pin-default`：`on_route` 钩子，当路由原因不是 `explicit model=` 时，把决策改成默认模型（已验证可行，见 `docs/verify/serve_custom.py`）。
- `/health` 原样（启动器靠它判断就绪）。额外提供 `GET /v1/models` 返回 `{"data":[{"id":name,"custom":bool,"loaded":bool,"source":...}]}`（如果 laya.serve 已有同名端点，就在 app 上覆盖/包一层）。
- 环境变量 `HF_ENDPOINT` 透传给 Laya 下载。

---

## 4. 显存档位与推荐参数（A 在 `probe` 里实现，B 展示）

| vram_mb | tier | 推荐编码器 | 推荐 mode | micro_batch × grad_accum | max_len | amp |
|---|---|---|---|---|---|---|
| 无 GPU | small | e5-small | full | 4 × 16 | 256 | off |
| < 6000 | small | e5-small | full；base 模型用 lora | 2 × 32 | 384 | on |
| 6000–11000 | base | e5-base / mmBERT-base | full；large 用 lora | 4 × 16 | 512 | on |
| ≥ 11000 | large | ModernBERT-large / laya 官方 | full | 8 × 8 | 512 | on |

`recommend` 字段返回：`{"encoder":..., "mode":..., "micro_batch":.., "grad_accum":.., "max_len":.., "amp":true, "grad_ckpt":true, "note_zh":..., "note_en":...}`。

---

## 5. 启动器新增 HTTP 接口（B 实现，前端 decision.js 调用）

全部挂在 `/v1/decision/`，JSON，错误格式 `{"detail": "..."}`，和原有接口一致。

```
GET  /v1/decision/env                 probe 结果（缓存到 data/decision/gpu.json，?refresh=1 重新探测）+ encoders 列表 + 训练环境状态（torch/laya/peft/torchvision 是否可用）
GET  /v1/decision/datasets            [{name,title,note,rows,created,questions}]
POST /v1/decision/datasets/create     {name,title,note}
POST /v1/decision/datasets/append     {name, rows:[{state,questions,expected}]}         // 标注界面逐条加
POST /v1/decision/datasets/import     {name, format:"jsonl|csv", text, csv:{text_column,label_column,question,instructions}}  // 粘贴/上传内容
POST /v1/decision/datasets/from_reviews {name, recipe}                                  // 把 laya-opencv 的自检用例+复核记录导入（复用 export_finetune）
GET  /v1/decision/datasets/rows       ?name=&offset=&limit=   分页读行
POST /v1/decision/datasets/delete     {name} 或 {name,index}
GET  /v1/decision/datasets/export     ?name=  下载 JSONL
POST /v1/decision/new                 {name, encoder, head_layers, max_len}            → 后台任务
POST /v1/decision/train               {name(out), base, dataset, mode, epochs, micro_batch, grad_accum, encoder_lr, head_lr, loss, max_len, holdout, resume} → 后台任务
POST /v1/decision/evaluate            {model, dataset} → 后台任务
GET  /v1/decision/jobs                ?id=   任务列表/单个任务：{id,kind,state:queued|running|done|error|cancelled,progress,stage,epoch,epochs,step,steps,loss,eta_seconds,log_tail:[..],result,error,started,seconds}
POST /v1/decision/jobs/cancel         {id}
GET  /v1/decision/models              [{name,encoder,params_m,size_mb,fine_tuned,created,train:{...},active:bool,loaded:bool}]
POST /v1/decision/models/delete       {name}
POST /v1/decision/models/activate     {name | "" }   设为默认并重启 decision_server（写 config.json 的 decision_active）
GET  /v1/decision/models/info         ?name=
```

任务规则：
- 同时只跑一个训练类任务（new / train / evaluate 共享一把锁）。
- **训练前**：若 device 是 cuda 且本地决策服务是本启动器拉起的子进程，先 `terminate` 它释放显存，置 `SERVICE.mode="paused"`；训练结束（成功或失败）后重新拉起。页面上「文本判定」在此期间显示「模型服务已暂停：正在训练」。
- 子进程 stdout 逐行解析 JSON 事件更新任务；非 JSON 行当作日志。任务日志落盘 `data/decision/jobs/<id>.log`。
- 取消 = terminate 子进程。

`/_wb/status` 增加字段：`"decision": {"active": name|null, "custom_models": [...names], "training": job_id|null, "paused": bool}`。

「文本判定」页的模型下拉：本地模型列表 = 内置三个 + 自定义模型名；`is_laya_model()` 要把自定义模型名也算进去（否则会被当成远程模型）。

---

## 6. config.json 新增键（D 写进 config.example.json，B/A 读取）

```json
"laya_version": "0.3.28",          // 锁定版本；auto_update 默认改为 "check"
"install_training": true,          // 安装 peft、torchvision（决策模型 LoRA 与目标检测需要）
"decision_active": "",             // 当前默认的自定义决策模型名；空 = 用官方 multilingual
"decision_pin_default": true,      // 有自定义默认模型时，未指定 model 的请求都用它
"decision_builtin": "multilingual",// 决策服务要注册的官方模型，逗号分隔；空 = 不注册官方模型（纯自训）
"detect_device": "auto"
```

---

## 7. 目标检测（C 实现）

### `detect_train.py` CLI（事件流格式同 §2）
```
probe                                   → {"torch":..,"torchvision":..,"device":..,"vram_mb":..}
train --dataset <dir> --out <dir> [--arch ssdlite|fasterrcnn_mobile] [--epochs 20] [--batch 8] [--imgsz 320]
      [--lr 0.01] [--device auto] [--resume] [--holdout 0.15]
      → result {"out":..,"classes":[..],"epochs_done":..,"map50":0.71,"per_class":{..},"seconds":..,"peak_vram_mb":..}
predict --model <dir> --image <path> [--conf 0.4]   → result {"boxes":[{"label","score","bbox":[x,y,w,h]}]}
```
- 默认 `ssdlite320_mobilenet_v3_large`（快、4G 显存够）；备选 `fasterrcnn_mobilenet_v3_large_320_fpn`。从 torchvision 预训练权重微调（下载走 `TORCH_HOME`；中文环境可能连不上，要给出手动放置路径的提示）。
- 保存 `model.pt`（state_dict）+ `meta.json` `{"arch","classes","imgsz","map50","created","torchvision"}`。
- OOM：batch 减半重试，同 §2。
- 4G 上 batch 8、imgsz 320 实测要能跑（无法实测时按估算写默认值，并在 meta 里标注）。

### vision_server 新增接口（C）
```
GET  /v1/vision/det/datasets                       [{name,images,boxes,classes}]
POST /v1/vision/det/datasets/create                {name, classes:[..]}
POST /v1/vision/det/datasets/add                   {name, image(dataURL), boxes:[{label, bbox:[x,y,w,h]}], size:[W,H]}  // 像素坐标，服务端转 YOLO 归一化
POST /v1/vision/det/datasets/label                 {name, file, boxes:[...]}   // 改一张图的标注
GET  /v1/vision/det/datasets/image                 ?name=&file=   原图；?thumb=1 缩略图
GET  /v1/vision/det/datasets/items                 ?name=&offset=&limit=  [{file,boxes,size}]
POST /v1/vision/det/datasets/delete                {name, file?}
POST /v1/vision/det/datasets/demo                  {scene, name, count}  用 vision_demo 的 bbox 生成合成检测数据集（后台任务）
POST /v1/vision/det/datasets/prelabel              {name, file, recipe}  用现有方案的分割区域生成候选框，便于标注
POST /v1/vision/det/train                          {dataset, name, arch, epochs, batch, imgsz} → 后台任务（子进程 detect_train.py，解析事件流）
GET  /v1/vision/det/models                         [{name, classes, arch, map50, created}]
POST /v1/vision/det/models/delete                  {name}
POST /v1/vision/det/predict                        {model, image, conf} → {boxes:[..], image(annotated dataURL)}
```
任务进度沿用 `/v1/vision/jobs`。

### recipe pipeline 新步骤（C，在 vision_core）
```json
{"op": "detect", "model": "my-detector", "conf": 0.4, "classes": ["weed"], "as": "regions:weeds"}
```
产出的 regions 和现有分割产出的 regions 结构一致，后面的 `measure` / `count` / `classify` 步骤照常用。模型文件不存在 → notes 加 `model_missing:<name>`（沿用现有约定）。推理在 vision_server 内惰性 `import torch, torchvision`；没有 torch → 同样 `model_missing`，并在 health 里报 `"detect": {"available": false, "reason": "torch not installed"}`。

### 前端（C，vision.js）
「视觉训练」页（原「模型训练」改名）分两个子页：**区域分类**（原有内容）和**目标检测**：数据集管理、画框标注（canvas 上拖拽画矩形、选类别、删除框、上一张/下一张）、从方案预标注、合成样本、训练参数与进度、模型列表、试一张图。

---

## 8. 工作台页签（B 改 workbench.html）

```
文本判定 | 视觉检测 | 视觉训练 | 决策训练
```
`data-view` 值：`text | vision | train | decision`。`decision.js` 通过 `/_wb/decision.js` 提供，暴露 `window.WBD = {onView, onStatus, onLang}`，launcher 的 `applyView/pollStatus/setLang` 里调用（和 `WBV` 并列）。

「决策训练」页布局（从上到下）：
1. **训练环境**卡片：显卡 / 显存 / 档位 / torch / laya / peft；一句话推荐；「重新探测」。决策服务状态（运行中 / 训练中已暂停 / 未安装）。
2. **数据集**：列表 + 新建；选中后：行数、题目模板、分页浏览、删除行；**标注器**（state 文本框 + 题目编辑器复用文本判定页的题目组件样式 + 每题选答案 → 「加入数据集」）；导入（粘贴 JSONL/CSV、选文件）；「从检测方案导入」（选 recipe）；导出。
3. **模型**：列表（名字、底座、参数量、准确率、是否当前默认）→ 设为默认 / 评估 / 删除 / 详情。「新建模型」：选编码器（按档位分组、标注推荐）→ 名字 → 建。
4. **训练**：起点（已有模型 / 官方权重）、数据集、模式（full/freeze/lora，按档位默认）、轮数、batch、学习率、损失、max_len、留出比例、续训 → 开始；进度条 + 阶段 + epoch/step + loss 曲线（简单 canvas 折线）+ 日志尾部 + 取消；结果卡（准确率、校准、显存峰值、用时）。

---

## 9. 测试（各自补，CI 不装 torch）

- `tests/` 里的测试不能依赖 torch / laya / peft（CI 只装 opencv + numpy）。torch 相关的测试放 `tests/gpu/`，默认跳过（`unittest.skipUnless(importlib.util.find_spec("torch"))`）。
- 子进程契约用假脚本测：`tests/fake_decision_train.py` 打印事件流，`decision_jobs` 解析它。
- 数据集导入/格式校验、CSV→JSONL、配置读写、推荐档位函数（纯函数）要有单测。

## 10. 版本与命名

- 项目名 `laya-opencv`，`VERSION = "1.0"`，页面标题、启动窗口标题、User-Agent 同步改。
- Windows 快捷方式名、Release 包名改成 `laya-opencv-*`。
- README 保留 laya-opencv 的全部说明并新增两章：「决策模型训练」「目标检测训练」；中英文各一份。
