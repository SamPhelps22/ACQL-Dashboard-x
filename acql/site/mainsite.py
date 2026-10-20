"""The league's main site, and the one thing read from it: when picks are due.

The commissioner's page says, for the week coming up, something like
"Week 7  Enter Picks  (Due Thursday 6:30pm)". That time is Eastern, and it
is the pool's word on the deadline, so the website's countdown goes by it.
When the page can't be read, or doesn't say, the dashboard's own deadline
setting is used instead (poolpage._deadline).

Nothing here knows about Qt.
"""

from __future__ import annotations

import calendar
import html
import re
import time
import urllib.request
from datetime import date, datetime, timedelta

URL = "http://users.erols.com/merpdave/ACQL2007x.html"
TIMEOUT = 10
#: Read the page at most this often (seconds); the site is built many times a day.
KEEP = 30 * 60

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DUE = re.compile(
    r"week\s*(\d{1,2})\b.{0,200}?due\s*(?:on\s*)?(" + "|".join(_DAYS) + r"|mon|tue|wed|thu|fri|sat|sun)\w*\.?,?"
    r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m", re.I | re.S)

_cache: dict = {"at": 0.0, "found": None}


def page_text(raw: bytes) -> str:
    """The page's words, without its markup: the page is saved from Word."""
    text = raw.decode("cp1252", errors="replace")
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>|<!--.*?-->", " ", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text.replace("\xa0", " "))


def parse_due(text: str) -> tuple[int, int, int, int] | None:
    """(week, weekday with Monday 0, hour, minute) from "Week 7 ... Due Thursday 6:30pm"."""
    found = _DUE.search(text)
    if not found:
        return None
    week, day, hour, minute, half = found.groups()
    weekday = next(i for i, name in enumerate(_DAYS) if name.startswith(day.lower()[:3]))
    hour = int(hour) % 12 + (12 if half.lower() == "p" else 0)
    minute = int(minute or 0)
    if not (1 <= int(week) <= 22 and minute < 60):
        return None
    return int(week), weekday, hour, minute


def _nth_sunday(year: int, month: int, n: int) -> date:
    day = date(year, month, 1)
    day += timedelta(days=(6 - day.weekday()) % 7)
    return day + timedelta(weeks=n - 1)


def eastern(day: date, hour: int, minute: int) -> float:
    """Seconds since 1970 for a clock time in US Eastern, daylight saving
    included (second Sunday of March to the first Sunday of November)."""
    summer = _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)
    offset = 4 if summer else 5
    return calendar.timegm(datetime(day.year, day.month, day.day, hour, minute).timetuple()) + offset * 3600


def due(year: int, opener=None, now: float | None = None) -> dict | None:
    """{"week", "at"} (at in seconds) as the main site gives it, or None."""
    now = time.time() if now is None else now
    if opener is None and now - _cache["at"] < KEEP:
        return _cache["found"]
    found = None
    try:
        with (opener or urllib.request.urlopen)(URL, timeout=TIMEOUT) as reply:
            said = parse_due(page_text(reply.read()))
        if said:
            from ..feeds import results
            week, weekday, hour, minute = said
            day = results.wednesday(year, week) + timedelta(days=(weekday - 2) % 7)   # Wednesday is 2
            found = {"week": week, "at": eastern(day, hour, minute)}
    except Exception:  # noqa: BLE001 - no signal, a moved page: the dashboard's setting stands
        found = None
    if opener is None:
        _cache.update(at=now, found=found)
    return found
