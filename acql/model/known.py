"""What was known before the deadline, written down each week and never rewritten.

A model can only be tested honestly on what it could have known at the time.
The lines are already kept as they move (odds.py, closing.py) and Deadeye's
card as it stood (cards.py); what was not kept was everything else about a
game on the day the cards went in - who was on the injury report and whether
the quarterback was, how many days each side had rested, the forecast, each
team's record and ratings going in. A week later the injury report has moved
on and none of it can be had again.

So this writes the week's scouting reports (scouting.py - the same gathering
the scouting window shows) into the database: over and over while the week is
still open, so it holds the latest, and for the last time at the pool's
deadline. After that the week is frozen. Nothing reads these yet: they are
the record a football model of the dashboard's own - one that knows about
injuries and rest, not only scores - will be taught and tested on, with no
hindsight in it.

No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import asdict

from ..models import Season

KIND = "known"
#: A week still open is written again no more often than this...
EVERY = 3600
#: ...except close to the deadline, when the late news lands.
CLOSE = 3 * 3600


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def kept(year: int, week: int) -> dict | None:
    """A week as it was written down: {"at", "frozen", "games": {game number: its report}}."""
    try:
        from .. import store
        found = store.get(KIND, _key(year, week), None)
        return found if isinstance(found, dict) and found.get("games") else None
    except Exception:  # noqa: BLE001 - nothing kept is nothing kept
        return None


def snapshot(season: Season, week: int) -> dict[str, dict]:
    """Every priced, unplayed game of a week as its scouting report, by game number."""
    from . import radar, scouting
    out = {}
    for shape in radar.build(season, week).games:
        report = scouting.report(season, shape.index, week)
        if report is not None:
            kept = asdict(report)
            kept.pop("twins", None)         # derived from the archive, not something known that week
            out[str(shape.index)] = kept
    return out


def keep(season: Season, year: int, week: int, lock: float, now: float | None = None, build=snapshot) -> str:
    """Write the week down if it is still open and due; freeze it once the
    deadline has passed. Returns what was done: "kept", "frozen", "fresh"
    (written recently enough), "closed" (already frozen, or the deadline
    passed with nothing written - it is not written with hindsight)."""
    from .. import store
    now = time.time() if now is None else now
    found = kept(year, week)
    if found is not None and found.get("frozen"):
        return "closed"
    if now >= lock:
        if found is None:
            return "closed"
        store.put(KIND, _key(year, week), {**found, "frozen": True, "frozen_at": now})
        return "frozen"
    age = now - float(found.get("at") or 0) if found is not None else None
    if age is not None and age < EVERY and lock - now > CLOSE:
        return "fresh"
    games = build(season, week)
    if not games:
        return "fresh"
    store.put(KIND, _key(year, week), {"at": now, "frozen": False, "games": games})
    return "kept"
