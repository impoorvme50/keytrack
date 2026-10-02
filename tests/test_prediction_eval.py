"""Independent evaluation must expose misses and preserve source semantics."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from keytrack import prediction_eval as evaluation

PROJECT = Path(__file__).resolve().parent.parent
FROZEN_SHA256 = "517b33578b18546c4136432f7a2065b3e81df4f7abbff597a92edaf4338e4048"


def sample(identity, commit, acceptable, kind="word", situation="synthetic"):
    return {"id": identity, "commit": commit, "acceptable_next": acceptable,
            "kind": kind, "situation": situation}


class PredictionEvaluationTests(unittest.TestCase):
    def test_frozen_set_has_independent_complete_units_and_all_four_groups(self):
        loaded = evaluation.load_dataset()
        self.assertEqual(loaded["sha256"], FROZEN_SHA256)
        self.assertEqual(loaded["manifest"]["kind_counts"],
                         {"word": 80, "phrase": 80, "unmatched": 20, "boundary": 20})
        examples = loaded["data"]["examples"]
        self.assertEqual(len(examples), 200)
        situations = {x["situation"] for x in examples}
        self.assertEqual(len(situations), 10)
        self.assertTrue(all(sum(x["situation"] == s for x in examples) == 20 for s in situations))
        self.assertEqual(len({x["commit"] for x in examples}), 200)

    def test_independent_additional_holdout_is_frozen_and_keeps_v1_contract(self):
        loaded = evaluation.load_dataset(evaluation.DATA / "evaluation-v2.json")
        self.assertEqual(loaded["manifest"]["samples"], 100)
        self.assertEqual(loaded["manifest"]["kind_counts"],
                         {"word": 40, "phrase": 40, "unmatched": 10, "boundary": 10})
        self.assertEqual(loaded["sha256"], "105e47ddcf865ef089b2b9ac4555ed8e7225612babf2ba01f91016f5a72e9ac5")
        self.assertEqual(evaluation.load_dataset()["sha256"],
                         "517b33578b18546c4136432f7a2065b3e81df4f7abbff597a92edaf4338e4048")

    def test_dataset_tampering_and_invalid_answer_contract_are_rejected(self):
        original = evaluation.load_dataset()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dataset.json"
            manifest_path = path.with_suffix(".manifest.json")
            data = deepcopy(original["data"])
            manifest = deepcopy(original["manifest"])
            path.write_text(json.dumps(data, ensure_ascii=False))
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "frozen manifest"):
                evaluation.load_dataset(path)
            manifest["sha256"] = evaluation.digest(path)
            data["examples"][0]["acceptable_next"] = []
            path.write_text(json.dumps(data, ensure_ascii=False))
            manifest["sha256"] = evaluation.digest(path)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "only boundary"):
                evaluation.load_dataset(path)

    def test_source_uses_builder_duplicate_tie_and_phrase_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "pairs.tsv"
            source.write_text("前 乙\t2\n前 甲\t10\n前 乙\t10\n前 丙\t9\n你好世界\t4\n世界 $\t9\n")
            result = evaluation.read_candidates([source], 2)
            self.assertEqual(result["candidates"]["前"], ["乙", "甲"])
            self.assertEqual(result["candidates"]["你好"], ["世界"])
            self.assertNotIn("世界", result["candidates"])
            source.write_text("甲  乙\t1\n")
            with self.assertRaises(ValueError):
                evaluation.read_candidates([source])

    def test_exact_full_commit_has_no_suffix_or_whitespace_fallback(self):
        examples = [sample("whole", "我想去", ["北京"], "phrase"),
                    sample("word", "去", ["北京"]), sample("space", "去 ", [], "boundary")]
        scored = evaluation.evaluate(examples, {"去": ["北京"]})
        self.assertEqual([x["lookup_hit"] for x in scored["rows"]], [False, True, False])
        self.assertEqual(scored["overall"]["lookup_hit"]["numerator"], 1)
        self.assertEqual(scored["overall"]["top3_acceptable_overall"]["denominator"], 3)

    def test_overall_and_conditional_denominators_include_real_misses(self):
        examples = [sample("rank1", "甲", ["对"]), sample("rank3", "乙", ["对"]),
                    sample("rank4", "丙", ["对"], "phrase"), sample("miss", "陌生词", ["对"], "unmatched"),
                    sample("boundary", "。", [], "boundary")]
        result = evaluation.evaluate(examples, {"甲": ["对"], "乙": ["错一", "错二", "对"],
                                                "丙": ["错一", "错二", "错三", "对"]})
        overall = result["overall"]
        self.assertEqual(overall["lookup_hit"], evaluation.fraction(3, 5))
        self.assertEqual(overall["top1_acceptable_overall"], evaluation.fraction(1, 5))
        self.assertEqual(overall["top3_acceptable_overall"], evaluation.fraction(2, 5))
        self.assertEqual(overall["top3_acceptable_given_hit"], evaluation.fraction(2, 3))
        self.assertEqual(overall["boundary_no_prediction"], evaluation.fraction(1, 1))
        self.assertIsNone(result["by_kind"]["unmatched"]["top3_acceptable_given_hit"]["percent"])
        self.assertEqual(result["rows"][2]["first_acceptable_rank"], 4)

    def test_unmatched_probe_can_match_and_boundary_contamination_is_visible(self):
        examples = [sample("rare", "临时会场牌", ["位置"], "unmatched"),
                    sample("punctuation", "。", [], "boundary")]
        result = evaluation.evaluate(examples, {"临时会场牌": ["位置"], "。": ["后来"]})
        self.assertEqual(result["by_kind"]["unmatched"]["top3_acceptable_overall"]["numerator"], 1)
        self.assertEqual(result["by_kind"]["boundary"]["lookup_hit"]["numerator"], 1)
        self.assertEqual(result["overall"]["boundary_no_prediction"], evaluation.fraction(0, 1))
        self.assertEqual(result["overall"]["top3_acceptable_given_hit"], evaluation.fraction(1, 2))

    def test_replacement_gate_uses_full_denominator_and_exact_threshold(self):
        examples = [sample(str(i), f"键{i}", ["对"]) for i in range(200)]
        baseline_table = {f"键{i}": ["对"] for i in range(36)}
        baseline = evaluation.evaluate(examples, baseline_table)
        for extra, acceptable, passed in ((19, True, False), (20, True, True), (20, False, False)):
            table = {f"键{i}": ["对" if acceptable else "错"] for i in range(36 + extra)}
            gate = evaluation.quality_gate(baseline, evaluation.evaluate(examples, table))
            self.assertEqual(gate["quality_gate_passed"], passed)
            self.assertEqual(gate["hit_improvement_pp"], extra / 2)
        with self.assertRaisesRegex(ValueError, "denominators"):
            evaluation.quality_gate(baseline, evaluation.evaluate(examples[:100], baseline_table))

    def test_reports_are_deterministic_and_cannot_overwrite_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tsv"
            source.write_text("早上 好\t10\n今天 有空\t8\n")
            report = evaluation.build_report([source], [source])
            output, markdown = root / "report.json", root / "report.md"
            evaluation.write_reports(report, output, markdown, [source])
            before = (output.read_bytes(), markdown.read_bytes())
            again = evaluation.build_report([source], [source])
            evaluation.write_reports(again, output, markdown, [source])
            self.assertEqual(before, (output.read_bytes(), markdown.read_bytes()))
            self.assertFalse(report["gate"]["quality_gate_passed"])
            with self.assertRaisesRegex(ValueError, "overwrite"):
                evaluation.write_reports(report, source, None, [source])
            with self.assertRaisesRegex(ValueError, "differ"):
                evaluation.write_reports(report, output, output)
            self.assertEqual(source.read_text(), "早上 好\t10\n今天 有空\t8\n")

    def test_cli_failure_gate_is_explicit_and_baseline_matches_saved_report(self):
        script = PROJECT / "scripts" / "evaluate-prediction.py"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            result = subprocess.run([sys.executable, str(script), "--candidate", str(evaluation.DEFAULT_BASELINE),
                                     "--json", str(output), "--fail-on-gate"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(output.read_text())
            saved = json.loads((evaluation.DATA / "evaluation-starter-v1.report.json").read_text())
            self.assertEqual(report["baseline"]["overall"], saved["baseline"]["overall"])
            self.assertEqual(report["baseline"]["overall"]["lookup_hit"], evaluation.fraction(36, 200))
            self.assertEqual(report["baseline"]["overall"]["top3_acceptable_overall"], evaluation.fraction(30, 200))


if __name__ == "__main__":
    unittest.main()
