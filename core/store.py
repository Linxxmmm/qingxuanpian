"""SQLite 数据层：照片表、归档日志、设置。

数据库默认放在照片根目录下的 `.xuanpian.db`，跟着照片文件夹走；
若该目录不可写，由 core.paths 决定退回到用户目录，这里只接收一个 dir。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from . import paths, scanner
from .const import bucket_of

DB_NAME = paths.DB_NAME

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    size        INTEGER DEFAULT 0,
    mtime       REAL DEFAULT 0,
    width       INTEGER DEFAULT 0,
    height      INTEGER DEFAULT 0,
    taken_at    REAL,
    score       INTEGER DEFAULT 0,
    flags       INTEGER DEFAULT 0,
    sharp       REAL DEFAULT 0,
    over_ratio  REAL DEFAULT 0,
    under_ratio REAL DEFAULT 0,
    group_id    INTEGER,
    dhash       TEXT,
    analyzed    INTEGER DEFAULT 0,
    present     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_id);
CREATE INDEX IF NOT EXISTS idx_photos_score ON photos(score);

CREATE TABLE IF NOT EXISTS archive_log (
    id      INTEGER PRIMARY KEY,
    ts      REAL,
    bucket  TEXT,
    dest    TEXT,
    mode    TEXT,
    count   INTEGER,
    detail  TEXT,
    undone  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

COLUMNS = (
    "id, path, name, size, mtime, width, height, taken_at, score, flags,"
    " sharp, over_ratio, under_ratio, group_id, dhash, analyzed, present"
)


class Store:
    def __init__(self, root: str | Path, data_dir: str | Path | None = None):
        self.root = Path(root)
        self.data_dir = Path(data_dir) if data_dir else self.root
        self.db_path = self.data_dir / DB_NAME
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._closed = False
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ 扫描
    def sync(self) -> dict:
        """把磁盘现状同步进库：新增、变更、消失。

        文件内容变了（mtime/size 不同）会把 analyzed 归零，让它重新分析，
        但保留已有评分——用户对这张照片的判断不该被文件变动抹掉。
        """
        found, skipped = scanner.scan_report(self.root)
        cur = self.conn.cursor()
        existing = {
            row["path"]: (row["id"], row["mtime"], row["size"], row["analyzed"])
            for row in cur.execute("SELECT id, path, mtime, size, analyzed FROM photos")
        }

        added = changed = removed = 0
        for rel, (mtime, size) in found.items():
            old = existing.pop(rel, None)
            name = rel.rsplit("/", 1)[-1]
            if old is None:
                # taken_at 先按文件修改时间兜底，EXIF 分析出来后再覆盖
                cur.execute(
                    "INSERT INTO photos (path, name, size, mtime, taken_at, present)"
                    " VALUES (?,?,?,?,?,1)",
                    (rel, name, size, mtime, mtime),
                )
                added += 1
            else:
                pid, old_mtime, old_size, analyzed = old
                if abs(old_mtime - mtime) > 1e-6 or old_size != size:
                    cur.execute(
                        "UPDATE photos SET mtime=?, size=?, analyzed=0 WHERE id=?",
                        (mtime, size, pid),
                    )
                    changed += 1
                elif not analyzed and old_mtime:
                    cur.execute("UPDATE photos SET present=1 WHERE id=?", (pid,))
                else:
                    cur.execute("UPDATE photos SET present=1 WHERE id=?", (pid,))

        for rel, (pid, _m, _s, _a) in existing.items():
            if (self.root / rel).exists():
                continue
            cur.execute("UPDATE photos SET present=0 WHERE id=?", (pid,))
            removed += 1

        self.conn.commit()
        return {
            "added": added,
            "changed": changed,
            "removed": removed,
            "total": len(found),
            "skipped": dict(skipped.most_common(8)),
            "skipped_total": sum(skipped.values()),
        }

    # ------------------------------------------------------------------ 分析
    def pending_analysis(self, limit: int = 512) -> list[dict]:
        rows = self.conn.execute(
            f"SELECT {COLUMNS} FROM photos WHERE present=1 AND analyzed=0 LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def save_analysis(self, pid: int, data: dict) -> None:
        self.conn.execute(
            "UPDATE photos SET width=?, height=?, sharp=?, over_ratio=?, under_ratio=?,"
            " flags=?, dhash=?, taken_at=COALESCE(?, taken_at), analyzed=1"
            " WHERE id=?",
            (
                data["width"],
                data["height"],
                data["sharp"],
                data["over_ratio"],
                data["under_ratio"],
                data["flags"],
                data["dhash"],
                data["taken_at"],
                pid,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ 查询
    def photos(self, bucket: str | None = None, flagged_only: bool = False,
               group_id: int | None = None, order: str = "path") -> list[dict]:
        sql = f"SELECT {COLUMNS} FROM photos WHERE present=1"
        args: list = []
        if bucket and bucket != "all":
            lo, hi = {
                "pick": (5, 5),
                "maybe": (3, 4),
                "reject": (1, 2),
                "none": (0, 0),
            }[bucket]
            sql += " AND score BETWEEN ? AND ?"
            args += [lo, hi]
        if flagged_only:
            sql += " AND flags != 0"
        if group_id is not None:
            sql += " AND group_id = ?"
            args.append(group_id)
        sql += f" ORDER BY {order if order in ('path','score','taken_at','sharp') else 'path'}"
        rows = [dict(r) for r in self.conn.execute(sql, args)]
        for row in rows:
            row["bucket"] = bucket_of(row["score"])
        return rows

    def counts(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM photos WHERE present=1").fetchone()[0]
        flagged = self.conn.execute(
            "SELECT COUNT(*) FROM photos WHERE present=1 AND flags != 0"
        ).fetchone()[0]
        rows = self.conn.execute(
            "SELECT score, COUNT(*) FROM photos WHERE present=1 GROUP BY score"
        ).fetchall()
        buckets = {"pick": 0, "maybe": 0, "reject": 0, "none": 0}
        for score, n in rows:
            buckets[bucket_of(score)] += n
        grouped = self.conn.execute(
            "SELECT COUNT(DISTINCT group_id) FROM photos WHERE present=1 AND group_id IS NOT NULL"
        ).fetchone()[0]
        return {"total": total, "flagged": flagged, "groups": grouped, **buckets}

    def by_id(self, pid: int) -> dict | None:
        row = self.conn.execute(
            f"SELECT {COLUMNS} FROM photos WHERE id=?", (pid,)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["bucket"] = bucket_of(item["score"])
        return item

    # ------------------------------------------------------------------ 评分
    def set_score(self, ids: list[int], score: int) -> None:
        if not ids:
            return
        self.conn.executemany(
            "UPDATE photos SET score=? WHERE id=?", [(score, i) for i in ids]
        )
        self.conn.commit()

    # ------------------------------------------------------------------ 分组
    def all_for_grouping(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, path, taken_at, dhash, sharp FROM photos"
            " WHERE present=1 AND dhash IS NOT NULL ORDER BY taken_at, path"
        )
        return [dict(r) for r in rows]

    def assign_groups(self, groups: list[list[int]]) -> int:
        """写入分组结果；少于 2 张的串不组。返回组的数量。"""
        self.conn.execute("UPDATE photos SET group_id=NULL")
        gid = 0
        for members in groups:
            if len(members) < 2:
                continue
            gid += 1
            self.conn.executemany(
                "UPDATE photos SET group_id=? WHERE id=?", [(gid, i) for i in members]
            )
        self.conn.commit()
        return gid

    def group_members(self, gid: int) -> list[dict]:
        rows = self.conn.execute(
            f"SELECT {COLUMNS} FROM photos WHERE group_id=? AND present=1"
            " ORDER BY sharp DESC",
            (gid,),
        )
        items = [dict(r) for r in rows]
        for it in items:
            it["bucket"] = bucket_of(it["score"])
        return items

    def group_list(self) -> list[dict]:
        """所有分组概览：每组一张代表图（最清晰的那张）+ 成员数。"""
        rows = self.conn.execute(
            "SELECT group_id, COUNT(*) AS n FROM photos"
            " WHERE present=1 AND group_id IS NOT NULL GROUP BY group_id ORDER BY group_id"
        ).fetchall()
        out = []
        for gid, n in rows:
            best = self.conn.execute(
                "SELECT id, path, score FROM photos WHERE group_id=? AND present=1"
                " ORDER BY sharp DESC LIMIT 1",
                (gid,),
            ).fetchone()
            if best:
                out.append(
                    {"group_id": gid, "count": n, "best_id": best["id"],
                     "best_path": best["path"], "best_score": best["score"]}
                )
        return out

    # ------------------------------------------------------------------ 归档日志
    def add_log(self, bucket: str, dest: str, mode: str, detail: list[dict]) -> int:
        cur = self.conn.execute(
            "INSERT INTO archive_log (ts, bucket, dest, mode, count, detail)"
            " VALUES (?,?,?,?,?,?)",
            (time.time(), bucket, dest, mode, len(detail), json.dumps(detail, ensure_ascii=False)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def logs(self, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM archive_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["detail"] = json.loads(item["detail"] or "[]")
            out.append(item)
        return out

    def mark_undone(self, log_id: int) -> None:
        self.conn.execute("UPDATE archive_log SET undone=1 WHERE id=?", (log_id,))
        self.conn.commit()

    def set_present(self, rel: str, present: bool) -> None:
        self.conn.execute(
            "UPDATE photos SET present=? WHERE path=?", (1 if present else 0, rel)
        )
        self.conn.commit()

    # ------------------------------------------------------------------ 设置
    def get_setting(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.conn.close()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    def ensure_open(self) -> None:
        """窗口关闭后仍有异步回调时，给出明确错误而不是难懂的 ProgrammingError。"""
        if self._closed:
            raise sqlite3.ProgrammingError(
                "数据库已经关闭（窗口关了之后还有后台任务在跑）"
            )
