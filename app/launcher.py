# -*- coding: utf-8 -*-
"""laya-opencv 启动器（Windows / Linux 通用，只用标准库）。

  1. 按 config.json 启动本地决策模型服务 (app/decision_server.py，没有它时退回 python -m laya.serve)；已经在跑就直接用
  2. 启动视觉服务 (app/vision_server.py，需要 OpenCV)；没装视觉组件时跳过，其余功能照常
  3. 在 ui_port 上提供工作台页面
  4. 检测接口：图像 → OpenCV 测量 → 数值层（硬规则）→ 判定模型 → 交叉核对
  4b. 决策模型训练接口 /v1/decision/*（数据集、模型、训练任务；见 docs/CONTRACT.md §5，实现在 decision_jobs.py）
       训练期间本地模型服务会被暂停（释放显存），训练结束自动恢复
       环境变量 LAYA_WB_DECISION_CLI 可以指定训练脚本的位置（默认 app/decision_train.py）
       环境变量 LAYA_WB_CONFIG 可以指定 config.json 的位置（默认项目根目录）
       POST /v1/inspect            {recipe, image | values, context, inputs, model, min_confidence, use_model, questions, state_level}
                                   recipe 是方案 id 或完整的方案对象；只给 values（测量值）时不需要图，也不需要视觉服务
       POST /v1/inspect/selftest   {recipe, model, limit}   数字判断力自检；GET ?recipe= 取上一次的报告
       POST /v1/inspect/review     {recipe, state, questions, gold}   记一条人工复核
       GET  /v1/inspect/export     ?recipe=   导出 {state, questions, gold} 的 JSONL
       /v1/vision/*                原样转发给视觉服务（见 vision_server.py）
  5. 转发页面发出的 /v1/systemone 请求。页面用请求头 X-WB-Target 指定接口：
       local     本地 Laya
       typesafe  TypeSafe 官方 (https://api.typesafe.ai)
       aiask     aiask.me 网络加速
       auto      按模型名自动选择，远程接口失败时自动换下一个
     远程接口的密钥只保存在本机 config.json，由这里加到请求头上，不经过浏览器。
"""
import copy
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decision_jobs  # noqa: E402
import numeric  # noqa: E402
import wb_lang  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
EXAMPLES = ROOT / "examples"
RECIPES = ROOT / "recipes"
DATA = Path(os.environ.get("LAYA_WB_DATA") or (ROOT / "data"))
CONFIG_FILE = Path(os.environ.get("LAYA_WB_CONFIG") or (ROOT / "config.json"))
PROJECT = "laya-opencv"
VERSION = "3.0"

DEFAULTS = {
    "language": "auto",
    "ui_host": "127.0.0.1",
    "ui_port": 8090,
    "start_local_laya": True,
    "laya_host": "127.0.0.1",
    "laya_port": 8000,
    "models": "multilingual",
    "default_model": "multilingual",
    "device": "auto",
    "preload": True,
    "api_key": "",
    "auto_update": True,
    # 决策模型训练（docs/CONTRACT.md §6）
    "laya_version": "",                 # 锁定的 laya 版本；非空时自动更新只检查、不升级
    "install_training": True,
    "decision_active": "",              # 当前默认的自定义决策模型名；空 = 用官方模型
    "decision_pin_default": True,       # 有自定义默认模型时，未指定 model 的请求都用它
    "decision_builtin": "multilingual", # 决策服务要注册的官方模型，逗号分隔；空 = 不注册官方模型
    "detect_device": "auto",
    "start_vision": True,
    "vision_host": "127.0.0.1",
    "vision_port": 8001,
    "vision_backbone_urls": "auto",
    "pip_index": "auto",
    "hf_endpoint": "auto",
    "open_browser": True,
    "proxy": "",
    "remote_timeout": 120,
    "auto_order": ["aiask", "typesafe"],
    "providers": {
        "typesafe": {"name": "TypeSafe 官方", "name_en": "TypeSafe (official)",
                     "base_url": "https://api.typesafe.ai", "api_key": "", "default_model": "jev-latest"},
        "aiask": {"name": "aiask.me 网络加速", "name_en": "aiask.me (accelerated)",
                  "base_url": "https://aiask.me", "api_key": "", "default_model": "jev-latest"},
    },
}
ENV_KEYS = {"typesafe": "TYPESAFE_API_KEY", "aiask": "AIASK_API_KEY"}
BUILTIN = ("typesafe", "aiask")      # 其余的 providers 都是用户添加的第三方接口

# 本地 Laya 认识的模型名和别名；其余名字（jev-latest 等）在「自动」下走远程接口
LAYA_NAMES = {"english", "multilingual", "typed-decisions", "en", "laya", "default", "multi", "ml",
              "laya-multilingual", "typed", "typed_decisions", "laya-typed-decisions", "decisions"}
# 只有本地 Laya 认识的请求字段，转发到远程接口前去掉
LAYA_ONLY_KEYS = ("max_len", "head_max_len", "task", "lang", "lang_guess", "min_confidence",
                  "batch_size", "sort_by_length")
# 远程接口返回这些状态时，「自动」会换下一个接口再试
RETRY_STATUS = {0, 401, 403, 404, 408, 429, 500, 502, 503, 504}

CONFIG_LOCK = threading.Lock()

