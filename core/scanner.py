"""目录扫描：递归收集照片文件（跳过缓存目录与隐藏目录）。"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Iterator

from .const import IMAGE_EXTS

# 这些目录里的东西不是照片，递归时直接跳过
SKIP_DIRS = {".xuanpian", ".xuanpian-cache", "__MACOSX", ".trash", "$RECYCLE.BIN"}


def iter_images(root: str | Path) -> Iterator[Path]:
    """递归遍历 root 下所有图片文件。"""
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and not d.startswith("~")
        ]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                yield Path(dirpath) / name


def scan_report(root: str | Path) -> tuple[dict[str, tuple[float, int]], "Counter[str]"]:
    """扫描目录，返回 ({相对路径: (mtime, size)}, 被忽略文件的扩展名统计)。

    第二项用来回答"我明明放了 500 张照片，怎么只认出 3 张"：把没被当成照片的
    文件按扩展名数出来，界面和日志里就能说清楚是哪些格式没进来。
    """
    root = Path(root)
    result: dict[str, tuple[float, int]] = {}
    skipped: Counter[str] = Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and not d.startswith("~")
        ]
        for name in filenames:
            if name.startswith(".xuanpian"):  # 我们自己的数据库/缓存，不算用户文件
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS:
                skipped[ext or "(无扩展名)"] += 1
                continue
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                # 权限/路径过长/云盘占位文件读不到——单独计数，别静默丢掉
                skipped["(无法访问)"] += 1
                continue
            rel = path.relative_to(root).as_posix()
            result[rel] = (st.st_mtime, st.st_size)
    return result, skipped


def scan(root: str | Path) -> dict[str, tuple[float, int]]:
    """扫描目录，返回 {相对路径: (mtime, size)}。

    相对路径以 root 为基准，正斜杠分隔，用于数据库比对，
    这样整个照片目录可以整体搬走而不丢打分。
    """
    return scan_report(root)[0]
