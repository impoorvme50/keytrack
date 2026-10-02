"""Explicit, read-only discovery of repeated complete expressions.

Recorder segments are historical records, not verified input-method sessions.
No personal text is persisted here; rejection storage contains only hashes.
"""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
MAX_SEGMENTS = 20_000
MAX_BYTES = 4_000_000
MAX_DISTINCT = 8_000
MAX_CANDIDATES = 50
MAX_SECONDS = 3.0
MAX_REJECTED = 2_000
BATCH_SECONDS = 30 * 60
BATCH_BASIS = "记录批次按应用、窗口标题和至少 30 分钟间隔估算，不代表真实输入会话。"
SENSITIVE = re.compile(
    r"https?://|www\.|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|\d{4,}|"
    r"(?:地址|住址|收件|收货|邮编|手机号|电话号码|联系电话|联系方式|微信号|身份证|银行账号|密码|验证码)|"
    r"(?:路|街|巷|弄)\s*[零一二三四五六七八九十百千万\d]+\s*号|"
    r"\b(?:password|verification\s+code|bank\s+account|shipping\s+address|home\s+address|phone|mobile|contact\s+number)\b|"
    r"\b\d{1,4}\s+.{1,40}\b(?:street|road|avenue|lane|drive|boulevard)\b", re.IGNORECASE
)


def identity(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def expressions(text: str) -> set[str]:
    """Keep whole records/lines; never concatenate commits or mine substrings."""
    def whole_repetition(item: str) -> bool:
        # A second match before the original length reveals the shortest exact
        # period. Candidate length is bounded below, avoiding regex backtracking.
        width = (item + item).find(item, 1)
        return 0 < width <= min(80, len(item) // 2) and len(item) % width == 0

    if (not isinstance(text, str) or SENSITIVE.search(text)
            or len(re.findall(r"\d", text)) >= 7
            or re.search(r"[零〇一二三四五六七八九两]{7,}", text)):
        return set()
    choices = {text.strip()}
    if "\n" in text or "\r" in text:
        choices.update(line.strip() for line in text.splitlines())
    return {item for item in choices
            if 6 <= len(item) <= 160
            and (len(re.findall(r"[\u4e00-\u9fff]", item)) >= 4
                 or len(re.findall(r"\b[a-zA-Z]{2,}\b", item)) >= 3)
            and not any(ord(ch) < 32 and ch not in "\n\t" for ch in item)
            and not re.search(r"[{}\[\]<>`\\]", item)
            and not re.search(r"(.{1,4})\1{2,}", item)
            and not whole_repetition(item)
            # strip() removes the last line separator. Restore only that marker
            # while checking repeated line blocks; eligible individual lines
            # remain in choices and the set counts each once per record.
            and not ("\n" in item and whole_repetition(item + "\n"))}


def suggested_code(text: str, used: set[str]) -> str:
    """Portable deterministic fallback; users can edit the code before import."""
    letters = "".join(chr(ord("a") + int(ch, 16)) for ch in identity(text))
    for width in range(5, 19):
        code = "q" + letters[:width]
        if code not in used:
            used.add(code)
            return code
    raise ValueError("无法生成无冲突短编码，请手动填写")


def discover(db: str, days: int, phrases: list[dict], rejected: set[str],
             *, today: date | None = None) -> dict:
    if type(days) is not int or days not in (7, 30, 90):
        raise ValueError("分析范围须为最近 7、30 或 90 天")
    today = today or datetime.now(ZONE).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, datetime.min.time(), ZONE).timestamp()
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), ZONE).timestamp()
    result = {"days": days, "start_day": first.isoformat(), "end_day": today.isoformat(),
              "scanned_segments": 0, "truncated": False, "candidates": [],
              "batch_basis": BATCH_BASIS, "rejected_count": len(rejected),
              "message": "没有符合门槛的重复表达。"}
    path = Path(db).expanduser().resolve()
    if not path.exists():
        result["message"] = "尚无可分析的本地输入记录。"
        return result
    deadline = time.monotonic() + MAX_SECONDS
    counts, sightings, activity = {}, {}, {}
    batch_serial = 0
    byte_count = 0
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1_000)
        rows = connection.execute(
            "SELECT start_ts, end_ts, substr(app,1,161), substr(window,1,513), substr(text,1,4097), "
            "length(app), length(window) FROM segments "
            "WHERE start_ts>=? AND start_ts<? ORDER BY start_ts DESC, id DESC LIMIT ?",
            (start, end, MAX_SEGMENTS + 1))
        for timestamp, end_timestamp, app, window, text, app_length, window_length in rows:
            if result["scanned_segments"] >= MAX_SEGMENTS or time.monotonic() >= deadline:
                result["truncated"] = True
                break
            result["scanned_segments"] += 1
            byte_count += sum(len(value.encode("utf-8")) for value in (text, app, window) if isinstance(value, str))
            if byte_count > MAX_BYTES:
                result["truncated"] = True
                break
            if ((app_length or 0) > 160 or (window_length or 0) > 512
                    or not isinstance(timestamp, (float, int)) or not math.isfinite(timestamp)
                    or not isinstance(end_timestamp, (float, int)) or not math.isfinite(end_timestamp)
                    or end_timestamp < timestamp):
                result["truncated"] = True
                continue
            key = (app, window)
            previous = activity.get(key)
            if previous is None or previous[0] - end_timestamp >= BATCH_SECONDS:
                batch_serial += 1
                batch_id = batch_serial
            else:
                batch_id = previous[1]
            # Include every record's activity, even when its text is ineligible.
            activity[key] = (timestamp, batch_id)
            if not isinstance(text, str) or len(text) > 4096:
                continue
            for expression in sorted(expressions(text)):
                if expression not in counts and len(counts) >= MAX_DISTINCT:
                    result["truncated"] = True
                    continue
                counts[expression] = counts.get(expression, 0) + 1
                sightings.setdefault(expression, set()).add(batch_id)
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error):
            result["truncated"] = True
        else:
            raise ValueError("本地历史暂时无法读取，请稍后再试") from error
    finally:
        connection.close()
    existing = {item["text"]: item["code"] for item in phrases}
    used = {item["code"] for item in phrases}
    eligible = []
    for text, count in counts.items():
        if time.monotonic() >= deadline:
            result["truncated"] = True
            break
        batches = len(sightings[text])
        token = identity(text)
        if count >= 3 and batches >= 2 and token not in rejected:
            eligible.append((text, count, batches, token))
    eligible.sort(key=lambda item: (-item[1], -item[2], item[0]))
    result["truncated"] |= len(eligible) > MAX_CANDIDATES
    for text, count, batches, token in eligible[:MAX_CANDIDATES]:
        if time.monotonic() >= deadline:
            result["truncated"] = True
            break
        duplicate = text in existing
        code = existing[text] if duplicate else suggested_code(text, used)
        result["candidates"].append({"id": token, "text": text, "count": count,
                                     "batch_count": batches, "suggested_code": code,
                                     "duplicate": duplicate, "code_conflict": False,
                                     "existing_code": existing.get(text)})
    if result["candidates"]:
        result["message"] = f"发现 {len(result['candidates'])} 条重复表达，勾选后才加入待保存列表。"
    if result["truncated"]:
        result["message"] += "分析或显示已达到上限，次数仅表示已扫描记录。"
    return result