# 每条消息: (中文, English)
MSG = {
    "cfg_bad": ("[!] config.json 格式有误，已改用默认配置: %s", "[!] config.json is not valid JSON; using defaults: %s"),
    "need_key": ("还没有填写「%s」的密钥，请先在工作台的「接口设置」里保存。",
                 'No API key is saved for "%s". Add it under Interface settings in the workbench.'),
    "unknown_target": ("未知的接口: %s", "Unknown interface: %s"),
    "no_remote_key": ("模型「%s」不是本地 Laya 的模型，需要走远程接口，但还没有填写任何密钥。"
                      "请在「接口设置」里保存 aiask.me 或 TypeSafe 的密钥。",
                      'Model "%s" is not a local Laya model, so it needs a remote interface, but no API key is saved. '
                      "Add an aiask.me or TypeSafe key under Interface settings."),
    "local_loading": ("本地 Laya 的模型还在加载，加载完成后再试。首次启动要下载模型（约 650 MB），进度在启动窗口里。",
                      "Local Laya is still loading its model; try again when it is ready. "
                      "The first start downloads the model (about 650 MB); progress is in the launcher window."),
    "local_exited": ("本地 Laya 服务已经退出（退出码 %s），报错信息在启动窗口里。",
                     "The local Laya service has exited (exit code %s); the error is in the launcher window."),
    "local_disabled": ("这台机器没有启用本地 Laya（没有安装，或 config.json 里 start_local_laya 为 false）。",
                       "Local Laya is not enabled on this machine (not installed, or start_local_laya is false in config.json)."),
    "local_unreach": ("连不上本地 Laya 服务 (%s)：%s", "Cannot reach the local Laya service (%s): %s"),
    "local_paused": ("模型服务已暂停：正在训练", "The model service is paused while a training job runs"),
    # 决策模型训练
    "dec_training": ("有训练任务正在运行（%s），训练结束后再切换默认模型。", "A training job is running (%s); switch the default model after it finishes."),
    "dec_restarting": ("[..] 默认决策模型改为「%s」，正在重启模型服务…", '[..] Default decision model set to "%s"; restarting the model service…'),
    "dec_pausing": ("[..] 训练任务开始，暂停本地模型服务以释放显存。", "[..] A training job is starting; pausing the local model service to free GPU memory."),
    "dec_resuming": ("[..] 训练任务结束，重新启动本地模型服务。", "[..] The training job finished; restarting the local model service."),
    "dec_models": ("[i] 自定义决策模型 %d 个：%s", "[i] %d custom decision model(s): %s"),
    "dec_pinned": ("[i] config.json 里 laya_version 锁定为 %s：训练脚本依赖 laya 的内部接口，自动更新只检查、不升级。",
                   "[i] laya_version is pinned to %s in config.json: the training scripts depend on laya's internal API, so updates are only checked, never installed."),
    "dec_pin_mismatch": ("[!] 当前安装的 laya 是 %s，config.json 锁定的是 %s。版本不一致时训练脚本可能报错；重新运行安装脚本可以装回锁定的版本。",
                         "[!] laya %s is installed but config.json pins %s. The training scripts may fail on a different version; run the installer again to restore the pinned one."),
    "dec_fallback": ("[i] 没有找到 app/decision_server.py，改用 python -m laya.serve 启动本地模型（自定义决策模型将不可用）。",
                     "[i] app/decision_server.py not found; starting the local model with python -m laya.serve (custom decision models unavailable)."),
    "remote_unreach": ("连不上 %s (%s)：%s", "Cannot reach %s (%s): %s"),
    "states_bad": ("'states' 必须是非空数组", "'states' must be a non-empty list"),
    "states_max": ("一次最多 64 条", "At most 64 items per request"),
    "item_not_json": ("第 %d 条的返回内容不是 JSON", "The response for item %d is not JSON"),
    "no_key_short": ("还没有填写密钥", "no API key saved"),
    "req_failed": ("请求失败", "request failed"),
    "name_required": ("请填写接口名称", "Enter a name for the interface"),
    "builtin_nodelete": ("内置接口不能删除，只能删除它的密钥", "Built-in interfaces cannot be deleted; only their key can be"),
    "key_from_env": ("这个密钥来自环境变量 %s，请在系统里删除它", "This key comes from the environment variable %s; remove it there"),
    "base_url_bad": ("接口地址要以 https:// 或 http:// 开头", "The base URL must start with https:// or http://"),
    "forbidden": ("请求来源不被允许", "Request origin not allowed"),
    "no_page": ("找不到 app/workbench.html", "app/workbench.html not found"),
    "need_json_ct": ("需要 application/json", "application/json required"),
    "bad_json": ("请求内容不是合法的 JSON", "The request body is not valid JSON"),
    "body_obj": ("请求内容必须是 JSON 对象", "The request body must be a JSON object"),
    # 视觉服务和检测
    "vis_missing": ("[i] 当前环境没有安装视觉组件（OpenCV），图像检测和训练不可用。\n"
                    "    重新运行安装脚本（install.bat / install.sh）即可补装。",
                    "[i] The vision components (OpenCV) are not installed; image inspection and training are unavailable.\n"
                    "    Run the installer (install.bat / install.sh) again to add them."),
    "vis_disabled_cfg": ("[i] config.json 里 start_vision 为 false，不启动视觉服务。",
                         "[i] start_vision is false in config.json; not starting the vision service."),
    "vis_starting": ("[..] 正在启动视觉服务 (%s)…", "[..] Starting the vision service (%s)…"),
    "vis_ready": ("[ok] 视觉服务已就绪：OpenCV %s%s", "[ok] The vision service is ready: OpenCV %s%s"),
    "vis_no_ml": ("（这个 OpenCV 不带训练模块，训练功能不可用）", " (this OpenCV build has no training module; training is unavailable)"),
    "vis_external": ("[ok] 检测到 %s 已有视觉服务在运行，直接使用它。", "[ok] A vision service is already running at %s; using it."),
    "vis_exited": ("[!] 视觉服务已退出，退出码 %s。上面的报错信息就是原因；其余功能不受影响。",
                   "[!] The vision service exited with code %s. The error above is the reason; everything else keeps working."),
    "vision_disabled": ("这台机器没有启用视觉组件（没有安装 OpenCV，或 config.json 里 start_vision 为 false）。重新运行安装脚本即可补装。",
                        "The vision components are not enabled on this machine (OpenCV is not installed, or start_vision is false in config.json). Run the installer again to add them."),
    "vision_starting": ("视觉服务还在启动，稍后再试。", "The vision service is still starting; try again in a moment."),
    "vision_exited": ("视觉服务已经退出（退出码 %s），报错信息在启动窗口里。", "The vision service has exited (exit code %s); the error is in the launcher window."),
    "vision_unreach": ("连不上视觉服务 (%s)：%s", "Cannot reach the vision service (%s): %s"),
    "recipe_missing": ("找不到检测方案: %s", "Inspection recipe not found: %s"),
    "recipe_bad": ("检测方案有问题: %s", "The inspection recipe has problems: %s"),
    "recipe_obj": ("'recipe' 要么是方案的 id，要么是一个完整的方案对象", "'recipe' must be a recipe id or a complete recipe object"),
    "recipe_builtin": ("内置方案不能删除", "Built-in recipes cannot be deleted"),
    "need_image": ("请提供图片（image）或测量值（values）", "Provide an image (image) or measurements (values)"),
    "selftest_none": ("这个方案里没有绑定硬规则的题目，没有可以自检的内容。", "This recipe has no question bound to a hard rule, so there is nothing to self-test."),
    "selftest_fail": ("自检时调用判定模型失败: %s", "The decision model call failed during the self-test: %s"),
    # 自动更新
    "upd_checking": ("[..] 正在检查 Laya 更新…", "[..] Checking for Laya updates…"),
    "upd_latest": ("[ok] Laya %s 已是最新版本。", "[ok] Laya %s is the latest version."),
    "upd_found": ("[..] 发现 Laya 新版本 %s（当前 %s），正在自动升级…", "[..] Laya %s is available (installed: %s); upgrading…"),
    "upd_done": ("[ok] 已升级到 Laya %s。", "[ok] Upgraded to Laya %s."),
    "upd_failed": ("[!] 自动升级没有成功，继续使用当前版本 %s。原因见上面 pip 的输出。\n"
                   "    如果提示 torch 版本冲突，说明新版本需要更新 PyTorch，请重新运行安装脚本。",
                   "[!] The automatic upgrade did not succeed; continuing with %s. See pip's output above.\n"
                   "    A torch version conflict means the new version needs a newer PyTorch: run the installer again."),
    "upd_mirror": ("[i] 版本服务器显示有 %s，但当前 pip 源还没有同步到，下次启动再试。",
                   "[i] Version %s is announced, but the configured pip index does not have it yet; will retry next start."),
    "upd_available": ("[i] Laya 有新版本 %s（当前 %s）。config.json 里 auto_update 设成了 \"check\"，所以没有自动升级。",
                      "[i] Laya %s is available (installed: %s). auto_update is \"check\" in config.json, so it was not installed."),
    "upd_offline": ("[i] 连不上版本服务器，跳过更新检查，继续使用 Laya %s。",
                    "[i] Could not reach the version server; skipping the update check and continuing with Laya %s."),
    "upd_skip_bad": ("[i] Laya %s 上次升级后无法启动，已跳过这个版本，继续使用 %s。",
                     "[i] Laya %s failed to start after the last upgrade; skipping it and continuing with %s."),
    "upd_running": ("[i] Laya 有新版本 %s，但服务已经在运行，本次不升级。关闭它之后再启动工作台即可升级。",
                    "[i] Laya %s is available, but the service is already running, so it was not upgraded. Stop it and start the workbench again to upgrade."),
    "upd_rollback": ("\n[!] 升级到 Laya %s 后服务无法启动，正在回退到 %s…", "\n[!] The service failed to start after upgrading to Laya %s; rolling back to %s…"),
    "upd_rolled": ("[ok] 已回退到 Laya %s，重新启动服务。之后会跳过 %s，等更新的版本发布再升级。",
                   "[ok] Rolled back to Laya %s and restarting the service. %s will be skipped until a newer version is released."),
    "mdl_new": ("[i] 模型文件有更新（%s → %s），加载模型时会自动下载新版本。",
                "[i] The model files have been updated (%s -> %s); the new version is downloaded when the model loads."),
    "mdl_same": ("[ok] 模型文件已是最新（%s）。", "[ok] The model files are up to date (%s)."),
    # 启动窗口
    "title": ("  %s %s", "  %s %s"),
    "no_laya": ("[i] 当前环境没有安装 laya，本地模型不可用，只能使用远程接口。\n"
                "    需要本地模型的话，运行安装脚本（install.bat / install.sh）。",
                "[i] laya is not installed in this environment; the local model is unavailable and only remote interfaces work.\n"
                "    Run the installer (install.bat / install.sh) if you want the local model."),
    "starting": ("[..] 正在启动本地 Laya 服务 (%s)，模型: %s\n"
                 "     首次启动会下载模型（multilingual 约 650 MB），请耐心等待。",
                 "[..] Starting the local Laya service (%s), models: %s\n"
                 "     The first start downloads the model (multilingual is about 650 MB); please wait."),
    "all_models": ("全部", "all"),
    "ready": ("\n[ok] 本地 Laya 已就绪，已加载: %s，设备: %s\n", "\n[ok] Local Laya is ready. Loaded: %s, device: %s\n"),
    "ports_busy": ("[!] 工作台端口 %s 起的 10 个端口都被占用: %s", "[!] The 10 ports starting at %s are all in use: %s"),
    "external": ("[ok] 检测到 %s 已有 Laya 服务在运行，直接使用它。", "[ok] A Laya service is already running at %s; using it."),
    "disabled_cfg": ("[i] config.json 里 start_local_laya 为 false，不启动本地模型，只使用远程接口。",
                     "[i] start_local_laya is false in config.json; not starting the local model, remote interfaces only."),
    "remote_line": ("[i] 远程接口 %s  %s  密钥: %s", "[i] Remote interface %s  %s  key: %s"),
    "key_set": ("已设置", "saved"),
    "key_unset": ("未设置", "not set"),
    "ui_addr": ("[ok] 工作台地址: %s", "[ok] Workbench address: %s"),
    "ui_exposed": ("[!] ui_host 设成了 %s：能访问这个端口的人都可以用你保存的密钥发请求，\n"
                   "    请只在可信的内网使用，或者改回 127.0.0.1 并通过 SSH 隧道访问。",
                   "[!] ui_host is %s: anyone who can reach this port can send requests with your saved keys.\n"
                   "    Use this only on a trusted network, or switch back to 127.0.0.1 and use an SSH tunnel."),
    "stop_hint": ("     按 Ctrl+C 或关闭这个窗口即可停止全部服务。\n", "     Press Ctrl+C or close this window to stop everything.\n"),
    "exited": ("\n[!] 本地 Laya 服务已退出，退出码 %s。上面的报错信息就是原因。\n"
               "    常见原因: 端口 %s 被占用、显存不足、模型下载失败。\n"
               "    工作台页面仍然开着，远程接口不受影响。",
               "\n[!] The local Laya service exited with code %s. The error above is the reason.\n"
               "    Common causes: port %s in use, not enough GPU memory, model download failed.\n"
               "    The workbench page stays open and remote interfaces keep working."),
}
REQUEST_LANG = threading.local()


def T(key, *args, **kw):
    """取一条消息。处理网页请求时用页面的语言，其余情况用启动窗口的语言。"""
    lang = kw.get("lang") or getattr(REQUEST_LANG, "value", None) or LANG
    text = MSG[key][1 if lang == "en" else 0]
    return text % args if args else text


