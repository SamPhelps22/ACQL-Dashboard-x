"""Phone alerts (acql/site/pushalerts.py): sent once, and never without a topic."""

import unittest
from unittest import mock

from acql.site import pushalerts


class TestPushAlerts(unittest.TestCase):
    def setUp(self):
        self.kept = {}
        self.patches = [
            mock.patch("acql.store.get", lambda k, key, d=None: self.kept.get((k, key), d)),
            mock.patch("acql.store.put", lambda k, key, v: self.kept.__setitem__((k, key), v)),
        ]
        for p in self.patches:
            p.start()
        self.sent = []
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def fake_send(self, title, message, **kw):
        self.sent.append(title)
        return True

    def test_no_topic_sends_nothing(self):
        with mock.patch.object(pushalerts, "send", self.fake_send):
            self.assertFalse(pushalerts._once("x", "t", "m"))
        self.assertEqual(self.sent, [])

    def test_sent_once(self):
        pushalerts.set_topic("acql-test-pool")
        with mock.patch.object(pushalerts, "send", self.fake_send):
            self.assertTrue(pushalerts._once("deadline:2026:7", "t", "m"))
            self.assertFalse(pushalerts._once("deadline:2026:7", "t", "m"))
            self.assertTrue(pushalerts._once("deadline:2026:8", "t", "m"))
        self.assertEqual(len(self.sent), 2)

    def test_bad_topic_refused(self):
        with self.assertRaises(ValueError):
            pushalerts.set_topic("a b")
        self.assertEqual(pushalerts.subscribe_link(), "")

    def test_parse_deadline(self):
        self.assertEqual(pushalerts.parse_deadline("thu 6pm"), (3, 18, 0))
        self.assertEqual(pushalerts.parse_deadline("Sunday 12:30pm"), (6, 12, 30))
        self.assertEqual(pushalerts.parse_deadline("wed 18:45"), (2, 18, 45))
        self.assertEqual(pushalerts.parse_deadline("sat 12am"), (5, 0, 0))
        for bad in ("6pm", "thu", "thu 25:00", "thu 13pm", "funday 6pm"):
            with self.assertRaises(ValueError):
                pushalerts.parse_deadline(bad)

    def test_deadline_kept_where_the_lock_reads_it(self):
        from acql.feeds import oddslock
        pushalerts.set_deadline("sun 12:30pm")
        self.assertEqual(oddslock.deadline_clock(), (6, 12, 30))

    def test_reminder_window(self):
        self.assertTrue(pushalerts.deadline_due(3600, 0))
        self.assertFalse(pushalerts.deadline_due(3 * 3600, 0))
        self.assertFalse(pushalerts.deadline_due(-1, 0))


if __name__ == "__main__":
    unittest.main()
