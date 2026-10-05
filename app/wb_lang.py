# -*- coding: utf-8 -*-
"""界面语言的选择 / Picks the UI language ("zh" or "en").

config.json 的 "language": "auto"（默认，跟随系统语言）/ "zh" / "en"。
环境变量 LAYA_WB_LANG 可以临时覆盖。
"""
import os


def detect(configured="auto"):
    for value in (os.environ.get("LAYA_WB_LANG"), configured):
        text = str(value or "").strip().lower()
        if text.startswith("zh"):
            return "zh"
        if text.startswith("en"):
            return "en"
    if os.name == "nt":
        try:
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "zh" if primary == 0x04 else "en"
        except Exception:
            pass
    candidates = [os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    try:
        import locale
        candidates.append(locale.getlocale()[0] or "")
    except Exception:
        pass
    for text in candidates:
        if text and text.lower().startswith(("zh", "chinese")):
            return "zh"
    return "en"
