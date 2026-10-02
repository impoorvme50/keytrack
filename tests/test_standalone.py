"""Package migration preserves user configuration and uses bundle-relative tools."""
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keytrack import agent, console, kev_rime_setup, rime_setup, standalone


class StandaloneTests(unittest.TestCase):
    def test_frozen_launch_agent_uses_bundle_helper(self):
        helper = "/Applications/Keytrack.app/Contents/Resources/keytrack-runtime/keytrack-helper"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", helper):
            value = agent._plist()
        self.assertEqual(value["ProgramArguments"], [helper, "record"])
        self.assertEqual(value["WorkingDirectory"], str(Path(helper).parent))
        self.assertNotIn(".venv", str(value))

    def test_install_requires_application_directory(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "/Volumes/Keytrack/Keytrack.app/Contents/Resources/keytrack-runtime/keytrack-helper"):
            self.assertFalse(standalone.status()["can_install"])
            with self.assertRaisesRegex(ValueError, "应用程序"):
                standalone.install(None)

    def test_configured_checks_both_recorder_and_existing_bridge(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            helper = "/Applications/Keytrack.app/Contents/Resources/keytrack-runtime/keytrack-helper"
            plist = root / "agent.plist"
            plist.write_bytes(plistlib.dumps({"ProgramArguments": [helper, "record"]}))
            custom = root / "rime_ice.custom.yaml"
            custom.write_text(kev_rime_setup.BEGIN + '\n"kev_rime/python": "/old/python"\n')
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", helper), patch.object(agent, "PLIST_PATH", str(plist)), patch.object(kev_rime_setup, "RIME_DIR", root):
                self.assertFalse(standalone.status()["configured"])
                custom.write_text(kev_rime_setup.BEGIN + '\n"kev_rime/python": "' + helper + '"\n')
                self.assertTrue(standalone.status()["configured"])

    def test_install_backs_up_service_and_all_custom_schemas(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            store = console.ConsoleStore(state_dir=root / "console", rime_dir=root / "Rime", db=str(root / "test.db"), demo=True)
            store.demo = False
            store.rime.mkdir(parents=True, exist_ok=True)
            (store.rime / "other.custom.yaml").write_text("patch:\n  keep: true\n")
            (store.rime / "rime_ice.custom.yaml").write_text(kev_rime_setup.BEGIN + "\n")
            plist = root / "agent.plist"
            plist.write_bytes(b"previous service")
            with patch.object(standalone, "status", return_value={"can_install": True}), patch.object(agent, "PLIST_PATH", str(plist)), patch.object(rime_setup, "RIME_DIR", str(store.rime)), patch.object(kev_rime_setup, "RIME_DIR", store.rime), patch.object(rime_setup, "setup", return_value=True), patch.object(kev_rime_setup, "setup", return_value=True) as kev, patch.object(agent, "install", return_value=True):
                result = standalone.install(store)
            snapshot = store.root / "backups" / (result["backup"] + "-installation")
            self.assertEqual((snapshot / plist.name).read_bytes(), b"previous service")
            self.assertEqual((snapshot / "other.custom.yaml").read_text(), "patch:\n  keep: true\n")
            self.assertEqual((snapshot / plist.name).stat().st_mode & 0o777, 0o600)
            kev.assert_called_once_with(verbose=False)

    def test_demo_rejects_install(self):
        with tempfile.TemporaryDirectory() as root:
            store = console.ConsoleStore(state_dir=Path(root), demo=True)
            with self.assertRaisesRegex(ValueError, "演示"):
                console.native_request(store, {"action": "install"})
