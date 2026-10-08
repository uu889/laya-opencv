# -*- coding: utf-8 -*-
"""决策模型服务端：替代 `python -m laya.serve`，能同时提供官方 Laya 权重和本项目自己训练的模型。

  python app/decision_server.py --host 127.0.0.1 --port 8000 --device auto
         [--builtin multilingual,english]   要注册的官方模型（可为空：纯自训模式，绝不会去下载官方权重）
         [--custom name=/abs/path ...]      本项目训练的模型（Laya 格式 checkpoint 目录），可多个
         [--default <name>]                 默认模型（不给则取第一个 custom，再取第一个 builtin）
         [--pin-default]                    没有显式指定 model 的请求一律用默认模型（关掉按语言路由）
         [--preload name,name]              启动时就加载的模型（默认：默认模型）
         [--max-loaded 1] [--api-key KEY]

和原生 laya.serve 的差别：
  1. HTTP 请求的 `model` 字段可以写自定义模型名。原生 `laya.serve._resolve_model` 只认官方名字，这里在本进程里
     把它替换成「Router 上注册过的名字直接通过」的版本（`_systemone_inner` 是按模块全局名查找它的，替换有效）。
  2. `--pin-default`：on_route 钩子把非显式指定的路由决策改成默认模型（见 docs/verify/serve_custom.py）。
  3. 没有在 --builtin 里的官方名字永远不会被路由到（钩子兜底），所以 `--builtin ""` 时不会触发任何下载。
  4. 新增 GET /v1/models：{"data":[{"id","custom","loaded","source","default"}]}。/health 原样。

环境变量 HF_ENDPOINT 原样透传给 Laya 的下载；LAYA_WB_LANG=zh|en 决定启动日志语言。
"""
import argparse
import json
import os
import sys

# 每条消息: (中文, English)
MSG = {
    "need_libs": ("缺少依赖 %s，请运行安装脚本补装训练/服务组件。", "Missing %s; run the installer to add the serving components."),
    "custom_bad": ("--custom 的格式是 name=/path/to/checkpoint，收到：%s", "--custom takes name=/path/to/checkpoint, got: %s"),
    "custom_missing": ("自定义模型 %s 的目录里没有 rl_agent_config.json：%s", "Custom model %s has no rl_agent_config.json in %s"),
    "builtin_bad": ("未知的官方模型名 %s（可选 multilingual / english / typed-decisions）", "Unknown built-in model %s (choose multilingual / english / typed-decisions)"),
    "no_models": ("没有任何模型可以服务：请用 --custom 或 --builtin 至少给一个。", "Nothing to serve: give at least one model with --custom or --builtin."),
    "default_bad": ("默认模型 %s 不在已注册的模型里：%s", "Default model %s is not among the registered models: %s"),
    "preload_bad": ("--preload 里的 %s 没有注册。", "%s in --preload is not registered."),
    "starting": ("[..] 决策服务 %s:%s  官方: %s  自定义: %s  默认: %s%s", "[..] Decision service %s:%s  built-in: %s  custom: %s  default: %s%s"),
    "pinned": ("（所有未指定 model 的请求都用默认模型）", " (every request without model= uses the default)"),
    "preloading": ("[..] 正在加载模型 %s…", "[..] Loading %s..."),
    "ready": ("[ok] 已加载: %s", "[ok] Loaded: %s"),
    "none": ("（无）", "(none)"),
}
LANG = (os.environ.get("LAYA_WB_LANG") or "zh").lower()


def T(key, *args):
    text = MSG[key][1 if LANG == "en" else 0]
    return text % args if args else text


def say(text):
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def parse_custom(values):
    """['name=/path', ...] → {name: abspath}。"""
    out = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(T("custom_bad", item))
        name, path = item.split("=", 1)
        name, path = name.strip(), os.path.abspath(os.path.expanduser(path.strip()))
        if not name or not path:
            raise SystemExit(T("custom_bad", item))
        if not os.path.exists(os.path.join(path, "rl_agent_config.json")):
            raise SystemExit(T("custom_missing", name, path))
        out[name.lower()] = path
    return out


