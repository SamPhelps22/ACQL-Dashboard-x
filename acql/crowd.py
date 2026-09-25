"""How this pool picks, learned from its own pick sheets.

The win-the-week card is only as good as its picture of the other coaches:
the edge in a pick is its chance of landing *minus the share of the pool
already on it*. Until now that share came from one curve - how pools in
general treat a favourite of a given size, and 73% on the favourite of a
lined game - and against this pool's real sheets it missed by about ten
points a game.

This starts from that same curve and learns how this pool departs from it:

    chalk        do they take favourites more or less than pools usually do
    spread       does the size of the line move them more or less than usual
    home         do they lean to the home side
    line gap     on a lined game, do they notice how far the commissioner's
                 line is from Vegas - or take the better team regardless
    last week    do they chase teams that just won
    teams        the teams they back (or fade) whatever the numbers say

Every one of those is pulled toward "no different from the usual curve" and
only moves as far as the sheets push it, so two weeks of evidence moves it a
little and a season moves it a lot. With no sheets at all it *is* the usual
curve, so nothing that relies on it can get worse for having it.

Technically: a binomial logistic model with the usual curve as a fixed
offset, fitted by penalised iteratively-reweighted least squares. Numpy only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import analytics, picks, predictions
from .models import Game, Season, same_team

#: Coaches do not pick independently - friends copy friends, everyone reads
#: the same headlines - so a sheet of 35 carries about this many coaches'
#: worth of independent evidence. Treating it as 35 would let one odd week
#: rewrite the model.
EFFECTIVE_COACHES = 12
#: How hard each kind of effect is pulled back toward the usual curve.
#: Larger is more sceptical. Team effects are the most sceptical: a team
#: appears once a week, and one week tells you little about it.
PENALTY = {"chalk": 3.0, "spread": 3.0, "home": 3.0, "gap": 3.0, "last": 3.0}
TEAM_PENALTY = 6.0
FEATURES = ("chalk", "spread", "home", "gap", "last")


@dataclass(frozen=True)
class Situation:
    """One game, from the side of the team the crowd is expected to prefer."""

    favourite: str
    underdog: str
    points: float            # the market's margin for the favourite
    fav_home: bool
    line: float | None       # the pool's line when the game is lined
    fav_won_last: float | None = None     # 1 won, 0 lost, None unknown / bye
    dog_won_last: float | None = None


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def usual_share(sit: Situation) -> float:
    """The old curve: what pools usually do with a game like this."""
    if sit.line is not None:
        return analytics.CHALK_PRIOR
    return analytics.crowd_on_favourite(sit.points)


def _row(sit: Situation) -> dict[str, float]:
    last = 0.0
    if sit.fav_won_last is not None and sit.dog_won_last is not None:
        last = sit.fav_won_last - sit.dog_won_last
    return {
        "chalk": 1.0,
        "spread": 0.0 if sit.line is not None else sit.points / 7.0,
        "home": 1.0 if sit.fav_home else -1.0,
        "gap": ((sit.line - sit.points) / 7.0) if sit.line is not None else 0.0,
        "last": last,
    }


@dataclass
class CrowdModel:
    coef: dict[str, float] = field(default_factory=dict)
    teams: dict[str, float] = field(default_factory=dict)   # team code -> lean
    games: int = 0
    weeks: list[int] = field(default_factory=list)

    def share_on_favourite(self, sit: Situation) -> float:
        z = _logit(usual_share(sit))
        for name, value in _row(sit).items():
            z += self.coef.get(name, 0.0) * value
        z += self.teams.get(predictions.team_code(sit.favourite), 0.0)
        z -= self.teams.get(predictions.team_code(sit.underdog), 0.0)
        return _sigmoid(z)

    def share_on(self, sit: Situation, pick: str) -> float:
        on_fav = self.share_on_favourite(sit)
        return on_fav if same_team(pick, sit.favourite) else 1 - on_fav

    # ---- in words, for the Insights page -------------------------------
    def habits(self) -> list[str]:
        """What stands out about this pool, largest effects first."""
        if not self.games:
            return []
        said: list[tuple[float, str]] = []
        base = Situation("A", "B", 3.0, False, None)
        usual = usual_share(base)
        this = self.share_on_favourite(base)
        said.append((abs(this - usual),
                     f"On a 3-point favourite {this:.0%} of this pool takes the favourite, "
                     f"against {usual:.0%} in a typical pool."))
        home = self.share_on_favourite(Situation("A", "B", 3.0, True, None))
        road = self.share_on_favourite(Situation("A", "B", 3.0, False, None))
        if abs(home - road) >= 0.03:
            side = "home" if home > road else "road"
            said.append((abs(home - road),
                         f"They lean to the {side} side: {home:.0%} on a 3-point home "
                         f"favourite, {road:.0%} on a road one."))
        gap_lo = self.share_on_favourite(Situation("A", "B", 7.0, True, 7.0))
        gap_hi = self.share_on_favourite(Situation("A", "B", 7.0, True, 10.0))
        if abs(gap_lo - gap_hi) >= 0.03:
            said.append((abs(gap_lo - gap_hi),
                         f"On lined games they {'do' if gap_hi < gap_lo else 'do not'} notice a "
                         f"stiff line: {gap_lo:.0%} take the favourite at the Vegas number, "
                         f"{gap_hi:.0%} when the pool line is 3 points bigger."))
        chase = self.coef.get("last", 0.0)
        if abs(chase) >= 0.15:
            said.append((abs(chase) / 4,
                         "They chase last week's winners." if chase > 0
                         else "They fade last week's winners."))
        loved = sorted(self.teams.items(), key=lambda kv: -kv[1])
        fans = [predictions.display_team(c) for c, v in loved if v >= 0.25][:3]
        doubts = [predictions.display_team(c) for c, v in reversed(loved) if v <= -0.25][:3]
        if fans:
            said.append((0.05, "Backed more than the numbers justify: " + ", ".join(fans) + "."))
        if doubts:
            said.append((0.05, "Faded more than the numbers justify: " + ", ".join(doubts) + "."))
        said.sort(key=lambda pair: -pair[0])
        return [text for _, text in said]


# ---- learning it ----------------------------------------------------------
@dataclass(frozen=True)
class Observation:
    situation: Situation
    on_favourite: float       # share of the pool that took the favourite
    counted: int
    week: int


def _won_last(season: Season, week: int) -> dict[str, float]:
    """Team code -> 1 if they won their game the week before, 0 if they lost."""
    prior = season.weeks.get(week - 1)
    out: dict[str, float] = {}
    if prior is None:
        return out
    for game in prior.games:
        if not game.played:
            continue
        for team in (game.home, game.away):
            code = predictions.team_code(team)
            if code:
                out[code] = 1.0 if same_team(team, game.winner) else 0.0
    return out


def situation(season: Season, week: int, game: Game, home_margin: float) -> Situation:
    """A game as the model sees it, given the market's margin for the home side."""
    line = getattr(game, "line", None)
    fav_name = getattr(game, "line_favourite", "") if line is not None else ""
    if line is not None and fav_name:
        fav_home = same_team(fav_name, game.home)
    else:
        fav_home = home_margin >= 0
    favourite, underdog = (game.home, game.away) if fav_home else (game.away, game.home)
    points = home_margin if fav_home else -home_margin
    last = _won_last(season, week)
    return Situation(
        favourite=favourite, underdog=underdog, points=points, fav_home=fav_home,
        line=line if (line is not None and fav_name) else None,
        fav_won_last=last.get(predictions.team_code(favourite)),
        dog_won_last=last.get(predictions.team_code(underdog)),
    )


