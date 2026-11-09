"""核心层冒烟测试：不启动界面，把扫描 / 分析 / 分组 / 归档 / 撤销跑一遍。

    python tools/smoke.py                 # 用自带的 sample2 样片
    python tools/smoke.py D:\\照片\\某个目录  # 指定目录（会在该目录里归档再撤销）
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.const import flag_text  # noqa: E402
from core.project import quick_open  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}{(' — ' + detail) if detail else ''}")


def isolated_copy(source: Path) -> Path:
    """复制一份样片再跑，避免把归档记录写进用户自己的目录。"""
    dest = ROOT / "_smoketest"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".xuanpian*", "精选", "待定", "淘汰"))
    return dest


def main() -> int:
    if len(sys.argv) > 1:
        source = Path(sys.argv[1])
        if not source.is_dir():
            print(f"目录不存在：{source}")
            return 2
        target = isolated_copy(source)
    else:
        source = ROOT / "sample2"
        if not source.is_dir():
            print(f"样片目录不存在：{source}")
            return 2
        target = isolated_copy(source)

    print(f"样片目录：{target}\n")
    t0 = time.time()
    proj, stats = quick_open(target)
    elapsed = time.time() - t0

    counts = proj.counts()
    print(
        f"扫描 {stats['total']} 张（新增 {stats['added']}），"
        f"分析 {stats['analyzed']} 张，{stats['groups']} 组连拍，耗时 {elapsed:.2f}s\n"
    )

    check("扫描到照片", counts["total"] > 0, f"{counts['total']} 张")
    check("分析完成且没有待分析项", not proj.store.pending_analysis(), "0 张待分析")

    photos = proj.photos()
    analyzed = [p for p in photos if p["analyzed"] and p["width"] > 0]
    check("照片都有尺寸信息", len(analyzed) == counts["total"],
          f"{len(analyzed)}/{counts['total']}")

    flags = [(p["name"], flag_text(p["flags"])) for p in photos if p["flags"]]
    check("硬伤能被识别", bool(flags), "、".join(f"{n}→{t}" for n, t in flags[:4]) or "无")

    groups = proj.store.group_list()
    check("连拍能聚成组", bool(groups),
          "、".join(f"组{g['group_id']}({g['count']}张)" for g in groups[:3]) or "无")

    sharp_sorted = True
    for g in groups[:3]:
        members = proj.store.group_members(g["group_id"])
        values = [m["sharp"] or 0 for m in members]
        if values != sorted(values, reverse=True):
            sharp_sorted = False
    check("连拍组内按清晰度排序", sharp_sorted)

    # 归档 → 撤销
    pick_ids = [p["id"] for p in photos[:3]]
    proj.store.set_score(pick_ids, 5)
    proj.store.set_score([photos[3]["id"]], 2)
    expected_pick = proj.counts()["pick"]
    result = proj.archive("pick", mode="move")
    moved = list((target / "精选").glob("*.jpg")) if (target / "精选").exists() else []
    check("归档把文件搬进了「精选」", result["count"] == expected_pick and len(moved) == expected_pick,
          f"{len(moved)} 个文件")

    undone = proj.undo(result["log_id"])
    left = list((target / "精选").glob("*.jpg")) if (target / "精选").exists() else []
    check("撤销把文件搬回来了", undone["restored"] == expected_pick and not left,
          f"还原 {undone['restored']} 个，残留 {len(left)} 个")

    proj.close()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