def parse_list(text):
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def build_parser():
    p = argparse.ArgumentParser(prog="decision_server.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--device", default="auto")
    p.add_argument("--builtin", default="", help="逗号分隔的官方模型名，可为空")
    p.add_argument("--custom", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--default", default=None)
    p.add_argument("--pin-default", action="store_true")
    p.add_argument("--preload", default=None, help="逗号分隔；默认只加载默认模型；'none' 表示都不预加载")
    p.add_argument("--max-loaded", type=int, default=1)
    p.add_argument("--api-key", default=None)
    p.add_argument("--log-level", default="warning")
    return p


class PinHook:
    """on_route 钩子：
    - 路由到了没有注册 / 没有允许的名字（例如 --builtin 为空时按语言路由到 multilingual）→ 改成默认模型；
    - --pin-default 时，只要不是显式 model= 指定的决策 → 改成默认模型。"""

    def __init__(self, default, repo, allowed, pin_default):
        self.default, self.repo, self.allowed, self.pin_default = default, repo, set(allowed), pin_default

    def on_route(self, ctx):
        from laya.router import RouteDecision
        decision = ctx.decision
        model, reason = decision["model"], decision.get("reason") or ""
        explicit = reason.startswith("explicit model=")
        if model == self.default:
            return
        if model not in self.allowed or (self.pin_default and not explicit):
            ctx.decision = RouteDecision(model=self.default, repo=self.repo,
                                         reason="pinned to %r (was %s: %s)" % (self.default, model, reason),
                                         detection=decision.get("detection"), workflow=decision.get("workflow"))


def make_resolve_model(router, allowed, original):
    """替换 laya.serve._resolve_model：Router 认识且允许的名字直接通过；其余交给原函数，但结果若不在允许名单里就当作「未指定」。"""
    def _resolve_model(model):
        if not model:
            return None
        try:
            key = router.resolve(model)
        except ValueError:
            key = None
        if key is not None and key in allowed:
            return key
        resolved = original(model)       # 官方 Hub id → 名字；路径 → 422；jev-1 等 → None
        if resolved is not None and resolved not in allowed:
            return None
        return resolved
    return _resolve_model


def build_router(args):
    """按参数建 Router；返回 (router, customs, builtins, default, allowed)。"""
    from laya.router import DEFAULT_MODELS, Router, _repo_str, normalise_name

    customs = parse_custom(args.custom)
    builtins = []
    for name in parse_list(args.builtin):
        try:
            builtins.append(normalise_name(name))
        except ValueError:
            raise SystemExit(T("builtin_bad", name))
    allowed = list(customs) + [b for b in builtins if b not in customs]
    if not allowed:
        raise SystemExit(T("no_models"))
    default = (args.default or "").strip().lower() or allowed[0]
    if default not in allowed:
        try:
            default = normalise_name(default)
        except ValueError:
            pass
        if default not in allowed:
            raise SystemExit(T("default_bad", args.default, ", ".join(allowed)))
    device = None if (args.device or "auto") == "auto" else args.device
    repo_of_default = customs.get(default) or _repo_str(DEFAULT_MODELS[default])
    hook = PinHook(default, repo_of_default, allowed, args.pin_default)
    # Router 构造只登记名字，不加载、不下载任何权重；官方名字（english/multilingual/typed-decisions）
    # 总在 router.models 里，但不在 allowed 里的永远被钩子改写成默认模型，所以不会触发下载。
    router = Router(models=customs, default=default, device=device, max_loaded=max(1, args.max_loaded), hooks=[hook])
    return router, customs, builtins, default, allowed


def add_models_route(app, router, customs, builtins, default):
    """GET /v1/models。如果 laya.serve 已经注册了同路径，先移除再挂我们的。"""
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/v1/models"]

    @app.get("/v1/models")
    def list_models():
        loaded = set(router.loaded or [])
        registered = router.registered
        data = []
        for name in list(customs) + [b for b in builtins if b not in customs]:
            if name in customs:
                source = customs[name]
            else:
                spec = router.models.get(name)
                source = spec if isinstance(spec, str) else "/".join(x for x in (spec or ()) if x)
            data.append({"id": name, "custom": name in customs, "loaded": name in loaded,
                         "source": registered.get(name, {}).get("source") or source, "default": name == default})
        return {"object": "list", "data": data, "default": default}


def create_server_app(args):
    """建 Router、打补丁、建 FastAPI app（不启动 uvicorn；测试也用它）。返回 (app, router, info)。"""
    import laya.serve as serve
    router, customs, builtins, default, allowed = build_router(args)
    original = serve._resolve_model
    if not getattr(original, "_laya_wb_patched", False):
        patched = make_resolve_model(router, set(allowed), original)
        patched._laya_wb_patched = True
        serve._resolve_model = patched
    if args.api_key:
        os.environ["LAYA_API_KEY"] = args.api_key
    app = serve.create_app(router)
    add_models_route(app, router, customs, builtins, default)
    info = {"customs": customs, "builtins": builtins, "default": default, "allowed": allowed}
    return app, router, info


def preload_names(args, default, allowed):
    if args.preload is None:
        return [default]
    if args.preload.strip().lower() in ("none", "-"):
        return []
    names = []
    for n in parse_list(args.preload):
        key = n.lower()
        if key not in allowed:
            raise SystemExit(T("preload_bad", n))
        names.append(key)
    return names


def main(argv=None):
    args = build_parser().parse_args(argv)
    missing = []
    for mod in ("torch", "laya", "fastapi", "uvicorn"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise SystemExit(T("need_libs", ", ".join(missing)))
    import uvicorn

    app, router, info = create_server_app(args)
    say(T("starting", args.host, args.port, ",".join(info["builtins"]) or T("none"),
          ",".join(info["customs"]) or T("none"), info["default"], T("pinned") if args.pin_default else ""))
    names = preload_names(args, info["default"], info["allowed"])
    if names:
        say(T("preloading", ",".join(names)))
        router.preload(names)
        say(T("ready", json.dumps(router.loaded)))
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
