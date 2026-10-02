#!/usr/bin/env python3
"""Build reproducible librime-predict databases from public, explicit sources.

Only this maintainer command needs git, clang++, Boost headers and Squirrel.
Installing Keytrack uses the checked-in databases and never builds/downloads.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data" / "prediction"
REVISIONS = {
    "predict": ("https://github.com/rime/librime-predict.git", "920bd41ebf6f9bf6855d14fbe80212e54e749791"),
    "librime": ("https://github.com/rime/librime.git", "a251145d3aafa33871824a40bbec04c966bd8b56"),
    "darts": ("https://github.com/s-yata/darts-clone.git", "87b71afd6cf784953e3c08f24c64203397f3b724"),
    "marisa": ("https://github.com/s-yata/marisa-trie.git", "3e87d53b78e15f2f43783d5e376561a8c9722051"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preprocess(paths: list[Path], max_candidates: int = 8) -> str:
    """Match upstream make_predict_data's explicit pair/prefix split semantics.

    Duplicate pairs keep their largest weight. Equal weights retain source
    order, matching Rust's stable sort. Reject malformed data before the C++
    tool, whose whitespace reader does not validate records.
    """
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    data: dict[str, dict[str, int]] = {}
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            fields = line.split("\t")
            if len(fields) != 2:
                raise ValueError(f"{path}:{number}: expected text TAB unsigned weight")
            text, raw_weight = fields
            if any(ord(c) < 32 or ord(c) == 127 for c in text):
                raise ValueError(f"{path}:{number}: prediction text contains control characters")
            if not raw_weight.isascii() or not raw_weight.isdecimal():
                raise ValueError(f"{path}:{number}: weight must be an unsigned integer")
            weight = int(raw_weight)
            if weight > 0xFFFFFFFF:
                raise ValueError(f"{path}:{number}: weight exceeds u32")
            if " " in text:
                tokens = text.split(" ")
                if len(tokens) != 2 or any(not x or any(c.isspace() for c in x) for x in tokens):
                    raise ValueError(f"{path}:{number}: expected exactly two nonempty words")
                pairs = [] if tokens[1] == "$" else [(tokens[0], tokens[1])]
            else:
                if not text or any(c.isspace() for c in text):
                    raise ValueError(f"{path}:{number}: empty text or unexpected whitespace")
                pairs = [(text[:i], text[i:]) for i in range(1, len(text))]
            for key, candidate in pairs:
                entry = data.setdefault(key, {})
                entry[candidate] = max(entry.get(candidate, 0), weight)
    lines = []
    for key in sorted(data):
        entries = sorted(data[key].items(), key=lambda x: -x[1])[:max_candidates]
        lines.extend(f"{key}\t{word}\t{weight}\n" for word, weight in entries)
    if not lines:
        raise ValueError("source produces no prediction records")
    return "".join(lines)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, **kwargs)


def checkout(cache: Path, name: str, offline: bool) -> Path:
    url, revision = REVISIONS[name]
    path = cache / name
    if path.is_symlink():
        raise ValueError(f"refusing symlink source cache: {path}")
    if path.exists():
        verify_checkout(path, revision)
        return path
    if offline:
        raise ValueError(f"missing source cache in offline mode: {path}")
    cache.mkdir(parents=True, exist_ok=True)
    # Failed fetches never become persistent cache entries, so an ordinary
    # retry can recover without deleting or modifying an existing checkout.
    with tempfile.TemporaryDirectory(prefix=f"{name}-fetch-", dir=cache) as temporary:
        staged = Path(temporary) / "checkout"
        staged.mkdir()
        run(["git", "init", "--quiet", str(staged)])
        run(["git", "-C", str(staged), "remote", "add", "origin", url])
        run(["git", "-C", str(staged), "fetch", "--quiet", "--depth", "1", "origin", revision])
        run(["git", "-C", str(staged), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
        verify_checkout(staged, revision)
        os.replace(staged, path)
    return path


def verify_checkout(path: Path, revision: str) -> None:
    observed = run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    changes = run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout
    if observed != revision or changes:
        raise ValueError(f"source cache must be clean and pinned to {revision}: {path}")


def compiler(cache: Path, librime: Path, boost_include: Path, offline: bool) -> Path:
    if not librime.is_file():
        raise ValueError(f"librime library not found: {librime}")
    if not (boost_include / "boost" / "signals2" / "signal.hpp").is_file():
        raise ValueError(f"Boost headers not found: {boost_include}")
    # This maintainer helper targets Squirrel's exported C++ ABI. Avoid
    # compiling against different-version private dictionary class layouts.
    library = ctypes.CDLL(str(librime))
    version_function = getattr(library, "_Z14RimeGetVersionv", None)
    if version_function is None:
        raise ValueError("librime does not expose Squirrel's expected version function")
    version_function.restype = ctypes.c_char_p
    if version_function() != b"1.16.0":
        raise ValueError("this pinned builder requires librime 1.16.0; update and validate matching source headers for another version")
    sources = {name: checkout(cache, name, offline) for name in REVISIONS}
    include = cache / "generated-include" / "rime"
    include.mkdir(parents=True, exist_ok=True)
    # Logging does not affect DB layout. Disabling it avoids a glog build/link.
    (include / "build_config.h").write_text("// Build helper: logging disabled.\n", encoding="utf-8")
    binary = cache / "build_predict"
    args = [
        "clang++", "-std=c++17", "-O2", "-I" + str(include.parent),
        "-I" + str(sources["librime"] / "src"),
        "-I" + str(sources["darts"] / "include"),
        "-I" + str(sources["marisa"] / "include"),
        "-I" + str(boost_include), "-I" + str(sources["predict"] / "src"),
        str(sources["predict"] / "tools" / "build_predict.cc"),
        str(sources["predict"] / "src" / "predict_db.cc"),
        str(librime), "-Wl,-rpath," + str(librime.parent), "-o", str(binary),
    ]
    run(args)
    return binary


def build(inputs: list[Path], output: Path, args: argparse.Namespace) -> dict:
    if output.is_symlink():
        raise ValueError(f"refusing symlink output: {output}")
    manifest_path = output.with_suffix(".manifest.json")
    if manifest_path.is_symlink():
        raise ValueError(f"refusing symlink manifest: {manifest_path}")
    input_paths = {path.resolve() for path in inputs}
    if output.resolve() in input_paths or manifest_path.resolve() in input_paths:
        raise ValueError("database output and manifest must not overwrite any input source")
    records = preprocess(inputs, args.max_candidates)
    data_license = args.license or ("MIT" if all(path in (DATA / "fixture.ngram.tsv", DATA / "starter.ngram.tsv") for path in inputs) else None)
    if not data_license:
        raise ValueError("custom sources require --license SPDX-ID and their own provenance record")
    output.parent.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    builder = compiler(args.cache, args.librime, args.boost_include, args.offline)
    # The upstream mapped file builder overwrites its destination. Keep failed
    # builds away from the prior good DB and replace atomically on success.
    with tempfile.TemporaryDirectory(prefix="predict-build-", dir=output.parent) as temp:
        temporary = Path(temp) / output.name
        run([str(builder), str(temporary)], input=records.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not temporary.read_bytes().startswith(b"Rime::Predict/1.0"):
            raise ValueError("upstream builder produced an invalid database header")
        os.replace(temporary, output)
    manifest = {
        "format": "Rime::Predict/1.0", "license": data_license,
        "sources": [{"file": str(x.relative_to(PROJECT)) if x.is_relative_to(PROJECT) else str(x), "sha256": sha256(x)} for x in inputs],
        "upstream_revisions": {name: revision for name, (_, revision) in REVISIONS.items()},
        "preprocessed_sha256": hashlib.sha256(records.encode()).hexdigest(),
        "contexts": len({line.split("\t", 1)[0] for line in records.splitlines()}),
        "records": len(records.splitlines()), "max_candidates_in_data": args.max_candidates,
        "db_sha256": sha256(output), "db_bytes": output.stat().st_size,
        "build_architecture": platform.machine(), "librime_sha256": sha256(args.librime),
        "librime_version": "1.16.0",
        "compiler": run(["clang++", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help="build the exact synthetic test fixture")
    parser.add_argument("--input", type=Path, action="append", help="two-column upstream ngram source; repeat to merge")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--license", help="SPDX identifier of custom input data; required with external --input")
    parser.add_argument("--cache", type=Path, default=PROJECT / ".local" / "prediction-build")
    parser.add_argument("--offline", action="store_true", help="require already cached pinned source checkouts")
    parser.add_argument("--librime", type=Path, default=Path("/Library/Input Methods/Squirrel.app/Contents/Frameworks/librime.1.dylib"))
    parser.add_argument("--boost-include", type=Path, default=Path("/opt/homebrew/opt/boost/include"))
    parser.add_argument("--preprocess-only", action="store_true", help="write three-column data to stdout without any build/download")
    args = parser.parse_args()
    inputs = [x.resolve() for x in (args.input or [DATA / ("fixture.ngram.tsv" if args.fixture else "starter.ngram.tsv")])]
    output = (args.output or DATA / ("keytrack-predict-fixture.db" if args.fixture else "keytrack-predict.db")).absolute()
    try:
        if args.preprocess_only:
            sys.stdout.write(preprocess(inputs, args.max_candidates))
        else:
            result = build(inputs, output, args)
            print(json.dumps({"output": str(output), **result}, indent=2, ensure_ascii=False))
    except subprocess.CalledProcessError as error:
        for stream in (error.stdout, error.stderr):
            if stream:
                sys.stderr.write(stream.decode("utf-8", errors="replace") if isinstance(stream, bytes) else stream)
        parser.exit(1, f"predict DB build failed: {error}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"predict DB build failed: {error}\n")


if __name__ == "__main__":
    main()
