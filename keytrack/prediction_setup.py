"""Opt-in local next-word experiment. No history access or model-service calls.

The experimental schema is a snapshot of the *deployed* daily schema, so all
user rules and patches survive. Reinstall refreshes that snapshot. Daily source
and dictionary files are never edited. Managed files are backed up atomically.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from . import annotations, rime_setup

PROJECT = Path(__file__).resolve().parent.parent
SCHEMA = "rime_ice_predict"
TITLE = "雾凇拼音 · 接词实验"
DB_NAME = "keytrack-predict.db"
HEADER = "# keytrack-local-prediction: managed snapshot v1"
BEGIN = "# >>> keytrack-prediction (managed by kbd setup-prediction)"
END = "# <<< keytrack-prediction"
LOGGER = "lua_processor@*keytrack_logger"
KEV = "lua_processor@*kev_hotkey"
GUARD = "lua_processor@*prediction_guard"
FILTER = "lua_filter@*prediction_filter"
LUA_FILES = ("prediction_guard.lua", "prediction_filter.lua")


def _rime(rime_dir=None) -> Path:
    return Path(rime_dir) if rime_dir is not None else Path(rime_setup.RIME_DIR)


def state_root(rime_dir=None) -> Path:
    root = _rime(rime_dir)
    # Tests and demo consoles with another Rime directory stay completely local.
    if root != Path.home() / "Library/Rime":
        return root.parent / "prediction-state"
    return Path.home() / ".keytrack/prediction"


def settings_path(rime_dir=None) -> Path:
    return state_root(rime_dir) / "control"


def _settings(rime_dir=None) -> dict:
    values = {"enabled": False, "max_candidates": 3, "max_iterations": 1}
    path = settings_path(rime_dir)
    if _unsafe_path(path):
        raise ValueError("联想开关不能使用符号链接")
    if path.exists():
        text = path.read_text()
        found = re.fullmatch(r"enabled=([01])\nmax_candidates=([1-5])\nmax_iterations=(1)\n", text)
        if not found:
            raise ValueError("联想设置文件格式错误")
        values = {"enabled": found[1] == "1", "max_candidates": int(found[2]),
                  "max_iterations": int(found[3])}
        _validate(**values)
    return values


def _validate(enabled, max_candidates=3, max_iterations=1):
    if type(enabled) is not bool:
        raise ValueError("联想开关必须是布尔值")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 5:
        raise ValueError("联想候选数须为 1–5")
    if type(max_iterations) is not int or max_iterations != 1:
        raise ValueError("实验版连续联想最多一轮")


def yaml_list(content: str, section: str, key: str) -> list[str]:
    """Read the compiler's canonical block list; reject other YAML shapes."""
    block = re.search(r"^" + re.escape(section) + r":\n((?:[ \t].*\n|\n)+)", content, re.M)
    if not block:
        raise ValueError(f"部署配置缺少 {section}")
    found = re.search(r"^  " + re.escape(key) + r":\n((?:    - .*\n)+)", block[1], re.M)
    if not found:
        raise ValueError(f"部署配置的 {section}/{key} 不是标准列表")
    return [line.strip()[2:].strip('"\'') for line in found[1].splitlines()]


def _replace_list(content, section, key, values):
    block = re.search(r"^" + re.escape(section) + r":\n((?:[ \t].*\n|\n)+)", content, re.M)
    if not block:
        raise ValueError(f"部署配置缺少 {section}")
    updated, count = re.subn(r"(^  " + re.escape(key) + r":\n)(?:    - .*\n)+",
                             lambda m: m[1] + "".join("    - " + json.dumps(v) + "\n" for v in values),
                             block[0], flags=re.M)
    if count != 1:
        raise ValueError(f"无法安全合并 {section}/{key}")
    return content[:block.start()] + updated + content[block.end():]


