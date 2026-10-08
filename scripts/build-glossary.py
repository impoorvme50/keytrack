"""Compile the frozen original metadata, or check the checked-in Lua output."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keytrack import annotations

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
target = annotations.PROJECT / "rime/keytrack_glossary.lua"
expected = annotations.render_lua()
if args.check:
    if not target.is_file() or target.read_text() != expected:
        raise SystemExit("Glossary output differs; run scripts/build-glossary.py")
else:
    target.write_text(expected)
catalog = annotations.catalog()
print(f"Original local glossary: {catalog['count']} bilingual entries "
      f"({catalog['base_count']} starter + {catalog['term_count']} work terms), source hashes and Lua output verified")
