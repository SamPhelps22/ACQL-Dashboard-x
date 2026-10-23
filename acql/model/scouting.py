"""A scouting report for one game: everything the dashboard knows about it, in one place.

The card says who; "why each pick" says why in a line or two. This is the
whole file on a matchup - both teams' seasons (record, scoring and defence
ranked against the league, the market's rating and the dashboard's own), who
is hurt, the weather, the betting line, the projected score, the pick and how
sure it is, the three things that weigh most on it, and what would have to
happen for it to be wrong - with a short written plan on top that says the
same in sentences.

Nothing here is new information: it is the same season, lines, injuries and
signals the card is built from, gathered around one game. A strength is a
top-eight rank in the league, a weakness a bottom-eight one; with a few
games played those ranks are noisy, and the report says how many they rest on.

No Qt here: ui/scouting.py lays it out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from .. import analytics
from . import evidence, pricing, radar
from ..feeds import results
from ..models import Game, Season, same_team
from .predictions import display_team, team_code
from ..version import MODEL_NAME

#: A rank this good (or this bad, from the other end) is a strength (a weakness).
TOP = 8
#: An underdog winning outright this often is worth saying under "what could go wrong".
LIVE_DOG = 0.30


@dataclass(frozen=True)
class Side:
    """One team going into the game."""

    team: str
    code: str
    home: bool
    record: str = "0-0"
    games: int = 0
    scored: float = 0.0         # points a game
    allowed: float = 0.0
    scored_rank: int = 0        # 1 = most in the league; 0 = not ranked yet
    allowed_rank: int = 0       # 1 = fewest
    last: str = ""              # "beat Baltimore 31-10"
    market: float | None = None     # points better than an average team, by the betting market
    market_rank: int = 0
    own: float | None = None        # ...and by the dashboard's own ratings
    hurt: tuple[str, ...] = ()      # "QB Joe Smith out (ankle)", the missing first
    missing: int = 0                # of those, not expected to play
    quarterback: str = ""           # the quarterback's line, when he is on the report
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    week: int
    index: int
    matchup: str
    kickoff: str                    # "Sun Oct 18, 1:00 PM" or ""
    home: Side
    away: Side
    pick: str
    chance: float
    tier: str
    pool_line: str                  # "Buffalo by 7" or ""
    line: str                       # the betting line as written: "Buffalo -6.5"
    total: float | None
    favourite: str
    margin: float                   # Deadeye's margin for that favourite
    score: tuple[int, int] | None   # projected (home, away) points
    upset: float
    close: float
    rout: float
    hard: float
    factors: tuple[evidence.Signal, ...] = ()       # the three that weigh most
    also: tuple[evidence.Signal, ...] = ()          # the rest of what is known
    risks: tuple[str, ...] = ()
    weather: str = ""
    plan: str = ""
    made: str = ""                  # how the number was made, step by step (evidence.Case.made)
    steps: tuple = ()               # the margin's arithmetic (waterfall.steps), home side
    twins: object = None            # the most alike past games and how they ended (twins.Twins)
    twin_favourite: str = ""        # the side the line favours, which the twins are read for

    @property
    def score_text(self) -> str:
        if self.score is None:
            return ""
        home, away = self.score
        return f"{self.home.team} {home}, {self.away.team} {away}"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _line_text(game: Game, home_margin: float | None) -> str:
    if home_margin is None:
        return ""
    if abs(home_margin) < analytics.PICK_EM:
        return "pick'em"
    side = game.home if home_margin > 0 else game.away
    return f"{display_team(side)} −{abs(home_margin):g}"


def projected_score(home_margin: float, total: float | None) -> tuple[int, int] | None:
    """(home, away) points from the expected margin and the over/under. None without a total."""
    if not total:
        return None
    home, away = (total + home_margin) / 2, (total - home_margin) / 2
    home_pts, away_pts = max(0, round(home)), max(0, round(away))
    if home_pts == away_pts and abs(home_margin) >= analytics.PICK_EM:      # a tie nobody is predicting
        if home_margin > 0:
            home_pts += 1
        else:
            away_pts += 1
    return home_pts, away_pts


def _sides(season: Season, week: int, game: Game) -> tuple[Side, Side]:
    year = results.season_year(season)
    forms = evidence.season_form(year, week)
    by_scored = sorted(forms, key=lambda c: -(forms[c].scored / max(1, forms[c].games)))
    by_allowed = sorted(forms, key=lambda c: forms[c].allowed / max(1, forms[c].games))
    try:
        from . import power
        ranks = power.rankings(season)
    except Exception:  # noqa: BLE001 - the report stands without the ratings
        ranks = None
    try:
        from ..feeds import injuries
    except Exception:  # noqa: BLE001
        injuries = None
    teams = len(forms) or 32

    def side(name: str, home: bool) -> Side:
        code = team_code(name)
        form = forms.get(code)
        rank = ranks.team(code) if ranks is not None else None
        listed = []
        if injuries is not None:
            try:
                listed = sorted(injuries.team(code), key=lambda i: (not i.quarterback, not i.missing))
            except Exception:  # noqa: BLE001
                listed = []
        games = form.games if form else 0
        scored = form.scored / games if games else 0.0
        allowed = form.allowed / games if games else 0.0
        s_rank = by_scored.index(code) + 1 if code in by_scored else 0
        a_rank = by_allowed.index(code) + 1 if code in by_allowed else 0
        passer = next((i for i in listed if i.quarterback), None)
        good, bad = [], []
        if s_rank and s_rank <= TOP:
            good.append(f"scoring: {scored:.1f} a game, {_ordinal(s_rank)} of {teams}")
        if s_rank and s_rank > teams - TOP:
            bad.append(f"scoring: {scored:.1f} a game, {_ordinal(s_rank)} of {teams}")
        if a_rank and a_rank <= TOP:
            good.append(f"defence: {allowed:.1f} allowed a game, {_ordinal(a_rank)} fewest")
        if a_rank and a_rank > teams - TOP:
            bad.append(f"defence: {allowed:.1f} allowed a game, {_ordinal(a_rank)} fewest of {teams}")
        if rank is not None and rank.rank <= TOP:
            good.append(f"the market rates them {_ordinal(rank.rank)}, {rank.rating:+.1f} points on an average team")
        if rank is not None and rank.rank > len(ranks.teams) - TOP:
            bad.append(f"the market rates them {_ordinal(rank.rank)} of {len(ranks.teams)}, {rank.rating:+.1f} points")
        if passer is not None and passer.missing:
            bad.append(f"quarterback: {passer.words()}")
        missing = sum(1 for i in listed if i.missing)
        if missing >= 4:
            bad.append(f"{missing} players not expected to play")
        return Side(
            team=display_team(name), code=code, home=home,
            record=form.record if form else "0-0", games=games, scored=scored, allowed=allowed,
            scored_rank=s_rank, allowed_rank=a_rank, last=form.last if form else "",
            market=rank.rating if rank is not None else None, market_rank=rank.rank if rank is not None else 0,
            own=rank.own if rank is not None else None,
            hurt=tuple(i.words() for i in listed), missing=missing,
            quarterback=passer.words() if passer is not None else "",
            strengths=tuple(good), weaknesses=tuple(bad),
        )

    return side(game.home, True), side(game.away, False)


def _risks(shape: radar.Shape, case, home: Side, away: Side, game: Game) -> list[str]:
    """What would have to happen for the pick to be wrong, likeliest first."""
    out = []
    if game.line is not None and game.line_favourite and same_team(shape.pick, game.line_favourite):
        out.append(f"{shape.pick} wins but by fewer than the pool's {game.line:g} - the pick is only "
                   f"credited {shape.chance:.0%} of the time")
    elif same_team(shape.pick, shape.favourite) and shape.upset >= LIVE_DOG:
        out.append(f"{shape.underdog} simply wins: about {shape.upset:.0%} of games like this go to the underdog")
    elif not same_team(shape.pick, shape.favourite):
        out.append(f"{shape.favourite} covers: the pick is the side getting points, and is credited {shape.chance:.0%} of the time")
    if shape.close >= 0.27:
        out.append(f"a one-score finish - {shape.close:.0%} of games like this are decided by three or fewer")
    picked = home if same_team(shape.pick, home.team) else away
    if picked.quarterback:
        out.append(f"{picked.team}'s quarterback is on the injury report: {picked.quarterback}")
    out.extend(shape.flags)
    if case is not None:
        out.extend(s.headline for s in case.signals if s.verdict == evidence.AGAINST)
    seen, kept = set(), []
    for line in out:
        if line and line not in seen:
            seen.add(line)
            kept.append(line)
    return kept


def _plan(r: Report) -> str:
    """The report in a few sentences."""
    parts = [f"The card takes {r.pick} at {r.chance:.0%} - a {r.tier.lower()}."]
    number = f"{MODEL_NAME} makes it {r.favourite} by {r.margin:.1f}"
    if r.line:
        number += f"; the betting line is {r.line}"
    if r.pool_line:
        number += f", and the pool's line is {r.pool_line}"
    parts.append(number + ".")
    if r.score is not None:
        parts.append(f"Projected: {r.score_text}.")
    lead = next((s for s in r.factors if s.verdict == evidence.FOR), None)
    if lead is not None:
        parts.append(f"The strongest thing for it is the {lead.name.lower()}: {lead.headline}.")
    edge = []
    for side, other in ((r.home, r.away), (r.away, r.home)):
        if side.scored_rank and other.allowed_rank and side.scored_rank <= TOP and other.allowed_rank > 32 - TOP:
            edge.append(f"{side.team}'s scoring ({_ordinal(side.scored_rank)}) against {other.team}'s defence "
                        f"({_ordinal(other.allowed_rank)} fewest allowed)")
    if edge:
        parts.append("The mismatch: " + "; ".join(edge) + ".")
    if r.risks:
        parts.append(f"The likeliest way it goes wrong: {r.risks[0]}.")
    return " ".join(parts)


_KEPT: dict[tuple, dict] = {}


def _cases(season: Season, week: int, me: str | None) -> dict[int, object]:
    """Game index -> its evidence.Case, built once per set of lines (it takes a second)."""
    from ..pool import briefing
    from . import predictions
    key = (id(season), week, predictions.market_time(week), me)
    if key not in _KEPT:
        _KEPT.clear()
        try:
            brief = briefing.build(season, week)
            _KEPT[key] = {c.index: c for c in evidence.build(season, brief, me)} if brief is not None else {}
        except Exception:  # noqa: BLE001 - the report stands on the numbers alone
            _KEPT[key] = {}
    return _KEPT[key]


def _twins(game, week: int, price, total):
    """The 30 most alike games since 2011 (twins.py), read for the line's favourite."""
    if price.base is None:
        return None
    try:
        from . import autopsy, twins
        return twins.find(abs(price.base), total, week, 0.0, autopsy.same_division(game.home, game.away))
    except Exception:  # noqa: BLE001 - the report shows without it
        return None


