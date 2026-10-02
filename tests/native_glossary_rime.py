"""Native candidate-glossary acceptance using private HOME and synthetic input.

Runs the same sequence in three independent Squirrel engines. No real user
Rime deployment, GUI, history, model or network is accessed. Timings exclude UI.
"""
from __future__ import annotations

from collections import Counter
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time

import native_prediction_rime as fixture


def run(language: str, benchmark: bool = False) -> dict:
    fixture.prepare()
    root, project = fixture.ROOT, fixture.PROJECT
    (root / ".keytrack/annotations").mkdir()
    # No writer exists: any key-path attempt to open this FIFO would block.
    os.mkfifo(root / ".keytrack/annotations/control")
    for name in ("keytrack_comments.lua", "keytrack_glossary.lua"):
        shutil.copyfile(project / "rime" / name, root / "lua" / name)
    (root / "lua/probe.lua").write_text('''return function(input, seg, env)
 if not seg:has_tag("abc") or seg:has_tag("prediction") or input == "qreply" then return end
 local words = input == "none" and {"完全无匹配"}
   or {"你好", "世界", "朋友", "今天", "你好🙂", "🙂"}
 for _, word in ipairs(words) do
  local candidate = Candidate("probe", seg.start, seg._end, word, "原注释")
  candidate.quality = 7.5
  yield(candidate)
 end
end
''')
    (root / "lua/wrap_probe.lua").write_text('''return function(input, env)
 for candidate in input:iter() do
  if candidate.type == "prediction" or candidate.text == "世界" then
   yield(ShadowCandidate(candidate, "simplified", candidate.text,
    candidate.comment == "" and "转换" or candidate.comment .. " · 转换"))
  else yield(candidate) end
 end
end
''')
    # This test-only final filter checks real candidate userdata and quality.
    (root / "lua/audit.lua").write_text('''return function(input, env)
 for candidate in input:iter() do
  assert(type(candidate) == "userdata", "non-candidate yield")
  local segment = env.engine.context.composition:back()
  if segment and segment:has_tag("prediction") then
   assert(candidate.type == "prediction", "iteration type lost")
  elseif candidate.type == "probe" or candidate.type == "simplified" then
   assert(candidate.type == (candidate.text == "世界" and "simplified" or "probe"))
   assert(candidate.quality == 7.5, "ordinary quality changed")
  end
  yield(candidate)
 end
end
''')
    schema = root / "rime_ice_predict.schema.yaml"
    source = schema.read_text()
    assert '    - "lua_filter@*prediction_filter"\n' in source
    source = source.replace('    - "lua_filter@*prediction_filter"\n',
                            '    - "lua_filter@*prediction_filter"\n    - lua_filter@*audit\n')
    source = re.sub(r"(?m)^keytrack_glossary:\n(?:  [^\n]*\n)*", "", source)
    schema.write_text(source + (f"\nkeytrack_glossary:\n  language: {language}\n" if language != "off" else ""))
    libdir = Path("/Library/Input Methods/Squirrel.app/Contents/Frameworks")
    lib = C.CDLL(str(libdir / "librime.1.dylib"), mode=C.RTLD_GLOBAL)
    plugins = [C.CDLL(str(libdir / "rime-plugins" / name), mode=C.RTLD_GLOBAL)
               for name in ("librime-lua.dylib", "librime-predict.dylib")]
    lib.rime_get_api.restype = C.POINTER(fixture.API)
    api = lib.rime_get_api().contents

    def call(name, result, *types):
        return C.CFUNCTYPE(result, *types)(getattr(api, name))

    traits = fixture.Traits()
    traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
    traits.shared_data_dir = traits.user_data_dir = str(root).encode()
    traits.app_name, traits.min_log_level, traits.log_dir = b"rime.keytrack-glossary-check", 2, str(root).encode()
    modules = (C.c_char_p * 5)(b"default", b"deployer", b"lua", b"predict", None)
    traits.modules = modules
    call("setup", None, C.POINTER(fixture.Traits))(C.byref(traits))
    call("deployer_initialize", None, C.POINTER(fixture.Traits))(C.byref(traits))
    assert call("deploy_schema", C.c_int, C.c_char_p)(str(schema).encode())
    call("initialize", None, C.POINTER(fixture.Traits))(C.byref(traits))
    session = call("create_session", C.c_size_t)()
    assert session and call("select_schema", C.c_int, C.c_size_t, C.c_char_p)(session, b"rime_ice_predict")
    process = call("process_key", C.c_int, C.c_size_t, C.c_int, C.c_int)
    expected, commits, menus, elapsed = Counter(), [], [], []
    coverage = Counter()
    names = {32: "space", 44: "comma", 0xFF09: "Tab", 0xFF1B: "Escape", 0xFF08: "BackSpace", 0xFFE1: "Shift_L"}

    def key(code, modifiers=0):
        code = ord(code) if isinstance(code, str) else code
        if not modifiers & (1 << 30):
            expected["Shift+Control+k" if code == ord("k") and modifiers == 5 else names.get(code, chr(code))] += 1
        started = time.perf_counter_ns()
        result = bool(process(session, code, modifiers))
        if benchmark:
            _, values = menu()
            coverage["candidate_appearances"] += len(values)
            coverage["gloss_appearances"] += sum("EN:" in comment or "日:" in comment for _, comment in values)
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000)
        return result

    def typing(value):
        for char in value:
            assert key(char)

    def commit():
        item = fixture.Commit(); item.data_size = C.sizeof(item) - C.sizeof(C.c_int)
        if not call("get_commit", C.c_int, C.c_size_t, C.POINTER(fixture.Commit))(session, C.byref(item)):
            return None
        value = (item.text or b"").decode(); commits.append(value)
        call("free_commit", C.c_int, C.POINTER(fixture.Commit))(C.byref(item))
        return value

    def menu():
        item = fixture.Context(); item.data_size = C.sizeof(item) - C.sizeof(C.c_int)
        assert call("get_context", C.c_int, C.c_size_t, C.POINTER(fixture.Context))(session, C.byref(item))
        values = [(item.menu.candidates[i].text.decode(), (item.menu.candidates[i].comment or b"").decode())
                  for i in range(item.menu.num_candidates)]
        preedit = (item.composition.preedit or b"").decode()
        call("free_context", C.c_int, C.POINTER(fixture.Context))(C.byref(item))
        menus.append([preedit, [text for text, _ in values]])
        return preedit, values

    prefix = "EN:" if language == "en" else "日:"

    def ordinary():
        preedit, values = menu()
        assert preedit and [text for text, _ in values] == ["你好", "世界", "朋友", "今天", "你好🙂", "🙂"], values
        for index, (_, comment) in enumerate(values):
            assert comment.startswith("原注释"), values
            if language == "off" or index >= 4:
                assert "EN:" not in comment and "日:" not in comment, values
            else:
                assert prefix in comment, values
        return values

    def prediction():
        preedit, values = menu()
        assert preedit == "" and [text for text, _ in values] == ["世界", "朋友", "今天"], values
        assert all(comment.startswith("转换 · 联想 · 数字/Tab") for _, comment in values), values
        assert all((prefix in comment) == (language != "off") for _, comment in values), values

    def empty():
        assert menu() == ("", [])

    def seed():
        typing("nihao"); ordinary(); assert key(" ") and commit() == "你好"; prediction()

    if benchmark:
        try:
            sequence = [*"nihao", 0xFF1B] * 166 + [*"nih", 0xFF1B]
            assert len(sequence) == 1000
            for code in sequence:
                assert key(code)
            assert commit() is None
        finally:
            call("destroy_session", C.c_int, C.c_size_t)(session)
            call("finalize", None)()
        buckets = [json.loads(line) for line in (root / ".keytrack/ime_keys.jsonl").read_text().splitlines()]
        observed = Counter()
        for bucket in buckets:
            assert bucket["capture_version"] == 3
            observed.update(bucket["keys"])
        assert observed == expected and sum(observed.values()) == 1000
        assert not (root / "calls").exists()
        return {"result": "PASS", "language": language, "keypresses": 1000,
                "keys": dict(sorted(observed.items())), "capture_version": 3,
                "candidate_appearances": coverage["candidate_appearances"],
                "gloss_appearances": coverage["gloss_appearances"],
                "gloss_coverage_percent": round(100 * coverage["gloss_appearances"] / coverage["candidate_appearances"], 2),
                "ordinary_key_and_context_ms": {"median": round(statistics.median(elapsed), 3),
                    "p95": round(sorted(elapsed)[949], 3), "max": round(max(elapsed), 3)},
                "commits": commits, "menus": menus}

    try:
        # Prediction remains absent by default while glossary can be enabled.
        typing("nihao"); ordinary(); assert key(" ") and commit() == "你好"; empty()
        (root / ".keytrack/prediction/control").write_text("enabled=1\nmax_candidates=3\nmax_iterations=1\n")
        seed(); assert key("2") and commit() == "朋友"; empty()
        seed(); assert key(0xFF09) and commit() == "世界"; empty()  # one round only
        seed(); assert not key(" ") and commit() is None; empty()
        seed(); assert not key("4") and commit() is None; empty()
        seed(); key(","); assert commit() == "，"; empty()
        seed(); assert key(0xFF1B) and commit() is None; empty()
        seed(); assert key(0xFF08) and commit() is None; empty(); assert not key(0xFF08)
        seed(); key("n"); assert commit() is None; ordinary(); key(0xFF1B); empty()
        key(0xFFE1); key(0xFFE1, 1 << 30)
        assert call("get_option", C.c_int, C.c_size_t, C.c_char_p)(session, b"ascii_mode")
        assert not key("a") and commit() is None; empty()
        key(0xFFE1); key(0xFFE1, 1 << 30)
        typing("nihao"); assert key("k", 5)
        _, values = menu()
        assert values[0][0] == "世界" and "✦ AI" in values[0][1] and "原注释" in values[0][1], values
        assert (prefix in values[0][1]) == (language != "off"), values
        assert key("k", 5); ordinary(); assert key(0xFF1B); empty()
        key("a", 1 << 30)  # releases remain excluded from physical-key buckets
    finally:
        call("destroy_session", C.c_int, C.c_size_t)(session)
        call("finalize", None)()
    buckets = [json.loads(line) for line in (root / ".keytrack/ime_keys.jsonl").read_text().splitlines()]
    observed = Counter()
    for bucket in buckets:
        assert bucket["capture_version"] == 3
        observed.update(bucket["keys"])
    assert observed == expected, (observed, expected)
    assert (root / "calls").read_text().splitlines() == ["called"]
    return {"result": "PASS", "language": language, "keypresses": sum(expected.values()),
            "keys": dict(sorted(observed.items())), "capture_version": 3, "commits": commits,
            "menus": menus, "process_key_ms": {"median": round(statistics.median(elapsed), 3),
                                                  "max": round(max(elapsed), 3)}}


