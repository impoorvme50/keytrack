"""Discovery uses synthetic history only, including read-only/WAL boundaries."""
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from keytrack import console, phrase_discovery as discovery, storage


class PhraseDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / "history.db"
        self.today = date(2026, 10, 3)
        self.start = datetime(2026, 10, 3, 9, tzinfo=discovery.ZONE).timestamp()
        self.store = console.ConsoleStore(self.root / "console", self.root / "Rime", str(self.db), demo=True)
        with storage.connect(str(self.db)):
            pass

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def insert(self, text, offset=0, app="测试应用", window="合成窗口"):
        with self.connection() as connection:
            connection.execute("INSERT INTO segments (app,window,start_ts,end_ts,text,key_count) VALUES (?,?,?,?,?,?)",
                               (app, window, self.start + offset, self.start + offset + 1, text, len(text)))

    def repeated(self, text, offsets=(0, 60, 3600)):
        for offset in offsets:
            self.insert(text, offset)

    def analyze(self, phrases=None, rejected=None, days=30):
        return discovery.discover(str(self.db), days, phrases or [], rejected or set(), today=self.today)

    def test_complete_expression_keeps_original_punctuation_and_no_substring_mining(self):
        text = "收到，谢谢。我会核对后回复。"
        self.repeated(text)
        before = self.db.read_bytes()
        result = self.analyze()
        self.assertEqual([item["text"] for item in result["candidates"]], [text])
        item = result["candidates"][0]
        self.assertEqual((item["count"], item["batch_count"]), (3, 2))
        self.assertIn("不代表真实输入会话", result["batch_basis"])
        self.assertEqual(before, self.db.read_bytes())
        self.assertFalse(self.store.root.exists())

    def test_same_record_repetition_does_not_inflate_counts(self):
        text = "我们会在确认细节后安排发货。"
        self.insert(text + "\n" + text)
        self.insert(text, 3600)
        self.assertEqual(self.analyze()["candidates"], [])

    def test_whole_periodic_repetition_is_filtered_without_losing_complete_lines(self):
        text = "我们会在确认细节后安排发货。"
        other = "样品准备好后，我会通知您。"
        for repetitions in range(2, 6):
            repeated = text * repetitions
            with self.subTest(repetitions=repetitions):
                self.assertEqual(discovery.expressions(repeated), set())
            self.repeated(repeated)
        unit = ''.join(chr(0x4E00 + index) for index in range(80))
        self.assertEqual(discovery.expressions(unit), {unit})
        self.assertEqual(discovery.expressions(unit * 2), set())
        self.assertEqual(discovery.expressions(text), {text})
        self.assertIn(text + other, discovery.expressions(text + other))
        different_lines = text + "\n" + other
        self.assertEqual(discovery.expressions(different_lines), {different_lines, text, other})
        self.assertEqual(discovery.expressions(different_lines + "\n" + different_lines), {text, other})
        self.assertEqual(discovery.expressions(text + "\n" + text), {text})
        self.assertEqual(discovery.expressions("收到" * 3), set())
        self.repeated(text + "\n" + text)
        result = self.analyze()
        self.assertEqual([item["text"] for item in result["candidates"]], [text])
        self.assertEqual(result["candidates"][0]["count"], 3)

    def test_three_occurrences_in_one_batch_are_not_suggested(self):
        self.repeated("样品准备好后，我会通知您。", (0, 20, 40))
        self.assertEqual(self.analyze()["candidates"], [])

    def test_continuous_records_do_not_become_batches_at_fixed_bucket_boundaries(self):
        self.repeated("样品准备好后，我会通知您。", (0, 1000, 2000))
        self.assertEqual(self.analyze()["candidates"], [])

    def test_intervening_other_text_keeps_a_continuous_history_batch(self):
        self.repeated("样品准备好后，我会通知您。", (0, 1800, 3600))
        self.insert("其他记录仍在连续输入。", 900)
        self.insert("其他记录仍在连续输入。", 2700)
        self.assertEqual(self.analyze()["candidates"], [])

    def test_long_record_duration_prevents_a_false_idle_gap(self):
        self.repeated("样品准备好后，我会通知您。", (0, 2000, 4000))
        with self.connection() as connection:
            connection.execute("UPDATE segments SET end_ts=start_ts+1900")
        self.assertEqual(self.analyze()["candidates"], [])

    def test_english_complete_expressions_and_crlf_lines_remain_savable(self):
        english = "Thank you for your inquiry. We will confirm the sample details shortly."
        self.repeated(english)
        self.repeated("样品准备好后，我会通知您。\r\n我们会在确认细节后安排发货。")
        result = self.analyze()
        self.assertIn(english, {item["text"] for item in result["candidates"]})
        self.assertTrue(all("\r" not in item["text"] for item in result["candidates"]))
        for item in result["candidates"]:
            console.validate_phrases([{"code": item["suggested_code"], "text": item["text"]}])

    def test_app_window_batches_and_equal_timestamp_are_safe(self):
        text = "细节确认完成后请回复我。"
        for window in (None, "合成窗口", "合成窗口二"):
            self.insert(text, window=window)
        self.assertEqual(self.analyze()["candidates"][0]["batch_count"], 3)

    def test_range_is_calendar_days_and_future_outside_range_is_excluded(self):
        self.repeated("我们会在确认细节后安排发货。", (-7 * 86400, -6 * 86400, 0))
        self.assertEqual(self.analyze(days=7)["candidates"], [])
        self.assertEqual(self.analyze(days=30)["candidates"][0]["count"], 3)
        self.insert("我们会在确认细节后安排发货。", 86400)
        self.assertEqual(self.analyze(days=30)["candidates"][0]["count"], 3)
        for days in (True, "30", 1, 365):
            with self.assertRaises(ValueError):
                self.analyze(days=days)

    def test_sensitive_lines_and_fragments_are_filtered_without_returning_them(self):
        for text in ("谢谢", "请发至我的地址然后通知我。", "我的电话是13800138000请联系。",
                     "请邮件联系 test@example.invalid 谢谢。", "请查看https://example.invalid详细信息。",
                     "收到收到收到收到收到收到", "请寄至测试路三号后通知我。", "请确认\x00之后再安排发货。"):
            self.repeated(text)
        for text in ("Please send samples to 123 Main Street.", "My password is something private.",
                     "Please confirm my bank account before payment.", "<script>repeat something here</script>",
                     "My contact number is +33 6 12 34 56 78. Please call me.",
                     "一三八零零一三八零零零请尽快联系。"):
            self.repeated(text)
        self.assertEqual(self.analyze()["candidates"], [])

    def test_multiline_preserves_whole_expression_and_lines(self):
        text = "样品准备好后，我会通知您。\n我们会在确认细节后安排发货。"
        self.repeated(text)
        texts = {item["text"] for item in self.analyze()["candidates"]}
        self.assertEqual(texts, {text, *text.splitlines()})

    def test_duplicate_is_marked_and_suggested_codes_avoid_existing_codes(self):
        text = "收到，谢谢。我会核对后回复。"
        self.repeated(text)
        item = self.analyze([{"text": text, "code": "qreply"}])["candidates"][0]
        self.assertTrue(item["duplicate"])
        self.assertEqual(item["existing_code"], "qreply")
        code = discovery.suggested_code("样品准备好后，我会通知您。", set())
        self.repeated("样品准备好后，我会通知您。")
        result = self.analyze([{"text": "其他已有表达", "code": code}])
        suggestions = [item["suggested_code"] for item in result["candidates"]]
        self.assertEqual(len(suggestions), len(set(suggestions)))
        self.assertNotIn(code, suggestions)
        self.assertTrue(all(console.validate_phrases([{"code": value, "text": "合成测试表达"}]) for value in suggestions))

    def test_scan_and_output_limits_report_partial_counts(self):
        self.repeated("样品准备好后，我会通知您。")
        self.repeated("我们会在确认细节后安排发货。")
        with patch.object(discovery, "MAX_SEGMENTS", 2):
            result = self.analyze()
            self.assertEqual(result["scanned_segments"], 2)
            self.assertTrue(result["truncated"])
        with patch.object(discovery, "MAX_CANDIDATES", 1):
            result = self.analyze()
            self.assertEqual(len(result["candidates"]), 1)
            self.assertTrue(result["truncated"])
            self.assertIn("次数仅表示已扫描记录", result["message"])

    def test_metadata_is_bounded_and_does_not_merge_truncated_titles(self):
        for offset in (0, 3600, 7200):
            self.insert("样品准备好后，我会通知您。", offset, window="标题" * 100_000)
        result = self.analyze()
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["scanned_segments"], 3)

    def test_read_only_query_sees_current_wal_without_changing_schema_or_journal(self):
        with self.connection() as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            text = "样品准备好后，我会通知您。"
            for offset in (0, 60, 3600):
                writer.execute("INSERT INTO segments (app,window,start_ts,end_ts,text,key_count) VALUES (?,?,?,?,?,?)",
                               ("测试", None, self.start + offset, self.start + offset + 1, text, len(text)))
            writer.commit()
            schema = writer.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
            self.assertEqual(self.analyze()["candidates"][0]["count"], 3)
            self.assertEqual(schema, writer.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall())
            self.assertEqual(writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_missing_database_does_not_create_files(self):
        missing = self.root / "missing" / "history.db"
        self.assertEqual(discovery.discover(str(missing), 30, [], set(), today=self.today)["candidates"], [])
        self.assertFalse(missing.parent.exists())

    def test_native_analysis_and_rejection_do_not_change_configuration_or_revision(self):
        text = "样品准备好后，我会通知您。"
        self.repeated(text)
        revision = self.store.revision()
        with patch.object(discovery, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 3, tzinfo=discovery.ZONE)
            clock.combine = datetime.combine
            clock.min = datetime.min
            result = console.native_request(self.store, {"action": "phrase_discovery", "days": 30})
        token = result["candidates"][0]["id"]
        reply = console.native_request(self.store, {"action": "phrase_discovery_reject", "ids": [token]})
        self.assertEqual(reply["revision"], revision)
        self.assertEqual(self.store.revision(), revision)
        path = self.store.root / "discovery-rejected.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(text, path.read_text())
        self.assertEqual(self.analyze(rejected=self.store.discovery_rejected())["candidates"], [])
        for target in self.store.targets.values():
            self.assertFalse(target.exists())
        self.assertFalse((self.store.root / "backups").exists())

    def test_reject_requires_issued_candidates_and_preserves_corrupt_storage(self):
        for ids in ([], [discovery.identity("未分析的合成表达")], [123], "bad"):
            with self.assertRaises(ValueError):
                self.store.reject_discovered_phrases(ids)
        self.store.root.mkdir()
        path = self.store.root / "discovery-rejected.json"
        path.write_text("broken-json")
        with self.assertRaises(ValueError):
            self.store.discovery_rejected()
        self.assertEqual(path.read_text(), "broken-json")

    def test_rejection_symlinks_and_capacity_refuse_without_overwriting(self):
        self.store.root.mkdir()
        source = self.root / "protected.json"
        source.write_text('{"version": 1, "ids": []}')
        path = self.store.root / "discovery-rejected.json"
        path.symlink_to(source)
        with self.assertRaises(ValueError):
            self.store.discovery_rejected()
        self.assertEqual(source.read_text(), '{"version": 1, "ids": []}')
        path.unlink()
        existing = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(2)]
        path.write_text(json.dumps({"version": 1, "ids": existing}))
        token = discovery.identity("样品准备好后，我会通知您。")
        self.store._discovery_ids = {token}
        with patch.object(discovery, "MAX_REJECTED", 2), self.assertRaises(ValueError):
            self.store.reject_discovered_phrases([token])
        self.assertEqual(json.loads(path.read_text())["ids"], existing)

    def test_fifo_rejection_file_is_refused_without_waiting_for_a_writer(self):
        self.store.root.mkdir()
        path = self.store.root / "discovery-rejected.json"
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            self.store.discovery_rejected()
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
