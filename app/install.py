# -*- coding: utf-8 -*-
"""laya-opencv安装脚本 / laya-opencv installer.

步骤：虚拟环境 → PyTorch → Laya → 检查 → 视觉组件（OpenCV，可选）→ 收尾。

由 install.bat / install.sh 调用，Windows、Linux 通用。可以重复运行，已装好的部分会跳过。
Called by install.bat / install.sh. Safe to re-run: finished steps are skipped.

    python app/install.py            install
    python app/install.py --dry-run  only print the commands
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wb_lang  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
DRY_RUN = "--dry-run" in sys.argv

DEFAULTS = {
    "language": "auto",
    "pip_index": "auto",
    "torch_index": "",
    "install_local_laya": True,
    "install_vision": True,
    "desktop_shortcut": True,
}
# 视觉组件：OpenCV 5 的主包去掉了训练模块（cv2.ml），所以固定用 4.x
VISION_PACKAGES = ["opencv-python-headless>=4.9,<5", "numpy"]

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
    "shortcut_name": ("laya-opencv", "laya-opencv"),
    "shortcut_done": ("  已在桌面创建快捷方式「%s」。", '  Created the desktop shortcut "%s".'),
    "title": ("  laya-opencv 安装程序", "  laya-opencv installer"),
    "dir": ("  安装目录: %s", "  Install folder: %s"),
    "need_py": ("[!] 需要 Python 3.10 或更高版本，当前是 %s。", "[!] Python 3.10 or newer is required; this is %s."),
    "s_venv": ("准备虚拟环境 (.venv)", "Prepare the virtual environment (.venv)"),
    "venv_have": ("  已存在，直接使用。", "  Already there; using it."),
    "venv_fail": ("[!] 创建虚拟环境失败。", "[!] Could not create the virtual environment."),
    "venv_apt": ("\n    Debian / Ubuntu 请先执行: sudo apt install python3-venv", "\n    On Debian / Ubuntu run first: sudo apt install python3-venv"),
    "s_torch": ("安装 PyTorch", "Install PyTorch"),
    "s_laya": ("安装 Laya 和服务端组件", "Install Laya and the server components"),
    "s_check": ("检查安装结果", "Check the installation"),
    "dry_skip": ("  (dry-run，跳过检查)", "  (dry run, check skipped)"),
    "check_fail": ("[!] 检查没有通过：laya=%s，服务端组件=%s，torch=%s", "[!] Check failed: laya=%s, server components=%s, torch=%s"),
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
    "remote_only": ("\n  config.json 里 install_local_laya 为 false：跳过 PyTorch 和 Laya，\n"
                    "  工作台只使用远程接口（TypeSafe / aiask.me）。",
                    "\n  install_local_laya is false in config.json: skipping PyTorch and Laya.\n"
                    "  The workbench will use remote interfaces only (TypeSafe / aiask.me)."),
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
    "first_start": ("  首次启动会下载模型（约 650 MB），以后启动只需加载模型。",
                    "  The first start downloads the model (about 650 MB); later starts only load it."),
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


def probe(code):
    """在虚拟环境里跑一小段 Python，返回输出；失败返回 None。"""
    if DRY_RUN or not VENV_PY.exists():
        return None
    try:
        out = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True,
                             timeout=180, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


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
    # 项目原来叫 Laya 工作台 / Laya Workbench。桌面上的旧快捷方式如果指向这个目录，
    # 或者指向的位置已经不存在（文件夹改过名），就删掉，免得留下一个失效的
    cleanup = (
        "$d=[Environment]::GetFolderPath('Desktop');$w=New-Object -ComObject WScript.Shell;"
        "foreach($n in @('Laya \u5de5\u4f5c\u53f0','Laya Workbench')){$f=Join-Path $d ($n+'.lnk');"
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


def main():
    local = bool(CFG.get("install_local_laya", True))
    vision = bool(CFG.get("install_vision", True))
    total = 2 + (3 if local else 0) + (1 if vision else 0)
    print("=" * 56)
    print(T("title"))
    print(T("dir", ROOT))
    print("=" * 56)
    if sys.version_info < (3, 10):
        raise SystemExit(T("need_py", sys.version.split()[0]))

    step(1, total, "s_venv")
    if VENV_PY.exists():
        print(T("venv_have"))
    else:
        if not run([sys.executable, "-m", "venv", VENV], check=False):
            raise SystemExit(T("venv_fail") + ("" if IS_WINDOWS else T("venv_apt")))
    run([VENV_PY, "-m", "ensurepip", "--upgrade"], check=False)

    if local:
        step(2, total, "s_torch")
        nvidia = has_nvidia()
        install_torch(nvidia)

        step(3, total, "s_laya")
        pip("-U", "laya[serve]")

        step(4, total, "s_check")
        if DRY_RUN:
            print(T("dry_skip"))
        else:
            laya_version = probe("import laya; print(laya.__version__)")
            serve_ok = probe("import laya.serve, fastapi, uvicorn; print('ok')")
            version, cuda = torch_state()
            if not laya_version or not serve_ok or not version:
                raise SystemExit(T("check_fail", laya_version, serve_ok, version))
            print("  laya   %s" % laya_version)
            print("  torch  %s" % version)
            if cuda:
                gpu = probe("import torch; print(torch.cuda.get_device_name(0))")
                print(T("gpu_ok", gpu or "cuda"))
            elif nvidia:
                print(T("gpu_wrong_build", ".venv\\Scripts\\python.exe" if IS_WINDOWS else ".venv/bin/python"))
            else:
                print(T("gpu_none"))
    else:
        print(T("remote_only"))

    if vision:
        step(total - 1, total, "s_vision")
        install_vision()
    else:
        print(T("vision_skip"))

    step(total, total, "s_finish")
    make_shortcut()
    print(T("done"))

    print("\n" + "=" * 56)
    print(T("all_done", "start.bat" if IS_WINDOWS else "./start.sh"))
    if local:
        print(T("first_start"))
    print("=" * 56)


if __name__ == "__main__":
    main()
