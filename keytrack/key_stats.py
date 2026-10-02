"""Read-only provenance checks for Rime-observed key aggregates."""
from .layouts import norm_key

SCOPE = "仅统计经过鼠须管的按键；不包含其他输入法、粘贴或安全输入。组合键按主键计一次。"


def quality(conn, day=None, counts=None):
    condition, args = (" WHERE day=?", (day,)) if day else ("", ())
    if counts is None:
        counts = dict(conn.execute("SELECT key,SUM(count) FROM key_counts" + condition + " GROUP BY key", args))
    total = sum(counts.values())
    condition, args = (" WHERE minute LIKE ?", (day + "T%",)) if day else ("", ())
    minutes = dict(conn.execute("SELECT minute,count FROM key_minutes" + condition, args))
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='key_capture_minutes'").fetchone()
    verified = dict(conn.execute("SELECT minute,count FROM key_capture_minutes" + condition, args)) if exists else {}
    first = conn.execute("SELECT MIN(minute) FROM key_capture_minutes WHERE count>0").fetchone()[0] if exists else None
    reliable = total > 0 and sum(minutes.values()) == total and minutes == verified
    status = "verified" if reliable else "mixed" if sum(verified.values()) else "legacy" if total else "empty"
    messages = {
        "verified": "按键采集已校验；手指分布按 ANSI 标准指法估算，不代表实际手指动作。",
        "mixed": "当天包含修复前后的按键记录，统计不完整；暂不计算速度、活跃时间、退格占比和手指百分比。",
        "legacy": "历史按键记录可能漏采字母和空格，统计不完整；暂不计算速度、活跃时间、退格占比和手指百分比。",
        "empty": "这一天还没有按键记录。",
    }
    mapped = sum(n for k, n in counts.items() if norm_key(k))
    return {"status": status, "reliable": reliable, "message": messages[status], "scope": SCOPE,
            "first_verified_minute": first, "mapped_keys": mapped, "unmapped_keys": total - mapped}
