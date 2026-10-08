# -*- coding: utf-8 -*-
"""laya-opencv 安装脚本 / laya-opencv installer.

步骤：虚拟环境 → PyTorch → Laya（锁定版本）→ 训练组件（torchvision、peft，可选）→ 检查
      → 探测显卡与训练档位 → 检测预训练权重（可选）→ 视觉组件（OpenCV，可选）→ 收尾。

由 install.bat / install.sh 调用，Windows、Linux 通用。可以重复运行，已装好的部分会跳过。
Called by install.bat / install.sh. Safe to re-run: finished steps are skipped.

    python app/install.py            install
    python app/install.py --dry-run  only print the commands

config.json 里和安装有关的键（见 README「配置」）：
    install_local_laya   false = 跳过 PyTorch / Laya / 训练组件，只用远程接口
    install_training     false = 不装 torchvision 和 peft（没有目标检测训练和 LoRA 模式）
    install_vision       false = 不装 OpenCV
    laya_version         锁定的 laya 版本（训练脚本依赖 laya 的内部接口）；空 = 装最新版
    pip_index / torch_index / proxy / desktop_shortcut
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wb_lang  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
VENV = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
DRY_RUN = "--dry-run" in sys.argv
DATA = Path(os.environ.get("LAYA_WB_DATA") or (ROOT / "data"))

PROJECT = "laya-opencv"
# 训练脚本（decision_train.py）用到 laya.train / laya.common 的内部接口，所以默认锁定这个版本；
# config.json 的 laya_version 可以改，留空则装最新版（自动更新也会随之恢复）
LAYA_VERSION_DEFAULT = "0.3.28"

DEFAULTS = {
    "language": "auto",
    "pip_index": "auto",
    "torch_index": "",
    "proxy": "",
    "install_local_laya": True,
    "install_training": True,
    "install_vision": True,
    "laya_version": LAYA_VERSION_DEFAULT,
    "desktop_shortcut": True,
}
# 视觉组件：OpenCV 5 的主包去掉了训练模块（cv2.ml），所以固定用 4.x
VISION_PACKAGES = ["opencv-python-headless>=4.9,<5", "numpy"]
# 训练组件：目标检测要 torchvision（必须和 torch 同一个构建），决策模型的 lora 模式要 peft
TRAINING_PACKAGES = ["peft"]
# 目标检测的预训练骨干权重（torchvision，BSD-3）；和 app/detect_train.py 里的常量一致。
# 放在 TORCH_HOME/hub/checkpoints/ 下，torchvision 加载时就不会再去下载
DETECT_WEIGHT_URL = "https://download.pytorch.org/models/mobilenet_v3_large-8738ca79.pth"
DETECT_WEIGHT_FILE = "mobilenet_v3_large-8738ca79.pth"
PYTORCH_INDEX = "https://download.pytorch.org/whl/"

# 每条消息: (中文, English)
MSG = {
    "cfg_bad": ("[!] config.json 格式有误，已改用默认配置: %s", "[!] config.json is not valid JSON; using defaults: %s"),
    "cmd_failed": ("\n[!] 上面的命令失败了（退出码 %d），安装中止。", "\n[!] The command above failed (exit code %d); installation stopped."),
    "torch_have": ("  已安装 torch %s（GPU %s），跳过。", "  torch %s is already installed (GPU %s); skipping."),
    "gpu_yes": ("可用", "available"),
    "gpu_no": ("不可用", "not available"),
    "torch_index": ("  按 config.json 的 torch_index 安装 PyTorch。", "  Installing PyTorch from torch_index in config.json."),
    "torch_gpu": ("  检测到 NVIDIA 显卡，安装 GPU 版 PyTorch（体积约 2~3 GB，需要一些时间）。",
                  "  NVIDIA GPU found; installing the GPU build of PyTorch (about 2-3 GB, this takes a while)."),
    "torch_cpu": ("  没有检测到 NVIDIA 显卡，安装 CPU 版 PyTorch。", "  No NVIDIA GPU found; installing the CPU build of PyTorch."),
    "torch_fallback": ("  [!] 自动选择 PyTorch 版本失败，改用 pip 默认版本安装。",
                       "  [!] Could not pick a PyTorch build automatically; installing pip's default build."),
    "shortcut_name": (PROJECT, PROJECT),
    "shortcut_done": ("  已在桌面创建快捷方式「%s」。", '  Created the desktop shortcut "%s".'),
    "title": ("  %s 安装程序", "  %s installer"),
    "dir": ("  安装目录: %s", "  Install folder: %s"),
    "need_py": ("[!] 需要 Python 3.10 或更高版本，当前是 %s。", "[!] Python 3.10 or newer is required; this is %s."),
    "s_venv": ("准备虚拟环境 (.venv)", "Prepare the virtual environment (.venv)"),
    "venv_have": ("  已存在，直接使用。", "  Already there; using it."),
    "venv_fail": ("[!] 创建虚拟环境失败。", "[!] Could not create the virtual environment."),
    "venv_apt": ("\n    Debian / Ubuntu 请先执行: sudo apt install python3-venv", "\n    On Debian / Ubuntu run first: sudo apt install python3-venv"),
    "s_torch": ("安装 PyTorch", "Install PyTorch"),
    "s_laya": ("安装 Laya 和服务端组件", "Install Laya and the server components"),
    "laya_pin": ("  锁定 laya %s（训练脚本依赖它的内部接口；要换版本请改 config.json 的 laya_version）。",
                 "  Pinning laya %s (the training scripts depend on its internal API; change laya_version in config.json to use another)."),
    "laya_latest": ("  config.json 里 laya_version 为空：安装最新版 laya。训练脚本可能和新版本不兼容。",
                    "  laya_version is empty in config.json: installing the latest laya. The training scripts may not work with a newer version."),
    "s_training": ("安装训练组件（torchvision、peft）", "Install the training components (torchvision, peft)"),
    "tv_have": ("  已安装 torchvision %s，跳过。", "  torchvision %s is already installed; skipping."),
    "tv_backend": ("  按已安装的 torch %s（%s 构建）安装同一构建的 torchvision。",
                   "  Installing the torchvision build that matches the installed torch %s (%s build)."),
    "tv_fail": ("  [!] torchvision 没有装上：目标检测训练暂时不可用，其余功能不受影响。\n"
                "      解决网络问题后重新运行安装脚本即可补装。",
                "  [!] torchvision could not be installed: object-detection training is unavailable for now; everything else works.\n"
                "      Run the installer again once the network problem is fixed."),
    "peft_have": ("  已安装 peft %s，跳过。", "  peft %s is already installed; skipping."),
    "peft_fail": ("  [!] peft 没有装上：决策模型训练的 lora 模式暂时不可用（full / freeze 模式照常）。\n"
                  "      解决网络问题后重新运行安装脚本即可补装。",
                  "  [!] peft could not be installed: the lora mode of decision-model training is unavailable for now (full / freeze work).\n"
                  "      Run the installer again once the network problem is fixed."),
    "training_skip": ("\n  config.json 里 install_training 为 false：跳过 torchvision 和 peft，\n"
                      "  不提供目标检测训练和决策模型的 lora 模式。",
                      "\n  install_training is false in config.json: skipping torchvision and peft;\n"
                      "  object-detection training and the lora mode of decision training will be unavailable."),
    "s_check": ("检查安装结果", "Check the installation"),
    "dry_skip": ("  (dry-run，跳过检查)", "  (dry run, check skipped)"),
    "check_fail": ("[!] 检查没有通过：laya=%s，服务端组件=%s，torch=%s", "[!] Check failed: laya=%s, server components=%s, torch=%s"),
    "check_pin": ("  [!] 安装到的 laya 是 %s，不是 config.json 锁定的 %s；训练脚本可能不兼容。",
                  "  [!] The installed laya is %s, not the pinned %s from config.json; the training scripts may not be compatible."),
    "gpu_ok": ("  GPU    可用 (%s)", "  GPU    available (%s)"),
    "gpu_wrong_build": ("  GPU    不可用 —— 有 NVIDIA 显卡，但当前 PyTorch 不是 GPU 版。\n"
                        "         Laya 会用 CPU 运行（能用，只是慢一些）。想用 GPU，\n"
                        "         请到 https://pytorch.org/get-started/locally/ 选择对应命令，\n"
                        "         用 %s -m pip 重新安装 torch。",
                        "  GPU    not available: there is an NVIDIA GPU, but this PyTorch is not a GPU build.\n"
                        "         Laya will run on the CPU (it works, just slower). To use the GPU,\n"
                        "         pick the matching command at https://pytorch.org/get-started/locally/\n"
                        "         and reinstall torch with %s -m pip."),
    "gpu_none": ("  GPU    不可用，使用 CPU 运行。", "  GPU    not available; running on the CPU."),
    "lib_line": ("  %-12s%s", "  %-12s%s"),
    "lib_missing": ("未安装", "not installed"),
    "remote_only": ("\n  config.json 里 install_local_laya 为 false：跳过 PyTorch、Laya 和训练组件，\n"
                    "  工作台只使用远程接口（TypeSafe / aiask.me）。",
                    "\n  install_local_laya is false in config.json: skipping PyTorch, Laya and the training components.\n"
                    "  The workbench will use remote interfaces only (TypeSafe / aiask.me)."),
    "s_probe": ("探测显卡与训练档位", "Probe the GPU and the training tier"),
    "probe_gpu": ("  显卡    %s", "  GPU     %s"),
    "probe_vram": ("  显存    %s", "  VRAM    %s"),
    "probe_device": ("  设备    %s（torch %s，CUDA %s，bf16 %s）", "  Device  %s (torch %s, CUDA %s, bf16 %s)"),
    "probe_tier": ("  档位    %s", "  Tier    %s"),
    "probe_rec": ("  推荐    编码器 %s，模式 %s，micro batch %s × grad accum %s，max_len %s，amp %s",
                  "  Suggest encoder %s, mode %s, micro batch %s x grad accum %s, max_len %s, amp %s"),
    "probe_saved": ("  已保存到 %s（页面上的「训练环境」卡片会读取它，也可以在页面上重新探测）。",
                    "  Saved to %s (the Training environment card on the page reads it; you can re-probe from the page)."),
    "probe_fail": ("  [!] 探测失败（%s）。不影响安装；启动工作台后在「决策训练」页点「重新探测」即可。",
                   "  [!] Probe failed (%s). Installation continues; open the Decision training tab and press Re-probe later."),
    "no_gpu_text": ("无（CPU）", "none (CPU)"),
    "unknown": ("未知", "unknown"),
    "yes": ("是", "yes"),
    "no": ("否", "no"),
    "tier_small": ("small（显存不到 6 GB 或无显卡）", "small (less than 6 GB of GPU memory, or no GPU)"),
    "tier_base": ("base（显存 6–11 GB）", "base (6-11 GB of GPU memory)"),
    "tier_large": ("large（显存 11 GB 以上）", "large (11 GB or more of GPU memory)"),
    "s_weights": ("下载目标检测的预训练权重（可选）", "Download the pretrained weights for object detection (optional)"),
    "weights_have": ("  已有 %s，跳过。", "  %s is already there; skipping."),
    "weights_get": ("  正在下载 %s（约 22 MB）…", "  Downloading %s (about 22 MB)..."),
    "weights_ok": ("  已保存到 %s", "  Saved to %s"),
    "weights_fail": ("  [!] 下载失败（%s）。不影响安装：训练目标检测时会再试一次，下载不到就从头训练。\n"
                     "      也可以手动下载 %s\n"
                     "      放到 %s 后再训练。",
                     "  [!] Download failed (%s). Installation continues: detection training retries the download and\n"
                     "      otherwise trains from scratch. You can also download %s\n"
                     "      by hand into %s before training."),
    "s_vision": ("安装视觉组件（OpenCV）", "Install the vision components (OpenCV)"),
    "vision_have": ("  已安装 OpenCV %s，跳过。", "  OpenCV %s is already installed; skipping."),
    "vision_swap": ("  已安装的 OpenCV %s 不带训练模块，换成 4.x 版本。", "  The installed OpenCV %s has no training module; switching to a 4.x build."),
    "vision_ok": ("  OpenCV %s，训练模块可用。", "  OpenCV %s, training module available."),
    "vision_fail": ("  [!] 视觉组件没有装上，图像检测和训练暂时不可用，其余功能不受影响。\n"
                    "      解决网络问题后重新运行安装脚本即可补装。",
                    "  [!] The vision components could not be installed; image inspection and training are unavailable for now.\n"
                    "      Everything else works. Run the installer again once the network problem is fixed."),
    "vision_skip": ("\n  config.json 里 install_vision 为 false：跳过 OpenCV，不提供图像检测和训练。",
                    "\n  install_vision is false in config.json: skipping OpenCV; image inspection and training will be unavailable."),
    "s_finish": ("收尾", "Finish up"),
    "done": ("  完成。", "  Done."),
    "all_done": ("  安装完成。运行 %s 启动工作台。", "  Installation finished. Run %s to start the workbench."),
    "first_start": ("  首次启动会下载官方模型（约 650 MB），以后启动只需加载模型；\n"
                    "  自己训练的决策模型在「决策训练」页设为默认后，就不再需要官方模型。",
                    "  The first start downloads the official model (about 650 MB); later starts only load it.\n"
                    "  Once a model you trained is set as the default on the Decision training tab, the official one is no longer needed."),
}


def load_config():
    cfg = dict(DEFAULTS)
    path = ROOT / "config.json"
    example = ROOT / "config.example.json"
    if not path.exists() and example.exists() and not DRY_RUN:
        path.write_bytes(example.read_bytes())   # 首次安装：从模板生成 config.json
    if not path.exists() and example.exists():
        path = example
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except ValueError as error:
            print("[!] config.json: %s" % error)
    return cfg


CFG = load_config()
LANG = wb_lang.detect(CFG.get("language"))
# "auto"：中文环境用清华镜像，其他环境用官方源
if str(CFG.get("pip_index") or "").strip().lower() == "auto":
    CFG["pip_index"] = "https://pypi.tuna.tsinghua.edu.cn/simple" if LANG == "zh" else ""


def T(key, *args):
    text = MSG[key][1 if LANG == "en" else 0]
    return text % args if args else text


def step(n, total, key):
    print("\n[%d/%d] %s" % (n, total, T(key)))


def run(cmd, check=True):
    """执行命令并把输出直接显示出来，返回是否成功。"""
    cmd = [str(c) for c in cmd]
    print("  > " + " ".join(cmd))
    if DRY_RUN:
        return True
    code = subprocess.call(cmd, cwd=str(ROOT))
    if code != 0 and check:
        raise SystemExit(T("cmd_failed", code))
    return code == 0


def probe(code, timeout=180):
    """在虚拟环境里跑一小段 Python，返回输出；失败返回 None。"""
    if DRY_RUN or not VENV_PY.exists():
        return None
    try:
        out = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True,
                             timeout=timeout, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def dist_version(name):
    """虚拟环境里某个包的版本；没装返回 None。"""
    return probe("import importlib.metadata as m; print(m.version(%r))" % name)


def pip(*args, check=True):
    cmd = [VENV_PY, "-m", "pip", "install", "--disable-pip-version-check"]
    if CFG.get("pip_index"):
        cmd += ["-i", CFG["pip_index"]]
    return run(cmd + list(args), check=check)


def has_nvidia():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        return subprocess.run([exe], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def torch_state():
    """返回 (版本, cuda 是否可用)；没装返回 (None, False)。"""
    out = probe("import torch; print(torch.__version__); print(int(torch.cuda.is_available()))")
    if not out:
        return None, False
    lines = out.splitlines()
    return lines[0], lines[-1] == "1"


def torch_backend():
    """已安装 torch 的构建：'cu130' / 'cpu' / 'rocm6.4'…（uv 的 --torch-backend 写法）；没装返回 None。

    torchvision 必须和 torch 是同一个构建，否则 pip 会顺手把 GPU 版 torch 换成 CPU 版（Linux）或装不上。
    """
    out = probe("import torch; print(torch.__version__); print(torch.version.cuda or ''); "
                "print(getattr(torch.version, 'hip', None) or '')")
    if not out:
        return None
    lines = (out.splitlines() + ["", ""])[:3]
    version, cuda, hip = lines[0].strip(), lines[1].strip(), lines[2].strip()
    if cuda:
        return "cu" + cuda.replace(".", "")
    if hip:
        return "rocm" + ".".join(hip.split(".")[:2])
    if "+" in version and not version.endswith("+cpu"):
        return version.split("+", 1)[1]        # 例如 2.14.1+xpu
    return "cpu"


def install_torch(nvidia):
    version, cuda = torch_state()
    if version:
        print(T("torch_have", version, T("gpu_yes") if cuda else T("gpu_no")))
        return
    if CFG.get("torch_index"):
        print(T("torch_index"))
        run([VENV_PY, "-m", "pip", "install", "--disable-pip-version-check", "torch",
             "--index-url", CFG["torch_index"]])
        return
    # uv 能按显卡驱动自动挑对应的 PyTorch 版本；没有显卡时装体积小得多的 CPU 版
    backend = "auto" if nvidia else "cpu"
    print(T("torch_gpu") if nvidia else T("torch_cpu"))
    if pip("uv", check=False):
        cmd = [VENV_PY, "-m", "uv", "pip", "install", "--python", VENV_PY, "--torch-backend", backend]
        if CFG.get("pip_index"):
            cmd += ["--default-index", CFG["pip_index"]]
        if run(cmd + ["torch"], check=False):
            return
    print(T("torch_fallback"))
    pip("torch")


def laya_requirement():
    """pip 的 laya 需求串：锁定版本时 laya[serve]==x.y.z，否则最新版。"""
    pin = str(CFG.get("laya_version") or "").strip()
    return "laya[serve]==%s" % pin if pin else "laya[serve]"


def install_laya():
    pin = str(CFG.get("laya_version") or "").strip()
    print(T("laya_pin", pin) if pin else T("laya_latest"))
    if pin:
        pip(laya_requirement())
    else:
        pip("-U", laya_requirement())


def install_torchvision():
    """装和 torch 同一构建的 torchvision。torch 版本用 torch==x.y.z 固定住，免得被顺带升级或换构建。"""
    have = dist_version("torchvision")
    if have:
        print(T("tv_have", have))
        return True
    version, _ = torch_state()
    backend = torch_backend()
    if DRY_RUN and not version:
        version, backend = "<torch>", "auto"
    if not version or not backend:
        return False
    public = version.split("+", 1)[0]
    pin = "torch==%s" % public
    print(T("tv_backend", version, backend))
    if CFG.get("torch_index"):
        return run([VENV_PY, "-m", "pip", "install", "--disable-pip-version-check", "torchvision", pin,
                    "--index-url", CFG["torch_index"]], check=False)
    if backend != "cpu" or not IS_WINDOWS:
        # 和安装 torch 时一样先试 uv（能按构建名选对 wheel），再退回 pip + 官方 PyTorch 索引
        if probe("import uv; print('ok')") or pip("uv", check=False):
            cmd = [VENV_PY, "-m", "uv", "pip", "install", "--python", VENV_PY, "--torch-backend", backend]
            if CFG.get("pip_index"):
                cmd += ["--default-index", CFG["pip_index"]]
            if run(cmd + ["torchvision", pin], check=False):
                return True
        return run([VENV_PY, "-m", "pip", "install", "--disable-pip-version-check", "torchvision", pin,
                    "--index-url", PYTORCH_INDEX + backend], check=False)
    # Windows 上 PyPI 的 torchvision 本身就是 CPU 构建
    return pip("torchvision", pin, check=False)


def install_training():
    ok_tv = install_torchvision()
    if not DRY_RUN and not (ok_tv and dist_version("torchvision")):
        print(T("tv_fail"))
    have = dist_version("peft")
    if have:
        print(T("peft_have", have))
        return
    version, _ = torch_state()
    pin = ["torch==%s" % version.split("+", 1)[0]] if version else []
    ok = pip(*(TRAINING_PACKAGES + pin), check=False)
    if not DRY_RUN and not (ok and dist_version("peft")):
        print(T("peft_fail"))


def run_probe():
    """用虚拟环境跑 app/decision_train.py probe（stdout 每行一个 JSON 事件），返回 result 事件或 (None, 错误)。"""
    cli = APP / "decision_train.py"
    if DRY_RUN or not VENV_PY.exists() or not cli.is_file():
        return None, "dry-run" if DRY_RUN else "missing"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LAYA_WB_LANG", LANG)
    try:
        out = subprocess.run([str(VENV_PY), str(cli), "probe"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300, cwd=str(ROOT), env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    result, error = None, None
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "result":
            result = event
        elif event.get("event") == "error":
            error = event.get("message")
    if result is None:
        return None, error or ("exit %s" % out.returncode) + ((": " + out.stderr.strip()[-300:]) if out.stderr.strip() else "")
    return result, None


def probe_gpu():
    """探测显卡、显存、档位和推荐参数，打印出来并存到 data/decision/gpu.json（页面「训练环境」卡片直接读它）。"""
    if DRY_RUN:
        print(T("dry_skip"))
        return
    result, error = run_probe()
    if result is None:
        print(T("probe_fail", error))
        return
    info = {k: v for k, v in result.items() if k != "event"}
    info["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec = info.get("recommend") or {}
    gpu = info.get("gpu_name") or T("no_gpu_text")
    vram = ("%d MB (%.1f GB)" % (info["vram_mb"], info["vram_mb"] / 1024.0)) if info.get("vram_mb") else "-"
    tier_key = "tier_" + str(info.get("tier") or "small")
    print(T("probe_gpu", gpu))
    print(T("probe_vram", vram))
    print(T("probe_device", info.get("device") or "cpu", info.get("torch") or T("lib_missing"), info.get("cuda") or "-",
            T("yes") if info.get("bf16") else T("no")))
    print(T("probe_tier", T(tier_key) if tier_key in MSG else info.get("tier")))
    if rec:
        print(T("probe_rec", rec.get("encoder"), rec.get("mode"), rec.get("micro_batch"), rec.get("grad_accum"),
                rec.get("max_len"), T("yes") if rec.get("amp") else T("no")))
        note = rec.get("note_en" if LANG == "en" else "note_zh")
        if note:
            print("  " + note)
    for warning in info.get("warnings") or []:
        print("  [!] " + str(warning))
    path = DATA / "decision" / "gpu.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
        print(T("probe_saved", path))
    except OSError as err:
        print("  [!] %s: %s" % (path, err))


def torch_hub_dir():
    home = os.environ.get("TORCH_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "torch")
    return Path(home) / "hub" / "checkpoints"


def url_opener():
    """按 config.json 的 proxy 建 opener；留空则跟随系统代理（urllib 默认行为）。"""
    proxy = str(CFG.get("proxy") or "").strip()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def download(url, dest, timeout=60):
    """下载到临时文件再改名；失败抛异常。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = url_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "%s-installer" % PROJECT})
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=str(dest.parent))
    try:
        with opener.open(request, timeout=timeout) as resp, os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(resp, out, 1024 * 256)
        os.replace(tmp, str(dest))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fetch_detect_weights():
    """把目标检测的预训练骨干权重放进 torch 的缓存目录。没有国内镜像，失败就给出手动放置的提示。"""
    folder = torch_hub_dir()
    dest = folder / DETECT_WEIGHT_FILE
    if dest.is_file() and dest.stat().st_size > 1024 * 1024:
        print(T("weights_have", dest))
        return
    print(T("weights_get", DETECT_WEIGHT_URL))
    if DRY_RUN:
        return
    try:
        download(DETECT_WEIGHT_URL, dest)
        print(T("weights_ok", dest))
    except (OSError, urllib.error.URLError, ValueError) as err:
        print(T("weights_fail", getattr(err, "reason", None) or err, DETECT_WEIGHT_URL, folder))


