"""The release guard: leftover merge markers and Python that does not compile."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
import guard  # noqa: E402

OPEN, CLOSE = b"<" * 7, b">" * 7


class GuardTests(unittest.TestCase):
    def test_clean_files_pass(self):
        self.assertEqual(guard.problems({"a.py": b"x = 1\n", "page.html": b"<p>a <<< b</p>\n"}), [])

    def test_conflict_marker_is_reported_with_its_line(self):
        page = b"<script>\nvar a;\n" + OPEN + b" HEAD\nvar b;\n=======\nvar c;\n" + CLOSE + b" 933e581\n</script>\n"
        self.assertEqual(guard.problems({"acql/ui/pool_page.html": page}),
                         ["acql/ui/pool_page.html:3: leftover merge conflict marker"])

    def test_crlf_marker_line_is_reported(self):
        self.assertEqual(len(guard.problems({"README.md": OPEN + b"\r\n"})), 1)

    def test_python_that_does_not_compile_is_reported(self):
        found = guard.problems({"a.py": b"def f(:\n"})
        self.assertEqual(len(found), 1)
        self.assertIn("does not compile", found[0])

    def test_marker_in_python_gives_both_complaints(self):
        found = guard.problems({"t.py": b"x = 1\n" + OPEN + b" HEAD\ny = 2\n"})
        self.assertEqual(len(found), 2)

    def test_updates_and_binary_types_are_left_alone(self):
        self.assertEqual(guard.problems({"updates/x.zip": OPEN + b" HEAD\n", "logo.png": OPEN + b" \n"}), [])

    @unittest.skipUnless(guard.chrome(), "no Chrome or Edge to parse scripts with")
    def test_a_page_script_that_does_not_parse_is_reported(self):
        self.assertEqual(guard.script_problems("p.html", b"<script>var a = 1;</script><script src='x.js'></script>"), [])
        found = guard.script_problems("p.html", b"<script>var a = 1;</script><script>var b = ;</script>")
        self.assertEqual(len(found), 1)
        self.assertIn("script 2: SyntaxError", found[0])


class HeartbeatTests(unittest.TestCase):
    """The off-PC check: behind only when games finished well after the site was built."""

    def test_verdicts(self):
        from datetime import datetime, timezone
        import heartbeat
        board = {"events": [{"date": "2026-10-18T17:00Z", "shortName": "NE @ CHI",
                             "status": {"type": {"completed": True}}},
                            {"date": "2026-10-20T00:15Z", "shortName": "KC @ SEA",
                             "status": {"type": {"completed": False}}}]}
        old = '{"generated":"2026-10-18 09:00"}'
        new = '{"generated":"2026-10-18 18:00"}'
        monday = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
        self.assertTrue(heartbeat.verdict(old, board, monday)["behind"])
        self.assertFalse(heartbeat.verdict(new, board, monday)["behind"])          # built after it ended
        self.assertFalse(heartbeat.verdict(old, board, datetime(2026, 10, 18, 22, tzinfo=timezone.utc))["behind"])
        self.assertFalse(heartbeat.verdict("<p>no time</p>", board, monday)["behind"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
