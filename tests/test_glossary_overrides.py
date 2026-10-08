"""Explicit synthetic edits only; no input-history or third-party term sources."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from keytrack import annotations, doctor, kev_rime_setup, prediction_setup
from tests.test_prediction import DAILY


class GlossaryOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rime = self.root / "Rime"
        self.rime.mkdir()
        self.overlay = [{"word": "模具", "en": "tooling", "ja": "金型", "reading": "かながた"},
                        {"word": "合成词", "en": "synthetic term", "ja": "合成語"}]

    def write_sources(self, overrides=None):
        for path, text in annotations.source_changes(self.rime, overrides=overrides).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def write_overlay(self, items):
        target = self.root / "console/glossary-overrides.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(items, ensure_ascii=False))
        return target

    def test_frozen_original_and_independent_work_sources(self):
        _, base = annotations.entries()
        _, work = annotations.work_entries()
        self.assertEqual(len(base), 120)
        self.assertEqual(len(work), 72)
        self.assertFalse({x["word"] for x in base} & {x["word"] for x in work})
        for filename, digest in (("glossary-v1.json", annotations.BASE_SHA256),
                                 ("work-terms-v1.json", annotations.WORK_SHA256)):
            self.assertEqual(hashlib.sha256((annotations.PROJECT / "data/annotations" / filename).read_bytes()).hexdigest(), digest)
        self.assertEqual(annotations.catalog()["count"], 192)

    def test_overlay_priority_and_new_term_are_visible_without_changing_base(self):
        before = (annotations.PROJECT / "data/annotations/glossary-v1.json").read_bytes()
        catalog = annotations.catalog(self.overlay + [{"word": "样品", "en": "test unit", "ja": "試験品"}])
        table = {x["word"]: x for x in catalog["entries"]}
        self.assertEqual(table["模具"]["en"], "tooling")
        self.assertEqual(table["样品"]["en"], "test unit")
        self.assertEqual(table["合成词"]["source"], "user")
        self.assertEqual(table["模具"]["base_source"], "work")
        self.assertEqual(table["样品"]["base_source"], "base")
        self.assertEqual(catalog["count"], 193)
        self.assertEqual((catalog["base_count"], catalog["term_count"], catalog["override_count"]), (120, 72, 3))
        self.assertEqual((annotations.PROJECT / "data/annotations/glossary-v1.json").read_bytes(), before)
        self.assertEqual(annotations.catalog()["override_count"], 0)

    def test_bundled_entries_remain_independent_of_effective_entries_and_personal_edits(self):
        catalog = annotations.catalog(self.overlay)
        bundled = {item["word"]: item for item in catalog["bundled_entries"]}
        effective = {item["word"]: item for item in catalog["entries"]}
        self.assertEqual(len(bundled), 192)
        self.assertEqual(bundled["模具"]["en"], "mold")
        self.assertEqual(effective["模具"]["en"], "tooling")
        self.assertNotIn("合成词", bundled)
        self.assertTrue(all(set(item) == {"word", "en", "ja", "reading"}
                            for item in catalog["bundled_entries"]))
        effective["模具"]["en"] = "edited effective response"
        self.assertEqual(bundled["模具"]["en"], "mold")
        bundled["模具"]["ja"] = "edited bundled response"
        self.assertEqual(effective["模具"]["ja"], "金型")
        self.assertEqual(next(x for x in annotations.catalog()["bundled_entries"] if x["word"] == "模具")["ja"], "金型")

    def test_normalization_and_lua_compilation_are_deterministic(self):
        normalized = annotations.validate_overrides(self.overlay)
        self.assertEqual([x["word"] for x in normalized], sorted(x["word"] for x in self.overlay))
        self.assertEqual(normalized[0]["reading"], "")
        self.assertEqual(annotations.render_lua(self.overlay), annotations.render_lua(list(reversed(self.overlay))))
        lua = annotations.render_lua(self.overlay)
        self.assertEqual(lua.count('["模具"]'), 1)
        self.assertIn('en = "tooling", ja = "金型（かながた）"', lua)
        self.assertNotIn("synthetic term", annotations.render_lua())

    def test_duplicate_words_and_invalid_shapes_are_rejected(self):
        for raw in (None, {}, "[]", [None], self.overlay + self.overlay[:1],
                    [{"word": "合成词", "en": "term", "ja": "語", "unknown": True}]):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                annotations.validate_overrides(raw)

    def test_unpaired_surrogates_are_rejected_before_any_console_file_access(self):
        valid = {"word": "合成词", "en": "term", "ja": "合成語", "reading": "ご"}
        for field in ("word", "en", "ja", "reading"):
            for surrogate in ("\ud800", "\udfff"):
                raw = [dict(valid, **{field: valid[field] + surrogate})]
                before = json.dumps(raw)
                with self.subTest(field=field, surrogate=ascii(surrogate)):
                    with self.assertRaises(ValueError):
                        annotations.validate_overrides(raw)
                    with patch.object(annotations, "read_managed", side_effect=AssertionError("unexpected file access")):
                        with self.assertRaises(ValueError):
                            annotations.console_changes(self.rime, "off", overrides=raw)
                    self.assertEqual(json.dumps(raw), before)
                    self.assertFalse(any(self.rime.iterdir()))

    def test_han_word_and_short_single_line_boundaries(self):
        item = {"word": "一二三四五六七八", "en": "e" * 80, "ja": "日" * 80, "reading": "あ" * 80}
        self.assertEqual(annotations.validate_overrides([item])[0], item)
        for key, value in (("word", "一二三四五六七八九"), ("word", "模具A"), ("word", "模具 "),
                           ("word", "模-具"), ("word", ""), ("en", ""), ("ja", ""),
                           ("en", "e" * 81), ("ja", "日" * 81), ("reading", "あ" * 81),
                           ("en", " first"), ("ja", "語\n次"), ("reading", "あ\tい"),
                           ("en", "a\u2028b"), ("ja", "a\u0085b"), ("reading", "a\u009bb"), ("reading", None)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                annotations.validate_overrides([dict(item, **{key: value})])

    def test_maximum_overlay_is_bounded_and_non_mutating(self):
        items = [{"word": "合" + chr(0x4e00 + index), "en": "term", "ja": "語"}
                 for index in range(301)]
        before = json.dumps(items)
        self.assertEqual(len(annotations.validate_overrides(items[:300])), 300)
        with self.assertRaises(ValueError):
            annotations.validate_overrides(items)
        self.assertEqual(json.dumps(items), before)

    def test_overlay_stays_within_existing_comment_budget(self):
        catalog = annotations.catalog([{"word": "样品", "en": "e" * 80, "ja": "日" * 80, "reading": "あ" * 80}])
        sample = next(x for x in catalog["examples"] if x["text"] == "样品")
        self.assertEqual(len(sample["en_comment"]), 24)
        self.assertEqual(len(sample["ja_comment"]), 24)
        self.assertTrue(sample["en_comment"].endswith("…"))
        mandatory = "✦ AI 建议 · 联想 · 数字/Tab" + "原" * 35
        self.assertEqual(annotations.compose(mandatory, sample["en_comment"]), mandatory)

    def test_user_text_is_quoted_as_data(self):
        overlay = [{"word": "合成词", "en": 'a"\\b', "ja": "語"}]
        lua = annotations.render_lua(overlay)
        self.assertIn('en = "a\\"\\\\b"', lua)
        with self.assertRaises(ValueError):
            annotations.render_lua([dict(overlay[0], en="a\nreturn {}")])

    def test_modified_source_or_provenance_is_rejected_even_with_a_new_manifest_hash(self):
        bundle = self.root / "bundle"
        shutil.copytree(annotations.PROJECT / "data/annotations", bundle / "data/annotations")
        with patch.object(annotations, "PROJECT", bundle):
            source = bundle / "data/annotations/work-terms-v1.json"
            manifest = bundle / "data/annotations/work-terms-v1.manifest.json"
            data, frozen = json.loads(source.read_text()), json.loads(manifest.read_text())
            data["entries"][0]["en"] = "changed"
            source.write_text(json.dumps(data, ensure_ascii=False))
            manifest.write_text(json.dumps(dict(frozen, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())))
            with self.assertRaisesRegex(ValueError, "校验"):
                annotations.work_entries()
            shutil.copyfile(self.original_project / "data/annotations/work-terms-v1.json", source)
            frozen["origin"]["used_input_history"] = True
            manifest.write_text(json.dumps(frozen))
            with self.assertRaisesRegex(ValueError, "校验"):
                annotations.work_entries()

    @property
    def original_project(self):
        return Path(__file__).resolve().parents[1]

    def test_cross_source_duplicates_are_rejected(self):
        work = annotations.work_entries()[1]
        duplicate = dict(work[0], word="样品")
        with patch.object(annotations, "work_entries", return_value=(annotations.WORK_ID, [duplicate, *work[1:]])):
            with self.assertRaisesRegex(ValueError, "重复"):
                annotations.render_lua()

    def test_previous_overlay_allows_an_explicit_second_edit_and_restore(self):
        self.write_sources(self.overlay)
        modified = [dict(x, en="changed") for x in self.overlay]
        changes = annotations.source_changes(self.rime, overrides=modified, previous_overrides=self.overlay)
        glossary = self.rime / "lua/keytrack_glossary.lua"
        self.assertEqual(changes[glossary], annotations.render_lua(modified))
        glossary.write_text(changes[glossary])
        restored = annotations.source_changes(self.rime, overrides=self.overlay, previous_overrides=modified)
        self.assertEqual(restored[glossary], annotations.render_lua(self.overlay))

    def test_missing_or_false_previous_overlay_cannot_adopt_independent_edits(self):
        self.write_sources(self.overlay)
        for previous in (None, []):
            with self.subTest(previous=previous), self.assertRaisesRegex(ValueError, "独立修改"):
                annotations.source_changes(self.rime, overrides=[], previous_overrides=previous)
        glossary = self.rime / "lua/keytrack_glossary.lua"
        glossary.write_text(annotations.render_lua(self.overlay) + "-- independently edited\n")
        with self.assertRaisesRegex(ValueError, "独立修改"):
            annotations.source_changes(self.rime, overrides=[], previous_overrides=self.overlay)

    def test_exact_previous_release_is_upgraded_and_header_lookalikes_are_preserved(self):
        original = annotations.entries()[1]
        quote = lambda value: json.dumps(value, ensure_ascii=False)
        lines = ["-- keytrack-candidate-glossary: managed keytrack-glossary-v1",
                 "-- Original MIT-licensed metadata; no input-history data.", "return {"]
        lines += [f"  [{quote(x['word'])}] = {{ en = {quote(x['en'])}, ja = {quote(x['ja'])} }},"
                  for x in sorted(original, key=lambda x: x["word"])]
        old = "\n".join([*lines, "}", ""])
        self.assertEqual(hashlib.sha256(old.encode()).hexdigest(), annotations.PREVIOUS["keytrack_glossary.lua"])
        glossary = self.rime / "lua/keytrack_glossary.lua"
        glossary.parent.mkdir()
        glossary.write_text(old)
        self.assertEqual(annotations.source_changes(self.rime)[glossary], annotations.render_lua())
        glossary.write_text(old + "-- user edit\n")
        with self.assertRaisesRegex(ValueError, "独立修改"):
            annotations.source_changes(self.rime)

    def test_invalid_overlay_is_rejected_while_off(self):
        with self.assertRaises(ValueError):
            annotations.console_changes(self.rime, "off", overrides=[{"word": "A"}])

    def test_edits_while_off_update_only_an_installed_managed_table(self):
        self.assertEqual(annotations.console_changes(self.rime, "off", overrides=self.overlay,
                                                    previous_overrides=[]), {})
        self.write_sources(self.overlay)
        comments = self.rime / "lua/keytrack_comments.lua"
        comments.write_text("-- independent customization\n")
        changed = [dict(item, en="changed") for item in self.overlay]
        plan = annotations.console_changes(self.rime, "off", overrides=changed, previous_overrides=self.overlay)
        glossary = self.rime / "lua/keytrack_glossary.lua"
        self.assertEqual(plan, {glossary: annotations.render_lua(changed)})
        glossary.write_text(plan[glossary])
        self.assertEqual(annotations.console_changes(self.rime, "off", overrides=self.overlay,
                         previous_overrides=changed)[glossary], annotations.render_lua(self.overlay))
        glossary.write_text(glossary.read_text() + "-- user modification\n")
        with self.assertRaisesRegex(ValueError, "独立修改"):
            annotations.console_changes(self.rime, "off", overrides=self.overlay, previous_overrides=changed)

    def test_disabling_without_an_overlay_edit_keeps_independent_table(self):
        self.write_sources(self.overlay)
        glossary = self.rime / "lua/keytrack_glossary.lua"
        glossary.write_text("-- user table\nreturn {}\n")
        self.assertEqual(annotations.console_changes(self.rime, "off", overrides=self.overlay,
                                                    previous_overrides=self.overlay), {})

    def test_setup_only_loader_is_bounded_and_packaged_compilation_is_public(self):
        self.assertEqual(annotations.default_overrides(self.rime), [])
        target = self.write_overlay(self.overlay)
        self.assertEqual(annotations.default_overrides(self.rime), annotations.validate_overrides(self.overlay))
        self.assertNotIn("tooling", annotations.render_lua())
        target.write_text("x" * (annotations.MAX_OVERRIDES_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "长度限制"):
            annotations.default_overrides(self.rime)
        target.unlink()
        os.mkfifo(target)
        with self.assertRaisesRegex(ValueError, "普通文件"):
            annotations.default_overrides(self.rime)

    def test_setup_loader_rejects_symlinks_and_malformed_overlay(self):
        target = self.write_overlay(self.overlay)
        target.write_text("{}")
        with self.assertRaisesRegex(ValueError, "格式"):
            annotations.default_overrides(self.rime)
        target.unlink()
        target.symlink_to(self.root / "other")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            annotations.default_overrides(self.rime)

    def test_kev_reinstall_keeps_saved_overlay_and_does_not_copy_it_into_project(self):
        self.write_overlay(self.overlay)
        squirrel = self.root / "Squirrel.app"
        squirrel.mkdir()
        (self.rime / "rime_ice.custom.yaml").write_text("patch:\n  other: true\n")
        with (patch.object(kev_rime_setup, "RIME_DIR", self.rime),
              patch.object(kev_rime_setup, "QUEUE_ROOT", self.root / "queue"),
              patch.object(kev_rime_setup.rime_setup, "SQUIRREL_APP", str(squirrel)),
              patch.object(kev_rime_setup.rime_setup, "redeploy", return_value=True)):
            self.assertTrue(kev_rime_setup.setup(False))
            first = (self.rime / "lua/keytrack_glossary.lua").read_text()
            self.assertEqual(first, annotations.render_lua(self.overlay))
            self.assertTrue(kev_rime_setup.setup(False))
            self.assertEqual((self.rime / "lua/keytrack_glossary.lua").read_text(), first)
        self.assertNotIn("tooling", (annotations.PROJECT / "rime/keytrack_glossary.lua").read_text())

    def test_prediction_reinstall_keeps_saved_overlay(self):
        self.write_overlay(self.overlay)
        (self.rime / "build").mkdir()
        (self.rime / "build/rime_ice.schema.yaml").write_text(DAILY)
        squirrel = self.root / "Squirrel.app"
        plugin = squirrel / "Contents/Frameworks/rime-plugins/librime-predict.dylib"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b"synthetic plugin")
        with patch.object(prediction_setup.rime_setup, "SQUIRREL_APP", str(squirrel)):
            self.assertTrue(prediction_setup.setup(False, self.rime, deploy=False))
            self.assertEqual((self.rime / "lua/keytrack_glossary.lua").read_text(), annotations.render_lua(self.overlay))
            self.assertTrue(prediction_setup.setup(False, self.rime, deploy=False))
            self.assertEqual((self.rime / "lua/keytrack_glossary.lua").read_text(), annotations.render_lua(self.overlay))

    def test_diagnostics_accept_exact_overlay_compilation_and_reject_drift(self):
        self.write_sources(self.overlay)
        self.write_overlay(self.overlay)
        with (patch.object(kev_rime_setup, "RIME_DIR", self.rime),
              patch.object(doctor.kev_switch, "is_enabled", return_value=False),
              patch.object(doctor.agent, "service_status", return_value={"running": True, "pid": 123}),
              patch.object(doctor.rime_setup, "installation_ready", return_value=True)):
            result = {item["name"]: item for item in doctor.checks()}
            self.assertEqual(result["keytrack_glossary.lua"]["level"], "ok")
            glossary = self.rime / "lua/keytrack_glossary.lua"
            glossary.write_text(glossary.read_text() + "-- independent edit\n")
            result = {item["name"]: item for item in doctor.checks()}
            self.assertEqual(result["keytrack_glossary.lua"]["level"], "error")
            self.write_overlay({})
            result = {item["name"]: item for item in doctor.checks()}
            self.assertEqual(result["glossary_overrides"]["level"], "error")


if __name__ == "__main__":
    unittest.main()
