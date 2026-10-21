#!/usr/bin/env python3
"""Refuse to ship a tree that is visibly broken.

    python packaging/guard.py                 check every tracked file in the working folder
    python packaging/guard.py --commit HEAD   check the files as they were committed

Two things have gone out broken before: a merge left its conflict markers in
acql/ui/pool_page.html (the public website went blank) and in the tests (a
syntax error). Both are caught here, along with any Python file that does not
compile. packaging/release.py runs this before it writes anything, and the
tests workflow runs it on every push.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A merge's own lines: seven angle brackets then a space or the end of the line.
MARKER = re.compile(rb"^(<{7}|>{7})(?: |\r?$)", re.MULTILINE)
CHECKED = (".py", ".html", ".md", ".txt", ".yml", ".yaml", ".json", ".bat", ".ps1", ".toml", ".cfg")
SKIPPED = ("updates/", ".venv/")


def git(*args: str, cwd: Path = ROOT) -> bytes:
    done = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=str(cwd), capture_output=True)
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def problems(files: dict[str, bytes]) -> list[str]:
    """What is wrong with these files (path -> bytes), one line each. Empty means fine."""
    found = []
    for path in sorted(files):
        data = files[path]
        if not path.endswith(CHECKED) or path.startswith(SKIPPED):
            continue
        marker = MARKER.search(data)
        if marker:
            line = data.count(b"\n", 0, marker.start()) + 1
            found.append(f"{path}:{line}: leftover merge conflict marker")
        if path.endswith(".py"):
            try:
                compile(data, path, "exec", dont_inherit=True)
            except (SyntaxError, ValueError) as exc:
                found.append(f"{path}: does not compile ({exc})")
    return found


def tracked_files(commit: str = "") -> dict[str, bytes]:
    names = [n for n in git("ls-tree" if commit else "ls-files", *(["-r", "--name-only", commit] if commit else []),
                            "-z").decode("utf-8").split("\0") if n]
    files = {}
    for name in names:
        if commit:
            files[name] = git("show", f"{commit}:{name}")
        else:
            path = ROOT / name
            if path.is_file():
                files[name] = path.read_bytes()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", default="", help="check the files as committed there, not the working folder")
    args = parser.parse_args()
    found = problems(tracked_files(args.commit))
    for line in found:
        print(f"  {line}")
    print(f"  Guard: {'FAILED, ' + str(len(found)) + ' problem(s)' if found else 'nothing wrong found'}.")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