def vision_state():
    """返回 (OpenCV 版本, 训练模块是否可用)；没装返回 (None, False)。"""
    out = probe("import cv2, numpy; print(cv2.__version__); "
                "print(int(all(hasattr(getattr(cv2, 'ml', None), n) for n in ('SVM_create', 'RTrees_create', 'KNearest_create'))))")
    if not out:
        return None, False
    lines = out.splitlines()
    return lines[0], lines[-1] == "1"


def install_vision():
    version, has_ml = vision_state()
    if version and has_ml:
        print(T("vision_have", version))
        return
    if version:
        print(T("vision_swap", version))
        run([VENV_PY, "-m", "pip", "uninstall", "-y", "opencv-python", "opencv-python-headless"], check=False)
    ok = pip(*VISION_PACKAGES, check=False)
    version, has_ml = vision_state()
    if DRY_RUN:
        return
    if ok and version and has_ml:
        print(T("vision_ok", version))
    else:
        print(T("vision_fail"))


def make_shortcut():
    if not IS_WINDOWS or DRY_RUN or not CFG.get("desktop_shortcut", True):
        return
    name = T("shortcut_name")
    target = str(ROOT / "start.bat").replace("'", "''")
    workdir = str(ROOT).replace("'", "''")
    script = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '%s.lnk'));"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()" % (name, target, workdir)
    )
    # 项目先后叫过 Laya 工作台 / Laya Workbench / laya-opencv。桌面上的旧快捷方式如果指向这个目录，
    # 或者指向的位置已经不存在（文件夹改过名），就删掉，免得留下一个失效的
    cleanup = (
        "$d=[Environment]::GetFolderPath('Desktop');$w=New-Object -ComObject WScript.Shell;"
        "foreach($n in @('Laya 工作台','Laya Workbench','laya-opencv')){$f=Join-Path $d ($n+'.lnk');"
        "if(Test-Path -LiteralPath $f){$t=$w.CreateShortcut($f).TargetPath;"
        "if(($t -eq '%s') -or (($t) -and -not (Test-Path -LiteralPath $t))){Remove-Item -LiteralPath $f}}}" % target
    )
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-Command", script], capture_output=True, timeout=60)
        if done.returncode == 0:
            print(T("shortcut_done", name))
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cleanup],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass


