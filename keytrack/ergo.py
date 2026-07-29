"""人体工学分析：手/指负载均衡 + 按键熵。

回答两个问题：
1. 我的左右手、各手指负载均衡吗？（哪根手指在加班）
2. 我的按键分布有多「匀」？（熵越接近上限，分布越均匀；
   全拼用户可以拿这个数据和双拼的理论值对比，决定要不要换方案）

数据来自 key_counts 表，布局与手指映射见 layouts.py。
"""

from __future__ import annotations

import math
from datetime import date

from . import storage
from .layouts import ANSI_ROWS, FINGER_NAMES, LEFT_FINGERS, norm_key

_KEY_FINGER = {k: f for row in ANSI_ROWS for k, _l, _w, f in row}
N_PHYSICAL_KEYS = len(_KEY_FINGER)


def _entropy(counts: list[int], slots: int) -> float:
    """归一化 Shannon 熵，0（全砸在一个上）~ 1（完全均匀）。"""
    total = sum(counts)
    if total <= 0 or slots <= 1:
        return 0.0
    h = -sum((c / total) * math.log2(c / total) for c in counts if c > 0)
    return h / math.log2(slots)


def analyze(day: date | None = None, db_path: str = storage.DEFAULT_DB_PATH) -> dict:
    with storage.connect(db_path) as conn:
        if day is None:
            rows = conn.execute(
                "SELECT key, SUM(count) AS c FROM key_counts GROUP BY key"
            ).fetchall()
        else:
            rows = storage.key_counts_for_day(conn, day)

    per_key: dict[str, int] = {}
    for r in rows:
        k = norm_key(r["key"])
        if k:
            per_key[k] = per_key.get(k, 0) + int(r["c"] if day is None else r["count"])

    total = sum(per_key.values())
    per_finger: dict[str, int] = {}
    for k, n in per_key.items():
        f = _KEY_FINGER[k]
        per_finger[f] = per_finger.get(f, 0) + n
    left = sum(n for f, n in per_finger.items() if f in LEFT_FINGERS)
    right = sum(n for f, n in per_finger.items() if f not in LEFT_FINGERS and f != "th")
    thumb = per_finger.get("th", 0)

    return {
        "total": total,
        "per_key": per_key,
        "per_finger": per_finger,
        "left": left,
        "right": right,
        "thumb": thumb,
        "key_entropy": _entropy(list(per_key.values()), N_PHYSICAL_KEYS),
        "finger_entropy": _entropy(list(per_finger.values()), 9),  # 8 手指 + 拇指
        "hand_entropy": _entropy([left, right], 2),
    }


def show(day: date | None = None, db_path: str = storage.DEFAULT_DB_PATH) -> None:
    r = analyze(day, db_path)
    title = day.isoformat() if day else "累计"
    print(f"\n===== 手指负载与均衡性 · {title} =====\n")
    if not r["total"]:
        print("（没有数据）\n")
        return
    print(f"共 {r['total']} 次按键（只计布局内的物理键）")
    hand_total = r["left"] + r["right"] + r["thumb"]
    print(f"左手 {r['left']/hand_total*100:.1f}%  右手 {r['right']/hand_total*100:.1f}%  拇指(空格) {r['thumb']/hand_total*100:.1f}%")
    print("-" * 56)
    order = ["lp", "lr", "lm", "li", "ri", "rm", "rr", "rp", "th"]
    hi = max(r["per_finger"].values()) if r["per_finger"] else 1
    for f in order:
        n = r["per_finger"].get(f, 0)
        bar = "█" * max(1, round(n / hi * 24)) if n else ""
        print(f"  {FINGER_NAMES[f]:<6} {n/hand_total*100:5.1f}%  {bar} {n}")
    print("-" * 56)
    print(f"按键熵 {r['key_entropy']:.2f}（1=60 个键完全均匀）")
    print(f"手指熵 {r['finger_entropy']:.2f}（1=九指完全均匀）")
    print(f"手掌熵 {r['hand_entropy']:.2f}（1=左右手各半）")

    # 一句话点评
    notes = []
    if r["hand_entropy"] < 0.95:
        heavy = "左" if r["left"] > r["right"] else "右"
        notes.append(f"{heavy}手明显更累")
    finger_avg = hand_total / 9
    for f in order:
        if r["per_finger"].get(f, 0) > finger_avg * 2 and f != "th":
            notes.append(f"{FINGER_NAMES[f]}负载超标（>{finger_avg*2/hand_total*100:.0f}%）")
    if r["key_entropy"] < 0.6:
        notes.append("按键集中度偏高——换双拼/优化指法有实打实的收益空间")
    if notes:
        print("\n点评：" + "；".join(notes) + "。")
    print()