def render_schema(deployed: str, max_candidates=3) -> str:
    _validate(False, max_candidates)
    # librime's own YAML emitter often omits the final newline.
    deployed = deployed.rstrip("\n") + "\n"
    processors = yaml_list(deployed, "engine", "processors")
    if processors[:2] != [LOGGER, KEV] or processors.count(LOGGER) != 1 or processors.count(KEV) != 1:
        raise ValueError("日常方案须先部署采集器第一、Kev 第二；运行 setup-ime / setup-kev-rime")
    if "key_binder" not in processors:
        raise ValueError("日常方案缺少 key_binder")
    if any(p in processors for p in (GUARD, "predictor")) or "predict_translator" in yaml_list(deployed, "engine", "translators"):
        raise ValueError("日常方案已有预测插件，拒绝覆盖")
    if re.search(r"^predictor:|^keytrack_prediction:|name: [\"']?prediction[\"']?\s*$", deployed, re.M):
        raise ValueError("日常方案已有联想配置，拒绝覆盖")
    content = re.sub(r"^__build_info:\n(?:[ \t].*\n|\n)*", "", deployed, flags=re.M)
    # Restrict identity updates to schema: user sections may also have name or
    # schema_id fields, and the compiler can emit those sections first.
    schema_block = re.search(r"^schema:\n(?:[ \t].*\n|\n)+", content, re.M)
    if not schema_block:
        raise ValueError("方案缺少 schema")
    identity = schema_block[0]
    for key, value in (("schema_id", SCHEMA), ("name", TITLE)):
        identity, n = re.subn(r"(^  " + key + r":)[^\n]*", lambda m: m[1] + " " + json.dumps(value, ensure_ascii=False), identity, count=1, flags=re.M)
        if n != 1:
            raise ValueError(f"方案缺少 schema/{key}")
    content = content[:schema_block.start()] + identity + content[schema_block.end():]
    content = _replace_list(content, "engine", "processors", processors[:2] + [GUARD, "predictor"] + processors[2:])
    content = _replace_list(content, "engine", "translators", ["predict_translator"] + yaml_list(content, "engine", "translators"))
    content = _replace_list(content, "engine", "filters", yaml_list(content, "engine", "filters") + [FILTER])
    switch = re.search(r"^switches:\n(?:[ \t].*\n|\n)*", content, re.M)
    if not switch:
        raise ValueError("方案缺少 switches")
    content = content[:switch.end()] + '  - name: prediction\n    reset: 0\n' + content[switch.end():]
    # The filter uses the current control-file count, always one round locally.
    content += (f"predictor:\n  db: {DB_NAME}\n  max_candidates: 5\n  max_iterations: 1\n"
                f"keytrack_prediction:\n  max_candidates: {max_candidates}\n")
    return HEADER + "\n# Refreshed from deployed rime_ice; rerun setup-prediction after daily rule changes.\n" + content


def _managed_default(content: str, present=True) -> str:
    outside = content
    if BEGIN in content or END in content:
        if content.count(BEGIN) != 1 or content.count(END) != 1 or content.index(BEGIN) > content.index(END):
            raise ValueError("联想方案管理标记不完整")
        outside = content[:content.index(BEGIN)] + content[content.index(END) + len(END):].lstrip("\n")
    if not present:
        return outside
    if SCHEMA in outside:
        raise ValueError("其他配置已注册同名联想方案，拒绝覆盖")
    if re.search(r"schema_list/(@next|\+)['\"]?\s*:", outside):
        raise ValueError("schema_list 追加位置已被其他插件占用")
    if re.search(r"^patch:\s*\{", outside, re.M) or len(re.findall(r"^patch:", outside, re.M)) > 1:
        raise ValueError("default.custom.yaml patch 需人工合并")
    block = f'{BEGIN}\n  "schema_list/@next":\n    schema: {SCHEMA}\n{END}\n'
    lines = outside.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.strip() == "patch:"), None)
    if index is None:
        return outside.rstrip("\n") + ("\n" if outside else "") + "patch:\n" + block
    stop = index + 1
    while stop < len(lines) and (not lines[stop].strip() or lines[stop][0].isspace() or lines[stop].startswith("#")):
        stop += 1
    if not lines[stop - 1].endswith("\n"):
        lines[stop - 1] += "\n"
    lines.insert(stop, block)
    return "".join(lines)


def _atomic(path, data):
    if _unsafe_path(path):
        raise ValueError(f"拒绝符号链接：{path}")
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".prediction-", delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _unsafe_path(path):
    # macOS's system temp directory aliases are expected; private/plugin paths
    # must still be real files and directories, including .keytrack itself.
    system_aliases = {Path("/var"): Path("/private/var"), Path("/tmp"): Path("/private/tmp")}
    return any(p.is_symlink() and system_aliases.get(p) != p.resolve() for p in (path, *path.parents))


def state(rime_dir=None) -> dict:
    root = _rime(rime_dir)
    settings = _settings(root)
    installed = False
    try:
        custom = root / f"{SCHEMA}.custom.yaml"
        if custom.exists() or custom.is_symlink():
            raise ValueError("实验方案已有自定义补丁，无法确认部署结构")
        source = (root / f"{SCHEMA}.schema.yaml").read_text()
        deployed = (root / "build" / f"{SCHEMA}.schema.yaml").read_text().rstrip("\n") + "\n"
        order = yaml_list(deployed, "engine", "processors")
        translators = yaml_list(deployed, "engine", "translators")
        filters = yaml_list(deployed, "engine", "filters")
        installed = (source.startswith(HEADER) and BEGIN in (root / "default.custom.yaml").read_text()
                     and order[:4] == [LOGGER, KEV, GUARD, "predictor"]
                     and all(order.count(component) == 1 for component in (LOGGER, KEV, GUARD, "predictor"))
                     and order.index("predictor") < order.index("key_binder")
                     and translators.count("predict_translator") == 1
                     and filters.count(FILTER) == 1 and filters[-1] == FILTER
                     and (root / DB_NAME).is_file()
                     and all(_compatible_lua(root, n) for n in LUA_FILES))
    except (OSError, ValueError):
        pass
    return {**settings, "installed": installed, "schema_id": SCHEMA, "schema_name": TITLE,
            "settings_path": str(settings_path(root))}


