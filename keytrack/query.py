"""keytrack 查询接口：给网页看板 / Swift 状态栏 / 脚本用的结构化数据。

三层用法：
1. Python API：`from keytrack import query; query.day_report(date.today())`
2. CLI JSON：`kbd today --json` / `kbd show 2026-07-28 --json`
3. 直接读 SQLite（Swift 推荐 GRDB / SQLite.swift）：表结构见 docs/SCHEMA.md

所有函数只读不改；时间戳都是 Unix 秒（本地时区）。
"""

from __future__ import annotations

from datetime import datetime, date

from . import storage


def segments_for_day(day: date, db_path: str = storage.DEFAULT_DB_PATH) -> list[dict]:
    """某天的输入片段，按开始时间排序。"""
    with storage.connect(db_path) as conn:
        rows = storage.segments_for_day(conn, day)
        return [
            {
                "app": r["app"],
                "window": r["window"],
                "start": r["start_ts"],
                "end": r["end_ts"],
                "text": r["text"],
                "chars": r["key_count"],
            }
            for r in rows
        ]


def key_stats_for_day(day: date, db_path: str = storage.DEFAULT_DB_PATH) -> dict:
    """某天的操作层指标：总量、节奏、按小时分布、按键频率、改稿率。"""
    with storage.connect(db_path) as conn:
        minutes = storage.key_minutes_for_day(conn, day)
        counts = storage.key_counts_for_day(conn, day)

    per_minute = {r["minute"]: r["count"] for r in minutes}
    total = sum(per_minute.values())
    active = len(per_minute)
    by_hour: dict[str, int] = {}
    for minute, n in per_minute.items():
        hour = minute[11:13]
        by_hour[hour] = by_hour.get(hour, 0) + n

    deleted = sum(
        r["count"] for r in counts if r["key"].lower() in ("backspace", "delete")
    )
    counted = sum(r["count"] for r in counts)  # key_counts 表总量（与 minutes 口径略异）
    return {
        "total_keys": total,
        "active_minutes": active,
        "avg_kpm": round(total / active, 1) if active else 0,
        "peak_kpm": max(per_minute.values()) if per_minute else 0,
        "by_hour": {h: by_hour[h] for h in sorted(by_hour)},
        "per_minute": per_minute,
        "key_frequency": {r["key"]: r["count"] for r in counts},
        "deleted_keys": deleted,
        "correction_rate": round(deleted / counted, 4) if counted else 0,
    }


def day_report(day: date, db_path: str = storage.DEFAULT_DB_PATH) -> dict:
    """一天的完整报告：片段 + 应用分布 + 操作指标。"""
    segments = segments_for_day(day, db_path)
    by_app: dict[str, int] = {}
    for s in segments:
        by_app[s["app"]] = by_app.get(s["app"], 0) + s["chars"]
    keys = key_stats_for_day(day, db_path)
    total_chars = sum(s["chars"] for s in segments)
    active = keys["active_minutes"]
    return {
        "day": day.isoformat(),
        "segments": segments,
        "segment_count": len(segments),
        "total_chars": total_chars,
        "cpm": round(total_chars / active, 1) if active else 0,  # 上屏字/活跃分钟
        "apps": dict(sorted(by_app.items(), key=lambda kv: kv[1], reverse=True)),
        "keys": keys,
    }


def available_days(db_path: str = storage.DEFAULT_DB_PATH) -> list[str]:
    """库里有数据的所有日期（ segments 与按键表的并集），升序。"""
    with storage.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d FROM (
                SELECT date(start_ts, 'unixepoch', 'localtime') AS d FROM segments
                UNION
                SELECT day AS d FROM key_counts
                UNION
                SELECT substr(minute, 1, 10) AS d FROM key_minutes
            ) ORDER BY d
            """
        ).fetchall()
    return [r[0] for r in rows]
