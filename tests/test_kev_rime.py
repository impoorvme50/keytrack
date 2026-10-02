"""Kev/Rime bridge and configuration regression checks; no model weights needed."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from keytrack import kev_rime_bridge, kev_rime_setup, kev_service, kev_switch


class FakeResponse(io.BytesIO):
    status = 200


class BridgeTests(unittest.TestCase):
    def test_choice_maps_back_to_candidate_index(self) -> None:
        request = {
            "input": "yisheng",
            "previous_text": "去医院看",
            "candidates": ["一生", "医生", "一声"],
        }
        result = {"answers": {"next": {"choice": "c2", "probabilities": {
            "c1": 0.04, "c2": 0.93, "c3": 0.03
        }}}}
        with patch.object(kev_rime_bridge, "open_local", return_value=FakeResponse(json.dumps(result).encode())) as send:
            self.assertEqual(kev_rime_bridge.choose_candidate(request), 2)
        sent = json.loads(send.call_args.args[0].data)
        self.assertEqual(sent["questions"]["next"]["criteria"], {
            "c1": "一生", "c2": "医生", "c3": "一声"
        })
        self.assertIn("去医院看", sent["state"])
        self.assertIn("当前拼音：yisheng", sent["state"])
        self.assertIn("前文语境", sent["questions"]["next"]["instructions"])
        self.assertEqual(send.call_args.kwargs["timeout"], kev_rime_bridge.TIMEOUT_SECONDS)

    def test_unexpected_choice_cannot_change_candidates(self) -> None:
        request = {"input": "abc", "previous_text": "", "candidates": ["甲", "乙"]}
        result = {"answers": {"next": {"choice": "c3", "probabilities": {
            "c1": 0.1, "c2": 0.2
        }}}}
        with patch.object(kev_rime_bridge, "open_local", return_value=FakeResponse(json.dumps(result).encode())):
            with self.assertRaises(ValueError):
                kev_rime_bridge.choose_candidate(request)

    def test_cli_writes_only_successful_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "request.json"
            response = Path(directory) / "response.txt"
            request.write_text(
                json.dumps({"input": "abc", "previous_text": "", "candidates": ["甲", "乙"]}),
                encoding="utf-8",
            )
            with patch.object(
                kev_rime_bridge,
                "decide_candidate",
                return_value=kev_rime_bridge.Decision(2, 0.93, 0.86),
            ):
                self.assertEqual(kev_rime_bridge.main([str(request), str(response)]), 0)
            self.assertEqual(response.read_text(encoding="ascii"), "2\t1\n")

    def test_weak_manual_choice_is_only_a_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / "request.json"
            response = Path(directory) / "response.txt"
            request.write_text(
                json.dumps({"input": "abc", "previous_text": "", "candidates": ["甲", "乙"]}),
                encoding="utf-8",
            )
            with patch.object(
                kev_rime_bridge,
                "decide_candidate",
                return_value=kev_rime_bridge.Decision(2, 0.65, 0.30),
            ):
                self.assertEqual(kev_rime_bridge.main([str(request), str(response)]), 0)
            self.assertEqual(response.read_text(encoding="ascii"), "2\t0\n")

    def test_invalid_probability_distribution_is_rejected(self) -> None:
        request = {"input": "abc", "previous_text": "", "candidates": ["甲", "乙"]}
        result = {"answers": {"next": {"choice": "c2", "probabilities": {
            "c1": 0.6, "c2": 0.6
        }}}}
        with patch.object(kev_rime_bridge, "open_local", return_value=FakeResponse(json.dumps(result).encode())):
            with self.assertRaises(ValueError):
                kev_rime_bridge.decide_candidate(request)


class SwitchTests(unittest.TestCase):
    def test_default_off_and_persistent_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "enabled"
            self.assertFalse(kev_switch.is_enabled(path))
            kev_switch.set_enabled(True, path)
            self.assertTrue(kev_switch.is_enabled(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            kev_switch.set_enabled(False, path)
            self.assertFalse(kev_switch.is_enabled(path))

    def test_symlink_switch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target"
            target.write_text("1\n")
            path = Path(directory) / "enabled"
            path.symlink_to(target)
            self.assertFalse(kev_switch.is_enabled(path))
            with self.assertRaises(OSError):
                kev_switch.set_enabled(False, path)
            self.assertEqual(target.read_text(), "1\n")


class SetupTests(unittest.TestCase):
    def test_login_service_is_pinned_to_small_local_model(self) -> None:
        config = kev_service.plist_for(Path("/tmp/Kev"))
        self.assertEqual(config["ProgramArguments"][5], "jaredpalmer/kev-0.8b")
        self.assertEqual(config["ProgramArguments"][-1], "8009")
        self.assertEqual(config["EnvironmentVariables"]["KEV_DTYPE"], "bf16")
        self.assertTrue(config["RunAtLoad"])

    def test_service_switch_persists_with_launchd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plist = Path(directory) / "com.keytrack.kev.plist"
            plist.write_text("test")
            with (
                patch.object(kev_service, "PLIST_PATH", plist),
                patch.object(kev_service, "is_loaded", return_value=True),
                patch.object(
                    kev_service.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                self.assertTrue(kev_service.set_running(False))
                self.assertEqual(run.call_args_list[0].args[0][1], "disable")
                self.assertEqual(run.call_args_list[1].args[0], ["launchctl", "unload", str(plist)])
            with (
                patch.object(kev_service, "PLIST_PATH", plist),
                patch.object(kev_service, "is_loaded", return_value=False),
                patch.object(
                    kev_service.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                self.assertTrue(kev_service.set_running(True))
                self.assertEqual(run.call_args_list[0].args[0][1], "enable")
                self.assertEqual(run.call_args_list[1].args[0], ["launchctl", "load", str(plist)])
            with (
                patch.object(kev_service, "PLIST_PATH", plist),
                patch.object(kev_service, "is_loaded", return_value=False),
                patch.object(
                    kev_service.subprocess,
                    "run",
                    side_effect=[
                        SimpleNamespace(returncode=0),
                        SimpleNamespace(returncode=1),
                        SimpleNamespace(returncode=0),
                    ],
                ) as run,
            ):
                self.assertFalse(kev_service.set_running(True))
                self.assertEqual(run.call_args_list[-1].args[0][1], "disable")

    def test_patch_keeps_existing_settings_and_is_idempotent(self) -> None:
        before = (
            "# existing\npatch:\n"
            '  "engine/processors/@next": lua_processor@*keytrack_logger\n'
            "other:\n  enabled: true\n"
        )
        python = Path("/tmp/keytrack/.venv/bin/python")
        bridge = Path("/tmp/keytrack/keytrack/kev_rime_bridge.py")
        after = kev_rime_setup.render_custom_yaml(before, python, bridge)
        self.assertIn('"engine/filters/@last": lua_filter@*kev_filter', after)
        self.assertIn('"engine/processors/@next": lua_processor@*keytrack_logger', after)
        self.assertLess(after.index(kev_rime_setup.END), after.index("other:"))
        self.assertEqual(kev_rime_setup.render_custom_yaml(after, python, bridge), after)

    def test_setup_installs_scripts_and_backs_up_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rime_dir = Path(directory) / "Rime"
            rime_dir.mkdir()
            custom = rime_dir / "rime_ice.custom.yaml"
            custom.write_text('patch:\n  "engine/processors/@next": lua_processor@*keytrack_logger\n')
            squirrel = Path(directory) / "Squirrel.app"
            squirrel.mkdir()
            with (
                patch.object(kev_rime_setup, "RIME_DIR", rime_dir),
                patch.object(kev_rime_setup, "QUEUE_ROOT", Path(directory) / "kev-rime"),
                patch.object(kev_rime_setup.rime_setup, "SQUIRREL_APP", str(squirrel)),
                patch.object(kev_rime_setup.rime_setup, "redeploy", return_value=True),
            ):
                self.assertTrue(kev_rime_setup.setup(verbose=False))
                self.assertTrue(kev_rime_setup.setup(verbose=False))
            self.assertTrue((rime_dir / "lua/kev_hotkey.lua").exists())
            self.assertTrue((rime_dir / "lua/kev_context.lua").exists())
            self.assertTrue((rime_dir / "lua/kev_filter.lua").exists())
            self.assertIn("lua_filter@*kev_filter", custom.read_text())
            self.assertEqual(len(list(rime_dir.glob("*.bak.kev-*"))), 1)


if __name__ == "__main__":
    unittest.main()
