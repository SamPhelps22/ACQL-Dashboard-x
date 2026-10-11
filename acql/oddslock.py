"""The odds lock: each week's numbers stop moving when the pool's cards are due.

Cards are due at the commissioner's deadline - Thursday, 6:00 pm on this
computer's clock - or at the week's first kickoff when that comes sooner
(Thanksgiving, a Wednesday opener). A line that moves after that can't change
a card already handed in, so it doesn't change Deadeye's either.

From then on the week's betting lines, the chances built on them and
Deadeye's card stay as they stood: no fetched line, newer predictions file or
typed spread changes them, and the week is priced with the share of the
models' opinion fitted on the weeks before it (pricing.model_weight), so its
own results coming in can't move it either. Deadeye is held to the card it
had when the games began, and the report card grades that card.

The first kickoff is the NFL's own, off its scoreboard: the app reads the
fixtures of the week being played and the one after it by itself
(results.calendar_weeks), so a week that opens on a Wednesday, or on
Thanksgiving afternoon, locks when its first game starts. Until the
scoreboard has been read for a week - no internet, say - the usual first
kickoff stands in: Thursday 8:15 pm Eastern, 12:30 pm on Thanksgiving. And a
week with a result in is locked whatever the clock says.
"""

from __future__ import annotations

import calendar
import time
from datetime import date, timedelta

