# laya-opencv

> Formerly laya-workbench (Laya Workbench).

[中文](README.md) | **English**

A local workbench and one-click installer for decision models, for Windows and Linux, with a Chinese and an English interface. Version 2.0 adds visual inspection: OpenCV looks and measures, the decision model draws the conclusion, for agriculture and quality-control scenarios.

[Laya](https://github.com/NandhaKishorM/laya) and TypeSafe's Jev are decision models: you give them some material (state) and a few questions, and they return a probability distribution for each question instead of generated text. This project bundles the installation and start-up of local Laya with a web workbench, so the same request can be sent to the local model or to a remote Jev interface.

![Workbench](docs/screenshot.en.png)

Decision models read text only; they cannot see images. Visual inspection connects the two as a pipeline:

```
image → OpenCV segmentation, recognition, measurement → numeric layer (hard rules, written out as text) → decision model → rule and model cross-checked → verdict
```

![Visual inspection](docs/screenshot-vision.en.png)

The screenshot shows steel pipe inspection in "Decide by rules only" mode; the image is a synthetic sample.

## Features

- One-click install: creates a virtual environment and installs PyTorch (matched to your GPU), `laya[serve]`, and the vision components (OpenCV, optional)
- Visual inspection: upload an image, capture one from the camera or use a sample; a recipe measures areas, counts, lengths and shares, then each question gets a verdict
- Five built-in recipes: fruit picking, weed control, pest monitoring, steel pipe inspection, fabric inspection. Recipes are JSON files and can be edited on the page
- Numeric layer: conclusions that depend on numbers are decided by hard rules, and the model's answer is used as a cross-check; disagreement, borderline values and low confidence are flagged for human review
- Model training: upload samples per class on the page and train a recognition model that classifies regions (OpenCV's `cv2.ml`; seconds to tens of seconds on a CPU)
- Numeric self-test: generates boundary cases on both sides of every threshold to measure how well the decision model handles numbers
- Automatic updates: every start checks for a new Laya version and upgrades to it; if the new version fails to start, it is rolled back
- Web workbench: material as text, JSON object or message list; yes/no, choice and score questions
- Several interfaces: Auto, local Laya, TypeSafe (official), aiask.me (accelerated), and any third-party service that offers `/v1/systemone`
- Keys are added, changed and deleted on the page and stored only on your machine
- Automatic fallback when a remote interface fails; batch requests are split into single calls for remote interfaces
- Chinese and English interface, switchable at any time from the top right of the page
- 8 built-in examples in each language; add your own by dropping JSON files into `examples/`
- Result view, raw response, request JSON, code snippets (curl / Python / JavaScript), history and a debug panel
- The launcher uses only the Python standard library; the vision components need only OpenCV and numpy, and text decisions work without them

## Install and start

Download the latest package from the [Releases](../../releases) page.

### Windows

1. Extract `laya-opencv-*.zip` to a permanent location, for example `D:\laya-opencv`
2. Double-click `install.bat` and wait for it to finish
3. Double-click `start.bat`; the browser opens <http://127.0.0.1:8090>

### Linux

```bash
tar -xzf laya-opencv-*.tar.gz
cd laya-opencv
bash install.sh
bash start.sh
```

Python 3.10 or newer is required. On Debian / Ubuntu run `sudo apt install python3 python3-venv` first.

On a server without a desktop, open an SSH tunnel from your own computer and then browse to <http://127.0.0.1:8090> locally:

```bash
ssh -L 8090:127.0.0.1:8090 user@server
```

The first start downloads the local model (multilingual is about 650 MB). You can run requests once the page shows "Local Laya ready". Closing the launcher window, or pressing Ctrl+C, stops everything.

### Remote interfaces only

If you do not want the local model on a machine, copy `config.example.json` to `config.json`, set `install_local_laya` and `start_local_laya` to `false`, then run the installer. PyTorch and Laya are skipped and only the vision components (about 80 MB) are installed. If you do not need visual inspection either, set `install_vision` to `false` as well and the install takes a few seconds.

## Visual inspection

The page has three tabs at the top: **Text decisions** is the original workbench; **Visual inspection** and **Model training** are new.

### How to use it

1. Open **Visual inspection** and pick a recipe
2. Choose an image, capture one with the camera, or click a sample image to try the flow first
3. Press **Inspect**. The right side shows the verdict, measurements and regions, the material and questions sent to the model, the raw response, and the numeric self-test

It also works without a decision model (no local Laya and no remote key): tick **Decide by rules only**, or just inspect; questions bound to a rule still get a verdict.

### Built-in recipes

| Recipe | Measures | Rules decide |
|---|---|---|
| Fruit picking | ripe-colour share, blemish share, diameter | pick or not, fruit grade |
| Weed control | cover, count and density of inter-row weeds | weed or not, treatment |
| Pest monitoring | total insects on a sticky trap, large insects, density | act or not, control level |
| Steel pipe inspection | scratch length, pit count, rust share | accept / concession / reject |
| Fabric inspection | defect count, longest defect, hole area | accept / downgrade / reject |

Each recipe also has one or two questions without a bound rule (such as "what is the best use for this fruit" or "how should it be handled"), which the decision model answers from the whole material.

The thresholds in the built-in recipes are for demonstration and are not any industry standard; the segmentation parameters are tuned for the synthetic sample images. Before real use, tune the parameters on your own images and replace the thresholds with your own standard. The full recipe format is in [docs/vision.en.md](docs/vision.en.md).

### How numbers are kept right

Decision models read text and do no arithmetic, and they only output yes/no, a choice or a score. So conclusions that depend on numbers are not left to the model:

- **Rules do the comparing**: every threshold comparison is done in code. Measurements are first rounded to the configured decimals, so the number shown is the number compared
- **Written out as text**: in the material given to the model, each number carries its comparisons, for example `99.3 % (≥ 70 %: yes, 29.3 above)`; the standard in each question uses the same wording, so the two match clause by clause
- **The rule decides**: when a question is bound to a hard rule, the rule's result is final and the model's answer is only a cross-check
- **Flagged for review**: when rule and model disagree, a measurement is inside its guard band, the model's confidence is low, or the image is blurry, too dark or too bright, the verdict is marked for human review
- **Measured, not assumed**: the numeric self-test generates boundary cases on both sides of every threshold, sends the same cases to the model once with bare numbers and once with the written comparisons, and reports agreement with the rules. Questions whose agreement is not high enough should stay rule-decided

Self-test results depend on the model and version you use; go by what your own machine reports. Self-test cases and human review records can be exported as `{state, questions, gold}` JSONL for later fine-tuning.

### Training a recognition model

Classical algorithms can measure colour, area and shape, but cannot tell which insect or which kind of defect something is. The **Model training** tab fills that gap:

1. Create a dataset and upload images per class (or tick regions in an inspection result to add them directly). Each class needs at least 2 images; 30 or more is recommended
2. Pick features (colour, texture, contour gradients, shape and size, deep features) and a classifier (SVM, random forest, k nearest neighbours), then press **Start training**
3. Read the cross-validated accuracy and the confusion matrix
4. Add a step `{"op": "classify", "model": "model name", "on": "regions:region name"}` to the recipe's `pipeline`

The built-in recipes already contain this step. Click **Train a sample model from synthetic images** on the verdict tab to see recognition results appear among the measurements.

Deep features need a pretrained backbone (MobileNetV2, about 14 MB, one click on the training tab) and work much better for visually complex targets.

Dense, overlapping small objects are beyond "segment first, then classify". For those, put an externally trained YOLO-family ONNX detector into `data/onnx/` and reference it in the recipe with `{"op": "detect", ...}`.

### One-shot endpoint

```bash
curl -s http://127.0.0.1:8090/v1/inspect \
  -H "Content-Type: application/json" -H "X-WB-Target: auto" \
  -d '{"recipe": "steel-pipe", "image": "<base64 or data URL>", "context": "the customer requires a rust-free surface"}'
```

The response contains the measurements, the material and questions sent to the model, the final verdict for each question (`verdicts`) and whether review is recommended (`review`). Send `values` (a set of ready-made measurements) instead of `image` to use only the numeric layer and the decision model, which lets you feed in data from other sensors.

### Limits

- The sample images are synthetic and far cleaner than real photos; results on them say nothing about real scenes
- Classical segmentation is sensitive to lighting and background, so keep the capture conditions fixed; pixel parameters in a recipe refer to the `max_side` processing size
- The recognition model is "features plus a small classifier", not a deep detection network; OpenCV cannot train YOLO-style models
- This is a workbench for validating an approach and for small batches, not a production-line inspection system; it outputs decisions and does not drive actuators

## Automatic updates

Every time you run `start.bat` / `start.sh`, two things are checked before the local model starts:

- **The Laya program**: compared with the latest version on PyPI. If there is a newer one, it is installed with pip before the service starts.
- **The model files**: compared with the latest commit on Hugging Face. Laya downloads the newest files itself when it loads the model; the check only tells you in advance whether there is an update.

The outcome is printed in the launcher window, and the page shows a line under the status at the top left, for example "Laya 0.3.26 (up to date), model revision e4e9ddf2".

How the special cases are handled:

- **No network**: the check is skipped and the current version is used; start-up is not affected.
- **The service fails to start after an upgrade**: the previous version is reinstalled and the service is started again. That version is then skipped until a newer one is released.
- **The new version needs a newer PyTorch**: PyTorch is pinned to its current version during the upgrade so that a GPU build is never replaced by a CPU build. In this case the upgrade fails with a message and the current version keeps running; run the installer again to resolve it.
- **A Laya service is already running on port 8000**: the check runs, but nothing is upgraded.

Controlled by `auto_update` in `config.json`: `true` (default, upgrade automatically), `"check"` (check and report only), `false` (no check).

## Language

- **Page**: switch with "中文 / English" at the top right; the choice is remembered. An example you have not edited is swapped for its version in the other language.
- **Installer and launcher window**: follow the system language by default. Set `language` in `config.json` to `zh` or `en` to fix it.
- **Error messages from the service**: follow the language the page is using.

## Interfaces

The "Interface" drop-down at the top left of the page:

| Interface | Where requests go | Key |
|---|---|---|
| Auto (recommended) | Decided by the model name, see below | The key of whichever interface is used |
| Local Laya | `127.0.0.1:8000` on this machine | None |
| TypeSafe (official) | `https://api.typesafe.ai` | A key from the TypeSafe console |
| aiask.me (accelerated) | `https://aiask.me` | An aiask.me key |
| Third-party interface | The address you enter | That service's key; may be left empty |

**How Auto works**

- Model name is `multilingual`, `english`, `typed-decisions`, or empty: local Laya is used
- Any other model name (such as `jev-latest`): the first remote interface in `auto_order` that has a key is used (aiask.me first, then TypeSafe, by default). If it is unreachable, times out or refuses the request (401 / 403 / 404 / 429 / 5xx), the next one is tried

The result view shows which interface answered, and any fallback that happened.

**Managing keys**

"Interface settings" shows only the interface that is selected under "Interface", so the keys never appear side by side:

- No key yet: paste it and click "Add key"
- Key saved: only its last 4 characters are shown; use "Change" or "Delete" (deleting asks for confirmation)
- "Test connection" fetches the model list with the current key, which confirms that the address and key work

Keys are written only to `config.json` on your machine and added to requests by the local launcher; requests sent by the browser never contain them. For TypeSafe and aiask.me the environment variables `TYPESAFE_API_KEY` and `AIASK_API_KEY` work too.

`config.json` is listed in `.gitignore` and is never committed.

**Third-party interfaces**

Pick "+ Add a third-party interface…" in the "Interface" drop-down and enter a name, base URL, key and default model. Any address that serves the `/v1/systemone` format works, for example another gateway, or a Laya service on another machine in your network.

- Enter only the host or path prefix; the workbench appends `/v1/systemone`. A full endpoint URL is accepted too and its ending is removed
- The key may be left empty, for internal services without authentication
- After adding, the name, base URL, default model and key can be changed, and the interface can be deleted
- A third-party interface is used only when selected and is not part of Auto. To include it, add its id from `config.json` (such as `custom-1`) to `auto_order`

**Differences between remote interfaces and local Laya**

- Remote interfaces have no batch endpoint. In batch mode the workbench calls `/v1/systemone` once per item and merges the results; you are billed per item
- `max_len` only applies to local Laya; for remote interfaces the confidence threshold is applied locally by the workbench
- Remote requests follow the system proxy by default; set `proxy` in `config.json` to use a specific one

## Examples

`examples/zh/` and `examples/en/` each hold one set of examples; the page shows the set for the current language. Every `.json` file is a complete request body and becomes one example button:

| File | What it shows |
|---|---|
| `01-ticket-routing.json` | Ticket routing: department, urgency, churn risk |
| `02-content-moderation.json` | Content moderation (batch) |
| `03-rag-relevance.json` | RAG passage relevance |
| `04-llm-output-check.json` | LLM output check |
| `05-email-triage.json` | Email triage (JSON object material) |
| `06-prompt-guard.json` | Prompt guard (message list material) |
| `07-model-routing.json` | Model routing (batch) |
| `08-confidence-gate.json` | Confidence gate |

Add a file in the same format and refresh the page to get another button. `_title` is the button label, `_note` a one-line description, and the remaining fields are the request. Files placed directly in `examples/` (not in a language folder) are shown in both languages.

The files can also be sent straight to local Laya with curl (fields starting with an underscore are ignored):

```bash
curl -s http://127.0.0.1:8000/v1/systemone \
  -H "Content-Type: application/json" \
  --data-binary "@examples/en/01-ticket-routing.json"
```

In Windows PowerShell write `curl.exe`. The two batch examples, which contain `states`, go to `/v1/systemone/batch`.

## Configuration

`config.json` is created from `config.example.json` on the first install or start. Restart after changing it.

| Setting | Meaning |
|---|---|
| `language` | `auto` (follow the system) / `zh` / `en`: language of the installer and launcher window, and the page's default language |
| `ui_host` / `ui_port` | Address and port of the workbench, `127.0.0.1:8090` by default |
| `open_browser` | Open the browser automatically after starting |
| `install_local_laya` | `false` = skip PyTorch and Laya during installation |
| `start_local_laya` | `false` = do not start the local model |
| `laya_host` / `laya_port` | Address of the local Laya service, `127.0.0.1:8000` by default |
| `models` | Models to preload, comma-separated: `multilingual,english,typed-decisions` |
| `default_model` | Model used when the language cannot be detected |
| `device` | `auto` / `cuda` / `cpu` |
| `api_key` | Access key for local Laya, normally empty |
| `install_vision` | `false` = skip OpenCV at install time; visual inspection and training are unavailable |
| `start_vision` | `false` = do not start the vision service |
| `vision_host` / `vision_port` | Address of the vision service, default `127.0.0.1:8001`; only the local launcher talks to it |
| `vision_backbone_urls` | Where to download the backbone. `auto` = hf-mirror.com first in a Chinese environment, then the official addresses; or one or more URLs separated by commas |
| `auto_update` | `true` = upgrade Laya automatically at every start; `"check"` = check and report only; `false` = no check |
| `providers` | Remote interfaces: names, base URL, key, default model |
| `auto_order` | Order in which Auto tries remote interfaces |
| `proxy` | Proxy for remote interfaces; empty = follow the system |
| `remote_timeout` | Timeout for remote requests, in seconds |
| `hf_endpoint` | Where models are downloaded from. `auto` = hf-mirror.com in a Chinese environment, Hugging Face directly otherwise; a URL or an empty value also works |
| `pip_index` | pip index used by the installer and by automatic updates. `auto` = the Tsinghua mirror in a Chinese environment, the official index otherwise; a URL or an empty value also works |
| `torch_index` | A specific PyTorch index; normally empty |
| `desktop_shortcut` | Create a desktop shortcut when installing on Windows |

> With `ui_host` set to `0.0.0.0`, anyone who can reach the port can send requests with your saved keys. Do this only on a trusted network; otherwise keep `127.0.0.1` and use an SSH tunnel.

## Troubleshooting

**A remote interface returns 401 / 403**
The key is wrong, or it has no access to the selected model. "Test connection" under Interface settings lists the models the key can use.

**The aiask.me address is wrong**
Requests go to `https://aiask.me/v1/systemone` by default. If your address differs, change the base URL (without `/v1/systemone`) under Interface settings and save.

**The page keeps showing "Local Laya is loading the model"**
Look at the launcher window: if the model is downloading, keep waiting; if there is an error, deal with that error.

**A port is in use**
If a Laya service is already running on port 8000, the workbench uses it. If another program holds the port, change `laya_port` in `config.json`. The vision service uses 8001; change `vision_port` if that is taken.

**There is an NVIDIA GPU but the device shows cpu**
The CPU build of PyTorch was installed. Pick the command for your CUDA version at <https://pytorch.org/get-started/locally/>, reinstall torch with the virtual environment's `python -m pip`, and restart.

**The Visual inspection tab says the vision components are not installed**
Run the installer again; it adds OpenCV. Both `install_vision` and `start_vision` must be `true` in `config.json`.

**It says this OpenCV has no training module**
The main OpenCV 5 package dropped `cv2.ml`. Running the installer again switches to 4.x; to do it by hand, use `pip install "opencv-python-headless<5"`.

**The backbone download fails**
Download any image-classification network as an `.onnx` file yourself (for example MobileNetV2 from the OpenCV Zoo) and put it into `data/backbones/`.

**The result is far from what you expect**
Look at the Measurements tab and the annotated image first to check the segmentation; then open "Recipe" below the image, adjust colour ranges, minimum areas and so on, press Apply and inspect again.

**The installation failed half-way**
Fix the problem and run the installer again; finished steps are skipped.

## Layout

```
install.bat / install.sh   install
start.bat / start.sh       start
config.example.json        configuration template
examples/zh/  examples/en/ example requests (Chinese / English)
recipes/zh/  recipes/en/   inspection recipes (Chinese / English)
app/workbench.html         the workbench page (both languages)
app/vision.js              the Visual inspection and Model training tabs
app/launcher.py            launcher: starts the local services, serves the page, forwards requests, runs the inspection flow
app/numeric.py             numeric layer: measurement specs, hard rules, wording, verdicts, self-test cases
app/vision_server.py       vision service (local HTTP API)
app/vision_core.py         segmentation, regions, measurements, annotation
app/vision_train.py        feature extraction, training, model management
app/vision_demo.py         synthetic sample images and training samples
app/install.py             installation logic
app/wb_lang.py             language selection
tests/                     tests; mock_laya.py is a fake Laya service for testing only
data/                      created at run time: training images, models, backbone, self-test and review records (not in version control)
```

## Releasing a new version

Push a tag starting with `v`; GitHub Actions builds the packages and creates the release:

```bash
git tag v2.0.0
git push origin v2.0.0
```

## Uninstall

Delete the folder (training images and models live in its `data/` subfolder); on Windows also delete the "laya-opencv" desktop shortcut. Models are cached under `.cache/huggingface` in your home directory and can be deleted as well.

## License

The code in this project is released under the MIT license. The Laya models and the TypeSafe and aiask.me services are subject to their own licenses and terms. OpenCV is released under Apache-2.0; the MobileNetV2 backbone that is downloaded on demand comes from the OpenCV Zoo. Detectors you add yourself keep their own license; Ultralytics YOLO, for example, is AGPL-3.0.