def deep_merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def read_raw_config():
    if not CONFIG_FILE.exists():
        example = ROOT / "config.example.json"
        if not example.exists():
            return {}
        # 首次运行：从模板生成 config.json（密钥会保存在这个文件里，它不进版本库）
        CONFIG_FILE.write_bytes(example.read_bytes())
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except ValueError as error:
        print("[!] config.json: %s" % error)
        return {}


RAW = read_raw_config()
CFG = deep_merge(DEFAULTS, RAW)
LANG = wb_lang.detect(CFG.get("language"))
_connect_host = "127.0.0.1" if CFG["laya_host"] in ("0.0.0.0", "::", "") else CFG["laya_host"]
UPSTREAM = "http://%s:%s" % (_connect_host, CFG["laya_port"])
UI_LOOPBACK = str(CFG["ui_host"]) in ("127.0.0.1", "localhost", "::1")

# 本机请求不走代理；远程请求默认跟随系统代理，config.json 的 proxy 可以单独指定
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
if CFG.get("proxy"):
    REMOTE_OPENER = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": CFG["proxy"], "https": CFG["proxy"]}))
else:
    REMOTE_OPENER = urllib.request.build_opener()

SERVICE = {"mode": "starting", "exit_code": None}   # starting / running / external / exited / disabled / paused
CHILD = None
CHILD_LOCK = threading.Lock()
PAUSE = {"by_job": False}        # 当前的「暂停」是不是训练任务触发的（训练结束要恢复）

# 决策模型训练：数据集 / 模型 / 任务都交给 decision_jobs 管理
DJ = decision_jobs.Store(DATA, lang=lambda: cur_lang(), hf_endpoint=lambda: hf_endpoint())


class WBError(Exception):
    def __init__(self, status, detail):
        Exception.__init__(self, detail)
        self.status = status
        self.detail = detail


# ----------------------------------------------------------------- 接口

def provider_key(pid):
    p = CFG["providers"].get(pid) or {}
    return str(p.get("api_key") or os.environ.get(ENV_KEYS.get(pid, ""), "") or "").strip()


def provider_public(pid):
    p = CFG["providers"][pid]
    custom = pid not in BUILTIN
    key_cfg = str(p.get("api_key") or "").strip()
    env_name = ENV_KEYS.get(pid, "")
    key_env = os.environ.get(env_name, "").strip() if env_name else ""
    key = key_cfg or key_env
    return {"id": pid, "name": p.get("name") or pid, "name_en": p.get("name_en") or p.get("name") or pid,
            "base_url": str(p.get("base_url") or "").rstrip("/"),
            "has_key": bool(key), "key_hint": key[-4:] if len(key) >= 8 else "",
            "key_env": env_name if (key_env and not key_cfg) else "",
            "custom": custom,
            "key_optional": custom,          # 第三方接口可以不带密钥（例如内网的另一台 Laya）
            "default_model": str(p.get("default_model") or ("" if custom else "jev-latest"))}


def provider_usable(pid):
    return bool(provider_key(pid)) or provider_public(pid)["key_optional"]


def provider_label(pid):
    p = provider_public(pid)
    lang = getattr(REQUEST_LANG, "value", None) or LANG
    return p["name_en"] if lang == "en" else p["name"]


def custom_models():
    """本项目训练出来的决策模型名（data/decision/models/ 下的目录）。"""
    try:
        return DJ.model_names()
    except Exception:
        return []


def is_laya_model(model):
    name = str(model or "").strip().lower()
    if (not name) or name in LAYA_NAMES or name.startswith("convaiinnovations/"):
        return True
    return name in {m.lower() for m in custom_models()}


def resolve(target, model):
    """返回要依次尝试的接口 id 列表。"""
    target = (target or "local").strip().lower()
    if target == "local":
        return ["local"]
    if target in CFG["providers"]:
        if not provider_usable(target):
            raise WBError(400, T("need_key", provider_label(target)))
        return [target]
    if target != "auto":
        raise WBError(400, T("unknown_target", target))
    if is_laya_model(model):
        return ["local"]
    order = [pid for pid in CFG.get("auto_order") or [] if pid in CFG["providers"]]
    ready = [pid for pid in order if provider_usable(pid)]
    if not ready:
        raise WBError(400, T("no_remote_key", model))
    return ready


def auth_headers():
    return {"Authorization": "Bearer %s" % CFG["api_key"]} if CFG.get("api_key") else {}


def call_local(path, data=None, method="GET", content_type=None, timeout=600):
    headers = auth_headers()
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(UPSTREAM + path, data=data, headers=headers, method=method)
    try:
        with LOCAL_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers
    except Exception as error:
        mode = SERVICE["mode"]
        if mode == "starting":
            detail = T("local_loading")
        elif mode == "exited":
            detail = T("local_exited", SERVICE["exit_code"])
        elif mode == "disabled":
            detail = T("local_disabled")
        elif mode == "paused":
            detail = T("local_paused")
        else:
            detail = T("local_unreach", UPSTREAM, error)
        body = json.dumps({"detail": detail, "service": mode}, ensure_ascii=False)
        return 503, body.encode("utf-8"), {}


def call_remote(pid, path, payload=None, method="GET"):
    """调用远程接口。网络层面失败时状态码返回 0。"""
    p = provider_public(pid)
    headers = {"Accept": "application/json", "User-Agent": "%s/%s" % (PROJECT, VERSION)}
    if provider_key(pid):
        headers["Authorization"] = "Bearer %s" % provider_key(pid)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(p["base_url"] + path, data=data, headers=headers, method=method)
    try:
        with REMOTE_OPENER.open(req, timeout=float(CFG.get("remote_timeout") or 120)) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except Exception as error:
        body = json.dumps({"detail": T("remote_unreach", provider_label(pid), p["base_url"], error)}, ensure_ascii=False)
        return 0, body.encode("utf-8")


def remote_payload(pid, body):
    out = {k: v for k, v in body.items() if k not in LAYA_ONLY_KEYS and not k.startswith("_")}
    if not str(out.get("model") or "").strip():
        out.pop("model", None)
        if provider_public(pid)["default_model"]:
            out["model"] = provider_public(pid)["default_model"]
    return out


def remote_single(candidates, body):
    """按顺序尝试远程接口，返回 (状态码, 响应体, 实际使用的接口, 尝试记录)。"""
    tried = []
    status, raw, used = 0, b"", candidates[0]
    for i, pid in enumerate(candidates):
        status, raw = call_remote(pid, "/v1/systemone", remote_payload(pid, body), "POST")
        tried.append("%s=%s" % (pid, status))
        used = pid
        if 200 <= status < 300:
            break
        if status not in RETRY_STATUS or i == len(candidates) - 1:
            break
    return status, raw, used, tried


def remote_batch(candidates, body):
    """远程接口没有批量端点：逐条调用 /v1/systemone，再拼成批量接口的返回格式。"""
    states = body.get("states")
    if not isinstance(states, list) or not states:
        raise WBError(400, T("states_bad"))
    if len(states) > 64:
        raise WBError(413, T("states_max"))
    base = {k: v for k, v in body.items() if k != "states"}

    lang = getattr(REQUEST_LANG, "value", None)

    def one(state):
        REQUEST_LANG.value = lang      # 线程池里的线程沿用这次请求的语言
        item = dict(base)
        item["state"] = state
        return remote_single(candidates, item)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outs = list(pool.map(one, states))
    results, total_in, total_out = [], 0, 0
    for index, (status, raw, used, tried) in enumerate(outs):
        if not 200 <= status < 300:
            try:
                err = json.loads(raw.decode("utf-8"))
            except ValueError:
                err = {"detail": raw.decode("utf-8", "replace")[:2000]}
            if isinstance(err, dict):
                err["_failed_state_index"] = index
            return status, json.dumps(err, ensure_ascii=False).encode("utf-8"), used, tried
        try:
            item = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise WBError(502, T("item_not_json", index + 1))
        usage = item.get("usage") or {} if isinstance(item, dict) else {}
        total_in += usage.get("input_tokens", 0) or 0
        total_out += usage.get("output_tokens", 0) or 0
        results.append(item)
    merged = {"results": results, "total_usage": {"input_tokens": total_in, "output_tokens": total_out}}
    return 200, json.dumps(merged, ensure_ascii=False).encode("utf-8"), outs[0][2], outs[0][3]


def list_models(target):
    """返回 ({模型名: 接口 id}, {接口 id: 错误说明})。"""
    models, errors = {}, {}
    target = (target or "local").strip().lower()
    pids = []
    if target in ("local", "auto"):
        # 只列决策服务真正注册了的官方模型（config 的 decision_builtin），再加自定义模型
        for name in served_builtins():
            models[name] = "local"
        for name in custom_models():
            models.setdefault(name, "local")
    if target == "auto":
        pids = [pid for pid in CFG.get("auto_order") or [] if pid in CFG["providers"] and provider_usable(pid)]
    elif target in CFG["providers"]:
        pids = [target]
    for pid in pids:
        if not provider_usable(pid):
            errors[pid] = T("no_key_short")
            continue
        status, raw = call_remote(pid, "/v1/models")
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            data = None
        if not 200 <= status < 300:
            detail = ""
            if isinstance(data, dict):
                err = data.get("error")
                detail = data.get("detail") or (err.get("message") if isinstance(err, dict) else err) or data.get("message") or ""
            errors[pid] = ("HTTP %s " % status if status else "") + str(detail or T("req_failed"))
            continue
        items = data
        if isinstance(data, dict):
            items = data.get("data") or data.get("models") or []
        for item in items if isinstance(items, list) else []:
            name = (item.get("id") or item.get("name")) if isinstance(item, dict) else item
            if name:
                models.setdefault(str(name), pid)
    return models, errors


