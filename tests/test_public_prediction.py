"""Synthetic data only: corpus boundary/aggregation/reproducibility contracts."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate-public-prediction.py"
spec = importlib.util.spec_from_file_location("public_prediction", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicPredictionTests(unittest.TestCase):
    def test_complete_commit_phrase_keys_and_hard_boundaries(self):
        observed = list(module.pairs(["我", "想", "去", "北京", None, "明天", "出发"]))
        self.assertIn(("我想去", "北京"), observed)
        self.assertIn(("想去", "北京"), observed)
        self.assertNotIn(("北京", "明天"), observed)
        self.assertNotIn(("我想去北京", "明天"), observed)
        self.assertIn(("明天", "出发"), observed)

    def test_prefix_length_limit(self):
        observed = list(module.pairs(["非常漫长的前置短语", "另外一个词", "后词"]))
        self.assertNotIn(("非常漫长的前置短语另外一个词", "后词"), observed)
        self.assertIn(("另外一个词", "后词"), observed)

    def test_aggregation_threshold_and_stable_ties(self):
        events = [("明天", "出发")] * 3 + [("明天", "休息")] * 3 + [("明天", "开会")] * 2
        left = module.select_records(Counter(events), min_count=3)
        right = module.select_records(Counter(reversed(events)), min_count=3)
        self.assertEqual(module.render(left), module.render(right))
        self.assertEqual([item[0] for item in left["明天"]], ["休息", "出发"])
        self.assertEqual([item[1] for item in left["明天"]], [500000, 500000])

    def test_starter_owns_keys_without_adding_weights(self):
        merged = module.merge_starter("你好 世界\t900000\n我想去 北京\t800000\n", "你好 朋友\t100\n")
        self.assertEqual(merged, "你好 朋友\t100\n我想去 北京\t800000\n")

    def test_candidate_limit_and_content_exclusion(self):
        counts = Counter({("明天", word): 5 for word in ["出发", "休息", "上班", "吃饭", "旅行", "下雨", "晴天", "工作", "学习"]})
        result = module.select_records(counts)
        self.assertEqual(len(result["明天"]), 8)
        for text in ("aaa", "电话123", "哈哈哈", "微信号", "约炮"):
            self.assertFalse(module.clean(text))

    def test_repetitions_in_one_dialogue_cannot_establish_support(self):
        counts = Counter({("明天", "出发"): 20, ("明天", "休息"): 6})
        support = Counter({("明天", "出发"): 1, ("明天", "休息"): 3})
        result = module.select_records(counts, support=support)
        self.assertEqual(result["明天"], [("休息", 1000000, 6)])

    def test_every_output_protects_source_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.json"
            source.write_text("original")
            for name in ("lccc.ngram.tsv", "public.ngram.tsv", "public-review-sample.json", "public.provenance.json"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    module.validate_outputs(root, [root / name])
            (root / "public.provenance.json").symlink_to(source)
            with self.assertRaises(ValueError):
                module.validate_outputs(root, [])
            self.assertEqual(source.read_text(), "original")

    def test_repeated_text_across_pair_boundary_is_excluded(self):
        counts = Counter({("别别", "别"): 25, ("明天", "出发"): 5})
        result = module.select_records(counts)
        self.assertEqual(set(result), {"明天"})

    def test_generated_resource_matches_provenance_and_preserves_starter(self):
        data = SCRIPT.parent.parent / "data/prediction"
        manifest = json.loads((data / "public.provenance.json").read_text())
        public = (data / "public.ngram.tsv").read_bytes()
        self.assertEqual(hashlib.sha256(public).hexdigest(), manifest["public_sha256"])
        self.assertEqual(hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), manifest["generator_sha256"])
        self.assertEqual(hashlib.sha256((data / "lccc.ngram.tsv").read_bytes()).hexdigest(), manifest["corpus_sha256"])
        rows = public.decode().splitlines()
        self.assertEqual(len(rows), manifest["public_records"])
        grouped = {}
        for row in rows:
            text, weight = row.split("\t")
            key, candidate = text.split(" ")
            grouped.setdefault(key, []).append(row)
        self.assertEqual(len(grouped), manifest["public_contexts"])
        self.assertTrue(all(len(values) <= 8 for values in grouped.values()))
        for row in (data / "starter.ngram.tsv").read_text().splitlines():
            self.assertIn(row, grouped[row.split(" ", 1)[0]])
        starter_counts = Counter(row.split(" ", 1)[0] for row in (data / "starter.ngram.tsv").read_text().splitlines())
        for key, count in starter_counts.items():
            self.assertEqual(len(grouped[key]), count)


if __name__ == "__main__":
    unittest.main()
