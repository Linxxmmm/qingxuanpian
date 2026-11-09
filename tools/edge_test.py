"""边界情况自检：空目录、坏图、重名归档、文件被移走后重新扫描。

    python tools/edge_test.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.project import Project  # noqa: E402

PASS, FAIL = [], []


def _make_photo(path: Path, w: int, h: int, color) -> None:
    """造一张真图（带点纹理，免得被当成纯色整块）。"""
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (w, h), color)
    draw = ImageDraw.Draw(img)
    for i in range(0, w, 40):
        draw.line([(i, 0), (i, h)], fill=(255, 255, 255), width=2)
    img.save(path, quality=88)


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}{(' — ' + detail) if detail else ''}")


def main() -> int:
    base = ROOT / "_edgetest"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir()

    # 1) 空目录
    empty = base / "empty"
    empty.mkdir()
    proj = Project(empty)
    proj.sync()
    check("空目录不报错", proj.counts()["total"] == 0, "0 张")

    # 2) 坏图 + 正常图
    mixed = base / "mixed"
    mixed.mkdir()
    src = sorted((ROOT / "sample2").glob("*.jpg"))[0]
    shutil.copy2(src, mixed / "good.jpg")
    (mixed / "broken.jpg").write_bytes(b"not really a jpeg")
    proj2 = Project(mixed)
    proj2.sync()
    proj2.analyze_all()
    counts = proj2.counts()
    check("坏图不会让扫描中断", counts["total"] == 2, f"{counts['total']} 张")
    items = proj2.photos()
    broken = [i for i in items if i["name"] == "broken.jpg"]
    check(
        "坏图仍被记录（不阻塞其它照片）",
        bool(broken),
        str({k: broken[0][k] for k in ("width", "height", "analyzed")}) if broken else "",
    )

    # 3) 重名归档：目标目录里已经有同名文件
    good = [i for i in items if i["name"] == "good.jpg"][0]
    proj2.store.set_score([good["id"]], 5)
    target_dir = mixed / "精选"
    target_dir.mkdir()
    (target_dir / "good.jpg").write_bytes(b"placeholder")
    res = proj2.archive("pick", "move")
    files = sorted(p.name for p in target_dir.iterdir())
    check("重名不覆盖、自动加后缀", res["count"] == 1 and len(files) == 2, "、".join(files))

    # 4) 撤销后原文件回到原处
    proj2.undo(res["log_id"])
    check(
        "撤销后原图回到根目录",
        (mixed / "good.jpg").exists() and len(list(target_dir.iterdir())) == 1,
    )

    # 5) 文件被外部删掉后重新扫描（连占位文件一起删干净）
    for leftover in target_dir.iterdir():
        leftover.unlink()
    (mixed / "good.jpg").unlink()
    proj2.sync()
    check("外部删除的照片不计入统计", proj2.counts()["total"] == 1,
          f"剩 {proj2.counts()['total']} 张")

    # 6) RAW：外面是外壳，里面嵌着 JPEG 预览 —— 必须能认出来、能读出来
    raw_dir = base / "raw"
    raw_dir.mkdir()
    from tools._rawtest import make_raw  # 复用造壳工具，保证和真实 RAW 一致

    make_raw(src, raw_dir / "DSC_9001.CR2")
    make_raw(src, raw_dir / "DSC_9002.NEF")
    (raw_dir / "broken.CR2").write_bytes(b"\x00" * 8192)
    (raw_dir / "readme.txt").write_text("notes", encoding="utf-8")
    proj3 = Project(raw_dir)
    stats = proj3.sync()
    proj3.analyze_all()
    raw_items = {i["name"]: i for i in proj3.photos()}
    check("RAW 文件被扫进来", stats["total"] == 3, f"{stats['total']} 个 RAW")
    check(
        "RAW 的内嵌预览能读出尺寸",
        raw_items.get("DSC_9001.CR2", {}).get("width", 0) > 1000,
        f"{raw_items.get('DSC_9001.CR2', {}).get('width')}×"
        f"{raw_items.get('DSC_9001.CR2', {}).get('height')}",
    )
    check(
        "读不出的 RAW 也不丢（占位可打分）",
        raw_items.get("broken.CR2", {}).get("width") == 0
        and raw_items.get("broken.CR2", {}).get("analyzed") == 1,
    )
    check(
        "非照片文件的扩展名被统计出来",
        (stats.get("skipped") or {}).get(".txt") == 1,
        str(stats.get("skipped")),
    )

    shutil.rmtree(base, ignore_errors=True)

    # ---------------------------------------------------------------- 一键全部归档
    base = ROOT / "_edgetest_all"
    shutil.rmtree(base, ignore_errors=True)
    (base / "sub").mkdir(parents=True)
    names = ["a.jpg", "b.jpg", "c.jpg", "sub/d.jpg", "sub/e.jpg"]
    for i, name in enumerate(names):
        _make_photo(base / name, 800, 600, (40 * i, 60, 120))
    proj = Project(base)
    proj.sync()
    proj.analyze_pending()
    ids = [p["id"] for p in proj.photos()]
    # 5 张分到三个档：2 精选、2 待定、1 淘汰
    for pid, score in zip(ids, (5, 5, 4, 3, 1)):
        proj.store.set_score([pid], score)
    counts = proj.counts()
    result = proj.archive(["pick", "maybe", "reject"], "move")
    logs = proj.logs(5)
    moved_files = list(base.glob("精选/*.jpg")) + list(base.glob("待定/*.jpg"))
    moved_files += list(base.glob("淘汰/*.jpg"))
    check(
        "一键全部归档搬走全部已评分照片",
        result["count"] == 5 and counts["pick"] + counts["maybe"] + counts["reject"] == 5,
        f"{result['count']} 张，日志 bucket={logs[0]['bucket'] if logs else '?'}",
    )
    check(
        "三个文件夹里确实各有文件",
        len(list(base.glob("精选/*.jpg"))) == 2
        and len(list(base.glob("待定/*.jpg"))) == 2
        and len(list(base.glob("淘汰/*.jpg"))) == 1,
        f"精选 {len(list(base.glob('精选/*.jpg')))}、"
        f"待定 {len(list(base.glob('待定/*.jpg')))}、"
        f"淘汰 {len(list(base.glob('淘汰/*.jpg')))}",
    )
    check("一键全部只写一条归档记录", len(logs) == 1 and logs[0]["count"] == 5, f"{len(logs)} 条")
    undo = proj.undo(logs[0]["id"])
    still_left = [p for p in moved_files if p.exists()]
    check(
        "一次撤销把三档全部还原",
        undo["restored"] == 5 and not still_left,
        f"还原 {undo['restored']} 张，残留 {len(still_left)} 个",
    )
    proj.close()
    shutil.rmtree(base, ignore_errors=True)

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