def _market_margins(week: int, games: list[Game]) -> dict[int, float]:
    """Game index -> the market's home margin, from the stored predictions."""
    forecasts, _ = predictions.load(week)
    if not forecasts:
        return {}
    out = {}
    for index, forecast in predictions.match_games(games, forecasts).by_game.items():
        game = next(g for g in games if g.index == index)
        value = forecast.market if forecast.market is not None else forecast.opening
        margin = predictions.home_margin(game, forecast, value)
        if margin is not None:
            out[index] = margin
    return out


def observations(season: Season, market=None, sheets=None) -> list[Observation]:
    """Every game on this season's sheets that has a market line to read against."""
    market = market or _market_margins
    sheets = sheets if sheets is not None else picks.load_all()
    out: list[Observation] = []
    for number, sheet in sorted(sheets.items()):
        week = season.weeks.get(number)
        if week is None or not week.games:
            continue
        margins = market(number, sorted(week.games, key=lambda g: g.index))
        for game in week.games:
            margin = margins.get(game.index)
            row = sheet.game_for(game.away, game.home)
            if margin is None or row is None or row.counted < 5:
                continue
            sit = situation(season, number, game, margin)
            share = row.share_on(sit.favourite)
            if share is None:
                share = 0.0
            out.append(Observation(sit, share, row.counted, number))
    return out


