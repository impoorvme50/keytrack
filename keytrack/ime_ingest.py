"""输入法内容路：把 RIME（鼠须管）采集到的两类事件吸进 SQLite。

RIME 侧的 lua 钩子（rime/keytrack_logger.lua）持续写两个文件：
- ~/.keytrack/ime_commits.jsonl：每行一次上屏 {"ts", "text", "sch"}
- ~/.keytrack/ime_keys.jsonl：每行一个按键分钟桶 {"min", "keys": {键: 次数}}

本模块在 helper（kbd record / launchd agent）运行期间做两件事：

1. 高频采样「最靠前窗口的属主应用」（CGWindowList，零权限、无缓存），
   用来给每条上屏记录标注"打在哪个 app 里"——输入法提交的目标应用
   必然持有键盘焦点，这个归属基本精确。
2. 定期把两个 jsonl 搬走（rename，lua 每次写都是开-写-关，互不打架）：
   - 上屏记录合并成"片段"落 segments 表：同一应用、间隔 ≤ SEGMENT_GAP 秒
     视为同一段；停顿或换应用则切新段。英文直通模式下一个字符一条记录，
     合并后自然还原成单词和句子。
   - 按键分钟桶直接累加进 key_counts / key_minutes 表（和旧 pynput 指标
     同表同语义，查看器无需改动）。

密码框天然安全：macOS 安全输入框不经过输入法，不会产生任何记录。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque

from . import storage


COMMITS_PATH = os.path.expanduser("~/.keytrack/ime_commits.jsonl")
KEYS_PATH = os.path.expanduser("~/.keytrack/ime_keys.jsonl")

SAMPLE_SECONDS = 0.3      # 前台应用采样间隔
DRAIN_SECONDS = 1.0       # 搬走 jsonl 的间隔
SEGMENT_GAP = 6.0         # 同一应用内停顿超过该秒数则切新片段
ATTRIBUTE_WINDOW = 30.0   # 采样与上屏时间差超过该值就不敢乱猜应用
MAX_SAMPLES = 2000        # 采样环形缓冲上限（约覆盖 10 分钟）

# 这些进程不可能产生输入法上屏（密码框走安全输入，绕过 IME）；
# 采样到它们说明屏幕刚锁定过或 API 返回了脏数据，不要当成打字目标。
_NON_TYPABLE_OWNERS = {"loginwindow", "SecurityAgent", "ScreenSaverEngine", "Window Server"}


def _frontmost_app() -> str:
    """当前最可能接收键盘输入的应用名。

    主用 CGWindowList：每次直接问窗口服务器「屏幕上最靠前的普通窗口属于谁」。
    无缓存、不需要 NSRunLoop、不需要任何权限，长驻后台进程也拿到实时结果。
    （NSWorkspace.frontmostApplication 在没有 runloop 的常驻进程里会返回
    过期值——实测锁屏一次后就一直停在 loginwindow，这个坑踩过。）
    """
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )
        for w in windows:
            if w.get("kCGWindowLayer", 99) == 0 and w.get("kCGWindowAlpha", 0) > 0:
                owner = w.get("kCGWindowOwnerName") or ""
                if owner and owner not in _NON_TYPABLE_OWNERS:
                    return owner
        return "Unknown"  # 只剩被排除的进程（锁屏等）
    except Exception:
        pass
    # 兜底：NSWorkspace（长驻进程里可能过期，但聊胜于无）
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        name = (app.localizedName() if app else None) or "Unknown"
        return "Unknown" if name in _NON_TYPABLE_OWNERS else name
    except Exception:
        return "Unknown"


def _drain_file(path: str) -> list[dict]:
    """把 jsonl 整个搬走并解析成对象列表；没有新内容时返回空表。

    用 rename 实现"原子搬走"：搬走期间 lua 新写的内容会落在新建的原名
    文件里，下一轮再收，不会丢也不会重复。坏行静默跳过。
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    reading = path + ".reading"
    try:
        os.replace(path, reading)
    except OSError:
        return []
    records: list[dict] = []
    try:
        with open(reading, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    finally:
        try:
            os.remove(reading)
        except OSError:
            pass
    return records


def drain_commits(path: str = COMMITS_PATH) -> list[dict]:
    """搬走并解析上屏记录（保留 ts/text/sch 三个字段的有效行）。"""
    out = []
    for obj in _drain_file(path):
        text, ts = obj.get("text"), obj.get("ts")
        if isinstance(text, str) and text and isinstance(ts, (int, float)):
            out.append({"ts": float(ts), "text": text, "sch": obj.get("sch", "")})
    return out


def drain_key_buckets(path: str = KEYS_PATH) -> list[dict]:
    """搬走并解析按键分钟桶。"""
    out = []
    for obj in _drain_file(path):
        minute, keys = obj.get("min"), obj.get("keys")
        if isinstance(minute, str) and isinstance(keys, dict) and keys:
            out.append({"min": minute, "keys": keys})
    return out


def store_key_buckets(conn, buckets: list[dict]) -> None:
    """按键分钟桶 → key_counts（按天）+ key_minutes（按分钟），与 pynput 指标同表。"""
    by_day: dict[str, dict[str, int]] = {}
    by_minute: dict[str, int] = {}
    for b in buckets:
        day = b["min"][:10]
        total = 0
        day_counts = by_day.setdefault(day, {})
        for key, n in b["keys"].items():
            if isinstance(n, (int, float)) and n > 0:
                n = int(n)
                day_counts[key] = day_counts.get(key, 0) + n
                total += n
        if total:
            by_minute[b["min"]] = by_minute.get(b["min"], 0) + total
    for day, counts in by_day.items():
        storage.bump_key_counts(conn, day, counts)
    storage.bump_key_minutes(conn, by_minute)


class ImeIngester:
    """后台线程：采样前台应用 + 定期吸入上屏记录与按键桶，合并落库。"""

    def __init__(self, db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False):
        self.db_path = db_path
        self.verbose = verbose

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: deque[tuple[float, str]] = deque(maxlen=MAX_SAMPLES)

        # 当前正在累积的片段
        self._seg_app: str | None = None
        self._seg_start = 0.0
        self._seg_end = 0.0
        self._seg_parts: list[str] = []

    # ---- 应用归属 ----

    def _sample_app(self) -> None:
        self._samples.append((time.time(), _frontmost_app()))

    def _attribute(self, ts: float) -> str:
        """给一条上屏记录找应用：取不晚于 ts（留秒级精度余量）的最近一次采样。"""
        best: tuple[float, str] | None = None
        for sample_ts, app in reversed(self._samples):
            if sample_ts <= ts + 1.5:
                best = (sample_ts, app)
                break
        if best is None or abs(best[0] - ts) > ATTRIBUTE_WINDOW:
            if self.verbose:
                n = len(self._samples)
                print(f"[attr] ts={ts:.1f} 无采样可配（共 {n} 个采样）→ Unknown")
            return "Unknown"
        if self.verbose:
            print(f"[attr] ts={ts:.1f} ← 采样 {best[0]:.1f}={best[1]}")
        return best[1]

    # ---- 片段合并与落库 ----

    def _feed(self, ts: float, text: str) -> None:
        app = self._attribute(ts)
        if (
            self._seg_app is not None
            and app == self._seg_app
            and ts - self._seg_end <= SEGMENT_GAP
        ):
            self._seg_parts.append(text)
            self._seg_end = max(self._seg_end, ts)
            return
        self._flush()
        self._seg_app = app
        self._seg_start = ts
        self._seg_end = ts
        self._seg_parts = [text]

    def _flush(self) -> None:
        if self._seg_app is None or not self._seg_parts:
            return
        text = "".join(self._seg_parts)
        if text.strip():
            with storage.connect(self.db_path) as conn:
                storage.insert_segment(
                    conn,
                    app=self._seg_app,
                    window=None,
                    start_ts=self._seg_start,
                    end_ts=self._seg_end,
                    text=text,
                    key_count=len(text),
                )
            if self.verbose:
                preview = text.replace("\n", "\u23ce")[:60]
                print(f"[ime] {self._seg_app}: +{len(text)} 字 | {preview}")
        self._seg_app = None
        self._seg_parts = []

    def _drain_all(self) -> None:
        for rec in drain_commits():
            self._feed(rec["ts"], rec["text"])
        buckets = drain_key_buckets()
        if buckets:
            with storage.connect(self.db_path) as conn:
                store_key_buckets(conn, buckets)
            if self.verbose:
                total = sum(sum(b["keys"].values()) for b in buckets)
                print(f"[keys] 吸入 {len(buckets)} 个分钟桶，共 {total} 击")

    # ---- 生命周期 ----

    def _loop(self) -> None:
        last_drain = 0.0
        while not self._stop.wait(SAMPLE_SECONDS):
            try:
                self._sample_app()
                now = time.time()
                if now - last_drain >= DRAIN_SECONDS:
                    last_drain = now
                    self._drain_all()
            except Exception as exc:  # 单次失败不该让采集挂掉
                if self.verbose:
                    print("[warn]", exc)

    def start_async(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        # 收尾：把剩余记录吸进来，并把最后一段落库
        self._drain_all()
        self._flush()


def ingest_once(
    db_path: str = storage.DEFAULT_DB_PATH,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    """一次性吸入（查询前兜底 / kbd ingest）：不采样，最近 30 秒的记录
    归到当前前台应用，更早的记为 Unknown。返回吸入的记录条数。"""
    ingester = ImeIngester(db_path=db_path, verbose=verbose and not quiet)
    ingester._sample_app()
    records = drain_commits()
    for rec in records:
        ingester._feed(rec["ts"], rec["text"])
    ingester._flush()
    buckets = drain_key_buckets()
    if buckets:
        with storage.connect(db_path) as conn:
            store_key_buckets(conn, buckets)
    return len(records) + len(buckets)