def _compatible_lua(root: Path, name: str) -> bool:
    data = (root / "lua" / name).read_bytes()
    if data == (PROJECT / "rime" / name).read_bytes():
        return True
    # Updating the app with glosses off must not disable the previously
    # validated prediction controls or force a live Rime reinstall.
    return annotations.language(root) == "off" and hashlib.sha256(data).hexdigest() == annotations.PREVIOUS.get(name)


def set_settings(enabled: bool, max_candidates=3, max_iterations=1, rime_dir=None) -> dict:
    _validate(enabled, max_candidates, max_iterations)
    root = _rime(rime_dir)
    if enabled and not state(root)["installed"]:
        raise ValueError("请先安装并部署接词实验方案")
    data = f"enabled={int(enabled)}\nmax_candidates={max_candidates}\nmax_iterations={max_iterations}\n".encode()
    path = settings_path(root)
    if path.exists() and path.read_bytes() == data:
        return {"message": "联想设置已是当前值"}
    # Controls are reversible; retain their own previous version too.
    if path.exists():
        backup = state_root(root) / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-control")
        _atomic(backup, path.read_bytes())
    _atomic(path, data)
    return {"message": f"本地接词联想已{'开启' if enabled else '关闭'}，下一次按键生效；请使用「{TITLE}」方案"}


def console_schema_changes(rime_dir=None, hotkey=None, phrases=False, gloss_language=None) -> dict:
    """Propagate native console controls to the owned experimental snapshot.

    Return writes for the console's existing atomic transaction; backup this
    extra file independently so generic console restore never replaces it whole.
    """
    root = _rime(rime_dir)
    path = root / f"{SCHEMA}.schema.yaml"
    if not path.exists():
        return {}
    source = path.read_text()
    if not source.startswith(HEADER):
        raise ValueError("联想方案不是 Keytrack 托管文件，未修改")
    updated = source
    if hotkey is not None:
        if hotkey not in ("Control+Shift+k", "Control+Alt+k", "Control+Alt+j"):
            raise ValueError("不支持的 Kev 快捷键")
        block = re.search(r"^kev_rime:\n(?:[ \t].*\n|\n)+", updated, re.M)
        if not block:
            raise ValueError("联想方案缺少 Kev 配置")
        fragment, count = re.subn(r"(^  hotkey:)[^\n]*", lambda m: m[1] + " " + json.dumps(hotkey), block[0], flags=re.M)
        if count != 1:
            raise ValueError("无法安全更新联想方案的 Kev 快捷键")
        updated = updated[:block.start()] + fragment + updated[block.end():]
    if phrases:
        translators = yaml_list(updated, "engine", "translators")
        phrase = "lua_translator@*keytrack_phrases"
        if phrase not in translators:
            updated = _replace_list(updated, "engine", "translators", translators + [phrase])
    if gloss_language is not None:
        updated = annotations.schema_language(updated, gloss_language)
    if source == updated:
        return {}
    snapshot = state_root(root) / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-console")
    _atomic(snapshot / path.name, source.encode())
    return {path: updated}


