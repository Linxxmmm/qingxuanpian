"""Project：把扫描 / 分析 / 分组 / 归档串成一个对象，UI 只跟它打交道。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from . import analyze, archive, burst, paths
from . import const
from .const import BUCKET_DIRNAME
from .store import Store
from .thumbs import ThumbCache


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"不是一个文件夹：{self.root}")
        self.data_dir, self.mode = paths.choose(self.root)
        try:
            self.store = Store(self.root, self.data_dir)
        except Exception as exc:
            raise RuntimeError(
                f"数据库无法建立（{self.data_dir / paths.DB_NAME}）：{exc}"
            ) from exc
        self.thumbs = ThumbCache(self.root, self.data_dir / paths.CACHE_DIR)

    @property
    def portable(self) -> bool:
        """打分记录是不是就存在照片文件夹里。"""
        return self.mode == "folder"

    # ---------------------------------------------------------------- 打开
    def sync(self, **_ignored) -> dict:
        """同步磁盘现状。返回 {added, changed, removed, total}。"""
        return self.store.sync()

    # ---------------------------------------------------------------- 分析
    def analyze_pending(
        self,
        progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        batch: int = 64,
    ) -> int:
        """分析所有未分析的照片。返回实际处理张数。"""
        done = 0
        while True:
            if should_stop and should_stop():
                break
            rows = self.store.pending_analysis(batch)
            if not rows:
                break
            for row in rows:
                if should_stop and should_stop():
                    break
                data = analyze.analyze(self.root / row["path"])
                if data is not None:
                    self.store.save_analysis(row["id"], data)
                else:
                    # 读不出来的（损坏/不支持的 HEIC）标记为已分析，别反复重试
                    self.store.save_analysis(
                        row["id"],
                        {
                            "width": 0, "height": 0, "sharp": 0.0,
                            "over_ratio": 0.0, "under_ratio": 0.0,
                            "flags": 0, "dhash": None, "taken_at": None,
                        },
                    )
                done += 1
                if progress:
                    progress(done, len(rows))
        return done

    def analyze_all(
        self,
        progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        **_ignored,
    ) -> int:
        """把库里所有待分析照片处理完，进度按总数上报。"""
        rows = self.store.pending_analysis(1_000_000)
        total = len(rows)
        done = 0
        for row in rows:
            if should_stop and should_stop():
                break
            data = analyze.analyze(self.root / row["path"])
            if data is None:
                data = {
                    "width": 0, "height": 0, "sharp": 0.0,
                    "over_ratio": 0.0, "under_ratio": 0.0,
                    "flags": 0, "dhash": None, "taken_at": None,
                }
            self.store.save_analysis(row["id"], data)
            done += 1
            if progress:
                progress(done, total)
        return done

    def analyze_pending_until_empty(self, progress=None, should_stop=None) -> int:
        """反复调用 analyze_pending，直到库里没有待分析项。"""
        total = 0
        while True:
            if should_stop and should_stop():
                break
            rows = self.store.pending_analysis(1)
            if not rows:
                break
            total += self.analyze_pending(progress=progress, should_stop=should_stop)
        return total

    # ---------------------------------------------------------------- 分组
    def regroup(self, **_ignored) -> int:
        """重算连拍分组，返回组数。照片量小时很快（1000 张约 1 秒）。"""
        photos = self.store.all_for_grouping()
        groups = burst.build_groups(photos)
        return self.store.assign_groups(groups)

    # ---------------------------------------------------------------- 归档
    def archive(self, bucket, mode: str = "move", **_ignored) -> dict:
        """归档一个分档，或一次归档多个分档（"一键全部归档"）。"""
        return archive.execute(self.store, bucket, mode)

    def archive_plan(self) -> dict[str, list[dict]]:
        return archive.plan_all(self.store)

    def undo(self, log_id: int) -> dict:
        return archive.undo(self.store, log_id)

    # ---------------------------------------------------------------- 查询
    def burst_stats(self) -> dict:
        """给「没识别到连拍」的提示用：照片数、带时间的数量、最接近的一对距离、时间相邻的对数。"""
        rows = self.store.all_for_grouping()
        timed = sum(1 for r in rows if r.get("taken_at"))
        closest = 64
        in_window = 0
        for a, b in zip(rows, rows[1:]):
            try:
                gap = abs(float(b["taken_at"] or 0) - float(a["taken_at"] or 0))
            except (TypeError, ValueError):
                gap = 0.0
            if gap <= const.BURST_TIME_GAP:
                in_window += 1
            try:
                distance = analyze.hamming(int(a["dhash"]), int(b["dhash"]))
            except (TypeError, ValueError):
                continue
            closest = min(closest, distance)
        return {
            "total": len(self.store.photos()),
            "timed": timed,
            "closest": closest,
            "in_window": in_window,
        }

    def photos(self, **kwargs) -> list[dict]:
        return self.store.photos(**kwargs)

    def counts(self) -> dict:
        return self.store.counts()

    def logs(self, limit: int = 30) -> list[dict]:
        return self.store.logs(limit)

    def close(self) -> None:
        if getattr(self, "store", None):
            self.store.close()


def quick_open(root: str | Path, do_group: bool = True) -> tuple[Project, dict]:
    """一步到位：扫描 + 分析 + 分组。给脚本和首启流程用。"""
    proj = Project(root)
    stats = proj.sync()
    started = time.time()
    analyzed = proj.analyze_pending_until_empty()
    stats["analyzed"] = analyzed
    stats["analyze_seconds"] = round(time.time() - started, 2)
    if do_group:
        stats["groups"] = proj.regroup()
    return proj, stats
