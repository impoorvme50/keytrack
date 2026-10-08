"""Input-tool controls preserve synthetic Rime settings and scoped ownership."""
import copy
import tempfile
import unittest
from pathlib import Path

from keytrack import input_tools


SOURCE = '''schema:
  schema_id: synthetic
switches:
  - name: ascii_mode
    reset: 0
  - name: emoji
    reset: 1 # original Emoji default
    states: [关闭, 开启]
melt_eng:
  dictionary: melt_eng
  enable_completion: false # original English preference
cn_en:
  enable_completion: true # original mixed preference
unrelated:
  keep: true
'''

CUSTOM = '# user comment\npatch:\n  "menu/page_size": 7\nother_section:\n  keep: true\n'


class InputToolsTests(unittest.TestCase):
    def test_preserve_defaults_do_not_require_or_rewrite_components(self):
        for source in (SOURCE, "", "unsupported: [yaml]\n"):
            self.assertEqual(input_tools.snapshot_patch(source, {}, {}), (source, {}))
            self.assertEqual(input_tools.custom_patch(CUSTOM, {}, source), CUSTOM)
        for field in input_tools.FIELDS:
            self.assertEqual(input_tools.snapshot_patch(SOURCE, {field: "existing"}, {}), (SOURCE, {}))

    def test_snapshot_on_off_and_preserve_restore_original_lines_exactly(self):
        choices = {"english_completion": "on", "mixed_completion": "off", "emoji_default": "off"}
        original_choices = copy.deepcopy(choices)
        updated, originals = input_tools.snapshot_patch(SOURCE, choices, {})
        self.assertIn("melt_eng:\n  dictionary: melt_eng\n  enable_completion: true\n", updated)
        self.assertIn("cn_en:\n  enable_completion: false\n", updated)
        self.assertIn("  - name: emoji\n    reset: 0\n", updated)
        self.assertIn("unrelated:\n  keep: true\n", updated)
        stored_originals = copy.deepcopy(originals)
        opposite = {field: "off" if mode == "on" else "on" for field, mode in choices.items()}
        toggled, saved = input_tools.snapshot_patch(updated, opposite, originals)
        restored, saved = input_tools.snapshot_patch(toggled, {}, saved)
        self.assertEqual(restored, SOURCE)
        self.assertEqual(saved, stored_originals)
        self.assertEqual(originals, stored_originals)
        self.assertEqual(choices, original_choices)

    def test_missing_original_line_is_removed_when_restoring_preserve(self):
        source = SOURCE.replace("  enable_completion: false # original English preference\n", "")
        changed, originals = input_tools.snapshot_patch(source, {"english_completion": "off"}, {})
        self.assertEqual(originals["english_completion"], "")
        self.assertIn("  enable_completion: false\n", changed)
        self.assertEqual(input_tools.snapshot_patch(changed, {}, originals)[0], source)

    def test_daily_managed_block_is_idempotent_and_removable(self):
        choices = {"english_completion": "on", "mixed_completion": "off", "emoji_default": "off"}
        updated = input_tools.custom_patch(CUSTOM, choices, SOURCE)
        self.assertIn('"melt_eng/enable_completion": true', updated)
        self.assertIn('"cn_en/enable_completion": false', updated)
        self.assertIn('"switches/@1/reset": 0', updated)
        self.assertIn('  "menu/page_size": 7\n', updated)
        self.assertTrue(updated.endswith("other_section:\n  keep: true\n"))
        self.assertEqual(input_tools.custom_patch(updated, choices, SOURCE), updated)
        self.assertEqual(input_tools.custom_patch(updated, {}, SOURCE), CUSTOM)

    def test_independent_flat_nested_and_merge_patches_are_rejected(self):
        patches = ['patch:\n  "melt_eng/enable_completion": false\n',
                   'patch:\n  melt_eng:\n    enable_completion: true\n',
                   'patch:\n  melt_eng:\n    +:\n      enable_completion: false\n',
                   'patch:\n  "melt_eng/enable_completion":\n',
                   'patch:\n  melt_eng:\n    enable_completion:\n      - false\n']
        for content in patches:
            with self.subTest(content=content), self.assertRaises(ValueError):
                input_tools.custom_patch(content, {"english_completion": "on"}, SOURCE)

    def test_independent_switch_patches_are_rejected_without_touching_other_controls(self):
        for content in ('patch:\n  "switches/@1/reset": 0\n',
                        'patch:\n  switches:\n    - name: emoji\n      reset: 0\n',
                        'patch:\n  "switches/+": [{name: custom}]\n'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                input_tools.custom_patch(content, {"emoji_default": "off"}, SOURCE)
            self.assertIn('"melt_eng/enable_completion": true',
                          input_tools.custom_patch(content, {"english_completion": "on"}, SOURCE))

    def test_unsupported_sources_and_duplicate_components_are_rejected(self):
        sources = [SOURCE.replace("  enable_completion: false # original English preference", "  enable_completion: [false]"),
                   SOURCE + "melt_eng:\n  enable_completion: true\n",
                   SOURCE.replace("  enable_completion: false # original English preference\n",
                                  "  enable_completion: false\n  enable_completion: true\n")]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                input_tools.snapshot_patch(source, {"english_completion": "on"}, {})
            with self.subTest(source=source), self.assertRaises(ValueError):
                input_tools.custom_patch(CUSTOM, {"english_completion": "on"}, source)
        for source in (SOURCE.replace("  - name: emoji", "  - name: other"),
                       SOURCE.replace("    reset: 1 # original Emoji default", "    reset: true"),
                       SOURCE.replace("  - name: emoji", "  - name: emoji\n    reset: 1\n  - name: emoji")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                input_tools.custom_patch(CUSTOM, {"emoji_default": "on"}, source)

    def test_invalid_modes_and_broken_management_markers_are_rejected(self):
        for field in input_tools.FIELDS:
            for mode in (None, True, [], {}, "enable", "on\n"):
                with self.subTest(field=field, mode=mode), self.assertRaises(ValueError):
                    input_tools.custom_patch(CUSTOM, {field: mode}, SOURCE)
        for content in (input_tools.BEGIN + "\n", input_tools.END + "\n" + input_tools.BEGIN,
                        input_tools.BEGIN + "\n" + input_tools.BEGIN + "\n" + input_tools.END,
                        "patch: {}\n", "patch:\n  other: true\npatch:\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                input_tools.custom_patch(content, {"english_completion": "on"}, SOURCE)

    def test_catalog_reads_supplied_synthetic_schema_and_reports_availability(self):
        with tempfile.TemporaryDirectory() as root:
            rime = Path(root) / "Rime"
            (rime / "build").mkdir(parents=True)
            (rime / "build/rime_ice.schema.yaml").write_text(SOURCE)
            result = input_tools.catalog(rime)
            self.assertEqual(result["english_completion"], {"available": True, "active": False})
            self.assertEqual(result["mixed_completion"], {"available": True, "active": True})
            self.assertEqual(result["emoji_default"], {"available": True, "active": True})
            (rime / "build/rime_ice.schema.yaml").write_text("unrelated: true\n")
            self.assertTrue(all(value == {"available": False, "active": False}
                                for value in input_tools.catalog(rime).values()))


if __name__ == "__main__":
    unittest.main()
