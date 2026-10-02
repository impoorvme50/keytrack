"""Conservative table edits, full-key source ownership and truthful deltas."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts/refine-public-prediction.py"
spec = importlib.util.spec_from_file_location("refine_prediction", SCRIPT)
refiner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refiner)


class RefinePredictionTests(unittest.TestCase):
    def test_only_explicit_single_morphemes_and_chinese_numerals_are_removed(self):
        base = {"普通键": [("的", 50), ("了", 40), ("吧", 30), ("子", 20), ("二八", 10), ("二手", 9)]}
        tags = {"的": "uj", "了": "ul", "吧": "y", "子": "ng", "二八": "m", "二手": "n"}
        filtered, report = refiner.filter_table(base, {}, lambda x: [x], tags)
        self.assertEqual(filtered["普通键"], [("的", 50), ("了", 40), ("吧", 30), ("二手", 9)])
        self.assertEqual(report["removed_pairs_by_reason"],
                         {"chinese_numeral_candidate": 1, "single_dictionary_morpheme_candidate": 1})
        self.assertEqual(report["removed_keys"], 0)

    def test_abnormal_repeat_excludes_fragments_but_preserves_normal_grammar(self):
        tags = {"好": "a", "看": "v", "的": "uj", "不": "d", "没": "v", "说": "v"}
        self.assertTrue(refiner.abnormal_repetition(["是", "的", "是"], tags))
        self.assertTrue(refiner.abnormal_repetition(["准备", "准备"], tags))
        self.assertFalse(refiner.abnormal_repetition(["好", "不", "好"], tags))
        self.assertFalse(refiner.abnormal_repetition(["看", "没", "看"], tags))
        self.assertFalse(refiner.abnormal_repetition(["你", "说", "你"], tags))
        self.assertFalse(refiner.abnormal_repetition(["人人"], tags))

    def test_standalone_violent_tokens_are_removed_without_substring_matching(self):
        base = {"正常": [("杀菌", 40), ("砍价", 30), ("砍了他", 20)], "我杀": [("了", 10)]}
        tokens = {"正常": ["正常"], "杀菌": ["杀菌"], "砍价": ["砍价"],
                  "砍了他": ["砍", "了", "他"], "我杀": ["我", "杀"]}
        filtered, report = refiner.filter_table(base, {}, lambda x: tokens[x], {})
        self.assertEqual(filtered, {"正常": [("杀菌", 40), ("砍价", 30)]})
        self.assertEqual(report["removed_pairs_by_reason"],
                         {"independent_violent_candidate": 1, "independent_violent_key": 1})
        self.assertEqual(report["removed_keys"], 1)

    def test_starter_is_protected_and_sources_own_complete_keys(self):
        base = {"受管": [("子", 900000)], "补充键": [("旧词", 800000)], "保留键": [("旧候选", 700000)]}
        starter = {"受管": [("子", 100), ("原候选", 90)]}
        supplement = {"受管": [("不应覆盖", 100)], "补充键": [("新词", 100), ("备选", 90)], "新增键": [("新词", 100)]}
        filtered, filtering = refiner.filter_table(base, starter, lambda x: [x], {"子": "ng"})
        self.assertEqual(filtering["removed_pairs"], 0)
        merged, owners = refiner.merge_tables(filtered, supplement, starter)
        self.assertEqual(merged["受管"], starter["受管"])
        self.assertEqual(merged["补充键"], supplement["补充键"])
        self.assertEqual(merged["保留键"], base["保留键"])
        self.assertEqual(owners["受管"], "starter")
        self.assertEqual(owners["补充键"], "original_supplement")
        self.assertEqual(owners["保留键"], "public_v1")

    def test_delta_distinguishes_add_remove_and_reweight(self):
        before = {"甲": [("一", 10), ("二", 9)], "旧": [("词", 8)]}
        after = {"甲": [("一", 100), ("三", 90)], "新": [("词", 8)]}
        delta = refiner.changes(before, after)
        self.assertEqual(delta, {"before_keys": 2, "before_pairs": 3, "after_keys": 2, "after_pairs": 3,
                                 "removed_keys": 1, "added_keys": 1, "removed_pairs": 2, "added_pairs": 2,
                                 "reweighted_shared_pairs": 1})

    def test_table_preserves_stable_weight_ties_and_rejects_ambiguous_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tsv"
            path.write_text("前 乙\t10\n前 甲\t10\n前 丙\t20\n")
            self.assertEqual(refiner.read_table(path)["前"], [("丙", 20), ("乙", 10), ("甲", 10)])
            for text in ("甲乙\t5\n", "甲 乙\t-1\n", "甲 乙\t1.5\n", "甲 乙\t4294967296\n",
                         "甲 乙\t10\n甲 乙\t20\n", "甲  乙\t20\n"):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    refiner.read_table(path)

    def test_all_output_paths_protect_sources_and_reject_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("original")
            for name in ("refined.ngram.tsv", "public.ngram.tsv", "public.provenance.json", "public-review-sample.json", "public-filter-report.json"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    refiner.protect_outputs(root, [root / name])
            (root / "public.provenance.json").symlink_to(source)
            with self.assertRaises(ValueError):
                refiner.protect_outputs(root, [])
            self.assertEqual(source.read_text(), "original")

    def test_candidate_provenance_retains_both_statistical_and_original_sources(self):
        directory = PROJECT / "data/prediction/quality-v3"
        manifest = json.loads((directory / "public.provenance.json").read_text())
        self.assertEqual(manifest["generator_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        public_path = directory / "public.ngram.tsv"
        self.assertEqual(manifest["public_sha256"], hashlib.sha256(public_path.read_bytes()).hexdigest())
        base = refiner.read_table(PROJECT / "data/prediction/quality-v1/public.ngram.tsv")
        public = refiner.read_table(public_path)
        starter = refiner.read_table(PROJECT / "data/prediction/starter.ngram.tsv")
        supplement = refiner.read_table(PROJECT / "data/prediction/workday-supplement-v1.ngram.tsv")
        self.assertEqual(manifest["difference_from_public_v1"], refiner.changes(base, public))
        self.assertEqual(manifest["original_source_chain"]["public_sha256"], refiner.PINNED_V1)
        self.assertEqual(manifest["supplement_merge"]["input_keys"], 60)
        self.assertEqual(manifest["supplement_merge"]["input_pairs"], 180)
        for key, values in starter.items():
            self.assertEqual(public[key], values)
        for key, values in supplement.items():
            self.assertEqual(public[key], starter.get(key, values))
        report = json.loads((directory / "public-filter-report.json").read_text())
        self.assertEqual(len(report["rows"]), report["removed_pairs"])
        self.assertEqual(sum(report["removed_pairs_by_reason"].values()), report["removed_pairs"])


if __name__ == "__main__":
    unittest.main()
