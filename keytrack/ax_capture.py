"""基于 macOS 辅助功能(Accessibility)的输入内容采集。

和 capture.py（监听物理按键）不同，这里读取"当前聚焦输入框里实际出现的文字"，
因此不管用什么输入法，拿到的都是最终上屏的真实内容（中文、emoji、粘贴的文本都行），
彻底绕开"拼音只记到字母"的问题。

思路：
- 每隔 POLL_INTERVAL 秒读一次系统当前聚焦元素的文本值(AXValue)。
- 进入一个输入框时先记"基线值"，不落库（避免把已有内容当成你输入的）。
- 你停止输入 IDLE_FLUSH_SECONDS 秒后，或切换到别的应用/输入框时，
  用"基线 → 当前值"的差异算出你新增的文字，只把新增部分落库。
- 停顿后再取差异，能保证此时输入法已经把拼音候选转成汉字，避免中间态噪声。

需要授权：系统设置 → 隐私与安全性 → 辅助功能（Accessibility）。
读不到内容的应用（终端、部分 Electron 应用、密码框）会被安静跳过。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
    AXIsProcessTrusted,
    kAXFocusedUIElementAttribute,
    kAXValueAttribute,
    kAXRoleAttribute,
    kAXSelectedTextAttribute,
)

from . import storage


POLL_INTERVAL = 0.4        # 轮询聚焦元素的间隔（秒）
IDLE_FLUSH_SECONDS = 6.0   # 停止输入多久就把当前累积的新增内容落库
MAX_TEXT_SCAN = 200_000    # 超过这个长度的字段跳过 diff，避免大文档卡顿


def _frontmost_app() -> str:
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return (app.localizedName() if app else None) or "Unknown"
    except Exception:
        return "Unknown"


def _focused_text_value() -> str | None:
    """返回当前聚焦元素的文本值；非文本元素或读不到时返回 None。"""
    system = AXUIElementCreateSystemWide()
    err, focused = AXUIElementCopyAttributeValue(
        system, kAXFocusedUIElementAttribute, None
    )
    if err != 0 or focused is None:
        return None
    err, value = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
    if err != 0 or not isinstance(value, str):
        return None
    return value


def _inserted(old: str, new: str) -> str:
    """返回从 old 变到 new 时新插入的那段文字（用公共前后缀求差）。

    - 纯追加 "abc" -> "abcde" 得 "de"。
    - 中间替换（拼音候选 "woshi" -> "我是"）得 "我是"。
    - 删除操作得 ""（不记录）。
    """
    if old == new:
        return ""
    m = min(len(old), len(new))
    p = 0
    while p < m and old[p] == new[p]:
        p += 1
    s = 0
    while s < (m - p) and old[-1 - s] == new[-1 - s]:
        s += 1
    return new[p: len(new) - s]


class AXRecorder:
    def __init__(self, db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False):
        self.db_path = db_path
        self.verbose = verbose
        self._stop = threading.Event()

        self._app = ""
        self._base = ""          # 当前追踪窗口的基线文本（不落库）
        self._last = ""          # 上次读到的文本
        self._base_start = 0.0   # 基线建立的时间
        self._last_change = 0.0  # 最近一次文本变化的时间

    def _record(self, end_ts: float) -> None:
        """把 base -> last 之间新增的文字落库，并把 base 推进到 last。"""
        delta = _inserted(self._base, self._last)
        if delta.strip():
            with storage.connect(self.db_path) as conn:
                storage.insert_segment(
                    conn,
                    app=self._app or "Unknown",
                    window=None,
                    start_ts=self._base_start or end_ts,
                    end_ts=end_ts,
                    text=delta,
                    key_count=len(delta),
                )
            if self.verbose:
                preview = delta.replace("\n", "\u23ce")[:60]
                print(f"[flush] {self._app}: +{len(delta)} 字 | {preview}")
        self._base = self._last
        self._base_start = end_ts

    def _reset_baseline(self, app: str, value: str, now: float) -> None:
        self._app = app
        self._base = value
        self._last = value
        self._base_start = now
        self._last_change = now

    def _tick(self) -> None:
        now = time.time()
        app = _frontmost_app()
        value = _focused_text_value()

        if value is None:
            # 焦点不在文本控件上（或读不到）：把已有的新增内容落库，暂停追踪
            if self._last != self._base:
                self._record(now)
            return

        if len(value) > MAX_TEXT_SCAN:
            return

        # 首次，或切换了应用 -> 先落旧账，再以新字段当前内容为基线
        if not self._app or app != self._app:
            if self._last != self._base:
                self._record(now)
            self._reset_baseline(app, value, now)
            return

        # 同一应用内换了输入框（内容和之前毫无公共前后缀）-> 视为新字段
        if value != self._last and _inserted(self._last, value) == value and self._last:
            self._record(now)
            self._reset_baseline(app, value, now)
            return

        if value != self._last:
            self._last = value
            self._last_change = now
        elif (self._last != self._base) and (now - self._last_change) >= IDLE_FLUSH_SECONDS:
            # 停顿够久，此时拼音已上屏，取差异落库
            self._record(now)

    def poll_loop(self) -> None:
        """阻塞式轮询循环，供独立或组合运行调用。"""
        while not self._stop.wait(POLL_INTERVAL):
            try:
                self._tick()
            except Exception as exc:  # 单次读取失败不该让整个采集挂掉
                if self.verbose:
                    print("[warn]", exc)

    def start(self) -> None:
        if not AXIsProcessTrusted():
            print(
                "⚠️  还没有辅助功能权限。请到\n"
                "    系统设置 → 隐私与安全性 → 辅助功能\n"
                "把运行本程序的终端（Terminal / iTerm）勾上，然后重新运行。\n"
            )
            return
        print("keytrack (辅助功能模式) 采集已启动。数据库：", self.db_path)
        print("按 Ctrl-C 停止（停止时会保存最后的内容）。")
        try:
            self.poll_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            print("\nkeytrack 已停止，数据已保存。")

    def stop(self) -> None:
        self._stop.set()
        if self._last != self._base:
            self._record(time.time())


def run(db_path: str = storage.DEFAULT_DB_PATH, verbose: bool = False) -> None:
    AXRecorder(db_path=db_path, verbose=verbose).start()


def probe() -> None:
    """实时探测：切到不同应用打字，看哪个读得到文字。

    每秒打印一次当前聚焦控件：应用名 / 角色(role) / 能否读到文本 / 内容长度。
    "可读=否" 的应用（多为终端、Electron 等）就是内容采集覆盖不到的。
    """
    if not AXIsProcessTrusted():
        print("⚠️  还没有辅助功能权限，先去 系统设置 → 隐私与安全性 → 辅助功能 授权。")
        return
    print("实时探测中。请切换到不同应用（备忘录/Safari/微信/Cursor…）里打字观察。")
    print("Ctrl-C 退出。\n")
    print(f"{'应用':<16}{'角色(role)':<22}{'可读':<6}{'长度':<6}预览")
    print("-" * 72)

    system = AXUIElementCreateSystemWide()
    last = None
    try:
        while True:
            app = _frontmost_app()
            err, focused = AXUIElementCopyAttributeValue(
                system, kAXFocusedUIElementAttribute, None
            )
            role = "-"
            readable = "否"
            length = 0
            preview = ""
            if err == 0 and focused is not None:
                _, role_val = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
                role = str(role_val) if role_val else "-"
                _, value = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
                if not isinstance(value, str):
                    _, value = AXUIElementCopyAttributeValue(
                        focused, kAXSelectedTextAttribute, None
                    )
                if isinstance(value, str):
                    readable = "是"
                    length = len(value)
                    preview = value.replace("\n", "\u23ce")[-30:]
            line = f"{app:<16}{role:<22}{readable:<6}{length:<6}{preview}"
            if line != last:  # 只在有变化时打印，避免刷屏
                print(line)
                last = line
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n探测结束。")