#: When the pool's cards are due, on this computer's own clock: the weekday
#: (Monday is 0, so Thursday is 3), the hour and the minute. The commissioner's
#: usual deadline; a different one can be kept in the database under
#: settings / deadline as {"weekday": 3, "hour": 18, "minute": 0}.
DEADLINE = (3, 18, 0)
#: When a week's first game usually starts, Eastern time: Thursday night.
USUAL_KICKOFF = (20, 15)
#: Thanksgiving's first game, Eastern time.
THANKSGIVING_KICKOFF = (12, 30)
#: Christmas Day's first game, Eastern time, when it falls before Thursday night.
CHRISTMAS_KICKOFF = (13, 0)

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _nth(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th given weekday of a month (Monday is 0, Sunday 6)."""
    day = date(year, month, 1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day + timedelta(weeks=n - 1)


def _eastern_hours(day: date) -> int:
    """How many hours the US east coast is behind UTC on a day: four in summer
    time (the second Sunday of March to the first Sunday of November), five
    otherwise. Worked out here rather than looked up, because Windows has no
    time-zone tables for Python to read."""
    summer = _nth(day.year, 3, 6, 2) <= day < _nth(day.year, 11, 6, 1)
    return 4 if summer else 5


def thursday(year: int, week: int) -> date:
    """The Thursday of a week of the NFL season."""
    from . import results
    return results.wednesday(year, week) + timedelta(days=1)


def usual_kickoff(year: int, week: int) -> float:
    """When a week's first game usually starts (seconds since 1970): Thursday
    night, Thanksgiving's early game, or Christmas afternoon when Christmas
    falls on the Wednesday or the Thursday. (A week 18 with no Thursday game
    locks early by this; the fixtures, once read, put that right.)"""
    day = thursday(year, week)
    christmas = date(day.year, 12, 25)
    hour, minute = USUAL_KICKOFF
    if day == _nth(day.year, 11, 3, 4):
        hour, minute = THANKSGIVING_KICKOFF
    elif christmas in (day - timedelta(days=1), day):
        day, (hour, minute) = christmas, CHRISTMAS_KICKOFF
    return float(calendar.timegm(
        (day.year, day.month, day.day, hour + _eastern_hours(day), minute, 0, 0, 0, 0)
    ))


def first_kickoff(year: int, week: int) -> float | None:
    """The week's first kickoff by the NFL's scoreboard, as last read - None
    until it has been. A postponed game doesn't count: the week starts with
    the first game actually played."""
    from . import results
    times = [s.kickoff for s in results.load(year, week) if s.kickoff and not s.called_off]
    return min(times) if times else None


def deadline_clock() -> tuple[int, int, int]:
    """(weekday, hour, minute) the cards are due: the one kept, or the usual."""
    try:
        from . import store
        kept = store.get("settings", "deadline", None)
        if isinstance(kept, dict):
            weekday = int(kept.get("weekday", DEADLINE[0]))
            hour, minute = int(kept.get("hour", DEADLINE[1])), int(kept.get("minute", DEADLINE[2]))
            if 0 <= weekday <= 6 and 0 <= hour <= 23 and 0 <= minute <= 59:
                return weekday, hour, minute
    except Exception:  # noqa: BLE001 - an unreadable setting is the usual deadline
        pass
    return DEADLINE


def deadline(year: int, week: int) -> float:
    """When a week's cards are due (seconds since 1970), on this computer's clock."""
    from . import results
    weekday, hour, minute = deadline_clock()
    day = results.wednesday(year, week) + timedelta(days=(weekday - 2) % 7)   # Wednesday is 2
    return time.mktime((day.year, day.month, day.day, hour, minute, 0, 0, 0, -1))


def kickoff_time(year: int, week: int) -> float:
    """The week's first kickoff: the scoreboard's, or the usual one until it is read."""
    found = first_kickoff(year, week)
    return found if found is not None else usual_kickoff(year, week)


def at_deadline(year: int, week: int) -> bool:
    """Whether the week locks at the pool's deadline rather than at a kickoff before it."""
    return deadline(year, week) <= kickoff_time(year, week)


def lock_time(year: int, week: int) -> float:
    """When a week's odds lock (seconds since 1970): the pool's deadline, or
    the first kickoff when that comes sooner."""
    return min(deadline(year, week), kickoff_time(year, week))


def locked(year: int, week: int, now: float | None = None) -> bool:
    """Whether a week's cards are in: past the deadline, or the first kickoff."""
    if not year or not week:
        return False
    return (time.time() if now is None else now) >= lock_time(year, week)


def _played(season, week: int) -> bool:
    weeks = getattr(season, "weeks", None)
    found = weeks.get(week) if isinstance(weeks, dict) else None
    games = getattr(found, "games", None)
    return isinstance(games, list) and any(getattr(g, "played", False) for g in games)


def locked_for(season, week: int, now: float | None = None) -> bool:
    """Whether a week of this season is locked: kicked off, or with a result in."""
    from . import results
    if not week:
        return False
    return _played(season, week) or locked(results.season_year(season, now), week, now)


def when(year: int, week: int) -> str:
    """"Thu Oct 8, 7:15 PM" - the lock on this computer's own clock."""
    at = time.localtime(lock_time(year, week))
    hour = at.tm_hour % 12 or 12
    return (f"{_DAYS[at.tm_wday]} {_MONTHS[at.tm_mon - 1]} {at.tm_mday}, "
            f"{hour}:{at.tm_min:02d} {'AM' if at.tm_hour < 12 else 'PM'}")


def note(season, week: int, now: float | None = None) -> str:
    """One line for a page showing a locked week ("" while it's open)."""
    from . import results
    from .version import MODEL_NAME
    if not locked_for(season, week, now):
        return ""
    year = results.season_year(season, now)
    if locked(year, week, now):
        return (f"Week {week}'s odds locked at {_what(year, week)} ({when(year, week)}): the lines, "
                f"the chances and {MODEL_NAME}'s card stay as they were then.")
    return (f"Week {week}'s odds are locked - a game has a result in, so the lines, the "
            f"chances and {MODEL_NAME}'s card stay as they are.")


def badge(season, week: int, now: float | None = None) -> str:
    """A few words for a crowded line ("" while the week is open)."""
    from . import results
    if not locked_for(season, week, now):
        return ""
    year = results.season_year(season, now)
    if locked(year, week, now):
        return (f"\N{LOCK} odds locked at {'the deadline' if at_deadline(year, week) else 'kickoff'}, "
                f"{when(year, week)}")
    return "\N{LOCK} odds locked - a game has a result in"


def coming(season, week: int, now: float | None = None) -> str:
    """When an open week's odds will lock, for the page ("" once they have)."""
    from . import results
    if not week or locked_for(season, week, now):
        return ""
    year = results.season_year(season, now)
    left = _left(lock_time(year, week) - (time.time() if now is None else now))
    if at_deadline(year, week):
        return f"Cards are due {when(year, week)} ({left}) - the odds lock then."
    if first_kickoff(year, week) is not None:
        usual = ""
    elif results.unreachable_since(now) is not None:
        usual = " (the usual time - the NFL's schedule can't be reached right now, so it can't be checked)"
    else:
        usual = " (the usual time - the schedule isn't in yet)"
    return f"Odds lock at the first kickoff, {when(year, week)}{usual} ({left})."


def _what(year: int, week: int) -> str:
    return "the pool's deadline" if at_deadline(year, week) else "the first kickoff"


def _left(seconds: float) -> str:
    """"in 2 days", "in 3 h 20 min", "in 12 min"."""
    minutes = max(0, int(seconds // 60))
    if minutes >= 2 * 1440:
        return f"in {minutes // 1440} days"
    if minutes >= 60:
        return f"in {minutes // 60} h {minutes % 60:02d} min"
    return f"in {minutes} min"