def check_install(nvidia):
    if DRY_RUN:
        print(T("dry_skip"))
        return
    laya_version = probe("import laya; print(laya.__version__)")
    serve_ok = probe("import laya.serve, fastapi, uvicorn; print('ok')")
    version, cuda = torch_state()
    if not laya_version or not serve_ok or not version:
        raise SystemExit(T("check_fail", laya_version, serve_ok, version))
    pin = str(CFG.get("laya_version") or "").strip()
    print(T("lib_line", "laya", laya_version))
    if pin and laya_version != pin:
        print(T("check_pin", laya_version, pin))
    print(T("lib_line", "torch", version))
    if CFG.get("install_training", True):
        print(T("lib_line", "torchvision", dist_version("torchvision") or T("lib_missing")))
        print(T("lib_line", "peft", dist_version("peft") or T("lib_missing")))
    if cuda:
        gpu = probe("import torch; print(torch.cuda.get_device_name(0))")
        print(T("gpu_ok", gpu or "cuda"))
    elif nvidia:
        print(T("gpu_wrong_build", ".venv\\Scripts\\python.exe" if IS_WINDOWS else ".venv/bin/python"))
    else:
        print(T("gpu_none"))


def main():
    local = bool(CFG.get("install_local_laya", True))
    training = local and bool(CFG.get("install_training", True))
    vision = bool(CFG.get("install_vision", True))
    # 虚拟环境 + 收尾，加上：PyTorch、Laya、检查、探测（本地）；训练组件、预训练权重（训练）；OpenCV（视觉）
    total = 2 + (4 if local else 0) + (2 if training else 0) + (1 if vision else 0)
    print("=" * 56)
    print(T("title", PROJECT))
    print(T("dir", ROOT))
    print("=" * 56)
    if sys.version_info < (3, 10):
        raise SystemExit(T("need_py", sys.version.split()[0]))

    n = 1
    step(n, total, "s_venv")
    if VENV_PY.exists():
        print(T("venv_have"))
    else:
        if not run([sys.executable, "-m", "venv", VENV], check=False):
            raise SystemExit(T("venv_fail") + ("" if IS_WINDOWS else T("venv_apt")))
    run([VENV_PY, "-m", "ensurepip", "--upgrade"], check=False)

    if local:
        n += 1
        step(n, total, "s_torch")
        nvidia = has_nvidia()
        install_torch(nvidia)

        n += 1
        step(n, total, "s_laya")
        install_laya()

        if training:
            n += 1
            step(n, total, "s_training")
            install_training()
        else:
            print(T("training_skip"))

        n += 1
        step(n, total, "s_check")
        check_install(nvidia)

        n += 1
        step(n, total, "s_probe")
        probe_gpu()

        if training:
            n += 1
            step(n, total, "s_weights")
            fetch_detect_weights()
    else:
        print(T("remote_only"))

    if vision:
        n += 1
        step(n, total, "s_vision")
        install_vision()
    else:
        print(T("vision_skip"))

    n += 1
    step(n, total, "s_finish")
    make_shortcut()
    print(T("done"))

    print("\n" + "=" * 56)
    print(T("all_done", "start.bat" if IS_WINDOWS else "./start.sh"))
    if local:
        print(T("first_start"))
    print("=" * 56)


if __name__ == "__main__":
    main()
