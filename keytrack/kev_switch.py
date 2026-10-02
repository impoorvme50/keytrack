"""Persistent, local on/off switch for the optional Rime Kev hotkey."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import kev_service


ROOT = Path.home() / ".keytrack/kev-rime"
ENABLED_FILE = ROOT / "enabled"


def is_enabled(path: Path = ENABLED_FILE) -> bool:
    try:
        return not path.is_symlink() and path.read_text(encoding="ascii").strip() == "1"
    except (OSError, UnicodeError):
        return False


def set_enabled(value: bool, path: Path = ENABLED_FILE) -> None:
    root = path.parent
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise OSError(f"unsafe Kev switch directory: {root}")
    root.chmod(0o700)
    if path.is_symlink():
        raise OSError(f"unsafe Kev switch path: {path}")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="ascii", dir=root, prefix=".kev-enabled-", delete=False
    ) as output:
        output.write("1\n" if value else "0\n")
        temporary = Path(output.name)
    try:
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def command(action: str) -> bool:
    target = not is_enabled() if action == "toggle" else action == "on"
    if action != "status":
        if target:
            if kev_service.PLIST_PATH.exists() and not kev_service.set_running(True):
                print("Kev 服务启动失败，开关保持关闭。")
                return False
            set_enabled(True)
        else:
            set_enabled(False)
            if not kev_service.set_running(False):
                print("Kev 建议已关闭，但常驻服务未能停止；可运行 uninstall-kev-agent。")
                return False
    active = is_enabled()
    state = "开启" if active else "关闭"
    print(f"Kev 候选建议：{state}")
    if kev_service.PLIST_PATH.exists():
        service_state = "已加载" if kev_service.is_loaded() else "已停止"
        print(f"Kev 专用服务：{service_state}")
    if active:
        from . import kev_rime_setup
        try:
            custom = (kev_rime_setup.RIME_DIR / "rime_ice.custom.yaml").read_text()
        except OSError:
            custom = ""
        print(f"输入拼音后按 {kev_rime_setup.configured_hotkey(custom)} 获取一次建议；再次按可撤销。")
        if not kev_service.PLIST_PATH.exists():
            print("本机未安装 Kev 常驻服务；请先启动 127.0.0.1:8009。")
    else:
        print("普通输入保持原样；已安装的 Kev 专用常驻服务也会停止。")
    return True
