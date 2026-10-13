"""The record: every recipe's number, written down when the cards go in.

The Model Lab marks ten recipes against the season by replaying it - each
week priced again from what was kept at the time. That is fair as long as
the replay really is what each recipe would have said then, and nothing but
trust says so: a recipe's sums can change, a file can be read differently,
and the past quietly changes with them.

So once a week's odds have locked (oddslock.py) its games are written here,
each with the home margin every recipe expects, and never written again.
Each game says whether it was written before its own kickoff. A week first
written after its games had been played is still kept - it stops the past
moving from then on - but it is marked as that, and counts as a replay, not
as a record made at the time. A game whose kickoff time was not on file when
it was written says neither: the record claims "before kickoff" only where
it can show the kickoff it was before.

The cards are due little more than an hour before Thursday's kickoff, and in
a holiday week at the kickoff itself, so a computer asleep at the deadline
would write every week late. So in the two days before a week locks, each
run also keeps a draft of it. When the week is written for good, a game
whose numbers are the same as its draft's is dated from the draft: that
number was on file then, and has not moved. A game whose numbers moved after
the draft is dated from the writing, like any other.

Nothing reads the picks from here. The lab still replays, and `check` sets
its replay beside what was written: where the two differ, the page says so.

No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..feeds import oddslock, results
from ..models import Season

if TYPE_CHECKING:                       # the scheduled job's cheap look (due) must not load the whole lab
    from . import modellab
from .predictions import team_code

KIND = "ledger"
#: The week ahead as it stood on the way to its lock - replaced on each run, dropped for the record.
DRAFT = "ledger-draft"
#: A draft is kept from this long before a week locks.
DRAFT_AHEAD = 2 * 86400
#: A replayed number this far (points) from the one written down has changed.
TOLERANCE = 0.05
#: A week with nothing to write is not tried again for this long.
RETRY = 6 * 3600


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def kept(year: int, week: int) -> dict | None:
    """A week as it was written down: {"at", "lock", "version", "games": [...]}, or None."""
    try:
        from .. import store
        found = store.get(KIND, _key(year, week), None)
        return found if isinstance(found, dict) and found.get("games") else None
    except Exception:  # noqa: BLE001 - nothing kept is nothing kept
        return None


def due(year: int, now: float | None = None) -> bool:
    """A cheap look, without reading a spreadsheet: has a week's deadline
    passed with nothing written for it, and not been tried lately?"""
    from .. import store
    now = time.time() if now is None else now
    try:
        tried = float(store.get("headless", "ledger_tried", 0) or 0)
    except Exception:  # noqa: BLE001
        tried = 0.0
    if now - tried < RETRY:
        return False
    return any(oddslock.locked(year, week, now) and kept(year, week) is None
               for week in results.calendar_weeks(year, now))


def tried(now: float | None = None) -> None:
    """Note that the writing was attempted, so `due` leaves it alone for a while."""
    from .. import store
    try:
        store.put("headless", "ledger_tried", time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - bookkeeping only
        pass


def drafted(year: int, week: int) -> dict:
    """A week's draft, by game: {index: row}. Empty when there is none."""
    try:
        from .. import store
        found = store.get(DRAFT, _key(year, week), None)
        rows = found.get("games") if isinstance(found, dict) else None
        return {int(row["index"]): row for row in rows or () if isinstance(row, dict) and "index" in row}
    except Exception:  # noqa: BLE001 - no draft is no draft
        return {}


def _same(then: dict | None, now: dict) -> bool:
    """Two sets of recipe numbers for a game are the same: the same recipes, no number moved."""
    return (isinstance(then, dict) and set(then) == set(now)
            and all(isinstance(then[name], (int, float)) and abs(then[name] - now[name]) <= TOLERANCE
                    for name in now))


