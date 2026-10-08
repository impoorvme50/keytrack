"""Statistics, frozen provenance and failure handling; no model weights needed."""
from __future__ import annotations
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from keytrack import kev_eval, kev_rime_bridge as bridge


def example(identity="a", kind="complete_word", acceptable=None, candidates=None):
    return {"id": identity, "kind": kind, "domain": "daily", "situation": "public_test",
            "input": "yisheng", "previous_text": "公开测试", "candidates": candidates or ["一生", "医生", "一声", "一升", "已生"],
            "acceptable": ["医生"] if acceptable is None else acceptable}


def decision(index=2, probability=0.93, margin=0.86):
    return {"index": index, "probability": probability, "margin": margin}


class StatisticsTests(unittest.TestCase):
    def test_rescue_regression_wrong_promotion_and_distinct_denominators(self):
        rows = [
            kev_eval.score_row(example("rescue"), decision()),
            kev_eval.score_row(example("regress", acceptable=["一生"]), decision()),
            kev_eval.score_row(example("still_wrong", acceptable=["一声"]), decision()),
            kev_eval.score_row(example("absent", acceptable=["衣生"]), decision(probability=0.7, margin=0.5)),
            kev_eval.score_row(example("reject", kind="reject", acceptable=[]), decision()),
            kev_eval.score_row(example("failure", acceptable=["一生"]), {"error": "timeout"}),
            kev_eval.score_row(example("equivalent", kind="ambiguous", acceptable=["一生", "医生"]), decision()),
        ]
        result = kev_eval.metrics(rows)
        self.assertEqual(result["samples"], 7)
        self.assertEqual(result["baseline_top1"]["numerator"], 3)
        self.assertEqual(result["baseline_top1"]["denominator"], 6)
        self.assertEqual(result["effective_top1"]["numerator"], 3)
        self.assertEqual(result["effective_top1_given_pool_coverage"]["denominator"], 5)
        self.assertEqual(result["target_absent"], 1)
        self.assertEqual(result["rescued"], 1)
        self.assertEqual(result["regressed"], 1)
        self.assertEqual(result["wrong_promotion"], 3)
        self.assertEqual(result["wrong_promotion_rate"]["denominator"], 5)
        self.assertEqual(result["regression_rate_given_baseline_correct"]["denominator"], 3)
        self.assertEqual(result["no_change"], 2)
        self.assertEqual(result["abstained"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["reject_no_promotion"]["numerator"], 0)
        self.assertEqual(sum(result["outcomes"].values()), 7)
        self.assertEqual(result["raw_model_top1_given_success"]["denominator"], 5)
        self.assertEqual(result["raw_model_top1_given_success"]["numerator"], 2)
        self.assertEqual(result["raw_model_rescues_unadopted_diagnostic"], 1)
        self.assertEqual(result["raw_model_regressions_unadopted_diagnostic"], 1)

    def test_weak_wrong_choice_keeps_original_and_is_not_a_regression(self):
        row = kev_eval.score_row(example(acceptable=["一生"]), decision(probability=0.89, margin=0.8))
        self.assertEqual(row["effective_index"], 1)
        self.assertTrue(row["effective_correct"])
        self.assertTrue(row["abstained"])
        self.assertFalse(row["regressed"])
        self.assertFalse(row["promoted"])

    def test_exact_adoption_boundaries_match_bridge(self):
        self.assertTrue(kev_eval.score_row(example(), decision(probability=bridge.MIN_PROBABILITY,
                        margin=bridge.MIN_MARGIN))["adopted"])
        for values in ((0.8999999, 0.3), (0.9, 0.2999999)):
            self.assertFalse(kev_eval.score_row(example(), decision(probability=values[0], margin=values[1]))["adopted"])

    def test_strong_first_choice_is_adopted_but_does_not_promote(self):
        row = kev_eval.score_row(example(), decision(index=1))
        self.assertTrue(row["adopted"])
        self.assertFalse(row["abstained"])
        self.assertFalse(row["promoted"])
        self.assertEqual(row["outcome"], "kept_first")

    def test_ambiguous_equivalent_full_answers_do_not_count_as_wrong(self):
        row = kev_eval.score_row(example(kind="ambiguous", acceptable=["一生", "医生"]), decision())
        self.assertEqual(row["outcome"], "equivalent_change")
        self.assertFalse(row["wrong_promotion"])

    def test_sentence_prefix_is_not_full_answer(self):
        row = kev_eval.score_row(example(kind="complete_sentence", candidates=["我明天过来", "我明天", "我命", "我", "握"],
                    acceptable=["我明天过来"]), decision())
        self.assertTrue(row["regressed"])
        self.assertTrue(row["wrong_promotion"])

    def test_empty_denominators_are_null_not_perfect(self):
        result = kev_eval.metrics([])
        self.assertIsNone(result["baseline_top1"]["percent"])
        self.assertIsNone(result["wrong_promotion_rate"]["percent"])
        self.assertIsNone(result["reject_no_promotion"]["percent"])

    def test_invalid_decisions_rejected_before_statistics(self):
        for values in ({"index": True, "probability": 0.9, "margin": 0.3},
                       decision(index=0), decision(index=6), decision(probability=float("nan")),
                       decision(margin=float("inf")), decision(probability=1.1),
                       decision(probability=True), decision(margin=-0.1),
                       decision(probability=0.2, margin=0.3)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                kev_eval.score_row(example(), values)
        with self.assertRaises(ValueError):
            kev_eval.score_row(example(), {"error": "server echoed content"})
        row = kev_eval.score_row(example(), {**decision(), "timing": {
            "model_ms": 1.5, "http_ms": float("nan"), "private_text": "do not retain", "bridge_ms": -1}})
        self.assertEqual(row["timing"], {"model_ms": 1.5})


class FrozenDataTests(unittest.TestCase):
    def test_both_frozen_versions_are_public_balanced_and_contain_60(self):
        for version in (1, 2):
            frozen = kev_eval.load_dataset(kev_eval.DATA / f"evaluation-v{version}.json")
            self.assertEqual(len(frozen["data"]["examples"]), 60)
            self.assertEqual(frozen["manifest"]["domain_counts"], {"daily": 30, "work": 30})
            self.assertEqual(frozen["manifest"]["kind_counts"], {"complete_word": 24,
                "complete_sentence": 18, "ambiguous": 12, "reject": 6})
        native = frozen["manifest"]["candidate_provenance"]
        self.assertFalse(native["user_dictionary_enabled"])
        self.assertEqual(native["text_commits"], 0)
        self.assertFalse(native["lua_or_logger_loaded"])
        self.assertEqual([x["file"] for x in native["public_binary_sources"]],
                         ["rime_ice.table.bin", "rime_ice.prism.bin"])

    def test_changed_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("evaluation-v1.json", "evaluation-v1.manifest.json", "LICENSE.txt"):
                (root / name).write_bytes((kev_eval.DATA / name).read_bytes())
            with (root / "evaluation-v1.json").open("a") as file:
                file.write(" ")
            with self.assertRaisesRegex(ValueError, "frozen manifest"):
                kev_eval.load_dataset(root / "evaluation-v1.json")

    def test_decision_ids_cannot_omit_or_add_samples(self):
        frozen = kev_eval.load_dataset()
        for decisions in ({}, {"unknown": decision()}):
            with self.assertRaisesRegex(ValueError, "exactly"):
                kev_eval.build_report(frozen, decisions, "offline_injected_decisions")

    def test_offline_report_never_calls_transport_and_excludes_text(self):
        frozen = kev_eval.load_dataset()
        decisions = {x["id"]: decision(index=1) for x in frozen["data"]["examples"]}
        with patch.object(bridge, "open_local", side_effect=AssertionError("unexpected network")):
            report = kev_eval.build_report(frozen, decisions, "offline_injected_decisions")
        self.assertEqual(report["overall"]["samples"], 60)
        self.assertFalse(report["thresholds"]["calibrated"])
        self.assertNotIn("previous_text", report["rows"][0])
        self.assertNotIn("candidates", report["rows"][0])

    def test_report_outputs_cannot_overwrite_frozen_sources_or_each_other(self):
        with self.assertRaises(ValueError):
            kev_eval.write_reports({}, kev_eval.DEFAULT_DATASET, None, [kev_eval.DEFAULT_DATASET])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "same"
            with self.assertRaises(ValueError):
                kev_eval.write_reports({}, path, path, [])


class LiveObservationTests(unittest.TestCase):
    def test_existing_bridge_validates_response_and_observer_is_restored(self):
        class Response(io.BytesIO):
            status = 200
        payload = {"latency_ms": 17.5, "answers": {"next": {"choice": "c2",
            "probabilities": {"c1": 0.02, "c2": 0.93, "c3": 0.02, "c4": 0.02, "c5": 0.01}}}}
        with patch.object(bridge, "open_local", return_value=Response(json.dumps(payload).encode())) as opener:
            result = kev_eval.live_decision(example())
            self.assertIs(bridge.open_local, opener)
        self.assertEqual(result["index"], 2)
        self.assertEqual(result["probability"], 0.93)
        self.assertEqual(result["timing"]["model_ms"], 17.5)
        self.assertGreaterEqual(result["timing"]["bridge_ms"], result["timing"]["http_ms"])
        self.assertEqual(opener.call_args.args[0].full_url, bridge.DEFAULT_URL)

    def test_server_errors_fall_back_without_error_content(self):
        with patch.object(bridge, "decide_candidate", side_effect=ValueError("private server content")):
            result = kev_eval.live_decision(example())
        self.assertEqual(result["error"], "invalid_response")
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(kev_eval.score_row(example(), result)["effective_index"], 1)
        self.assertEqual(kev_eval.error_category(urllib.error.URLError(TimeoutError())), "timeout")

    def test_invalid_server_probability_distribution_is_not_a_model_decision(self):
        class Response(io.BytesIO):
            status = 200
        bad = {"latency_ms": 1, "answers": {"next": {"choice": "c2",
               "probabilities": {"c1": 0.1, "c2": 0.9, "c3": 0.9, "c4": 0.9, "c5": 0.9}}}}
        with patch.object(bridge, "open_local", return_value=Response(json.dumps(bad).encode())):
            raw = kev_eval.live_decision(example())
        row = kev_eval.score_row(example(), raw)
        self.assertEqual(row["error"], "invalid_response")
        self.assertIsNone(row["raw_correct"])
        self.assertFalse(row["abstained"])
        self.assertFalse(row["promoted"])

    def test_cold_start_is_not_inferred_from_first_request(self):
        rows = [{"timing": {"model_ms": 20, "http_ms": 30, "bridge_ms": 31}},
                {"timing": {"model_ms": 10, "http_ms": 15, "bridge_ms": 16}}]
        result = kev_eval.latency_report(rows)
        self.assertFalse(result["cold_start"]["measured"])
        self.assertFalse(result["menu_visible_latency"]["measured"])
        self.assertEqual(result["first_request_on_existing_service"]["model_ms"]["median_ms"], 20)
        self.assertEqual(result["warm_subsequent_requests"]["model_ms"]["median_ms"], 10)
        self.assertEqual(kev_eval.timing_summary([1, 2, 3, 4, 100])["p95_ms"], 100)

    def test_transport_refuses_remote_and_redirect_urls(self):
        for url in ("http://localhost:8009/v1/systemone", "https://example.com", "http://127.0.0.1:8009/other"):
            with self.assertRaises(ValueError):
                bridge.open_local(urllib.request.Request(url), timeout=1)

    def test_live_mode_must_be_explicit(self):
        spec = importlib.util.spec_from_file_location("evaluate_kev_script", kev_eval.PROJECT / "scripts/evaluate-kev.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(kev_eval, "run_live") as live, patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                module.main([])
        self.assertEqual(error.exception.code, 2)
        live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
