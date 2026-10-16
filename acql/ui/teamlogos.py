"""NFL team logos, for showing beside team names.

The logos come from ESPN's image server - the same place the live scores
come from - and are kept in the data folder after the first download, so
the dashboard only goes online for them once. Until a logo is on disk (or
when there is no connection) nothing is shown and the team name stands on
its own, exactly as before.
"""

from __future__ import annotations

import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from ..model.predictions import DISPLAY, team_code
from ..store import data_dir

URL = "https://a.espncdn.com/i/teamlogos/nfl/500/{code}.png"
#: Where ESPN's code differs from ours.
ESPN_CODES = {"was": "wsh"}

_fetching = threading.Lock()
_started = False
#: Every way a table writes a team, lower case, to its code.
_NAMES = {name.lower(): code for code, name in DISPLAY.items()}


def folder() -> Path:
    return data_dir() / "logos"


def path(code: str) -> Path:
    return folder() / f"{code}.png"


def fetch_all() -> None:
    """Download any logo not yet on disk, in the background. Safe to call
    more than once; only the first call does anything."""
    global _started
    with _fetching:
        if _started:
            return
        _started = True
    threading.Thread(target=_download, name="team-logos", daemon=True).start()


def _download() -> None:
    try:
        folder().mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for code in DISPLAY:
        target = path(code)
        if target.is_file() and target.stat().st_size:
            continue
        try:
            request = urllib.request.Request(URL.format(code=ESPN_CODES.get(code, code)),
                                             headers={"User-Agent": "ACQL Dashboard"})
            with urllib.request.urlopen(request, timeout=10) as reply:
                body = reply.read()
            if body:
                part = target.with_suffix(".part")
                part.write_bytes(body)
                part.replace(target)
        except Exception:  # noqa: BLE001 - offline is fine: the name stands alone
            continue
    icon.cache_clear()


def code_in(text: object) -> str:
    """The team a table cell is about, or "".

    Matches a cell that is a team's name ("Dallas"), or starts with one and
    goes on with a line or a score ("Dallas by 3", "Dallas 24-17"). Anything
    else - a player's name, a sentence - is left alone.
    """
    words = str(text or "").strip()
    if not words:
        return ""
    lower = words.lower()
    if lower in _NAMES:
        return _NAMES[lower]
    for name, code in _NAMES.items():
        if lower.startswith(name + " "):
            rest = lower[len(name) + 1:]
            if rest.startswith("by ") or rest[:1].isdigit() or rest[:1] == "(":
                return code
    return ""


@lru_cache(maxsize=64)
def icon(code: str) -> QIcon | None:
    """The team's logo as an icon, or None when it isn't on disk yet."""
    code = team_code(code) or code
    file = path(code) if code else None
    if file is None or not file.is_file():
        return None
    pixmap = QPixmap(str(file))
    return None if pixmap.isNull() else QIcon(pixmap)


def pixmap(team: object, size: int) -> QPixmap | None:
    """The team's logo at `size` pixels square, or None."""
    found = icon(team_code(team))
    return found.pixmap(size, size) if found is not None else None
