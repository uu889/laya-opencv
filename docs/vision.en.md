# Writing inspection recipes

[中文](vision.md) | **English**

A recipe is a JSON file under `recipes/zh/` or `recipes/en/`; each file is one button on the Visual inspection tab. Files placed directly in `recipes/` show in both languages; "Save as my recipe" on the page writes `recipes/my-*.json`.

Fields starting with an underscore (`_title` for the button, `_note` for the description) are used only by the page.

```json
{
  "_title": "Steel pipe inspection",
  "_note": "one-line description",
  "id": "steel-pipe",
  "subject": "Outer surface of a seamless steel pipe",
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

| Field | Purpose |
|---|---|
| `subject` | One-line description of what is inspected; written into the material given to the model |
| `max_side` | Processing size: images whose long side is larger are scaled down first. Pixel parameters in `pipeline` refer to this size. Default 1280 |
| `calibration.mm_per_px` | Millimetres per pixel of the original image. With it, lengths are in mm and areas in mm²; without it, pixels |
| `quality` | Image quality gate: `min_sharpness` (variance of the Laplacian) and `brightness` (lower and upper limit of mean brightness, 0 to 255). Failing it marks the verdict for review |
| `model` | Default decision model; a model name typed at the top of the page takes precedence |
| `demo` / `train` | Used by the built-in recipes: the sample-image scene and the parameters for "Train a sample model" |

## pipeline: processing the image step by step

Each step has an `op` and produces a named result that later steps and measurements refer to.

### mask: segment a mask

```json
{"op": "mask", "name": "rust", "method": "hsv", "ranges": [{"h": [5, 42], "s": [35, 100], "v": [20, 100]}], "within": "pipe", "open": 3, "close": 7, "min_area": 40}
```

| `method` | What it does | Main parameters |
|---|---|---|
| `hsv` | Colour range | `ranges`: hue `h` in 0 to 360 degrees, saturation `s` and value `v` in 0 to 100. `h` as `[340, 20]` wraps around 0 degrees (red) |
| `exg` | Excess-green index, separates green plants from soil | `threshold`: `"otsu"` or a number such as `0.1` |
| `gray` | Brightness threshold | `below` / `above` (0 to 100), or `"otsu": "dark"` / `"bright"`; `channel` may be `gray`, `s`, `v`, `l` |
| `anomaly` | Places that differ strongly from the local background (scratches, holes, broken yarns) | `pre_blur` removes fine texture first; `sigma` background blur radius, or `"background": "median"` with `ksize`; `k` multiple of the robust standard deviation; `min_delta` minimum difference; `polarity`: `dark` / `bright` / `both` |
| `chroma` | Places whose colour deviates from the dominant colour (stains) | `pre_blur`, `k`, `min_delta` |
| `rows` | Bands covering the crop rows, found from a vegetation mask | `from`; `min_spacing` minimum row spacing as a share of the frame; `axis`: `vertical` / `horizontal`; `angle` of the rows |
| `combine` | Combine masks | `of`: list of mask names; `how`: `or` / `and` / `sub` / `not` |

Every method accepts post-processing, applied in this order: `invert`, `within` (keep only the part inside another mask), `exclude`, `open`, `close`, `dilate`, `erode` (kernel diameter in pixels), `fill` (fill holes), `min_area`, `keep_largest` (keep the n largest blobs).

### regions: take individual regions from a mask

```json
{"op": "regions", "name": "defects", "from": "defects", "min_area": 12, "max_area": 5000, "where": {"elongation": [">=", 3]}}
```

Each region has `area`, `length`, `width`, `diameter` (equivalent diameter), `elongation` (length over width), `circularity` (0 to 1), `solidity` (0 to 1) and `bbox`. With `calibration`, the first four are in mm² and mm.

`where` filters by attribute: `{"attr": [">=", 3]}`, `{"attr": {"min": 1, "max": 5}}`, `{"label": "scratch"}`. It can be used in measurements too.

### classify: use a trained model

```json
{"op": "classify", "model": "steel-defects", "on": "regions:defects", "pad": 0.25, "min_prob": 0.5}
```

`on` is `regions:name` (each region gets a `label` and `prob`), `image` (classify the whole image; the result is stored under `into`) or `tiles` (cut the image into blocks of `tile` pixels and classify each; `normal` names the normal class, and blocks of other classes are merged into regions).

If the model has not been trained yet, the step is skipped, measurements that depend on recognition have no value, and rule decisions are unaffected.

### detect: an externally trained ONNX detector

```json
{"op": "detect", "model_file": "data/onnx/pests.onnx", "classes": ["aphid", "whitefly"], "size": 640, "conf": 0.25, "iou": 0.45, "into": "insects"}
```

ONNX exports of the YOLO family are supported (both the v5 and the v8 / v11 output layout). `classes` are the class names used in training, in the same order. If the file is missing, measurements that depend on it are reported as "not measured", and rules bound to them ask for review instead of treating the count as 0.

### detect: a detector trained in this project (object detection)

```json
{"op": "detect", "model": "weed-detector", "conf": 0.4, "classes": ["weed"], "as": "regions:weeds"}
```

`model` is the name of a model trained on the "Vision training → Object detection" page (`data/det/models/<name>/`). `conf` is the confidence threshold; `classes` optionally keeps only those classes; `as` is `regions:name` (`into` is accepted too), default `objects`. The regions have exactly the same shape as those from a `regions` step (`bbox`, `area`, `length`, `width`, `elongation`, `circularity`, …) plus `label` and `prob`, so later `count`, `class_count`, `top_label`, `sum` / `max` measurements use them as usual. The annotated image shows the class and score of every box.

If the model has not been trained, or torch / torchvision are not installed, the step yields no regions, `notes` gets `model_missing:<name>`, and measurements that depend on it are reported as "not measured" (like `classify`); the other steps and rule decisions are unaffected. Inference loads torch lazily inside the vision service, so the first call takes a few seconds.

## measurements

```json
"scratch_len": {
  "label": "Longest scratch", "unit": "mm", "decimals": 1, "guard": 1, "range": [0, 200],
  "compute": {"type": "max", "regions": "defects", "attr": "length", "where": {"elongation": [">=", 4]}}
}
```

| Field | Purpose |
|---|---|
| `label` / `unit` | Display name and unit; written into the material |
| `decimals` | Decimal places. The measurement is rounded to this precision before it is compared and shown |
| `guard` / `guard_pct` | Guard band: when the measurement is within this distance of a threshold (absolute, or a percentage of the threshold), the comparison counts as borderline |
| `bands` | Bands from low to high: `[{"max": 30, "label": "unripe"}, {"max": 70, "label": "turning"}, {"label": "ripe"}]` |
| `limit` | The measurement's own limit `{"min": .., "max": ..}`, written into the material (thresholds used in rules are written automatically) |
| `range` / `typical` | Value range and typical value used when the self-test generates cases |
| `hidden` | `true` = keep it out of the material |
| `compute` | How to compute it, see below. A measurement without `compute` can only come from `values` in the request |

| `compute.type` | Meaning | Parameters |
|---|---|---|
| `area_ratio` | Share of the area covered by a mask (%) | `mask`; `within` (another mask as the denominator; the whole image if omitted) |
| `area` | Area of a mask | `mask` |
| `count` | Number of regions | `regions`, `where` |
| `sum` / `max` / `min` / `mean` | Sum / largest / smallest / mean of a region attribute | `regions`, `attr`, `where` |
| `density` | Count per unit area | `regions`; `per`: `m2` / `dm2` / `cm2`; `within` |
| `mean_channel` | Mean of a channel | `channel`, `mask` |
| `class_count` / `class_ratio` | Count / share recognised as a class | `regions`, `label` |
| `top_label` | The most frequent class | `regions` |
| `label` | Result of whole-image classification | `from` |
| `input` | Supplied in `inputs` of the request (readings from other sensors) | `default` |
| `expr` | Computed from other measurements | `expr`: arithmetic plus `min` `max` `abs` `round` `sqrt`, e.g. `"defect_area / pipe_area * 100"` |

## rules: hard rules

Conditions are comparisons combined with `all`, `any` and `not`. A comparison is `{"m": "measurement", "op": ">=", "value": 70}`; `op` is one of `>=` `>` `<=` `<` `==` `!=` `in` `between`.

A yes/no rule uses `when`:

```json
"pick": {"label": "Meets the picking standard", "when": {"all": [{"m": "ripe_ratio", "op": ">=", "value": 70}, {"m": "blemish_ratio", "op": "<=", "value": 3}]}}
```

A graded rule uses `cases`; the first one that holds, top to bottom, wins, and the last one has no `when` and acts as the default:

```json
"verdict": {"label": "Inspection result", "cases": [
  {"value": "Reject", "when": {"any": [{"m": "scratch_len", "op": ">", "value": 20}, {"m": "pit_count", "op": ">=", "value": 2}]}},
  {"value": "Concession", "when": {"m": "defect_count", "op": ">=", "value": 1}},
  {"value": "Accept"}]}
