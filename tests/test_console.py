"""Companion console writes only managed settings; reports are read-only."""
import hashlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from keytrack import console, kev_rime_setup, prediction_setup, storage


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.rime = root / "Rime"
        self.rime.mkdir()
        custom = kev_rime_setup.render_custom_yaml("patch:\n  other: true\n", Path("/tmp/python"), Path("/tmp/bridge"))
        (self.rime / "rime_ice.custom.yaml").write_text(custom)
        (self.rime / "squirrel.custom.yaml").write_text("# original\npatch:\n  unrelated: true\n")
        self.store = console.ConsoleStore(root / "console", self.rime, str(root / "test.db"), demo=True)

    def test_patch_keeps_other_sections_and_is_idempotent(self):
        original = "# user\npatch:\n  other: 7\nother_section:\n  value: true\n"
        entries = console.scalar("style/font_point", 18)
        updated = console.managed(original, entries)
        self.assertIn("  other: 7", updated)
        self.assertLess(updated.index(console.END), updated.index("other_section:"))
        self.assertEqual(console.managed(updated, entries), updated)
        self.assertEqual(console.managed(updated, None), original)

    def test_conflicting_user_patch_is_not_overwritten(self):
        for original in ('patch:\n  "style/font_point": 19\n', 'patch:\n  style/font_point: 19\n'):
            with self.assertRaisesRegex(ValueError, "已有设置占用"):
                console.managed(original, console.scalar("style/font_point", 18))

    def test_save_backups_and_stale_revision(self):
        original = (self.rime / "squirrel.custom.yaml").read_text()
        settings = dict(console.DEFAULTS, theme="blue", font_size=20, hotkey="Control+Alt+j")
        revision = self.store.revision()
        result = self.store.save_settings(settings, revision)
        self.assertTrue(result["saved"])
        self.assertIn('"style/font_point": 20', (self.rime / "squirrel.custom.yaml").read_text())
        self.assertIn('"kev_rime/hotkey": "Control+Alt+j"', (self.rime / "rime_ice.custom.yaml").read_text())
        reinstall = kev_rime_setup.render_custom_yaml((self.rime / "rime_ice.custom.yaml").read_text(), Path("/tmp/python"), Path("/tmp/bridge"))
        self.assertIn('"kev_rime/hotkey": "Control+Alt+j"', reinstall)
        backup = self.store.root / "backups" / (result["backup"] + ".json")
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(backup.read_text())["files"]["squirrel.custom.yaml"], original)
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            self.store.save_settings(settings, revision)

    def test_restore_preserves_unrelated_newer_edits(self):
        result = self.store.save_settings(dict(console.DEFAULTS, theme="green"), self.store.revision())
        custom = self.rime / "squirrel.custom.yaml"
        custom.write_text(custom.read_text() + "# later external edit\n")
        self.store.restore(result["backup"], self.store.revision())
        self.assertNotIn(console.BEGIN, custom.read_text())
        self.assertIn("# later external edit", custom.read_text())
        self.assertEqual(len(self.store.backups()), 2)

    def test_phrase_file_is_separate_and_multiline_supported(self):
        original = (self.rime / "rime_ice.custom.yaml").read_text()
        items = [{"code": "qreply", "text": 'First line\nSecond "line"', "category": "回复"}]
        result = self.store.save_phrases(items, self.store.revision())
        self.assertTrue(result["saved"])
        self.assertIn(original, (self.rime / "rime_ice.custom.yaml").read_text())
        self.assertIn("keytrack_phrases", (self.rime / "rime_ice.custom.yaml").read_text())
        generated = self.store.targets["keytrack_phrases_data.lua"].read_text()
        self.assertIn('First line\\nSecond \\"line\\"', generated)
        self.assertFalse((self.rime / "custom_phrase.txt").exists())

    def test_original_palette_can_be_selected_and_restored(self):
        custom = self.rime / "squirrel.custom.yaml"
        custom.write_text('patch:\n  "style/color_scheme": wechat\n  "style/color_scheme_dark": wechat_dark\n  other: true\n')
        saved = self.store.save_settings(dict(console.DEFAULTS, theme="blue"), self.store.revision())
        self.assertIn('"style/color_scheme": "keytrack_light"', custom.read_text())
        self.assertEqual(self.store.state()["settings"]["_original_schemes"]["style/color_scheme"], "wechat")
        self.store.save_settings(console.DEFAULTS, self.store.revision())
        self.assertIn('"style/color_scheme": "wechat"', custom.read_text())
        self.store.restore(saved["backup"], self.store.revision())
        self.assertIn('"style/color_scheme": "wechat"', custom.read_text())
        self.assertIn('  other: true', custom.read_text())

    def test_existing_theme_colors_remain_compatible(self):
        accents = {"green": ("#0f766e", "#14b8a6"), "blue": ("#2563eb", "#60a5fa"),
                   "slate": ("#475569", "#94a3b8")}
        light = {"back_color": "#f9fbfa", "text_color": "#334155", "candidate_text_color": "#172d2b",
                 "comment_text_color": "#667b7b", "label_color": "#728785",
                 "hilited_candidate_text_color": "#ffffff", "hilited_comment_text_color": "#ffffff",
                 "hilited_label_color": "#ffffff", "border_color": "#dce8e5"}
        dark = {"back_color": "#19232b", "text_color": "#dce6e5", "candidate_text_color": "#f1f5f9",
                "comment_text_color": "#a5b5b8", "label_color": "#9badb3",
                "hilited_candidate_text_color": "#102a2a", "hilited_comment_text_color": "#102a2a",
                "hilited_label_color": "#102a2a", "border_color": "#334348"}
        themes = {theme["id"]: theme for theme in self.store.state()["appearance_themes"]}
        for identifier, (light_accent, dark_accent) in accents.items():
            self.assertEqual(themes[identifier]["light"], dict(light, hilited_candidate_back_color=light_accent))
            self.assertEqual(themes[identifier]["dark"], dict(dark, hilited_candidate_back_color=dark_accent))

    def test_catalog_and_generated_palettes_use_identical_colors(self):
        themes = console.native_request(self.store, {"action": "state"})["appearance_themes"]
        self.assertEqual([theme["id"] for theme in themes],
                         ["green", "blue", "slate", "forest", "mint", "mist", "navy", "sand", "paper"])
        for theme in themes:
            settings = console.validate_settings(dict(console.DEFAULTS, theme=theme["id"]))
            generated = console.appearance_patch(settings)
            self.assertEqual(generated.count('"preset_color_schemes/'), 2)
            for mode in ("light", "dark"):
                raw = re.search(r'^  "preset_color_schemes/keytrack_' + mode + r'": (.*)$', generated, re.M)[1]
                native = json.loads(re.sub(r'(0x[0-9a-f]+)', r'"\1"', raw))
                actual_rgb = {field: "#" + value[6:8] + value[4:6] + value[2:4]
                              for field, value in native.items() if field.endswith("_color")}
                self.assertEqual(actual_rgb, theme[mode])
        # UI clients receive copies, so changing a preview cannot change future Rime output.
        themes[0]["light"]["back_color"] = "#000000"
        self.assertEqual(self.store.state()["appearance_themes"][0]["light"]["back_color"], "#f9fbfa")

    def test_new_theme_text_has_readable_contrast_in_both_modes(self):
        def luminance(rgb):
            channels = [int(rgb[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [ch / 12.92 if ch <= .04045 else ((ch + .055) / 1.055) ** 2.4 for ch in channels]
            return sum(ch * weight for ch, weight in zip(linear, (.2126, .7152, .0722)))

        def contrast(foreground, background):
            high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
            return (high + .05) / (low + .05)

        for theme in self.store.state()["appearance_themes"][3:]:
            for mode in ("light", "dark"):
                palette = theme[mode]
                for field in ("text_color", "candidate_text_color", "comment_text_color", "label_color"):
                    with self.subTest(theme=theme["id"], mode=mode, field=field):
                        self.assertGreaterEqual(contrast(palette[field], palette["back_color"]), 4.5)
                for field in ("hilited_candidate_text_color", "hilited_comment_text_color", "hilited_label_color"):
                    with self.subTest(theme=theme["id"], mode=mode, field=field):
                        self.assertGreaterEqual(contrast(palette[field], palette["hilited_candidate_back_color"]), 4.5)

    def test_unknown_theme_is_rejected_before_any_write(self):
        revision = self.store.revision()
        for identifier in ("pink", "forest-dark", "", None, ["mint"]):
            with self.assertRaisesRegex(ValueError, "外观选项"):
                self.store.save_settings(dict(console.DEFAULTS, theme=identifier), revision)
        self.assertEqual(self.store.revision(), revision)
        self.assertEqual(self.store.backups(), [])

    def test_font_and_preedit_start_in_preserve_mode_and_read_nested_theme(self):
        custom = self.store.targets["squirrel.custom.yaml"]
        original = '''patch:
  style:
    font_face: "Original Font"
    inline_preedit: false
    color_scheme: original
  "preset_color_schemes/+":
    original:
      font_face: "Theme Font"
      inline_preedit: true
  unrelated: true
'''
        custom.write_text(original)
        state = self.store.state()
        self.assertEqual(state["settings"]["font_mode"], "existing")
        self.assertEqual(state["settings"]["preedit_mode"], "existing")
        self.assertEqual(state["appearance_baseline"]["style"], {"font_face": "Original Font", "inline_preedit": False})
        self.assertEqual(state["appearance_baseline"]["light"], {"font_face": "Theme Font", "inline_preedit": True})
        self.store.save_settings(state["settings"], state["revision"])
        self.assertTrue(custom.read_text().startswith(original))
        block = custom.read_text().split(console.BEGIN)[1]
        self.assertNotIn('/font_face"', block)
        self.assertNotIn('/inline_preedit"', block)

    def test_selected_font_and_preedit_override_style_and_both_new_themes(self):
        settings = dict(console.DEFAULTS, theme="mint", font_mode="custom", font_face="PingFangSC-Regular", preedit_mode="candidate")
        self.store.save_settings(settings, self.store.revision())
        actual = console.yaml_paths(self.store.targets["squirrel.custom.yaml"].read_text())
        for prefix in ("style", "preset_color_schemes/keytrack_light", "preset_color_schemes/keytrack_dark"):
            for field in ("font_face", "comment_font_face", "label_font_face"):
                self.assertEqual(actual[f"{prefix}/{field}"], "PingFangSC-Regular")
            self.assertIs(actual[f"{prefix}/inline_preedit"], False)

    def test_original_theme_overrides_are_independent_and_restore_nested_values(self):
        custom = self.store.targets["squirrel.custom.yaml"]
        original = '''patch:
  'style/color_scheme': original
  'style/color_scheme_dark': original_dark
  "preset_color_schemes/+":
    original:
      font_face: "Theme Font"
      label_font_face: "Number Font"
      inline_preedit: true
    original_dark:
      font_face: "Dark Font"
      inline_preedit: false
'''
        custom.write_text(original)
        saved = self.store.save_settings(dict(console.DEFAULTS, font_mode="system", preedit_mode="inline"), self.store.revision())
        actual = console.yaml_paths(custom.read_text())
        self.assertEqual(actual["preset_color_schemes/original/font_face"], "")
        self.assertEqual(actual["preset_color_schemes/original_dark/label_font_face"], "")
        self.assertTrue(actual["preset_color_schemes/original_dark/inline_preedit"])
        self.store.save_settings(console.DEFAULTS, self.store.revision())
        actual = console.yaml_paths(custom.read_text())
        self.assertEqual(actual["preset_color_schemes/original/font_face"], "Theme Font")
        self.assertEqual(actual["preset_color_schemes/original/label_font_face"], "Number Font")
        self.assertFalse(actual["preset_color_schemes/original_dark/inline_preedit"])
        custom.write_text(custom.read_text() + "# later unrelated edit\n")
        self.store.restore(saved["backup"], self.store.revision())
        self.assertIn("# later unrelated edit", custom.read_text())
        self.assertEqual(console.yaml_paths(custom.read_text())["preset_color_schemes/original_dark/font_face"], "Dark Font")

    def test_direct_font_and_preedit_originals_keep_comments_and_restore(self):
        custom = self.store.targets["squirrel.custom.yaml"]
        original = '''patch:
  "style/font_face": "Original Font" # keep font note
  style/label_font_face: 'Original Number'
  'style/comment_font_face': 'Comment # Font'
  "style/inline_preedit": false # keep pinyin note
  unrelated: true
'''
        custom.write_text(original)
        saved = self.store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face="Missing Font,Helvetica", preedit_mode="inline"), self.store.revision())
        self.store.save_settings(console.DEFAULTS, self.store.revision())
        self.assertIn('"Original Font" # keep font note', custom.read_text())
        self.assertIn('false # keep pinyin note', custom.read_text())
        self.assertEqual(console.yaml_paths(custom.read_text())["style/comment_font_face"], "Comment # Font")
        custom.write_text(custom.read_text() + "# external edit\n")
        self.store.restore(saved["backup"], self.store.revision())
        actual = console.yaml_paths(custom.read_text())
        self.assertEqual(actual["style/font_face"], "Original Font")
        self.assertIs(actual["style/inline_preedit"], False)
        self.assertIn("# external edit", custom.read_text())

    def test_old_settings_and_old_clients_keep_new_appearance_choices(self):
        self.store.targets["settings.json"].parent.mkdir(parents=True)
        old = {key: value for key, value in console.DEFAULTS.items() if key not in ("font_mode", "font_face", "preedit_mode")}
        self.store.targets["settings.json"].write_text(json.dumps(dict(old, theme="navy", font_size=20)))
        settings = self.store.state()["settings"]
        self.assertEqual(settings["theme"], "navy")
        self.assertEqual(settings["font_size"], 20)
        self.assertEqual(settings["font_mode"], "existing")
        self.store.save_settings(dict(settings, font_mode="custom", font_face="Helvetica", preedit_mode="candidate"), self.store.revision())
        self.store.save_settings(dict(old, theme="navy", font_size=21), self.store.revision())
        actual = self.store.state()["settings"]
        self.assertEqual((actual["font_mode"], actual["font_face"], actual["preedit_mode"]), ("custom", "Helvetica", "candidate"))

    def test_invalid_font_and_preedit_rejected_without_writes(self):
        revision = self.store.revision()
        invalid = [{"font_mode": value} for value in (None, [], "other")]
        invalid += [{"preedit_mode": value} for value in (True, [], "window")]
        invalid += [{"font_mode": "custom", "font_face": value} for value in (None, [], "", " ", "x\npatch:", "x\x7f", "x" * 161, "x,", ",x", " x")]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.save_settings(dict(console.DEFAULTS, **changes), revision)
        self.assertEqual(self.store.revision(), revision)
        self.assertEqual(self.store.backups(), [])

    def test_font_text_is_a_quoted_scalar_and_missing_fonts_remain_allowed(self):
        face = 'Missing "Font",Helvetica # fallback'
        self.store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face=face), self.store.revision())
        custom = self.store.targets["squirrel.custom.yaml"].read_text()
        self.assertEqual(console.yaml_paths(custom)["style/font_face"], face)
        self.assertEqual(self.store.state()["settings"]["font_face"], face)

    def test_font_save_stale_revision_and_new_external_override_are_rejected(self):
        self.store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face="Helvetica"), self.store.revision())
        revision = self.store.revision()
        custom = self.store.targets["squirrel.custom.yaml"]
        custom.write_text(custom.read_text() + '  "style/font_face": "New External Font"\n')
        before = custom.read_text()
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            self.store.save_settings(self.store.state()["settings"], revision)
        with self.assertRaisesRegex(ValueError, "已有设置占用"):
            self.store.save_settings(self.store.state()["settings"], self.store.revision())
        self.assertEqual(custom.read_text(), before)

    def test_opaque_original_font_scalar_refused_without_writes(self):
        custom = self.store.targets["squirrel.custom.yaml"]
        for raw in ('[Helvetica, Avenir]', '*user_font', '!!str Helvetica', '|'):
            custom.write_text(f'patch:\n  "style/font_face": {raw}\n')
            before = self.store.revision()
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "不是支持的标量"):
                self.store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face="Helvetica"), before)
            self.assertEqual(self.store.revision(), before)

    def test_opaque_original_style_refused_instead_of_missing_theme_priority(self):
        custom = self.store.targets["squirrel.custom.yaml"]
        for line in ('style: {color_scheme: custom_theme, font_face: Avenir}',
                     'style: *shared_style', '"style/color_scheme": *shared_scheme'):
            custom.write_text(f'patch:\n  {line}\n')
            before = self.store.revision()
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "无法确认字体覆盖范围"):
                self.store.save_settings(dict(console.DEFAULTS, font_mode="custom", font_face="Helvetica"), before)
            self.assertEqual(self.store.revision(), before)

    def test_new_palette_backup_restore_keeps_phrases_prediction_and_external_edits(self):
        phrases = [{"code": "qexample", "text": "已有常用语", "category": "回复"}]
        self.store.save_phrases(phrases, self.store.revision())
        self.store.save_prediction({"enabled": True, "max_candidates": 4})
        self.store.save_settings(dict(console.DEFAULTS, theme="forest"), self.store.revision())
        before = self.store.targets["squirrel.custom.yaml"].read_text()
        saved = self.store.save_settings(dict(console.DEFAULTS, theme="sand"), self.store.revision())
        custom = self.store.targets["squirrel.custom.yaml"]
        custom.write_text(custom.read_text() + "# later external theme note\n")
        self.store.restore(saved["backup"], self.store.revision())
        self.assertEqual(custom.read_text(), before + "# later external theme note\n")
        restored = self.store.state()
        self.assertEqual(restored["settings"]["theme"], "forest")
        self.assertEqual(restored["phrases"], phrases)
        self.assertTrue(restored["prediction"]["enabled"])
        self.assertEqual(restored["prediction"]["max_candidates"], 4)

    def test_duplicate_or_unsafe_phrase_codes_rejected(self):
        for items in ([{"code":"vabc","text":"x"}], [{"code":"qreply","text":"x"},{"code":"qreply","text":"y"}], [{"code":"qreply","text":"x\x00"}]):
            with self.assertRaises(ValueError):
                console.validate_phrases(items)

    def test_transaction_failure_restores_written_files(self):
        target1, target2 = self.store.targets["settings.json"], self.store.targets["phrases.json"]
        target1.parent.mkdir(parents=True)
        target1.write_text("null")
        target2.write_text("[]")
        original = console.atomic
        def fail(path, text):
            if path == target2 and text == "new":
                raise OSError("write failed")
            return original(path, text)
        with patch.object(console, "atomic", side_effect=fail):
            with self.assertRaises(OSError):
                self.store.commit({target1:"new",target2:"new"}, "test", self.store.revision())
        self.assertEqual(target1.read_text(), "null")
        self.assertEqual(target2.read_text(), "[]")

    def test_report_does_not_return_text_unless_requested_or_write_database(self):
        today = datetime.now(console.ZONE).date()
        start = datetime.combine(today, datetime.min.time(), console.ZONE).timestamp()
        with storage.connect(self.store.db) as conn:
            storage.insert_segment(conn, "Example", None, start + 3600, start + 3601, "private sample", 14)
            storage.bump_key_counts(conn, today.isoformat(), {"a": 10, "BackSpace": 2})
            storage.bump_key_minutes(conn, {today.isoformat()+"T01:00":12})
            conn.execute("INSERT INTO key_capture_minutes VALUES (?,?)", (today.isoformat()+"T01:00",12))
        path = Path(self.store.db)
        before = hashlib.sha256(path.read_bytes()).digest()
        report = self.store.report(today.isoformat())
        self.assertEqual(report["total_chars"],14)
        self.assertEqual(report["cpm"],14)
        self.assertIsNone(report["segments"])
        self.assertNotIn("private sample", json.dumps(report))
        self.assertEqual(self.store.report(today.isoformat(),True)["segments"][0]["text"],"private sample")
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).digest())

    def test_missing_database_is_not_created(self):
        self.assertEqual(self.store.report("2026-10-02")["total_chars"],0)
        self.assertFalse(Path(self.store.db).exists())

    def test_application_rules_are_validated(self):
        valid = dict(console.DEFAULTS, apps=[{"bundle":"com.apple.Terminal","english":True}])
        self.assertIn("com.apple.Terminal",console.appearance_patch(console.validate_settings(valid)))
        for value in ("../../bad", "com.apple/Terminal"):
            with self.assertRaises(ValueError):
                console.validate_settings(dict(console.DEFAULTS,apps=[{"bundle":value,"english":True}]))

    def test_native_bridge_reuses_safe_store_without_history_text(self):
        state = console.native_request(self.store, {"action": "state"})
        self.assertTrue(state["status"]["demo"])
        report = console.native_request(self.store, {"action": "report", "day": "2026-10-02"})
        self.assertIsNone(report["segments"])
        items = [{"code": "qnative", "category": "测试", "text": "第一行\n第二行"}]
        outcome = console.native_request(self.store, {"action": "phrases", "phrases": items, "revision": state["revision"]})
        self.assertTrue(outcome["saved"])
        self.assertEqual(console.native_request(self.store, {"action": "state"})["phrases"], items)
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            console.native_request(self.store, {"action": "phrases", "phrases": [], "revision": state["revision"]})

    def test_native_bridge_rejects_unknown_actions_and_bad_switches(self):
        for payload in ({"action": "unknown"}, {"action": "kev", "enabled": "on"},
                        {"action": "prediction", "enabled": "on"},
                        {"action": "prediction", "enabled": True, "max_candidates": True},
                        {"action": "prediction", "enabled": True, "max_iterations": 2}, [], None):
            with self.assertRaises(ValueError):
                console.native_request(self.store, payload)

    def test_demo_prediction_controls_are_independent_of_kev(self):
        initial = console.native_request(self.store, {"action": "state"})
        self.assertEqual(initial["prediction"]["max_candidates"], 3)
        self.assertEqual(initial["prediction"]["max_iterations"], 1)
        self.assertFalse(initial["prediction"]["enabled"])
        with patch.object(console.kev_switch, "command") as kev, patch.object(prediction_setup, "set_settings") as prediction:
            console.native_request(self.store, {"action": "prediction", "enabled": True, "max_candidates": 4})
            current = console.native_request(self.store, {"action": "state"})
            kev.assert_not_called()
            prediction.assert_not_called()
        self.assertTrue(current["prediction"]["enabled"])
        self.assertEqual(current["prediction"]["max_candidates"], 4)
        self.assertFalse(current["status"]["kev_enabled"])
        console.native_request(self.store, {"action": "prediction", "enabled": False, "max_candidates": 4})
        self.assertFalse(self.store.state()["prediction"]["enabled"])

    def test_live_prediction_dispatch_uses_store_rime_and_does_not_touch_kev(self):
        self.store.demo = False
        with patch.object(prediction_setup, "set_settings", return_value={"message": "saved"}) as prediction, patch.object(console.kev_switch, "command") as kev:
            result = console.native_request(self.store, {"action": "prediction", "enabled": True, "max_candidates": 3})
        self.assertEqual(result["message"], "saved")
        prediction.assert_called_once_with(enabled=True, max_candidates=3, max_iterations=1, rime_dir=self.rime)
        kev.assert_not_called()

    def test_prediction_is_in_revision_and_backup_restore_without_kev_changes(self):
        revision = self.store.revision()
        backup = self.store.backup("prediction baseline")
        self.store.save_prediction({"enabled": True, "max_candidates": 5})
        self.assertNotEqual(revision, self.store.revision())
        with self.assertRaisesRegex(ValueError, "其他窗口"):
            self.store.save_phrases([], revision)
        with patch.object(console.kev_switch, "command") as kev:
            self.store.restore(backup, self.store.revision())
            kev.assert_not_called()
        current = self.store.state()["prediction"]
        self.assertFalse(current["enabled"])
        self.assertEqual(current["max_candidates"], 3)
        restored_snapshot = json.loads((self.store.root / "backups" / (self.store.backups()[0]["id"] + ".json")).read_text())
        self.assertTrue(restored_snapshot["prediction"]["enabled"])

    def test_hotkey_and_first_phrase_propagate_to_experiment_and_restore_scoped(self):
        source = self.rime / f"{prediction_setup.SCHEMA}.schema.yaml"
        source.write_text(prediction_setup.HEADER + '\nengine:\n  translators:\n    - table_translator\nkev_rime:\n  hotkey: "Control+Shift+k"\n')
        saved = self.store.save_settings(dict(console.DEFAULTS, hotkey="Control+Alt+j"), self.store.revision())
        self.assertIn('hotkey: "Control+Alt+j"', source.read_text())
        self.store.save_phrases([{"code": "qexperiment", "text": "实验短语"}], self.store.revision())
        self.assertIn("lua_translator@*keytrack_phrases", source.read_text())
        source.write_text(source.read_text() + "# later experiment comment\n")
        self.store.restore(saved["backup"], self.store.revision())
        self.assertIn('hotkey: "Control+Shift+k"', source.read_text())
        self.assertIn("# later experiment comment", source.read_text())
        self.assertTrue(list((self.rime.parent / "prediction-state/backups").glob("*-console/*.schema.yaml")))


