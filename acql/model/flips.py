"""How far each pick is from changing: the line at which it would flip.

A pick is a side and a chance. What it doesn't say is how close it is to
being the other side. A 56% pick on a straight-up game with a 2-point
favourite flips if the market moves two points; a 56% pick against a pool
line can flip on half a point, because the pool's line is fixed and the
market's isn't. Between Tuesday's lines and Thursday's deadline the market
moves on injury news, so the picks worth looking at again are the ones
whose flip point is near.

The flip point is found on the pricing's own rule (pricing.price,
analytics.predict_margin): the expected margin at which the pick's chance
crosses one half, carried back to the betting line with everything else -
the models' share, the spread of results - held as it is. Display only:
nothing here changes a pick.

Also here, for lined games: the gap between the commissioner's pool line and
the market's number for the same favourite (pool_gaps), which is where a
pick'em pool's lines go stale and where the card finds most of its value.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import analytics
from ..models import Game

#: Within this many points of flipping, a pick is called fragile.
FRAGILE = 1.0
#: The margins NFL games land on most: crossing one matters more than its size.
KEY_NUMBERS = (3, 7)


@dataclass(frozen=True)
class Flip:
    index: int
    matchup: str
    pick: str
    chance: float
    market: float | None        # the market's home margin now
    flip_market: float | None   # the market's home margin at which the pick changes
    distance: float | None      # points of market move to get there (None: can't flip on the line)
    side_after: str = ""

    @property
    def fragile(self) -> bool:
        return self.distance is not None and self.distance <= FRAGILE

    @property
    def crosses_key(self) -> bool:
        if self.market is None or self.flip_market is None:
            return False
        low, high = sorted((self.market, self.flip_market))
        return any(low < k < high or low < -k < high for k in KEY_NUMBERS)

    def flips_at(self, home: str, away: str) -> str:
        """"Chicago −2.5" - the line the pick turns at."""
        if self.flip_market is None:
            return ""
        return _line_text(self.flip_market, home, away)


def _line_text(home_margin: float, home: str, away: str) -> str:
    value = round(home_margin * 2) / 2
    if abs(value) < 0.25:
        return "pick 'em"
    team = home if value > 0 else away
    return f"{team} −{abs(value):g}"


def _pick_at(game: Game, margin: float, sd: float) -> str | None:
    found = analytics.predict_margin(game, margin, sd=sd)
    if found is None or found.chance <= 0.5 + 1e-9 and found.reason == "pick 'em":
        return None
    return found.pick


def flip_margin(game: Game, margin: float, sd: float) -> float | None:
    """The expected home margin, nearest `margin`, at which the pick changes side."""
    now = _pick_at(game, margin, sd)
    if now is None:
        return None
    best = None
    for direction in (1, -1):
        low, high = 0.0, None
        step = 0.5
        reach = 0.0
        while reach < 30:
            reach += step
            if _pick_at(game, margin + direction * reach, sd) not in (now,):
                high = reach
                break
            low = reach
        if high is None:
            continue
        for _ in range(25):
            mid = (low + high) / 2
            if _pick_at(game, margin + direction * mid, sd) == now:
                low = mid
            else:
                high = mid
        if best is None or high < abs(best - margin):
            best = margin + direction * high
    return best


def week_flips(season, week: int) -> list[Flip]:
    """Every unplayed, priced game of a week: its pick and where it would turn."""
    from . import pricing
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    games = [g for g in games if not g.played]
    if not games:
        return []
    ctx = pricing.context(season, week, games)
    out = []
    for price in pricing.price_week(season, week, games, ctx):
        guess = price.prediction()
        if guess is None or price.margin is None:
            continue
        at = flip_margin(price.game, price.margin, price.sd)
        market = price.base
        flip_market = None if at is None or market is None else market + (at - price.margin)
        # just past the flip point (beyond the pick 'em band on a straight-up game)
        after = (_pick_at(price.game, at + (0.5 if at > price.margin else -0.5), price.sd)
                 if at is not None else None)
        out.append(Flip(price.game.index, price.game.label, guess.pick, guess.chance, market, flip_market,
                        None if at is None else abs(at - price.margin), after or ""))
    return out


@dataclass(frozen=True)
class PoolGap:
    index: int
    matchup: str
    favourite: str          # the pool's favourite
    pool_line: float        # what the favourite must cover
    need: int               # the whole points that takes (analytics.line_need)
    market: float | None    # the market's number for that favourite (positive: favoured)
    gap: float | None       # market minus pool line: + the favourite is underpriced by the pool
    pick: str
    chance: float
    crowd_on_favourite: float | None

    @property
    def side_with_value(self) -> str:
        if self.gap is None or abs(self.gap) < 0.25:
            return ""
        return "favourite" if self.gap > 0 else "underdog"

    @property
    def crosses_key(self) -> bool:
        if self.market is None:
            return False
        low, high = sorted((self.market, self.pool_line))
        return any(low < k < high for k in KEY_NUMBERS)


def pool_gaps(season, week: int) -> list[PoolGap]:
    """The week's lined games, widest gap between pool line and market first."""
    from . import pricing
    from .predictions import team_code
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    games = [g for g in games if not g.played and g.line is not None]
    if not games:
        return []
    every = sorted(found.games, key=lambda g: g.index)
    ctx = pricing.context(season, week, every)
    chalk = analytics.pool_chalk(season)[0]
    out = []
    for price in pricing.price_week(season, week, every, ctx):
        g = price.game
        if g.played or g.line is None:
            continue
        guess = price.prediction()
        fav_home = team_code(g.line_favourite) == team_code(g.home)
        market = None if price.base is None else (price.base if fav_home else -price.base)
        out.append(PoolGap(g.index, g.label, g.line_favourite, g.line, analytics.line_need(g.line), market,
                           None if market is None else market - g.line,
                           guess.pick if guess else "", guess.chance if guess else 0.5, chalk))
    return sorted(out, key=lambda p: -(abs(p.gap) if p.gap is not None else -1))
