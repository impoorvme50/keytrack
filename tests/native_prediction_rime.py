"""Isolated acceptance checks with Squirrel's real librime/Lua/predict plugins.

Run directly on macOS after ``python scripts/build-predict-db.py --fixture``.
This creates a private HOME and synthetic translations; it never deploys into
the user's Rime directory. Engine timings exclude the macOS candidate window.
"""
from __future__ import annotations

import atexit
from collections import Counter
import ctypes as C
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parent.parent
ROOT = Path(tempfile.mkdtemp(prefix="keytrack-prediction-native-"))
atexit.register(shutil.rmtree, ROOT)
os.environ["HOME"] = str(ROOT)
sys.path.insert(0, str(PROJECT))

from keytrack import prediction_setup  # noqa: E402


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
    _fields_ = [(name, C.c_int) for name in (
        "length", "cursor_pos", "sel_start", "sel_end",
    )] + [("preedit", C.c_char_p)]


class Context(C.Structure):
    _fields_ = [("data_size", C.c_int), ("composition", Composition), ("menu", Menu),
               ("commit_text_preview", C.c_char_p), ("select_labels", C.POINTER(C.c_char_p))]


class Commit(C.Structure):
    _fields_ = [("data_size", C.c_int), ("text", C.c_char_p)]


API_NAMES = """setup set_notification_handler initialize finalize start_maintenance
is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy
deploy_schema deploy_config_file sync_user_data create_session find_session
destroy_session cleanup_stale_sessions cleanup_all_sessions process_key
commit_composition clear_composition get_commit free_commit get_context free_context
get_status free_status set_option get_option set_property get_property get_schema_list
free_schema_list get_current_schema select_schema""".split()


class API(C.Structure):
    _fields_ = [("data_size", C.c_int)] + [(name, C.c_void_p) for name in API_NAMES]


