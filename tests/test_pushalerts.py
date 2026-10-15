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

    def test_reminder_window(self):
        self.assertTrue(pushalerts.deadline_due(3600, 0))
        self.assertFalse(pushalerts.deadline_due(3 * 3600, 0))
        self.assertFalse(pushalerts.deadline_due(-1, 0))


if __name__ == "__main__":
    unittest.main()
