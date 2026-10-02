"""键盘热力图：把 key_counts 渲染成独立 HTML（log 色阶 + 悬停提示）。

数据只读 key_counts 表（RIME/pynput 两套键名都认），输出一个零依赖的
HTML 文件，浏览器打开即可。颜色按 log(count) 缩放——space 和生僻键
差着两三个数量级，线性色阶会全军覆没。
"""

from __future__ import annotations

import math
import subprocess
from datetime import date

from . import storage, key_stats
from .layouts import ANSI_ROWS, norm_key


def _key_counts(day: date | None, db_path: str) -> dict[str, int]:
    """指定日（None=全部累计）的按键频率，归一到物理键 id。"""
    with storage.connect(db_path) as conn:
        if day is None:
            rows = conn.execute(
                "SELECT key, SUM(count) AS c FROM key_counts GROUP BY key"
            ).fetchall()
        else:
            rows = storage.key_counts_for_day(conn, day)
    counts: dict[str, int] = {}
    for r in rows:
        k = norm_key(r["key"])
        if k:
            counts[k] = counts.get(k, 0) + int(r["c"] if day is None else r["count"])
    return counts


def _color(ratio: float) -> str:
    """冰蓝(低) → 深红(高)，ratio 0..1。"""
    if ratio <= 0:
        return "#1c2128"
    # hsl 220°(蓝) → 0°(红)
    hue = 220 - 220 * ratio
    light = 25 + 25 * ratio
    return f"hsl({hue:.0f}, 85%, {light:.0f}%)"


def render_html(counts: dict[str, int], title: str, reliable: bool = True, note: str = "") -> str:
    total = sum(counts.values())
    vmax = math.log1p(max(counts.values())) if counts else 1
    rows_html = []
    for row in ANSI_ROWS:
        keys_html = []
        for key_id, label, width, _finger in row:
            n = counts.get(key_id, 0)
            ratio = math.log1p(n) / vmax if n else 0
            pct = f"{n / total * 100:.2f}%" if total and reliable else "占比待完善"
            tip = f"{key_id}: {n} 次（{pct}）"
            keys_html.append(
                f'<div class="key" style="flex:{width};background:{_color(ratio)}" '
                f'title="{tip}">{label}</div>'
            )
        rows_html.append(f'<div class="row">{"".join(keys_html)}</div>')
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
    top_html = "".join(
        f"<tr><td>{k}</td><td>{n}</td><td>{f"{n/total*100:.1f}%" if reliable else "待完善"}</td></tr>"
        for k, n in top
    ) if total else ""
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; font-family:-apple-system,monospace; padding:24px; }}
  h1 {{ font-size:18px; }} .row {{ display:flex; gap:4px; margin-bottom:4px; max-width:900px; }}
  .key {{ border-radius:6px; text-align:center; padding:10px 0; min-width:0;
         font-size:14px; color:#e6edf3; cursor:default; border:1px solid #30363d; }}
  table {{ margin-top:20px; border-collapse:collapse; }}
  td {{ padding:2px 14px 2px 0; font-size:13px; }}
</style></head><body>
<h1>{title}</h1>
<p>{note}</p>
<p>共 {total} 次按键。颜色=log 频率（蓝→红），悬停键帽看次数与占比。</p>
{"".join(rows_html)}
<table>{top_html}</table>
</body></html>"""


def export(
    day: date | None = None,
    db_path: str = storage.DEFAULT_DB_PATH,
    out: str | None = None,
    open_browser: bool = True,
) -> str:
    counts = _key_counts(day, db_path)
    with storage.connect(db_path) as conn:
        quality = key_stats.quality(conn, day.isoformat() if day else None)
    title = f"keytrack 键盘热力图 · {day.isoformat()}" if day else "keytrack 键盘热力图 · 累计"
    if out is None:
        suffix = day.isoformat() if day else "all"
        out = f"~/.keytrack/heatmap-{suffix}.html"
    import os

    out = os.path.expanduser(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(counts, title, quality["reliable"], quality["message"] + " " + quality["scope"]))
    if open_browser:
        subprocess.run(["open", out], check=False)
    return out
