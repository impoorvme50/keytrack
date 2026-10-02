"""Local prediction installation/control safety; synthetic data and no live Rime."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import tempfile
import hashlib
import unittest
from unittest.mock import patch

from keytrack import annotations, prediction_setup as prediction


DAILY = '''__build_info:
  timestamp: 0
schema:
  schema_id: rime_ice
  name: 用户雾凇
  version: "1"
switches:
  - name: ascii_mode
    reset: 0
    states: [中文, 英文]
engine:
  processors:
    - lua_processor@*keytrack_logger
    - lua_processor@*kev_hotkey
    - ascii_composer
    - speller
    - key_binder
    - express_editor
  translators:
    - script_translator
    - lua_translator@*keytrack_phrases
  filters:
    - lua_filter@*kev_filter
translator:
  dictionary: rime_ice
  enable_user_dict: true
speller:
  alphabet: "abcdefghijklmnopqrstuvwxyz;"
  algebra:
    - derive/eng$/en/
key_binder:
  bindings:
    - {when: composing, accept: Control+p, send: Up}
kev_rime:
  hotkey: Control+Shift+k
'''


class PredictionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rime = self.root / "Rime"
        (self.rime / "build").mkdir(parents=True)
        (self.rime / "build/rime_ice.schema.yaml").write_text(DAILY)
        self.default = '# user\npatch:\n  "schema_list":\n    - schema: rime_ice\n  "menu/page_size": 7\nother:\n  keep: true\n'
        (self.rime / "default.custom.yaml").write_text(self.default)
        (self.rime / "rime_ice.custom.yaml").write_text('patch:\n  "speller/alphabet": abcxyz\n')
        (self.rime / "squirrel.custom.yaml").write_text('patch:\n  "style/font_point": 19\n')
        (self.root / "history.db").write_bytes(b"synthetic history retained")
        self.bundle = self.root / "bundle"
        (self.bundle / "rime").mkdir(parents=True)
        (self.bundle / "data/prediction").mkdir(parents=True)
        for name in prediction.LUA_FILES:
            (self.bundle / "rime" / name).write_bytes((prediction.PROJECT / "rime" / name).read_bytes())
        self.db_bytes = b"Rime::Predict/1.0" + bytes(100)
        (self.bundle / "data/prediction/keytrack-predict.db").write_bytes(self.db_bytes)
        squirrel = self.root / "Squirrel.app"
        plugin = squirrel / "Contents/Frameworks/rime-plugins/librime-predict.dylib"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b"synthetic plugin path")
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(prediction, "PROJECT", self.bundle))
        stack.enter_context(patch.object(prediction.rime_setup, "SQUIRREL_APP", str(squirrel)))

    def install(self) -> None:
        self.assertTrue(prediction.setup(False, self.rime, deploy=False))

    def deploy_fixture(self) -> None:
        source = self.rime / f"{prediction.SCHEMA}.schema.yaml"
        (self.rime / "build" / source.name).write_bytes(source.read_bytes())

    def before(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.rime.rglob("*") if path.is_file()}

    def test_clone_retains_rules_and_orders_consumers_after_collectors(self) -> None:
        result = prediction.render_schema(DAILY)
        self.assertEqual(prediction.yaml_list(result, "engine", "processors")[:4], [
            prediction.LOGGER, prediction.KEV, prediction.GUARD, "predictor",
        ])
        processors = prediction.yaml_list(result, "engine", "processors")
        self.assertLess(processors.index("predictor"), processors.index("key_binder"))
        self.assertIn("  dictionary: rime_ice\n", result)
        self.assertIn("  enable_user_dict: true\n", result)
        self.assertIn('  alphabet: "abcdefghijklmnopqrstuvwxyz;"\n', result)
        self.assertIn("    - derive/eng$/en/\n", result)
        self.assertIn("    - {when: composing, accept: Control+p, send: Up}\n", result)
        self.assertIn("lua_translator@*keytrack_phrases", result)
        self.assertIn("lua_filter@*kev_filter", result)
        self.assertNotIn("__build_info:", result)
        self.assertIn("  max_iterations: 1\n", result)

    def test_clone_rejects_occupied_processor_and_predictor_configs(self) -> None:
        bad_sources = [
            DAILY.replace(prediction.LOGGER, "lua_processor@*other"),
            DAILY.replace(prediction.KEV, "lua_processor@*other"),
            DAILY.replace("    - ascii_composer\n", "    - predictor\n"),
            DAILY + "predictor:\n  db: another.db\n",
            DAILY.replace("  - name: ascii_mode", "  - name: prediction"),
            DAILY.replace("    - script_translator", "    - predict_translator"),
            DAILY.replace("    - key_binder\n", ""),
        ]
        for source in bad_sources:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    prediction.render_schema(source)

    def test_clone_accepts_compiler_output_without_final_newline(self) -> None:
        start = DAILY.index("engine:\n")
        stop = DAILY.index("translator:\n", start)
        engine = DAILY[start:stop]
        # Make the engine's final filter-list entry the final byte of the file.
        without_newline = (DAILY[:start] + DAILY[stop:] + engine).rstrip("\n")
        self.assertEqual(prediction.render_schema(without_newline),
                         prediction.render_schema(without_newline + "\n"))
        result = prediction.render_schema(without_newline)
        self.assertEqual(prediction.yaml_list(result, "engine", "filters"),
                         ["lua_filter@*kev_filter", prediction.FILTER])

    def test_clone_updates_schema_identity_without_renaming_other_sections(self) -> None:
        user = "application:\n  name: must-keep\n  schema_id: app-metadata\n"
        result = prediction.render_schema(user + DAILY)
        self.assertIn(user, result)
        self.assertIn('schema:\n  schema_id: "rime_ice_predict"\n  name: "雾凇拼音 · 接词实验"\n', result)

    def test_default_registration_keeps_final_patch_value_on_its_own_line(self) -> None:
        for original in ("patch:\n  keep: true", "patch:"):
            with self.subTest(original=original):
                result = prediction._managed_default(original)
                self.assertTrue(result.startswith(original + "\n" + prediction.BEGIN + "\n"))
                self.assertEqual(prediction._managed_default(result), result)

    def test_install_backups_default_and_keeps_original_user_files(self) -> None:
        originals = self.before()
        self.install()
        self.assertEqual((self.rime / "build/rime_ice.schema.yaml").read_bytes(), originals[self.rime / "build/rime_ice.schema.yaml"])
        for name in ("rime_ice.custom.yaml", "squirrel.custom.yaml"):
            self.assertEqual((self.rime / name).read_bytes(), originals[self.rime / name])
        self.assertEqual((self.root / "history.db").read_bytes(), b"synthetic history retained")
        content = (self.rime / "default.custom.yaml").read_text()
        self.assertIn("    - schema: rime_ice\n", content)
        self.assertIn("other:\n  keep: true\n", content)
        backups = list((prediction.state_root(self.rime) / "backups").glob("*/default.custom.yaml"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.default)
        self.assertFalse(prediction.state(self.rime)["enabled"])
        self.assertEqual(prediction.state(self.rime)["max_candidates"], 3)
        self.assertEqual(prediction.settings_path(self.rime).stat().st_mode & 0o777, 0o600)

    def test_reinstall_is_idempotent_and_preserves_switch(self) -> None:
        self.install()
        self.deploy_fixture()
        prediction.set_settings(True, 3, rime_dir=self.rime)
        contents = self.before()
        backups = sorted((prediction.state_root(self.rime) / "backups").rglob("*"))
        self.install()
        self.assertEqual(self.before(), contents)
        self.assertEqual(sorted((prediction.state_root(self.rime) / "backups").rglob("*")), backups)
        self.assertTrue(prediction.state(self.rime)["enabled"])
        self.assertEqual(prediction.state(self.rime)["max_candidates"], 3)

    def test_reinstall_refuses_independent_edit_inside_managed_filter(self) -> None:
        self.install()
        path = self.rime / "lua/prediction_filter.lua"
        path.write_text(path.read_text() + "\n-- independent user change\n")
        before = self.before()
        self.assertFalse(prediction.setup(False, self.rime, deploy=False))
        self.assertEqual(self.before(), before)

    def test_known_previous_filter_remains_usable_with_glosses_off_only(self) -> None:
        self.install()
        self.deploy_fixture()
        target = self.rime / "lua/prediction_filter.lua"
        previous = b"-- synthetic exact previous release\n"
        target.write_bytes(previous)
        with patch.dict(annotations.PREVIOUS, {"prediction_filter.lua": hashlib.sha256(previous).hexdigest()}):
            self.assertTrue(prediction.state(self.rime)["installed"])
            prediction.set_settings(True, rime_dir=self.rime)
            path = annotations.settings_path(self.rime)
            path.parent.mkdir(parents=True)
            path.write_text("language=en\n")
            self.assertFalse(prediction.state(self.rime)["installed"])
            path.write_text("language=off\n")
            target.write_bytes(previous + b"-- independent edit\n")
            self.assertFalse(prediction.state(self.rime)["installed"])

    def test_controls_require_deployment_and_do_not_touch_kev(self) -> None:
        with self.assertRaises(ValueError):
            prediction.set_settings(True, rime_dir=self.rime)
        self.install()
        with self.assertRaises(ValueError):
            prediction.set_settings(True, rime_dir=self.rime)
        self.deploy_fixture()
        kev = self.root / "kev-enabled"
        kev.write_text("1\n")
        prediction.set_settings(True, rime_dir=self.rime)
        self.assertTrue(prediction.state(self.rime)["installed"])
        self.assertTrue(prediction.state(self.rime)["enabled"])
        prediction.set_settings(False, rime_dir=self.rime)
        self.assertFalse(prediction.state(self.rime)["enabled"])
        self.assertEqual(kev.read_text(), "1\n")

    def test_controls_refuse_damaged_or_customized_deployed_prediction_structure(self) -> None:
        self.install()
        self.deploy_fixture()
        path = self.rime / "build" / f"{prediction.SCHEMA}.schema.yaml"
        deployed = path.read_text()
        unsafe_deployments = [
            deployed.replace(f'    - "{prediction.FILTER}"\n', ""),
            deployed.replace(f'    - "{prediction.FILTER}"\n', f'    - "{prediction.FILTER}"\n    - lua_filter@*other\n'),
            deployed.replace('    - "predict_translator"\n', ""),
            deployed.replace('    - "predict_translator"\n', '    - "predict_translator"\n    - "predict_translator"\n'),
            deployed.replace('    - "predictor"\n', '    - "predictor"\n    - "predictor"\n'),
            deployed.replace(f'    - "{prediction.LOGGER}"\n', f'    - "{prediction.LOGGER}"\n    - "{prediction.LOGGER}"\n'),
        ]
        for altered in unsafe_deployments:
            self.assertNotEqual(altered, deployed)
            path.write_text(altered)
            with self.subTest(deployed=altered):
                self.assertFalse(prediction.state(self.rime)["installed"])
                with self.assertRaises(ValueError):
                    prediction.set_settings(True, rime_dir=self.rime)
                self.assertFalse(prediction.state(self.rime)["enabled"])
        path.write_text(deployed)
        self.assertTrue(prediction.state(self.rime)["installed"])
        custom = self.rime / f"{prediction.SCHEMA}.custom.yaml"
        custom.write_text('patch:\n  "engine/filters": []\n')
        self.assertFalse(prediction.state(self.rime)["installed"])
        with self.assertRaises(ValueError):
            prediction.set_settings(True, rime_dir=self.rime)

    def test_invalid_controls_are_rejected_before_writes(self) -> None:
        for args in [(1, 3, 1), (False, True, 1), (False, 0, 1), (False, 6, 1), (False, 3, 0), (False, 3, 2)]:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    prediction.set_settings(*args, rime_dir=self.rime)
        self.assertFalse(prediction.settings_path(self.rime).exists())

    def test_console_schema_updates_managed_snapshot_only_with_backup(self) -> None:
        path = self.rime / f"{prediction.SCHEMA}.schema.yaml"
        source = prediction.render_schema(DAILY.replace("    - lua_translator@*keytrack_phrases\n", ""))
        path.write_text(source)
        changes = prediction.console_schema_changes(self.rime, hotkey="Control+Alt+j", phrases=True)
        self.assertEqual(set(changes), {path})
        updated = changes[path]
        self.assertEqual(prediction.yaml_list(updated, "engine", "processors"),
                         prediction.yaml_list(source, "engine", "processors"))
        self.assertEqual(prediction.yaml_list(updated, "engine", "filters"),
                         prediction.yaml_list(source, "engine", "filters"))
        translators = prediction.yaml_list(updated, "engine", "translators")
        self.assertEqual(translators.count("lua_translator@*keytrack_phrases"), 1)
        self.assertIn('  hotkey: "Control+Alt+j"\n', updated)
        self.assertIn("  dictionary: rime_ice\n", updated)
        backups = list((prediction.state_root(self.rime) / "backups").glob(f"*-console/{path.name}"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), source)
        self.assertEqual(path.read_text(), source)  # writes join the console transaction
        path.write_text(updated)
        self.assertEqual(prediction.console_schema_changes(self.rime, hotkey="Control+Alt+j", phrases=True), {})
        self.assertEqual(len(list((prediction.state_root(self.rime) / "backups").glob(f"*-console/{path.name}"))), 1)
        path.write_text("# another plugin\n" + source)
        with self.assertRaises(ValueError):
            prediction.console_schema_changes(self.rime, hotkey="Control+Alt+j", phrases=True)
        self.assertTrue(path.read_text().startswith("# another plugin\n"))

    def test_custom_db_replacement_has_backup_and_survives_reinstall(self) -> None:
        self.install()
        replacement = self.root / "replacement.db"
        replacement_bytes = b"Rime::Predict/1.0\0" + b"x" * 100
        replacement.write_bytes(replacement_bytes)
        self.assertTrue(prediction.setup(False, self.rime, deploy=False, db_file=replacement))
        self.assertEqual((self.rime / prediction.DB_NAME).read_bytes(), replacement_bytes)
        backups = list((prediction.state_root(self.rime) / "backups").glob(f"*/{prediction.DB_NAME}"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.db_bytes)
        self.install()
        self.assertEqual((self.rime / prediction.DB_NAME).read_bytes(), replacement_bytes)
        self.assertEqual(len(list((prediction.state_root(self.rime) / "backups").glob(f"*/{prediction.DB_NAME}"))), 1)
        replacement.write_bytes(b"invalid database")
        original = self.before()
        self.assertFalse(prediction.setup(False, self.rime, deploy=False, db_file=replacement))
        self.assertEqual(self.before(), original)

    def test_rollback_removes_only_managed_entry_and_keeps_new_user_changes(self) -> None:
        self.install()
        self.deploy_fixture()
        prediction.set_settings(True, rime_dir=self.rime)
        path = self.rime / "default.custom.yaml"
        path.write_text(path.read_text() + "later_user_change:\n  enabled: true\n")
        prediction.rollback(self.rime, deploy=False)
        content = path.read_text()
        self.assertNotIn(prediction.BEGIN, content)
        self.assertNotIn(prediction.SCHEMA, content)
        self.assertIn(self.default, content)
        self.assertIn("later_user_change:\n  enabled: true\n", content)
        self.assertFalse(prediction.state(self.rime)["enabled"])
        self.assertTrue((self.rime / f"{prediction.SCHEMA}.schema.yaml").exists())
        self.assertEqual((self.root / "history.db").read_bytes(), b"synthetic history retained")

    def test_conflicts_preflight_before_changing_other_files(self) -> None:
        conflicts = [
            ("default.custom.yaml", 'patch:\n  "schema_list/@next":\n    schema: other\n'),
            (f"{prediction.SCHEMA}.schema.yaml", "# another plugin\n"),
            (f"{prediction.SCHEMA}.custom.yaml", "patch:\n  keep: true\n"),
            ("lua/prediction_guard.lua", "-- another plugin\n"),
            (prediction.DB_NAME, "another plugin db"),
        ]
        for name, content in conflicts:
            target = self.rime / name
            before_content = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            original = self.before()
            with self.subTest(name=name):
                self.assertFalse(prediction.setup(False, self.rime, deploy=False))
                self.assertEqual(self.before(), original)
                self.assertFalse(prediction.settings_path(self.rime).exists())
            if before_content is None:
                target.unlink()
            else:
                target.write_bytes(before_content)

    def test_symlink_state_and_config_are_rejected_without_target_changes(self) -> None:
        external = self.root / "external"
        external.write_text("keep me\n")
        settings = prediction.settings_path(self.rime)
        settings.parent.mkdir(parents=True)
        settings.symlink_to(external)
        with self.assertRaises(ValueError):
            prediction.set_settings(False, rime_dir=self.rime)
        self.assertFalse(prediction.setup(False, self.rime, deploy=False))
        settings.unlink()
        (self.rime / "default.custom.yaml").unlink()
        (self.rime / "default.custom.yaml").symlink_to(external)
        self.assertFalse(prediction.setup(False, self.rime, deploy=False))
        self.assertEqual(external.read_text(), "keep me\n")

    def test_manifest_symlink_is_rejected_before_any_rime_writes(self) -> None:
        manifest = prediction.state_root(self.rime) / "installed.json"
        external = self.root / "external-manifest"
        external.write_text('{"files": {}}\n')
        manifest.parent.mkdir(parents=True)
        manifest.symlink_to(external)
        original = self.before()
        self.assertFalse(prediction.setup(False, self.rime, deploy=False))
        self.assertEqual(self.before(), original)
        self.assertEqual(external.read_text(), '{"files": {}}\n')
        self.assertTrue(manifest.is_symlink())
        self.assertFalse(prediction.settings_path(self.rime).exists())

    def test_manifest_write_failure_restores_changed_existing_files(self) -> None:
        self.install()
        # Preserve an original scheme list until the last publication step.
        (self.rime / "default.custom.yaml").write_text(self.default)
        (self.rime / "build/rime_ice.schema.yaml").write_text(
            DAILY.replace('  alphabet: "abcdefghijklmnopqrstuvwxyz;"', '  alphabet: "abcxyz;"')
        )
        replacement = self.root / "next-db"
        replacement.write_bytes(b"Rime::Predict/1.0\0" + b"y" * 100)
        manifest = prediction.state_root(self.rime) / "installed.json"
        original_manifest = manifest.read_bytes()
        original = self.before()
        atomic = prediction._atomic
        failed = False
        changed_before_failure = set()

        def fail_manifest_once(path, data):
            nonlocal failed
            if path == manifest and not failed:
                # Both existing experimental files were changed before failure.
                changed_before_failure.update(
                    name for name in (f"{prediction.SCHEMA}.schema.yaml", prediction.DB_NAME)
                    if (self.rime / name).read_bytes() != original[self.rime / name]
                )
                failed = True
                raise OSError("synthetic manifest publish failure")
            return atomic(path, data)

        with patch.object(prediction, "_atomic", side_effect=fail_manifest_once):
            self.assertFalse(prediction.setup(False, self.rime, deploy=False, db_file=replacement))
        self.assertTrue(failed)
        self.assertEqual(changed_before_failure, {f"{prediction.SCHEMA}.schema.yaml", prediction.DB_NAME})
        self.assertEqual(self.before(), original)
        self.assertEqual(manifest.read_bytes(), original_manifest)
        self.assertEqual((self.rime / "default.custom.yaml").read_text(), self.default)


if __name__ == "__main__":
    unittest.main()
