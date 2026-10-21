"""Do the sources agree with each other?

Freshness (readiness.py) says whether each input is recent. It cannot say
whether an input is right. On 2026-10-18 the week-7 record said "Chicago
-6.5" beside a moneyline that made Chicago 54% to win: a 6.5-point favourite
wins about seven times in ten, so both could not be true - the line had come
from a 2024 archive file. No single source looked stale; only the two side by
side gave it away.

So these checks set numbers that describe the same thing against each other:

    line vs moneyline      the chance the spread implies against the chance the
                           moneylines imply (they come from different feeds)
    line vs total          a spread wider than most of the expected points, or
                           a total no NFL game is priced at
    pool line vs market    the commissioner's line far from the betting line -
                           usually a typo, or the sides the wrong way round
    where the file came    a week's numbers read from a file that the gate
    from                   (predictions.refusal) would turn away today
    the week's record      the open "known before kickoff" record against the
                           numbers now, and whether it is complete

Display only: nothing here changes a number, blocks a run or picks a side.
No Qt here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Chance points between what the line implies and what the moneylines imply
#: before the two are called inconsistent. Books shade moneylines and the
#: feeds update at different times, so a few points apart is normal; the
#: 2026-10-18 case was 17 apart.
MONEYLINE_GAP = 0.12
#: Spread as a share of the total: a 40-point total with a 30-point spread is
#: a 35-5 game, which no book prices.
SPREAD_SHARE_OF_TOTAL = 0.6
TOTAL_RANGE = (28.0, 66.0)
#: Points between the pool line and the market before it looks like a slip.
POOL_LINE_GAP = 4.5
#: Points between the open record's line and the line now before the record
#: is called out of date.
RECORD_GAP = 2.0


@dataclass(frozen=True)
class Problem:
    kind: str       # "moneyline" | "total" | "pool line" | "source" | "record"
    game: str       # "New England @ Chicago", or "" for the whole week
    text: str


def _number(text: object) -> float | None:
    found = re.search(r"([+\-−]?\d+(?:\.\d+)?)\s*$", str(text or ""))
    if not found:
        return None
    return float(found.group(1).replace("−", "-"))


def week(season, week_number: int) -> list[Problem]:
    """Every disagreement between sources for one week's unplayed games."""
    from . import analytics
    from .model import predictions, pricing
    found = season.weeks.get(week_number)
    games = sorted(found.games, key=lambda g: g.index) if found is not None else []
    games = [g for g in games if not g.played]
    if not games:
        return []
    out: list[Problem] = []
    forecasts, source = predictions.load(week_number)
    if source and not str(source).startswith(("betting lines", "pasted", "typed")):
        try:
            from pathlib import Path
            if Path(source).exists():
                refused = predictions.refusal(source)
                if refused:
                    out.append(Problem("source", "", f"Week {week_number}'s numbers were read from "
                                       f"{Path(source).name}, which isn't one week's file ({refused})"))
        except OSError:
            pass
    ctx = pricing.context(season, week_number, games, forecasts) if forecasts else None
    by_game = ctx.forecasts if ctx is not None else {}
    for g in games:
        f = by_game.get(g.index)
        if f is None or f.market is None:
            continue
        label = g.label
        if f.market_win is not None:
            implied = analytics.win_chance(f.market)        # f.market: points in the file's home side's favour
            gap = abs(implied - f.market_win)
            if gap > MONEYLINE_GAP:
                home_fav = f.market >= 0
                fav = f.home if home_fav else f.road
                by_line = implied if home_fav else 1 - implied
                by_money = f.market_win if home_fav else 1 - f.market_win
                out.append(Problem("moneyline", label,
                                   f"{fav} by {abs(f.market):g} implies {by_line:.0%} to win, "
                                   f"but the moneylines say {by_money:.0%}"))
        if f.total:
            if not TOTAL_RANGE[0] <= f.total <= TOTAL_RANGE[1]:
                out.append(Problem("total", label, f"a total of {f.total:g} points is outside any NFL price"))
            elif abs(f.market) > f.total * SPREAD_SHARE_OF_TOTAL:
                out.append(Problem("total", label,
                                   f"a {abs(f.market):g}-point spread with a total of only {f.total:g}"))
        if g.line is not None and g.line_favourite:
            fav_home = predictions.team_code(g.line_favourite) == predictions.team_code(f.home)
            market_for_fav = f.market if fav_home else -f.market
            if abs(market_for_fav - g.line) > POOL_LINE_GAP:
                out.append(Problem("pool line", label,
                                   f"pool line {g.line_favourite} by {g.line:g}, but the market has them "
                                   f"{'favoured' if market_for_fav >= 0 else 'the underdog'} by {abs(market_for_fav):g}"))
    out.extend(record(season, week_number, games, by_game))
    return out


def record(season, week_number: int, games, by_game) -> list[Problem]:
    """The open "known before kickoff" record against the numbers now, and its completeness."""
    from .feeds import results
    from .model import known, predictions
    kept = known.kept(results.season_year(season), week_number)
    if kept is None or kept.get("frozen"):
        return []
    out: list[Problem] = []
    stored = kept.get("games") or {}
    for g in games:
        entry = stored.get(str(g.index))
        f = by_game.get(g.index)
        if entry is None or f is None or f.market is None:
            continue
        then = _number(entry.get("line"))
        fav = str(entry.get("favourite") or "")
        if then is None or not fav:
            continue
        then_for_home = abs(then) if predictions.team_code(fav) == predictions.team_code(f.home) else -abs(then)
        if abs(then_for_home - f.market) > RECORD_GAP:
            out.append(Problem("record", g.label,
                               f"the week's open record has {entry.get('line')}, the line now is "
                               f"{f.home if f.market >= 0 else f.road} {-abs(f.market):g}".replace("-", "−")))
    priced = [g for g in games if by_game.get(g.index) is not None]
    missing = [g.label for g in priced if str(g.index) not in stored]
    if missing:
        out.append(Problem("record", "", f"{len(missing)} priced game{'' if len(missing) == 1 else 's'} "
                           f"missing from the week's record: {', '.join(missing[:3])}"))
    lined = [g for g in games if g.line is not None]
    recorded_lines = sum(1 for g in lined if (stored.get(str(g.index)) or {}).get("pool_line"))
    if lined and recorded_lines < len(lined):
        out.append(Problem("record", "", f"the week's record has {recorded_lines} of {len(lined)} pool lines"))
    return out
