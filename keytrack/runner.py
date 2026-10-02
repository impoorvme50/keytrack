"""组合采集：输入法事件吸入（主）+ 可选 pynput 系统级按键监听（副）。

- 主路：鼠须管 lua 钩子写的两个 jsonl → SQLite（上屏文字合并成片段；
  按键分钟桶进指标表）。零权限，覆盖所有应用，含 Electron。
- 副路（--pynput）：pynput 系统级按键监听。只有当你还在用别的输入法、
  想统计那些按键时才需要；要"输入监控"权限。和 lua 分钟桶同表，
  同时开会重复计数，日常别开。
"""

from __future__ import annotations

import time

from . import storage
from .ime_ingest import ImeIngester, COMMITS_PATH, KEYS_PATH


def run(
    db_path: str = storage.DEFAULT_DB_PATH,
    verbose: bool = False,
    pynput: bool = False,
) -> None:
    ime = ImeIngester(db_path=db_path, verbose=verbose)
    ime.start_async()
    print("· 采集已开启（输入法路）：上屏文字 + 按键节奏 → SQLite")
    print(f"  事件文件：{COMMITS_PATH}")
    print(f"          {KEYS_PATH}")
    print("  若一直没有内容：确认当前输入法是鼠须管，并已运行 `kbd setup-ime`")

    met = None
    if pynput:
        from .metrics import MetricsRecorder
        met = MetricsRecorder(db_path=db_path, verbose=verbose)
        met.start_async()
        print("· pynput 系统级按键监听已开启（需输入监控权限）")
        print("  注意：与 lua 分钟桶同表，鼠须管内的按键会被计两次")

    print("数据库：", db_path)
    print("按 Ctrl-C 停止（停止时会保存最后的数据）。\n")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ime.stop()
        if met is not None:
            met.stop()
        print("\nkeytrack 已停止，数据已保存。")
