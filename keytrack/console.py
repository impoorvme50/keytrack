"""Loopback-only companion console; independent of the recorder and IME process."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import urllib.parse
import webbrowser
import sys
import contextlib
import io
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from . import key_stats
from . import agent, appearance, doctor, kev_rime_setup, kev_switch, layouts, prediction_setup, rime_setup, storage, standalone

PROJECT = Path(__file__).resolve().parent.parent
ZONE = ZoneInfo("Asia/Shanghai")
BEGIN = "# >>> keytrack-console (managed by kbd console)"
END = "# <<< keytrack-console"
THEMES = appearance.THEMES
DEFAULTS = {"theme": "existing", "font_size": 16, "comment_size": 14,
            "font_mode": "existing", "font_face": "", "preedit_mode": "existing",
            "layout": "horizontal", "density": "comfortable", "hotkey": "Control+Shift+k", "apps": []}
HOTKEYS = ("Control+Shift+k", "Control+Alt+k", "Control+Alt+j")
SCHEME_KEYS = ("style/color_scheme", "style/color_scheme_dark")
APPEARANCE_FIELDS = ("font_face", "label_font_face", "comment_font_face", "inline_preedit")


def yaml_scalar(raw: str):
    """Read the small scalar subset we manage, without executing or rewriting YAML."""
    match = re.fullmatch(r'''\s*("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|[^#]*?)\s*(?:#.*)?''', raw)
    if not match:
        raise ValueError("字体或拼音配置不是支持的标量格式，请先检查文件")
    text = match[1].strip()
    if text.startswith('"'):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ValueError("字体或拼音配置使用了不支持的转义，请先检查文件") from exc
    if text.startswith("'"):
        return text[1:-1].replace("''", "'")
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~"):
        return None
    return text


def yaml_paths(content: str) -> dict:
    """Inspect ordinary nested/flat Rime settings; unhandled YAML stays untouched."""
    values, stack = {}, []
    for line in content.splitlines():
        found = re.match(r'''^( *)("(?:\\.|[^"\\])*"|'(?:''|[^'])*'|[^:#][^:]*):(?:[ \t]+(.*)|[ \t]*)$''', line)
        if not found:
            continue
        indent, key, raw = len(found[1]), found[2].strip(), found[3] or ""
        while stack and stack[-1][0] >= indent:
            stack.pop()
        try:
            key = yaml_scalar(key)
        except ValueError:
            continue
        if not isinstance(key, str):
            continue
        path = (stack[-1][1] + "/" if stack else "") + key
        # patch and the Rime merge operator are structural, not parts of a setting path.
        normalized = "/".join(part for part in path.split("/") if part not in ("patch", "+"))
        if not raw or raw.startswith("#"):
            stack.append((indent, path))
            continue
        try:
            value = yaml_scalar(raw)
        except ValueError:
            continue
        if isinstance(value, (str, bool)):
            values[normalized] = value
    return values


def outside_managed(content: str) -> str:
    if BEGIN not in content and END not in content:
        return content
    if content.count(BEGIN) != 1 or content.count(END) != 1:
        raise ValueError("配置管理标记不完整，请先检查文件")
    start, stop = content.index(BEGIN), content.index(END)
    if stop < start:
        raise ValueError("配置管理标记顺序不正确，请先检查文件")
    return content[:start] + content[stop + len(END):]


def appearance_overrides(settings: dict) -> dict:
    values = {}
    if settings.get("font_mode", "existing") != "existing":
        face = settings["font_face"] if settings["font_mode"] == "custom" else ""
        values.update({field: face for field in APPEARANCE_FIELDS[:3]})
    if settings.get("preedit_mode", "existing") != "existing":
        values["inline_preedit"] = settings["preedit_mode"] == "inline"
    schemes = ("keytrack_light", "keytrack_dark") if settings["theme"] != "existing" else settings.get("_appearance_schemes", [])
    # Squirrel applies theme fields after global style fields, so set both levels.
    return {f"{prefix}/{field}": value for prefix in ("style", *(f"preset_color_schemes/{name}" for name in schemes))
            for field, value in values.items()}


def adopt_appearance(content: str, keys: set[str], originals: dict, managed_keys: set[str] | None = None) -> tuple[str, dict]:
    """Migrate only exact direct overrides; retain their original scalar and comments."""
    outside_managed(content)  # Validate markers before inspecting any scalar.
    migrated = dict(originals)
    for key in sorted(keys):
        escaped = re.escape(key)
        spelling = f'(?:"{escaped}"|\'{escaped}\'|{escaped})'
        # Exact two-space entries are direct patch keys. Nested style/theme fields
        # are retained because a slash patch safely overrides their value.
        begin, end = (content.index(BEGIN), content.index(END) + len(END)) if BEGIN in content else (-1, -1)
        found = [match for match in re.finditer(r"^  " + spelling + r":[ \t]*(.*)(?:\n|$)", content, re.M)
                 if not begin <= match.start() < end]
        if len(found) > 1:
            raise ValueError(f"已有重复设置 {key}，没有覆盖")
        if found:
            if found[0][1].lstrip().startswith(("!", "&", "*", "[", "{", "|", ">")):
                raise ValueError(f"已有设置 {key} 不是支持的标量，未修改")
            value = yaml_scalar(found[0][1])
            expected = bool if key.endswith("/inline_preedit") else str
            if type(value) is not expected:
                raise ValueError(f"已有设置 {key} 不是支持的标量，未修改")
            migrated.setdefault(key, found[0][0])
            # Don't overwrite a user's newer direct edit once the key is managed.
            if key in originals or key in (managed_keys or set()):
                raise ValueError(f"已有设置占用 {key}，请刷新并检查外部修改")
            content = content[:found[0].start()] + content[found[0].end():]
    return content, migrated


def original_schemes(content: str) -> dict:
    values = yaml_paths(outside_managed(content))
    return {key: values[key] for key in SCHEME_KEYS if isinstance(values.get(key), str)
            and re.fullmatch(r"[\w-]+", values[key])}


def adopt_schemes(content: str) -> str:
    # These two explicit controls are migrated into our block, with originals in the backup.
    for key in SCHEME_KEYS:
        escaped = re.escape(key)
        spelling = f'(?:"{escaped}"|\'{escaped}\'|{escaped})'
        begin, end = (content.index(BEGIN), content.index(END) + len(END)) if BEGIN in content else (-1, -1)
        matches = [match for match in re.finditer(r'^  ' + spelling + r''':[ \t]*(?:[\w-]+|"[\w-]+"|'[\w-]+')[ \t]*(?:#.*)?\n?''', content, re.M)
                   if not begin <= match.start() < end]
        for match in reversed(matches):
            content = content[:match.start()] + content[match.end():]
    return content


def managed(content: str, entries: str | None) -> str:
    """Only update our block, preserving all user text, comments and unrelated patches."""
    block = f"{BEGIN}\n{entries}{END}\n" if entries else ""
    outside = outside_managed(content)
    for key in yaml_paths(entries or ""):
        escaped = re.escape(key)
        spelling = f'(?:"{escaped}"|\'{escaped}\'|{escaped})'
        if re.search(r'^\s*' + spelling + r'\s*:', outside, re.M):
            raise ValueError(f"已有设置占用 {key}，没有覆盖")
    if BEGIN in content or END in content:
        start = content.index(BEGIN)
        stop = content.index(END, start) + len(END)
        if stop < len(content) and content[stop] == "\n":
            stop += 1
        return content[:start] + block + content[stop:]
    if not entries:
        return content
    if re.search(r"^patch:\s*\{", content, re.M):
        raise ValueError("当前配置使用行内 patch，请先改为分行格式")
    lines = content.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.strip() == "patch:"), None)
    if index is None:
        return content.rstrip("\n") + ("\n" if content else "") + "patch:\n" + block
    stop = len(lines)
    for i in range(index + 1, len(lines)):
        if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#"):
            stop = i
            break
    lines.insert(stop, block)
    return "".join(lines)


def scalar(key: str, value) -> str:
    return f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}\n"


def color(value: str) -> str:
    rgb = value.lstrip("#")
    return "0x" + rgb[4:6] + rgb[2:4] + rgb[0:2]


def appearance_patch(settings: dict) -> str:
    entries = scalar("style/font_point", settings["font_size"])
    entries += scalar("style/comment_font_point", settings["comment_size"])
    entries += scalar("style/label_font_point", max(11, settings["font_size"] - 3))
    entries += scalar("style/candidate_list_layout", "linear" if settings["layout"] == "horizontal" else "stacked")
    entries += scalar("style/corner_radius", 9)
    entries += scalar("style/hilited_corner_radius", 6)
    entries += scalar("style/line_spacing", 4 if settings["density"] == "compact" else 8)
    entries += scalar("style/spacing", 5 if settings["density"] == "compact" else 10)
    if settings["theme"] != "existing":
        for suffix in ("light", "dark"):
            theme = {"name": f"Keytrack {suffix}", "author": "Keytrack",
                     **{field: color(rgb) for field, rgb in THEMES[settings["theme"]][suffix].items()}}
            # Hex colors are native Rime scalars, not quoted strings.
            rendered = json.dumps(theme, ensure_ascii=False)
            rendered = re.sub(r'"(0x[0-9a-f]+)"', r'\1', rendered)
            entries += f'  "preset_color_schemes/keytrack_{suffix}": {rendered}\n'
        entries += scalar("style/color_scheme", "keytrack_light")
        entries += scalar("style/color_scheme_dark", "keytrack_dark")
    else:
        for key, value in settings.get("_original_schemes", {}).items():
            entries += scalar(key, value)
    overrides = appearance_overrides(settings)
    for key, line in settings.get("_original_appearance", {}).items():
        if key not in overrides:
            entries += line
    entries += ''.join(scalar(key, value) for key, value in overrides.items())
    for app in settings["apps"]:
        entries += scalar(f"app_options/{app['bundle']}/ascii_mode", app["english"])
    return entries


def validate_settings(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("设置格式不正确")
    value = {key: raw.get(key, default) for key, default in DEFAULTS.items()}
    for name, lo, hi in (("font_size", 12, 28), ("comment_size", 10, 24)):
        if type(value[name]) is not int or not lo <= value[name] <= hi:
            raise ValueError("字号超出允许范围")
    if value["theme"] not in ("existing", *THEMES) or value["layout"] not in ("horizontal", "vertical"):
        raise ValueError("外观选项不正确")
    if value["density"] not in ("compact", "comfortable") or value["hotkey"] not in HOTKEYS:
        raise ValueError("间距或快捷键选项不正确")
    if value["font_mode"] not in ("existing", "system", "custom") or value["preedit_mode"] not in ("existing", "inline", "candidate"):
        raise ValueError("字体或拼音显示选项不正确")
    face = value["font_face"]
    if (not isinstance(face, str) or len(face) > 160 or face != face.strip()
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in face)
            or (value["font_mode"] == "custom" and not face)
            or any(not part.strip() for part in face.split(",")) and bool(face)):
        raise ValueError("字体名称须为 1–160 字，不能包含控制字符或空回退项")
    if not isinstance(value["apps"], list) or len(value["apps"]) > 30:
        raise ValueError("应用设置最多 30 项")
    seen = set()
    for item in value["apps"]:
        if (not isinstance(item, dict) or not isinstance(item.get("bundle"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", item["bundle"])
                or len(item["bundle"]) > 160 or type(item.get("english")) is not bool):
            raise ValueError("应用标识或中英文状态不正确")
        if item["bundle"] in seen:
            raise ValueError("同一应用不能重复设置")
        seen.add(item["bundle"])
    return value


def validate_phrases(raw: object) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 300:
        raise ValueError("常用语最多 300 条")
    result, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("常用语格式不正确")
        code, text, category = item.get("code"), item.get("text"), item.get("category", "常用")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z]{2,20}", code):
            raise ValueError("短编码须为 2–20 位小写英文字母")
        if code.startswith(("v", "u")):
            raise ValueError("编码不要以 v 或 u 开头，它们用于符号和特殊输入")
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or any(ord(ch) < 32 and ch not in "\n\t" for ch in text)):
            raise ValueError("常用语不能为空，最多 2000 字")
        if not isinstance(category, str) or not category.strip() or len(category) > 18 or any(ord(ch) < 32 for ch in category):
            raise ValueError("分类须为 1–18 字")
        if code in seen:
            raise ValueError(f"编码 {code} 重复，请使用不同编码")
        seen.add(code)
        result.append({"code": code, "text": text, "category": category.strip()})
    return result


def phrase_lua(items: list[dict]) -> str:
    lines = ["-- Managed by Keytrack console; UTF-8, no executable user content.\nreturn {\n"]
    for item in items:
        fields = ", ".join(f"{key} = {json.dumps(item[key], ensure_ascii=False)}" for key in ("code", "text", "category"))
        lines.append("  {" + fields + "},\n")
    return "".join(lines) + "}\n"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def atomic(path: Path, text: str):
    if path.is_symlink():
        raise ValueError("不能覆盖符号链接，请检查保存位置")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("保存目录不能是符号链接")
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as stream:
        stream.write(text)
        temp = Path(stream.name)
    try:
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ConsoleStore:
    def __init__(self, state_dir: Path | None = None, rime_dir: Path | None = None, db: str = storage.DEFAULT_DB_PATH, demo=False):
        self.root = state_dir or Path.home() / ".keytrack/console"
        self.rime = rime_dir or Path(rime_setup.RIME_DIR)
        self.db, self.demo = db, demo
        self.lock = threading.RLock()
        self._demo_prediction = {"enabled": False, "installed": True, "max_candidates": 3,
                                 "max_iterations": 1, "schema_id": "rime_ice_predict",
                                 "schema_name": prediction_setup.TITLE}
        self.targets = {"settings.json": self.root / "settings.json", "phrases.json": self.root / "phrases.json",
                        "squirrel.custom.yaml": self.rime / "squirrel.custom.yaml",
                        "rime_ice.custom.yaml": self.rime / "rime_ice.custom.yaml",
                        "keytrack_phrases_data.lua": self.rime / "lua/keytrack_phrases_data.lua"}

    def revision(self) -> str:
        payload = "\0".join(key + "\0" + read_text(path) for key, path in self.targets.items())
        control = json.dumps(self._demo_prediction, sort_keys=True) if self.demo else read_text(prediction_setup.settings_path(self.rime))
        payload += "\0prediction\0" + control
        payload += "\0prediction_schema\0" + read_text(self.rime / f"{prediction_setup.SCHEMA}.schema.yaml")
        return hashlib.sha256(payload.encode()).hexdigest()

    def prediction_state(self) -> dict:
        return dict(self._demo_prediction) if self.demo else prediction_setup.state(rime_dir=self.rime)

    def appearance_source(self, settings: dict) -> dict:
        paths = [] if self.demo else [Path(rime_setup.SQUIRREL_APP) / "Contents/SharedSupport/squirrel.yaml"]
        paths.append(self.rime / "squirrel.yaml")
        values = {}
        for path in paths:
            values.update(yaml_paths(read_text(path)))
        values.update(yaml_paths(outside_managed(read_text(self.targets["squirrel.custom.yaml"]))))
        values.update(settings.get("_original_schemes", {}))
        for key, line in settings.get("_original_appearance", {}).items():
            values.update(yaml_paths(line))
        return values

    def appearance_baseline(self, settings: dict) -> dict:
        values = self.appearance_source(settings)
        style = {"font_face": values.get("style/font_face", ""),
                 "inline_preedit": values.get("style/inline_preedit", True)}
        result = {"style": style}
        for mode, key in (("light", SCHEME_KEYS[0]), ("dark", SCHEME_KEYS[1])):
            name = values.get(key, values.get(SCHEME_KEYS[0], ""))
            result[mode] = {field: values.get(f"preset_color_schemes/{name}/{field}", value)
                            for field, value in style.items()}
        # Unsupported scalar shapes are labelled unknown rather than advertised
        # as an installed font or a confirmed input-method display setting.
        for sample in result.values():
            if not isinstance(sample["font_face"], str):
                sample["font_face"] = ""
            if type(sample["inline_preedit"]) is not bool:
                sample["inline_preedit"] = True
        return result

    def state(self) -> dict:
        settings = json.loads(read_text(self.targets["settings.json"]) or "null")
        if settings is None:
            settings = dict(DEFAULTS)
            custom = read_text(self.targets["squirrel.custom.yaml"])
            settings["_original_schemes"] = original_schemes(custom)
            settings["hotkey"] = kev_rime_setup.configured_hotkey(read_text(self.targets["rime_ice.custom.yaml"]))
            font = re.search(r'(?m)^\s*font_point:\s*(\d+)', custom)
            if font:
                settings["font_size"] = int(font.group(1))
        else:
            # Old clients/settings retain their choices while the new independent
            # controls start in preserve mode. Never reinitialize old preferences.
            settings = dict(DEFAULTS, **settings)
        phrases = json.loads(read_text(self.targets["phrases.json"]) or "[]")
        if self.demo:
            status = {"kev_enabled": False, "recorder": {"running": True}, "demo": True}
        else:
            status = {"kev_enabled": kev_switch.is_enabled(), "recorder": agent.service_status(), "demo": False}
        prediction = self.prediction_state()
        return {"settings": settings, "phrases": phrases, "revision": self.revision(), "status": status,
                "appearance_themes": appearance.catalog(),
                "appearance_baseline": self.appearance_baseline(settings),
                "prediction": prediction,
                "today": datetime.now(ZONE).date().isoformat(), "deployment": self.deployment(),
                "installation": {"packaged": False, "configured": True, "can_install": False} if self.demo else standalone.status()}

    def save_prediction(self, request: dict) -> dict:
        """This independent switch never changes Kev or starts its model service."""
        enabled = request.get("enabled")
        candidates = request.get("max_candidates", 3)
        iterations = request.get("max_iterations", 1)
        if type(enabled) is not bool:
            raise ValueError("联想开关状态不正确")
        if type(candidates) is not int or not 1 <= candidates <= 5:
            raise ValueError("联想候选须为 1–5 个")
        if type(iterations) is not int or iterations != 1:
            raise ValueError("实验版连续联想最多一轮")
        if self.demo:
            self._demo_prediction.update(enabled=enabled, max_candidates=candidates, max_iterations=iterations)
            return {"message": "演示：本地接词联想已开启" if enabled else "演示：本地接词联想已关闭"}
        return prediction_setup.set_settings(enabled=enabled, max_candidates=candidates,
                                             max_iterations=iterations, rime_dir=self.rime)

    def deployment(self) -> dict:
        pending = False
        for name in ("squirrel", "rime_ice"):
            source, built = self.rime / f"{name}.custom.yaml", self.rime / "build" / f"{name}.yaml"
            if name == "rime_ice":
                built = self.rime / "build/rime_ice.schema.yaml"
            if BEGIN not in read_text(source):
                continue
            if not built.exists() or built.stat().st_mtime < source.stat().st_mtime:
                pending = True
        prediction = self.rime / f"{prediction_setup.SCHEMA}.schema.yaml"
        prediction_built = self.rime / "build" / prediction.name
        if read_text(prediction).startswith(prediction_setup.HEADER):
            if not prediction_built.exists() or prediction_built.stat().st_mtime < prediction.stat().st_mtime:
                pending = True
        return {"pending": pending, "message": "等待重新部署" if pending else "已部署的配置可用"}

    def backups(self) -> list[dict]:
        result = []
        for file in sorted((self.root / "backups").glob("*.json"), reverse=True)[:50]:
            try:
                raw = json.loads(file.read_text())
                result.append({"id": file.stem, "created": raw["created"], "reason": raw["reason"]})
            except (OSError, ValueError, KeyError):
                continue
        return result

    def backup(self, reason: str) -> str:
        now = datetime.now(ZONE)
        identifier = now.strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(2)
        prediction = self.prediction_state()
        snapshot = {"created": now.isoformat(), "reason": reason,
                    "files": {key: read_text(path) for key, path in self.targets.items()},
                    "prediction": {key: prediction[key]
                                   for key in ("enabled", "max_candidates", "max_iterations")}}
        atomic(self.root / "backups" / f"{identifier}.json", json.dumps(snapshot, ensure_ascii=False, indent=2))
        return identifier

    def commit(self, changes: dict[Path, str], reason: str, revision: str, prediction: dict | None = None) -> dict:
        if revision != self.revision():
            raise ValueError("设置已被其他窗口或编辑器修改，请刷新后再保存")
        previous = {path: read_text(path) for path in changes}
        previous_prediction = self.prediction_state() if prediction is not None else None
        identifier = self.backup(reason)
        written = []
        prediction_changed = False
        try:
            for path, content in changes.items():
                if read_text(path) != previous[path]:
                    raise ValueError("文件在保存过程中发生变化，操作已停止")
                atomic(path, content)
                written.append(path)
            if prediction is not None:
                self.save_prediction(prediction)
                prediction_changed = True
        except Exception:
            if prediction_changed:
                self.save_prediction(previous_prediction)
            for path in reversed(written):
                atomic(path, previous[path])
            raise
        requested = True if self.demo else rime_setup.redeploy()
        return {"saved": True, "deployment_requested": requested, "backup": identifier,
                "message": "已保存并请求重新部署" if requested else "已保存，自动部署未成功，请重试部署"}

    def save_settings(self, raw: dict, revision: str) -> dict:
        if revision != self.revision():
            raise ValueError("设置已被其他窗口或编辑器修改，请刷新后再保存")
        current = self.state()["settings"]
        if isinstance(raw, dict):
            raw = dict(raw)
            for key in ("font_mode", "font_face", "preedit_mode"):
                raw.setdefault(key, current[key])
        settings = validate_settings(raw)
        settings["_original_schemes"] = current.get("_original_schemes", {})
        source = self.appearance_source(current)
        if (settings["theme"] == "existing" and (settings["font_mode"] != "existing" or settings["preedit_mode"] != "existing")
                and ("style" in source or any(key in source and (not isinstance(source[key], str)
                     or not re.fullmatch(r"[\w-]{1,128}", source[key])) for key in SCHEME_KEYS))):
            raise ValueError("原配色使用了不支持的 style 格式，无法确认字体覆盖范围；请先检查配置")
        settings["_appearance_schemes"] = sorted({source[key] for key in SCHEME_KEYS if isinstance(source.get(key), str)
                                                 and re.fullmatch(r"[\w-]{1,128}", source[key])})
        content, originals = adopt_appearance(read_text(self.targets["squirrel.custom.yaml"]),
                                             set(appearance_overrides(settings)), current.get("_original_appearance", {}),
                                             set(appearance_overrides(current)))
        settings["_original_appearance"] = originals
        content = managed(adopt_schemes(content), appearance_patch(settings))
        custom = read_text(self.targets["rime_ice.custom.yaml"])
        if kev_rime_setup.BEGIN not in custom:
            raise ValueError("请先安装 Kev 钩子，再设置快捷键")
        begin, end = custom.index(kev_rime_setup.BEGIN), custom.index(kev_rime_setup.END)
        fragment = custom[begin:end]
        fragment = re.sub(r'("kev_rime/hotkey":\s*)"[^"\n]*"', lambda m: m[1] + json.dumps(settings["hotkey"]), fragment)
        custom = custom[:begin] + fragment + custom[end:]
        changes = {self.targets["settings.json"]: json.dumps(settings, ensure_ascii=False, indent=2),
                   self.targets["squirrel.custom.yaml"]: content,
                   self.targets["rime_ice.custom.yaml"]: custom}
        changes.update(prediction_setup.console_schema_changes(self.rime, hotkey=settings["hotkey"]))
        return self.commit(changes, "更新外观与输入设置", revision)

    def save_phrases(self, raw, revision: str) -> dict:
        items = validate_phrases(raw)
        entries = scalar("engine/translators/@last", "lua_translator@*keytrack_phrases")
        custom = managed(read_text(self.targets["rime_ice.custom.yaml"]), entries)
        changes = {self.targets["phrases.json"]: json.dumps(items, ensure_ascii=False, indent=2),
                   self.targets["keytrack_phrases_data.lua"]: phrase_lua(items),
                   self.rime / "lua/keytrack_phrases.lua": (PROJECT / "rime/keytrack_phrases.lua").read_text(),
                   self.targets["rime_ice.custom.yaml"]: custom}
        changes.update(prediction_setup.console_schema_changes(self.rime, phrases=True))
        return self.commit(changes, "更新常用语", revision)

    def restore(self, identifier: str, revision: str) -> dict:
        if not re.fullmatch(r"\d{8}-\d{6}-\d{6}-[a-f0-9]{4}", identifier):
            raise ValueError("备份编号不正确")
        snapshot = json.loads((self.root / "backups" / f"{identifier}.json").read_text())
        files = snapshot["files"]
        changes = {}
        restored_hotkey = None
        for key, path in self.targets.items():
            previous = files.get(key, "")
            if key.endswith("custom.yaml"):
                entries = None
                if BEGIN in previous:
                    entries = previous.split(BEGIN + "\n", 1)[1].split(END, 1)[0]
                elif key == "squirrel.custom.yaml":
                    entries = ''.join(scalar(k, v) for k, v in original_schemes(previous).items()) or None
                    original_keys = set(self.state()["settings"].get("_original_appearance", {}))
                    _, originals = adopt_appearance(previous, original_keys, {})
                    entries = (entries or "") + ''.join(originals.values()) or None
                value = managed(read_text(path), entries)
                if key == "rime_ice.custom.yaml":
                    # Restore only the managed Kev hotkey, never unrelated configuration.
                    previous_hotkey = re.search(r'"kev_rime/hotkey":\s*"([^"\n]+)"', previous)
                    if previous_hotkey:
                        restored_hotkey = previous_hotkey[1]
                        value = re.sub(r'("kev_rime/hotkey":\s*)"[^"\n]*"', lambda m: m[1] + json.dumps(previous_hotkey[1]), value)
            else:
                value = previous or ("[]" if key == "phrases.json" else "null" if key == "settings.json" else "return {}\n")
            changes[path] = value
        changes.update(prediction_setup.console_schema_changes(self.rime, hotkey=restored_hotkey,
                       phrases="keytrack_phrases" in files.get("rime_ice.custom.yaml", "")))
        return self.commit(changes, "恢复控制台配置", revision, prediction=snapshot.get("prediction"))

    def report(self, day_string: str, include_text=False) -> dict:
        day = date.fromisoformat(day_string)
        start = datetime.combine(day, datetime.min.time(), ZONE).timestamp()
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), ZONE).timestamp()
        blank = {"day": day_string, "total_chars": 0, "segment_count": 0, "active_minutes": None, "cpm": None,
                 "total_keys": 0, "correction_rate": None, "apps": [], "hours": [], "trend": [],
                 "calendar": [], "key_frequency": {}, "fingers": [], "keyboard": layouts.ANSI_ROWS,
                 "segments": None, "segment_limit": 500, "key_quality": {"status": "empty", "reliable": False, "message": "这一天还没有按键记录。", "scope": key_stats.SCOPE, "first_verified_minute": None, "mapped_keys": 0, "unmapped_keys": 0}}
        path = Path(self.db).resolve()
        if not path.exists():
            return blank
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN")
            summary = conn.execute("SELECT COUNT(*), COALESCE(SUM(key_count),0) FROM segments WHERE start_ts>=? AND start_ts<?", (start, end)).fetchone()
            counts = {row[0]: row[1] for row in conn.execute("SELECT key,count FROM key_counts WHERE day=?", (day_string,))}
            minutes = list(conn.execute("SELECT minute,count FROM key_minutes WHERE minute LIKE ? AND count>0", (day_string + "T%",)))
            apps = [{"name": row[0], "chars": row[1]} for row in conn.execute("SELECT app,SUM(key_count) AS chars FROM segments WHERE start_ts>=? AND start_ts<? GROUP BY app ORDER BY chars DESC", (start, end))]
            today = datetime.now(ZONE).date()
            first = today - timedelta(days=90)
            first_ts = datetime.combine(first, datetime.min.time(), ZONE).timestamp()
            per_day = {row[0]: row[1] for row in conn.execute("SELECT date(start_ts,'unixepoch','+8 hours'), SUM(key_count) FROM segments WHERE start_ts>=? GROUP BY 1", (first_ts,))}
            all_days = {row[0] for row in conn.execute("SELECT DISTINCT day FROM key_counts WHERE day>=?", (first.isoformat(),))}
            calendar = []
            for index in range(91):
                item = first + timedelta(days=index)
                calendar.append({"day": item.isoformat(), "chars": per_day.get(item.isoformat(), 0), "has_keys": item.isoformat() in all_days})
            hours = [0] * 24
            for minute, count in minutes:
                hours[int(minute[11:13])] += count
            normalized = {}
            fingers = {key: 0 for key in layouts.FINGER_NAMES}
            mapping = {key: finger for row in layouts.ANSI_ROWS for key, _, _, finger in row}
            for key, count in counts.items():
                physical = layouts.norm_key(key)
                if physical:
                    normalized[physical] = normalized.get(physical, 0) + count
                    fingers[mapping[physical]] += count
            quality = key_stats.quality(conn, day_string, counts)
            valid = quality["reliable"]
            deleted = sum(n for k, n in counts.items() if layouts.norm_key(k) == "backspace")
            total = sum(counts.values())
            blank.update(total_chars=summary[1], segment_count=summary[0], active_minutes=len(minutes) if valid else None,
                         cpm=round(summary[1] / len(minutes), 1) if minutes and valid else None,
                         total_keys=total, correction_rate=round(deleted / total * 100, 1) if total and valid else None,
                         key_quality=quality, apps=apps, hours=hours if valid else [], calendar=calendar, trend=calendar[-14:], key_frequency=normalized,
                         fingers=[{"name": layouts.FINGER_NAMES[k], "count": v} for k, v in fingers.items()] if valid else [])
            if include_text:
                blank["segments"] = [{"app": row[0], "time": datetime.fromtimestamp(row[1], ZONE).strftime("%H:%M"), "text": row[2]} for row in conn.execute("SELECT app,start_ts,text FROM segments WHERE start_ts>=? AND start_ts<? ORDER BY start_ts DESC LIMIT 500", (start, end))]
            return blank
        finally:
            conn.close()


class ConsoleHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass # No request URLs, tokens, or input text in access logs.

    def reply(self, status: int, data, content_type="application/json; charset=utf-8"):
        body = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return secrets.compare_digest(self.headers.get("X-Keytrack-Token", ""), self.server.token)

    def host_ok(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.host_ok():
            return self.reply(403, {"error": "访问来源不正确"})
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path in ("/", "/console.css", "/console.js"):
            name = "index.html" if path == "/" else path[1:]
            types = {"index.html": "text/html; charset=utf-8", "console.css": "text/css; charset=utf-8", "console.js": "text/javascript; charset=utf-8"}
            return self.reply(200, (PROJECT / "ui" / name).read_text(), types[name])
        if not self.authorized():
            return self.reply(403, {"error": "请从 Keytrack 窗口重新打开控制台"})
        try:
            with self.server.store.lock:
                if path == "/api/state":
                    data = self.server.store.state()
                elif path == "/api/report":
                    query = urllib.parse.parse_qs(parsed.query)
                    data = self.server.store.report(query.get("day", [datetime.now(ZONE).date().isoformat()])[0], query.get("text", ["0"])[0] == "1")
                elif path == "/api/backups":
                    data = {"backups": self.server.store.backups()}
                elif path == "/api/doctor":
                    data = {"checks": [{"level": "ok", "message": "演示环境：交互仅修改测试配置"}]} if self.server.store.demo else {"checks": doctor.checks()}
                else:
                    return self.reply(404, {"error": "页面不存在"})
            self.reply(200, data)
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
            self.reply(400, {"error": "读取失败，请检查配置或数据库是否可用"})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        allowed = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
        if not self.host_ok() or not self.authorized() or origin not in allowed:
            return self.reply(403, {"error": "请在本机控制台中操作"})
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            return self.reply(400, {"error": "请求格式不正确"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("请求过大或为空")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("请求格式不正确")
            with self.server.store.lock:
                store = self.server.store
                if self.path == "/api/settings":
                    result = store.save_settings(data.get("settings"), data.get("revision"))
                elif self.path == "/api/phrases":
                    result = store.save_phrases(data.get("phrases"), data.get("revision"))
                elif self.path == "/api/restore":
                    result = store.restore(data.get("id", ""), data.get("revision"))
                elif self.path == "/api/backup":
                    result = {"message": "备份已保存到本机", "backup": store.backup("手动备份")}
                elif self.path == "/api/redeploy":
                    ok = True if store.demo else rime_setup.redeploy()
                    result = {"message": "已请求重新部署" if ok else "重新部署未成功，请从鼠须管菜单重试"}
                elif self.path == "/api/kev":
                    value = data.get("enabled")
                    if type(value) is not bool:
                        raise ValueError("开关状态不正确")
                    if store.demo:
                        result = {"message": "演示：已验证开关请求，未改变本机 AI 状态"}
                    else:
                        if not kev_switch.command("on" if value else "off"):
                            raise ValueError("开关设置失败，请查看诊断")
                        result = {"message": "AI 建议已开启" if value else "AI 建议已关闭"}
                else:
                    return self.reply(404, {"error": "操作不存在"})
            self.reply(200, result)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "保存失败，请检查文件权限；没有完成操作"
            self.reply(400, {"error": message})


def demo_store() -> tuple[ConsoleStore, tempfile.TemporaryDirectory]:
    temp = tempfile.TemporaryDirectory(prefix="keytrack-console-demo-")
    root = Path(temp.name)
    rime = root / "Rime"
    (rime / "lua").mkdir(parents=True)
    python = PROJECT / ".venv/bin/python"
    (rime / "rime_ice.custom.yaml").write_text(kev_rime_setup.render_custom_yaml("", python, PROJECT / "keytrack/kev_rime_bridge.py"))
    db = root / "demo.db"
    with storage.connect(str(db)) as conn:
        today = datetime.now(ZONE).date()
        for index in range(91):
            day = today - timedelta(days=index)
            if index % 7 == 3:
                continue
            base = datetime.combine(day, datetime.min.time(), ZONE).timestamp()
            for hour, app in ((9, "ZCode"), (11, "飞书"), (14, "邮件"), (16, "微信")):
                text = "这是一段用于检查页面展示的示例文字，不是真实输入记录。" * (2 + (index * 13 + hour) % 9)
                storage.insert_segment(conn, app, None, base + hour * 3600, base + hour * 3600 + 120, text, len(text))
                from .ime_ingest import store_key_buckets
                store_key_buckets(conn, [{"min": f"{day}T{hour:02d}:{minute:02d}", "capture_version": 3,
                    "keys": {"a": 8, "e": 10, "i": 4, "n": 6, "o": 5, "space": 3, "BackSpace": 1,
                             "comma": 1, "Super+Super_L": 1, "Super+a": 1, "Left": 1}}
                    for minute in range(20)])
    store = ConsoleStore(root / "console", rime, str(db), demo=True)
    items = [{"code": "qreply", "category": "工作回复", "text": "收到，谢谢。我会核对后回复。"},
             {"code": "qsample", "category": "外贸", "text": "Thank you for your inquiry. We will confirm the sample details shortly."}]
    atomic(store.targets["phrases.json"], json.dumps(items, ensure_ascii=False))
    return store, temp


def serve(port=0, db=storage.DEFAULT_DB_PATH, demo=False, open_browser=True):
    cleanup = None
    if demo:
        store, cleanup = demo_store()
    else:
        store = ConsoleStore(db=db)
    server = ThreadingHTTPServer(("127.0.0.1", port), ConsoleHandler)
    server.token = secrets.token_urlsafe(32)
    server.store = store
    url = f"http://127.0.0.1:{server.server_port}/#token={server.token}"
    print(json.dumps({"url": url}), flush=True) # Native launcher reads this pipe, not an access log.
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if cleanup:
            cleanup.cleanup()


def launch() -> bool:
    bundle = standalone.app_bundle() if getattr(sys, "frozen", False) else PROJECT / "dist/Keytrack.app"
    if bundle is None or not bundle.exists():
        print("请先运行 scripts/build-console.sh 构建 Keytrack 窗口。")
        return False
    return subprocess.run(["open", str(bundle)], check=False).returncode == 0


def native_request(store: ConsoleStore, request: dict) -> dict:
    """Native UI uses private process pipes, with no listening socket or web view."""
    if not isinstance(request, dict):
        raise ValueError("请求格式不正确")
    action = request.get("action")
    with store.lock:
        if action == "state":
            return store.state()
        if action == "report":
            return store.report(request.get("day", datetime.now(ZONE).date().isoformat()), request.get("text") is True)
        if action == "backups":
            return {"backups": store.backups()}
        if action == "doctor":
            return {"checks": [{"level": "ok", "message": "演示环境：仅修改测试配置"}]} if store.demo else {"checks": doctor.checks()}
        if action == "install":
            if store.demo:
                raise ValueError("演示模式不会安装后台服务")
            return standalone.install(store)
        if action == "settings":
            return store.save_settings(request.get("settings"), request.get("revision"))
        if action == "phrases":
            return store.save_phrases(request.get("phrases"), request.get("revision"))
        if action == "prediction":
            return store.save_prediction(request)
        if action == "prediction_install":
            if store.demo:
                raise ValueError("演示模式不会安装实际联想方案")
            if not prediction_setup.setup(verbose=False, rime_dir=store.rime):
                raise ValueError("本地联想安装未完成，请查看诊断后重试")
            return {"message": "本地联想实验方案已安装，开关仍保持当前设置"}
        if action == "restore":
            return store.restore(request.get("id", ""), request.get("revision"))
        if action == "backup":
            return {"message": "备份已保存到本机", "backup": store.backup("手动备份")}
        if action == "redeploy":
            ok = store.demo or rime_setup.redeploy()
            return {"message": "已请求重新部署" if ok else "重新部署未成功，请从鼠须管菜单重试"}
        if action == "kev":
            value = request.get("enabled")
            if type(value) is not bool:
                raise ValueError("开关状态不正确")
            if store.demo:
                return {"message": "演示模式没有改变本机 AI 状态"}
            if not kev_switch.command("on" if value else "off"):
                raise ValueError("开关设置失败，请查看诊断")
            return {"message": "AI 建议已开启" if value else "AI 建议已关闭"}
    raise ValueError("操作不存在")


def native_serve(db=storage.DEFAULT_DB_PATH, demo=False):
    store, cleanup = demo_store() if demo else (ConsoleStore(db=db), None)
    try:
        while True:
            line = sys.stdin.buffer.readline(2_000_002)
            if not line:
                break
            try:
                if len(line) > 2_000_000 or not line.endswith(b"\n"):
                    raise ValueError("请求过大或不完整")
                with contextlib.redirect_stdout(io.StringIO()):
                    result = native_request(store, json.loads(line))
                response = {"ok": True, "data": result}
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
                response = {"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "操作未完成，请检查配置和文件权限"}
            print(json.dumps(response, ensure_ascii=False), flush=True)
            if len(line) > 2_000_000 or not line.endswith(b"\n"):
                break
    finally:
        if cleanup:
            cleanup.cleanup()
