"""The suicide pool: which team to use this week, and which to keep.

Each coach must pick one team a week to win outright, and can use each team
only once all season. So a pick has two costs: the chance it loses now, and
the later week it would have been the safe answer. The best pick this week
is often not the most likely winner - it is a likely winner that will not be
needed later.

What this knows:

    used teams     from the coach's own suicide picks (workbook and sheets)
    this week      the market's line for each game when it is stored,
                   otherwise a rating-based estimate
    the pool line  the suicide pool plays by the pool's lines: a team in a
                   lined game survives only if it is credited with it (a
                   favourite must win by more than the line, an underdog
                   survives by covering). This week's real pool lines are
                   used when the sheet has them; for later weeks, and for
                   this week before they are posted, a line is assumed on
                   any game with a favourite of LINED_FROM points or more
    later weeks    the season's schedule (schedule.py) and team ratings
                   worked out from every betting line seen so far this
                   season - rough early on, firmer by mid-season

and it says what it did in plain words, so a coach can overrule it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import analytics, luck, predictions, schedule
from .config import WEEKS_IN_SEASON
from .models import Season, same_team

#: A later week where a team is at least this likely to survive is a
#: "strong spot" - a week where it could be the answer. Under the pool's
#: lines nothing gets much past 71%: a big favourite has to cover a line
#: and is close to a coin flip, so the safest spot is a favourite of about
#: 4.5 to 6 points that gets no line at all.
STRONG = 0.66
#: Options this close to the best chance this week are treated as equally
#: safe, and the one with the least left to give later is preferred.
CLOSE_ENOUGH = 0.04
#: A team whose best later spot beats this week by this much is worth saving.
SAVE_MARGIN = 0.06
#: Home advantage used for weeks with no line yet, in points.
HOME_EDGE = 1.7
#: How hard ratings are pulled toward average; lines are few early on.
RATING_RIDGE = 2.0
#: The pool puts a line on a game once the favourite is this big (every
#: game at 6.5 or more in weeks 1-2 had one; none below did).
LINED_FROM = 6.5
#: The smallest line the pool posts.
SMALLEST_LINE = 7


@dataclass(frozen=True)
class Option:
    team: str               # display name
    code: str
    opponent: str
    home: bool
    chance: float           # this week
    from_market: bool       # True when this week's number is the real line
    best_later: float       # best chance in any later week
    best_week: int | None
    best_opponent: str
    strong_spots: int       # later weeks at or above STRONG
    save: bool              # worth keeping for later
    line: str = ""          # "PHI by 8" when the pool line decides it
    line_assumed: bool = False   # True when that line is a guess, not posted

    @property
    def later_text(self) -> str:
        if self.best_week is None:
            return "–"
        return f"wk {self.best_week} vs {self.best_opponent} ({self.best_later:.0%})"


@dataclass(frozen=True)
class Advice:
    coach: str
    week: int
    alive: bool
    used: list[tuple[int, str]]          # (week, team) already spent
    options: list[Option]
    pick: Option | None
    reason: str
    rated_from: int                       # games the ratings were built on


# ---- ratings from the lines -------------------------------------------------
def _lines_so_far(upto: int) -> list[tuple[str, str, float]]:
    """(home code, away code, market home margin) for every stored week <= upto."""
    out = []
    for week in range(1, upto + 1):
        forecasts, _ = predictions.load(week)
        for f in forecasts or []:
            value = f.market if f.market is not None else f.opening
            home, road = predictions.team_code(f.home), predictions.team_code(f.road)
            if value is None or not home or not road:
                continue
            out.append((home, road, float(value)))
    return out


def ratings(games: list[tuple[str, str, float]]) -> dict[str, float]:
    """Points better than an average team, from the market's margins.

    margin(home) = rating(home) - rating(away) + home edge, solved by least
    squares with every rating pulled gently toward zero - early in a season
    each team has only been priced two or three times.
    """
    teams = sorted({t for h, a, _ in games for t in (h, a)})
    if not teams:
        return {}
    index = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(games), len(teams)))
    y = np.zeros(len(games))
    for r, (home, away, margin) in enumerate(games):
        X[r, index[home]] += 1
        X[r, index[away]] -= 1
        y[r] = margin - HOME_EDGE
    beta = np.linalg.solve(X.T @ X + RATING_RIDGE * np.eye(len(teams)), X.T @ y)
    return {t: float(beta[index[t]]) for t in teams}


def assumed_line(margin: float) -> float | None:
    """The pool line a game with this favourite's margin would probably get."""
    size = abs(margin)
    if size < LINED_FROM:
        return None
    return float(max(SMALLEST_LINE, math.floor(size + 0.5)))


def survive_chance(margin: float, line: float | None, team_is_favourite: bool) -> float:
    """Chance a team survives: wins outright, or is credited under the line.

    `margin` is the market's margin for this team (negative as the underdog).
    """
    if line is None:
        return analytics.win_chance(margin) if margin >= 0 else 1 - analytics.win_chance(-margin)
    fav_margin = margin if team_is_favourite else -margin
    p_fav = luck.favourite_covers(fav_margin, line)
    return p_fav if team_is_favourite else 1 - p_fav


def _modelled(margin: float) -> float:
    """Survive chance with the line the pool would probably post."""
    line = assumed_line(margin)
    return survive_chance(margin, line, margin > 0)


