"""操作层指标采集：按键频率 + 打字速度/节奏。

只监听物理按键，只统计"数量和时间"，不保存任何输入内容。
和 ax_capture（负责真实文字内容）并行运行，两者各取所长：
- ax_capture：你输入了"什么"（真实中文）。
- metrics：你输入得"多快/多频繁"，哪个键按得最多。

需要授权：系统设置 → 隐私与安全性 → 输入监控。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from pynput import keyboard

from . import storage


FLUSH_TICK_SECONDS = 3.0


class MetricsRecorder:
    def __init__(self, db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False):
        self.db_path = db_path
        self.verbose = verbose

        self._lock = threading.Lock()
        self._key_counts: dict[str, int] = {}
        self._minutes: dict[str, int] = {}
        self._day = ""

        self._stop = threading.Event()
        self._listener: keyboard.Listener | None = None
        self._flush_thread: threading.Thread | None = None

    def _key_label(self, key) -> str:
        if isinstance(key, keyboard.KeyCode) and key.char is not None:
            return key.char
        return getattr(key, "name", None) or str(key)

    def _on_press(self, key) -> None:
        now = datetime.now()
        day = now.date().isoformat()
        minute = now.strftime("%Y-%m-%dT%H:%M")
        label = self._key_label(key)
        with self._lock:
            if day != self._day:
                self._flush_locked()
                self._day = day
            self._key_counts[label] = self._key_counts.get(label, 0) + 1
            self._minutes[minute] = self._minutes.get(minute, 0) + 1

    def _flush_locked(self) -> None:
        if not self._key_counts and not self._minutes:
            return
        with storage.connect(self.db_path) as conn:
            if self._key_counts:
                storage.bump_key_counts(conn, self._day, self._key_counts)
            if self._minutes:
                storage.bump_key_minutes(conn, self._minutes)
        self._key_counts = {}
        self._minutes = {}

    def _flush_loop(self) -> None:
        while not self._stop.wait(FLUSH_TICK_SECONDS):
            with self._lock:
                self._flush_locked()

    def start_async(self) -> bool:
        """启动监听（非阻塞）。返回是否成功启动。"""
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.stop()
        with self._lock:
            self._flush_locked()
