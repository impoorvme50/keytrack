# keytrack 数据 schema

给想直接读库的消费者（Swift 状态栏、网页看板、脚本）。
数据库默认路径：`~/.keytrack/keytrack.db`（SQLite，无并发写冲突顾虑：
只有吸入器写，读者随便读）。

## 表

### segments — 输入内容片段（「打了什么」）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| app | TEXT | 应用名（最靠前窗口属主，如 `微信`/`Cursor`；补录的为 `Unknown`） |
| window | TEXT | 预留，当前恒为 NULL |
| start_ts | REAL | 片段开始，Unix 秒（本地时区） |
| end_ts | REAL | 片段结束 |
| text | TEXT | 上屏文字原文（汉字/英文/标点，可含 `\n`） |
| key_count | INTEGER | 字符数（Unicode 码点数） |

片段切分规则：同一应用内相邻上屏间隔 ≤ 6 秒合为一段；停顿或换应用切新段。

```sql
-- 今天的时间线
SELECT datetime(start_ts,'unixepoch','localtime') AS t, app, text
FROM segments
WHERE start_ts >= strftime('%s','now','start of day','localtime')
ORDER BY start_ts;
```

### key_counts — 按键频率（按天）

| 列 | 类型 | 说明 |
|----|------|------|
| day | TEXT | `YYYY-MM-DD`，与 key 联合主键 |
| key | TEXT | 键名。RIME 风格（`space`/`Return`/`BackSpace`，v2 起）与 pynput 风格（` `/`\n`/小写名，历史数据）可能并存 |
| count | INTEGER | 当天次数 |

### key_minutes — 按键节奏（按分钟）

| 列 | 类型 | 说明 |
|----|------|------|
| minute | TEXT PK | `YYYY-MM-DDTHH:MM`（本地时区） |
| count | INTEGER | 该分钟总击键数 |

用途：活跃分钟数、平均/峰值击键每分钟、按小时分布（`substr(minute,12,2)` 分组）。

## JSON 接口（`kbd today --json`）

```jsonc
{
  "day": "2026-07-28",
  "segments": [{"app": "微信", "window": null, "start": 1785..., "end": 1785..., "text": "...", "chars": 12}],
  "segment_count": 53,
  "total_chars": 2048,
  "apps": {"微信": 500, "Cursor": 400},          // 按字符数降序
  "keys": {
    "total_keys": 2634,
    "active_minutes": 20,
    "avg_kpm": 131.7,
    "peak_kpm": 220,
    "by_hour": {"12": 390, "13": 475},
    "per_minute": {"2026-07-28T15:22": 174},
    "key_frequency": {"space": 390, "BackSpace": 8}
  }
}
```

Python 侧对应物：`keytrack/query.py` 的 `day_report()` / `segments_for_day()` /
`key_stats_for_day()` / `available_days()`。

## 事件暂存文件（生产者视角，一般不用碰）

吸入前的事件躺在 jsonl 里，由常驻 helper 或查询前补录搬走（rename 原子搬运）：

- `~/.keytrack/ime_commits.jsonl`：`{"ts": 1785..., "text": "上屏文字", "sch": "rime_ice"}`
- `~/.keytrack/ime_keys.jsonl`：`{"min": "2026-07-28T15:30", "keys": {"a": 3, "space": 1}}`
