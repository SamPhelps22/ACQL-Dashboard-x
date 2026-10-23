"""Where each pick's chance stood about a day ago (idea #9, ghost marks).

Change is the signal: a chance that moved from 55% to 61% since yesterday is
worth a second look before the deadline. This keeps the card's chances once
an hour while the week is open and, for each game, gives the value from
about a day before - shown faintly beside today's.

No Qt.
"""

from __future__ import annotations

import time

KIND = "chance-trail"
EVERY = 3600
#: "About a day ago": the newest record at least this old...
AGO = 20 * 3600
#: ...and no older than this.
OLDEST = 48 * 3600
#: A move smaller than this isn't shown.
SHOWN = 0.03
KEEP = 200


def _kept(week: int) -> list:
    from .. import store
    try:
        found = store.get(KIND, str(int(week)), []) or []
    except Exception:  # noqa: BLE001
        return []
    return found if isinstance(found, list) else []


def record(week: int, chances: dict[int, tuple[str, float]], now: float | None = None) -> bool:
    """Keep the card's (side, chance) per game if the last record is an hour old. True when kept."""
    from .. import store
    now = time.time() if now is None else now
    kept = _kept(week)
    if kept and now - float(kept[-1][0]) < EVERY:
        return False
    kept = (kept + [[now, {str(k): [str(side), round(float(c), 4)] for k, (side, c) in chances.items()}]])[-KEEP:]
    try:
        store.put(KIND, str(int(week)), kept)
    except Exception:  # noqa: BLE001
        return False
    return True


def day_ago(week: int, now: float | None = None) -> tuple[float, dict[int, tuple[str, float]]] | None:
    """(when, {game: (side, chance)}) from about a day ago, or None."""
    now = time.time() if now is None else now
    fit = [(float(at), row) for at, row in _kept(week) if AGO <= now - float(at) <= OLDEST]
    if not fit:
        return None
    at, row = fit[-1]
    out = {}
    for k, v in row.items():
        if isinstance(v, list) and len(v) == 2:
            out[int(k)] = (str(v[0]), float(v[1]))
    return at, out


def ghosts(week: int, chances: dict[int, tuple[str, float]], now: float | None = None) -> dict[int, float]:
    """{game: this side's chance a day ago} for the picks that moved by SHOWN or more.
    A pick that changed side is compared for the same team (1 - the old side's chance)."""
    from ..model.predictions import team_code
    then = day_ago(week, now)
    if then is None:
        return {}
    _at, old = then
    out = {}
    for i, (side, chance) in chances.items():
        if i not in old:
            continue
        old_side, old_chance = old[i]
        was = old_chance if team_code(old_side) == team_code(side) else 1 - old_chance
        if abs(chance - was) >= SHOWN:
            out[i] = was
    return out
