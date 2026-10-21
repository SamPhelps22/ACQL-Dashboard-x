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


if __name__ == "__main__":
    unittest.main(verbosity=1)
