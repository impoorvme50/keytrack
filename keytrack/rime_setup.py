"""把 keytrack 的 lua 上屏钩子装进鼠须管（Squirrel / RIME）。

做四件事：
1. 把 rime/keytrack_logger.lua 拷到 ~/Library/Rime/lua/ 下；
2. 找出当前启用的输入方案（default.yaml / default.custom.yaml 的 schema_list）；
3. 往每个方案的 <schema>.custom.yaml 里合并一行
       "engine/processors/@next": lua_processor@*keytrack_logger
   （@* 前缀表示直接从 lua/ 目录加载，不需要改 rime.lua）；
4. 调 `Squirrel --reload` 触发重新部署，让改动生效。

整个过程幂等：重复运行会跳过已装好的部分。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

RIME_DIR = os.path.expanduser("~/Library/Rime")
SQUIRREL_APP = "/Library/Input Methods/Squirrel.app"
SQUIRREL_BIN = os.path.join(SQUIRREL_APP, "Contents/MacOS/Squirrel")

LUA_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rime", "keytrack_logger.lua")
LUA_NAME = "keytrack_logger.lua"
PROCESSOR = "lua_processor@*keytrack_logger"

_BEGIN = "# >>> keytrack（由 kbd setup-ime 管理，勿手动改这一段）"
_END = "# <<< keytrack"
# 依次尝试的插入位置；第一个没被占用的胜出（先后对被动观察者无所谓）
_POSITIONS = ["@next", "@before 0", "@after 0", "@last"]


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


def _merge_custom_yaml(path: str) -> str:
    """把 keytrack 处理器合并进某个 <schema>.custom.yaml。返回状态说明。"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        content = ""

    if PROCESSOR in content:
        return "已挂载，跳过"

    position = next(
        (p for p in _POSITIONS if f'"engine/processors/{p}"' not in content),
        _POSITIONS[-1],
    )
    entry = f'  "engine/processors/{position}": {PROCESSOR}'

    if re.search(r"^patch:\s*\{", content, re.M):
        return "失败：已有行内 patch: {...} 写法，请手动加上 " + entry.strip()

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "patch:":
            lines.insert(i + 1, _BEGIN)
            lines.insert(i + 2, entry)
            lines.insert(i + 3, _END)
            new_content = "\n".join(lines) + "\n"
            break
    else:
        block = f"{_BEGIN}\npatch:\n{entry}\n{_END}\n"
        new_content = content
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        new_content += block

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"已写入（{os.path.basename(path)}，位置 {position}）"


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

    lua_dst = os.path.join(RIME_DIR, "lua", LUA_NAME)
    if os.path.exists(lua_dst) and open(lua_dst, "rb").read() == open(LUA_SRC, "rb").read():
        say(f"· lua 钩子已是最新：{lua_dst}")
    else:
        shutil.copyfile(LUA_SRC, lua_dst)
        say(f"· 已安装 lua 钩子 → {lua_dst}")

    schemas = _find_schemas()
    say(f"· 启用的输入方案：{', '.join(schemas)}")
    ok = True
    for schema in schemas:
        status = _merge_custom_yaml(os.path.join(RIME_DIR, f"{schema}.custom.yaml"))
        say(f"  - {schema}: {status}")
        ok = ok and not status.startswith("失败")

    if redeploy():
        say("· 已触发鼠须管重新部署。")
    else:
        say("⚠️  自动部署没成功：请点菜单栏输入法图标 →「重新部署」（或注销重登）。")

    say("\n验证方法：切到鼠须管，在任意 app 打几个字，然后运行 `kbd ingest` 或 `kbd today`。")
    return ok
