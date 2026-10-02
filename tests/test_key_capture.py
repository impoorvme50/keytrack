"""Prevent incomplete legacy counts from masquerading as physical key statistics."""
from contextlib import closing
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from keytrack import console, ime_ingest, key_stats, layouts, rime_setup, kev_rime_setup, storage, query, week, ergo


class CaptureTests(unittest.TestCase):
    def test_physical_names_and_chords(self):
        cases = {'comma': ',', 'period': '.', 'quotedbl': "'", 'backslash': '\\',
                 'A': 'a', 'Super+a': 'a', 'Shift+Control+k': 'k', 'Super+Super_L': 'cmd',
                 'Control+Control_R': 'ctrl_r', 'Shift+BackSpace': 'backspace', 'Shift++': '=',
                 'Left': None, 'F12': None, 'Escape': None}
        for name, physical in cases.items():
            self.assertEqual(layouts.norm_key(name), physical, name)
        for shifted, physical in zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'):
            self.assertEqual(layouts.norm_key(shifted), physical)

    def test_migration_is_idempotent_preserves_user_and_kev(self):
        content = '# user\n' + rime_setup._BEGIN + '\npatch:\n  "engine/processors/@next": lua_processor@*keytrack_logger\n' + rime_setup._END + '\n'
        content = kev_rime_setup.render_custom_yaml(content, Path('/python'), Path('/bridge'))
        content += '  "style/font_point": 18\nother:\n  keep: true\n'
        updated = rime_setup.render_custom_yaml(content)
        self.assertIn('"engine/processors/@before 0": lua_processor@*keytrack_logger', updated)
        self.assertIn('"engine/processors/@before 1": lua_processor@*kev_hotkey', updated)
        self.assertIn('other:\n  keep: true', updated)
        self.assertEqual(rime_setup.render_custom_yaml(updated), updated)
        self.assertEqual(kev_rime_setup.render_custom_yaml(updated, Path('/python'), Path('/bridge')), updated)
        self.assertEqual(updated.count('lua_processor@*keytrack_logger'), 1)

    def test_unknown_slot_not_overwritten(self):
        for processor in ('lua_processor@*other', 'speller'):
            with self.assertRaises(ValueError):
                rime_setup.render_custom_yaml(f'patch:\n  "engine/processors/@before 0": {processor}\n')

    def test_old_mixed_and_verified_same_minute(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = str(Path(temporary) / 'test.db')
            with storage.connect(db) as conn:
                ime_ingest.store_key_buckets(conn, [{'min': '2026-10-01T12:00', 'keys': {'BackSpace': 10}}])
                self.assertEqual(key_stats.quality(conn, '2026-10-01')['status'], 'legacy')
                ime_ingest.store_key_buckets(conn, [{'min': '2026-10-01T12:00', 'capture_version': 3, 'keys': {'a': 10}}])
                self.assertEqual(key_stats.quality(conn, '2026-10-01')['status'], 'mixed')
                ime_ingest.store_key_buckets(conn, [{'min': '2026-10-02T12:00', 'capture_version': 3,
                    'keys': {'a': 10, 'comma': 2, 'Shift+BackSpace': 1, 'Left': 1}}])
                quality = key_stats.quality(conn, '2026-10-02')
                self.assertTrue(quality['reliable'])
                self.assertEqual(quality['mapped_keys'], 13)
                self.assertEqual(quality['unmapped_keys'], 1)
                self.assertEqual(quality['first_verified_minute'], '2026-10-01T12:00')
            store = console.ConsoleStore(Path(temporary)/'state', Path(temporary)/'Rime', db, demo=True)
            before = hashlib.sha256(Path(db).read_bytes()).digest()
            old = store.report('2026-10-01')
            self.assertIsNone(old['cpm'])
            self.assertIsNone(old['active_minutes'])
            self.assertIsNone(old['correction_rate'])
            self.assertEqual(old['fingers'], [])
            self.assertEqual(old['hours'], [])
            new = store.report('2026-10-02')
            self.assertEqual(new['key_frequency'][','], 2)
            self.assertEqual(new['correction_rate'], 7.1)
            self.assertEqual(sum(f['count'] for f in new['fingers']), 13)
            self.assertEqual(hashlib.sha256(Path(db).read_bytes()).digest(), before)
            self.assertIsNone(query.day_report(__import__('datetime').date(2026,10,1), db)['cpm'])
            self.assertIsNone(week.week_report(__import__('datetime').date(2026,10,2),2, db)['avg_cpm'])
            self.assertIsNone(ergo.analyze(None, db)['finger_entropy'])

    def test_provenance_is_atomic(self):
        with tempfile.TemporaryDirectory() as temporary, storage.connect(str(Path(temporary)/'db')) as conn:
            conn.execute("CREATE TRIGGER fail BEFORE INSERT ON key_capture_minutes BEGIN SELECT RAISE(ABORT, 'failure'); END")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                ime_ingest.store_key_buckets(conn, [{'min':'2026-10-02T12:00','capture_version':3,'keys':{'a':1}}])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM key_counts').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM key_minutes').fetchone()[0],0)

    def test_old_database_read_without_migration(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.executescript("CREATE TABLE key_counts(day,key,count); CREATE TABLE key_minutes(minute,count); INSERT INTO key_counts VALUES('2026-10-01','Return',20); INSERT INTO key_minutes VALUES('2026-10-01T12:00',20);")
            self.assertEqual(key_stats.quality(conn, '2026-10-01')['status'], 'legacy')
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='key_capture_minutes'").fetchone())
