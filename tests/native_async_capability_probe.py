"""Probe installed Rime/Lua capabilities without touching the user's input method.

Run directly on macOS: python3 tests/native_async_capability_probe.py
All text and configuration are synthetic, under a temporary HOME. This is an
engine/API probe, not evidence that Squirrel's real candidate window refreshes.
No model calls, front-end messages, or simulated keyboard events are used.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import plistlib
import tempfile
import threading


class Traits(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [
        (name, C.c_char_p) for name in (
            "shared_data_dir", "user_data_dir", "distribution_name",
            "distribution_code_name", "distribution_version", "app_name",
        )
    ] + [("modules", C.POINTER(C.c_char_p)), ("min_log_level", C.c_int)] + [
        (name, C.c_char_p) for name in ("log_dir", "prebuilt_data_dir", "staging_dir")
    ]


class Candidate(C.Structure):
    _fields_ = [("text", C.c_char_p), ("comment", C.c_char_p), ("reserved", C.c_void_p)]


class Menu(C.Structure):
    _fields_ = [(name, C.c_int) for name in (
        "page_size", "page_no", "is_last_page", "highlighted_candidate_index", "num_candidates",
    )] + [("candidates", C.POINTER(Candidate)), ("select_keys", C.c_char_p)]


class Composition(C.Structure):
    _fields_ = [(name, C.c_int) for name in ("length", "cursor_pos", "sel_start", "sel_end")] + [
        ("preedit", C.c_char_p),
    ]


class Context(C.Structure):
    _fields_ = [("data_size", C.c_int), ("composition", Composition), ("menu", Menu),
                ("commit_text_preview", C.c_char_p), ("select_labels", C.POINTER(C.c_char_p))]


API_NAMES = """setup set_notification_handler initialize finalize start_maintenance
is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy
deploy_schema deploy_config_file sync_user_data create_session find_session
destroy_session cleanup_stale_sessions cleanup_all_sessions process_key
commit_composition clear_composition get_commit free_commit get_context free_context
get_status free_status set_option get_option set_property get_property get_schema_list
free_schema_list get_current_schema select_schema""".split()


class API(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(name, C.c_void_p) for name in API_NAMES]


LUA_PROBE = '''local M = {}
function M.init(env)
  local context = env.engine.context
  context:set_property("probe_version", rime_api.get_rime_version())
  local names = {
    "commit_notifier", "select_notifier", "update_notifier", "delete_notifier",
    "abort_notifier", "option_update_notifier", "property_update_notifier",
    "unhandled_key_notifier", "activate_notifier", "deactivate_notifier",
    "focus_notifier", "session_id", "client", "refresh_non_confirmed_composition",
  }
  local features = {}
  for _, name in ipairs(names) do
    local ok, value = pcall(function() return context[name] end)
    features[#features + 1] = name .. ":" .. (ok and type(value) or "unavailable")
  end
  context:set_property("probe_features", table.concat(features, ","))
  env.connection = context.property_update_notifier:connect(function(ctx, name)
    if name == "probe_result" then
      ctx:refresh_non_confirmed_composition()
    end
  end)
end
function M.func(input, seg, env)
  local words = {"测试甲", "测试乙"}
  if env.engine.context:get_property("probe_result") == "ready" then
    words = {"测试乙", "测试甲"}
  end
  for _, word in ipairs(words) do
    yield(Candidate("synthetic", seg.start, seg._end, word, "隔离探测"))
  end
end
function M.fini(env)
  if env.connection then env.connection:disconnect() end
end
return M
'''


def main() -> None:
    app = Path("/Library/Input Methods/Squirrel.app")
    libdir = app / "Contents/Frameworks"
    artifacts = [app / "Contents/MacOS/Squirrel", libdir / "librime.1.dylib",
                 libdir / "rime-plugins/librime-lua.dylib"]
    owner_thread = threading.get_ident()
    notifications = []
    callback_type = C.CFUNCTYPE(None, C.c_void_p, C.c_size_t, C.c_char_p, C.c_char_p)

    @callback_type
    def notified(_, session_id, kind, value):
        notifications.append({"session_id": session_id, "type": kind.decode(),
                              "value": value.decode(), "thread": threading.get_ident()})

    with tempfile.TemporaryDirectory(prefix="keytrack-async-probe-") as directory:
        root = Path(directory)
        original_home = os.environ.get("HOME")
        os.environ["HOME"] = directory
        (root / "lua").mkdir()
        (root / "build").mkdir()
        (root / "lua/probe.lua").write_text(LUA_PROBE)
        (root / "build/probe.schema.yaml").write_text('''schema:
  schema_id: probe
  name: Synthetic async capability probe
  version: "1"
engine:
  processors: [speller, selector, express_editor]
  segmentors: [abc_segmentor, fallback_segmentor]
  translators: ["lua_translator@*probe"]
speller:
  alphabet: abcdefghijklmnopqrstuvwxyz
menu:
  page_size: 5
''')
        (root / "build/default.yaml").write_text('config_version: "1"\nschema_list:\n  - schema: probe\n')
        lib = C.CDLL(str(libdir / "librime.1.dylib"), mode=C.RTLD_GLOBAL)
        plugin = C.CDLL(str(libdir / "rime-plugins/librime-lua.dylib"), mode=C.RTLD_GLOBAL)
        lib.rime_get_api.restype = C.POINTER(API)
        api = lib.rime_get_api().contents

        def call(name, result, *types):
            field = getattr(API, name)
            assert field.offset + C.sizeof(C.c_void_p) <= api.data_size + C.sizeof(C.c_int), name
            assert getattr(api, name), name
            return C.CFUNCTYPE(result, *types)(getattr(api, name))

        traits = Traits()
        traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
        traits.shared_data_dir = traits.user_data_dir = directory.encode()
        traits.app_name = b"rime.keytrack-async-probe"
        traits.log_dir = directory.encode()
        traits.min_log_level = 2
        modules = (C.c_char_p * 4)(b"default", b"deployer", b"lua", None)
        traits.modules = modules
        call("setup", None, C.POINTER(Traits))(C.byref(traits))
        call("set_notification_handler", None, callback_type, C.c_void_p)(notified, None)
        initialized = False
        session = 0
        try:
            call("initialize", None, C.POINTER(Traits))(C.byref(traits))
            initialized = True
            session = call("create_session", C.c_size_t)()
            assert session
            assert call("select_schema", C.c_int, C.c_size_t, C.c_char_p)(session, b"probe")
            process_key = call("process_key", C.c_int, C.c_size_t, C.c_int, C.c_int)
            assert process_key(session, ord("a"), 0)  # Engine input only; no OS key event.

            def property_value(name):
                buf = C.create_string_buffer(4096)
                assert call("get_property", C.c_int, C.c_size_t, C.c_char_p, C.c_void_p, C.c_size_t)(
                    session, name.encode(), buf, len(buf))
                return buf.value.decode()

            def snapshot():
                context = Context()
                context.data_size = C.sizeof(context) - C.sizeof(C.c_int)
                assert call("get_context", C.c_int, C.c_size_t, C.POINTER(Context))(session, C.byref(context))
                try:
                    return [context.menu.candidates[i].text.decode() for i in range(context.menu.num_candidates)]
                finally:
                    call("free_context", C.c_int, C.POINTER(Context))(C.byref(context))

            before = snapshot()
            notification_start = len(notifications)
            call("set_property", None, C.c_size_t, C.c_char_p, C.c_char_p)(session, b"probe_result", b"ready")
            # No process_key between snapshots. Explicit owner-thread API call
            # exercises engine refresh, not an async Squirrel input-thread wakeup.
            after = snapshot()
            events = notifications[notification_start:]
            assert before == ["测试甲", "测试乙"], before
            assert after == ["测试乙", "测试甲"], after
            assert any(e["type"] == "property" and e["value"] == "probe_result=ready" for e in events), events
            assert all(e["thread"] == owner_thread for e in events), events
            report = {
                "squirrel_version": plistlib.loads((app / "Contents/Info.plist").read_bytes())["CFBundleVersion"],
                "rime_version": property_value("probe_version"),
                "binary_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts},
                "context_features": dict(item.split(":", 1) for item in property_value("probe_features").split(",")),
                "engine_menu_before": before, "engine_menu_after": after,
                "process_key_calls_after_result": 0,
                "property_notification_on_calling_owner_thread": True,
                "frontend_focus_boundary_proven": False,
                "idle_real_candidate_window_refresh_proven": False,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if session:
                call("destroy_session", C.c_int, C.c_size_t)(session)
            if initialized:
                call("finalize", None)()
            if original_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original_home
            del plugin  # Keep plugin loaded throughout finalization.


if __name__ == "__main__":
    main()