class ProtocolTests(unittest.TestCase):
    def handler(self, token="secret", origin="http://127.0.0.1:10001", body=None):
        handler = object.__new__(console.ConsoleHandler)
        handler.server = SimpleNamespace(server_port=10001,token="secret",store=Mock())
        handler.headers = {"Host":"127.0.0.1:10001","X-Keytrack-Token":token,"Origin":origin,"Content-Type":"application/json"}
        payload = json.dumps(body or {}).encode()
        handler.headers["Content-Length"] = str(len(payload))
        handler.rfile = io.BytesIO(payload)
        handler.reply = Mock()
        handler.path="/api/settings"
        return handler

    def test_cross_origin_or_missing_token_cannot_write(self):
        for token,origin in (("","http://127.0.0.1:10001"),("secret","https://example.com")):
            handler=self.handler(token,origin)
            handler.do_POST()
            self.assertEqual(handler.reply.call_args.args[0],403)
            handler.server.store.save_settings.assert_not_called()

    def test_foreign_host_cannot_access_static_or_data(self):
        handler=self.handler()
        handler.headers["Host"]="attacker.example"
        handler.path="/api/state"
        handler.do_GET()
        self.assertEqual(handler.reply.call_args.args[0],403)

    def test_data_requires_token(self):
        handler=self.handler(token="")
        handler.path="/api/state"
        handler.do_GET()
        self.assertEqual(handler.reply.call_args.args[0],403)


if __name__ == "__main__":
    unittest.main()
