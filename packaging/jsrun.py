"""Run a little JavaScript in headless Chrome or Edge and get its answer back (#83).

The pool page's script has no test runner of its own and no Node: this puts
the code in a scratch page, runs it in the browser the release guard already
uses, and reads back what it left as JSON in the page title. Tests load the
page's own pieces (acql/ui/pool_page/*.js) and call their functions.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from guard import chrome


class NoBrowser(Exception):
    pass


def run(code: str, answer: str, *, browser: str | None = None, timeout: int = 90):
    """Run `code`, then `answer` (an expression); return the expression's value.
    Raises NoBrowser when there is no Chrome or Edge, RuntimeError on a script error."""
    browser = browser or chrome()
    if browser is None:
        raise NoBrowser("no Chrome or Edge")
    probe = ("<!doctype html><meta charset='utf-8'><title>probing</title><script>"
             "try {" + code + "\n;document.title = JSON.stringify({ok: (" + answer + ")});}"
             " catch (e) { document.title = JSON.stringify({error: e.name + ': ' + e.message}); }</script>")
    folder = Path(tempfile.mkdtemp(prefix="acql-js-"))
    try:
        (folder / "p.html").write_text(probe, encoding="utf-8")
        done = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                               f"--user-data-dir={folder / 'u'}", "--dump-dom", (folder / "p.html").as_uri()],
                              capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    title = re.search(rb"<title>(.*?)</title>", done.stdout, re.DOTALL)
    if not title or title.group(1) == b"probing":
        raise RuntimeError("the browser gave no answer")
    found = json.loads(html.unescape(title.group(1).decode("utf-8")))
    if "error" in found:
        raise RuntimeError(found["error"])
    return found["ok"]
