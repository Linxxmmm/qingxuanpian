"""生成演示用样片库：把样片放大到真实相机尺寸，再人为造出连拍串和几种硬伤。

只用于界面演示与冒烟测试，不会进 git。
"""

from __future__ import annotations

import random
import shutil
import time
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT.parent / "选片小程序" / "preview" / "assets"
OUT = ROOT / "sample2"

WIDE = 3000


def load_big(src: Path, width: int = WIDE) -> Image.Image:
    """读一张样片并按需放大到相机尺寸，硬伤样片也要基于它来造。"""
    with Image.open(src) as im:
        im = im.convert("RGB")
        ratio = width / im.width
        if ratio > 1:
            im = im.resize((width, int(im.height * ratio)), Image.LANCZOS)
        return im


def upscale(src: Path, dst: Path, width: int = WIDE) -> None:
    im = load_big(src, width)
    im.save(dst, "JPEG", quality=92)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    originals = sorted(SRC.glob("*.jpg"))
    if not originals:
        raise SystemExit(f"找不到样片：{SRC}")

    now = time.time()
    made = 0
    for i, src in enumerate(originals):
        dst = OUT / f"IMG_{2000 + i:04d}.jpg"
        upscale(src, dst)
        stamp = now - (len(originals) - i) * 600
        _touch(dst, stamp)
        made += 1

    # 造一组真的连拍：同一画面，轻微位移 + 逐张变糊
    burst_src = originals[5] if len(originals) > 5 else originals[0]
    im = load_big(burst_src)
    base_stamp = now - 300
    for k in range(5):
        frame = im.crop((k * 6, 0, im.width - (4 - k) * 6, im.height))
        if k > 0:
            frame = frame.filter(ImageFilter.GaussianBlur(radius=0.4 * k))
            frame = ImageEnhance.Brightness(frame).enhance(1.0 + 0.02 * k)
        path = OUT / f"BURST_{k + 1}.jpg"
        frame.save(path, "JPEG", quality=92)
        _touch(path, base_stamp + k * 0.6)
        made += 1

    # 故意做过曝和欠曝各一张，用来验证硬伤角标（同样放大到相机尺寸）
    im = load_big(originals[2])
    over = ImageEnhance.Brightness(im).enhance(2.6)
    over.save(OUT / "OVER_1.jpg", "JPEG", quality=92)
    _touch(OUT / "OVER_1.jpg", now - 200)
    under = ImageEnhance.Brightness(im).enhance(0.02)
    under.save(OUT / "UNDER_1.jpg", "JPEG", quality=92)
    _touch(OUT / "UNDER_1.jpg", now - 180)

    # 纯虚焦一张
    blur = load_big(originals[3]).filter(ImageFilter.GaussianBlur(radius=60))
    blur.save(OUT / "BLUR_1.jpg", "JPEG", quality=92)
    _touch(OUT / "BLUR_1.jpg", now - 160)

    print(f"样片库已生成：{OUT}（{made + 3} 张）")


def _touch(path: Path, stamp: float) -> None:
    import os

    os.utime(path, (stamp, stamp))


if __name__ == "__main__":
    main()