def keep(season: Season, now: float | None = None, numbers=None) -> list[int]:
    """Write down every locked week not written yet, and keep a draft of a week
    about to lock - its numbers are still moving, so the draft is replaced on
    each run and only dates the numbers that did not move again. Returns the
    weeks newly written for good."""
    from .. import store
    if numbers is None:
        from .modellab import week_numbers as numbers
    from ..version import VERSION
    now = time.time() if now is None else now
    year = results.season_year(season, now)
    done = []
    for number in sorted(season.weeks):
        games = sorted(season.weeks[number].games, key=lambda g: g.index)
        if not games or kept(year, number) is not None:
            continue
        locked = oddslock.locked_for(season, number, now)
        lock = oddslock.lock_time(year, number)
        if not locked and lock - now > DRAFT_AHEAD:
            continue
        found = numbers(season, number)
        scores = results.load(year, number)
        earlier = drafted(year, number)
        rows = []
        for game in games:
            margins = {name: round(float(margin), 4)
                       for name, margin in (found.get(game.index) or {}).items() if margin is not None}
            if not margins:
                continue
            score, _flipped = results.find(scores, game.away, game.home)
            kickoff = getattr(score, "kickoff", None) if score is not None else None
            road, home = team_code(game.away), team_code(game.home)
            # these numbers have been on file since the draft, if the draft says the same
            draft = earlier.get(game.index) or {}
            since = draft.get("at")
            held = (isinstance(since, (int, float)) and since < now and (draft.get("road"), draft.get("home"))
                    == (road, home) and _same(draft.get("margins"), margins))
            at = float(since) if held else now
            rows.append({
                "index": game.index, "road": road, "home": home,
                "kickoff": kickoff, "at": at,
                # written before the game began: nothing of its result could be in the
                # number. With no kickoff time on file that cannot be shown: None, not True.
                "before": (False if game.played and not held else
                           None if kickoff is None else at < kickoff),
                "margins": margins,
            })
        if not rows:
            continue
        try:
            if locked:
                store.put(KIND, _key(year, number), {"at": now, "lock": lock, "version": VERSION, "games": rows})
                done.append(number)
            else:
                store.put(DRAFT, _key(year, number), {"at": now, "games": rows})
        except store.StoreError:
            break
    return done


def written_before(row: dict) -> bool | None:
    """Whether a game was written down before its own kickoff: True, False, or
    None where no kickoff time was kept and so it cannot be said. (A game with
    no kickoff on file was once written as "before"; it is read here as None.)"""
    before = row.get("before")
    if before is None or (before and row.get("kickoff") is None):
        return None
    return bool(before)


# ---- the record beside today's replay ----------------------------------------------------------
@dataclass(frozen=True)
class Line:
    """One week as it was written down."""

    week: int
    at: float                   # when it was written: the last of its numbers to settle
    lock: float                 # when its odds locked
    version: str
    games: int
    before: int                 # games written before their own kickoff
    numbers: int = 0            # recipe numbers the lab has replayed since, on its graded games...
    changed: int = 0            # ...and how many of them no longer match what was written
    worst: str = ""             # the recipe furthest from its written number, if any moved
    unknown: int = 0            # games with no kickoff time on file: before or after cannot be said

    @property
    def standing(self) -> str:
        if self.before == self.games:
            return "written before kickoff"
        if self.unknown == self.games:
            return "kickoff times not known"
        if not self.before and not self.unknown:
            return "written after the games"
        return (f"{self.before} of {self.games} before kickoff"
                + (f" \u00b7 {self.unknown} not known" if self.unknown else ""))


@dataclass(frozen=True)
class Record:
    lines: tuple[Line, ...] = ()
    graded: int = 0             # the lab's graded games...
    at_the_time: int = 0        # ...and how many of them were written down before their kickoff
    unknown: int = 0            # ...and how many had no kickoff time on file, so cannot be counted either way

    @property
    def changed(self) -> int:
        return sum(line.changed for line in self.lines)


def check(lab: modellab.Lab, year: int) -> Record:
    """Every week written down, set beside the lab's replay of the same games."""
    lines, at_the_time, unknown = [], 0, 0
    try:
        from .. import store
        keys = store.items(KIND)
    except Exception:  # noqa: BLE001 - no record is an empty one
        keys = {}
    weeks = sorted(int(key.split("-")[1]) for key in keys if str(key).startswith(f"{int(year)}-"))
    for week in weeks:
        found = kept(year, week)
        if found is None:
            continue
        rows = [row for row in found["games"] if isinstance(row, dict)]
        numbers = changed = 0
        gaps: dict[str, float] = {}
        for row in rows:
            key = (week, int(row.get("index", -1)))
            if key not in lab.fixtures:
                continue
            at_the_time += written_before(row) is True
            unknown += written_before(row) is None
            written = row.get("margins") or {}
            for entry in lab.entries:
                play = entry.log.get(key)
                now, then = (play.margin if play is not None else None), written.get(entry.name)
                if now is None and then is None:
                    continue
                numbers += 1
                gap = abs(now - then) if now is not None and then is not None else float("inf")
                if gap > TOLERANCE:
                    changed += 1
                    gaps[entry.name] = max(gaps.get(entry.name, 0.0), gap)
        settled = [float(row["at"]) for row in rows if isinstance(row.get("at"), (int, float))]
        lines.append(Line(
            week, max(settled) if len(settled) == len(rows) and rows else float(found.get("at") or 0),
            float(found.get("lock") or 0), str(found.get("version") or ""),
            len(rows), sum(written_before(row) is True for row in rows), numbers, changed,
            max(gaps, key=gaps.get) if gaps else "",
            sum(written_before(row) is None for row in rows),
        ))
    return Record(tuple(lines), len(lab.fixtures), at_the_time, unknown)
