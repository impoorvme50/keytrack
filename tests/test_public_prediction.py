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
    def test_phrase_keys_start_at_segment_boundary_and_words_remain_available(self):
        tokens = ["昨天", "听", "消息", "他", None, "我们", "准备", "讨论"]
        observed = {key for key, _, _ in module.contexts(tokens, segment_initial_phrases=True)}
        self.assertIn("昨天听消息", observed)
        self.assertIn("消息", observed)
        self.assertIn("我们准备", observed)
        self.assertNotIn("听消息", observed)
        self.assertNotIn("消息他", observed)

    def test_copied_utterance_across_dialogues_does_not_prove_language_diversity(self):
        counts = Counter({("我们", "讨论"): 20, ("我们", "确认"): 15})
        dialogues = Counter({("我们", "讨论"): 10, ("我们", "确认"): 8})
        utterances = Counter({("我们", "讨论"): 1, ("我们", "确认"): 3})
        result = module.select_records(counts, support=dialogues, min_count=8, min_dialogues=5,
                                       utterance_support=utterances, min_utterances=3)
        self.assertEqual([x[0] for x in result["我们"]], ["确认"])

    def test_quality_prefixes_reject_particles_and_repeated_fragments(self):
        tags = {"嗯": "e", "已经": "d", "准备": "v", "看": "v", "不": "d", "没": "v"}
        self.assertFalse(module.prefix_quality(["嗯", "准备"], tags))
        self.assertFalse(module.prefix_quality(["已经", "准备", "已经"], tags))
        self.assertTrue(module.prefix_quality(["看", "不", "看"], tags))
        self.assertTrue(module.prefix_quality(["看", "没", "看"], tags))
        self.assertFalse(module.prefix_quality(["准备", "准备"], tags))

    def test_multiword_completion_ends_in_content_and_stops_at_boundaries(self):
        tags = {"提供": "v", "资料": "n", "给": "p", "同事": "n", "次日": "t"}
        frequencies = dict.fromkeys(tags, 100)
        shapes = module.defaultdict(set)
        observed = list(module.pairs(["提供", "资料", "给", "同事", None, "次日"],
                                     tags=tags, frequencies=frequencies, max_candidate_words=3, shapes=shapes))
        self.assertIn(("提供", "资料给同事"), observed)
        self.assertIn(("提供", "资料"), observed)
        self.assertNotIn(("提供", "资料给"), observed)
        self.assertNotIn(("同事", "次日"), observed)
        self.assertEqual(shapes["资料给同事"], {("资料", "给", "同事")})

    def test_pos_hints_preserve_frequent_lexical_units_but_remove_numeric_fragments(self):
        tags = {"也": "d", "的": "uj", "能否": "c", "片刻": "m", "张小乙": "nr", "致谢": "nr", "很": "zg", "子": "ng", "没": "v"}
        frequency = {"也": 500000, "的": 500000, "能否": 11000, "片刻": 9000, "张小乙": 400, "致谢": 1200, "很": 60000, "子": 20000, "没": 50000}
        self.assertFalse(module.semantic_tail("也", tags, frequency))
        self.assertFalse(module.semantic_tail("的", tags, frequency))
        self.assertTrue(module.semantic_tail("能否", tags, frequency))
        self.assertFalse(module.semantic_tail("片刻", tags, frequency))
        self.assertFalse(module.semantic_tail("张小乙", tags, frequency))
        self.assertTrue(module.semantic_tail("致谢", tags, frequency))
        for word in ("很", "子", "没"):
            self.assertFalse(module.semantic_tail(word, tags, frequency))
        self.assertTrue(module.NUMERAL.fullmatch("一百二十"))
        self.assertFalse(module.NUMERAL.fullmatch("片刻"))

    def test_share_uses_all_key_positions_instead_of_filtered_candidate_total(self):
        counts = Counter({("借阅", "书籍"): 30, ("借阅", "杂志"): 29})
        support = Counter({("借阅", "书籍"): 6, ("借阅", "杂志"): 6})
        result = module.select_records(counts, min_count=8, min_dialogues=5,
                                       support=support, observations=Counter({"借阅": 1000}), min_share_percent=3)
        self.assertEqual(result["借阅"], [("书籍", 30000, 30)])

    def test_nested_completions_require_shared_tokens_and_dialogue_support(self):
        counts = Counter({("借阅", "读"): 100, ("借阅", "读完"): 75,
                          ("借阅", "读后感"): 80})
        support = Counter({("借阅", "读"): 80, ("借阅", "读完"): 60,
                           ("借阅", "读后感"): 70})
        shapes = {"读": {("读",)}, "读完": {("读", "完")}, "读后感": {("读后感",)}}
        result = module.select_records(counts, min_count=8, min_dialogues=5,
                                       support=support, observations=Counter({"借阅": 200}),
                                       min_share_percent=3, shapes=shapes)
        self.assertEqual([x[0] for x in result["借阅"]], ["读后感", "读完"])
        support["借阅", "读完"] = 20
        result = module.select_records(counts, support=support, shapes=shapes)
        self.assertIn("读", [x[0] for x in result["借阅"]])

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
        data = SCRIPT.parent.parent / "data/prediction/quality-v2"
        manifest = json.loads((data / "public.provenance.json").read_text())
        public = (data / "public.ngram.tsv").read_bytes()
        self.assertEqual(hashlib.sha256(public).hexdigest(), manifest["public_sha256"])
        generators = (SCRIPT, data / "generate-public-prediction.py")
        self.assertIn(manifest["generator_sha256"], {hashlib.sha256(x.read_bytes()).hexdigest() for x in generators})
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
        starter = data.parent / "starter.ngram.tsv"
        for row in starter.read_text().splitlines():
            self.assertIn(row, grouped[row.split(" ", 1)[0]])
        starter_counts = Counter(row.split(" ", 1)[0] for row in starter.read_text().splitlines())
        for key, count in starter_counts.items():
            self.assertEqual(len(grouped[key]), count)


if __name__ == "__main__":
    unittest.main()
