"""单张照片的量化分析：清晰度、曝光、dHash、EXIF 拍摄时间、缩略图。"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from . import raw

from .const import (
    EXPOSURE_HIGHLIGHT,
    EXPOSURE_SHADOW,
    FLAG_BLUR,
    FLAG_LOWRES,
    FLAG_OVEREXPOSED,
    FLAG_UNDEREXPOSED,
    MIN_MEGAPIXEL,
    OVEREXPOSED_RATIO,
    SHARP_BLUR_MAX,
    UNDEREXPOSED_RATIO,
)

# 分析时把图压到这个尺寸再算，快且够用
_ANALYZE_SIDE = 512

_EXIF_TAKEN = 36867  # DateTimeOriginal


def _load_gray(path: Path, side: int) -> tuple[Image.Image, int, int]:
    """读取图片（含 RAW 的内嵌预览），按 EXIF 方向摆正，返回 (灰度图, 原宽, 原高)。

    原始尺寸单独从文件头读（不解码整张图），避免把缩放后的尺寸写进库。
    """
    width, height = raw.image_size(path)
    im = raw.load_image(path, max_side=side)
    if not width or not height:
        width, height = im.size
    if max(im.size) > side:
        im = im.copy()
        im.thumbnail((side, side), Image.BILINEAR)
    gray = im.convert("L")
    return gray.copy(), width, height


def _sharpness(gray: Image.Image) -> float:
    """Laplacian 方差：值越小越糊。"""
    arr = np.asarray(gray, dtype=np.float32)
    if arr.shape[0] < 3 or arr.shape[1] < 3:
        return 0.0
    lap = (
        -4.0 * arr[1:-1, 1:-1]
        + arr[:-2, 1:-1]
        + arr[2:, 1:-1]
        + arr[1:-1, :-2]
        + arr[1:-1, 2:]
    )
    return float(lap.var())


def _exposure_ratios(gray: Image.Image) -> tuple[float, float]:
    """返回 (高光像素占比, 暗部像素占比)。"""
    hist = np.asarray(gray.histogram(), dtype=np.float64)
    total = hist.sum() or 1.0
    over = float(hist[EXPOSURE_HIGHLIGHT:].sum() / total)
    under = float(hist[: EXPOSURE_SHADOW + 1].sum() / total)
    return over, under


def dhash(gray: Image.Image, size: int = 8) -> int:
    """差值哈希：转成 64 位整数，用于比较两张图是否同一画面。"""
    small = gray.resize((size + 1, size), Image.BILINEAR)
    arr = np.asarray(small, dtype=np.int16)
    diff = arr[:, 1:] > arr[:, :-1]
    bits = 0
    for byte in np.packbits(diff.reshape(-1)):
        bits = (bits << 8) | int(byte)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def exif_taken_at(path: Path) -> float | None:
    """读 EXIF 拍摄时间，返回 Unix 时间戳；读不到返回 None。

    RAW 打不开时，改从它内嵌的那张 JPEG 里读——拍摄时间就在那儿。
    """
    raw_bytes: bytes | None = None
    try:
        with Image.open(path) as im:
            raw_bytes = im.getexif().get(_EXIF_TAKEN)
    except Exception:
        raw_bytes = None
    if not raw_bytes:
        payload = raw.embedded_preview(path)
        if payload is None:
            return None
        try:
            with Image.open(io.BytesIO(payload)) as im:
                raw_bytes = im.getexif().get(_EXIF_TAKEN)
        except Exception:
            return None
    if not raw_bytes:
        return None
    try:
        import datetime as _dt

        dt = _dt.datetime.strptime(str(raw_bytes).strip(), "%Y:%m:%d %H:%M:%S")
        return dt.timestamp()
    except Exception:
        return None


def analyze(path: Path) -> dict:
    """分析一张照片，返回可直接写库的字段。

    失败时返回 None（调用方跳过），不让单张坏图打断整体分析。
    """
    try:
        gray, width, height = _load_gray(path, _ANALYZE_SIDE)
    except Exception:
        return None

    sharp = _sharpness(gray)
    over, under = _exposure_ratios(gray)
    megapixel = width * height / 1_000_000.0

    flags = 0
    if sharp < SHARP_BLUR_MAX:
        flags |= FLAG_BLUR
    if over > OVEREXPOSED_RATIO:
        flags |= FLAG_OVEREXPOSED
    if under > UNDEREXPOSED_RATIO:
        flags |= FLAG_UNDEREXPOSED
    if megapixel < MIN_MEGAPIXEL:
        flags |= FLAG_LOWRES

    return {
        "width": width,
        "height": height,
        "sharp": sharp,
        "over_ratio": over,
        "under_ratio": under,
        "flags": flags,
        "dhash": str(dhash(gray)),
        "taken_at": exif_taken_at(path),
    }


def load_thumb(path: Path, side: int) -> Image.Image:
    """读一张缩略图（已按 EXIF 摆正，含 RAW 内嵌预览）；调用方负责保持比例。"""
    im = raw.load_image(path, max_side=side)
    if max(im.size) > side:
        im = im.copy()
        im.thumbnail((side, side), Image.LANCZOS)
    return im.convert("RGB")


def load_full(path: Path, max_side: int = 0) -> Image.Image:
    """读大图用于单张预览。

    max_side <= 0（默认）表示**不缩放，按原图分辨率解码**——看片就是要看原图。
    RAW 没有"原图可解码"这回事，返回的是它内嵌的全尺寸 JPEG 预览。
    只有显式传了正数才会等比缩小（例如生成联系表缩略图时）。
    """
    return raw.load_image(path, max_side=max_side)
