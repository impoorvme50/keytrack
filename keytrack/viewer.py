"""终端查看器：回看"今天（或指定某天）输入了什么"。"""

from __future__ import annotations

from datetime import datetime, date, timedelta

from . import storage, key_stats
from .layouts import norm_key


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _clean_preview(text: str, limit: int | None = None) -> str:
    """把不可见字符转成可读符号，方便终端展示。"""
    shown = text.replace("\n", " \u23ce ").replace("\t", " \u21e5 ")
    if limit is not None and len(shown) > limit:
        shown = shown[:limit] + " …"
    return shown


def _correction_stats(counts: list) -> tuple[int, float]:
    """改稿率：删除键（BackSpace/Delete，两套键名）占全部击键的比例。"""
    total = sum(r["count"] for r in counts)
    deleted = sum(
        r["count"] for r in counts if norm_key(r["key"]) == "backspace"
    )
    return deleted, (deleted / total if total else 0.0)


def _show_speed(minutes: list, counts: list | None = None, total_chars: int = 0) -> None:
    if not minutes:
        return
    per_min = [row["count"] for row in minutes]
    total = sum(per_min)
    active = len(per_min)
    peak = max(per_min)
    avg = total / active if active else 0
    print("-" * 60)
    print("输入节奏：")
    print(f"    活跃 {active} 分钟，共 {total} 次按键")
    if total_chars:
        cpm = total_chars / active if active else 0
        print(f"    上屏 {total_chars} 字，{cpm:.0f} 字/活跃分钟（中文 CPM 口径）")
    print(f"    平均 {avg:.0f} 击/分钟，峰值 {peak} 击/分钟")
    if counts:
        deleted, rate = _correction_stats(counts)
        if deleted:
            print(f"    改稿率 {rate*100:.1f}%（删除键 {deleted} 次——越低越一气呵成）")
    # 一个简易的每小时活跃度柱状
    by_hour: dict[str, int] = {}
    for row in minutes:
        hour = row["minute"][11:13]
        by_hour[hour] = by_hour.get(hour, 0) + row["count"]
    hi = max(by_hour.values())
    print("    按小时分布：")
    for hour in sorted(by_hour):
        n = by_hour[hour]
        bar = "█" * max(1, round(n / hi * 24))
        print(f"      {hour}:00  {bar} {n}")
    print()


def show_day(day: date, db_path: str = storage.DEFAULT_DB_PATH, full: bool = False) -> None:
    with storage.connect(db_path) as conn:
        segments = storage.segments_for_day(conn, day)
        counts = storage.key_counts_for_day(conn, day)
        minutes = storage.key_minutes_for_day(conn, day)
        quality = key_stats.quality(conn, day.isoformat())

    title = day.strftime("%Y-%m-%d (%a)")
    print(f"\n===== 今天输入了什么 · {title} =====\n")

    if not segments:
        print("（这一天还没有记录。先运行 `kbd record` 开始采集。）\n")
    else:
        total_keys = sum(s["key_count"] for s in segments)
        by_app: dict[str, int] = {}
        for s in segments:
            by_app[s["app"]] = by_app.get(s["app"], 0) + s["key_count"]

        print(f"共 {len(segments)} 段输入，{total_keys} 次按键。")
        top_apps = sorted(by_app.items(), key=lambda kv: kv[1], reverse=True)
        print("按应用分布：", "  ".join(f"{a}({n})" for a, n in top_apps))
        print("-" * 60)

        for s in segments:
            when = f"{_fmt_time(s['start_ts'])}–{_fmt_time(s['end_ts'])}"
            head = f"[{when}] {s['app']}  ({s['key_count']} keys)"
            print(head)
            body = _clean_preview(s["text"], None if full else 200)
            print(f"    {body}")
            print()

    print(quality["scope"])
    if quality["reliable"]:
        _show_speed(minutes, counts, total_chars=sum(s["key_count"] for s in segments))
    else:
        print(quality["message"])

    if counts:
        print("-" * 60)
        print("按键频率 Top 10（哪个键按得最多）：")
        for row in counts[:10]:
            key = row["key"]
            label = {" ": "space", "\n": "enter", "\t": "tab"}.get(key, key)
            print(f"    {label:<12} {row['count']}")
        print()


def parse_day(s: str | None) -> date:
    if not s or s == "today":
        return datetime.now().date()
    if s == "yesterday":
        return datetime.now().date() - timedelta(days=1)
    return datetime.strptime(s, "%Y-%m-%d").date()
