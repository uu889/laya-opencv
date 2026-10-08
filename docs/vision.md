# 检测方案的写法

**中文** | [English](vision.en.md)

检测方案是 `recipes/zh/`、`recipes/en/` 下的 JSON 文件，一个文件对应「视觉检测」页上的一个按钮。直接放在 `recipes/` 下的文件在两种语言下都显示；在页面上「另存为我的方案」会存成 `recipes/my-*.json`。

以下划线开头的字段（`_title` 按钮名、`_note` 说明）只给页面用。

```json
{
  "_title": "钢管质检",
  "_note": "一句话说明",
  "id": "steel-pipe",
  "subject": "无缝钢管外表面",
  "max_side": 640,
  "calibration": {"mm_per_px": 0.2},
  "quality": {"min_sharpness": 5, "brightness": [40, 230]},
  "model": "multilingual",
  "pipeline": [ ... ],
  "draw": [ ... ],
  "measurements": { ... },
  "rules": { ... },
  "questions": { ... },
  "bindings": { ... }
}
```

| 字段 | 作用 |
|---|---|
| `subject` | 检测对象的一句话描述，会写进交给模型的素材 |
| `max_side` | 处理尺寸：长边超过它的图先等比缩小。`pipeline` 里的像素参数都按这个尺寸算。默认 1280 |
| `calibration.mm_per_px` | 原图上每个像素代表多少毫米。写了它，长度按 mm、面积按 mm² 输出；不写就是像素 |
| `quality` | 图像质量门槛：`min_sharpness`（拉普拉斯方差）和 `brightness`（平均亮度的上下限，0~255）。不合格时结论标成建议复核 |
| `model` | 默认的判定模型名；页面顶部填了模型名时以页面为准 |
| `demo` / `train` | 内置方案用：示例图的场景，以及「训练示例模型」用的参数 |

## pipeline：一步一步处理图像

每一步有一个 `op`，产出一个有名字的结果，后面的步骤和测量值按名字引用。

### mask：分割出一张掩膜

```json
{"op": "mask", "name": "rust", "method": "hsv", "ranges": [{"h": [5, 42], "s": [35, 100], "v": [20, 100]}], "within": "pipe", "open": 3, "close": 7, "min_area": 40}
```

| `method` | 做什么 | 主要参数 |
|---|---|---|
| `hsv` | 按颜色范围取 | `ranges`：色相 `h` 用 0~360 度，饱和度 `s`、亮度 `v` 用 0~100。`h` 写成 `[340, 20]` 表示跨过 0 度（红色） |
| `exg` | 超绿指数，从土壤背景里分出绿色植物 | `threshold`：`"otsu"` 或一个数（如 `0.1`） |
| `gray` | 按亮度取 | `below` / `above`（0~100），或 `"otsu": "dark"` / `"bright"`；`channel` 可选 `gray`、`s`、`v`、`l` |
| `anomaly` | 和局部背景差得多的地方（划痕、破洞、断纱） | `pre_blur` 先抹掉细纹理；`sigma` 背景模糊半径，或 `"background": "median"` + `ksize`；`k` 稳健标准差的倍数；`min_delta` 最小差值；`polarity`：`dark` / `bright` / `both` |
| `chroma` | 颜色偏离主色调的地方（污渍） | `pre_blur`、`k`、`min_delta` |
| `rows` | 从植被掩膜里找出作物行的条带 | `from`；`min_spacing` 行距占画面的最小比例；`axis`：`vertical` / `horizontal`；`angle` 行的倾角 |
| `combine` | 合并掩膜 | `of`：掩膜名的列表；`how`：`or` / `and` / `sub` / `not` |

所有方法都可以加后处理，按这个顺序执行：`invert`、`within`（只保留某个掩膜内的部分）、`exclude`、`open`、`close`、`dilate`、`erode`（核的直径，像素）、`fill`（填洞）、`min_area`、`keep_largest`（只留最大的 n 块）。

### regions：从掩膜里取出一个个区域

```json
{"op": "regions", "name": "defects", "from": "defects", "min_area": 12, "max_area": 5000, "where": {"elongation": [">=", 3]}}
```

每个区域有这些属性：`area`（面积）、`length`（长）、`width`（宽）、`diameter`（等效直径）、`elongation`（长宽比）、`circularity`（圆度，0~1）、`solidity`（实心度，0~1）、`bbox`。写了 `calibration` 时，前四个的单位是 mm² 和 mm。

