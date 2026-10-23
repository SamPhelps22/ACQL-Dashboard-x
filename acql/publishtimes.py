"""When each source publishes a week (idea #100), and whether next week's lines are up (#65).

Two things the fetch timing was guessing at:

* lines_posted(year, week) - ESPN's scoreboard (free) shows a game's spread
  once the books have posted it. Before a week has any market number, the
  nightly run asks that first, and spends an Odds API request only once the
  lines are there - and straight away when they appear on Sunday night,
  rather than up to twelve hours later.
* note / window - the first time each week's predictions file covers the
  week, and the first time its lines show, are written down; after a few
  weeks that gives each source's usual window ("Tue 10 am-1 pm"), which
  Readiness shows.

No Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

KIND = "publish-times"
#: ESPN is asked about a week with no lines at most this often.
ASK_EVERY = 3600
NAMES = {"predictions": "The predictions file", "lines": "Next week's lines"}


def note(source: str, week: int, year: int, at: float | None = None) -> bool:
    """Write down the first time a source had a week. True the first time."""
    from . import store
    at = time.time() if at is None else at
    key = f"{source}-{int(year)}"
    try:
        kept = store.get(KIND, key, {}) or {}
        if str(week) in kept:
            return False
        kept[str(week)] = at
        store.put(KIND, key, kept)
    except Exception:  # noqa: BLE001
        return False
    return True


@dataclass(frozen=True)
class Window:
    source: str
    weeks: int
    weekday: str          # the most common day, "Tue"
    start: float          # earliest hour that day (local, 0-24)
    end: float

    def words(self) -> str:
        def hour(h: float) -> str:
            hh, mm = int(h), int(round((h - int(h)) * 60))
            suffix = "am" if hh < 12 else "pm"
            hh12 = hh % 12 or 12
            return f"{hh12}{':%02d' % mm if mm else ''} {suffix}"
        return f"usually {self.weekday} {hour(self.start)}-{hour(self.end)} ({self.weeks} weeks seen)"


def window(source: str, year: int) -> Window | None:
    """The source's usual day and hours, from the weeks seen so far (3 or more)."""
    from . import store
    try:
        kept = store.get(KIND, f"{source}-{int(year)}", {}) or {}
    except Exception:  # noqa: BLE001
        return None
    stamps = [time.localtime(float(v)) for v in kept.values()]
    if len(stamps) < 3:
        return None
    days = [time.strftime("%a", t) for t in stamps]
    common = max(set(days), key=days.count)
    hours = [t.tm_hour + t.tm_min / 60 for t, d in zip(stamps, days) if d == common]
    return Window(source, len(stamps), common, min(hours), max(hours))


def lines_posted(year: int, week: int, now: float | None = None, fetch=None) -> bool | None:
    """Whether ESPN's scoreboard shows spreads for the week: True, False, or None (couldn't ask).
    Asks ESPN (free) at most once an hour per week; the answer is noted when lines first appear."""
    from . import store
    from .feeds import results
    now = time.time() if now is None else now
    scores = results.load(year, week)
    if any(s.home_spread is not None for s in scores):
        note("lines", week, year, now)
        return True
    key = f"asked-{int(year)}-{int(week)}"
    try:
        asked = float(store.get(KIND, key, 0) or 0)
    except Exception:  # noqa: BLE001
        asked = 0.0
    if now - asked < ASK_EVERY:
        return False
    try:
        store.put(KIND, key, now)
        scores = (fetch or results.fetch)(year, week)
        if scores:
            results.save(year, week, scores, now)
    except Exception:  # noqa: BLE001
        return None
    posted = any(s.home_spread is not None for s in scores)
    if posted:
        note("lines", week, year, now)
    return posted