def main() -> None:
    benchmark = "--benchmark" in sys.argv
    if "--language" in sys.argv:
        print(json.dumps(run(sys.argv[sys.argv.index("--language") + 1], benchmark), ensure_ascii=False))
        return
    reports = []
    for language in ("off", "en", "ja"):
        command = [sys.executable, __file__, "--language", language]
        if benchmark:
            command.append("--benchmark")
        process = subprocess.run(command, text=True, capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr + process.stdout
        reports.append(json.loads(process.stdout))
    for report in reports[1:]:
        for name in ("keypresses", "keys", "commits", "menus"):
            assert report[name] == reports[0][name], name
    names = ("language", "ordinary_key_and_context_ms", "candidate_appearances", "gloss_appearances", "gloss_coverage_percent") \
        if benchmark else ("language", "process_key_ms")
    print(json.dumps({"result": "PASS", "isolation": "private HOME / synthetic translations and fixture DB",
                      "glossary_sha256": hashlib.sha256((fixture.PROJECT / "rime/keytrack_glossary.lua").read_bytes()).hexdigest(),
                      "language_source": "in-memory schema config keytrack_glossary/language",
                      "annotations_control_fifo_unread": True,
                      "candidate_text_order_count_and_key_rules_equal": True,
                      "keypresses_each_language": reports[0]["keypresses"], "capture_version": 3,
                      "languages": [{name: report[name] for name in names} for report in reports],
                      "timing_scope": "native process_key + get_context, no AI; excludes UI" if benchmark else "native process_key including explicit AI hotkey; excludes UI",
                      "candidate_window_tested": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
