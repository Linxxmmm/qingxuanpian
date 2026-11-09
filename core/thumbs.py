"""缩略图缓存：按 (路径, mtime, 尺寸) 做磁盘缓存，第二次打开文件夹是秒开的。

缓存目录放在照片文件夹下的 `.xuanpian-cache`，可随时整体删除，删了会重建。
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PIL import Image

from . import analyze, paths
from .const import THUMB_QUALITY, THUMB_SIZES

CACHE_DIR = paths.CACHE_DIR


class ThumbCache:
    def __init__(self, root: str | Path, cache_dir: str | Path | None = None):
        self.root = Path(root)
        self.dir = Path(cache_dir) if cache_dir else (self.root / CACHE_DIR)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # 实在写不了就只在内存里缓存，不影响看图
            self.dir = Path(tempfile.mkdtemp(prefix="xp-thumbs-"))
        self._mem: dict[tuple[str, int], Image.Image] = {}

    def _key(self, rel: str, mtime: float, size: int) -> Path:
        raw = f"{rel}|{int(mtime)}|{size}".encode("utf-8")
        return self.dir / (hashlib.md5(raw).hexdigest() + ".jpg")

    def get(self, rel: str, mtime: float, size: int) -> Image.Image | None:
        """取缩略图；磁盘没有就解码原图并写缓存。失败返回 None。"""
        mem_key = (rel, size)
        if mem_key in self._mem:
            return self._mem[mem_key]

        path = self._key(rel, mtime, size)
        if path.exists():
            try:
                with Image.open(path) as im:
                    img = im.convert("RGB").copy()
                self._mem[mem_key] = img
                return img
            except Exception:
                path.unlink(missing_ok=True)

        src = self.root / rel
        if not src.exists():
            return None
        try:
            img = analyze.load_thumb(src, size)
        except Exception:
            return None
        try:
            img.save(path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        except Exception:
            pass
        self._mem[mem_key] = img
        return img

    def closest_size(self, wanted: int) -> int:
        """把想要的格子边长映射到最近的缓存档位，避免重复解码。"""
        return min(THUMB_SIZES, key=lambda s: abs(s - wanted))

    def clear(self) -> int:
        self._mem.clear()
        n = 0
        for f in self.dir.glob("*.jpg"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        return n