`where` 用来按属性筛选：`{"属性": [">=", 3]}`、`{"属性": {"min": 1, "max": 5}}`、`{"label": "scratch"}`。测量值里也可以用。

### classify：用训练出的模型分类

```json
{"op": "classify", "model": "steel-defects", "on": "regions:defects", "pad": 0.25, "min_prob": 0.5}
```

`on` 可以是 `regions:区域名`（给每个区域标上 `label` 和 `prob`）、`image`（整图分类，结果存进 `into`）或 `tiles`（把图切成 `tile` 大小的块逐块分类，`normal` 是正常类别的名字，其余类别的块合并成区域）。

模型还没训练时这一步会被跳过，依赖识别结果的测量值没有值，规则裁决不受影响。

### detect：外部训练好的 ONNX 检测模型

```json
{"op": "detect", "model_file": "data/onnx/pests.onnx", "classes": ["aphid", "whitefly"], "size": 640, "conf": 0.25, "iou": 0.45, "into": "insects"}
```

支持 YOLO 系列导出的 ONNX（v5 和 v8 / v11 两种输出排布）。`classes` 是训练时的类别名，顺序要一致。模型文件不存在时，依赖它的测量值记为「没有测到」，绑定的规则会提示复核，而不是按 0 处理。

### detect：本项目训练的检测模型（目标检测）

```json
{"op": "detect", "model": "weed-detector", "conf": 0.4, "classes": ["weed"], "as": "regions:weeds"}
```

`model` 是「视觉训练 → 目标检测」页训练出的模型名（`data/det/models/<name>/`）。`conf` 是置信度阈值；`classes` 可选，只保留这几类；`as` 写成 `regions:名字`（也接受 `into`），默认 `objects`。产出的区域和 `regions` 步骤的结构完全一样（`bbox`、`area`、`length`、`width`、`elongation`、`circularity`…），并带 `label` 和 `prob`，后面的 `count`、`class_count`、`top_label`、`sum` / `max` 等测量值照常引用。标注图上会写出类别和分数。

模型还没训练、或没有安装 torch / torchvision 时，这一步产出零个区域，`notes` 里记 `model_missing:<name>`，依赖它的测量值记为「没有测到」（和 `classify` 一样），其余步骤和规则裁决不受影响。推理在视觉服务里按需加载 torch，第一次调用会慢几秒。

## measurements：测量值

```json
"scratch_len": {
  "label": "最长划痕", "unit": "mm", "decimals": 1, "guard": 1, "range": [0, 200],
  "compute": {"type": "max", "regions": "defects", "attr": "length", "where": {"elongation": [">=", 4]}}
}
```

| 字段 | 作用 |
|---|---|
| `label` / `unit` | 显示的名字和单位，会写进素材 |
| `decimals` | 小数位。测量值先四舍五入到这个位数，再拿去比较和显示 |
| `guard` / `guard_pct` | 临界带：测量值离阈值不超过它（绝对值，或阈值的百分比）时，这次比较算「临界」 |
| `bands` | 档位，从低到高：`[{"max": 30, "label": "未熟"}, {"max": 70, "label": "转色"}, {"label": "成熟"}]` |
| `limit` | 这一项自己的限值 `{"min": .., "max": ..}`，会写进素材（规则里用到的阈值会自动写，不用重复） |
| `range` / `typical` | 自检生成用例时用的取值范围和典型值 |
| `hidden` | `true` = 不写进素材 |
| `compute` | 怎么算，见下表。不写 `compute` 的项只能由接口的 `values` 提供 |

| `compute.type` | 含义 | 参数 |
|---|---|---|
| `area_ratio` | 掩膜面积占比（%） | `mask`；`within`（分母用另一个掩膜，不写就是整幅图） |
| `area` | 掩膜面积 | `mask` |
| `count` | 区域个数 | `regions`、`where` |
| `sum` / `max` / `min` / `mean` | 区域某个属性的合计 / 最大 / 最小 / 平均 | `regions`、`attr`、`where` |
| `density` | 单位面积的个数 | `regions`；`per`：`m2` / `dm2` / `cm2`；`within` |
| `mean_channel` | 某个通道的平均值 | `channel`、`mask` |
| `class_count` / `class_ratio` | 识别为某一类的个数 / 占比 | `regions`、`label` |
| `top_label` | 数量最多的类别 | `regions` |
| `label` | 整图分类的结果 | `from` |
| `input` | 由请求里的 `inputs` 提供（其它传感器的读数） | `default` |
| `expr` | 用其它测量值算出来 | `expr`：四则运算和 `min` `max` `abs` `round` `sqrt`，如 `"defect_area / pipe_area * 100"` |

