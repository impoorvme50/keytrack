"""launchd 常驻 helper：登录后自动跑 `kbd record`，采集无感常驻。

`kbd install-agent`   写入 ~/Library/LaunchAgents/com.keytrack.recorder.plist 并加载；
`kbd uninstall-agent` 卸载并删除。
日志在 ~/.keytrack/logs/，状态用 `launchctl list | grep keytrack` 查看。
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys

LABEL = "com.keytrack.recorder"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
LOG_DIR = os.path.expanduser("~/.keytrack/logs")


def _plist() -> dict:
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = bool(getattr(sys, "frozen", False))
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "record"] if bundled else [
            os.path.join(project_dir, ".venv/bin/python"),
            "-u",
            os.path.join(project_dir, "kbd.py"),
            "record",
        ],
        "WorkingDirectory": os.path.dirname(sys.executable) if bundled else project_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": os.path.join(LOG_DIR, "record.out.log"),
        "StandardErrorPath": os.path.join(LOG_DIR, "record.err.log"),
        "ProcessType": "Background",
        "LowPriorityIO": True,
    }


def install(verbose: bool = True) -> bool:
    python = _plist()["ProgramArguments"][0]
    if not os.path.exists(python):
        if verbose:
            print(f"❌ 没找到虚拟环境解释器：{python}\n   先确认项目 .venv 存在。")
        return False
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(_plist(), f)

    # 已加载的话先卸掉再装，保证新版本生效
    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    result = subprocess.run(["launchctl", "load", PLIST_PATH], capture_output=True, text=True)
    if result.returncode != 0:
        if verbose:
            print("❌ launchctl load 失败：", result.stderr.strip())
        return False
    if verbose:
        print(f"· 常驻 helper 已安装并启动：{PLIST_PATH}")
        print(f"· 日志：{LOG_DIR}/record.*.log")
        print("· 现在起登录系统即自动采集；卸载用 `kbd uninstall-agent`。")
    return True


def uninstall(verbose: bool = True) -> bool:
    if not os.path.exists(PLIST_PATH):
        if verbose:
            print("常驻 helper 没安装过。")
        return True
    subprocess.run(["launchctl", "unload", PLIST_PATH], capture_output=True)
    os.remove(PLIST_PATH)
    if verbose:
        print("· 常驻 helper 已卸载。")
    return True


def service_status(label: str = LABEL) -> dict:
    """Query the user's service domain; a loaded job is not necessarily running."""
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"loaded": False, "running": False, "state": "unknown", "pid": None}
    if result.returncode != 0:
        absent = "Could not find service" in result.stderr
        return {"loaded": False, "running": False,
                "state": "absent" if absent else "unknown", "pid": None}
    state = re.search(r"^\s*state = (.+)$", result.stdout, re.M)
    pid = re.search(r"^\s*pid = (\d+)$", result.stdout, re.M)
    value = state.group(1).strip() if state else "unknown"
    return {"loaded": True, "running": value == "running" and pid is not None,
            "state": value, "pid": int(pid.group(1)) if pid else None}


def status() -> None:
    info = service_status()
    state = ("运行中" if info["running"] else "状态无法读取" if info["state"] == "unknown"
             else "已加载，未运行" if info["loaded"] else "未运行")
    print(f"常驻 helper：{state}（plist {'已装' if os.path.exists(PLIST_PATH) else '未装'}）")
    from .ime_ingest import COMMITS_PATH, KEYS_PATH

    for path in (COMMITS_PATH, KEYS_PATH):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print(f"  待吸入：{path}（{os.path.getsize(path)} 字节）")


if __name__ == "__main__":
    sys.exit(0 if install() else 1)