def clean_base_url(value):
    """用户常常会把完整的端点地址贴进来，这里去掉末尾的 /v1/systemone 或 /v1。"""
    url = str(value or "").strip().rstrip("/")
    for tail in ("/v1/systemone/batch", "/v1/systemone", "/v1"):
        if url.lower().endswith(tail):
            url = url[:-len(tail)].rstrip("/")
            break
    if not url.lower().startswith(("https://", "http://")):
        raise WBError(400, T("base_url_bad"))
    return url


def write_config():
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(RAW, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(CONFIG_FILE))


def apply_settings(body):
    """接口的增删改。返回新建接口的 id（其他操作返回 None）。

    action: save（默认，改地址 / 名称 / 默认模型 / 密钥）、delete_key、add（新建第三方接口）、delete（删除第三方接口）
    """
    action = str(body.get("action") or "save")
    pid = str(body.get("provider") or "")
    with CONFIG_LOCK:
        raw_all = RAW.setdefault("providers", {})
        if action == "add":
            name = str(body.get("name") or "").strip()
            if not name:
                raise WBError(400, T("name_required"))
            entry = {"name": name, "base_url": clean_base_url(body.get("base_url")),
                     "api_key": str(body.get("api_key") or "").strip(),
                     "default_model": str(body.get("default_model") or "").strip(), "custom": True}
            n = 1
            while "custom-%d" % n in CFG["providers"]:
                n += 1
            pid = "custom-%d" % n
            raw_all[pid] = dict(entry)
            CFG["providers"][pid] = dict(entry)
            write_config()
            return pid
        if pid not in CFG["providers"]:
            raise WBError(400, T("unknown_target", pid))
        if action == "delete":
            if pid in BUILTIN:
                raise WBError(400, T("builtin_nodelete"))
            raw_all.pop(pid, None)
            CFG["providers"].pop(pid, None)
            write_config()
            return None
        raw_p = raw_all.setdefault(pid, {})
        cfg_p = CFG["providers"][pid]
        if action == "delete_key":
            if not str(cfg_p.get("api_key") or "").strip() and provider_public(pid)["key_env"]:
                raise WBError(400, T("key_from_env", provider_public(pid)["key_env"]))
            raw_p["api_key"] = cfg_p["api_key"] = ""
            write_config()
            return None
        if body.get("base_url") is not None:
            raw_p["base_url"] = cfg_p["base_url"] = clean_base_url(body.get("base_url"))
        if body.get("default_model") is not None:
            raw_p["default_model"] = cfg_p["default_model"] = str(body.get("default_model")).strip()
        if pid not in BUILTIN and body.get("name") is not None:
            name = str(body.get("name")).strip()
            if not name:
                raise WBError(400, T("name_required"))
            raw_p["name"] = cfg_p["name"] = name
            raw_p.pop("name_en", None)
            cfg_p.pop("name_en", None)
        if body.get("api_key") is not None and str(body.get("api_key")).strip():
            raw_p["api_key"] = cfg_p["api_key"] = str(body.get("api_key")).strip()
        write_config()
        return None


# ----------------------------------------------------------------- 自动更新
#
# 每次启动时检查两样东西：
#   1. laya 这个 Python 包：和 PyPI 上的最新版本比较，有新版本就用 pip 升级
#   2. 模型文件：和 Hugging Face 上的最新提交比较。模型文件不用我们动手，
#      Laya 加载模型时会自己下载最新版本，这里只是提前告诉你有没有更新
# 升级后如果服务起不来，会自动退回原来的版本，并记住跳过那个版本。

MODEL_REPO = "convaiinnovations/laya"
STATE_FILE = ROOT / ".update-state.json"
UPDATE = {"mode": "off", "status": "", "installed": None, "latest": None, "previous": None,
          "model_before": None, "model_latest": None, "pinned": ""}


def laya_pin():
    """config.json 里锁定的 laya 版本（训练脚本依赖 laya 的内部接口）；空字符串 = 不锁定。"""
    return str(CFG.get("laya_version") or "").strip()


def update_mode():
    value = CFG.get("auto_update", True)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("check", "notify"):
            mode = "check"
        else:
            mode = "off" if value in ("off", "false", "0", "no", "") else "auto"
    else:
        mode = "auto" if value else "off"
    if mode == "auto" and laya_pin():      # 锁定了版本：只报告有没有新版本，绝不自动升级
        return "check"
    return mode


def pip_index():
    value = str(CFG.get("pip_index") or "").strip()
    if value.lower() == "auto":      # 和安装脚本一致：中文环境用清华镜像
        return "https://pypi.tuna.tsinghua.edu.cn/simple" if LANG == "zh" else ""
    return value


def hf_endpoint():
    if os.environ.get("HF_ENDPOINT"):
        return os.environ["HF_ENDPOINT"].rstrip("/")
    value = str(CFG.get("hf_endpoint") or "").strip()
    if value.lower() == "auto":      # 中文环境用 hf-mirror，其他环境直连 Hugging Face
        value = "https://hf-mirror.com" if LANG == "zh" else ""
    return value.rstrip("/")


def parse_version(text):
    """只认 1.2.3 这样的正式版本号；预发布版本返回 None。"""
    text = str(text or "").strip()
    if not re.match(r"^\d+(\.\d+)*$", text):
        return None
    return tuple(int(part) for part in text.split("."))


def installed_version(name="laya"):
    importlib.invalidate_caches()
    try:
        return importlib.metadata.version(name)
    except Exception:
        return None


def fetch_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "%s/%s" % (PROJECT, VERSION)})
    opener = LOCAL_OPENER if re.match(r"^https?://(127\.0\.0\.1|localhost)[:/]", url) else REMOTE_OPENER
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_version():
    """PyPI 上 laya 的最新正式版本；查不到返回 None。"""
    urls = []
    index = pip_index().rstrip("/")
    if index:
        base = index[:-len("/simple")] if index.endswith("/simple") else index
        urls.append(base + "/pypi/laya/json")
    if "https://pypi.org/pypi/laya/json" not in urls:
        urls.append("https://pypi.org/pypi/laya/json")
    for url in urls:
        try:
            version = fetch_json(url)["info"]["version"]
            if parse_version(version):
                return version
        except Exception:
            continue
    try:      # 镜像不提供 JSON 接口时，退回去问 pip
        cmd = [sys.executable, "-m", "pip", "index", "versions", "laya", "--disable-pip-version-check",
               "--retries", "0", "--timeout", "5"]
        if index:
            cmd += ["-i", index]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
        match = re.search(r"laya \(([^)]+)\)", out)
        if match and parse_version(match.group(1)):
            return match.group(1)
    except Exception:
        pass
    return None


def read_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(data):
    try:
        STATE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def pip_install_laya(spec):
    """安装指定版本的 laya。把 torch 钉在现在的版本上，防止 pip 顺手把 GPU 版换成 CPU 版。"""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec]
    index = pip_index()
    if index:
        cmd += ["-i", index]
    constraint = None
    torch_version = installed_version("torch")
    if torch_version:
        constraint = ROOT / ".update-constraints.txt"
        constraint.write_text("torch==%s\n" % torch_version, encoding="utf-8")
        cmd += ["-c", str(constraint)]
    print("  > " + " ".join(cmd))
    try:
        return subprocess.call(cmd, cwd=str(ROOT)) == 0
    except OSError:
        return False
    finally:
        if constraint is not None:
            try:
                constraint.unlink()
            except OSError:
                pass


def cached_model_sha():
    cache = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub")
    ref = Path(cache) / ("models--" + MODEL_REPO.replace("/", "--")) / "refs" / "main"
    try:
        return ref.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def check_model():
    UPDATE["model_before"] = cached_model_sha()
    try:
        data = fetch_json((hf_endpoint() or "https://huggingface.co") + "/api/models/" + MODEL_REPO + "/revision/main")
        UPDATE["model_latest"] = str(data.get("sha") or "") or None
    except Exception:
        UPDATE["model_latest"] = None
    before, latest = UPDATE["model_before"], UPDATE["model_latest"]
    if before and latest:
        print(T("mdl_new", before[:8], latest[:8]) if before != latest else T("mdl_same", latest[:8]))


def check_update(can_upgrade=True):
    """启动时调用。can_upgrade=False 表示只检查（比如 Laya 服务已经在别处运行）。"""
    UPDATE["mode"] = update_mode()
    UPDATE["installed"] = installed_version()
    UPDATE["pinned"] = laya_pin()
    if UPDATE["pinned"] and UPDATE["installed"]:
        print(T("dec_pinned", UPDATE["pinned"]))
        if UPDATE["installed"] != UPDATE["pinned"]:
            print(T("dec_pin_mismatch", UPDATE["installed"], UPDATE["pinned"]))
    if UPDATE["mode"] == "off" or not UPDATE["installed"]:
        return
    print(T("upd_checking"))
    current = UPDATE["installed"]
    latest = latest_version()
    UPDATE["latest"] = latest
    if not latest:
        UPDATE["status"] = "offline"
        print(T("upd_offline", current))
    elif not parse_version(current) or parse_version(latest) <= parse_version(current):
        UPDATE["status"] = "latest"
        print(T("upd_latest", current))
    elif read_state().get("skip_version") == latest:
        UPDATE["status"] = "skipped"
        print(T("upd_skip_bad", latest, current))
    elif UPDATE["mode"] == "check":
        UPDATE["status"] = "available"
        print(T("upd_available", latest, current))
    elif not can_upgrade:
        UPDATE["status"] = "running"
        print(T("upd_running", latest))
    else:
        print(T("upd_found", latest, current))
        ok = pip_install_laya("laya[serve]==%s" % latest)
        now = installed_version()
        UPDATE["installed"] = now
        if ok and now == latest:
            UPDATE["status"] = "upgraded"
            UPDATE["previous"] = current
            print(T("upd_done", now))
        else:
            UPDATE["status"] = "failed"
            print(T("upd_failed", now or current))
    check_model()


