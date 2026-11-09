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
from .const import BUCKET_DIRNAME, bucket_of

DB_NAME = paths.DB_NAME

# 归档文件夹名 → 猜一个分数（只用于补回老数据里没记过的照片）
_BUCKET_SCORE = {BUCKET_DIRNAME[key]: score for key, score in
                 (("pick", 5), ("maybe", 4), ("reject", 1))}


def inferred_score(rel: str) -> int:
    """照片躺在「精选 / 待定 / 淘汰」里但库里没记录时，按文件夹猜分数。"""
    head = rel.split("/", 1)[0]
    return _BUCKET_SCORE.get(head, 0)

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
    dhash       TEXT,
    analyzed    INTEGER DEFAULT 0,
    present     INTEGER DEFAULT 1
);
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

-- 打分记忆：按「文件名 + 大小 + 修改时间」记指纹，文件被归档搬进子文件夹
-- （路径变了）之后重新扫描还能把分数找回来。
CREATE TABLE IF NOT EXISTS score_memory (
    key   TEXT PRIMARY KEY,
    name  TEXT,
    score INTEGER,
    ts    REAL
);
"""

COLUMNS = (
    "id, path, name, size, mtime, width, height, taken_at, score, flags,"
    " sharp, over_ratio, under_ratio, dhash, analyzed, present"
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
    def _memory_key(self, name: str, size: int, mtime: float) -> str:
        return f"{name}|{int(size)}|{int(round(mtime))}"

    def _remember(self, rows) -> int:
        """把照片当前的分数写进打分记忆，返回写入条数。"""
        now = time.time()
        made = 0
        for row in rows:
            if not row["score"]:
                continue
            key = self._memory_key(row["name"], row["size"], row["mtime"] or 0)
            self.conn.execute(
                "INSERT INTO score_memory (key, name, score, ts) VALUES (?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET score=excluded.score, ts=excluded.ts",
                (key, row["name"], row["score"], now),
            )
            made += 1
        return made

    def sync(self) -> dict:
        """把磁盘现状同步进库：新增、变更、消失。

        文件内容变了（mtime/size 不同）会把 analyzed 归零，让它重新分析，
        但保留已有评分——用户对这张照片的判断不该被文件变动抹掉。

        照片被归档搬到「精选 / 待定 / 淘汰」之后路径会变，所以新增行时还会
        查一遍打分记忆（文件名+大小+修改时间），把分数接回来。
        """
        found, skipped = scanner.scan_report(self.root)
        cur = self.conn.cursor()
        existing = {
            row["path"]: (row["id"], row["mtime"], row["size"], row["analyzed"])
            for row in cur.execute("SELECT id, path, mtime, size, analyzed FROM photos")
        }
        memory = {
            row["key"]: row["score"]
            for row in cur.execute("SELECT key, score FROM score_memory")
        }

        added = changed = removed = restored = 0
        for rel, (mtime, size) in found.items():
            old = existing.pop(rel, None)
            name = rel.rsplit("/", 1)[-1]
            if old is None:
                # taken_at 先按文件修改时间兜底，EXIF 分析出来后再覆盖
                score = memory.get(self._memory_key(name, size, mtime), 0)
                if not score:
                    # 没有记忆时按所在的归档文件夹猜一个（老版本归档的照片靠这条）
                    score = inferred_score(rel)
                if score:
                    restored += 1
                cur.execute(
                    "INSERT INTO photos (path, name, size, mtime, taken_at, score, present)"
                    " VALUES (?,?,?,?,?,?,1)",
                    (rel, name, size, mtime, mtime, score),
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
            "restored": restored,
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
               order: str = "path") -> list[dict]:
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
        return {"total": total, "flagged": flagged, **buckets}

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
        # 星级只有 1–5 五档：0 不是分数，而是「还没评」的初始状态
        score = max(1, min(5, int(score)))
        self.conn.executemany(
            "UPDATE photos SET score=? WHERE id=?", [(score, i) for i in ids]
        )
        rows = self.conn.execute(
            "SELECT name, size, mtime, score FROM photos WHERE id IN (%s)"
            % ",".join("?" * len(ids)),
            list(ids),
        ).fetchall()
        self._remember(rows)
        self.conn.commit()

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
