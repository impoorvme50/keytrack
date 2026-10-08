#!/usr/bin/env python3
"""Evaluate the frozen public five-candidate set; live requests require --live."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keytrack import kev_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="only use the already running 127.0.0.1:8009 service")
    mode.add_argument("--decisions", type=Path, help="offline JSON object mapping frozen sample IDs to decisions")
    parser.add_argument("--dataset", type=Path, default=kev_eval.DEFAULT_DATASET)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--markdown", type=Path, dest="markdown_path")
    args = parser.parse_args(argv)
    try:
        frozen = kev_eval.load_dataset(args.dataset)
        if args.live:
            def progress(done, total):
                if done == 1 or done % 10 == 0:
                    print(f"Kev public evaluation: {done}/{total}", file=sys.stderr)
            report = kev_eval.run_live(frozen, progress)
        else:
            decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
            report = kev_eval.build_report(frozen, decisions, "offline_injected_decisions")
        protected = [args.dataset, args.dataset.with_suffix(".manifest.json"), args.dataset.parent / "LICENSE.txt"]
        if args.decisions:
            protected.append(args.decisions)
        kev_eval.write_reports(report, args.json_path, args.markdown_path, protected)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Error text can include a server response; keep output content-free.
        print(f"Kev evaluation failed: {kev_eval.error_category(error)}; frozen inputs and service unchanged", file=sys.stderr)
        return 1
    if not args.json_path and not args.markdown_path:
        sys.stdout.write(kev_eval.render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
