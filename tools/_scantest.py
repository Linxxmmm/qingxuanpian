"""排查脚本：造一个贴近真实的照片目录，看扫描/入库/列表各环节拿到多少张。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import scanner  # noqa: E402
from core.project import Project  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sample2"
WORK = ROOT / "_scantest"


def build() -> Path:
    shutil.rmtree(WORK, ignore_errors=True)
    srcs = sorted(SRC.glob("*.jpg"))[:6]
    layout = [
        ("", "IMG_0001.JPG"),                     # 大写扩展名，根目录
        ("", "婚礼 现场 #1.jpg"),                  # 中文 + 空格 + 井号
        ("", "a&b (2).jpeg"),
        ("子目录/场次一", "DSC_001.jpg"),          # 中文子目录
        ("子目录/场次二", "DSC_002.JPG"),
        ("子目录", "IMG_0002.png"),
    ]
    for i, (sub, name) in enumerate(layout):
        target_dir = WORK / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(srcs[i % len(srcs)], target_dir / name)
    # 不该被当成照片的东西
    (WORK / "notes.txt").write_text("x", encoding="utf-8")
    (WORK / "子目录" / "IMG_0002.xmp").write_text("x", encoding="utf-8")
    hidden = WORK / ".hidden"
    hidden.mkdir(exist_ok=True)
    shutil.copy2(srcs[0], hidden / "hidden.jpg")
    return WORK


def main() -> int:
    root = build()
    print("目录树：")
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix() or "."
        print(f"  {rel}/  dirs={dirnames} files={filenames}")

    files = list(scanner.iter_images(root))
    print(f"\niter_images 找到 {len(files)} 张：")
    for f in files:
        print("   ", f.relative_to(root).as_posix())

    scanned = scanner.scan(root)
    print(f"\nscan() 返回 {len(scanned)} 条")

    proj = Project(root)
    print("sync:", proj.sync())
    proj.analyze_all()
    rows = proj.photos()
    print(f"库里有 {len(rows)} 张：")
    for r in rows:
        print(f"    {r['path']}  {r['width']}×{r['height']} flags={r['flags']}")
    print("counts:", proj.counts())
    proj.close()

    ui_rows = [r for r in rows]
    print(f"\n如果界面只显示 1 张，说明 UI 层有额外过滤；这里直接拿到 {len(ui_rows)} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
