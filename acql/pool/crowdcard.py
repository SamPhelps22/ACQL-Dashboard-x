"""The crowd forecast, graded (idea #32 of the upgrade book).

Before the commissioner's sheet arrives, every pool decision - the Big Loser
slots, the money card, Leverage - leans on crowd.py's guess of how the pool
will split on each game. This grades that guess, game by game, week by week,
against the sheet that came in.

Each week is predicted only from what was there before it: the sheets of the
earlier weeks (and older seasons'), never its own or a later one. Until
crowd.MINIMUM_GAMES of this season's games are in, the dashboard used the
usual curve instead, and so does this - it grades what the card would have
leaned on. The usual curve is graded beside it on every game, so the gain
from learning the pool's habits is plain.

Going forward the guess is also kept as it was made (`remember`, called when
the week is warmed and its sheet isn't in yet), so a week can be graded on
the very numbers the card used, not a rebuild. No Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..models import Season
from ..model.predictions import display_team, team_code
from . import crowd

KIND = "crowd-forecast"


@dataclass(frozen=True)
class Graded:
    week: int
    favourite: str
    underdog: str
    predicted: float            # share expected on the favourite
    usual: float                # the usual curve's share
    actual: float
    counted: int
    kept: bool                  # predicted from a guess kept before the sheet (not rebuilt)

    @property
    def miss(self) -> float:
        return abs(self.predicted - self.actual)

    @property
    def usual_miss(self) -> float:
        return abs(self.usual - self.actual)


@dataclass(frozen=True)
class Card:
    games: list[Graded]

    def weeks(self) -> list[int]:
        return sorted({g.week for g in self.games})

    def mean_miss(self, week: int | None = None) -> float | None:
        found = [g.miss for g in self.games if week is None or g.week == week]
        return sum(found) / len(found) if found else None

    def mean_usual(self, week: int | None = None) -> float | None:
        found = [g.usual_miss for g in self.games if week is None or g.week == week]
        return sum(found) / len(found) if found else None

    def worst(self, n: int = 5) -> list[Graded]:
        return sorted(self.games, key=lambda g: -g.miss)[:n]


def _key(o: crowd.Observation) -> str:
    return f"{team_code(o.situation.favourite)}|{team_code(o.situation.underdog)}"


def kept(week: int) -> dict[str, float]:
    """The guesses kept for a week before its sheet arrived: "fav|dog" -> share on the favourite."""
    from .. import store
    try:
        found = store.get(KIND, str(int(week)), {}) or {}
    except Exception:  # noqa: BLE001
        return {}
    shares = found.get("shares") if isinstance(found, dict) else None
    return {str(k): float(v) for k, v in (shares or {}).items()}


def remember(season: Season, week: int, *, now: float | None = None) -> bool:
    """Keep this week's crowd guesses, once, while its sheet isn't in. True when kept."""
    from .. import store
    from ..model import pricing
    from . import picks
    if kept(week):
        return False
    try:
        if picks.load(week) is not None:
            return False              # too late: the sheet is in
    except Exception:  # noqa: BLE001
        return False
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    margins = pricing.market_margins(week, games)
    learned = crowd.model(season)
    shares = {}
    for game in games:
        margin = margins.get(game.index)
        if margin is None:
            continue
        sit = crowd.situation(season, week, game, margin)
        share = learned.share_on_favourite(sit) if learned.games >= crowd.MINIMUM_GAMES else crowd.usual_share(sit)
        shares[f"{team_code(sit.favourite)}|{team_code(sit.underdog)}"] = round(share, 4)
    if not shares:
        return False
    store.put(KIND, str(int(week)), {"at": time.time() if now is None else now, "shares": shares})
    return True


def grade(season: Season, obs: list[crowd.Observation] | None = None,
          extra: list[crowd.Observation] | None = None) -> Card:
    """Every game on this season's sheets, graded against the guess made before it."""
    obs = crowd.observations(season) if obs is None else obs
    extra = crowd.older_sheets(season) if extra is None else extra
    out: list[Graded] = []
    for week in sorted({o.week for o in obs}):
        before = [o for o in obs if o.week < week]
        model = crowd.fit(before + list(extra))
        learned_enough = sum(1 for o in before) >= crowd.MINIMUM_GAMES
        guesses = kept(week)
        for o in obs:
            if o.week != week:
                continue
            usual = crowd.usual_share(o.situation)
            k = _key(o)
            if k in guesses:
                predicted, from_kept = guesses[k], True
            else:
                predicted = model.share_on_favourite(o.situation) if learned_enough else usual
                from_kept = False
            out.append(Graded(week, display_team(o.situation.favourite), display_team(o.situation.underdog),
                              predicted, usual, o.on_favourite, o.counted, from_kept))
    return Card(out)
