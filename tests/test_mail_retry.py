"""Gmail sends try again when the connection cannot be made, and never send twice."""

import smtplib
import sys
import unittest
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acql.site import mailer  # noqa: E402


class Settings:
    sender, password = "me@example.com", "x"


def server_factory(plan):
    """A fake Gmail: `plan` is one entry per connection - an exception to raise, or None for a good send."""
    log = {"connections": 0, "delivered": 0}

    class Server:
        def __init__(self):
            log["connections"] += 1
            self.step = plan[min(log["connections"], len(plan)) - 1]

        def __enter__(self):
            if isinstance(self.step, OSError) and not isinstance(self.step, smtplib.SMTPException):
                raise self.step
            return self

        def __exit__(self, *_exc):
            if isinstance(self.step, smtplib.SMTPServerDisconnected):
                raise self.step
            return False

        def login(self, *_):
            if isinstance(self.step, smtplib.SMTPAuthenticationError):
                raise self.step

        def send_message(self, _message):
            log["delivered"] += 1

    return Server, log


def send(plan, **kwargs):
    factory, log = server_factory(plan)
    naps = []
    try:
        mailer.send(Settings, EmailMessage(), smtp_factory=factory, sleep=naps.append, pause=7, **kwargs)
    finally:
        log["naps"] = naps
    return log


class RetryTests(unittest.TestCase):
    def test_a_blip_is_retried_and_then_sent(self):
        log = send([OSError("no DNS"), None])
        self.assertEqual((log["connections"], log["delivered"], log["naps"]), (2, 1, [7]))

    def test_it_gives_up_after_the_last_try(self):
        with self.assertRaises(mailer.MailError) as caught:
            send([OSError("down")], attempts=3)
        self.assertIn("after 3 tries", str(caught.exception))

    def test_a_refused_sign_in_is_not_retried(self):
        with self.assertRaises(mailer.MailError):
            send([smtplib.SMTPAuthenticationError(535, b"no")])

    def test_a_failure_only_on_closing_does_not_send_twice(self):
        log = send([smtplib.SMTPServerDisconnected("closed")])
        self.assertEqual((log["connections"], log["delivered"]), (1, 1))


class PublishRetryTests(unittest.TestCase):
    def setUp(self):
        from acql import headless
        self.headless = headless
        self.logged = []
        headless._log, self._real_log = self.logged.append, headless._log

    def tearDown(self):
        self.headless._log = self._real_log

    def test_a_dropped_connection_is_tried_again(self):
        calls, naps = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("timed out")
            return "https://site"

        self.assertEqual(self.headless._retrying(flaky, ValueError, pause=5, sleep=naps.append), "https://site")
        self.assertEqual((len(calls), naps), (3, [5, 5]))
        self.assertEqual(len(self.logged), 2)

    def test_the_last_failure_is_raised(self):
        def down():
            raise ValueError("down")
        with self.assertRaises(ValueError):
            self.headless._retrying(down, ValueError, tries=2, sleep=lambda _s: None)

    def test_other_errors_are_not_retried(self):
        calls = []

        def broken():
            calls.append(1)
            raise KeyError("bug")
        with self.assertRaises(KeyError):
            self.headless._retrying(broken, ValueError, sleep=lambda _s: None)
        self.assertEqual(len(calls), 1)


class LogbookTests(unittest.TestCase):
    def test_a_trouble_is_logged_once_per_kind_and_never_raises(self):
        from acql import logbook
        from acql.ui.pages import base
        lines = []
        real, base.write_log = base.write_log, lines.append
        logbook._SEEN.clear()
        try:
            logbook.trouble("pick sheets not saved", ValueError("disk full"))
            logbook.trouble("pick sheets not saved", ValueError("disk full"))
            logbook.trouble("pick sheets not saved", ValueError("locked"))
        finally:
            base.write_log = real
        self.assertEqual(lines, ["pick sheets not saved: ValueError: disk full",
                                 "pick sheets not saved: ValueError: locked"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
