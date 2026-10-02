"""Manage the optional local Kev 0.8B server as a macOS LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
from pathlib import Path


LABEL = "com.keytrack.kev"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / ".keytrack/logs"
MODEL = "jaredpalmer/kev-0.8b"
PORT = "8009"


def is_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True
    )
    return result.returncode == 0


def set_running(value: bool) -> bool:
    """Persistently enable or disable this project's LaunchAgent."""
    if not PLIST_PATH.exists():
        return not value
    target = f"gui/{os.getuid()}/{LABEL}"
    policy = "enable" if value else "disable"
    result = subprocess.run(["launchctl", policy, target], capture_output=True)
    if result.returncode != 0:
        return False
    loaded = is_loaded()
    if loaded == value:
        return True
    verb = "load" if value else "unload"
    result = subprocess.run(["launchctl", verb, str(PLIST_PATH)], capture_output=True)
    if result.returncode != 0 and value:
        # Keep the persisted policy aligned with the still-off feature flag.
        subprocess.run(["launchctl", "disable", target], capture_output=True)
    return result.returncode == 0


def plist_for(repo: Path) -> dict:
    repo = repo.expanduser().resolve()
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(repo / ".venv/bin/python"),
            "-u",
            "-m",
            "kev.serve",
            "--run",
            MODEL,
            "--port",
            PORT,
        ],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {"KEV_DTYPE": "bf16"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(LOG_DIR / "kev.out.log"),
        "StandardErrorPath": str(LOG_DIR / "kev.err.log"),
    }


def install(repo: Path, verbose: bool = True) -> bool:
    repo = repo.expanduser().resolve()
    if not (repo / "kev/serve.py").is_file() or not (repo / ".venv/bin/python").exists():
        if verbose:
            print(f"❌ 找不到 Kev 服务或虚拟环境：{repo}")
        return False
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    LOG_DIR.chmod(0o700)
    if PLIST_PATH.exists() and not set_running(False):
        if verbose:
            print("❌ 无法停止旧 Kev LaunchAgent，配置未更新。")
        return False

    with tempfile.NamedTemporaryFile(
        mode="wb", dir=PLIST_PATH.parent, prefix=".keytrack-kev-", delete=False
    ) as output:
        plistlib.dump(plist_for(repo), output)
        temporary = Path(output.name)
    os.replace(temporary, PLIST_PATH)
    PLIST_PATH.chmod(0o600)

    switch_file = Path.home() / ".keytrack/kev-rime/enabled"
    try:
        enabled = (
            switch_file.is_file()
            and not switch_file.is_symlink()
            and switch_file.read_text(encoding="ascii").strip() == "1"
        )
    except (OSError, UnicodeError):
        enabled = False
    if not set_running(enabled):
        if verbose:
            print("❌ Kev LaunchAgent 状态设置失败。")
        return False
    if verbose:
        state = "已设为登录后启动" if enabled else "已安装，等待 `kbd kev on` 开启"
        print(f"· Kev 0.8B {state}：{PLIST_PATH}")
        print(f"· 日志：{LOG_DIR}/kev.*.log")
        print("· 服务只监听 127.0.0.1:8009。")
    return True


def uninstall(verbose: bool = True) -> bool:
    if not PLIST_PATH.exists():
        if verbose:
            print("Kev LaunchAgent 未安装。")
        return True
    if not set_running(False):
        if verbose:
            print("❌ 无法停止 Kev LaunchAgent，未删除配置。")
        return False
    PLIST_PATH.unlink()
    # Remove the persisted launchd override, ready for a future reinstall.
    subprocess.run(
        ["launchctl", "enable", f"gui/{os.getuid()}/{LABEL}"], capture_output=True
    )
    if verbose:
        print("· 已卸载 Kev LaunchAgent。")
    return True
