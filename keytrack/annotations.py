"""Small, original local gloss table. No history, network, or inference access."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LANGUAGES = ("off", "en", "ja")
SHARED_FILES = ("keytrack_comments.lua", "keytrack_glossary.lua")
FILTER_FILES = ("kev_filter.lua", "prediction_filter.lua")
BEGIN = "# >>> keytrack-candidate-glossary (managed by kbd console)"
END = "# <<< keytrack-candidate-glossary"
# Exact release files only: an independently edited script is never adopted.
PREVIOUS = {
    "kev_filter.lua": "144299a8437296a466b4049ca64c9bf9d2b02a4d3a54394955dc098708faca21",
    "prediction_filter.lua": "7ec75df8f57b3b4d8a1292fade1623220dcb496d5f42d036ff90b83615cc69ca",
}


def settings_path(rime: Path) -> Path:
    root = Path.home() / ".keytrack/annotations" if rime == Path.home() / "Library/Rime" else rime.parent / "annotations-state"
    return root / "control"


def read_managed(path: Path, limit=2_000_000) -> str:
    system_aliases = {Path("/var"): Path("/private/var"), Path("/tmp"): Path("/private/tmp")}
    if any(p.is_symlink() and system_aliases.get(p) != p.resolve() for p in (path, *path.parents)):
        raise ValueError("释义文件不能使用符号链接，原文件已保留")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("释义文件必须是普通文件，原文件已保留")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("释义文件超出长度限制，原文件已保留")
        return data.decode("utf-8")
    finally:
        os.close(descriptor)


def language(rime: Path) -> str:
    # Console preference state only; the engine reads its compiled schema.
    try:
        text = read_managed(settings_path(rime), 64)
    except (UnicodeError, ValueError):
        return "off"
    found = re.fullmatch(r"language=(off|en|ja)\n", text)
    return found[1] if found else "off"


def entries() -> tuple[str, list[dict]]:
    source = PROJECT / "data/annotations/glossary-v1.json"
    data = source.read_bytes()
    manifest = json.loads((source.parent / "manifest.json").read_text())
    raw = json.loads(data)
    items = raw.get("entries")
    if (raw.get("schema_version") != 1 or raw.get("id") != "keytrack-glossary-v1"
            or not isinstance(items, list) or len(items) != 120
            or manifest.get("source_sha256") != hashlib.sha256(data).hexdigest()
            or manifest.get("entry_count") != len(items)):
        raise ValueError("随应用附带的释义词表未通过校验")
    seen = set()
    for item in items:
        word = item.get("word") if isinstance(item, dict) else None
        if not isinstance(word, str) or not re.fullmatch(r"[\u3400-\u9fff]{1,8}", word) or word in seen:
            raise ValueError("释义词条须为唯一的完整汉字词")
        seen.add(word)
        for key in ("en", "ja", "reading"):
            value = item.get(key, "" if key == "reading" else None)
            if (not isinstance(value, str) or len(value) > 80 or value != value.strip()
                    or (key != "reading" and not value) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise ValueError("释义内容须为简短单行文本")
    return raw["id"], items


def render_lua() -> str:
    version, items = entries()
    lines = [f"-- keytrack-candidate-glossary: managed {version}", "-- Original MIT-licensed metadata; no input-history data.", "return {"]
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    for item in sorted(items, key=lambda v: v["word"]):
        japanese = item["ja"] + ("（" + item["reading"] + "）" if item.get("reading") else "")
        lines.append(f"  [{quote(item['word'])}] = {{ en = {quote(item['en'])}, ja = {quote(japanese)} }},")
    return "\n".join([*lines, "}", ""])


def compose(comment: str, text: str, limit=64) -> str:
    gloss = text if len(text) <= 24 else text[:23] + "…"
    full = comment + (" · " if comment else "") + gloss
    return full if len(full) <= limit else comment


def catalog() -> dict:
    version, items = entries()
    table = {item["word"]: item for item in items}
    examples = []
    for word, comment in (("你好", "✦ AI 建议"), ("朋友", "联想 · 数字/Tab"), ("样品", "")):
        item = table[word]
        japanese = item["ja"] + ("（" + item["reading"] + "）" if item.get("reading") else "")
        examples.append({"text": word, "original_comment": comment,
                         "en_comment": compose(comment, "EN:" + item["en"]),
                         "ja_comment": compose(comment, "日:" + japanese)})
    return {"version": version, "count": len(items), "examples": examples}


def source_changes(rime: Path, filters=False) -> dict[Path, str]:
    """Plan, do not write. Preflight every owned file before a console commit."""
    result = {}
    names = (*SHARED_FILES, *FILTER_FILES) if filters else SHARED_FILES
    for name in names:
        target = rime / "lua" / name
        current = read_managed(target)
        value = (PROJECT / "rime" / name).read_text()
        if name == "keytrack_glossary.lua" and value != render_lua():
            raise ValueError("释义编译结果与源词表不一致")
        if current and current != value and hashlib.sha256(current.encode()).hexdigest() != PREVIOUS.get(name):
            raise ValueError(f"{name} 有独立修改，已保留；请检查后再启用释义")
        result[target] = value
    return result


def render_patch(content: str, selected: str) -> str:
    """Language is compiled into the schema, never read from a FIFO by Lua."""
    from . import console
    if selected not in LANGUAGES:
        raise ValueError("候选释义选项不正确")
    outside = content
    if BEGIN in content or END in content:
        if content.count(BEGIN) != 1 or content.count(END) != 1 or content.index(BEGIN) > content.index(END):
            raise ValueError("候选释义管理标记不完整，原配置已保留")
        start, stop = content.index(BEGIN), content.index(END) + len(END)
        if stop < len(content) and content[stop] == "\n":
            stop += 1
        outside = content[:start] + content[stop:]
    else:
        start, stop = -1, -1
    if "keytrack_glossary/language" in console.yaml_paths(outside) or "keytrack_glossary" in console.yaml_paths(outside):
        raise ValueError("候选释义配置已有独立设置，原配置已保留")
    if start < 0 and selected == "off":
        return content
    block = f'{BEGIN}\n  "keytrack_glossary/language": "{selected}"\n{END}\n'
    if start >= 0:
        return content[:start] + block + content[stop:]
    if re.search(r"^patch:\s*\{", content, re.M) or len(re.findall(r"^patch:", content, re.M)) > 1:
        raise ValueError("候选释义无法安全合并 patch，原配置已保留")
    lines = content.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.strip() == "patch:"), None)
    if index is None:
        return content.rstrip("\n") + ("\n" if content else "") + "patch:\n" + block
    stop = len(lines)
    for i in range(index + 1, len(lines)):
        if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#"):
            stop = i
            break
    if stop and not lines[stop - 1].endswith("\n"):
        lines[stop - 1] += "\n"
    lines.insert(stop, block)
    return "".join(lines)


def schema_language(source: str, selected: str) -> str:
    if selected not in LANGUAGES:
        raise ValueError("候选释义选项不正确")
    block = re.search(r"^keytrack_glossary:\n(?:[ \t].*\n|\n)*", source, re.M)
    if not block:
        if re.search(r"^keytrack_glossary:", source, re.M):
            raise ValueError("联想方案的候选释义配置格式不正确")
        return source if selected == "off" else source.rstrip("\n") + f'\nkeytrack_glossary:\n  language: "{selected}"\n'
    if len(re.findall(r"^keytrack_glossary:", source, re.M)) != 1:
        raise ValueError("联想方案的候选释义配置重复，原文件已保留")
    fragment, count = re.subn(r"^  language:[^\n]*", f'  language: "{selected}"', block[0], flags=re.M)
    if count != 1:
        raise ValueError("无法安全更新联想方案的候选释义语言")
    return source[:block.start()] + fragment + source[block.end():]


def console_changes(rime: Path, selected: str, custom: str | None = None) -> dict[Path, str]:
    if selected not in LANGUAGES:
        raise ValueError("候选释义选项不正确")
    path = settings_path(rime)
    current = read_managed(path, 64)
    result = {}
    daily = rime / "rime_ice.custom.yaml"
    original = read_managed(daily) if custom is None else custom
    patched = render_patch(original, selected)
    if patched != original:
        result[daily] = patched
    if selected != "off":
        from . import kev_rime_setup
        if kev_rime_setup.BEGIN not in read_managed(rime / "rime_ice.custom.yaml"):
            raise ValueError("请先安装输入法扩展，再启用候选释义")
        result.update({target: value for target, value in source_changes(rime, filters=True).items()
                       if read_managed(target) != value})
    if selected != "off" or current:
        value = f"language={selected}\n"
        if current != value:
            result[path] = value
    return result
