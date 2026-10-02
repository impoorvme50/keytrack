#!/usr/bin/env python3
"""Score sources against the frozen 200-example next-word evaluation."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keytrack.prediction_eval import (DEFAULT_BASELINE, DEFAULT_DATASET, build_report,
                                     render_markdown, write_reports)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="append", type=Path,
                        help="two-column ngram source; repeat for multiple inputs (default: starter)")
    parser.add_argument("--candidate", action="append", type=Path,
                        help="two-column candidate source; repeat for multiple inputs")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--markdown", type=Path, dest="markdown_path")
    parser.add_argument("--fail-on-gate", action="store_true",
                        help="return 2 if candidate fails the data quality gate")
    args = parser.parse_args()
    baseline = args.baseline or [DEFAULT_BASELINE]
    if args.fail_on_gate and not args.candidate:
        parser.error("--fail-on-gate requires --candidate")
    try:
        report = build_report(baseline, args.candidate, args.dataset, args.max_candidates)
        write_reports(report, args.json_path, args.markdown_path,
                      [args.dataset, args.dataset.with_suffix(".manifest.json"), *baseline, *(args.candidate or [])])
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if not args.json_path and not args.markdown_path:
        sys.stdout.write(render_markdown(report))
    if args.fail_on_gate and not report["gate"]["quality_gate_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
