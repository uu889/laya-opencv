# -*- coding: utf-8 -*-
"""把一张图交给 Jev 看（TypeSafe 的实验功能，见 https://docs.typesafe.ai/images）。只用标准库。

Jev 1.13 / 1.14 可以直接收图：图放在请求顶层的 assets 里，用一个引用字符串（这里用 UUID）作键；
素材（state）或题干里出现这个字符串的地方，模型就会看到这张图。请求必须带上
`TypeSafe-Danger-Zone-Images: true`。本地 Laya 只读文本，不能看图。

服务端不会帮你缩放：尺寸、格式不合格的图直接拒绝，而且一张不合格整个请求失败。
所以发出前在这里先按文档的限制检查一遍；缩放和转格式由页面（canvas）或视觉服务做。
"""
import base64
import binascii
import struct
import uuid

HEADER = ("TypeSafe-Danger-Zone-Images", "true")

# 文档里的限制（https://docs.typesafe.ai/images#limits），改了只改这里
MIN_SIDE = 280
MAX_SIDE = 1568
MIN_PIXELS = 78400
MAX_PIXELS = 2458624
MAX_FILE = 16 * 1024 * 1024
MAX_REQUEST = 32 * 1024 * 1024

MODES = ("opencv", "opencv+jev", "jev")

MSG = {
    "bad_mode": ("vision_mode 只能是 opencv、opencv+jev 或 jev", "vision_mode must be opencv, opencv+jev or jev"),
    "no_image": ("「Jev 看图」需要一张图片（image）", "Jev image modes need an image (image)"),
    "bad_b64": ("图片不是合法的 base64", "The image is not valid base64"),
    "bad_format": ("Jev 只收 PNG 或 JPEG 图片，请先转换格式（页面上传时会自动转换）",
                   "Jev accepts PNG or JPEG only; convert the image first (the page converts uploads for you)"),
    "bad_size": ("图片尺寸 %d×%d 不符合 Jev 的要求：每边 %d ~ %d 像素",
                 "Image size %dx%d is outside Jev's limits: %d to %d pixels per side"),
    "bad_pixels": ("图片总像素 %d 不符合 Jev 的要求：%d ~ %d", "Image has %d pixels; Jev requires %d to %d"),
    "too_big": ("图片有 %.1f MiB，超过 Jev 单张 16 MiB 的上限", "The image is %.1f MiB, over Jev's 16 MiB per-image limit"),
    "req_big": ("请求有 %.1f MiB，超过 Jev 32 MiB 的上限", "The request is %.1f MiB, over Jev's 32 MiB limit"),
}


class ImageError(Exception):
    def __init__(self, key, *args):
        Exception.__init__(self, key)
        self.key = key
        self.args_ = args

    def text(self, lang="zh"):
        msg = MSG[self.key][1 if lang == "en" else 0]
        return msg % self.args_ if self.args_ else msg


def read_image(data):
    """data URL 或 base64 字符串 → 原始字节。"""
    text = str(data or "").strip()
    if text.startswith("data:"):
        text = text.split(",", 1)[1] if "," in text else ""
    if not text:
        raise ImageError("no_image")
    try:
        return base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError):
        raise ImageError("bad_b64")


def _jpeg_info(raw):
    """返回 (宽, 高, 是否渐进式)。扫描到第一个 SOF 段为止。"""
    i = 2
    while i + 4 <= len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = struct.unpack(">H", raw[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > len(raw):
                break
            h, w = struct.unpack(">HH", raw[i + 5:i + 9])
            return w, h, marker in (0xC2, 0xC6, 0xCA, 0xCE)
        i += 2 + length
    return None


def inspect_image(raw):
    """返回 {format, width, height, bytes, progressive}；不是 PNG / JPEG 时抛 ImageError。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR" and len(raw) >= 24:
        w, h = struct.unpack(">II", raw[16:24])
        if b"acTL" in raw[:raw.find(b"IDAT") if b"IDAT" in raw else len(raw)]:
            raise ImageError("bad_format")                 # 动画 PNG 会被拒绝
        return {"format": "png", "width": w, "height": h, "bytes": len(raw), "progressive": False}
    if raw[:2] == b"\xff\xd8":
        info = _jpeg_info(raw)
        if info:
            return {"format": "jpg", "width": info[0], "height": info[1], "bytes": len(raw), "progressive": info[2]}
    raise ImageError("bad_format")


def check(info):
    """按文档的限制检查一张图，不合格抛 ImageError。"""
    w, h = info["width"], info["height"]
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE:
        raise ImageError("bad_size", w, h, MIN_SIDE, MAX_SIDE)
    if not MIN_PIXELS <= w * h <= MAX_PIXELS:
        raise ImageError("bad_pixels", w * h, MIN_PIXELS, MAX_PIXELS)
    if info["bytes"] > MAX_FILE:
        raise ImageError("too_big", info["bytes"] / 1048576.0)


def make_asset(data):
    """一张图（data URL / base64）→ (引用, asset, 图片信息)。引用是新的 UUID，不会和正文撞上。"""
    raw = read_image(data)
    info = inspect_image(raw)
    check(info)
    ref = "img-" + uuid.uuid4().hex
    asset = {"type": "image", "format": info["format"], "data_base64": base64.b64encode(raw).decode("ascii")}
    return ref, asset, info


def check_request(payload_bytes):
    if len(payload_bytes) > MAX_REQUEST:
        raise ImageError("req_big", len(payload_bytes) / 1048576.0)


def redact(request):
    """给页面显示用：把 assets 里的 base64 换成一句说明，免得几 MB 的字符串塞进历史和原始请求。"""
    if not isinstance(request, dict) or not isinstance(request.get("assets"), dict):
        return request
    out = dict(request)
    out["assets"] = {}
    for ref, asset in request["assets"].items():
        item = dict(asset) if isinstance(asset, dict) else asset
        if isinstance(item, dict) and isinstance(item.get("data_base64"), str):
            item["data_base64"] = "<%d base64 chars>" % len(item["data_base64"])
        out["assets"][ref] = item
    return out
