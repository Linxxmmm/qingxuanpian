"""造几个假 RAW 文件（外面是垃圾字节，里面塞真 JPEG），验证预览提取。

真实 RAW（CR2/CR3/NEF/ARW…）的结构千差万别，但它们都把全尺寸 JPEG 预览
原样存在文件里，所以"外面套壳 + 首尾塞噪声 + 中间塞 JPEG"足以覆盖提取逻辑。
"""

from __future__ import annotations

import io
import os
import random
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import analyze, raw, scanner  # noqa: E402
from core.project import Project  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sample2"
WORK = ROOT / "_rawtest"


def make_raw(src: Path, dest: Path, with_small_thumb: bool = True) -> None:
    """把一个 JPEG 包进假 RAW 外壳：头噪声 + 缩略图 + 全尺寸预览 + 尾噪声。"""
    full = src.read_bytes()
    rnd = random.Random(src.name)

    head = bytes(rnd.randrange(256) for _ in range(4096))
    tail = bytes(rnd.randrange(256) for _ in range(2048))
    chunks = [head]

    if with_small_thumb:
        with Image.open(src) as im:
            small = im.copy()
            small.thumbnail((160, 160))
            buf = io.BytesIO()
            small.convert("RGB").save(buf, "JPEG", quality=70)
            chunks.append(buf.getvalue())

    chunks.append(full)
    chunks.append(tail)
    dest.write_bytes(b"".join(chunks))


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    srcs = sorted(SRC.glob("*.jpg"))[:4]
    names = ["DSC_0001.CR2", "DSC_0002.NEF", "IMG_0003.ARW", "P1000004.RW2"]
    for src, name in zip(srcs, names):
        make_raw(src, WORK / name)
    # 一张真正的普通 JPEG 当对照
    shutil.copy2(srcs[0], WORK / "normal.jpg")
    # 一张纯垃圾的 .CR2，确认不会打断整体流程
    (WORK / "broken.CR2").write_bytes(b"\x00" * 5000 + b"not a jpeg at all")

    print("文件：", sorted(p.name for p in WORK.iterdir()))
    print("scanner 找到：", [p.name for p in scanner.iter_images(WORK)])

    print("\n单张读取检查：")
    for path in sorted(WORK.iterdir()):
        print("  raw.is_raw:", raw.is_raw(path), "|", path.name)
        try:
            im = raw.load_image(path)
            print(f"     -> {im.size} {im.mode}")
        except Exception as exc:
            print(f"     -> 读不出：{exc}")
        print("     taken_at:", analyze.exif_taken_at(path))

    proj = Project(WORK)
    print("\nsync:", proj.sync())
    proj.analyze_all()
    rows = proj.photos()
    print(f"入库 {len(rows)} 张：")
    for r in rows:
        tag = "（无法预览占位）" if r["width"] == 0 else f"{r['width']}×{r['height']}"
        print(f"    {r['path']:<18} {tag}  flags={r['flags']}  group={r['group_id']}")
    print("counts:", proj.counts())
    proj.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
