"""Read-only input-stack diagnostics. Never read or print recorded input text."""

from __future__ import annotations

import hashlib
import json
import urllib.request

from . import agent, kev_rime_bridge, kev_rime_setup, kev_service, kev_switch


def checks() -> list[dict]:
    result = []

    def add(name: str, level: str, message: str) -> None:
        result.append({"name": name, "level": level, "message": message})

    recorder = agent.service_status()
    if recorder["running"]:
        add("recorder", "ok", f"采集服务运行中（PID {recorder['pid']}）")
    else:
        message = "采集服务状态无法读取" if recorder["state"] == "unknown" else "采集服务未运行"
        add("recorder", "warning", message + "；可检查 kbd status")

    enabled = kev_switch.is_enabled()
    add("kev_switch", "ok", f"Kev 建议{'开启' if enabled else '关闭'}，由快捷键主动触发")
    for name in kev_rime_setup.LUA_FILES:
        target = kev_rime_setup.RIME_DIR / "lua" / name
        source = kev_rime_setup.PROJECT_DIR / "rime" / name
        try:
            identical = hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
            add(name, "ok" if identical else "error",
                f"{name} 已安装且与源码一致" if identical else f"{name} 版本不同；运行 kbd setup-kev-rime")
        except OSError:
            add(name, "error" if enabled else "warning", f"{name} 未安装或无法读取；运行 kbd setup-kev-rime")

    schema = kev_rime_setup.RIME_DIR / "build" / f"{kev_rime_setup.SCHEMA}.schema.yaml"
    try:
        content = schema.read_text(encoding="utf-8")
        hooked = all(hook in content for hook in ("lua_processor@*kev_hotkey", "lua_filter@*kev_filter"))
        add("deployed_schema", "ok" if hooked else "error",
            "雾凇拼音已部署 Kev 钩子" if hooked else "部署方案缺少 Kev 钩子；运行 kbd setup-kev-rime")
    except OSError:
        add("deployed_schema", "error" if enabled else "warning", "雾凇拼音部署文件无法读取")

    if enabled:
        service = agent.service_status(kev_service.LABEL)
        if kev_service.PLIST_PATH.exists() and not service["running"]:
            add("kev_agent", "warning", "Kev 常驻服务尚未运行；模型可能正在加载")
        request = urllib.request.Request("http://127.0.0.1:8009/v1/models")
        try:
            with kev_rime_bridge.open_local(request, timeout=1.0) as response:
                data = response.read(kev_rime_bridge.MAX_RESPONSE_BYTES + 1)
                if response.status != 200 or len(data) > kev_rime_bridge.MAX_RESPONSE_BYTES:
                    raise ValueError("invalid model response")
            models = json.loads(data)["models"]
            if not isinstance(models, list) or not any(
                isinstance(model, dict) and model.get("id") == "kev-latest" for model in models
            ):
                raise ValueError("Kev model not found")
            add("kev_http", "ok", "本机 Kev 模型接口可用（127.0.0.1:8009）")
        except (OSError, ValueError, KeyError, TypeError):
            add("kev_http", "error", "本机 Kev 模型接口不可用；检查服务启动与模型加载日志")
    else:
        add("kev_http", "ok", "Kev 已关闭，跳过模型连接")
    return result


def command(as_json: bool = False) -> bool:
    result = checks()
    if as_json:
        print(json.dumps({"checks": result}, ensure_ascii=False, indent=2))
    else:
        symbols = {"ok": "✓", "warning": "!", "error": "✗"}
        for item in result:
            print(f"{symbols[item['level']]} {item['message']}")
        print("这里只验证安装与服务；实际候选窗仍需在鼠须管里试打。")
    return not any(item["level"] == "error" for item in result)
