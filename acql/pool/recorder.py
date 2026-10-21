"""The game-day flight recorder: the week as it looked at each live look.

The scores are kept (results.py) and the week can be replayed from its
scoring plays (site/replay.py), but what the screen *said* during the games -
your chance of finishing first at 2:40 pm, the place you were in - was never
written down. Without it, the live model (gameday.outlook, scaled by the time
left) can't be checked against how weeks actually ended, and a Sunday can't
be looked back on as it felt.

So each look while games are on adds a point - only when something changed -
to one record per week: the time, each game's state and score, and your
chance, place and running total. Small (about 30 points a game day). No Qt.
"""

from __future__ import annotations

import time

KIND = "live-trace"
#: A week keeps at most this many points; the oldest are dropped past it.
MOST = 600
#: A chance that moved less than this (and no score) is not a new point.
NOISE = 0.005


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def trace(year: int, week: int) -> list[dict]:
    from .. import store
    try:
        found = store.get(KIND, _key(year, week), [])
    except Exception:  # noqa: BLE001
        return []
    return found if isinstance(found, list) else []


def point(bd, now: float) -> dict:
    """One look, as the screen had it."""
    you = bd.you
    return {
        "at": round(now, 1),
        "games": [[s.index, s.state, s.home_points, s.away_points, round(s.left, 3)] for s in bd.states],
        "chance": None if you is None or you.chance is None else round(you.chance, 4),
        "place": None if you is None else you.place,
        "now": None if you is None else you.total_now,
    }


def record(season, week: int, you: str = "", now: float | None = None, board=None) -> bool:
    """Add a point for the week if a game is on and something changed. True when one was added."""
    from .. import store
    from ..feeds import results
    from . import gameday
    now = time.time() if now is None else now
    bd = board if board is not None else gameday.board(season, week, you)
    if bd is None or not bd.live:
        return False
    year = results.season_year(season)
    kept = trace(year, week)
    new = point(bd, now)
    if kept:
        last = kept[-1]
        same_games = last.get("games") == new["games"]
        moved = (last.get("chance") is None) != (new["chance"] is None) or (
            new["chance"] is not None and abs(new["chance"] - last["chance"]) >= NOISE)
        if same_games and not moved:
            return False
    kept.append(new)
    try:
        store.put(KIND, _key(year, week), kept[-MOST:])
    except Exception:  # noqa: BLE001 - a lost point is never a broken look
        return False
    return True
