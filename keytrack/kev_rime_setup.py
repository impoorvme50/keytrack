"""Install the opt-in Kev candidate reranker into the Rime Ice schema."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import sys
from datetime import datetime
from pathlib import Path

from . import annotations, rime_setup


PROJECT_DIR = Path(__file__).resolve().parent.parent
RIME_DIR = Path(rime_setup.RIME_DIR)
QUEUE_ROOT = Path.home() / ".keytrack/kev-rime"
SCHEMA = "rime_ice"
BEGIN = "# >>> kev-rime (managed by kbd setup-kev-rime)"
END = "# <<< kev-rime"
LUA_FILES = ("kev_context.lua", "kev_hotkey.lua", "kev_filter.lua", *annotations.SHARED_FILES)


def configured_hotkey(content: str) -> str:
    value = re.search(r'"kev_rime/hotkey":\s*"([^"\n]+)"', content)
    return value[1] if value else "Control+Shift+k"


def render_custom_yaml(content: str, python: Path, bridge: Path) -> str:
    """Add or update the managed patch block without disturbing other settings."""
    slot = "@before 1" if re.search(r'engine/processors/@before 0["\']?:\s*lua_processor@\*keytrack_logger', content) else "@before 0"
    outside = content
    if BEGIN in content and END in content:
        outside = content[:content.index(BEGIN)] + content[content.index(END) + len(END):]
    if re.search(r'engine/processors/' + re.escape(slot) + r'["\']?:', outside):
        raise ValueError("Kev insertion position already occupied in custom.yaml")
    entries = (
        f'  "engine/processors/{slot}": lua_processor@*kev_hotkey\n'
        f'  "engine/filters/@last": lua_filter@*kev_filter\n'
        f'  "kev_rime/python": {json.dumps(str(python), ensure_ascii=False)}\n'
        f'  "kev_rime/bridge": {json.dumps(str(bridge), ensure_ascii=False)}\n'
        f'  "kev_rime/hotkey": {json.dumps(configured_hotkey(content))}\n'
    )
    block = f"{BEGIN}\n{entries}{END}\n"
    if BEGIN in content or END in content:
        if content.count(BEGIN) != 1 or content.count(END) != 1:
            raise ValueError("incomplete Kev Rime marker block")
        start = content.index(BEGIN)
        stop = content.index(END, start) + len(END)
        if stop < len(content) and content[stop] == "\n":
            stop += 1
        return content[:start] + block + content[stop:]

    if re.search(r'^\s*"engine/(?:filters/@last)"\s*:', content, re.M):
        raise ValueError("Kev insertion position already occupied in custom.yaml")
    if re.search(r"^patch:\s*\{", content, re.M):
        raise ValueError("inline patch mapping needs manual editing")

    lines = content.splitlines(keepends=True)
    patch_index = next((i for i, line in enumerate(lines) if line.strip() == "patch:"), None)
    if patch_index is None:
        prefix = content if not content or content.endswith("\n") else content + "\n"
        return prefix + "patch:\n" + block

    insert_at = len(lines)
    for i in range(patch_index + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line[0].isspace() and not line.startswith("#"):
            insert_at = i
            break
    lines.insert(insert_at, block)
    return "".join(lines)


def setup(verbose: bool = True) -> bool:
    def say(message: str) -> None:
        if verbose:
            print(message)

    if not Path(rime_setup.SQUIRREL_APP).exists():
        say("❌ 没找到鼠须管。")
        return False
    bundled = bool(getattr(sys, "frozen", False))
    python = Path(sys.executable) if bundled else PROJECT_DIR / ".venv/bin/python"
    bridge = PROJECT_DIR / "rime/kev_bridge.marker" if bundled else PROJECT_DIR / "keytrack/kev_rime_bridge.py"
    if not python.exists() or not bridge.exists():
        say("❌ 缺少 keytrack Python 环境或 Kev 桥接脚本。")
        return False

    custom = RIME_DIR / f"{SCHEMA}.custom.yaml"
    current = custom.read_text(encoding="utf-8") if custom.exists() else ""
    try:
        updated = render_custom_yaml(current, python, bridge)
        overrides = annotations.default_overrides(RIME_DIR)
        annotation_sources = annotations.source_changes(RIME_DIR, filters=True, overrides=overrides,
                                                        previous_overrides=overrides)
    except ValueError as exc:
        say(f"❌ Rime 配置未改动：{exc}")
        return False

    try:
        for directory in (QUEUE_ROOT, QUEUE_ROOT / "requests", QUEUE_ROOT / "responses"):
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            if directory.is_symlink():
                raise OSError(f"unsafe queue path: {directory}")
            directory.chmod(0o700)
    except OSError as exc:
        say(f"❌ 无法创建 Kev 私有队列：{exc}")
        return False

    lua_dir = RIME_DIR / "lua"
    lua_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for name in LUA_FILES:
        source = PROJECT_DIR / "rime" / name
        target = lua_dir / name
        desired = annotation_sources[target].encode() if target in annotation_sources else source.read_bytes()
        if not target.exists() or target.read_bytes() != desired:
            if target.exists():
                backup = target.with_name(f"{target.name}.bak.kev-{stamp}")
                shutil.copy2(target, backup)
                say(f"· 原脚本已备份：{backup}")
            target.write_bytes(desired)
            say(f"· 已安装 {target}")

    if updated != current:
        if custom.exists():
            backup = custom.with_name(f"{custom.name}.bak.kev-{stamp}")
            shutil.copy2(custom, backup)
            say(f"· 原配置已备份：{backup}")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=RIME_DIR, prefix=".kev-rime-", delete=False
        ) as handle:
            handle.write(updated)
            temporary = Path(handle.name)
        os.replace(temporary, custom)
        say(f"· 已更新 {custom}")
    else:
        say("· Kev Rime 配置已是最新。")

    if rime_setup.redeploy():
        say("· 已触发鼠须管重新部署。")
    else:
        say("⚠️ 自动部署未成功，请从鼠须管菜单执行「重新部署」。")
    say(f"· 已保留开关状态；用 `kbd kev on|off` 控制，在拼音候选菜单按 {configured_hotkey(updated)} 获取建议。")
    say("· 只有高把握的建议才会移到首位；再次按快捷键可撤销。")
    return True
