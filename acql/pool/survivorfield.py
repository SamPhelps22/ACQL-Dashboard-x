"""Who else is on each team in the suicide pool this week.

survivor.py ranks a coach's teams by the chance each one survives. That is
half the picture: the pot goes to whoever is left, so a team half the pool
is on buys nothing when it wins and costs the whole crowd together when it
loses, while a team as safe that nobody holds leaves you standing over the
ones who fall.

How the others pick is learned from their own suicide picks this season.
Each coach is taken to choose among the teams they still have, more often
the safer ones:

    P(team) is proportional to exp(sharpness x survive chance)

One number, `sharpness`, fitted to every pick the pool has made: 0 would be
picking blind, a large number is always taking the safest team left. With
no picks yet it falls back to SHARPNESS.

`check` scores the fit against picking blind and against "everyone takes
their safest team", on the same picks, so the field is only trusted as far
as it beats those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..feeds import schedule
from ..model import predictions
from ..models import Season
from . import survivor

#: Used before the pool has made any picks to learn from.
SHARPNESS = 12.0
#: Simulated weeks for the "who is left" figures.
SIMULATIONS = 20000
SEED = 7


def team_chances(season: Season, week: int, rating: dict[str, float] | None = None,
                 market: dict[str, float] | None = None) -> dict[str, float]:
    """Team code -> chance it survives `week`, priced the way survivor.advise prices it."""
    rating = rating if rating is not None else survivor.ratings(survivor._lines_so_far(week))
    market = market if market is not None else survivor._this_week_lines(week, season)
    out = {}
    for team in schedule.teams():
        code = predictions.team_code(team)
        found = schedule.fixture(team, week) if code else None
        if found is None:
            continue
        opponent, home = found
        margin = market.get(code)
        if margin is None:
            margin = (rating.get(code, 0.0) - rating.get(predictions.team_code(opponent), 0.0)
                      + (survivor.HOME_EDGE if home else -survivor.HOME_EDGE))
        posted = survivor._posted_line(season, week, team)
        if posted is not None:
            line, is_fav = posted
        else:
            line, is_fav = survivor.assumed_line(margin), margin > 0
        out[code] = survivor.survive_chance(margin, line, is_fav)
    return out


def _shares(chances: dict[str, float], spent: set[str], sharpness: float) -> dict[str, float]:
    free = {c: p for c, p in chances.items() if c not in spent}
    if not free:
        return {}
    top = max(free.values())
    weights = {c: math.exp(sharpness * (p - top)) for c, p in free.items()}
    total = sum(weights.values())
    return {c: w / total for c, w in weights.items()}


@dataclass(frozen=True)
class Made:
    """One suicide pick a coach really made, with what they could have taken."""
    coach: str
    week: int
    team: str
    chances: dict[str, float]
    spent: frozenset[str]


def history(season: Season, upto: int) -> list[Made]:
    """Every real pick before week `upto`, back to the start of the season.

    Rounds the pool restarted count too: how a coach chooses doesn't change
    when the pot does. Spent teams reset with each new round.
    """
    starts = [0] + [r["week"] for r in survivor.rounds(_year(season))]
    restart = getattr(season, "suicide_restart", 0) or 0
    if restart and restart not in starts:
        starts.append(restart)
    starts.sort()
    by_week = {}
    out = []
    for key, player in season.players.items():
        picks = player.suicide_picks or {}
        spent: set[str] = set()
        for week in sorted(picks):
            if week >= upto:
                break
            if any(s == week for s in starts[1:]):
                spent = set()
            code = predictions.team_code(picks[week])
            if not code:
                continue                    # "-Dead-" and blanks
            if week not in by_week:
                by_week[week] = team_chances(season, week)
            chances = by_week[week]
            if code in chances and code not in spent:
                out.append(Made(player.display, week, code, chances, frozenset(spent)))
            spent.add(code)
    return out


def _year(season: Season) -> int:
    from ..feeds import results
    return results.season_year(season)


def _loglik(made: list[Made], sharpness: float) -> float:
    total = 0.0
    for m in made:
        share = _shares(m.chances, set(m.spent), sharpness).get(m.team, 0.0)
        total += math.log(max(share, 1e-12))
    return total


def fit(made: list[Made]) -> float:
    """The sharpness that best explains the picks (a plain grid, then a finer one)."""
    if not made:
        return SHARPNESS
    best = max(np.arange(0.0, 60.01, 1.0), key=lambda s: _loglik(made, s))
    fine = np.arange(max(0.0, best - 1), best + 1.001, 0.1)
    return float(max(fine, key=lambda s: _loglik(made, s)))


def check(made: list[Made]) -> dict[str, float] | None:
    """Leave-one-week-out: fit on the other weeks, score each week's picks.

    Per pick, the average log chance given to what was really picked, for
    this model, picking blind, and "the safest team left" (with a little
    room so a miss isn't minus infinity); and how often the model's top
    team was the one picked.
    """
    weeks = sorted({m.week for m in made})
    if len(weeks) < 2:
        return None
    model = blind = safest = 0.0
    top_hits = 0
    for w in weeks:
        train = [m for m in made if m.week != w]
        s = fit(train)
        for m in (x for x in made if x.week == w):
            share = _shares(m.chances, set(m.spent), s)
            model += math.log(max(share.get(m.team, 0.0), 1e-12))
            blind += math.log(1 / len(share))
            best = max(share, key=lambda c: m.chances[c])
            safest += math.log(0.9 if m.team == best else 0.1 / max(1, len(share) - 1))
            top_hits += m.team == max(share, key=share.get)
    n = len(made)
    return {"picks": n, "model": model / n, "blind": blind / n,
            "safest": safest / n, "top_hit": top_hits / n}


@dataclass(frozen=True)
class FieldTeam:
    code: str
    team: str
    chance: float
    rivals: float           # expected number of other live coaches on it
    out_if_live: float      # if you take it and it survives, expected rivals knocked out
    alone: float            # chance you are the only one left after the week


@dataclass(frozen=True)
class Field:
    week: int
    coach: str
    rivals: int             # other coaches still alive
    sharpness: float
    learned_from: int       # real picks it was fitted on
    teams: list[FieldTeam]  # every team the coach can still use, safest first


def field(season: Season, coach_key: str, week: int, *, sims: int = SIMULATIONS,
          seed: int = SEED) -> Field | None:
    player = season.players.get(coach_key)
    if player is None:
        return None
    made = history(season, week)
    sharpness = fit(made)
    chances = team_chances(season, week)
    codes = sorted(chances)
    index = {c: i for i, c in enumerate(codes)}
    survive = np.array([chances[c] for c in codes])

    rival_shares = []
    for key, other in season.players.items():
        if key == coach_key or not other.suicide_alive:
            continue
        spent = {c for _, c in survivor.used_teams(season, key)}
        share = _shares(chances, spent, sharpness)
        if share:
            row = np.zeros(len(codes))
            for c, p in share.items():
                row[index[c]] = p
            rival_shares.append(row)
    shares = np.array(rival_shares) if rival_shares else np.zeros((0, len(codes)))
    expected = shares.sum(axis=0)

    # One draw of every game's result and every rival's pick per simulated week.
    # Opponents share a game, so a team and its opponent can't both survive a
    # straight-up result; under a pool line they can't both be credited either.
    rng = np.random.default_rng(seed)
    pairs = {}
    for c in codes:
        found = schedule.fixture(predictions.display_team(c), week)
        if found:
            opp = predictions.team_code(found[0])
            if opp in index:
                pairs[c] = opp
    coin = rng.random((sims, len(codes)))
    lives = coin < survive
    for c, opp in pairs.items():
        if c < opp:     # the opponent reads the same coin from the other end
            lives[:, index[opp]] = coin[:, index[c]] >= 1 - survive[index[opp]]
    if len(shares):
        cum = np.cumsum(shares, axis=1)
        draws = rng.random((sims, len(shares)))
        picked = np.array([np.searchsorted(cum[r], draws[:, r]) for r in range(len(shares))]).T
        picked = np.minimum(picked, len(codes) - 1)
        rival_lives = np.take_along_axis(lives, picked, axis=1)
        left = rival_lives.sum(axis=1)
    else:
        left = np.zeros(sims)

    spent = {c for _, c in survivor.used_teams(season, coach_key)}
    teams = []
    for c in codes:
        if c in spent:
            continue
        i = index[c]
        live = lives[:, i]
        out = float((len(shares) - left[live]).mean()) if live.any() else 0.0
        alone = float((live & (left == 0)).mean())
        teams.append(FieldTeam(c, predictions.display_team(c), chances[c],
                               float(expected[i]), out, alone))
    teams.sort(key=lambda t: -t.chance)
    return Field(week, player.display, len(shares), sharpness, len(made), teams)
