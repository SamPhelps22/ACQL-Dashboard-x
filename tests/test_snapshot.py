"""The locked snapshot GitHub sends the emails from (acql/site/snapshot.py)."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acql import store  # noqa: E402
from acql.site import snapshot  # noqa: E402


class Lock(unittest.TestCase):
    def test_round_trip_and_tamper(self):
        key = os.urandom(32)
        plain = os.urandom(5000) + b"\0" * 300
        blob = snapshot.lock(plain, key)
        self.assertNotIn(plain[:64], blob)
        self.assertEqual(snapshot.unlock(blob, key), plain)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.unlock(blob[:-1] + bytes([blob[-1] ^ 1]), key)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.unlock(blob, os.urandom(32))

    def test_key_text(self):
        key = os.urandom(32)
        self.assertEqual(snapshot.parse_key(key.hex().upper()), key)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.parse_key("too short")


class Schedule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.use(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        store.use(None)
        self.tmp.cleanup()

    def at(self, *when):
        return time.mktime((*when, 0, 0, -1))

    def test_due_once_a_day_in_its_window(self):
        tue = (2026, 10, 27)
        self.assertEqual(snapshot.due(self.at(*tue, 11, 50, 0)), [])
        self.assertEqual(snapshot.due(self.at(*tue, 12, 41, 0)), ["email"])
        store.put("cloudrun", "email:2026-10-27", 1.0)
        self.assertEqual(snapshot.due(self.at(*tue, 13, 41, 0)), [])
        self.assertEqual(snapshot.due(self.at(2026, 10, 25, 9, 41, 0)), ["brief"])
        self.assertEqual(snapshot.due(self.at(2026, 10, 26, 12, 41, 0)), [])     # Monday

    def test_pc_steps_aside_only_when_switched_on(self):
        self.assertFalse(snapshot.pc_should_skip("x"))
        store.put("settings", "cloud", {"sending": True})
        self.assertTrue(snapshot.pc_should_skip("x"))

    def test_carry_keeps_earlier_sends(self):
        store.put("alerts", "sent:deadline:2026:8", 5.0)
        path = Path(self.tmp.name) / "c.json"
        snapshot.export_carried(path)
        store.delete("alerts")
        self.assertEqual(snapshot.merge_carried(path), 1)
        self.assertEqual(store.get("alerts", "sent:deadline:2026:8"), 5.0)


if __name__ == "__main__":
    unittest.main()
