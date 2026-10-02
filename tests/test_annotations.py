"""Public/synthetic candidate glosses and reversible console controls only."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keytrack import annotations, console, kev_rime_setup, prediction_setup
from tests.test_prediction import DAILY


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.rime = root / "Rime"
        self.rime.mkdir()
        (self.rime / "rime_ice.custom.yaml").write_text(kev_rime_setup.render_custom_yaml("patch:\n  other: true\n", Path("/tmp/python"), Path("/tmp/bridge")))
        self.store = console.ConsoleStore(root / "console", self.rime, str(root / "synthetic.db"), demo=True)

    def test_original_frozen_data_and_deterministic_compilation(self):
        version, items = annotations.entries()
        self.assertEqual(version, "keytrack-glossary-v1")
        self.assertEqual(len(items), 120)
        self.assertEqual(annotations.render_lua(), (annotations.PROJECT / "rime/keytrack_glossary.lua").read_text())
        examples = annotations.catalog()["examples"]
        self.assertTrue(all("EN:" in x["en_comment"] and "日:" in x["ja_comment"] for x in examples))
        self.assertTrue(all(x["original_comment"] in x["en_comment"] for x in examples))

    def test_source_sha_mismatch_is_rejected(self):
        original = annotations.PROJECT / "data/annotations/manifest.json"
        actual = json.loads(original.read_text())
        with patch.object(annotations.json, "loads", side_effect=[dict(actual, source_sha256="0" * 64), {}]):
            with self.assertRaises(ValueError):
                annotations.entries()

    def test_default_off_does_not_install_or_create_control(self):
        self.assertEqual(self.store.state()["settings"]["gloss_language"], "off")
        self.store.save_settings(console.DEFAULTS, self.store.revision())
        self.assertFalse(annotations.settings_path(self.rime).exists())
        self.assertFalse((self.rime / "lua/keytrack_comments.lua").exists())

    def test_mode_language_saves_and_restores_without_changing_other_controls(self):
        kev = self.rime.parent / "kev-enabled"
        kev.write_text("1\n")
        initial = self.store.prediction_state()
        saved = self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), self.store.revision())
        self.assertEqual(self.store.state()["settings"]["gloss_language"], "en")
        self.assertIn('"keytrack_glossary/language": "en"', (self.rime / "rime_ice.custom.yaml").read_text())
        installed = {p: p.read_bytes() for p in (self.rime / "lua").glob("*.lua")}
        self.store.save_settings(dict(console.DEFAULTS, gloss_language="ja"), self.store.revision())
        self.assertEqual(self.store.state()["settings"]["gloss_language"], "ja")
        self.assertEqual(self.store.prediction_state(), initial)
        self.assertEqual(kev.read_text(), "1\n")
        self.store.restore(saved["backup"], self.store.revision())
        self.assertEqual(self.store.state()["settings"]["gloss_language"], "off")
        self.assertEqual(installed, {p: p.read_bytes() for p in installed})
        self.assertIn('"keytrack_glossary/language": "off"', (self.rime / "rime_ice.custom.yaml").read_text())

    def test_schema_mode_and_hotkey_save_restore_are_atomic_and_scoped(self):
        schema = self.rime / "rime_ice_predict.schema.yaml"
        schema.write_text(prediction_setup.render_schema(DAILY))
        saved = self.store.save_settings(dict(console.DEFAULTS, gloss_language="en", hotkey="Control+Alt+j"), self.store.revision())
        self.assertIn('language: "en"', schema.read_text())
        self.assertIn('hotkey: "Control+Alt+j"', schema.read_text())
        daily = self.rime / "rime_ice.custom.yaml"
        self.assertIn('"kev_rime/hotkey": "Control+Alt+j"', daily.read_text())
        daily.write_text(daily.read_text() + "\nexternal_section:\n  keep: true\n")
        self.store.save_phrases([{"code":"qsample", "text":"合成常用语", "category":"测试"}], self.store.revision())
        self.assertIn('"keytrack_glossary/language": "en"', daily.read_text())
        self.store.restore(saved["backup"], self.store.revision())
        self.assertIn('language: "off"', schema.read_text())
        self.assertIn('hotkey: "Control+Shift+k"', schema.read_text())
        self.assertIn("external_section:\n  keep: true", daily.read_text())

    def test_independent_language_patch_is_preserved(self):
        path = self.rime / "rime_ice.custom.yaml"
        path.write_text(path.read_text() + '  "keytrack_glossary/language": "ja"\n')
        revision = self.store.revision()
        with self.assertRaisesRegex(ValueError, "独立设置"):
            self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), revision)
        self.assertEqual(self.store.revision(), revision)

    def test_schema_duplicate_or_invalid_modes_are_rejected(self):
        for source in ('keytrack_glossary: invalid\n', 'keytrack_glossary:\n  language: en\nkeytrack_glossary:\n  language: ja\n'):
            with self.assertRaises(ValueError):
                annotations.schema_language(source, "en")

    def test_legacy_client_preserves_existing_mode(self):
        self.store.save_settings(dict(console.DEFAULTS, gloss_language="ja"), self.store.revision())
        old = dict(console.DEFAULTS)
        del old["gloss_language"]
        self.store.save_settings(old, self.store.revision())
        self.assertEqual(self.store.state()["settings"]["gloss_language"], "ja")

    def test_legacy_backup_defaults_off_without_downgrading_scripts(self):
        identifier = self.store.backup("legacy")
        file = self.store.root / "backups" / (identifier + ".json")
        data = json.loads(file.read_text())
        data["files"] = {k: v for k, v in data["files"].items() if not k.startswith("annotations")}
        file.write_text(json.dumps(data))
        self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), self.store.revision())
        script = self.rime / "lua/kev_filter.lua"
        before = script.read_bytes()
        self.store.restore(identifier, self.store.revision())
        self.assertEqual(annotations.language(self.rime), "off")
        self.assertEqual(script.read_bytes(), before)

    def test_invalid_language_leaves_all_targets_unchanged(self):
        revision = self.store.revision()
        for value in (None, [], "english", "en\n"):
            with self.assertRaises(ValueError):
                self.store.save_settings(dict(console.DEFAULTS, gloss_language=value), revision)
            self.assertEqual(self.store.revision(), revision)

    def test_user_edited_module_or_filter_is_never_overwritten(self):
        for name in (*annotations.FILTER_FILES, *annotations.SHARED_FILES):
            with self.subTest(name=name):
                path = self.rime / "lua" / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("-- independent customization\nreturn {}\n")
                revision = self.store.revision()
                with self.assertRaisesRegex(ValueError, "独立修改"):
                    self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), revision)
                self.assertEqual(self.store.revision(), revision)
                path.unlink()

    def test_off_is_available_with_independent_scripts(self):
        self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), self.store.revision())
        script = self.rime / "lua/kev_filter.lua"
        script.write_text("-- user's later edit\n")
        self.store.save_settings(console.DEFAULTS, self.store.revision())
        self.assertEqual(annotations.language(self.rime), "off")
        self.assertEqual(script.read_text(), "-- user's later edit\n")

    def test_control_and_scripts_are_part_of_revision(self):
        self.store.save_settings(dict(console.DEFAULTS, gloss_language="en"), self.store.revision())
        old = self.store.revision()
        annotations.settings_path(self.rime).write_text("language=ja\n")
        with self.assertRaisesRegex(ValueError, "修改"):
            self.store.save_settings(console.DEFAULTS, old)
        old = self.store.revision()
        with (self.rime / "lua/keytrack_comments.lua").open("a") as stream:
            stream.write("-- later edit\n")
        self.assertNotEqual(self.store.revision(), old)

    def test_invalid_controls_fail_off_and_do_not_hang_on_fifo(self):
        path = annotations.settings_path(self.rime)
        path.parent.mkdir(parents=True)
        for text in ("en", "language=en", "language=en\nextra", "x" * 65):
            path.write_text(text)
            self.assertEqual(annotations.language(self.rime), "off")
        path.unlink()
        os.mkfifo(path)
        self.assertEqual(annotations.language(self.rime), "off")
        with self.assertRaisesRegex(ValueError, "普通文件"):
            annotations.console_changes(self.rime, "off")

    def test_symlink_ancestor_is_rejected(self):
        path = annotations.settings_path(self.rime)
        other = self.rime.parent / "other"
        other.mkdir()
        path.parent.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            annotations.console_changes(self.rime, "en")
        self.assertFalse((other / "control").exists())

    def test_long_gloss_drops_before_existing_markers(self):
        original = "原注释 ✦ AI 建议 联想 · 数字/Tab"
        self.assertTrue(annotations.compose(original, "EN: hello").startswith(original))
        self.assertEqual(annotations.compose("原" * 60, "EN: hello"), "原" * 60)
        self.assertEqual(annotations.compose("", "日: " + "日" * 40), "日: " + "日" * 20 + "…")


if __name__ == "__main__":
    unittest.main()