def prepare() -> None:
    for folder in ("build", "lua", ".keytrack/kev-rime", ".keytrack/prediction"):
        (ROOT / folder).mkdir(parents=True)
    (ROOT / ".keytrack/kev-rime/enabled").write_text("1\n")
    # Off is represented by absent state; do not prime prediction on session start.
    fixture = PROJECT / "data/prediction/keytrack-predict-fixture.db"
    if not fixture.exists():
        raise SystemExit("Build fixture first: python scripts/build-predict-db.py --fixture")
    shutil.copyfile(fixture, ROOT / "keytrack-predict.db")
    for name in (
        "kev_context.lua", "kev_filter.lua", "kev_hotkey.lua", "keytrack_phrases.lua",
        "keytrack_logger.lua", "prediction_guard.lua", "prediction_filter.lua",
    ):
        shutil.copyfile(PROJECT / "rime" / name, ROOT / "lua" / name)
    # Advance a minute deterministically without waiting 60 seconds. The real
    # collector is otherwise unchanged; both buckets must certify actual order.
    logger = ROOT / "lua/keytrack_logger.lua"
    clock = '''local fixture_date = os.date
os.date = function(format, epoch)
  if format == "%Y-%m-%dT%H:%M" and epoch == nil then
    local file = io.open(os.getenv("HOME") .. "/minute", "r")
    if file then local value = file:read("*l"); file:close(); return value end
  end
  return fixture_date(format, epoch)
end
'''
    logger.write_text(clock + logger.read_text())
    (ROOT / "minute").write_text("2026-10-02T12:00\n")
    (ROOT / "lua/keytrack_phrases_data.lua").write_text(
        'return {{code="qreply", text="第一行\\n第二行", category="测试"}}\n'
    )
    (ROOT / "bridge.sh").write_text(
        'cp "$1" "$HOME/request.json"\necho called >> "$HOME/calls"\n'
        'printf "2\\t1\\n" > "$2"\n'
    )
    (ROOT / "lua/probe.lua").write_text('''return function(input, seg, env)
 if seg:has_tag("prediction") or input == "qreply" then return end
 local values = input == "none" and {"完全无匹配"}
   or {"你好", "拟好", "你", "拟", "尼", "泥"}
 for _, word in ipairs(values) do
  yield(Candidate("probe", seg.start, seg._end, word, ""))
 end
end
''')
    # Daily schemes may traditionalize or decorate candidates before our final
    # filter. A ShadowCandidate changes type but must retain prediction rules.
    (ROOT / "lua/wrap_probe.lua").write_text('''return function(input, env)
 for candidate in input:iter() do
  if candidate.type == "prediction" then
   yield(ShadowCandidate(candidate, "simplified", candidate.text, "转换"))
  else
   yield(candidate)
  end
 end
end
''')
    source = f'''schema:
  schema_id: probe
  name: Probe
  version: "1"
switches:
  - name: ascii_mode
    reset: 0
    states: [中文, 英文]
engine:
  processors:
    - lua_processor@*keytrack_logger
    - lua_processor@*kev_hotkey
    - ascii_composer
    - recognizer
    - speller
    - punctuator
    - selector
    - navigator
    - key_binder
    - express_editor
  segmentors:
    - ascii_segmentor
    - abc_segmentor
    - punct_segmentor
    - fallback_segmentor
  translators:
    - punct_translator
    - lua_translator@*probe
    - lua_translator@*keytrack_phrases
  filters:
    - lua_filter@*kev_filter
    - lua_filter@*wrap_probe
speller:
  alphabet: abcdefghijklmnopqrstuvwxyz
ascii_composer:
  switch_key:
    Shift_L: clear
    Shift_R: clear
menu:
  page_size: 7
punctuator:
  half_shape:
    ",": "，"
    ".": "。"
kev_rime:
  python: /bin/sh
  bridge: {ROOT}/bridge.sh
  hotkey: Control+Shift+k
'''
    schema = prediction_setup.render_schema(source)
    (ROOT / "rime_ice_predict.schema.yaml").write_text(schema)
    (ROOT / "default.yaml").write_text(
        'config_version: "1"\nschema_list:\n  - schema: rime_ice\n'
    )
    (ROOT / "default.custom.yaml").write_text(prediction_setup._managed_default(
        'patch:\n  "menu/page_size": 7\n'
    ))


