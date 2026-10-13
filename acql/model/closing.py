"""Closing line value: did the line move toward Deadeye's picks after they were in?

The surest test of a pick is not whether it won - one game is mostly luck -
but whether the market came round to it. A card is handed in on Thursday;
the games it covers kick off through Monday, and the line keeps moving on
news and money until each one starts. If the lines keep moving *toward* the
sides Deadeye took, it was seeing what the market saw later. If they keep
moving away, it wasn't.

The lines come free with the scores: ESPN's scoreboard carries each game's
spread until it kicks off, and the dashboard reads that scoreboard all week
anyway. Each game's line is kept here as a run of stretches - this number,
from then until then (results.save hands every reading over) - so each game
has the line as it stood at the pool's deadline and the last one before
kickoff, both from the same book: the difference is a real move, not two
books disagreeing.

Kept in the app's database; nothing here knows about Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..models import Season, same_team
from .predictions import team_code

KIND = "closing"
#: Stretches kept per game: a line rarely changes this many times in a week.
KEEP = 60
#: A move this small (points) is noise.
MOVE = 0.5
#: When the deadline line had to come from Deadeye's card rather than the
#: scoreboard (a week from before these were kept), two different books are
#: being compared: only a full point counts as a move.
MOVE_MIXED = 1.0


def _key(year: int, week: int) -> str:
    return f"{int(year)}-{int(week)}"


def _kept(year: int, week: int) -> dict:
    try:
        from .. import store
        found = store.get(KIND, _key(year, week), {})
        return found if isinstance(found, dict) else {}
    except Exception:  # noqa: BLE001 - nothing kept is nothing kept
        return {}


def capture(year: int, week: int, scores, now: float | None = None) -> int:
    """Keep the spread of every game that hasn't kicked off. Returns how many were read."""
    from .. import store
    now = time.time() if now is None else now
    kept = _kept(year, week)
    read = 0
    for s in scores:
        spread = getattr(s, "home_spread", None)
        kickoff = getattr(s, "kickoff", None)
        if spread is None or getattr(s, "state", "pre") != "pre" or (kickoff and kickoff <= now):
            continue
        entry = kept.setdefault(f"{s.away}@{s.home}", {"kickoff": kickoff, "runs": []})
        entry["kickoff"] = kickoff
        runs = entry.setdefault("runs", [])
        if runs and float(runs[-1][2]) == float(spread):
            runs[-1][1] = now                    # the same number, still standing
        else:
            runs.append([now, now, float(spread)])
        del runs[:-KEEP]
        read += 1
    if read:
        try:
            store.put(KIND, _key(year, week), kept)
        except store.StoreError:
            pass
    return read


def lines(year: int, week: int) -> dict[frozenset, dict]:
    """{the two teams: {"home": code, "kickoff": t, "runs": [(from, until, home margin), ...]}}."""
    out = {}
    for key, entry in _kept(year, week).items():
        away, _, home = key.partition("@")
        runs = [(float(a), float(b), float(m)) for a, b, m in entry.get("runs") or []]
        if home and away and runs:
            out[frozenset((away, home))] = {"home": home, "kickoff": entry.get("kickoff"), "runs": runs}
    return out


@dataclass(frozen=True)
class PickValue:
    week: int
    matchup: str
    pick: str
    then: float             # the line when the card went in, from the pick's side
    close: float            # the last line before kickoff, from the pick's side
    mixed: bool             # `then` came from the card, not the scoreboard

    @property
    def moved(self) -> float:
        """Points the line moved toward the pick (negative: away from it)."""
        return self.close - self.then

    @property
    def verdict(self) -> int:
        need = MOVE_MIXED if self.mixed else MOVE
        return 1 if self.moved >= need else -1 if self.moved <= -need else 0


@dataclass(frozen=True)
class Value:
    picks: list[PickValue]

    @property
    def toward(self) -> int:
        return sum(1 for p in self.picks if p.verdict > 0)

    @property
    def away(self) -> int:
        return sum(1 for p in self.picks if p.verdict < 0)

    @property
    def points(self) -> float:
        """Average points of movement toward the picks, over every pick measured."""
        return sum(p.moved for p in self.picks) / len(self.picks) if self.picks else 0.0

    @property
    def weeks(self) -> list[int]:
        return sorted({p.week for p in self.picks})


def value(season: Season, year: int | None = None) -> Value:
    """Every pick on Deadeye's kept cards whose line was read after the deadline."""
    from ..pool import cards
    from ..feeds import oddslock, results
    year = year or results.season_year(season)
    out: list[PickValue] = []
    for number in sorted(season.weeks):
        snap = cards.model(number)
        if snap is None or snap.rebuilt:
            continue                    # a card made after the fact knew how the lines ended
        week = season.weeks[number]
        snap = cards.aligned(snap, cards._slate(week.games))
        kept = lines(year, number)
        lock = oddslock.lock_time(year, number)
        for game in week.games:
            side = (snap.plain or snap.take).get(game.index)
            entry = kept.get(frozenset((team_code(game.home), team_code(game.away))))
            if not side or entry is None:
                continue
            runs = entry["runs"]
            if runs[-1][1] < lock:
                continue                # never read between the deadline and the kickoff
            flip = entry["home"] != team_code(game.home)          # a neutral site, the other way round
            turn = (lambda m: -m) if flip else (lambda m: m)
            close = turn(runs[-1][2])
            standing = [m for start, _end, m in runs if start <= lock]
            if standing:
                then, mixed = turn(standing[-1]), False
            elif game.index in snap.margin:
                then, mixed = float(snap.margin[game.index]), True
            else:
                continue
            sign = 1.0 if same_team(side, game.home) else -1.0
            out.append(PickValue(number, game.label, side, sign * then, sign * close, mixed))
    return Value(out)