def rollback():
    """升级后服务没能启动：装回原来的版本，并记住跳过这个版本。"""
    bad, previous = UPDATE["installed"], UPDATE["previous"]
    print(T("upd_rollback", bad, previous))
    if not pip_install_laya("laya[serve]==%s" % previous):
        return False
    UPDATE["installed"] = installed_version()
    UPDATE["status"] = "rolled_back"
    UPDATE["latest"] = bad
    state = read_state()
    state["skip_version"] = bad
    write_state(state)
    print(T("upd_rolled", previous, bad))
    return True



# ----------------------------------------------------------------- 视觉服务

_vision_host = "127.0.0.1" if str(CFG["vision_host"]) in ("0.0.0.0", "::", "") else str(CFG["vision_host"])
VISION_UP = "http://%s:%s" % (_vision_host, CFG["vision_port"])
VISION = {"mode": "disabled", "exit_code": None}     # disabled / starting / running / external / exited
VISION_CHILD = None


def cur_lang():
    return getattr(REQUEST_LANG, "value", None) or LANG


def call_vision(path, payload=None, method="GET", raw=None, content_type=None, timeout=900):
    headers, data = {}, None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type or "application/json"
    req = urllib.request.Request(VISION_UP + path, data=data, headers=headers, method=method)
    try:
        with LOCAL_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers
    except Exception as error:
        mode = VISION["mode"]
        if mode == "disabled":
            detail = T("vision_disabled")
        elif mode == "starting":
            detail = T("vision_starting")
        elif mode == "exited":
            detail = T("vision_exited", VISION["exit_code"])
        else:
            detail = T("vision_unreach", VISION_UP, error)
        body = json.dumps({"detail": detail, "service": mode}, ensure_ascii=False)
        return 503, body.encode("utf-8"), {}


def vision_health(timeout=1.5):
    if VISION["mode"] == "disabled":
        return None
    status, raw, _ = call_vision("/v1/vision/health", timeout=timeout)
    if status != 200:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def backbone_urls():
    """预训练骨干网络的下载地址。auto：中文环境先走 hf-mirror，再试官方地址。"""
    value = CFG.get("vision_backbone_urls", "auto")
    if isinstance(value, list):
        return [str(u) for u in value if u]
    if str(value or "").strip().lower() not in ("", "auto"):
        return [u.strip() for u in str(value).split(",") if u.strip()]
    name = "image_classification_mobilenetv2_2022apr.onnx"
    urls = ["https://huggingface.co/opencv/image_classification_mobilenet/resolve/main/" + name,
            "https://github.com/opencv/opencv_zoo/raw/main/models/image_classification_mobilenet/" + name]
    mirror = hf_endpoint()
    if mirror and "huggingface.co" not in mirror:
        urls.insert(0, mirror + "/opencv/image_classification_mobilenet/resolve/main/" + name)
    return urls


def start_vision():
    """启动视觉服务子进程。没装 OpenCV 时不启动，工作台的其余功能不受影响。"""
    global VISION_CHILD
    if not CFG.get("start_vision", True):
        print(T("vis_disabled_cfg"))
        return
    VISION["mode"] = "probe"
    if vision_health():
        VISION["mode"] = "external"
        print(T("vis_external", VISION_UP))
        return
    VISION["mode"] = "disabled"
    if importlib.util.find_spec("cv2") is None or importlib.util.find_spec("numpy") is None:
        print(T("vis_missing"))
        return
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["LAYA_WB_BACKBONE_URLS"] = ",".join(backbone_urls())
    env["LAYA_WB_DATA"] = str(DATA)
    env.setdefault("LAYA_WB_DETECT_DEVICE", str(CFG.get("detect_device") or "auto"))   # 目标检测训练/推理用的设备
    if CFG.get("proxy"):
        env["LAYA_WB_PROXY"] = str(CFG["proxy"])
    VISION_CHILD = subprocess.Popen([sys.executable, str(APP / "vision_server.py"), "--host", str(CFG["vision_host"]),
                                     "--port", str(CFG["vision_port"])], env=env, cwd=str(ROOT))
    VISION["mode"] = "starting"
    print(T("vis_starting", VISION_UP))
    threading.Thread(target=watch_vision, daemon=True).start()


def watch_vision():
    while VISION_CHILD is not None:
        code = VISION_CHILD.poll()
        if code is not None:
            VISION["mode"], VISION["exit_code"] = "exited", code
            print(T("vis_exited", code))
            return
        if VISION["mode"] == "starting":
            health = vision_health(1.5)
            if health:
                VISION["mode"] = "running"
                print(T("vis_ready", health.get("opencv", "?"), "" if health.get("has_ml") else T("vis_no_ml")))
        time.sleep(1 if VISION["mode"] == "starting" else 3)


# ----------------------------------------------------------------- 检测方案

RECIPE_KEYS_FOR_VISION = ("pipeline", "measurements", "calibration", "draw", "max_side")


def clean_recipe(body, fallback_id=""):
    recipe = {k: v for k, v in body.items() if not str(k).startswith("_")}
    recipe["id"] = str(recipe.get("id") or fallback_id)
    return recipe


def read_recipes(lang):
    """recipes/<语言>/ 里的内置方案，加上直接放在 recipes/ 下的自定义方案（两种语言都显示）。"""
    items = []
    for folder, custom in ((RECIPES / ("en" if lang == "en" else "zh"), False), (RECIPES, True)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                body = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(body, dict) or not isinstance(body.get("measurements"), dict):
                continue
            recipe = clean_recipe(body, path.stem)
            items.append({
                "file": path.name, "id": recipe["id"], "custom": custom,
                "title": str(body.get("_title") or recipe["id"]), "note": str(body.get("_note") or ""),
                "recipe": recipe, "problems": numeric.validate(recipe),
                "standards": {rid: numeric.rule_text(recipe, rid, lang) for rid in (recipe.get("rules") or {})},
            })
    return items


def find_recipe(ref, lang):
    if isinstance(ref, dict):
        return clean_recipe(ref, "inline")
    if not isinstance(ref, str) or not ref.strip():
        raise WBError(400, T("recipe_obj"))
    for item in read_recipes(lang):
        if item["id"] == ref.strip() or item["file"] == ref.strip():
            return item["recipe"]
    raise WBError(404, T("recipe_missing", ref))


def save_recipe(body):
    """把页面上改过的方案另存为自定义方案（recipes/my-*.json）。"""
    recipe = body.get("recipe")
    if not isinstance(recipe, dict) or not isinstance(recipe.get("measurements"), dict):
        raise WBError(400, T("recipe_obj"))
    problems = numeric.validate(recipe)
    if problems:
        raise WBError(422, T("recipe_bad", "; ".join(problems[:5])))
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(recipe.get("id") or "recipe").lower()).strip("-") or "recipe"
    if not slug.startswith("my-"):
        slug = "my-" + slug
    out = {"_title": str(body.get("title") or recipe.get("id") or slug), "_note": str(body.get("note") or "")}
    out.update({k: v for k, v in recipe.items() if not str(k).startswith("_")})
    out["id"] = slug
    RECIPES.mkdir(parents=True, exist_ok=True)
    (RECIPES / (slug + ".json")).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return slug


def delete_recipe(body):
    name = os.path.basename(str(body.get("file") or ""))
    path = RECIPES / name
    if not name.endswith(".json") or not path.is_file():
        raise WBError(400, T("recipe_builtin"))
    path.unlink()


# ----------------------------------------------------------------- 检测：图像 → 测量 → 规则 → 判定

def error_detail(data, fallback=""):
    if isinstance(data, dict):
        err = data.get("error")
        detail = data.get("detail") or (err.get("message") if isinstance(err, dict) else err) or data.get("message")
        if detail:
            return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    return fallback or T("req_failed")


def laya_decide(target, body, batch=False):
    """把一份 systemone 请求交给当前接口（本地 Laya 或远程），返回解析好的结果。"""
    started = time.time()
    path = "/v1/systemone/batch" if batch else "/v1/systemone"
    candidates = resolve(target, body.get("model"))
    if candidates == ["local"]:
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        status, raw, _ = call_local(path, raw_body, "POST", "application/json")
        used, tried = "local", []
    else:
        body = {k: v for k, v in body.items() if k != "model" or not is_laya_model(v)}   # 远程接口不认本地模型名
        status, raw, used, tried = (remote_batch if batch else remote_single)(candidates, body)
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        data = {"detail": raw.decode("utf-8", "replace")[:500]}
    ok = 200 <= status < 300 and isinstance(data, dict)
    return {"ok": ok, "status": status, "data": data, "provider": used, "tried": tried, "request": body,
            "ms": round((time.time() - started) * 1000, 1), "error": None if ok else error_detail(data)}


