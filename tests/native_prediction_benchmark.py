"""Reproducible engine-only next-word timing, private HOME, synthetic commits.

No desktop input, user configuration or personal history is accessed. Cold
schema load, warm commit/observers/lookup and get_context are separate scopes.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import platform
import plistlib
from pathlib import Path
import shutil
import statistics
import subprocess
import time

SCRIPT = Path(__file__).with_name("native_prediction_rime.py")
spec = importlib.util.spec_from_file_location("prediction_native", SCRIPT)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def percentiles(values):
    ordered = sorted(values)
    def p(value):
        return round(ordered[max(0, (len(ordered) * value + 99) // 100 - 1)], 4)
    return {"samples": len(values), "median": round(statistics.median(values), 4),
            "p95": p(95), "p99": p(99), "max": round(max(values), 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 1000:
        parser.error("each warm group requires at least 1000 samples")
    if args.output and (args.output.is_symlink() or args.output.resolve() in {args.db.resolve(), args.source.resolve()}):
        parser.error("report must not overwrite database/source or follow symbolic links")
    # Builder semantics determine the expected ordered candidates, independently
    # checked against the actual mapped database's native engine output.
    builder_spec = importlib.util.spec_from_file_location("builder", native.PROJECT / "scripts/build-predict-db.py")
    builder = importlib.util.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)
    words = {}
    for line in builder.preprocess([args.source]).splitlines():
        key, word, _ = line.split("\t")
        words.setdefault(key, []).append(word)
    native.prepare()
    # The behavioral fixture replaces os.date with a file-driven test clock.
    # Timing must use the production collector without that extra file read.
    shutil.copyfile(native.PROJECT / "rime/keytrack_logger.lua", native.ROOT / "lua/keytrack_logger.lua")
    shutil.copyfile(args.db, native.ROOT / "keytrack-predict.db")
    (native.ROOT / "lua/probe.lua").write_text('''return function(input, seg, env)
 if seg:has_tag("prediction") then return end
 local text = env.engine.context:get_property("benchmark_text")
 yield(Candidate("probe", seg.start, seg._end, text, ""))
end
''')
    (native.ROOT / ".keytrack/prediction/control").write_text("enabled=1\nmax_candidates=3\nmax_iterations=1\n")
    libdir = Path("/Library/Input Methods/Squirrel.app/Contents/Frameworks")
    lib = C.CDLL(str(libdir / "librime.1.dylib"), mode=C.RTLD_GLOBAL)
    get_version = getattr(lib, "_Z14RimeGetVersionv")
    get_version.restype = C.c_char_p
    engine_version = get_version().decode()
    plugins = [C.CDLL(str(libdir / "rime-plugins" / name), mode=C.RTLD_GLOBAL)
               for name in ("librime-lua.dylib", "librime-predict.dylib")]
    lib.rime_get_api.restype = C.POINTER(native.API)
    api = lib.rime_get_api().contents
    def call(name, result, *types):
        return C.CFUNCTYPE(result, *types)(getattr(api, name))
    traits = native.Traits()
    traits.data_size = C.sizeof(traits) - C.sizeof(C.c_int)
    traits.shared_data_dir = traits.user_data_dir = str(native.ROOT).encode()
    traits.app_name = b"rime.keytrack-prediction-benchmark"
    traits.min_log_level = 3
    traits.log_dir = str(native.ROOT).encode()
    modules = (C.c_char_p * 5)(b"default", b"deployer", b"lua", b"predict", None)
    traits.modules = modules
    call("setup", None, C.POINTER(native.Traits))(C.byref(traits))
    call("deployer_initialize", None, C.POINTER(native.Traits))(C.byref(traits))
    assert call("deploy_schema", C.c_int, C.c_char_p)(str(native.ROOT / "rime_ice_predict.schema.yaml").encode())
    call("initialize", None, C.POINTER(native.Traits))(C.byref(traits))
    session = call("create_session", C.c_size_t)()
    start = time.perf_counter_ns()
    assert call("select_schema", C.c_int, C.c_size_t, C.c_char_p)(session, b"rime_ice_predict")
    cold_schema_ms = (time.perf_counter_ns() - start) / 1e6
    process = call("process_key", C.c_int, C.c_size_t, C.c_int, C.c_int)
    set_property = call("set_property", None, C.c_size_t, C.c_char_p, C.c_char_p)
    def committed():
        commit = native.Commit()
        commit.data_size = C.sizeof(commit) - C.sizeof(C.c_int)
        assert call("get_commit", C.c_int, C.c_size_t, C.POINTER(native.Commit))(session, C.byref(commit))
        text = commit.text.decode()
        call("free_commit", C.c_int, C.POINTER(native.Commit))(C.byref(commit))
        return text
    def snapshot():
        context = native.Context()
        context.data_size = C.sizeof(context) - C.sizeof(C.c_int)
        assert call("get_context", C.c_int, C.c_size_t, C.POINTER(native.Context))(session, C.byref(context))
        candidates = [context.menu.candidates[i].text.decode() for i in range(context.menu.num_candidates)]
        call("free_context", C.c_int, C.POINTER(native.Context))(C.byref(context))
        return candidates
    groups = {}
    all_keys = sorted(words)
    matched = [all_keys[i * len(all_keys) // min(len(all_keys), 100)] for i in range(min(len(all_keys), 100))]
    try:
        for name, keys in (("matched", matched), ("unmatched", ["隔离评测不存在的完整上屏词"] )):
            timings, contexts = [], []
            warmup = max(20, len(keys))
            for index in range(args.samples + warmup):
                text = keys[index % len(keys)]
                set_property(session, b"benchmark_text", text.encode())
                assert process(session, ord("a"), 0)
                start = time.perf_counter_ns()
                assert process(session, ord(" "), 0)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                assert committed() == text
                start = time.perf_counter_ns()
                candidates = snapshot()
                context_ms = (time.perf_counter_ns() - start) / 1e6
                assert candidates == words.get(text, [])[:3], (text, candidates, words.get(text))
                process(session, 0xFF1B, 0)
                if index >= warmup:
                    timings.append(elapsed)
                    contexts.append(context_ms)
            groups[name] = {"unique_keys": len(keys), "commit_process_key_ms": percentiles(timings),
                            "get_context_ms": percentiles(contexts), "warmup": warmup}
    finally:
        call("destroy_session", C.c_int, C.c_size_t)(session)
        call("finalize", None)()
    squirrel_info = plistlib.loads((libdir.parent / "Info.plist").read_bytes())
    report = {"result": "PASS", "isolation": "private HOME / synthetic translations",
              "environment": {"architecture": platform.machine(), "macos": platform.mac_ver()[0],
                              "device": subprocess.check_output(["sysctl", "-n", "hw.model"], text=True).strip(),
                              "squirrel": squirrel_info.get("CFBundleShortVersionString") or squirrel_info["CFBundleVersion"],
                              "librime": engine_version, "collector": "unmodified production keytrack_logger.lua"},
              "db": args.db.name, "db_sha256": hashlib.sha256(args.db.read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
              "cold_schema_select_ms": round(cold_schema_ms, 4), "cold_samples": 1,
              "cold_scope": "first schema selection in fresh process; OS file cache uncontrolled",
              "groups": groups, "candidate_window_ms": None,
              "scope": "commit key processing including collectors/observers/lookup; get_context includes Python decoding and free_context, measured separately",
              "budget_pass": all(group["commit_process_key_ms"]["p95"] <= 5 and group["commit_process_key_ms"]["p99"] <= 10 for group in groups.values())}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    main()
