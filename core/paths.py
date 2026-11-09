"""决定数据存哪儿。

默认把数据库和缩略图缓存放在照片文件夹里（整个目录拷到别的电脑上，打分也跟着走）。
但如果这个文件夹不可写（只读盘、受控文件夹、网络盘、权限不足……），
就依次退回：用户目录 `%LOCALAPPDATA%\\轻选片\\libraries\\<目录名>-<路径哈希>` → 系统临时目录。
三条路都试过还不行，才报错。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

APP_NAME = "轻选片"
DB_NAME = ".xuanpian.db"
CACHE_DIR = ".xuanpian-cache"

_BAD_CHARS = '\\/:*?"<>|'


def _directory_key(root: Path) -> str:
    return hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:16]


def _safe_name(root: Path) -> str:
    name = "".join(c for c in (root.name or "root") if c not in _BAD_CHARS).strip()
    return (name or "root")[:40]


def appdata_root() -> Path | None:
    """用户数据目录；拿不到就返回 None，由上层继续退。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        return None
    root = Path(base) / APP_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    return root


def writable(directory: Path) -> bool:
    """真的写一个探针文件来判断，比 os.access 可靠（它不看 ACL）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".xp-write-test"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except Exception:
        return False


def library_dir(root: str | Path) -> Path | None:
    """退回用的按目录隔离的数据目录；用户目录不可用时返回 None。"""
    root = Path(root).resolve()
    base = appdata_root()
    if base is None:
        return None
    return base / "libraries" / f"{_safe_name(root)}-{_directory_key(root)}"


def temp_dir(root: str | Path) -> Path:
    root = Path(root).resolve()
    return Path(tempfile.gettempdir()) / APP_NAME / f"{_safe_name(root)}-{_directory_key(root)}"


def choose(root: str | Path) -> tuple[Path, str]:
    """返回 (数据目录, 模式)。

    模式：`folder` = 存在照片文件夹里；`appdata` = 用户目录；`temp` = 临时目录（重启后仍在，但可能被清理）。
    """
    root = Path(root).resolve()

    if writable(root) and writable(root / CACHE_DIR):
        return root, "folder"

    lib = library_dir(root)
    if lib is not None and writable(lib):
        return lib, "appdata"

    tmp = temp_dir(root)
    if writable(tmp):
        return tmp, "temp"

    raise RuntimeError(
        "找不到可写的位置存放打分记录：照片目录、用户目录、临时目录都写不进去。"
        "请把照片文件夹（或整个程序）放到有写权限的位置再试。"
    )


def log_path() -> Path | None:
    base = appdata_root()
    if base is None:
        return None
    d = base / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    return d / "app.log"