## rules：硬规则

条件由比较和 `all`（且）、`any`（或）、`not`（非）组成。比较写成 `{"m": "测量值名", "op": ">=", "value": 70}`，`op` 可以是 `>=` `>` `<=` `<` `==` `!=` `in` `between`。

是非规则写 `when`：

```json
"pick": {"label": "达到采摘标准", "when": {"all": [{"m": "ripe_ratio", "op": ">=", "value": 70}, {"m": "blemish_ratio", "op": "<=", "value": 3}]}}
```

分档规则写 `cases`，从上往下第一个成立的生效，最后一档不写 `when` 作为兜底：

```json
"verdict": {"label": "质检结论", "cases": [
  {"value": "不合格", "when": {"any": [{"m": "scratch_len", "op": ">", "value": 20}, {"m": "pit_count", "op": ">=", "value": 2}]}},
  {"value": "让步接收", "when": {"m": "defect_count", "op": ">=", "value": 1}},
  {"value": "合格"}]}
```

## questions 和 bindings

`questions` 和「文本判定」页的题目格式完全一样（`noul` 是非、`choice` 单选、`score` 打分）。

`bindings` 把题目绑到规则上：

```json
"bindings": {"pick": {"rule": "pick"}, "verdict": {"rule": "verdict", "mode": "advise"}}
```

- 是非题绑是非规则；单选题绑分档规则，规则的 `value` 必须是题目的选项；打分题绑分档规则，`value` 是等级的序号
- `mode` 默认是 `enforce`：规则的结果就是结论，模型的答案只用来核对。`advise`：模型的答案是结论，规则的结果作为参照。先跑「数字自检」，一致率够高再考虑改成 `advise`
- 绑定了规则的题目，发给模型时题干后面会自动附上判定标准。不想附的话加 `"show_standard": false`
- 没有绑定的题目完全由模型回答

## draw：标注图

```json
"draw": [
  {"mask": "rust", "color": "#f59e0b", "alpha": 0.35, "label": "锈斑"},
  {"regions": "defects", "color": "#e11d48", "label": "缺陷", "colors": {"scratch": "#3b82f6"}}
]
```

不写 `draw` 时画出所有区域。图上的编号对应「测量与区域」页签里的表格。

## 接口

页面用到的接口都可以直接调用，请求头 `X-WB-Target` 指定判定模型走哪个接口（`auto` / `local` / 远程接口的 id）。

| 接口 | 作用 |
|---|---|
| `POST /v1/inspect` | `{recipe, image 或 values, context, model, min_confidence, use_model, inputs}` → 测量、素材、每题结论。`recipe` 可以是方案的 id，也可以是完整的方案对象 |
| `POST /v1/inspect/selftest` | `{recipe, model, limit}` → 数字自检报告 |
| `GET /v1/inspect/selftest?recipe=` | 上一次的自检报告 |
| `POST /v1/inspect/review` | `{recipe, state, questions, gold}` → 记下一条人工复核 |
| `GET /v1/inspect/export?recipe=` | 导出 `{state, questions, gold}` 的 JSONL |
| `POST /v1/vision/analyze` | `{recipe, image, inputs}` → 只做图像分析，不调用判定模型 |
| `GET /v1/vision/datasets`、`POST /v1/vision/datasets/add` | 数据集 |
| `POST /v1/vision/train`、`GET /v1/vision/jobs?id=` | 训练和进度 |
| `GET /v1/vision/models`、`POST /v1/vision/predict` | 模型列表和单张图分类 |

完整的参数说明在 `app/vision_server.py` 和 `app/launcher.py` 开头的注释里。

## 调参的顺序

1. 固定拍摄条件：距离、角度、光照、背景。这比任何算法参数都重要
2. 在画面里放一把尺，算出 `mm_per_px`
3. 先只写分割步骤，在页面上看标注图对不对；颜色范围用取色工具量出 H、S、V 再留一点余量
4. 加上测量值，用几张已知结果的图核对数值
5. 写规则和题目，阈值来自你的标准；给贴近阈值时不可靠的测量值设 `guard`
6. 需要区分类别时再训练识别模型
7. 接上判定模型后跑一次「数字自检」

## 目标检测

