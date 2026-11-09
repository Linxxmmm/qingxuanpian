"""归档：把照片按分数搬进「精选 / 待定 / 淘汰」子文件夹，并且可以撤销。

设计原则（沿用产品文档与开源项目的共识）：
- 只搬运，不删除。任何一次归档都能一键撤销。
- 默认 move；需要留底时选 copy。
- 目标重名自动加后缀，绝不覆盖已有文件。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from .const import BUCKET_DIRNAME

# 缩略图线程/看图解码可能正开着这张图，Windows 下会报 WinError 32。
# 短暂重试几次基本都能过，比直接跳过更符合用户预期。
_RETRY_TIMES = 6
_RETRY_WAIT = 0.15


def _transfer(src: Path, target: Path, mode: str) -> None:
    """搬或复制，遇到"文件被占用"重试。"""
    last: OSError | None = None
    for attempt in range(_RETRY_TIMES):
        try:
            if mode == "copy":
                shutil.copy2(src, target)
            else:
                shutil.move(str(src), str(target))
            return
        except OSError as exc:
            last = exc
            if getattr(exc, "winerror", None) != 32 or attempt == _RETRY_TIMES - 1:
                raise
            time.sleep(_RETRY_WAIT)
    if last:
        raise last


def _unique_target(dest_dir: Path, name: str) -> Path:
    """目标已存在时追加 (1)(2)…，永不覆盖。"""
    target = dest_dir / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def plan(store, bucket: str) -> list[dict]:
    """列出该分档下待归档的照片；未评分（0 星）不参与归档。"""
    return store.photos(bucket=bucket)


def plan_all(store) -> dict[str, list[dict]]:
    """列出所有可归档分档的照片：{"pick": [...], "maybe": [...], "reject": [...]}。"""
    return {bucket: plan(store, bucket) for bucket in BUCKET_DIRNAME}


def _normalize_buckets(bucket) -> list[str]:
    if isinstance(bucket, str):
        return [bucket]
    return [b for b in bucket if b in BUCKET_DIRNAME]


def execute(store, bucket, mode: str = "move") -> dict:
    """执行归档，返回 {count, log_id, dest, skipped, buckets}。

    bucket 既可以是单个分档名，也可以是分档列表——"一键全部归档"就是把
    精选 / 待定 / 淘汰 一起传进来，只写一条日志，撤销时一起回来。
    """
    buckets = _normalize_buckets(bucket)
    if not buckets:
        raise ValueError(f"不可归档的分档：{bucket}")

    photos: list[tuple[str, dict]] = []
    for name in buckets:
        photos.extend((name, photo) for photo in plan(store, name))
    if not photos:
        return {"count": 0, "log_id": None, "dest": "", "skipped": 0, "buckets": buckets}

    detail: list[dict] = []
    skipped = 0
    errors: list[str] = []
    dests: list[str] = []
    for name, photo in photos:
        dest_dir = store.root / BUCKET_DIRNAME[name]
        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest_dir.name not in dests:
            dests.append(dest_dir.name)

        src = store.root / photo["path"]
        if not src.exists():
            skipped += 1
            errors.append(f"{photo['path']}：原图不在了")
            continue
        target = _unique_target(dest_dir, src.name)
        try:
            _transfer(src, target, mode)
        except OSError as exc:
            skipped += 1
            errors.append(f"{photo['path']}：{exc}")
            continue

        detail.append(
            {
                "rel": photo["path"],
                "dst": target.relative_to(store.root).as_posix(),
                "mode": mode,
                "bucket": name,
            }
        )
        if mode != "copy":
            store.set_present(photo["path"], False)

    log_bucket = buckets[0] if len(buckets) == 1 else "all"
    log_id = store.add_log(log_bucket, "、".join(dests), mode, detail) if detail else None
    return {
        "count": len(detail),
        "log_id": log_id,
        "dest": "、".join(str(store.root / d) for d in dests),
        "skipped": skipped,
        "errors": errors[:10],
        "buckets": buckets,
    }


def undo(store, log_id: int) -> dict:
    """撤销一次归档：move 的搬回原位，copy 的删掉副本。"""
    logs = {log["id"]: log for log in store.logs(limit=200)}
    log = logs.get(log_id)
    if not log:
        return {"restored": 0, "error": "找不到这条归档记录"}
    if log["undone"]:
        return {"restored": 0, "error": "这条记录已经撤销过了"}

    restored = 0
    for item in log["detail"]:
        src = store.root / item["rel"]
        dst = store.root / item["dst"]
        try:
            if item["mode"] == "copy":
                if dst.exists():
                    dst.unlink()
                restored += 1
            elif dst.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                if src.exists():
                    src = _unique_target(src.parent, src.name)
                _transfer(dst, src, "move")
                store.set_present(item["rel"], True)
                restored += 1
        except OSError:
            continue

    store.mark_undone(log_id)
    return {"restored": restored}
