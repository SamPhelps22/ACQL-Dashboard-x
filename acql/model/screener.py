"""The slate screener (idea #1 of the upgrade book): every game of the week in one grid.

Each column is a number another page already works out - the card's chance,
the market's own chance for the same side, the share of the pool expected on
it, how far the pool's line sits from the market, how far the market must move
to turn the pick, the likeliest Big Loser in the game, how hard it is to call,
the weather and the quarterbacks' injury news. Laid side by side they can be
sorted and filtered like a stock screener, so "what needs a look before the
deadline" is one click.

Nothing here prices anything its own way: the chances are pricing.py's, the
hard score radar.py's, the flips flips.py's. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import analytics
from ..feeds import lines, results
from ..models import Season, same_team
from . import flips, luck, pricing, radar
from .predictions import display_team, team_code


@dataclass(frozen=True)
class Row:
    index: int
    matchup: str
    away: str
    home: str
    pick: str
    chance: float                  # the card's chance of being credited (Deadeye)
    market: float | None           # the betting line's own chance for the same side
    crowd: float | None            # share of the pool expected (or counted) on the pick
    counted: bool                  # crowd counted off the week's pick sheet
    pool_line: str                 # "BAL −3" or ""
    pool_gap: float | None         # market minus pool line for the pool's favourite (+: pool too short)
    flip: float | None             # points of market move that turn the pick
    loser: str                     # the side likelier to lose by 15+
    loser_chance: float
    hard: float                    # 0-100 (radar)
    weather: str                   # "" or the forecast in words, when it matters
    injuries: str                  # quarterback news, both sides, or ""
    flags: tuple[str, ...] = ()

    @property
    def edge(self) -> float | None:
        """Deadeye's chance minus the market's for the same side (points of 0..1)."""
        return None if self.market is None else self.chance - self.market

    @property
    def lean(self) -> float | None:
        """How far the pool leans past the card's chance: + the pool likes the pick more than it should."""
        return None if self.crowd is None else self.crowd - self.chance


@dataclass(frozen=True)
class Screen:
    week: int
    rows: list[Row]
    sheet: bool                    # the week's pick sheet is in


#: The filters the page offers, each a test on a row.
FILTERS = {
    "all": ("Every game", lambda r: True),
    "toss": ("Toss-ups (under 55%)", lambda r: r.chance < 0.55),
    "fragile": ("Could flip (1.5 pts or less)", lambda r: r.flip is not None and r.flip <= 1.5),
    "pool_gap": ("Pool line off the market by 1+", lambda r: r.pool_gap is not None and abs(r.pool_gap) >= 1.0),
    "herd": ("Pool leaning 15+ past the chance", lambda r: r.lean is not None and r.lean >= 0.15),
    "against": ("Card differs from the market's side", lambda r: r.market is not None and r.market < 0.5),
    "loser": ("Big Loser 20%+", lambda r: r.loser_chance >= 0.20),
    "news": ("Weather or quarterback news", lambda r: bool(r.weather or r.injuries)),
}


def _qb_news(code: str) -> str:
    try:
        from ..feeds import injuries
        said = injuries.summary(code, most=1)
    except Exception:  # noqa: BLE001 - the screener stands without the report
        return ""
    return said if said.startswith("QB") else ""


def _sky(year: int, week: int, away: str, home: str) -> str:
    try:
        from ..feeds import weather
        found = weather.game(year, week, away, home)
    except Exception:  # noqa: BLE001
        return ""
    return found.words() if found is not None and found.notable else ""


def build(season: Season, week: int | None = None, *, sky=None, qb=None) -> Screen:
    """The week's unplayed, priced games, one row each, in slate order.

    `sky` and `qb` stand in for the weather and injury look-ups (tests)."""
    week = analytics.upcoming_week(season) if week is None else week
    found = season.weeks.get(week) if season is not None else None
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return Screen(week or 0, [], False)
    sky = sky or _sky
    qb = qb or _qb_news
    year = results.season_year(season)
    ctx = pricing.context(season, week, games)
    prices = {p.game.index: p for p in pricing.price_week(season, week, games, ctx)}
    shapes = {s.index: s for s in radar.build(season, week).games}
    try:
        turns = {f.index: f for f in flips.week_flips(season, week)}
    except Exception:  # noqa: BLE001
        turns = {}
    try:
        gaps = {g.index: g for g in flips.pool_gaps(season, week)}
    except Exception:  # noqa: BLE001
        gaps = {}
    try:
        from ..pool import picks
        sheet = picks.load(week)
    except Exception:  # noqa: BLE001
        sheet = None
    chalk = analytics.pool_chalk(season)[0]

    rows: list[Row] = []
    for game in games:
        price, shape = prices.get(game.index), shapes.get(game.index)
        if price is None or shape is None or price.margin is None:
            continue
        pick = shape.pick
        market = None if price.base is None else luck.credited_chance(game, price.base, pick)
        spread = price.spread or (lines.Spread("home" if price.base >= 0 else "away", abs(price.base))
                                  if price.base is not None else None)
        try:
            crowd = pricing.crowd_share(season, week, game, pick, spread, sheet, chalk)
        except Exception:  # noqa: BLE001
            crowd = None
        counted = bool(sheet is not None and sheet.game_for(game.away, game.home) is not None)
        gap = gaps.get(game.index)
        pool_line = (f"{display_team(game.line_favourite)} −{game.line:g}"
                     if game.line is not None and game.line_favourite else "")
        home_loses = analytics.big_loser_chance(price.margin, price.sd)
        away_loses = analytics.big_loser_chance(-price.margin, price.sd)
        loser, loser_chance = ((game.home, home_loses) if home_loses >= away_loses else (game.away, away_loses))
        news = "; ".join(f"{team_code(t).upper()} {said}" for t in (game.away, game.home) if (said := qb(team_code(t))))
        turn = turns.get(game.index)
        rows.append(Row(
            index=game.index, matchup=game.label, away=display_team(game.away), home=display_team(game.home),
            pick=pick, chance=shape.chance, market=market, crowd=crowd, counted=counted,
            pool_line=pool_line, pool_gap=None if gap is None else gap.gap,
            flip=None if turn is None else turn.distance,
            loser=display_team(loser), loser_chance=loser_chance, hard=shape.hard,
            weather=sky(year, week, game.away, game.home), injuries=news, flags=shape.flags,
        ))
    return Screen(week, rows, sheet is not None)


def filtered(screen: Screen, key: str) -> list[Row]:
    test = FILTERS.get(key, FILTERS["all"])[1]
    return [r for r in screen.rows if test(r)]


def same_side(row: Row, team: str) -> bool:
    return same_team(row.pick, team)
