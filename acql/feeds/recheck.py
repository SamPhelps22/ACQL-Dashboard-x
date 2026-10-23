"""Final scores, checked again after the whistle (idea #17).

Once a game is kept as final, results.save never changes it - a later look
can't lose a final. That also means a stat correction made after the game
(a scoring change, a late penalty ruled differently) would never reach the
dashboard, and a correction can change who the pool credits. So each final
is asked about again twice, 15 minutes and 12 hours after it was first seen
final, and a changed score replaces the kept one and is written down with
its before and after.

The scoreboard is free (no odds budget). Nothing here knows about Qt.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace

from . import results

KIND = "recheck"
#: When a final is asked about again, seconds after it was first seen final.
AFTER = (15 * 60, 12 * 3600)
#: A game is taken to have ended this long after kickoff, when it was already
#: final the first time it was seen here.
GAME_S = int(3.5 * 3600)


@dataclass(frozen=True)
class Correction:
    year: int
    week: int
    game: str                  # "AWAY @ HOME", the pool's codes
    before: tuple[int, int]    # (away, home) as kept
    after: tuple[int, int]
    at: float

    def text(self) -> str:
        return (f"Week {self.week} {self.game}: final score corrected from {self.before[0]}-{self.before[1]} "
                f"to {self.after[0]}-{self.after[1]}")


def _pair(s: results.Score) -> str:
    return f"{s.away}@{s.home}"


def _kept(year: int, week: int) -> dict:
    from .. import store
    try:
        found = store.get(KIND, f"{int(year)}-{int(week)}", {})
    except Exception:  # noqa: BLE001
        return {}
    return found if isinstance(found, dict) else {}


def _put(year: int, week: int, state: dict) -> None:
    from .. import store
    try:
        store.put(KIND, f"{int(year)}-{int(week)}", state)
    except Exception:  # noqa: BLE001
        pass


def _track(year: int, week: int, now: float) -> dict:
    """Each kept final with when it was first seen final and which re-checks are done."""
    state = _kept(year, week)
    games = dict(state.get("games") or {})
    for s in results.load(year, week):
        if not s.final or s.away_points is None or s.home_points is None:
            continue
        if _pair(s) not in games:
            seen = now
            if s.kickoff and now - s.kickoff > GAME_S + AFTER[-1]:
                seen = s.kickoff + GAME_S          # long over before it was first seen here
            games[_pair(s)] = {"final_at": seen, "done": 0}
    state["games"] = games
    return state


def due(year: int, weeks, now: float | None = None) -> bool:
    """Is any kept final owed a re-check now?"""
    now = time.time() if now is None else now
    for week in weeks:
        for entry in _track(year, week, now)["games"].values():
            done = int(entry.get("done", 0))
            if done < len(AFTER) and now >= float(entry["final_at"]) + AFTER[done]:
                return True
    return False


def run(year: int, week: int, now: float | None = None, fetch=None) -> list[Correction]:
    """Re-check a week's finals that are due; keep any corrected score. The corrections made."""
    from .. import store
    now = time.time() if now is None else now
    state = _track(year, week, now)
    games = state["games"]
    owed = [p for p, e in games.items()
            if int(e.get("done", 0)) < len(AFTER) and now >= float(e["final_at"]) + AFTER[int(e.get("done", 0))]]
    if not owed:
        _put(year, week, state)
        return []
    fresh = {_pair(s): s for s in (fetch or results.fetch)(year, week)}
    kept = results.load(year, week)
    made, changed = [], False
    for i, s in enumerate(kept):
        p = _pair(s)
        if p not in owed:
            continue
        games[p]["done"] = int(games[p].get("done", 0)) + 1
        new = fresh.get(p)
        if new is None or not new.final or new.away_points is None or new.home_points is None:
            continue
        if (new.away_points, new.home_points) != (s.away_points, s.home_points):
            made.append(Correction(year, week, f"{s.away.upper()} @ {s.home.upper()}",
                                   (s.away_points, s.home_points), (new.away_points, new.home_points), now))
            kept[i] = replace(s, away_points=new.away_points, home_points=new.home_points, detail=new.detail)
            changed = True
    if changed:
        raw = results._stored(year, week)
        raw["scores"] = [asdict(s) for s in kept]
        try:
            store.put(results.KIND, results._key(year, week), raw)
        except Exception:  # noqa: BLE001
            made = []
    state["corrections"] = list(state.get("corrections") or []) + [
        {"game": c.game, "before": list(c.before), "after": list(c.after), "at": c.at} for c in made]
    _put(year, week, state)
    return made


def corrections(year: int, weeks) -> list[Correction]:
    """Every correction kept for these weeks, oldest first."""
    out = []
    for week in weeks:
        for c in _kept(year, week).get("corrections") or []:
            try:
                out.append(Correction(year, week, c["game"], tuple(c["before"]), tuple(c["after"]), float(c["at"])))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out, key=lambda c: c.at)
