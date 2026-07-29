"""周报：最近 7 天的产出与节奏汇总，可选推送到 Lark 群机器人。

隐私口径：周报只含聚合数字（字数/击键/改稿率/应用分布），
绝不包含任何输入正文——要推送的内容可以放心发到第三方。
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta

from . import query, storage


def week_report(end: date | None = None, days: int = 7, db_path: str = storage.DEFAULT_DB_PATH) -> dict:
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    per_day = []
    apps: dict[str, int] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        rep = query.day_report(d, db_path=db_path)
        per_day.append({
            "day": rep["day"],
            "chars": rep["total_chars"],
            "cpm": rep["cpm"],
            "keys": rep["keys"]["total_keys"],
            "active_minutes": rep["keys"]["active_minutes"],
            "correction_rate": rep["keys"]["correction_rate"],
        })
        for app, n in rep["apps"].items():
            apps[app] = apps.get(app, 0) + n

    total_chars = sum(d["chars"] for d in per_day)
    total_keys = sum(d["keys"] for d in per_day)
    total_active = sum(d["active_minutes"] for d in per_day)
    best = max(per_day, key=lambda d: d["chars"]) if per_day else None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": per_day,
        "total_chars": total_chars,
        "total_keys": total_keys,
        "active_minutes": total_active,
        "avg_cpm": round(total_chars / total_active, 1) if total_active else 0,
        "best_day": best,
        "apps": dict(sorted(apps.items(), key=lambda kv: kv[1], reverse=True)[:10]),
    }


def format_text(rep: dict) -> str:
    lines = [
        f"📊 keytrack 周报（{rep['start']} ~ {rep['end']}）",
        f"上屏 {rep['total_chars']} 字 · 击键 {rep['total_keys']} 次 · 活跃 {rep['active_minutes']} 分钟",
        f"平均速度 {rep['avg_cpm']} 字/活跃分钟",
    ]
    if rep["best_day"] and rep["best_day"]["chars"]:
        b = rep["best_day"]
        lines.append(f"巅峰日：{b['day']}（{b['chars']} 字，{b['cpm']} 字/分钟）")
    if rep["apps"]:
        top = "  ".join(f"{a}({n}字)" for a, n in list(rep["apps"].items())[:5])
        lines.append(f"主战场：{top}")
    daily = "  ".join(
        f"{d['day'][5:]}:{d['chars']}" for d in rep["days"] if d["chars"]
    )
    if daily:
        lines.append(f"每日字数：{daily}")
    return "\n".join(lines)


def show(rep: dict) -> None:
    print(f"\n===== keytrack 周报 · {rep['start']} ~ {rep['end']} =====\n")
    print(f"上屏 {rep['total_chars']} 字 · 击键 {rep['total_keys']} 次 · 活跃 {rep['active_minutes']} 分钟")
    print(f"平均速度 {rep['avg_cpm']} 字/活跃分钟")
    if rep["best_day"] and rep["best_day"]["chars"]:
        b = rep["best_day"]
        print(f"巅峰日：{b['day']}（{b['chars']} 字，{b['cpm']} 字/分钟）")
    if rep["apps"]:
        top = "  ".join(f"{a}({n}字)" for a, n in list(rep["apps"].items())[:5])
        print(f"主战场：{top}")
    print()
    print(f"{'日期':<12}{'字数':>6}{'击键':>8}{'活跃分':>7}{'CPM':>6}{'改稿率':>8}")
    for d in rep["days"]:
        print(
            f"{d['day']:<12}{d['chars']:>6}{d['keys']:>8}{d['active_minutes']:>7}"
            f"{d['cpm']:>6}{d['correction_rate']*100:>7.1f}%"
        )
    print()


def push_lark(webhook: str, text: str, timeout: int = 10) -> bool:
    """推送到 Lark 自定义机器人 webhook（只发聚合数字文本）。"""
    payload = json.dumps(
        {"msg_type": "text", "content": {"text": text}}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("code") == 0 or body.get("StatusCode") == 0
    except Exception as exc:
        print("推送失败：", exc)
        return False