```

## questions and bindings

`questions` uses exactly the format of the Text decisions tab (`noul` yes/no, `choice`, `score`).

`bindings` ties questions to rules:

```json
"bindings": {"pick": {"rule": "pick"}, "verdict": {"rule": "verdict", "mode": "advise"}}
```

- A yes/no question binds to a yes/no rule; a choice question binds to a graded rule whose `value`s are options of the question; a score question binds to a graded rule whose `value`s are level indexes
- `mode` defaults to `enforce`: the rule's result is the verdict and the model's answer is only a cross-check. With `advise`, the model's answer is the verdict and the rule's result is the reference. Run the numeric self-test first and consider `advise` only when agreement is high enough
- For a bound question, the standard is appended to the question text sent to the model. Add `"show_standard": false` to leave it out
- Unbound questions are answered by the model alone

## draw: the annotated image

```json
"draw": [
  {"mask": "rust", "color": "#f59e0b", "alpha": 0.35, "label": "rust"},
  {"regions": "defects", "color": "#e11d48", "label": "defects", "colors": {"scratch": "#3b82f6"}}
]
```

Without `draw`, all regions are drawn. The numbers on the image match the table on the Measurements tab.

## Endpoints

Everything the page uses can be called directly. The `X-WB-Target` header selects the interface for the decision model (`auto` / `local` / the id of a remote interface).

| Endpoint | Purpose |
|---|---|
| `POST /v1/inspect` | `{recipe, image or values, context, model, min_confidence, use_model, inputs}` → measurements, material, a verdict per question. `recipe` is a recipe id or a complete recipe object |
| `POST /v1/inspect/selftest` | `{recipe, model, limit}` → numeric self-test report |
| `GET /v1/inspect/selftest?recipe=` | The last self-test report |
| `POST /v1/inspect/review` | `{recipe, state, questions, gold}` → records one human review |
| `GET /v1/inspect/export?recipe=` | Exports `{state, questions, gold}` JSONL |
| `POST /v1/vision/analyze` | `{recipe, image, inputs}` → image analysis only, no decision model |
| `GET /v1/vision/datasets`, `POST /v1/vision/datasets/add` | Datasets |
| `POST /v1/vision/train`, `GET /v1/vision/jobs?id=` | Training and progress |
| `GET /v1/vision/models`, `POST /v1/vision/predict` | Model list and single-image classification |

The full parameters are described in the comments at the top of `app/vision_server.py` and `app/launcher.py`.

## A sensible order for tuning

1. Fix the capture conditions: distance, angle, lighting, background. This matters more than any algorithm parameter
2. Put a ruler in the frame and work out `mm_per_px`
3. Write only the segmentation steps first and check the annotated image on the page; measure H, S and V with a colour picker and leave some margin
4. Add measurements and check the numbers against a few images with known results
5. Write rules and questions with thresholds from your own standard; set `guard` for measurements that are unreliable near a threshold
6. Train a recognition model only when you need to tell classes apart
7. Once a decision model is connected, run the numeric self-test

## Object detection

The "Vision training" page has two sub-tabs: **Region classification** (the original small cv2.ml classifiers) and **Object detection** (torchvision SSDLite / Faster R-CNN, which draws a box around every target in an image). Detection needs `install_training` (torch + torchvision); without it, datasets and labelling still work, training and inference are disabled, and the `detect` field of `GET /v1/vision/health` says why.

### Data

```
data/det/datasets/<name>/images/*.jpg      images
data/det/datasets/<name>/labels/*.txt      YOLO format: one `class_id cx cy w h` per line (normalised 0–1)
data/det/datasets/<name>/classes.json      ["crop", "weed"]
data/det/models/<name>/model.pt + meta.json
```

This is the usual YOLO layout, so data labelled with LabelImg, Roboflow and similar tools can be copied in directly (do not forget `classes.json`). The labeller on the page: choose an image (or click a thumbnail to open an existing one), drag on the image to draw a box, pick its class, save; click a box to change its class or press Delete to remove it. "Pre-label from recipe" proposes boxes from an existing recipe's segmentation / classification steps for you to correct. "Generate synthetic samples" creates demo data with boxes from the five built-in scenes.

### Training

Parameters: network (`ssdlite` is fast and fits a 4 GB GPU, the default; `fasterrcnn_mobile` is a bit more accurate and slower), epochs, batch size, input size, holdout fraction, pretrained weights (`auto`: try to download torchvision's ImageNet backbone weights, and train from scratch with a hint about where to place the file manually if the download fails; `yes`: fail if the download fails; `no`: train from scratch). Training runs in the subprocess `app/detect_train.py`; progress (epoch / step / loss / ETA) and the log are shown on the page, and the job can be cancelled. Out-of-memory errors halve the batch size and retry automatically. The result is mAP@0.5 on the holdout set plus per-class AP.

Manual weights: download `https://download.pytorch.org/models/mobilenet_v3_large-8738ca79.pth` into `%TORCH_HOME%\hub\checkpoints\` (default `~/.cache/torch/hub/checkpoints/`), then train with `auto` or `yes`.

The CLI can be used directly too (one JSON event per stdout line):

```
python app/detect_train.py probe
python app/detect_train.py train --dataset data/det/datasets/demo-weed --out data/det/models/weed-det --epochs 20 --batch 8 --imgsz 320 [--pretrained auto|yes|no] [--resume]
python app/detect_train.py predict --model data/det/models/weed-det --image photo.jpg --conf 0.4
```

### Using it in a recipe

See the `detect` section under pipeline above: `{"op": "detect", "model": "weed-det", "conf": 0.4, "as": "regions:weeds"}`.

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/vision/det/datasets` | datasets `[{name, images, boxes, classes}]` |
| `POST /v1/vision/det/datasets/create` | `{name, classes}` |
| `POST /v1/vision/det/datasets/add` | `{name, image, boxes:[{label, bbox:[x,y,w,h]}], size}` in pixels; the server converts to YOLO |
| `POST /v1/vision/det/datasets/label` | `{name, file, boxes}` replace one image's labels |
| `GET /v1/vision/det/datasets/items?name=&offset=&limit=` | paged images with boxes |
| `GET /v1/vision/det/datasets/image?name=&file=[&thumb=1]` | image / thumbnail |
| `POST /v1/vision/det/datasets/delete` | `{name, file?}` |
| `POST /v1/vision/det/datasets/demo` | `{scene, name, count}` synthetic dataset (background job) |
| `POST /v1/vision/det/datasets/prelabel` | `{name, file, recipe}` candidate boxes from a recipe |
| `POST /v1/vision/det/train` | `{dataset, name, arch, epochs, batch, imgsz, pretrained, holdout, resume}` → background job; progress in `GET /v1/vision/jobs?id=` (with `epoch/epochs/step/steps/loss/eta_seconds/log_tail`) |
| `POST /v1/vision/jobs/cancel` | `{id}` cancel a job |
| `GET /v1/vision/det/models`, `POST /v1/vision/det/models/delete` | list / delete models |
| `POST /v1/vision/det/predict` | `{model, image, conf}` → `{boxes, image}` (annotated) |
