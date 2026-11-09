"""RAW / 特殊格式的照片读取。

大多数相机 RAW（CR2、CR3、NEF、ARW、DNG、RAF、RW2、ORF、PEF…）里都嵌着一张
**全尺寸 JPEG 预览图**，选片完全够用。Pillow 打不开这些格式，所以这里的思路是：

1. 先让 Pillow 试一次（DNG、部分 TIFF 系 RAW 它能直接读）；
2. 不行就在文件字节里找最大的那张内嵌 JPEG（从 SOI 到 EOI），解码取用。

这样既不需要装 rawpy/libraw，也不会因为一张 RAW 读不出来就把整张卡片变成空白。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from .const import RAW_EXTS

# iPhone 的 HEIC/HEIF：装了 pillow-heif 就能像普通图片一样打开，没装也不影响其它格式
try:  # pragma: no cover - 取决于运行环境装了没
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

# 内嵌预览至少要这么大才算"有意义的预览"，太小的只是 EXIF 缩略图
_MIN_PREVIEW_SIDE = 320
# 超过这个大小就不整体读进内存了，改成按块扫描
_CHUNK = 8 << 20
_EXIF_ORIENTATION = 274


def is_raw(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTS


def _try_pillow(data: bytes | Path) -> Image.Image | None:
    try:
        source = io.BytesIO(data) if isinstance(data, bytes) else data
        with Image.open(source) as im:
            im.load()
            return ImageOps.exif_transpose(im).copy()
    except Exception:
        return None


def _iter_jpeg_segments(blob: bytes):
    """在字节流里找出所有 JPEG 段（SOI…EOI），按出现顺序返回 (start, end)。"""
    start = blob.find(b"\xff\xd8\xff")
    while start != -1:
        end = blob.find(b"\xff\xd9", start + 3)
        if end == -1:
            return
        yield start, end + 2
        start = blob.find(b"\xff\xd8\xff", end + 2)


def _preview_candidates(blob: bytes) -> list[tuple[int, int, int]]:
    """列出所有可解码的内嵌 JPEG：(最大边, 面积, start, end)。

    只读文件头拿尺寸（Image.open 是惰性的），不解码像素——RAW 里常有
    1620px 的小预览和 6000px 的全尺寸预览两张，按用途各取所需才快。
    """
    out: list[tuple[int, int, int, int]] = []
    for start, end in _iter_jpeg_segments(blob):
        if end - start < 8 * 1024:  # 太小的跳过，多半是 EXIF 缩略图
            continue
        try:
            with Image.open(io.BytesIO(blob[start:end])) as im:
                size = im.size
        except Exception:
            continue
        if max(size) < _MIN_PREVIEW_SIDE:
            continue
        out.append((max(size), size[0] * size[1], start, end))
    return out


def _pick_segment(blob: bytes, max_side: int = 0) -> tuple[int, int] | None:
    """挑一张合适的预览：要缩略图就挑"够用且最小"的，要看大图就挑最大的。"""
    candidates = _preview_candidates(blob)
    if not candidates:
        return None
    if max_side and max_side > 0:
        fit = [c for c in candidates if c[0] >= max_side]
        if fit:
            best = min(fit, key=lambda c: c[1])
            return best[2], best[3]
    widest = max(candidates, key=lambda c: c[0])
    return widest[2], widest[3]


def _best_preview_blob(blob: bytes, max_side: int = 0) -> bytes | None:
    span = _pick_segment(blob, max_side)
    if span is None:
        return None
    return blob[span[0]: span[1]]


def _best_preview(blob: bytes, max_side: int = 0) -> Image.Image | None:
    payload = _best_preview_blob(blob, max_side)
    if payload is None:
        return None
    try:
        with Image.open(io.BytesIO(payload)) as im:
            im.load()
            return ImageOps.exif_transpose(im).copy()
    except Exception:
        return None


def embedded_preview(path: str | Path) -> bytes | None:
    """返回文件里嵌入式 JPEG 预览的原始字节（RAW 的 EXIF 信息都在里面）。"""
    try:
        return _best_preview_blob(_read_bytes(Path(path)))
    except Exception:
        return None


def _read_bytes(path: Path, max_size: int = 512 << 20) -> bytes:
    """读整个文件；过大时只读前 max_size 字节（预览图一般在文件开头附近）。"""
    size = path.stat().st_size
    with open(path, "rb") as handle:
        return handle.read(min(size, max_size))


def image_size(path: str | Path) -> tuple[int, int]:
    """只读文件头拿原始像素尺寸（不解码整张图，很快）。

    读不出来返回 (0, 0)。EXIF 里的旋转标记会照实换算成"看到的宽高"。
    """
    path = Path(path)
    try:
        with Image.open(path) as im:
            size = im.size
            orientation = im.getexif().get(_EXIF_ORIENTATION)
        return _apply_orientation(size, orientation)
    except Exception:
        pass

    payload = embedded_preview(path)
    if payload is None:
        return (0, 0)
    try:
        with Image.open(io.BytesIO(payload)) as im:
            size = im.size
            orientation = im.getexif().get(_EXIF_ORIENTATION)
        return _apply_orientation(size, orientation)
    except Exception:
        return (0, 0)


def _apply_orientation(size: tuple[int, int], orientation) -> tuple[int, int]:
    """旋转 90°/270° 的 EXIF 方向，宽高要对调。"""
    if orientation in (5, 6, 7, 8):
        return size[1], size[0]
    return size


def load_image(path: str | Path, max_side: int = 0) -> Image.Image:
    """把任意支持格式（含 RAW）读成 PIL 图。

    max_side <= 0 表示按可用的最大分辨率返回；否则等比缩小。
    读不出来时抛异常，由调用方决定怎么兜底。
    """
    path = Path(path)

    # 1) Pillow 直接能读的（JPEG/PNG/WebP/TIFF/部分 DNG）
    direct = _try_pillow(path)
    if direct is not None:
        if max_side and max(direct.size) > max_side:
            direct.thumbnail((max_side, max_side), Image.LANCZOS)
        return direct.convert("RGB") if direct.mode not in ("RGB", "L") else direct

    # 2) 内嵌 JPEG 预览（CR2 / CR3 / NEF / ARW / RAF / RW2 / ORF / PEF…）
    blob = _read_bytes(path)
    preview = _best_preview(blob, max_side)
    if preview is not None:
        if max_side and max(preview.size) > max_side:
            preview.thumbnail((max_side, max_side), Image.LANCZOS)
        return preview

    raise ValueError(f"读不出预览：{path.name}")