def safe_decide(target, body, batch=False):
    try:
        return laya_decide(target, body, batch)
    except WBError as error:
        return {"ok": False, "status": error.status, "data": {"detail": error.detail}, "provider": None, "tried": [],
                "ms": 0, "error": error.detail}


def inspect(body, target):
    """一张图（或一组现成的测量值）走完整个流程，返回每道题的最终结论。"""
    started = time.time()
    lang = cur_lang()
    recipe = find_recipe(body.get("recipe"), lang)
    if isinstance(body.get("questions"), dict):
        recipe = dict(recipe, questions=body["questions"])
    problems = numeric.validate(recipe)
    if problems:
        raise WBError(422, T("recipe_bad", "; ".join(problems[:5])))

    analysis, values = None, {}
    if body.get("image"):
        payload = {"recipe": {k: recipe[k] for k in RECIPE_KEYS_FOR_VISION if k in recipe}, "image": body["image"],
                   "inputs": body.get("inputs") if isinstance(body.get("inputs"), dict) else {}}
        status, raw, _ = call_vision("/v1/vision/analyze", payload)
        try:
            analysis = json.loads(raw.decode("utf-8"))
        except ValueError:
            analysis = None
        if status != 200 or not isinstance(analysis, dict):
            raise WBError(status if status >= 400 else 502, error_detail(analysis, raw.decode("utf-8", "replace")[:300]))
        values = dict(analysis.get("values") or {})
    elif not isinstance(body.get("values"), dict):
        raise WBError(400, T("need_image"))
    if isinstance(body.get("values"), dict):         # 直接给测量值：不用图，或者覆盖图里量出来的某几项
        values.update(body["values"])
    values = numeric.normalize(recipe, values)       # 四舍五入到规格的小数位：显示的数就是拿来比较的数

    quality = numeric.check_quality(recipe, values, lang)
    level = "raw" if body.get("state_level") == "raw" else "compared"
    context = body.get("context") if body.get("context") not in ("", None, {}) else None
    state = numeric.build_state(recipe, values, lang, level, context, (analysis or {}).get("details"), quality)
    use_model = body.get("use_model", True) is not False
    if not use_model:                                # 只按规则裁决：没绑定规则的题目没有答案，不列出来
        bound = recipe.get("bindings") or {}
        recipe = dict(recipe, questions={q: s for q, s in (recipe.get("questions") or {}).items() if q in bound})
    questions = numeric.bound_questions(recipe, lang)

    min_conf = body.get("min_confidence")
    min_conf = float(min_conf) if numeric.is_number(min_conf) else None
    answers, model_info = None, None
    if use_model and questions:
        request = {"state": state, "questions": questions}
        model = str(body.get("model") or recipe.get("model") or "").strip()
        if model:
            request["model"] = model
        got = safe_decide(target, request)
        model_info = {"ok": got["ok"], "status": got["status"], "provider": got["provider"], "tried": got["tried"],
                      "ms": got["ms"], "error": got["error"], "request": got.get("request") or request, "response": got["data"],
                      "model": got["data"].get("model") if got["ok"] else None}
        if got["ok"] and isinstance(got["data"].get("answers"), dict):
            answers = got["data"]["answers"]
    decision = numeric.decide(recipe, values, answers, lang, min_conf, quality,
                              model_error=bool(model_info and not model_info["ok"]))
    notes = (analysis or {}).get("notes") or []
    details = (analysis or {}).get("details") or {}
    measures = [{"name": name, "label": numeric.label_of(recipe, name), "value": values.get(name),
                 "unit": numeric.unit_of(recipe, name), "text": numeric.describe(recipe, name, values.get(name), lang, level, details.get(name))}
                for name, spec in (recipe.get("measurements") or {}).items()
                if isinstance(spec, dict) and not spec.get("hidden") and not str(name).startswith("_")]
    return {"recipe": recipe.get("id"), "analysis": analysis, "values": values, "measures": measures, "quality": quality, "state": state,
            "questions": questions, "model": model_info, "use_model": use_model,
            "verdicts": decision["verdicts"], "review": decision["review"], "reasons": decision["reasons"],
            "missing_models": sorted(set(n.split(":", 1)[1] for n in notes if n.startswith("model_missing:"))),
            "missing_files": sorted(set(n.split(":", 1)[1] for n in notes if n.startswith("onnx_missing:"))),
            "ms": round((time.time() - started) * 1000, 1)}


SELFTEST_PASS = 0.98      # 带比较结论的素材上，模型和规则的一致率达到这个值，才建议把题目交给模型裁决


def selftest_file(recipe_id):
    return DATA / "selftest" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", str(recipe_id)) + ".json")


