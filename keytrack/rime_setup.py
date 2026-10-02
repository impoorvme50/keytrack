"""把 keytrack 的 lua 上屏钩子装进鼠须管（Squirrel / RIME）。

做四件事：
1. 把 rime/keytrack_logger.lua 拷到 ~/Library/Rime/lua/ 下；
2. 找出当前启用的输入方案（default.yaml / default.custom.yaml 的 schema_list）；
3. 往每个方案的 <schema>.custom.yaml 里合并一行
       "engine/processors/@before 0": lua_processor@*keytrack_logger
   （@* 前缀表示直接从 lua/ 目录加载，不需要改 rime.lua）；
4. 调 `Squirrel --reload` 触发重新部署，让改动生效。

整个过程幂等：重复运行会跳过已装好的部分。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

RIME_DIR = os.path.expanduser("~/Library/Rime")
SQUIRREL_APP = "/Library/Input Methods/Squirrel.app"
SQUIRREL_BIN = os.path.join(SQUIRREL_APP, "Contents/MacOS/Squirrel")

LUA_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rime", "keytrack_logger.lua")
LUA_NAME = "keytrack_logger.lua"
PROCESSOR = "lua_processor@*keytrack_logger"

_BEGIN = "# >>> keytrack（由 kbd setup-ime 管理，勿手动改这一段）"
_END = "# <<< keytrack"


def _find_schemas(rime_dir: str = RIME_DIR) -> list[str]:
    """从 default.yaml / default.custom.yaml 的 schema_list 里解析启用的方案 id。"""
    schemas: list[str] = []
    seen: set[str] = set()
    for name in ("default.custom.yaml", "default.yaml"):
        path = os.path.join(rime_dir, name)
        if not os.path.exists(path):
            continue
        in_list = False
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("schema_list:"):
                    in_list = True
                    continue
                if in_list:
                    m = re.match(r"-\s*schema:\s*([\w.-]+)", stripped)
                    if m:
                        if m.group(1) not in seen:
                            seen.add(m.group(1))
                            schemas.append(m.group(1))
                        continue
                    if stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                        in_list = False  # schema_list 结束
    if not schemas:  # 全新安装还没部署过：退回鼠须管默认方案
        schemas = ["luna_pinyin"]
    return schemas


def render_custom_yaml(content: str) -> str:
    """Migrate only known hooks; never override an unrelated insertion slot."""
    if re.search(r"^patch:\s*\{", content, re.M):
        raise ValueError("行内 patch 需手动调整")
    hook = re.compile(r'^  [\"\']?engine/processors/(@[^\"\':]+)[\"\']?:\s*([^\s#]+)\s*$', re.M)
    entries = list(hook.finditer(content))
    logger = [m for m in entries if m[2] == PROCESSOR]
    if len(logger) > 1 or (PROCESSOR in content and not logger):
        raise ValueError("采集器配置无法安全迁移")
    for match in entries:
        if match[1] == "@before 0" and match[2] not in (PROCESSOR, "lua_processor@*kev_hotkey"):
            raise ValueError("最前位置已被其他处理器占用")
    # Kev remains before all consuming processors, immediately after the observer.
    for match in entries:
        if match[2] == "lua_processor@*kev_hotkey" and match[1] == "@before 0":
            if any(m[1] == "@before 1" for m in entries):
                raise ValueError("Kev 的迁移位置已被占用")
            if "# >>> kev-rime (managed by kbd setup-kev-rime)" not in content:
                raise ValueError("非托管 Kev 配置需手动调整")
            content = content.replace(match[0], '  "engine/processors/@before 1": lua_processor@*kev_hotkey')
    entry = '  "engine/processors/@before 0": ' + PROCESSOR
    if logger:
        return content.replace(logger[0][0], entry)
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "patch:":
            lines[i + 1:i + 1] = [_BEGIN, entry, _END]
            return "\n".join(lines) + "\n"
    prefix = content if not content or content.endswith("\n") else content + "\n"
    return prefix + f"{_BEGIN}\npatch:\n{entry}\n{_END}\n"


def _write_backed_up(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, path.with_name(path.name + ".bak.keytrack-" + stamp))
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".keytrack-", delete=False) as handle:
        handle.write(data)
        temporary = handle.name
    os.replace(temporary, path)


def _merge_custom_yaml(path: str) -> str:
    target = Path(path)
    try:
        updated = render_custom_yaml(target.read_text() if target.exists() else "")
    except ValueError as exc:
        return "失败：" + str(exc)
    _write_backed_up(target, updated.encode())
    return "已挂载于最前位置"


def installation_ready() -> bool:
    """Both installed source and deployed ordering must match this bundle."""
    root = Path(RIME_DIR)
    try:
        if (root / "lua" / LUA_NAME).read_bytes() != Path(LUA_SRC).read_bytes():
            return False
        for schema in _find_schemas(RIME_DIR):
            deployed = (root / "build" / f"{schema}.schema.yaml").read_text()
            first = re.search(r'processors:\s*\n\s*-\s*["\']?([^"\'\n]+)', deployed)
            if not first or first[1].strip() != PROCESSOR:
                return False
        return True
    except OSError:
        return False


def redeploy() -> bool:
    """触发鼠须管重新部署。失败（多半是没启用/没登录会话）时返回 False。"""
    if not os.path.exists(SQUIRREL_BIN):
        return False
    try:
        result = subprocess.run([SQUIRREL_BIN, "--reload"], check=False, timeout=30, capture_output=True)
        return result.returncode == 0
    except Exception:
        return False


def setup(verbose: bool = True) -> bool:
    def say(*args):
        if verbose:
            print(*args)

    if not os.path.exists(SQUIRREL_APP):
        say("❌ 没找到鼠须管。请先安装：brew install --cask squirrel-app")
        say("   然后在 系统设置 → 键盘 → 输入法 里添加「鼠须管」。")
        return False

    os.makedirs(os.path.join(RIME_DIR, "lua"), exist_ok=True)
    os.makedirs(os.path.expanduser("~/.keytrack"), exist_ok=True)

    schemas = _find_schemas(RIME_DIR)
    # Validate every schema before modifying any source or configuration.
    plans = []
    try:
        for schema in schemas:
            path = Path(RIME_DIR) / f"{schema}.custom.yaml"
            plans.append((path, render_custom_yaml(path.read_text() if path.exists() else "")))
    except ValueError as exc:
        say(f"❌ 配置未改动：{exc}")
        return False
    _write_backed_up(Path(RIME_DIR) / "lua" / LUA_NAME, Path(LUA_SRC).read_bytes())
    for path, updated in plans:
        _write_backed_up(path, updated.encode())
        say(f"· {path.stem}：采集器已放在最前面")

    if redeploy():
        say("· 已触发鼠须管重新部署。")
    else:
        say("⚠️  自动部署没成功：请点菜单栏输入法图标 →「重新部署」（或注销重登）。")

    say("\n验证方法：切到鼠须管，在任意 app 打几个字，然后运行 `kbd ingest` 或 `kbd today`。")
    return True