def main() -> None:
    prepare()
    libdir = Path("/Library/Input Methods/Squirrel.app/Contents/Frameworks")
    lib = C.CDLL(str(libdir / "librime.1.dylib"), mode=C.RTLD_GLOBAL)
    # Keep handles alive until librime finalizes.
    plugins = [C.CDLL(str(libdir / "rime-plugins" / name), mode=C.RTLD_GLOBAL)
               for name in ("librime-lua.dylib", "librime-predict.dylib")]
    lib.rime_get_api.restype = C.POINTER(API)
    api = lib.rime_get_api().contents

    def call(name, result, *types):
        return C.CFUNCTYPE(result, *types)(getattr(api, name))

    traits = Traits()
    traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
    traits.shared_data_dir = traits.user_data_dir = str(ROOT).encode()
    traits.app_name = b"rime.keytrack-prediction-check"
    traits.min_log_level = 2
    traits.log_dir = str(ROOT).encode()
    modules = (C.c_char_p * 5)(b"default", b"deployer", b"lua", b"predict", None)
    traits.modules = modules
    call("setup", None, C.POINTER(Traits))(C.byref(traits))
    call("deployer_initialize", None, C.POINTER(Traits))(C.byref(traits))
    assert call("deploy_config_file", C.c_int, C.c_char_p, C.c_char_p)(b"default.yaml", b"config_version")
    default = (ROOT / "build/default.yaml").read_text()
    assert re.findall(r"^  - schema: ([^\n]+)$", default, re.M) == ["rime_ice", "rime_ice_predict"], default
    assert call("deploy_schema", C.c_int, C.c_char_p)(str(ROOT / "rime_ice_predict.schema.yaml").encode())
    deployed = (ROOT / "build/rime_ice_predict.schema.yaml").read_text()
    processor_block = re.search(r"  processors:\n((?:    -[^\n]*\n)+)", deployed)
    assert processor_block, deployed
    processors = [line.strip().removeprefix("- ").strip('"\'')
                  for line in processor_block[1].splitlines()]
    assert processors[:2] == ["lua_processor@*keytrack_logger", "lua_processor@*kev_hotkey"], processors
    assert processors.index("lua_processor@*prediction_guard") < processors.index("predictor") < processors.index("key_binder"), processors
    call("initialize", None, C.POINTER(Traits))(C.byref(traits))
    session = call("create_session", C.c_size_t)()
    assert session
    assert call("select_schema", C.c_int, C.c_size_t, C.c_char_p)(session, b"rime_ice_predict")
    process_key = call("process_key", C.c_int, C.c_size_t, C.c_int, C.c_int)
    get_option = call("get_option", C.c_int, C.c_size_t, C.c_char_p)
    expected = Counter()
    names = {32: "space", 44: "comma", 0xFF09: "Tab", 0xFF1B: "Escape", 0xFF08: "BackSpace", 0xFFE1: "Shift_L"}

    def key(code: int | str, modifiers: int = 0) -> bool:
        code = ord(code) if isinstance(code, str) else code
        if not modifiers & (1 << 30):
            name = "Shift+Control+k" if code == ord("k") and modifiers == 5 else names.get(code, chr(code))
            expected[name] += 1
        return bool(process_key(session, code, modifiers))

    def type_text(text: str) -> None:
        for char in text:
            assert key(char)

    def committed() -> str | None:
        commit = Commit()
        commit.data_size = C.sizeof(commit) - C.sizeof(C.c_int)
        if not call("get_commit", C.c_int, C.c_size_t, C.POINTER(Commit))(session, C.byref(commit)):
            return None
        result = (commit.text or b"").decode()
        call("free_commit", C.c_int, C.POINTER(Commit))(C.byref(commit))
        return result

    def snapshot() -> tuple[str, list[tuple[str, str]]]:
        context = Context()
        context.data_size = C.sizeof(context) - C.sizeof(C.c_int)
        assert call("get_context", C.c_int, C.c_size_t, C.POINTER(Context))(session, C.byref(context))
        candidates = [(context.menu.candidates[i].text.decode(),
                       (context.menu.candidates[i].comment or b"").decode())
                      for i in range(context.menu.num_candidates)]
        preedit = (context.composition.preedit or b"").decode()
        call("free_context", C.c_int, C.POINTER(Context))(C.byref(context))
        return preedit, candidates

    def no_menu() -> None:
        assert snapshot() == ("", []), snapshot()

    def prediction() -> None:
        preedit, words = snapshot()
        assert preedit == "", (preedit, words)
        assert [text for text, _ in words] == ["世界", "朋友", "今天"], words
        assert all("联想" in marker for _, marker in words), words

    timings: list[float] = []
    snapshots: list[float] = []

    def seed() -> None:
        type_text("nihao")
        start = time.perf_counter_ns()
        assert key(" ")
        timings.append((time.perf_counter_ns() - start) / 1_000_000)
        assert committed() == "你好"
        start = time.perf_counter_ns()
        prediction()
        snapshots.append((time.perf_counter_ns() - start) / 1_000_000)

    try:
        no_menu()
        type_text("nihao")
        assert key(" ")
        assert committed() == "你好"
        no_menu()  # default off
        (ROOT / ".keytrack/prediction/control").write_text("enabled=1\nmax_candidates=3\nmax_iterations=1\n")
        seed()
        assert key("n")
        assert committed() is None
        preedit, words = snapshot()
        assert preedit == "n" and words[0] == ("你好", ""), (preedit, words)
        assert key(0xFF1B)
        no_menu()

        seed()
        assert key(0xFF1B)
        assert committed() is None
        no_menu()
        assert not key(0xFF08)  # no composition: app receives ordinary Backspace
        seed()
        assert key(0xFF08)
        assert committed() is None
        no_menu()
        assert not key(0xFF08)

        seed()
        key(",")
        assert committed() == "，"
        no_menu()
        seed()
        for _ in range(3):
            assert not key(" ")  # app receives every Space; no hidden selection
            assert committed() is None
            no_menu()
        seed()
        assert not key("4")  # outside the visible 1–3 selection range
        assert committed() is None
        no_menu()
        seed()
        assert key("2")
        assert committed() == "朋友"
        no_menu()
        seed()
        assert key(0xFF09)
        assert committed() == "世界"
        no_menu()  # 世界 has a follow-on row, but max_iterations=1 ends it.

        # The next bucket must remain valid after keys consumed by the guard.
        (ROOT / "minute").write_text("2026-10-02T12:01\n")
        seed()
        key(0xFFE1)
        key(0xFFE1, 1 << 30)
        assert get_option(session, b"ascii_mode")
        assert not key("a")  # app receives English text directly
        assert committed() is None
        no_menu()
        key(0xFFE1)
        key(0xFFE1, 1 << 30)
        assert not get_option(session, b"ascii_mode")
        type_text("none")
        assert key(" ")
        assert committed() == "完全无匹配"
        no_menu()
        type_text("ni")
        assert key(0xFF08)
        assert snapshot()[0] == "n"
        assert key(0xFF1B)
        no_menu()
        type_text("qreply")
        assert snapshot()[1][0] == ("第一行\n第二行", "测试")
        assert key(" ")
        assert committed() == "第一行\n第二行"
        no_menu()

        seed()
        (ROOT / ".keytrack/prediction/control").write_text("enabled=0\nmax_candidates=3\nmax_iterations=1\n")
        key(" ")
        assert committed() is None
        no_menu()
        type_text("nihao")
        assert key("k", 5)
        assert snapshot()[1][0] == ("拟好", "✦ AI")
        assert key("k", 5)
        assert snapshot()[1][0] == ("你好", "")
        assert key("k", 5)
        assert (ROOT / "calls").read_text().splitlines() == ["called"]
        assert key(" ")
        assert committed() == "拟好"
        no_menu()
        (ROOT / ".keytrack/prediction/control").write_text("enabled=1\nmax_candidates=3\nmax_iterations=1\n")
        seed()
        key("k", 5)
        assert (ROOT / "calls").read_text().splitlines() == ["called"]
        assert committed() is None
        key(0xFF1B)
        key("a", 1 << 30)  # release never contributes a physical keypress
    finally:
        call("destroy_session", C.c_int, C.c_size_t)(session)
        call("finalize", None)()

    buckets = [json.loads(line) for line in (ROOT / ".keytrack/ime_keys.jsonl").read_text().splitlines()]
    assert {bucket["min"] for bucket in buckets} == {"2026-10-02T12:00", "2026-10-02T12:01"}, buckets
    assert all(bucket["capture_version"] == 3 for bucket in buckets), buckets
    observed = Counter()
    for bucket in buckets:
        observed.update(bucket["keys"])
    assert sum(expected.values()) == 116, expected
    assert observed == expected, (observed, expected)
    report = {
        "result": "PASS", "isolation": "private HOME / synthetic DB and translations",
        "keypresses": sum(expected.values()), "minute_buckets": len(buckets), "capture_version": 3,
        "prediction_samples": len(timings),
        "commit_process_key_ms": {"median": round(statistics.median(timings), 3), "max": round(max(timings), 3)},
        "get_context_ms": {"median": round(statistics.median(snapshots), 3), "max": round(max(snapshots), 3)},
        "candidate_window_ms": None,
        "timing_scope": "native engine commit + observers + lookup; context retrieval; excludes OS UI",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
