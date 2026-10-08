"""New console controls and private-pipe interchange use synthetic state only."""
import json
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keytrack import annotations, console, input_tools, kev_rime_setup, phrase_exchange, prediction_setup
from tests.test_prediction import DAILY


PROJECT = Path(__file__).resolve().parent.parent
TOOLS_DAILY = (DAILY.replace("engine:\n", "  - name: emoji\n    reset: 1 # synthetic default\nengine:\n")
               + "melt_eng:\n  dictionary: melt_eng\n  enable_completion: false # synthetic English default\n"
               + "cn_en:\n  enable_completion: true # synthetic mixed default\n")


def custom_gloss(en="synthetic sample", ja="合成サンプル"):
    return [{"word": "样品", "en": en, "ja": ja, "reading": "さんぷる"}]


class MSIMEConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rime = self.root / "Rime"
        (self.rime / "build").mkdir(parents=True)
        (self.rime / "build/rime_ice.schema.yaml").write_text(TOOLS_DAILY)
        self.schema = self.rime / f"{prediction_setup.SCHEMA}.schema.yaml"
        self.schema.write_text(prediction_setup.render_schema(TOOLS_DAILY).replace(
            "  hotkey: Control+Shift+k\n", '  hotkey: "Control+Shift+k"\n'))
        self.daily = self.rime / "rime_ice.custom.yaml"
        self.daily.write_text(kev_rime_setup.render_custom_yaml(
            '# synthetic original\npatch:\n  "menu/page_size": 7\n', Path("/tmp/synthetic-python"), Path("/tmp/synthetic-bridge")))
        (self.rime / "squirrel.custom.yaml").write_text("# synthetic squirrel\npatch:\n  unrelated: true\n")
        self.history = self.root / "synthetic.db"
        self.history.write_bytes(b"synthetic sentinel: settings must not open this file")
        self.kev_sentinel = self.root / "synthetic-kev-enabled"
        self.kev_sentinel.write_text("1\n")
        self.store = console.ConsoleStore(self.root / "console", self.rime, str(self.history), demo=True)
        self.store.save_prediction({"enabled": True, "max_candidates": 4})

    def files(self):
        return {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def save(self, **changes):
        state = self.store.state()
        return self.store.save_settings(dict(state["settings"], **changes), state["revision"])

    def assert_switches_and_history(self, prediction):
        self.assertEqual(self.store.prediction_state(), prediction)
        self.assertEqual(self.kev_sentinel.read_text(), "1\n")
        self.assertEqual(self.history.read_bytes(), b"synthetic sentinel: settings must not open this file")

    def test_default_preserve_does_not_rewrite_daily_tool_values_or_snapshot(self):
        before_daily, before_schema = self.daily.read_text(), self.schema.read_text()
        state = self.store.state()
        self.assertTrue(all(state["settings"][field] == "existing" for field in input_tools.FIELDS))
        self.save(font_size=18)
        self.assertNotIn(input_tools.BEGIN, self.daily.read_text())
        self.assertEqual(self.schema.read_text(), before_schema)
        self.assertIn('"menu/page_size": 7', self.daily.read_text())
        self.assertIn(kev_rime_setup.BEGIN, before_daily)
        self.assert_switches_and_history(state["prediction"])

    def test_tool_controls_sync_daily_and_snapshot_and_restore_exact_originals(self):
        original = self.store.state()
        original_schema = self.schema.read_text()
        saved = self.save(english_completion="on", mixed_completion="off", emoji_default="off")
        self.assertIn('"melt_eng/enable_completion": true', self.daily.read_text())
        self.assertIn('"cn_en/enable_completion": false', self.daily.read_text())
        self.assertIn('"switches/@1/reset": 0', self.daily.read_text())
        self.assertIn("melt_eng:\n  dictionary: melt_eng\n  enable_completion: true\n", self.schema.read_text())
        self.assertIn("cn_en:\n  enable_completion: false\n", self.schema.read_text())
        self.assertIn("  - name: emoji\n    reset: 0\n", self.schema.read_text())
        self.save(english_completion="off", mixed_completion="on", emoji_default="on")
        self.save(**{field: "existing" for field in input_tools.FIELDS})
        self.assertEqual(self.schema.read_text(), original_schema)
        self.assertNotIn(input_tools.BEGIN, self.daily.read_text())
        self.assert_switches_and_history(original["prediction"])
        self.store.restore(saved["backup"], self.store.revision())
        self.assertEqual(self.schema.read_text(), original_schema)
        self.assertTrue(all(self.store.state()["settings"][field] == "existing" for field in input_tools.FIELDS))
        self.assert_switches_and_history(original["prediction"])

    def test_legacy_clients_missing_new_fields_keep_current_choices(self):
        choices = {"english_completion": "on", "mixed_completion": "off", "emoji_default": "off",
                   "gloss_language": "ja", "gloss_overrides": custom_gloss()}
        self.save(**choices)
        state = self.store.state()
        old = {key: value for key, value in state["settings"].items()
               if key not in (*input_tools.FIELDS, "gloss_language", "gloss_overrides")}
        old["font_size"] = 20
        self.store.save_settings(old, state["revision"])
        current = self.store.state()
        for field, value in choices.items():
            self.assertEqual(current["settings"][field], value)
        self.assertEqual(current["settings"]["font_size"], 20)
        self.assert_switches_and_history(state["prediction"])

    def test_independent_tool_patch_rejection_leaves_all_files_and_backups_unchanged(self):
        self.daily.write_text(self.daily.read_text() + '  "melt_eng/enable_completion": false\n')
        before = self.files()
        with self.assertRaisesRegex(ValueError, "占用"):
            self.save(english_completion="on")
        self.assertEqual(self.files(), before)
        self.assertEqual(self.store.backups(), [])

    def test_overrides_while_initially_off_are_saved_without_optional_install(self):
        before = self.store.state()
        saved = self.save(gloss_overrides=custom_gloss())
        current = self.store.state()
        self.assertEqual(current["settings"]["gloss_language"], "off")
        self.assertEqual(current["settings"]["gloss_overrides"], custom_gloss())
        self.assertEqual(current["glossary"]["override_count"], 1)
        self.assertFalse(annotations.settings_path(self.rime).exists())
        self.assertFalse((self.rime / "lua/keytrack_glossary.lua").exists())
        self.assertNotIn("gloss_overrides", json.loads(self.store.targets["settings.json"].read_text()))
        self.assert_switches_and_history(before["prediction"])
        self.store.restore(saved["backup"], self.store.revision())
        self.assertEqual(self.store.state()["settings"]["gloss_overrides"], [])

    def test_enabled_then_off_override_updates_and_backup_restore_keep_switches(self):
        original = self.store.state()
        self.save(gloss_language="en", gloss_overrides=custom_gloss("first synthetic gloss"))
        table = self.rime / "lua/keytrack_glossary.lua"
        self.assertIn("first synthetic gloss", table.read_text())
        self.assertIn('language: "en"', self.schema.read_text())
        saved = self.save(gloss_language="off", gloss_overrides=custom_gloss("second synthetic gloss"))
        self.assertIn("second synthetic gloss", table.read_text())
        self.assertNotIn("first synthetic gloss", table.read_text())
        self.assertEqual(annotations.language(self.rime), "off")
        self.daily.write_text(self.daily.read_text() + "\nexternal_note:\n  retained: true\n")
        self.store.restore(saved["backup"], self.store.revision())
        state = self.store.state()
        self.assertEqual(state["settings"]["gloss_language"], "en")
        self.assertEqual(state["settings"]["gloss_overrides"], custom_gloss("first synthetic gloss"))
        self.assertIn("first synthetic gloss", table.read_text())
        self.assertNotIn("second synthetic gloss", table.read_text())
        self.assertIn("external_note:\n  retained: true\n", self.daily.read_text())
        self.assertIn('language: "en"', self.schema.read_text())
        self.assert_switches_and_history(original["prediction"])

    def test_override_revision_and_invalid_unicode_fail_before_any_write(self):
        self.save(gloss_overrides=custom_gloss())
        state = self.store.state()
        self.store.targets["glossary-overrides.json"].write_text(json.dumps(custom_gloss("external synthetic edit")))
        before = self.files()
        with self.assertRaisesRegex(ValueError, "修改"):
            self.store.save_settings(state["settings"], state["revision"])
        self.assertEqual(self.files(), before)
        for invalid in (custom_gloss("\ud800"), [{"word": "样品", "en": "x", "ja": "x", "unsupported": True}]):
            before = self.files()
            with self.assertRaises(ValueError):
                self.save(gloss_overrides=invalid)
            self.assertEqual(self.files(), before)

    def test_preview_and_export_requests_never_write_files_or_read_history(self):
        current = self.store.state()
        draft = [{"code": "qdraft", "text": "草稿表达", "category": "测试"}]
        incoming = [{"code": "qdraft", "text": "冲突表达", "category": "测试"},
                    {"code": "qnew", "text": '原话\n带 "引号"\t制表符', "category": "测试"}]
        content = phrase_exchange.export_phrases(incoming)
        before = self.files()
        with patch.object(console.sqlite3, "connect", side_effect=AssertionError("history forbidden")), \
                patch.object(console, "atomic", side_effect=AssertionError("configuration write forbidden")), \
                patch.object(console.kev_switch, "command", side_effect=AssertionError("switch change forbidden")):
            report = console.native_request(self.store, {"action": "phrase_import_preview", "existing": draft,
                                                        "content": content, "format": "json"})
            self.assertEqual([row["status"] for row in report["rows"]], ["conflict", "new"])
            exported = console.native_request(self.store, {"action": "phrase_export", "phrases": draft, "format": "tsv"})
            self.assertEqual(phrase_exchange.preview(exported["content"], "tsv", [])["rows"][0]["text"], "草稿表达")
        self.assertEqual(self.files(), before)
        self.assertEqual(self.store.revision(), current["revision"])
        self.assert_switches_and_history(current["prediction"])


class MSIMENativePipeTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen([sys.executable, str(PROJECT / "kbd.py"), "console-native", "--demo"],
                                        cwd=PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(self.close)

    def close(self):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()

    def response(self, payload):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 15)
        self.assertTrue(ready, "private pipe did not answer")
        line = self.process.stdout.readline()
        self.assertTrue(line, "private pipe closed after a valid frame")
        return json.loads(line)

    def request(self, payload):
        result = self.response(payload)
        self.assertTrue(result["ok"], result)
        return result["data"]

    def test_import_and_export_use_current_draft_and_preserve_real_pipe_state(self):
        initial = self.request({"action": "state"})
        draft = initial["phrases"] + [{"code": "qdraft", "text": "未保存草稿", "category": "测试"}]
        incoming = [{"code": "qdraft", "text": "冲突表达", "category": "测试"},
                    {"code": "qnew", "text": '多行\n"原话"\t保留', "category": "测试"}]
        result = self.request({"action": "phrase_import_preview", "format": "json", "existing": draft,
                               "content": phrase_exchange.export_phrases(incoming)})
        self.assertEqual([row["status"] for row in result["rows"]], ["conflict", "new"])
        exported = self.request({"action": "phrase_export", "format": "tsv", "phrases": draft})
        self.assertEqual(phrase_exchange.preview(exported["content"], "tsv", [])["counts"]["new"], len(draft))
        current = self.request({"action": "state"})
        for key in ("revision", "settings", "phrases", "prediction", "status"):
            self.assertEqual(current[key], initial[key])
        self.assertEqual(self.request({"action": "backups"})["backups"], [])

    def test_legal_large_frame_and_oversized_file_error_keep_the_pipe_alive(self):
        initial = self.request({"action": "state"})
        base = '{"schema_version":1,"phrases":[]}'
        content = base + " " * (phrase_exchange.MAX_BYTES - 1 - len(base))
        payload = {"action": "phrase_import_preview", "format": "json", "content": content, "existing": []}
        self.assertGreater(len(json.dumps(payload).encode()), 2_000_000)
        self.assertEqual(self.request(payload)["counts"]["total"], 0)
        current = self.request({"action": "state"})
        self.assertEqual(current["revision"], initial["revision"])
        payload["content"] = "汉" * (phrase_exchange.MAX_BYTES // 3 + 1)
        result = self.response(payload)
        self.assertFalse(result["ok"])
        self.assertIn("2 MB", result["error"])
        self.assertEqual(self.request({"action": "state"})["revision"], initial["revision"])

    def test_native_settings_and_stale_revision_preserve_prediction_and_kev(self):
        self.request({"action": "prediction", "enabled": True, "max_candidates": 4})
        initial = self.request({"action": "state"})
        self.request({"action": "settings", "revision": initial["revision"],
                      "settings": dict(initial["settings"], english_completion="on", emoji_default="off",
                                       gloss_overrides=custom_gloss())})
        current = self.request({"action": "state"})
        self.assertEqual(current["settings"]["english_completion"], "on")
        self.assertEqual(current["settings"]["gloss_overrides"], custom_gloss())
        self.assertEqual(current["prediction"], initial["prediction"])
        self.assertEqual(current["status"]["kev_enabled"], initial["status"]["kev_enabled"])
        stale = self.response({"action": "settings", "revision": initial["revision"], "settings": initial["settings"]})
        self.assertFalse(stale["ok"])
        self.assertIn("修改", stale["error"])
        self.assertEqual(self.request({"action": "state"})["revision"], current["revision"])


if __name__ == "__main__":
    unittest.main()
