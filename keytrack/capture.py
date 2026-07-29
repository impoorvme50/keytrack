"""按键采集与文本重建。

核心逻辑：
- 用 pynput 全局监听按键。
- 维护一个"当前片段"缓冲：连续输入的可读文本。
- 遇到以下情况就把当前片段落库（flush）：
    * 前台应用切换；
    * 空闲超过 IDLE_FLUSH_SECONDS 秒没有输入；
    * 缓冲文本达到 MAX_SEGMENT_CHARS 长度。
- 退格会从缓冲末尾删字符；回车/Tab 作为可见字符写入。
- 同时按天聚合每个键的按下次数（保留频率统计）。

macOS 需要在"系统设置 → 隐私与安全性 → 输入监控"里授权运行的终端/程序，
否则监听不到任何按键。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from pynput import keyboard

from . import storage


IDLE_FLUSH_SECONDS = 8.0      # 空闲多久就把当前片段落库
MAX_SEGMENT_CHARS = 2000      # 单个片段最大字符数
FLUSH_TICK_SECONDS = 2.0      # 后台检查空闲的间隔


def _frontmost_app() -> tuple[str, str | None]:
    """返回 (应用名, 窗口标题)。拿不到时回退到 Unknown。"""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        name = app.localizedName() if app else None
        return (name or "Unknown", None)
    except Exception:
        return ("Unknown", None)


# 特殊键 -> 写入缓冲的可见字符（None 表示忽略）
_SPECIAL_CHARS = {
    keyboard.Key.space: " ",
    keyboard.Key.enter: "\n",
    keyboard.Key.tab: "\t",
}


class Recorder:
    def __init__(self, db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False):
        self.db_path = db_path
        self.verbose = verbose

        self._lock = threading.Lock()
        self._buf: list[str] = []
        self._key_count = 0
        self._seg_app: str = ""
        self._seg_window: str | None = None
        self._seg_start: float = 0.0
        self._last_activity: float = 0.0

        self._pending_key_counts: dict[str, int] = {}
        self._pending_day: str = ""

        self._stop = threading.Event()
        self._listener: keyboard.Listener | None = None

    # ---- 片段管理 -------------------------------------------------

    def _flush_locked(self) -> None:
        """把当前缓冲片段落库。调用者必须已持有 self._lock。"""
        text = "".join(self._buf)
        if text.strip() == "" or self._key_count == 0:
            self._reset_buffer_locked()
            return
        end = self._last_activity or time.time()
        with storage.connect(self.db_path) as conn:
            storage.insert_segment(
                conn,
                app=self._seg_app or "Unknown",
                window=self._seg_window,
                start_ts=self._seg_start or end,
                end_ts=end,
                text=text,
                key_count=self._key_count,
            )
        if self.verbose:
            preview = text.replace("\n", "\u23ce")[:60]
            print(f"[flush] {self._seg_app}: {self._key_count} keys | {preview}")
        self._reset_buffer_locked()

    def _reset_buffer_locked(self) -> None:
        self._buf = []
        self._key_count = 0
        self._seg_app = ""
        self._seg_window = None
        self._seg_start = 0.0

    def _flush_key_counts_locked(self) -> None:
        if self._pending_key_counts:
            with storage.connect(self.db_path) as conn:
                storage.bump_key_counts(conn, self._pending_day, self._pending_key_counts)
            self._pending_key_counts = {}

    # ---- 键盘事件 -------------------------------------------------

    def _key_label(self, key) -> str:
        if isinstance(key, keyboard.KeyCode) and key.char is not None:
            return key.char
        name = getattr(key, "name", None)
        return name or str(key)

    def _on_press(self, key) -> None:
        now = time.time()
        today = datetime.now().date().isoformat()

        with self._lock:
            # 按天聚合键频率
            if today != self._pending_day:
                self._flush_key_counts_locked()
                self._pending_day = today
            label = self._key_label(key)
            self._pending_key_counts[label] = self._pending_key_counts.get(label, 0) + 1

            # 前台 app 切换 -> 先落旧片段
            app, window = _frontmost_app()
            if self._buf and app != self._seg_app:
                self._flush_locked()

            # 新片段起始
            if not self._buf:
                self._seg_app = app
                self._seg_window = window
                self._seg_start = now

            # 文本重建
            if key == keyboard.Key.backspace:
                if self._buf:
                    self._buf.pop()
            elif key in _SPECIAL_CHARS:
                self._buf.append(_SPECIAL_CHARS[key])
            elif isinstance(key, keyboard.KeyCode) and key.char is not None:
                self._buf.append(key.char)
            # 其它特殊键（方向键、修饰键等）不写入文本，只计入频率

            self._key_count += 1
            self._last_activity = now

            if len("".join(self._buf)) >= MAX_SEGMENT_CHARS:
                self._flush_locked()

    # ---- 后台空闲检查 ---------------------------------------------

    def _idle_loop(self) -> None:
        while not self._stop.wait(FLUSH_TICK_SECONDS):
            with self._lock:
                if self._buf and (time.time() - self._last_activity) >= IDLE_FLUSH_SECONDS:
                    self._flush_locked()
                self._flush_key_counts_locked()

    # ---- 生命周期 -------------------------------------------------

    def start(self) -> None:
        print("keytrack 采集已启动。数据库：", self.db_path)
        print("按 Ctrl-C 停止（停止时会保存最后的片段）。")
        idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
        idle_thread.start()
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()
        try:
            self._listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.stop()
        with self._lock:
            self._flush_locked()
            self._flush_key_counts_locked()
        print("\nkeytrack 已停止，数据已保存。")


def run(db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False) -> None:
    Recorder(db_path=db_path, verbose=verbose).start()