def _chance(rating: dict[str, float], team: str, opponent: str, home: bool) -> float:
    margin = rating.get(team, 0.0) - rating.get(opponent, 0.0) + (HOME_EDGE if home else -HOME_EDGE)
    return _modelled(margin)


def _posted_line(season: Season, week: int, team: str) -> tuple[float, bool] | None:
    """(pool line, team is the favourite) if the sheet has posted one."""
    wk = season.weeks.get(week)
    for game in (wk.games if wk is not None else []):
        if not (same_team(team, game.home) or same_team(team, game.away)):
            continue
        line = getattr(game, "line", None)
        favourite = getattr(game, "line_favourite", "")
        if line is None or not favourite:
            return None
        return float(line), same_team(team, favourite)
    return None


def _this_week_lines(week: int) -> dict[str, float]:
    """Team code -> the market's margin for that team this week, if stored."""
    forecasts, _ = predictions.load(week)
    out = {}
    for f in forecasts or []:
        value = f.market if f.market is not None else f.opening
        home, road = predictions.team_code(f.home), predictions.team_code(f.road)
        if value is None or not home or not road:
            continue
        out[home], out[road] = float(value), -float(value)
    return out


# ---- the advice -------------------------------------------------------------
def used_teams(season: Season, coach_key: str) -> list[tuple[int, str]]:
    player = season.players.get(coach_key)
    if player is None:
        return []
    out = []
    for week, team in sorted((player.suicide_picks or {}).items()):
        code = predictions.team_code(team)
        if code:
            out.append((week, code))
    return out


def advise(
    season: Season,
    coach_key: str,
    week: int,
    *,
    games: list[tuple[str, str, float]] | None = None,
    this_week: dict[str, float] | None = None,
) -> Advice | None:
    """What this coach should consider for `week`.

    `games` (every priced game so far) and `this_week` (team code -> market
    margin) are read from the stored predictions unless given.
    """
    player = season.players.get(coach_key)
    if player is None:
        return None
    used = used_teams(season, coach_key)
    spent = {code for _, code in used}
    priced = games if games is not None else _lines_so_far(week)
    rating = ratings(priced)
    market = this_week if this_week is not None else _this_week_lines(week)
    last_week = min(WEEKS_IN_SEASON, schedule.WEEKS)

    options = []
    for team in schedule.teams():
        code = predictions.team_code(team)
        if not code or code in spent:
            continue
        found = schedule.fixture(team, week)
        if found is None:
            continue                                   # bye
        opponent, home = found
        if code in market:
            margin, real = market[code], True
        else:
            margin = (rating.get(code, 0.0) - rating.get(predictions.team_code(opponent), 0.0)
                      + (HOME_EDGE if home else -HOME_EDGE))
            real = False
        posted = _posted_line(season, week, team)
        if posted is not None:
            line, is_fav = posted
            assumed = False
        else:
            line, is_fav, assumed = assumed_line(margin), margin > 0, True
        chance = survive_chance(margin, line, is_fav)
        line_text = ""
        if line is not None:
            fav = code if is_fav else predictions.team_code(opponent)
            line_text = f"{fav.upper()} by {line:g}"
        later = []
        for w in range(week + 1, last_week + 1):
            nxt = schedule.fixture(team, w)
            if nxt is None:
                continue
            opp, at_home = nxt
            later.append((_chance(rating, code, predictions.team_code(opp), at_home), w, opp))
        best = max(later, default=(0.0, None, ""))
        strong = sum(1 for c, _, _ in later if c >= STRONG)
        options.append(Option(
            team=predictions.display_team(code), code=code,
            opponent=predictions.display_team(opponent), home=home,
            chance=chance, from_market=real,
            best_later=best[0], best_week=best[1],
            best_opponent=predictions.display_team(best[2]) if best[2] else "",
            strong_spots=strong,
            save=best[0] >= chance + SAVE_MARGIN and strong >= 1,
            line=line_text, line_assumed=bool(line_text) and assumed,
        ))
    options.sort(key=lambda o: -o.chance)

    pick, reason = None, ""
    if not player.suicide_alive:
        reason = f"{player.display} is out of the suicide pool."
    elif options:
        top = options[0].chance
        close = [o for o in options if o.chance >= top - CLOSE_ENOUGH]
        # Among the safest few, spend the team with the least left to give.
        pick = min(close, key=lambda o: (o.strong_spots, -o.chance))
        if pick is options[0]:
            later = (
                ", and it has no later week this safe - nothing is lost by using it now."
                if pick.strong_spots == 0 else
                f", and only {pick.strong_spots} later week"
                f"{' is' if pick.strong_spots == 1 else 's are'} as safe."
                if pick.strong_spots <= 2 else
                f". It has {pick.strong_spots} strong weeks later too, but nothing "
                f"else this week comes close."
            )
            reason = f"{pick.team} is the likeliest to survive this week ({pick.chance:.0%}){later}"
        else:
            first = options[0]
            reason = (
                f"{pick.team} ({pick.chance:.0%}) is within {CLOSE_ENOUGH:.0%} of "
                f"{first.team} ({first.chance:.0%}), and {first.team} has "
                f"{first.strong_spots} strong later spots to {pick.team}'s "
                f"{pick.strong_spots} - so {first.team} is worth keeping."
            )

    return Advice(
        coach=player.display, week=week, alive=player.suicide_alive,
        used=[(w, predictions.display_team(c)) for w, c in used],
        options=options, pick=pick, reason=reason, rated_from=len(priced),
    )