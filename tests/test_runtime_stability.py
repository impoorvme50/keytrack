"""回归检查：长驻采样的对象生命周期与 SQLite 查询兼容性。"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

from keytrack import ime_ingest, storage


class FrontmostAppTests(unittest.TestCase):
    def test_window_owner_becomes_native_string_inside_pool(self) -> None:
        active = False

        @contextmanager
        def pool():
            nonlocal active
            active = True
            try:
                yield
            finally:
                active = False

        class Owner:
            def __str__(self):
                if not active:
                    raise AssertionError("window owner was converted outside the pool")
                return "Cursor"

        quartz = types.ModuleType("Quartz")
        quartz.CGWindowListCopyWindowInfo = lambda *_: [
            {"kCGWindowLayer": 0, "kCGWindowAlpha": 1, "kCGWindowOwnerName": Owner()}
        ]
        quartz.kCGWindowListOptionOnScreenOnly = 1
        quartz.kCGNullWindowID = 0
        objc = types.ModuleType("objc")
        objc.autorelease_pool = pool

        with patch.dict(sys.modules, {"Quartz": quartz, "objc": objc}):
            result = ime_ingest._frontmost_app()
        self.assertEqual(result, "Cursor")
        self.assertIs(type(result), str)
        self.assertFalse(active)

    def test_missing_fallback_name_is_unknown(self) -> None:
        quartz = types.ModuleType("Quartz")

        def unavailable_windows(*_):
            raise RuntimeError("WindowServer unavailable")

        quartz.CGWindowListCopyWindowInfo = unavailable_windows
        quartz.kCGWindowListOptionOnScreenOnly = 1
        quartz.kCGNullWindowID = 0

        appkit = types.ModuleType("AppKit")
        app = types.SimpleNamespace(localizedName=lambda: None)
        workspace = types.SimpleNamespace(frontmostApplication=lambda: app)
        appkit.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: workspace)

        objc = types.ModuleType("objc")
        objc.autorelease_pool = nullcontext
        with patch.dict(sys.modules, {"Quartz": quartz, "AppKit": appkit, "objc": objc}):
            self.assertEqual(ime_ingest._frontmost_app(), "Unknown")


class StorageTests(unittest.TestCase):
    def test_new_database_uses_wal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "keytrack.db")
            with storage.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_reader_sees_committed_data_during_exclusive_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "keytrack.db")
            with storage.connect(path) as conn:
                storage.insert_segment(conn, "Test", None, 1, 1, "committed", 9)

            writer = sqlite3.connect(path)
            try:
                writer.execute("BEGIN EXCLUSIVE")
                writer.execute(
                    "INSERT INTO segments (app, window, start_ts, end_ts, text, key_count) "
                    "VALUES (?, NULL, ?, ?, ?, ?)",
                    ("Test", 2, 2, "pending", 7),
                )
                with storage.connect(path) as reader:
                    self.assertEqual(
                        [row[0] for row in reader.execute("SELECT text FROM segments ORDER BY id")],
                        ["committed"],
                    )
            finally:
                writer.rollback()
                writer.close()

    def test_existing_readonly_database_can_be_queried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "keytrack.db")
            with sqlite3.connect(path) as conn:
                storage._init_schema(conn)
                conn.execute(
                    "INSERT INTO segments (app, window, start_ts, end_ts, text, key_count) "
                    "VALUES (?, NULL, ?, ?, ?, ?)",
                    ("Test", 1, 1, "sample", 6),
                )
            os.chmod(path, 0o444)
            try:
                with storage.connect(path) as conn:
                    self.assertEqual(
                        conn.execute("SELECT text FROM segments").fetchone()[0], "sample"
                    )
                    self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            finally:
                os.chmod(path, 0o644)


if __name__ == "__main__":
    unittest.main()