def fit(obs: list[Observation]) -> CrowdModel:
    """The pool's habits, from what it actually did."""
    if not obs:
        return CrowdModel()
    teams = sorted({
        c for o in obs
        for c in (predictions.team_code(o.situation.favourite),
                  predictions.team_code(o.situation.underdog)) if c
    })
    cols = list(FEATURES) + [f"team:{t}" for t in teams]
    index = {c: i for i, c in enumerate(cols)}
    X = np.zeros((len(obs), len(cols)))
    offset = np.zeros(len(obs))
    y = np.zeros(len(obs))
    n = np.zeros(len(obs))
    for r, o in enumerate(obs):
        for name, value in _row(o.situation).items():
            X[r, index[name]] = value
        fav = predictions.team_code(o.situation.favourite)
        dog = predictions.team_code(o.situation.underdog)
        if fav:
            X[r, index[f"team:{fav}"]] += 1.0
        if dog:
            X[r, index[f"team:{dog}"]] -= 1.0
        offset[r] = _logit(usual_share(o.situation))
        y[r] = o.on_favourite
        n[r] = min(o.counted, EFFECTIVE_COACHES)
    penalty = np.diag([PENALTY.get(c, TEAM_PENALTY) for c in cols])

    beta = np.zeros(len(cols))
    for _ in range(50):
        eta = offset + X @ beta
        p = 1 / (1 + np.exp(-eta))
        w = n * p * (1 - p)
        grad = X.T @ (n * (y - p)) - penalty @ beta
        hess = X.T @ (X * w[:, None]) + penalty
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break

    return CrowdModel(
        coef={c: float(beta[index[c]]) for c in FEATURES},
        teams={c[5:]: float(beta[index[c]]) for c in cols if c.startswith("team:")},
        games=len(obs),
        weeks=sorted({o.week for o in obs}),
    )


# ---- the model the pages use -----------------------------------------------
_CACHE: dict[tuple, CrowdModel] = {}


def model(season: Season) -> CrowdModel:
    """The pool's habits as of the sheets stored now; remembered per season."""
    sheets = picks.load_all()
    from . import odds
    key = (id(season), tuple(sorted(sheets)), picks._store_stamp(),
           predictions.store_stamp(), odds.stamp())
    found = _CACHE.get(key)
    if found is None:
        _CACHE.clear()
        found = fit(observations(season, sheets=sheets))
        _CACHE[key] = found
    return found


#: Games of evidence before the learned habits replace the usual curve.
#: Below this the pages keep what they did before, pool chalk and all.
MINIMUM_GAMES = 16


def guess(season: Season, week: int, game: Game, home_margin: float, pick: str) -> float | None:
    """The share of this pool expected on `pick`, from its own habits.

    None until there is enough of this season's evidence to lean on; the
    caller then uses the usual curve exactly as it did before.
    """
    learned = model(season)
    if learned.games < MINIMUM_GAMES:
        return None
    return learned.share_on(situation(season, week, game, home_margin), pick)


def check(obs: list[Observation]) -> dict[str, float] | None:
    """How well it predicts a week it has not seen, against the usual curve.

    Each week is predicted from the others only. Returns the average miss,
    in share of the pool, for both - the honest measure of whether learning
    the pool's habits beats assuming a typical pool.
    """
    weeks = sorted({o.week for o in obs})
    if len(weeks) < 2:
        return None
    learned, usual, count = 0.0, 0.0, 0
    for held in weeks:
        m = fit([o for o in obs if o.week != held])
        for o in obs:
            if o.week != held:
                continue
            learned += abs(m.share_on_favourite(o.situation) - o.on_favourite)
            usual += abs(usual_share(o.situation) - o.on_favourite)
            count += 1
    return {"learned": learned / count, "usual": usual / count, "games": count}
