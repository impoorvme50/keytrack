"""Exercise the native app's real private-pipe protocol with synthetic state."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


class NativePipeTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, str(PROJECT / "kbd.py"), "console-native", "--demo"],
            cwd=PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        self.addCleanup(self.close)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()

    def request(self, payload):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())
        self.assertTrue(result["ok"], result)
        return result["data"]

    def test_multiline_save_restore_and_following_requests_stay_framed(self):
        state = self.request({"action": "state"})
        before = state["phrases"]
        items = [{"code": "qnative", "category": "测试", "text": '第一行\n第二行 "引号"'}]
        saved = self.request({"action": "phrases", "phrases": items, "revision": state["revision"]})
        current = self.request({"action": "state"})
        self.assertEqual(current["phrases"], items)
        self.assertIsNone(self.request({"action": "report", "day": current["today"]})["segments"])
        self.request({"action": "restore", "id": saved["backup"], "revision": current["revision"]})
        self.assertEqual(self.request({"action": "state"})["phrases"], before)
        self.assertEqual(len(self.request({"action": "backups"})["backups"]), 2)

    def test_malformed_line_returns_one_error_and_next_request_succeeds(self):
        self.process.stdin.write("not-json\n")
        self.process.stdin.flush()
        error = json.loads(self.process.stdout.readline())
        self.assertFalse(error["ok"])
        self.assertTrue(self.request({"action": "state"})["status"]["demo"])
        result = self.request({"action": "kev", "enabled": True})
        self.assertIn("演示", result["message"])
        self.assertFalse(self.request({"action": "state"})["status"]["kev_enabled"])

    def test_prediction_round_trip_does_not_toggle_kev_or_break_pipe(self):
        original = self.request({"action": "state"})
        self.assertFalse(original["prediction"]["enabled"])
        self.request({"action": "prediction", "enabled": True, "max_candidates": 5, "max_iterations": 1})
        current = self.request({"action": "state"})
        self.assertTrue(current["prediction"]["enabled"])
        self.assertEqual(current["prediction"]["max_candidates"], 5)
        self.assertEqual(current["status"]["kev_enabled"], original["status"]["kev_enabled"])
        self.request({"action": "prediction", "enabled": False})
        self.assertFalse(self.request({"action": "state"})["prediction"]["enabled"])
        self.assertIsNone(self.request({"action": "report", "day": current["today"]})["segments"])

    def test_shared_appearance_catalog_and_new_theme_round_trip(self):
        self.request({"action": "prediction", "enabled": True, "max_candidates": 4})
        original = self.request({"action": "state"})
        themes = original["appearance_themes"]
        self.assertEqual({item["id"] for item in themes},
                         {"green", "blue", "slate", "forest", "mint", "mist", "navy", "sand", "paper"})
        self.assertEqual(len(themes), 9)
        for item in themes:
            self.assertTrue(item["name"])
            self.assertTrue(item["description"])
            for mode in ("light", "dark"):
                self.assertIn("hilited_candidate_back_color", item[mode])
                self.assertIn("candidate_text_color", item[mode])
                for value in item[mode].values():
                    self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$")

        saved = self.request({"action": "settings", "revision": original["revision"],
                              "settings": dict(original["settings"], theme="forest", font_size=18)})
        current = self.request({"action": "state"})
        self.assertEqual(current["settings"]["theme"], "forest")
        self.assertEqual(current["settings"]["font_size"], 18)
        self.assertEqual(current["appearance_themes"], themes)
        for key in ("phrases", "prediction"):
            self.assertEqual(current[key], original[key])
        self.assertEqual(current["status"]["kev_enabled"], original["status"]["kev_enabled"])

        self.request({"action": "restore", "id": saved["backup"], "revision": current["revision"]})
        restored = self.request({"action": "state"})
        for key in ("settings", "phrases", "prediction"):
            self.assertEqual(restored[key], original[key])
        self.assertEqual(restored["status"]["kev_enabled"], original["status"]["kev_enabled"])
