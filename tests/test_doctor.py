"""Diagnose job state and deployment drift using isolated fixtures."""
import io
import json
import subprocess
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from keytrack import agent, doctor, kev_rime_bridge, kev_rime_setup, kev_service


class AgentStateTests(unittest.TestCase):
    def test_loaded_and_running_are_different(self):
        for output, running, pid in (
            ("state = running\n pid = 123\n", True, 123),
            ("state = waiting\n", False, None),
            ("state = running\n", False, None),
        ):
            with patch.object(agent.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=output, stderr="",
            )) as run:
                state = agent.service_status()
                self.assertTrue(state["loaded"])
                self.assertEqual((state["running"], state["pid"]), (running, pid))
                self.assertEqual(run.call_args.args[0][1], "print")

    def test_permission_error_is_unknown_not_stopped(self):
        with patch.object(agent.subprocess, "run", return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="Operation not permitted",
        )):
            self.assertEqual(agent.service_status()["state"], "unknown")
        with patch.object(agent.subprocess, "run", side_effect=subprocess.TimeoutExpired("launchctl", 2)):
            self.assertEqual(agent.service_status()["state"], "unknown")


class LocalConnectionTests(unittest.TestCase):
    def test_system_proxy_is_bypassed(self):
        with patch.object(urllib.request, "build_opener") as build:
            request = urllib.request.Request(kev_rime_bridge.DEFAULT_URL)
            kev_rime_bridge.open_local(request, timeout=1)
            self.assertEqual(build.call_args.args[0].proxies, {})
            build.return_value.open.assert_called_once_with(request, timeout=1)

    def test_remote_url_and_redirect_are_rejected(self):
        with self.assertRaises(ValueError):
            kev_rime_bridge.open_local(urllib.request.Request("https://example.com"), 1)
        with self.assertRaises(ValueError):
            kev_rime_bridge._NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_oversized_response_cannot_change_candidates(self):
        response = io.BytesIO(b" " * (kev_rime_bridge.MAX_RESPONSE_BYTES + 1))
        response.status = 200
        with patch.object(kev_rime_bridge, "open_local", return_value=response):
            with self.assertRaisesRegex(ValueError, "response too large"):
                kev_rime_bridge.decide_candidate({
                    "input": "nihao", "previous_text": "", "candidates": ["你好", "拟好"],
                })


class DoctorTests(unittest.TestCase):
    def test_drift_is_reported_and_disabled_ai_does_not_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lua").mkdir()
            (root / "build").mkdir()
            for name in kev_rime_setup.LUA_FILES:
                (root / "lua" / name).write_bytes((kev_rime_setup.PROJECT_DIR / "rime" / name).read_bytes())
            (root / "build/rime_ice.schema.yaml").write_text(
                "lua_processor@*kev_hotkey\nlua_filter@*kev_filter\n",
            )
            with (
                patch.object(kev_rime_setup, "RIME_DIR", root),
                patch.object(doctor.kev_switch, "is_enabled", return_value=False),
                patch.object(agent, "service_status", return_value={"running": True, "pid": 123}),
                patch.object(kev_rime_bridge, "open_local") as connect,
            ):
                with redirect_stdout(io.StringIO()):
                    self.assertTrue(doctor.command(as_json=True))
                connect.assert_not_called()
                (root / "lua/kev_hotkey.lua").write_text("old version")
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertFalse(doctor.command(as_json=True))
                checks = json.loads(output.getvalue())["checks"]
                self.assertTrue(any(item["name"] == "kev_hotkey.lua" and item["level"] == "error" for item in checks))

    def test_enabled_ai_checks_model_identity(self):
        response = io.BytesIO(b'{"models": [{"id": "other-model"}]}')
        response.status = 200
        with (
            patch.object(doctor.kev_switch, "is_enabled", return_value=True),
            patch.object(kev_service, "PLIST_PATH", Path("/nonexistent/keytrack-test.plist")),
            patch.object(agent, "service_status", return_value={"running": True, "pid": 123}),
            patch.object(kev_rime_bridge, "open_local", return_value=response),
        ):
            checks = doctor.checks()
            self.assertTrue(any(item["name"] == "kev_http" and item["level"] == "error" for item in checks))


if __name__ == "__main__":
    unittest.main()
