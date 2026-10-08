"""Small configuration mappings for capabilities already supplied by Rime."""
from __future__ import annotations

import json
import re
from pathlib import Path

MODES = ("existing", "on", "off")
FIELDS = ("english_completion", "mixed_completion", "emoji_default")
BEGIN = "# >>> keytrack-input-tools (managed by kbd console)"
END = "# <<< keytrack-input-tools"
NAMES = {"english_completion": "英文补全", "mixed_completion": "中英词补全", "emoji_default": "Emoji 初始状态"}


def validate(settings: dict) -> None:
    for field in FIELDS:
        if settings.get(field, "existing") not in MODES:
            raise ValueError("输入工具选项不正确")


def section(source: str, name: str):
    matches = list(re.finditer(r"^" + re.escape(name) + r":\n(?:[ \t].*\n|\n)*", source, re.M))
    if len(matches) != 1:
        raise ValueError(f"无法安全识别 {name} 配置，请保留原设置")
    return matches[0]


def emoji_item(source: str):
    block = section(source, "switches")
    items = list(re.finditer(r"^  - ", block[0], re.M))
    matches = []
    for index, item in enumerate(items):
        stop = items[index + 1].start() if index + 1 < len(items) else len(block[0])
        text = block[0][item.start():stop]
        if re.match(r'^  - name: [\"\']?emoji[\"\']?(?:\s*#.*)?\n', text):
            matches.append((index, block.start() + item.start(), block.start() + stop, text))
    if len(matches) != 1:
        raise ValueError("未找到唯一的 Emoji 开关，请保留原设置")
    return matches[0]


def current_line(source: str, field: str):
    if field == "emoji_default":
        _, start, stop, fragment = emoji_item(source)
        key, indent = "reset", "    "
    else:
        block = section(source, "melt_eng" if field == "english_completion" else "cn_en")
        start, stop, fragment, key, indent = block.start(), block.end(), block[0], "enable_completion", "  "
    matches = list(re.finditer(r"^" + indent + key + r":[^\n]*(?:\n|$)", fragment, re.M))
    if len(matches) > 1:
        raise ValueError("输入工具配置重复，未覆盖")
    line = matches[0][0] if matches else ""
    if line:
        valid = r"(?:0|1)" if field == "emoji_default" else r"(?:true|false)"
        if not re.fullmatch(indent + key + r":\s*" + valid + r"\s*(?:#.*)?\n?", line):
            raise ValueError("输入工具配置不是支持的标量，未覆盖")
    return start, stop, fragment, key, indent, matches, line


def snapshot_patch(source: str, settings: dict, originals: dict) -> tuple[str, dict]:
    validate(settings)
    originals = dict(originals)
    for field in FIELDS:
        mode = settings.get(field, "existing")
        if mode == "existing" and field not in originals:
            continue
        start, stop, fragment, key, indent, matches, line = current_line(source, field)
        if mode == "existing":
            replacement = originals[field]
        else:
            originals.setdefault(field, line)
            value = str(int(mode == "on")) if field == "emoji_default" else json.dumps(mode == "on")
            replacement = indent + key + ": " + value + "\n"
        if matches:
            found = matches[0]
            fragment = fragment[:found.start()] + replacement + fragment[found.end():]
        elif replacement:
            fragment += replacement
        source = source[:start] + fragment + source[stop:]
    return source, originals


def custom_patch(content: str, settings: dict, source: str) -> str:
    from . import console
    validate(settings)
    if BEGIN in content or END in content:
        if content.count(BEGIN) != 1 or content.count(END) != 1 or content.index(BEGIN) > content.index(END):
            raise ValueError("输入工具管理标记不完整，原配置已保留")
        start, stop = content.index(BEGIN), content.index(END) + len(END)
        if stop < len(content) and content[stop] == "\n":
            stop += 1
        outside = content[:start] + content[stop:]
    else:
        start = stop = -1
        outside = content
    entries = ""
    for field in FIELDS:
        mode = settings.get(field, "existing")
        if mode == "existing":
            continue
        current_line(source, field)  # Refuse unsupported or missing components.
        key = {"english_completion": "melt_eng/enable_completion", "mixed_completion": "cn_en/enable_completion"}.get(field)
        if field == "emoji_default":
            key = f"switches/@{emoji_item(source)[0]}/reset"
            if re.search(r'^\s*(?:[\"\']?switches(?:[\"\']?\s*:|/))', outside, re.M):
                raise ValueError("已有独立开关设置，无法安全管理 Emoji 初始状态")
        if declares_path(outside, key):
            raise ValueError(f"已有设置占用 {key}，没有覆盖")
        entries += console.scalar(key, int(mode == "on") if field == "emoji_default" else mode == "on")
    block = f"{BEGIN}\n{entries}{END}\n" if entries else ""
    if start >= 0:
        return content[:start] + block + content[stop:]
    if not entries:
        return content
    if re.search(r"^patch:\s*\{", content, re.M) or len(re.findall(r"^patch:", content, re.M)) > 1:
        raise ValueError("无法安全合并输入工具配置，原文件已保留")
    lines = content.splitlines(keepends=True)
    patch = next((i for i, line in enumerate(lines) if line.strip() == "patch:"), None)
    if patch is None:
        return content.rstrip("\n") + ("\n" if content else "") + "patch:\n" + block
    stop = next((i for i in range(patch + 1, len(lines)) if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#")), len(lines))
    if stop and not lines[stop - 1].endswith("\n"):
        lines[stop - 1] += "\n"
    lines.insert(stop, block)
    return "".join(lines)


def declares_path(content: str, target: str) -> bool:
    """Include empty and container declarations, which scalar lookup omits."""
    from .console import yaml_scalar
    stack = []
    for line in content.splitlines():
        match = re.match(r'''^( *)("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|[^:#][^:]*):(?:[ \t]+(.*)|[ \t]*)$''', line)
        if not match:
            continue
        indent, raw = len(match[1]), match[3] or ""
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = yaml_scalar(match[2].strip())
        if not isinstance(key, str):
            continue
        path = (stack[-1][1] + "/" if stack else "") + key
        normalized = "/".join(part for part in path.split("/") if part not in ("patch", "+"))
        if normalized == target or (target.startswith(normalized + "/") and raw and not raw.startswith("#")):
            return True
        if not raw or raw.startswith("#"):
            stack.append((indent, path))
    return False


DEMO_SOURCE = "melt_eng:\n  dictionary: melt_eng\ncn_en:\n  enable_completion: true\nswitches:\n  - name: ascii_mode\n    reset: 0\n  - name: emoji\n    reset: 1\n"


def source(rime: Path, demo=False) -> str:
    path = rime / "build/rime_ice.schema.yaml"
    if not path.exists():
        path = rime / "rime_ice.schema.yaml"
    return path.read_text() if path.exists() else DEMO_SOURCE if demo else ""


def catalog(rime: Path, demo=False) -> dict:
    text = source(rime, demo)
    result = {}
    for field in FIELDS:
        try:
            *_, line = current_line(text, field)
            active = (field != "emoji_default" if not line else
                      re.search(r":\s*(?:true|1)(?:\s|$)", line) is not None)
            result[field] = {"available": True, "active": active}
        except ValueError:
            result[field] = {"available": False, "active": False}
    return result