def setup(verbose=True, rime_dir=None, deploy=True, db_file=None) -> bool:
    root = _rime(rime_dir)
    def say(message):
        if verbose:
            print(message)
    try:
        manifest_path = state_root(root) / "installed.json"
        for private in (manifest_path, settings_path(root)):
            if _unsafe_path(private):
                raise ValueError(f"拒绝符号链接：{private}")
        source = root / "build/rime_ice.schema.yaml"
        if not source.is_file():
            raise ValueError("请先部署现有雾凇拼音及 Keytrack/Kev 钩子")
        plugin = Path(rime_setup.SQUIRREL_APP) / "Contents/Frameworks/rime-plugins/librime-predict.dylib"
        if not plugin.exists():
            raise ValueError("鼠须管未提供 librime-predict 插件")
        original = root / "default.custom.yaml"
        default = original.read_text() if original.exists() else ""
        schema = root / f"{SCHEMA}.schema.yaml"
        # Own experimental custom patches can change safety-critical order/limits.
        if (root / f"{SCHEMA}.custom.yaml").exists():
            raise ValueError("实验方案已有自定义补丁，拒绝覆盖其处理链")
        if schema.exists() and not schema.read_text().startswith(HEADER):
            raise ValueError("同名方案由其他插件占用，拒绝覆盖")
        values = _settings(root)
        plans = {original: _managed_default(default).encode(), schema: render_schema(source.read_text(), values["max_candidates"]).encode()}
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        for name in LUA_FILES:
            target = root / "lua" / name
            data = (PROJECT / "rime" / name).read_bytes()
            if target.exists() and target.read_bytes() != data:
                owned = (hashlib.sha256(target.read_bytes()).hexdigest() == annotations.PREVIOUS[name]
                         if name in annotations.PREVIOUS else target.read_text().startswith("-- keytrack-local-prediction"))
                if not owned:
                    raise ValueError(f"{name} 有独立修改或由其他插件占用，原文件已保留")
            plans[target] = data
        plans.update({path: text.encode() for path, text in annotations.source_changes(root).items()})
        db = root / DB_NAME
        custom_db = db_file is not None or manifest.get("custom_db", False)
        db_source = Path(db_file) if db_file else (db if custom_db and db.exists() else PROJECT / "data/prediction/keytrack-predict.db")
        data = db_source.read_bytes()
        if len(data) < 64 or not data.startswith(b"Rime::Predict/1.0\0"):
            raise ValueError("联想词库格式错误，请用 build-predict-db.py 生成")
        if db.exists() and db.read_bytes() != data and str(db) not in manifest.get("files", {}):
            raise ValueError("同名联想数据库由其他插件占用")
        plans[db] = data
        for path in plans:
            if _unsafe_path(path):
                raise ValueError(f"拒绝符号链接：{path}")
        changed = {p: d for p, d in plans.items() if not p.exists() or p.read_bytes() != d}
        snapshot = state_root(root) / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        if changed:
            # Preflight all files before writing anything to Rime.
            for path in changed:
                if path.exists():
                    _atomic(snapshot / path.relative_to(root), path.read_bytes())
            _atomic(snapshot / "manifest.json", json.dumps({"existing": [str(p.relative_to(root)) for p in changed if p.exists()],
                                                         "created": [str(p.relative_to(root)) for p in changed if not p.exists()]}, indent=2).encode())
            say(f"· 配置备份：{snapshot}")
        manifest = {"schema_id": SCHEMA, "custom_db": custom_db,
                    "files": {str(p): hashlib.sha256(d).hexdigest() for p, d in plans.items()}}
        originals = {p: p.read_bytes() for p in [*changed, manifest_path] if p.exists()}
        written = []
        try:
            if not settings_path(root).exists():
                set_settings(False, rime_dir=root)
            # Publish the scheme-list entry last; partial new files stay inert.
            for path, data in changed.items():
                if path != original:
                    _atomic(path, data)
                    written.append(path)
            _atomic(manifest_path, json.dumps(manifest, indent=2).encode())
            written.append(manifest_path)
            if original in changed:
                _atomic(original, changed[original])
                written.append(original)
        except (OSError, ValueError) as exc:
            failures = []
            for path in reversed(written):
                if path in originals:
                    try:
                        _atomic(path, originals[path])
                    except (OSError, ValueError):
                        failures.append(str(path))
            if failures:
                raise OSError(f"{exc}；原文件恢复失败 {failures}，备份在 {snapshot}") from exc
            raise
        if deploy and not rime_setup.redeploy():
            say("· 请从鼠须管菜单重新部署，再开启联想。")
        say(f"· 已添加「{TITLE}」，日常方案保留；当前联想{'开启' if values['enabled'] else '关闭'}。")
        return True
    except (OSError, ValueError) as exc:
        say(f"联想安装未完成：{exc}")
        return False


def rollback(rime_dir=None, deploy=True) -> dict:
    root = _rime(rime_dir)
    values = _settings(root)
    path = root / "default.custom.yaml"
    current = path.read_text() if path.exists() else ""
    updated = _managed_default(current, False)
    set_settings(False, values["max_candidates"], rime_dir=root)
    if updated != current:
        snapshot = state_root(root) / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-rollback")
        _atomic(snapshot / path.name, current.encode())
        _atomic(path, updated.encode())
    if deploy:
        rime_setup.redeploy()
    return {"message": "联想已关闭，实验方案入口已移除。请切回雾凇拼音；实验文件保留，未删除任何文件。"}


def command(action: str) -> bool:
    try:
        if action == "rollback":
            result = rollback()
        elif action == "status":
            result = state()
        elif action in ("on", "off", "toggle"):
            try:
                values = _settings()
            except ValueError:
                if action != "off":
                    raise
                # A safe off command repairs corrupt controls without enabling.
                values = {"enabled": False, "max_candidates": 3}
            target = (not values["enabled"]) if action == "toggle" else action == "on"
            result = set_settings(target, values["max_candidates"])
        else:
            raise ValueError("未知联想操作")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return True
    except (ValueError, OSError) as exc:
        print(str(exc))
        return False