def _steps(game, ctx, price) -> list:
    try:
        from . import waterfall
        return waterfall.steps(game, ctx, price)
    except Exception:  # noqa: BLE001 - the report shows without it
        return []


def report(season: Season, index: int, week: int | None = None, me: str | None = None) -> Report | None:
    """The scouting report for one unplayed game of the week ahead, or None if it isn't priced."""
    slate = radar.build(season, week)
    shape = next((g for g in slate.games if g.index == index), None)
    found = season.weeks.get(slate.week)
    game = next((g for g in found.games if g.index == index), None) if found is not None else None
    if shape is None or game is None:
        return None
    year = results.season_year(season)
    ctx = pricing.context(season, slate.week, sorted(found.games, key=lambda g: g.index))
    forecast = ctx.forecasts.get(index)
    price = pricing.price(game, ctx, pricing.stored_spread(slate.week, game),
                          typed=pricing.stored_spread(slate.week, game) is not None)
    total = getattr(forecast, "total", None) or None
    home, away = _sides(season, slate.week, game)
    case = _cases(season, slate.week, me).get(index)
    signals = list(case.signals) if case is not None else []
    weighing = [s for s in signals if s.verdict != evidence.INFO] + [s for s in signals if s.verdict == evidence.INFO]
    kickoff = evidence._kickoff(year, slate.week, game)
    sky = ""
    try:
        from ..feeds import weather
        forecast_sky = weather.game(year, slate.week, game.away, game.home)
        if forecast_sky is not None:
            sky = forecast_sky.words()
        elif weather.indoors(year, slate.week, game.away, game.home):
            sky = "indoors"
    except Exception:  # noqa: BLE001
        sky = ""
    made = Report(
        week=slate.week, index=index, matchup=game.label,
        kickoff=time.strftime("%a %b %d, %I:%M %p", time.localtime(kickoff)).replace(" 0", " ") if kickoff else "",
        home=home, away=away, pick=shape.pick, chance=shape.chance, tier=evidence.strength(shape.chance),
        pool_line=f"{display_team(game.line_favourite)} by {game.line:g}" if game.line is not None and game.line_favourite else "",
        line=_line_text(game, price.base), total=total, favourite=shape.favourite, margin=shape.margin,
        score=projected_score(price.margin, total) if price.margin is not None else None,
        upset=shape.upset, close=shape.close, rout=shape.rout, hard=shape.hard,
        factors=tuple(weighing[:3]), also=tuple(weighing[3:]),
        risks=tuple(_risks(shape, case, home, away, game)), weather=sky,
        made=case.made() if case is not None and hasattr(case, "made") else "",
        steps=tuple(_steps(game, ctx, price)),
        twins=_twins(game, slate.week, price, total),
        twin_favourite=(display_team(game.home) if (price.base or 0) >= 0 else display_team(game.away))
        if price.base is not None else "",
    )
    return replace(made, plan=_plan(made))
