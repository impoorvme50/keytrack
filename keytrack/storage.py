"""本地 SQLite 存储层。

两张表：
- segments: 重建后的输入片段（app / 时间窗口 / 文本内容 / 按键数）。
- key_counts: 按天聚合的单键频率（保留"哪个键按得最多"的老功能）。
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, date
from typing import Iterator


DEFAULT_DB_PATH = os.path.expanduser("~/.keytrack/keytrack.db")


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)


@contextmanager
def connect(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    _ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # WAL 允许采集写入时继续查询。模式保存在数据库里，已启用时不必
        # 每次连接都重新设置；旧库只读或暂时被锁住时保留原模式。
        if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError as exc:
                code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                if code not in (
                    sqlite3.SQLITE_READONLY,
                    sqlite3.SQLITE_BUSY,
                    sqlite3.SQLITE_LOCKED,
                ):
                    raise
        _init_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            app         TEXT    NOT NULL,
            window      TEXT,
            start_ts    REAL    NOT NULL,
            end_ts      REAL    NOT NULL,
            text        TEXT    NOT NULL,
            key_count   INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_segments_start ON segments(start_ts);

        CREATE TABLE IF NOT EXISTS key_counts (
            day    TEXT    NOT NULL,
            key    TEXT    NOT NULL,
            count  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, key)
        );

        -- 每分钟按键数，用于计算打字速度/节奏（minute 形如 2026-07-28T10:26）
        CREATE TABLE IF NOT EXISTS key_minutes (
            minute TEXT    NOT NULL PRIMARY KEY,
            count  INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def insert_segment(
    conn: sqlite3.Connection,
    app: str,
    window: str | None,
    start_ts: float,
    end_ts: float,
    text: str,
    key_count: int,
) -> None:
    conn.execute(
        "INSERT INTO segments (app, window, start_ts, end_ts, text, key_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (app, window, start_ts, end_ts, text, key_count),
    )
    conn.commit()


def bump_key_counts(conn: sqlite3.Connection, day: str, counts: dict[str, int]) -> None:
    if not counts:
        return
    for key, n in counts.items():
        conn.execute(
            "INSERT INTO key_counts (day, key, count) VALUES (?, ?, ?) "
            "ON CONFLICT(day, key) DO UPDATE SET count = count + excluded.count",
            (day, key, n),
        )
    conn.commit()


def bump_key_minutes(conn: sqlite3.Connection, minutes: dict[str, int]) -> None:
    if not minutes:
        return
    for minute, n in minutes.items():
        conn.execute(
            "INSERT INTO key_minutes (minute, count) VALUES (?, ?) "
            "ON CONFLICT(minute) DO UPDATE SET count = count + excluded.count",
            (minute, n),
        )
    conn.commit()


def key_minutes_for_day(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT minute, count FROM key_minutes WHERE minute LIKE ? ORDER BY minute",
        (day.isoformat() + "T%",),
    )
    return cur.fetchall()


def _day_bounds(day: date) -> tuple[float, float]:
    start = datetime(day.year, day.month, day.day).timestamp()
    end = start + 86400
    return start, end


def segments_for_day(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    start, end = _day_bounds(day)
    cur = conn.execute(
        "SELECT * FROM segments WHERE start_ts >= ? AND start_ts < ? ORDER BY start_ts",
        (start, end),
    )
    return cur.fetchall()


def key_counts_for_day(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT key, count FROM key_counts WHERE day = ? ORDER BY count DESC",
        (day.isoformat(),),
    )
    return cur.fetchall()