def selftest(body, target):
    """数字判断力自检：在每个阈值两侧生成边界用例，看判定模型的答案和硬规则是否一致。

    同一批用例跑两遍：raw（素材里只有数值）和 compared（素材里带着数值层写好的比较结论）。
    两者的差距就是数值层的作用；compared 上仍然不一致的题目，应该保持规则裁决。
    """
    lang = cur_lang()
    recipe = find_recipe(body.get("recipe"), lang)
    cases = numeric.probe_cases(recipe, limit=max(8, min(64, int(body.get("limit") or 48))))
    if not cases:
        raise WBError(422, T("selftest_none"))
    bindings = recipe.get("bindings") or {}
    questions = {q: s for q, s in numeric.bound_questions(recipe, lang).items() if q in cases[0]["gold"] and q in bindings}
    model = str(body.get("model") or recipe.get("model") or "").strip()
    report = {"recipe": recipe.get("id"), "cases": len(cases), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
              "model": model, "provider": None, "threshold": SELFTEST_PASS, "levels": {}, "advice": {}}
    for level in ("raw", "compared"):
        request = {"states": [numeric.build_state(recipe, c["values"], lang, level) for c in cases], "questions": questions}
        if model:
            request["model"] = model
        got = safe_decide(target, request, batch=True)
        if not got["ok"]:
            raise WBError(got["status"] if got["status"] >= 400 else 502, T("selftest_fail", got["error"]))
        results = got["data"].get("results") or []
        report["provider"] = got["provider"]
        report["model"] = (results[0].get("model") if results and isinstance(results[0], dict) else None) or model
        report["levels"][level] = numeric.score_probe(recipe, cases, [r.get("answers") if isinstance(r, dict) else None for r in results])
    for qid in questions:
        row = report["levels"]["compared"].get(qid) or {}
        near = row.get("near_accuracy")
        good = (row.get("accuracy") or 0) >= SELFTEST_PASS and (near is None or near >= SELFTEST_PASS - 0.03)
        report["advice"][qid] = "advise" if good else "enforce"
    try:
        path = selftest_file(recipe.get("id"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return report


def read_selftest(recipe_id):
    try:
        data = json.loads(selftest_file(recipe_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


REVIEW_LOCK = threading.Lock()


def save_review(body):
    """记下一次人工复核的结论（正确答案），以后可以导出成微调数据。"""
    gold = body.get("gold")
    if not isinstance(gold, dict) or not gold or not isinstance(body.get("questions"), dict) or body.get("state") is None:
        raise WBError(400, T("body_obj"))
    record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "recipe": str(body.get("recipe") or ""), "state": body["state"],
              "questions": {q: body["questions"][q] for q in gold if q in body["questions"]}, "gold": gold,
              "note": str(body.get("note") or "")}
    with REVIEW_LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(str(DATA / "reviews.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return count_reviews(record["recipe"])


def read_reviews(recipe_id=None):
    out = []
    try:
        with open(str(DATA / "reviews.jsonl"), encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict) and (not recipe_id or item.get("recipe") == recipe_id):
                    out.append(item)
    except OSError:
        pass
    return out


def count_reviews(recipe_id):
    return len(read_reviews(recipe_id))


def export_finetune(recipe_ref, lang):
    """导出 {state, questions, gold} 格式的 JSONL：自检的边界用例（答案来自规则）加上人工复核记录。"""
    recipe = find_recipe(recipe_ref, lang)
    records = numeric.finetune_records(recipe, numeric.probe_cases(recipe, limit=64), lang, "compared")
    for item in read_reviews(recipe.get("id")):
        records.append({"state": item["state"], "questions": item["questions"], "gold": item["gold"]})
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


# ----------------------------------------------------------------- 本地服务

def upstream_health(timeout=2.0):
    status, raw, _ = call_local("/health", timeout=timeout)
    if status != 200:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def status_payload():
    health = upstream_health(1.5)
    return {
        "version": VERSION,
        "language": LANG,
        "ready": bool(health),
        "health": health,
        "service": SERVICE["mode"],
        "exit_code": SERVICE["exit_code"],
        "laya_url": UPSTREAM,
        "auth": bool(CFG.get("api_key")),
        "models": CFG["models"],
        "default_model": CFG["default_model"],
        "update": dict(UPDATE),
        "vision": {"mode": VISION["mode"], "exit_code": VISION["exit_code"], "url": VISION_UP,
                   "health": vision_health(1.0) if VISION["mode"] in ("starting", "running", "external") else None},
        "providers": [provider_public(pid) for pid in sorted(CFG["providers"], key=lambda x: (BUILTIN.index(x) if x in BUILTIN else len(BUILTIN), len(x), x))],
        "auto_order": [pid for pid in CFG.get("auto_order") or [] if pid in CFG["providers"]],
        "decision": decision_status(),
    }


def decision_models():
    """模型列表，补上「是否当前默认」和「服务里是否已加载」。"""
    items = DJ.list_models()
    active = str(CFG.get("decision_active") or "").strip()
    health = upstream_health(1.0) if SERVICE["mode"] in ("running", "external") else None
    loaded = set((health or {}).get("loaded") or [])
    for item in items:
        item["active"] = item["name"] == active
        item["loaded"] = item["name"] in loaded
    return items


def decision_status():
    """/_wb/status 里的 decision 块（docs/CONTRACT.md §5）。"""
    running = DJ.running_job()
    active = str(CFG.get("decision_active") or "").strip()
    return {"active": active or None, "custom_models": custom_models(), "training": running["id"] if running else None,
            "training_kind": running["kind"] if running else None, "paused": SERVICE["mode"] == "paused",
            "available": DJ.cli_ready() and DJ.installed().get("torch", False), "builtin": CFG.get("decision_builtin"),
            "pin_default": bool(CFG.get("decision_pin_default", True))}


def read_examples(lang):
    """examples/<语言>/ 里的示例，加上直接放在 examples/ 下的自定义示例（两种语言都显示）。"""
    items = []
    folders = [EXAMPLES / ("en" if lang == "en" else "zh"), EXAMPLES]
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                body = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(body, dict) or "questions" not in body:
                continue
            items.append({
                "file": path.name,
                "title": str(body.get("_title") or path.stem),
                "note": str(body.get("_note") or ""),
                "request": {k: v for k, v in body.items() if not k.startswith("_")},
            })
    return items


# ----------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # 页面轮询很频繁，不刷屏
        pass

    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj, extra=None):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    def _trusted(self):
        """挡掉别的网页对本机工作台发起的请求（跨站请求、DNS 重绑定）。"""
        host = (self.headers.get("Host") or "").strip().lower()
        if UI_LOOPBACK and host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost", "[::1]"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in ("http://" + host, "https://" + host):
            return False
        return True

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def _set_lang(self):
        value = (self.headers.get("X-WB-Lang") or "").strip().lower()
        REQUEST_LANG.value = value if value in ("zh", "en") else None

    def do_GET(self):
        self._set_lang()
        if not self._trusted():
            return self._json(403, {"detail": T("forbidden")})
        parsed = urllib.parse.urlsplit(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            try:
                page = (APP / "workbench.html").read_bytes()
            except OSError:
                return self._json(500, {"detail": T("no_page")})
            return self._send(200, page, "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/_wb/status":
            return self._json(200, status_payload())
        if path == "/_wb/examples":
            return self._json(200, read_examples((query.get("lang") or [LANG])[0]))
        if path == "/_wb/vision.js":
            try:
                return self._send(200, (APP / "vision.js").read_bytes(), "application/javascript; charset=utf-8")
            except OSError:
                return self._json(404, {"detail": "app/vision.js not found"})
        if path == "/_wb/recipes":
            return self._json(200, read_recipes((query.get("lang") or [cur_lang()])[0]))
        if path == "/_wb/decision.js":
            try:
                return self._send(200, (APP / "decision.js").read_bytes(), "application/javascript; charset=utf-8")
            except OSError:
                return self._json(404, {"detail": "app/decision.js not found"})
        if path.startswith("/v1/decision/"):
            try:
                return self._decision_get(path, query)
            except (WBError, decision_jobs.DJError) as error:
                return self._json(error.status, {"detail": error.detail})
        if path.startswith("/v1/vision/"):
            status, body, got = call_vision(self.path)
            extra = {name: got[name] for name in ("X-Variant", "X-Seed", "X-Objects") if got.get(name)}
            return self._send(status, body, got.get("Content-Type") or "application/json", extra)
        try:
            if path == "/v1/inspect/selftest":
                return self._json(200, read_selftest((query.get("recipe") or [""])[0]))
            if path == "/v1/inspect/export":
                text = export_finetune((query.get("recipe") or [""])[0], cur_lang())
                name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (query.get("recipe") or ["recipe"])[0])
                return self._send(200, text.encode("utf-8"), "application/x-ndjson; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="laya-finetune-%s.jsonl"' % name})
        except WBError as error:
            return self._json(error.status, {"detail": error.detail})
        if path == "/_wb/models":
            models, errors = list_models((query.get("target") or ["local"])[0])
            return self._json(200, {"models": [{"id": k, "provider": v} for k, v in models.items()],
                                    "errors": errors})
        status, body, got = call_local(self.path)
        self._send(status, body, got.get("Content-Type") or "application/json")

    def do_POST(self):
        self._set_lang()
        data = self._body()
        if not self._trusted():
            return self._json(403, {"detail": T("forbidden")})
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/_wb/settings":
                return self._settings(data)
            if path in ("/v1/systemone", "/v1/systemone/batch"):
                return self._systemone(path, data)
            if path.startswith("/v1/vision/"):
                status, body, got = call_vision(self.path, raw=data, method="POST", content_type=self.headers.get("Content-Type"))
                return self._send(status, body, got.get("Content-Type") or "application/json")
            if path.startswith("/v1/decision/"):
                return self._decision_post(path, self._json_body(data))
            if path in ("/v1/inspect", "/v1/inspect/selftest", "/v1/inspect/review", "/_wb/recipes/save", "/_wb/recipes/delete"):
                body = self._json_body(data)
                target = (self.headers.get("X-WB-Target") or body.get("target") or "auto").strip().lower()
                if path == "/v1/inspect":
                    return self._json(200, inspect(body, target))
                if path == "/v1/inspect/selftest":
                    return self._json(200, selftest(body, target))
                if path == "/v1/inspect/review":
                    return self._json(200, {"reviews": save_review(body)})
                if path == "/_wb/recipes/save":
                    return self._json(200, {"id": save_recipe(body), "recipes": read_recipes(cur_lang())})
                delete_recipe(body)
                return self._json(200, {"recipes": read_recipes(cur_lang())})
        except (WBError, decision_jobs.DJError) as error:
            return self._json(error.status, {"detail": error.detail})
        status, body, got = call_local(self.path, data, "POST", self.headers.get("Content-Type"))
        self._send(status, body, got.get("Content-Type") or "application/json")

    def _decision_get(self, path, query):
        """GET /v1/decision/*（docs/CONTRACT.md §5）。"""
        q = lambda key, default="": (query.get(key) or [default])[0]
        if path == "/v1/decision/env":
            return self._json(200, DJ.env(refresh=q("refresh") in ("1", "true", "yes")))
        if path == "/v1/decision/datasets":
            return self._json(200, DJ.list_datasets())
        if path == "/v1/decision/datasets/rows":
            return self._json(200, DJ.rows(q("name"), q("offset", "0"), q("limit", "20")))
        if path == "/v1/decision/datasets/export":
            name = DJ.check_name(q("name"))
            text = DJ.export_text(name)
            return self._send(200, text.encode("utf-8"), "application/x-ndjson; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="%s.jsonl"' % urllib.parse.quote(name)})
        if path == "/v1/decision/jobs":
            if q("id"):
                return self._json(200, DJ.get_job(q("id")))
            return self._json(200, DJ.list_jobs())
        if path == "/v1/decision/models":
            return self._json(200, decision_models())
        if path == "/v1/decision/models/info":
            return self._json(200, DJ.model_info(q("name")))
        raise WBError(404, "unknown path %s" % path)

    def _decision_post(self, path, body):
        """POST /v1/decision/*。"""
        if path == "/v1/decision/datasets/create":
            return self._json(200, DJ.create_dataset(body.get("name"), body.get("title"), body.get("note")))
        if path == "/v1/decision/datasets/append":
            return self._json(200, DJ.append_rows(body.get("name"), body.get("rows")))
        if path == "/v1/decision/datasets/import":
            return self._json(200, DJ.import_text(body.get("name"), body.get("format"), body.get("text"), body.get("csv")))
        if path == "/v1/decision/datasets/from_reviews":
            text = export_finetune(body.get("recipe"), cur_lang())
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
            return self._json(200, DJ.import_rows(body.get("name"), records))
        if path == "/v1/decision/datasets/delete":
            return self._json(200, DJ.delete(body.get("name"), body.get("index")))
        if path == "/v1/decision/new":
            return self._json(200, DJ.start_new(body))
        if path == "/v1/decision/train":
            return self._json(200, DJ.start_train(body))
        if path == "/v1/decision/evaluate":
            return self._json(200, DJ.start_evaluate(body))
        if path == "/v1/decision/jobs/cancel":
            return self._json(200, DJ.cancel(body.get("id")))
        if path == "/v1/decision/models/delete":
            return self._json(200, DJ.delete_model(body.get("name")))
        if path == "/v1/decision/models/activate":
            return self._json(200, activate_model(body.get("name")))
        raise WBError(404, "unknown path %s" % path)

    def _json_body(self, data):
        if "application/json" not in (self.headers.get("Content-Type") or "").lower():
            raise WBError(415, T("need_json_ct"))
        try:
            body = json.loads(data.decode("utf-8"))
        except ValueError:
            raise WBError(400, T("bad_json"))
        if not isinstance(body, dict):
            raise WBError(400, T("body_obj"))
        return body

    def _settings(self, data):
        body = self._json_body(data)
        created = apply_settings(body)
        payload = status_payload()
        if created:
            payload["created"] = created
        self._json(200, payload)

    def _systemone(self, path, data):
        target = (self.headers.get("X-WB-Target") or "local").strip().lower()
        try:
            body = json.loads(data.decode("utf-8")) if data else None
        except ValueError:
            body = None
        model = body.get("model") if isinstance(body, dict) else None
        candidates = resolve(target, model)
        if candidates == ["local"]:
            status, raw, got = call_local(path, data, "POST", self.headers.get("Content-Type") or "application/json")
            extra = {"X-WB-Provider": "local"}
            for name in ("X-Inference-Time-Ms", "Retry-After"):
                if got.get(name):
                    extra[name] = got[name]
            return self._send(status, raw, got.get("Content-Type") or "application/json", extra)
        if not isinstance(body, dict):
            raise WBError(400, T("body_obj"))
        if path.endswith("/batch"):
            status, raw, used, tried = remote_batch(candidates, body)
        else:
            status, raw, used, tried = remote_single(candidates, body)
        self._send(status or 502, raw, "application/json; charset=utf-8",
                   {"X-WB-Provider": used, "X-WB-Tried": ",".join(tried)})


def served_builtins():
    """决策服务注册的官方模型名列表（config 的 decision_builtin；老配置退回 models）。"""
    builtin = CFG["decision_builtin"] if "decision_builtin" in RAW else CFG.get("models", "multilingual")
    names = [x.strip() for x in str(builtin or "").split(",") if x.strip()]
    if not names and not custom_models():
        names = ["multilingual"]
    return names


def decision_server_args():
    """app/decision_server.py 的命令行（docs/CONTRACT.md §3）。"""
    builtin = ",".join(served_builtins())
    customs = custom_models()
    active = str(CFG.get("decision_active") or "").strip()
    if active and active not in customs:
        active = ""
    default = active or (builtin.split(",")[0] if builtin else (customs[0] if customs else "multilingual"))
    if not builtin and not customs:
        builtin = "multilingual"
    args = [sys.executable, str(APP / "decision_server.py"), "--host", str(CFG["laya_host"]), "--port", str(CFG["laya_port"]),
            "--device", str(CFG.get("device") or "auto"), "--builtin", builtin, "--default", default]
    for name in customs:
        args += ["--custom", "%s=%s" % (name, DJ.models_dir / name)]
    if active and CFG.get("decision_pin_default", True):
        args.append("--pin-default")
    if CFG.get("preload", True):
        args += ["--preload", default]
    if CFG.get("api_key"):
        args += ["--api-key", str(CFG["api_key"])]
    return args, default


def start_laya():
    """启动本地决策模型服务子进程（app/decision_server.py；没有它就退回 python -m laya.serve），日志直接打在当前窗口。"""
    global CHILD
    if importlib.util.find_spec("laya") is None:
        print(T("no_laya"))
        SERVICE["mode"] = "disabled"
        return
    env = dict(os.environ)
    env["LAYA_HOST"] = str(CFG["laya_host"])
    env["LAYA_PORT"] = str(CFG["laya_port"])
    env["LAYA_PRELOAD"] = "1" if CFG.get("preload", True) else "0"
    env["LAYA_MODELS"] = str(CFG.get("models") or "")
    if CFG.get("default_model"):
        env["LAYA_DEFAULT_MODEL"] = str(CFG["default_model"])
    if str(CFG.get("device") or "auto").lower() != "auto":
        env["LAYA_DEVICE"] = str(CFG["device"])
    if CFG.get("api_key"):
        env["LAYA_API_KEY"] = str(CFG["api_key"])
    if hf_endpoint() and not env.get("HF_ENDPOINT"):
        env["HF_ENDPOINT"] = hf_endpoint()
    env["PYTHONUNBUFFERED"] = "1"
    env["LAYA_WB_DATA"] = str(DATA)
    if (APP / "decision_server.py").is_file():
        cmd, shown = decision_server_args()
        customs = custom_models()
        if customs:
            print(T("dec_models", len(customs), ", ".join(customs)))
    else:
        print(T("dec_fallback"))
        cmd, shown = [sys.executable, "-m", "laya.serve"], CFG.get("models") or T("all_models")
    with CHILD_LOCK:
        SERVICE["mode"] = "starting"
        SERVICE["exit_code"] = None
        CHILD = subprocess.Popen(cmd, env=env, cwd=str(ROOT))
    print(T("starting", UPSTREAM, shown))


def service_ours():
    return CHILD is not None and CHILD.poll() is None and SERVICE["mode"] in ("starting", "running")


def stop_child(timeout=20):
    """结束我们自己拉起的模型服务子进程；等它退出。"""
    global CHILD
    with CHILD_LOCK:
        child = CHILD
        CHILD = None
    if child is None or child.poll() is not None:
        return
    try:
        child.terminate()
    except OSError:
        return
    try:
        child.wait(timeout)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
        except OSError:
            pass


def needs_pause():
    """训练前要不要暂停模型服务：只有模型服务占着显卡时才需要。设备不明时按需要暂停处理。"""
    if str(CFG.get("device") or "auto").lower() == "cpu":
        return False
    device = DJ.cached_device()
    return device != "cpu"


def pause_service(force=False):
    """训练开始：结束本启动器拉起的模型服务，释放显存；SERVICE.mode 置为 paused。返回是否真的暂停了。"""
    if not service_ours() or not (force or needs_pause()):
        return False
    print(T("dec_pausing"))
    SERVICE["mode"] = "paused"
    stop_child()
    return True


def resume_service():
    """训练结束：重新拉起被暂停的模型服务。"""
    if SERVICE["mode"] != "paused":
        return False
    print(T("dec_resuming"))
    start_laya()
    return True


def restart_service():
    """切换默认模型：重启本启动器拉起的模型服务（外部服务 / 未启用时什么都不做）。"""
    if not service_ours() and SERVICE["mode"] not in ("exited", "paused"):
        return False
    if SERVICE["mode"] in ("starting", "running"):
        SERVICE["mode"] = "paused"
        stop_child()
    start_laya()
    return SERVICE["mode"] == "starting"


def before_job(kind):
    if kind in decision_jobs.JOB_KINDS:
        PAUSE["by_job"] = pause_service()


def after_job(kind):
    if PAUSE["by_job"]:
        PAUSE["by_job"] = False
        resume_service()


DJ.before_start = before_job
DJ.after_finish = after_job


def supervise():
    """盯着当前的模型服务子进程：就绪了改 running，退出了改 exited。子进程换了（暂停 / 重启）就接着盯新的。"""
    handled = None
    rolled_back = False
    while True:
        child = CHILD
        if child is None or child is handled:
            time.sleep(1)
            continue
        code = child.poll()
        if code is None:
            if SERVICE["mode"] == "starting" and upstream_health(1.5):
                SERVICE["mode"] = "running"
                health = upstream_health(1.5) or {}
                print(T("ready", ", ".join(health.get("loaded") or []) or "-", health.get("device", "-")))
            time.sleep(2 if SERVICE["mode"] == "starting" else 3)
            continue
        handled = child
        if SERVICE["mode"] == "paused" or child is not CHILD:
            continue                                   # 是我们自己结束的（暂停 / 重启），不算退出
        # 刚升级完就起不来：退回原来的版本再启动一次
        if code != 0 and SERVICE["mode"] == "starting" and UPDATE["status"] == "upgraded" and not rolled_back and rollback():
            rolled_back = True
            start_laya()
            continue
        SERVICE["mode"] = "exited"
        SERVICE["exit_code"] = code
        print(T("exited", code, CFG["laya_port"]))


def activate_model(name):
    """把自定义模型设为默认（写 config.json 的 decision_active）并重启模型服务。"""
    name = str(name or "").strip()
    if name:
        DJ.model_info(name)                            # 不存在就 404
    running = DJ.running_job()
    if running:
        raise WBError(409, T("dec_training", running["id"]))
    with CONFIG_LOCK:
        RAW["decision_active"] = name
        CFG["decision_active"] = name
        write_config()
    print(T("dec_restarting", name or (CFG.get("decision_builtin") or "multilingual")))
    restarted = restart_service()
    return {"active": name or None, "restarted": restarted, "service": SERVICE["mode"]}


def make_server():
    last_error = None
    for port in range(int(CFG["ui_port"]), int(CFG["ui_port"]) + 10):
        try:
            return ThreadingHTTPServer((str(CFG["ui_host"]), port), Handler), port
        except OSError as error:
            last_error = error
    raise SystemExit(T("ports_busy", CFG["ui_port"], last_error))


def can_open_browser():
    if not CFG.get("open_browser", True):
        return False
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return True


def main():
    print("=" * 56)
    print(T("title", PROJECT, VERSION))
    print("=" * 56)

    if upstream_health():
        SERVICE["mode"] = "external"
        print(T("external", UPSTREAM))
        check_update(can_upgrade=False)
    elif not CFG.get("start_local_laya", True):
        SERVICE["mode"] = "disabled"
        print(T("disabled_cfg"))
    else:
        check_update()
        start_laya()
    threading.Thread(target=supervise, daemon=True).start()

    start_vision()

    for pid in CFG["providers"]:
        p = provider_public(pid)
        print(T("remote_line", provider_label(pid), p["base_url"], T("key_set") if p["has_key"] else T("key_unset")))

    server, port = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % port
    print(T("ui_addr", url))
    if not UI_LOOPBACK:
        print(T("ui_exposed", CFG["ui_host"]))
    print(T("stop_hint"))
    if can_open_browser():
        threading.Timer(1.0, webbrowser.open, [url]).start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        running = DJ.running_job()
        if running:
            try:
                DJ.cancel(running["id"])
            except Exception:
                pass
        for child in (CHILD, VISION_CHILD):
            if child is not None and child.poll() is None:
                child.terminate()
        server.shutdown()


if __name__ == "__main__":
    main()