「视觉训练」页分两个子页：**区域分类**（原有的 cv2.ml 小分类器）和**目标检测**（torchvision 的 SSDLite / Faster R-CNN，能在一张图里框出每个目标）。目标检测需要 `install_training`（torch + torchvision）；没装时数据集和标注照常可用，训练和推理按钮不可用，`GET /v1/vision/health` 的 `detect` 字段会说明原因。

### 数据

```
data/det/datasets/<name>/images/*.jpg      图片
data/det/datasets/<name>/labels/*.txt      YOLO 格式：每行 class_id cx cy w h（0~1 归一化）
data/det/datasets/<name>/classes.json      ["crop", "weed"]
data/det/models/<name>/model.pt + meta.json
```

这就是 YOLO 系列通用的标注格式，用 LabelImg、Roboflow 等工具标好的数据可以直接拷进来（别忘了 `classes.json`）。页面上的标注器：选一张图（或点缩略图打开已有的图）→ 在图上拖动画框 → 选类别 → 保存；点框选中后可以改类别或按 Delete 删除。「从方案预标注」用现有方案的分割 / 识别步骤给出候选框，再手动修正。「生成合成样本」用五个内置场景生成带框的演示数据。

### 训练

参数：网络（`ssdlite` 快、4G 显存够，默认；`fasterrcnn_mobile` 略准、略慢）、轮数、批大小、输入尺寸、留出验证比例、预训练权重（`auto`：尝试下载 torchvision 的 ImageNet 骨干权重，下载不到就从头训练并在日志里提示手动放置的路径；`yes`：下载不到就报错；`no`：从头训练）。训练在子进程 `app/detect_train.py` 里跑，进度（轮 / 步 / 损失 / 预计剩余时间）和日志显示在页面上，可以取消；显存不足会自动把批大小减半重试。训练完给出留出集上的 mAP@0.5 和每类 AP。

手动放置预训练权重：把 `https://download.pytorch.org/models/mobilenet_v3_large-8738ca79.pth` 下载到 `%TORCH_HOME%\hub\checkpoints\`（默认 `~/.cache/torch/hub/checkpoints/`），再用 `auto` 或 `yes` 训练。

命令行也可以直接用（stdout 每行一个 JSON 事件）：

```
python app/detect_train.py probe
python app/detect_train.py train --dataset data/det/datasets/demo-weed --out data/det/models/weed-det --epochs 20 --batch 8 --imgsz 320 [--pretrained auto|yes|no] [--resume]
python app/detect_train.py predict --model data/det/models/weed-det --image photo.jpg --conf 0.4
```

### 在方案里使用

见上面 pipeline 的 `detect` 一节：`{"op": "detect", "model": "weed-det", "conf": 0.4, "as": "regions:weeds"}`。

### 接口

| 接口 | 作用 |
|---|---|
| `GET /v1/vision/det/datasets` | 数据集列表 `[{name, images, boxes, classes}]` |
| `POST /v1/vision/det/datasets/create` | `{name, classes}` |
| `POST /v1/vision/det/datasets/add` | `{name, image, boxes:[{label, bbox:[x,y,w,h]}], size}` 像素坐标，服务端转成 YOLO |
| `POST /v1/vision/det/datasets/label` | `{name, file, boxes}` 改一张图的标注 |
| `GET /v1/vision/det/datasets/items?name=&offset=&limit=` | 分页列出图片和框 |
| `GET /v1/vision/det/datasets/image?name=&file=[&thumb=1]` | 原图 / 缩略图 |
| `POST /v1/vision/det/datasets/delete` | `{name, file?}` |
| `POST /v1/vision/det/datasets/demo` | `{scene, name, count}` 合成数据集（后台任务） |
| `POST /v1/vision/det/datasets/prelabel` | `{name, file, recipe}` 用方案生成候选框 |
| `POST /v1/vision/det/train` | `{dataset, name, arch, epochs, batch, imgsz, pretrained, holdout, resume}` → 后台任务，进度在 `GET /v1/vision/jobs?id=`（含 `epoch/epochs/step/steps/loss/eta_seconds/log_tail`） |
| `POST /v1/vision/jobs/cancel` | `{id}` 取消任务 |
| `GET /v1/vision/det/models`、`POST /v1/vision/det/models/delete` | 模型列表 / 删除 |
| `POST /v1/vision/det/predict` | `{model, image, conf}` → `{boxes, image}`（带标注图） |
