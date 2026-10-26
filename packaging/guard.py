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


#: Web pages whose inline scripts must at least parse: a script that doesn't
#: parse leaves the pool's website blank on every phone.
PAGES = ("acql/ui/pool_page.html",)
#: The pool page is kept as pieces (acql/ui/pool_page/*, joined in name order);
#: it is checked as the one page they make.
PARTS = "acql/ui/pool_page/"
MODE_PARTS = "acql/ui/pool_modes/"


def joined_pages(files: dict[str, bytes]) -> dict[str, bytes]:
    """Each page to parse: the whole files, and the pool page joined from its pieces."""
    out = {name: files[name] for name in PAGES if name in files}
    # the league modes' pieces (pool_modes/*.js) join in among them by name, as poolpage does
    pieces = sorted((n for n in files if (n.startswith(PARTS) and n[len(PARTS):][:3].isdigit() and n.endswith((".html", ".js")))
                     or (n.startswith(MODE_PARTS) and n[len(MODE_PARTS):][:3].isdigit() and n.endswith(".js"))),
                    key=lambda n: n.rsplit("/", 1)[-1])
    if pieces:
        out[PARTS.rstrip("/") + ".html (joined)"] = b"".join(files[n] for n in pieces)
    return out
#: Inline JavaScript only: a <script type="application/json"> data block is not code.
_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)(?![^>]*\btype=[\"']?(?!text/javascript|module)\w)[^>]*>(.*?)</script>",
                     re.DOTALL | re.IGNORECASE)


def chrome() -> str | None:
    """A Chrome or Edge to parse scripts with, or None."""
    import os
    import shutil
    for name in ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        for tail in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
            path = Path(base) / tail if base else None
            if path is not None and path.is_file():
                return str(path)
    return None


def script_problems(path: str, data: bytes, browser: str | None = None) -> list[str]:
    """Each inline script of a page, parsed (not run) by a real browser. [] when
    they all parse - or when there is no browser to ask, which is said on stdout."""
    import json
    import tempfile
    browser = browser or chrome()
    if browser is None:
        print(f"  (no Chrome or Edge found: {path}'s scripts not parsed)")
        return []
    scripts = [m.group(1).decode("utf-8", "replace") for m in _SCRIPT.finditer(data)]
    probe = ("<!doctype html><meta charset='utf-8'><title>probing</title><script>var out=[];"
             f"{json.dumps(scripts)}.forEach(function(s,i){{try{{new Function(s)}}catch(e){{"
             "out.push('script '+(i+1)+': '+e.name+': '+e.message)}});"
             "document.title=out.length?out.join(' | '):'PARSED';</script>")
    with tempfile.TemporaryDirectory() as folder:
        page = Path(folder) / "probe.html"
        page.write_text(probe, encoding="utf-8")
        try:
            done = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                                   f"--user-data-dir={Path(folder) / 'profile'}", "--dump-dom", page.as_uri()],
                                  capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  (the browser couldn't be run: {exc}; {path}'s scripts not parsed)")
            return []
    title = re.search(rb"<title>(.*?)</title>", done.stdout, re.DOTALL)
    word = title.group(1).decode("utf-8", "replace") if title else ""
    if word == "PARSED":
        return []
    if not word or word == "probing":
        print(f"  (the browser gave no answer; {path}'s scripts not parsed)")
        return []
    import html
    return [f"{path}: {html.unescape(part)}" for part in word.split(" | ")]


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
    files = tracked_files(args.commit)
    found = problems(files)
    if not found:          # a page full of conflict markers needs no browser to say so
        for page, data in joined_pages(files).items():
            found += script_problems(page, data)
    for line in found:
        print(f"  {line}")
    print(f"  Guard: {'FAILED, ' + str(len(found)) + ' problem(s)' if found else 'nothing wrong found'}.")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
