"""Data conversion must keep upstream ordering and reject ambiguous input."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("predict_builder", PROJECT / "scripts" / "build-predict-db.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PredictionDataTests(unittest.TestCase):
    def convert(self, text, max_candidates=8):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.tsv"
            path.write_text(text, encoding="utf-8")
            return builder.preprocess([path], max_candidates)

    def test_fixture_has_four_ordered_candidates_and_no_startup_menu(self):
        result = builder.preprocess([PROJECT / "data" / "prediction" / "fixture.ngram.tsv"])
        candidates = [line.split("\t")[1] for line in result.splitlines() if line.startswith("你好\t")]
        self.assertEqual(candidates, ["世界", "朋友", "今天", "第四项"])
        self.assertNotIn("$\t", result)

    def test_duplicate_keeps_max_weight_and_ties_keep_source_order(self):
        result = self.convert("前 甲\t10\n前 乙\t30\n前 甲\t30\n前 丙\t20\n", 2)
        self.assertEqual(result, "前\t甲\t30\n前\t乙\t30\n")

    def test_phrase_splits_at_unicode_characters_and_discards_end_marker(self):
        result = self.convert("你好世界\t12\n世界 $\t10\n")
        self.assertEqual(result, "你\t好世界\t12\n你好\t世界\t12\n你好世\t界\t12\n")

    def test_malformed_sources_fail_before_native_reader(self):
        for source in ("\n", "甲\t乙\t10\n", "甲 乙 丙\t10\n", "甲 乙\t-1\n", "甲 乙\t1.5\n", "甲 乙\t4294967296\n", "甲  乙\t10\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.convert(source)

    def test_empty_prediction_data_and_invalid_cap_fail(self):
        with self.assertRaises(ValueError):
            self.convert("甲\t10\n")
        with self.assertRaises(ValueError):
            self.convert("甲 乙\t10\n", 0)

    def test_controls_are_rejected_before_darts_can_truncate_a_key(self):
        for control in ("\0", "\x1b", "\x7f"):
            with self.subTest(control=repr(control)), self.assertRaisesRegex(ValueError, "control characters"):
                self.convert(f"甲{control}乙 丙\t10\n")

    def test_output_and_manifest_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.manifest.json"
            original = "甲 乙\t10\n"
            source.write_text(original)
            # These cases fail before preprocessing or compiler setup; no
            # native tool or source checkout is needed to protect the source.
            for output in (source, source.with_name("source.db")):
                with self.subTest(output=output.name), patch.object(builder, "compiler") as compile_tool:
                    with self.assertRaisesRegex(ValueError, "must not overwrite"):
                        builder.build([source], output, None)
                    compile_tool.assert_not_called()
                    self.assertEqual(source.read_text(), original)

    def test_failed_fetch_is_cleaned_up_and_retry_preserves_clean_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            revision = builder.REVISIONS["predict"][1]
            fetches = 0

            def fake_git(args, **kwargs):
                nonlocal fetches
                command = args[1] if args[1] == "init" else args[3]
                if command == "fetch":
                    fetches += 1
                    # Fetches happen in a staging directory, never in the
                    # final cache path, and the first one fails transiently.
                    self.assertNotEqual(Path(args[2]), cache / "predict")
                    if fetches == 1:
                        raise subprocess.CalledProcessError(128, args)
                stdout = revision + "\n" if command == "rev-parse" else ""
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            with patch.object(builder, "run", side_effect=fake_git):
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.checkout(cache, "predict", False)
                self.assertEqual(list(cache.iterdir()), [])
                installed = builder.checkout(cache, "predict", False)
                self.assertEqual(installed, cache / "predict")
                marker = installed / "keep.txt"
                marker.write_text("existing checkout")
                self.assertEqual(builder.checkout(cache, "predict", True), installed)
                self.assertEqual(marker.read_text(), "existing checkout")
                self.assertEqual(fetches, 2)

    def test_starter_scale_and_each_record_use_explicit_word_pairs(self):
        source = PROJECT / "data" / "prediction" / "starter.ngram.tsv"
        result = builder.preprocess([source])
        self.assertEqual(len(result.splitlines()), 896)
        self.assertEqual(len({line.split("\t")[0] for line in result.splitlines()}), 224)
        self.assertTrue(all(len(line.split("\t")[0].split(" ")) == 2 for line in source.read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
