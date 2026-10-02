"""Run candidate-comment contracts in an isolated synthetic HOME."""
from pathlib import Path
import os
import shutil
import stat
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class CommentsLuaTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lua"), "Lua runtime unavailable")
    def test_glossary_filter_contracts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="keytrack-comments-mock-") as directory:
            home = Path(directory)
            for name in ("annotations", "kev-rime", "prediction"):
                (home / ".keytrack" / name).mkdir(parents=True)
            control = home / ".keytrack/annotations/control"
            os.mkfifo(control)
            self.assertTrue(stat.S_ISFIFO(control.stat().st_mode))
            result = subprocess.run(
                [shutil.which("lua"), str(PROJECT / "tests/keytrack_comments_lua.lua"),
                 str(PROJECT), str(home)], text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("passed: 13 contracts", result.stdout)
            self.assertTrue(stat.S_ISFIFO(control.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
