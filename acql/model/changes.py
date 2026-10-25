"""Why a game's chance moved (idea #23 of the upgrade book).

Between two moments a card's chance can move for two kinds of reason: the
betting line moved (news the market has priced), or something else did - a
newer predictions file, the moneyline on a straight-up game, the share of the
models' opinion, a typed spread. This splits the move into those two parts:

    line          today's price worked out again with the line as it stood then,
                  everything else as it is now; the difference is the line's doing
    the rest      what's left of the move between the chance kept then
                  (chancetrail.py, once an hour) and the chance now

The chance kept then is the card's own, so the two parts always add up to the
whole move. Nothing here changes a price; it re-asks pricing.py with one
number swapped. No Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from .. import analytics
from ..feeds import lines, odds
from ..models import Season, same_team
from . import pricing
from .predictions import display_team, team_code


@dataclass(frozen=True)
class Move:
    index: int
    matchup: str
    pick: str                    # the card's side now; every chance below is for it
    now: float
    then: float | None           # the card's chance kept at the earlier moment
    line_then: float | None      # the market's home margin then / now
    line_now: float | None
    line_part: float | None      # change in chance from the line alone
    rest_part: float | None      # everything else

    @property
    def total(self) -> float | None:
        return None if self.then is None else self.now - self.then


def _chance_for(game, margin: float, sd: float, side: str) -> float:
    said = analytics.predict_margin(game, margin, sd=sd)
    return said.chance if same_team(said.pick, side) else 1 - said.chance


def kept_at(week: int, when: float) -> tuple[float, dict[int, tuple[str, float]]] | None:
    """The card's chances as last kept at or before `when` (chancetrail)."""
    from ..pool import chancetrail
    best = None
    for at, row in chancetrail._kept(week):
        try:
            at = float(at)
        except (TypeError, ValueError):
            continue
        if at <= when and (best is None or at > best[0]):
            best = (at, row)
    if best is None:
        return None
    out = {}
    for k, v in best[1].items():
        if isinstance(v, list) and len(v) == 2:
            out[int(k)] = (str(v[0]), float(v[1]))
    return best[0], out


def moments(week: int, now: float | None = None) -> list[tuple[str, float]]:
    """The earlier moments worth comparing with: about a day ago, two days ago and
    the first line fetched this week - each only when something was kept by then."""
    from ..pool import chancetrail
    now = time.time() if now is None else now
    kept = [float(at) for at, _ in chancetrail._kept(week)]
    if not kept:
        return []
    first = min(kept)
    out = []
    for label, ago in (("About a day ago", 86400), ("Two days ago", 2 * 86400), ("Three days ago", 3 * 86400)):
        if now - ago >= first:
            out.append((label, now - ago))
    found = odds.stored(week)
    if found is not None and found.history:
        opening = min(at for at, _ in found.history)
        if opening >= first and all(abs(opening - t) > 3600 for _, t in out):
            out.append(("First line fetched this week", opening))
    out.append(("When the first chance was kept", first))
    return out


def explain(season: Season, week: int, since: float) -> list[Move]:
    """Every priced, unplayed game: its move since `since`, split in two."""
    found = season.weeks.get(week) if season is not None else None
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return []
    ctx = pricing.context(season, week, games)
    typed = lines.load_spreads(week, games)
    then_lines = odds.lines_at(week, since)
    kept = kept_at(week, since)
    then_chances = kept[1] if kept else {}
    out: list[Move] = []
    for game in games:
        if game.played:
            continue
        price = pricing.price(game, ctx, typed.get(game.index), typed=game.index in typed)
        if price.margin is None:
            continue
        said = price.prediction()
        pick = display_team(said.pick)
        now = said.chance
        key = f"{team_code(game.away)}@{team_code(game.home)}"
        line_then = then_lines.get(key)
        forecast = ctx.forecasts.get(game.index)
        line_part = None
        if line_then is not None and forecast is not None and not price.typed:
            swapped = replace(ctx, forecasts={**ctx.forecasts, game.index: replace(forecast, market=line_then)})
            old = pricing.price(game, swapped, typed.get(game.index), typed=False)
            if old.margin is not None:
                line_part = now - _chance_for(game, old.margin, old.sd, pick)
        then = None
        if game.index in then_chances:
            side, chance = then_chances[game.index]
            then = chance if same_team(side, pick) else 1 - chance
        rest = None if then is None or line_part is None else (now - then) - line_part
        out.append(Move(game.index, game.label, pick, now, then, line_then, price.base, line_part, rest))
    return out
