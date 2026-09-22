"""Season analytics: projections, title odds and the patterns behind the scores.

Everything here is plain computation over the domain model, with no Qt, so it
can be tested on its own and read without a UI around it. The pages only
format what these functions return.

Two sections:

* Looking ahead - how many weeks are left, who can still win, the leader's
  magic number, and title odds from a simulation of the rest of the season.
* Looking back - the home-team record, which weeks were hard, whether a good
  week tends to follow a good week, head-to-head records, and each player's
  form against their consistency.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .config import WEEKS_IN_SEASON
from .models import Player, Season

SIMULATIONS = 10_000
# How many weeks of their own a player needs before their history outweighs
# the pool's. Pick'em results are mostly noise week to week, so this is set
# high: at 3, one hot opening week made a player an 80% title favourite with
# seventeen weeks still to play. At 8, a player's own record only carries
# more weight than the pool's from about the midpoint of the season.
SHRINKAGE_WEEKS = 8
EARLY_WEEKS = 4      # below this, the UI warns that odds will move a lot
SEED = 2026          # fixed, so odds change only when the data does
MIN_MOMENTUM_PAIRS = 8


# ======================================================================
# Looking ahead
# ======================================================================
def weeks_remaining(season: Season) -> int:
    """Weeks still to be finalised. A week in progress counts as remaining."""
    return max(0, WEEKS_IN_SEASON - len(season.final_weeks()))


def max_per_week(season: Season) -> int:
    """The most anyone can add in one week: every game plus every big loser."""
    return season.max_regular_points + season.max_big_loser_points


def current_wins(player: Player) -> int:
    """Season wins as the standings have them.

    stats.xls is authoritative, so its figure is used when present. Without
    a stats export the week sheets are all there is, so they are summed.
    """
    return player.wins or player.season_wins


def history(player: Player) -> list[int]:
    return [v for v in player.weekly_wins.values() if v is not None]


@dataclass(frozen=True)
class Outlook:
    """One player's position and prospects."""

    player: Player
    wins: int
    pace: float           # average wins a week so far
    projected: float      # wins + pace for every remaining week
    best_case: int        # wins + a perfect week, every week left
    title_odds: float     # 0..1, from the simulation
    top3_odds: float      # 0..1
    status: str


@dataclass(frozen=True)
class RaceSummary:
    outlooks: list[Outlook]      # most likely champion first
    remaining: int
    per_week: int
    in_contention: int           # mathematically able to finish first
    magic_number: int | None     # None once the season is over
    leader: Player | None
    chaser: Player | None        # the player with the best best case, bar the leader
    simulations: int


def simulate(
    players: list[Player],
    remaining: int,
    *,
    sims: int = SIMULATIONS,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray]:
    """Title and top-three odds for each player, by simulating the season out.

    Each simulated week, a player scores one of their own past weeks, picked
    at random - a bootstrap of their record. A player with only a few weeks
    has too little history to trust, so each draw comes from the whole pool's
    weeks instead with probability k/(n+k), k = SHRINKAGE_WEEKS: a player is
    treated as typical until they have shown otherwise for a while.

    Ties for first share the title equally, so the odds always sum to one.
    Because every draw is a real past score, nobody can exceed a perfect
    week, and a player who is mathematically out gets exactly zero.
    """
    count = len(players)
    wins = np.array([current_wins(p) for p in players], dtype=float)
    if count == 0:
        return np.zeros(0), np.zeros(0)

    pool = np.array([v for p in players for v in history(p)], dtype=float)
    if remaining == 0 or pool.size == 0:
        # Nothing left to play (or nothing to play it with): the table stands.
        return _odds(wins[:, None])

    rng = np.random.default_rng(seed)
    added = np.zeros((count, sims))
    for i, player in enumerate(players):
        own = np.array(history(player), dtype=float)
        shape = (sims, remaining)
        pooled = pool[rng.integers(pool.size, size=shape)]
        if own.size:
            weight = own.size / (own.size + SHRINKAGE_WEEKS)
            mine = own[rng.integers(own.size, size=shape)]
            draws = np.where(rng.random(shape) < weight, mine, pooled)
        else:
            draws = pooled
        added[i] = draws.sum(axis=1)
    return _odds(wins[:, None] + added)


def _odds(finals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Turn a (players, sims) table of final totals into title and top-3 odds."""
    best = finals.max(axis=0)
    on_top = finals == best
    title = (on_top / on_top.sum(axis=0)).mean(axis=1)
    # A player's place is one more than the number strictly ahead of them,
    # so players level on points share the better place.
    ahead = (finals[None, :, :] > finals[:, None, :]).sum(axis=1)
    top3 = (ahead < 3).mean(axis=1)
    return title, top3


def race(season: Season, *, sims: int = SIMULATIONS) -> RaceSummary:
    """Everything the Projections tab needs, computed in one pass."""
    players = [p for p in season.players.values()]
    remaining = weeks_remaining(season)
    per_week = max_per_week(season)
    if not players:
        return RaceSummary([], remaining, per_week, 0, None, None, None, 0)

    title, top3 = simulate(players, remaining, sims=sims)
    wins = [current_wins(p) for p in players]
    best_cases = [w + remaining * per_week for w in wins]
    top = max(wins)

    leaders = [p for p, w in zip(players, wins) if w == top]
    leader = sorted(leaders, key=lambda p: p.display.lower())[0]
    # The chaser is whoever could finish highest if everything went their way.
    others = sorted(
        ((b, p) for p, b in zip(players, best_cases) if p.key != leader.key),
        key=lambda o: (-o[0], o[1].display.lower()),
    )
    chaser_best, chaser = others[0] if others else (None, None)
    clinched = remaining > 0 and chaser_best is not None and top > chaser_best

    outlooks = []
    for p, w, b, t, t3 in zip(players, wins, best_cases, title, top3):
        own = history(p)
        pace = sum(own) / len(own) if own else 0.0
        if remaining == 0:
            status = "Champion" if w == top else "Final"
        elif clinched and p.key == leader.key:
            status = "Clinched"
        elif w == top:
            status = "Co-leader" if len(leaders) > 1 else "Leader"
        elif b >= top:
            status = "In contention"
        else:
            status = "Out of the title race"
        outlooks.append(Outlook(
            player=p, wins=w, pace=pace, projected=w + pace * remaining,
            best_case=b, title_odds=float(t), top3_odds=float(t3), status=status,
        ))
    outlooks.sort(key=lambda o: (-o.title_odds, -o.wins, o.player.display.lower()))

    in_contention = sum(1 for b in best_cases if b >= top)
    magic = None
    if remaining > 0 and chaser_best is not None:
        # Baseball's magic number, carried over: each leader win and each
        # point the chaser fails to score brings the clinch one closer.
        magic = max(0, chaser_best - top + 1)
    return RaceSummary(
        outlooks=outlooks, remaining=remaining, per_week=per_week,
        in_contention=in_contention, magic_number=magic,
        leader=leader, chaser=chaser, simulations=sims,
    )


# ======================================================================
# Looking back
# ======================================================================
MIN_HOME_GAMES = 48   # three full weeks; fewer than that is a coin flip's noise


def home_record(season: Season) -> tuple[int, int]:
    """(home wins, decided games) across every game with a result."""
    home = decided = 0
    for week in season.weeks.values():
        for game in week.games:
            result = game.winner_is_home()
            if result is None:
                continue
            decided += 1
            home += int(result)
    return home, decided


@dataclass(frozen=True)
class WeekProfile:
    week: int
    average: float
    best: int
    worst: int
    players: int


def week_profiles(season: Season) -> list[WeekProfile]:
    """How the pool scored each final week: the best, the worst and the mean."""
    out = []
    for week in season.final_weeks():
        scores = [
            p.weekly_wins[week] for p in season.players.values()
            if p.weekly_wins.get(week) is not None
        ]
        if scores:
            out.append(WeekProfile(
                week, sum(scores) / len(scores), max(scores), min(scores), len(scores),
            ))
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Correlation, or None when either side has no spread to correlate."""
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def momentum(season: Season) -> tuple[float, int] | None:
    """Does a good week predict a good next week? (correlation, pairs used)

    Scores are taken relative to that week's pool average first. Otherwise a
    hard week drags everyone down together and the correlation measures the
    schedule, not the players. What is left is whether beating the pool one
    week goes with beating it the next.
    """
    weeks = season.final_weeks()
    averages = {w.week: w.average for w in week_profiles(season)}
    xs, ys = [], []
    for player in season.players.values():
        for this, following in zip(weeks, weeks[1:]):
            a, b = player.weekly_wins.get(this), player.weekly_wins.get(following)
            if a is None or b is None or this not in averages or following not in averages:
                continue
            xs.append(a - averages[this])
            ys.append(b - averages[following])
    if len(xs) < MIN_MOMENTUM_PAIRS:
        return None
    r = pearson(xs, ys)
    return None if r is None else (r, len(xs))


def describe_momentum(r: float) -> str:
    """Plain words for a correlation, with the usual rough thresholds."""
    if r >= 0.3:
        return "good weeks tend to follow good weeks"
    if r >= 0.1:
        return "a slight carry-over from week to week"
    if r > -0.1:
        return "no carry-over - each week starts fresh"
    if r > -0.3:
        return "a slight bounce-back after bad weeks"
    return "strong weeks tend to be followed by weaker ones"


@dataclass(frozen=True)
class Matchup:
    wins: int      # weeks the row player outscored the column player
    ties: int
    shared: int    # weeks both played

    @property
    def share(self) -> float:
        """Share of shared weeks won, ties counting as half."""
        return (self.wins + 0.5 * self.ties) / self.shared if self.shared else 0.0


def head_to_head(players: list[Player], weeks: list[int]) -> list[list[Matchup | None]]:
    """For every ordered pair, how often the row player beat the column player.

    The diagonal is None: a player does not play themselves.
    """
    grid: list[list[Matchup | None]] = []
    for a in players:
        row: list[Matchup | None] = []
        for b in players:
            if a.key == b.key:
                row.append(None)
                continue
            wins = ties = shared = 0
            for week in weeks:
                x, y = a.weekly_wins.get(week), b.weekly_wins.get(week)
                if x is None or y is None:
                    continue
                shared += 1
                wins += x > y
                ties += x == y
            row.append(Matchup(wins, ties, shared))
        grid.append(row)
    return grid


@dataclass(frozen=True)
class FormPoint:
    player: Player
    average: float
    spread: float     # standard deviation of weekly wins
    weeks: int


def form_profile(season: Season, minimum_weeks: int = 3) -> list[FormPoint]:
    """Average against spread for every player with enough weeks to have one."""
    out = []
    for player in season.players.values():
        own = history(player)
        if len(own) >= minimum_weeks:
            out.append(FormPoint(
                player, sum(own) / len(own), statistics.pstdev(own), len(own),
            ))
    return out


# ======================================================================
# Against the line
# ======================================================================
# How often an NFL regular-season game is decided by exactly this margin, as
# a percentage of games: 6,752 regular-season games, 2000-2026. Football
# scores in 3s and 7s, so margins pile up on certain numbers - which is
# exactly where the pool puts its lines.
MARGIN_FREQUENCY = {
    1: 4.15, 2: 4.10, 3: 14.96, 4: 4.93, 5: 3.60, 6: 6.01, 7: 9.09, 8: 3.79,
    9: 1.60, 10: 5.52, 11: 2.33, 12: 1.66, 13: 2.77, 14: 4.81, 15: 1.53,
    16: 2.07, 17: 3.42,
}
# Margins with no scoring reason to bunch up. A smooth curve through these
# gives "how common would a margin this size be without key numbers", and
# every margin's excess over that curve is its key-number weight.
DEAD_MARGINS = (1, 2, 5, 8, 9, 11, 12, 15, 16)

# Spread of results around the betting line. Fitted so straight-up win
# chances match the market's own moneylines: at 11.4 the model says 60% for a
# 3-point favourite against a market 60%, 74% at 7 against 74%, 82% at 10
# against 82%.
SPREAD_SD = 11.4
MARGIN_RANGE = range(-60, 61)


def _key_weights() -> dict[int, float]:
    xs = list(DEAD_MARGINS)
    ys = [math.log(MARGIN_FREQUENCY[m]) for m in xs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    return {m: f / math.exp(intercept + slope * m) for m, f in MARGIN_FREQUENCY.items()}


KEY_WEIGHT = _key_weights()     # 3 is ~4x, 7 ~3.2x, 14 ~2.7x, 10 ~2.4x, 6 ~2x


def _shape(center: float, sd: float) -> dict[int, float]:
    weights = {
        d: math.exp(-((d - center) / sd) ** 2 / 2) * KEY_WEIGHT.get(abs(d), 1.0)
        for d in MARGIN_RANGE
    }
    total = sum(weights.values())
    return {d: w / total for d, w in weights.items()}


@lru_cache(maxsize=512)
def margin_distribution(spread: float, sd: float = SPREAD_SD) -> tuple[tuple[int, float], ...]:
    """Chance of each final margin, for a team favoured by `spread`.

    A bell curve on its own says a 7-point favourite wins by 7 about as often
    as by 8, which is not how football scores. Each margin is weighted by how
    common it really is, then the curve is shifted so its average margin is
    still the spread - without that shift the key numbers, which cluster near
    zero, drag the average down and every favourite looks weaker than the
    market prices them.
    """
    low, high = spread - 6, spread + 6
    for _ in range(40):                      # bisection on the centre
        mid = (low + high) / 2
        if sum(d * p for d, p in _shape(mid, sd).items()) < spread:
            low = mid
        else:
            high = mid
    return tuple(_shape((low + high) / 2, sd).items())


def cover_chance(spread: float, need: int, sd: float = SPREAD_SD) -> float:
    """Chance a team favoured by `spread` wins by at least `need` points."""
    return sum(p for margin, p in margin_distribution(round(spread, 1), sd) if margin >= need)


def win_chance(spread: float) -> float:
    """Chance a team favoured by `spread` simply wins."""
    return cover_chance(spread, 1)


def line_threshold(spread: float, most: int = 30) -> int:
    """The biggest whole-number pool line the favourite is still worth taking at.

    Useful before the commissioner posts a line: "take them at 6 or less".
    """
    best = 0
    for line in range(most + 1):
        if cover_chance(spread, line + 1) > 0.5:
            best = line
    return best


def _same(a: object, b: object) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold() != ""


@dataclass(frozen=True)
class LineRecord:
    """A player's picks on games that carried a pool line."""

    correct: int
    decided: int      # lined games with a result, in weeks the player played
    weeks: int        # weeks in which they had at least one decided lined game

    @property
    def rate(self) -> float:
        return self.correct / self.decided if self.decided else 0.0

    @property
    def per_week(self) -> float:
        return self.correct / self.weeks if self.weeks else 0.0


def lined_games(season: Season) -> list[tuple[int, "Game"]]:
    """(week, game) for every game with a pool line, in slate order."""
    return [
        (number, game)
        for number in sorted(season.weeks)
        for game in season.weeks[number].games
        # getattr: an out-of-date models.py has no line fields at all, and a
        # season with no lines is better than three pages that fail to draw.
        if getattr(game, "line", None) is not None
    ]


def line_records(season: Season) -> dict[str, LineRecord]:
    """Each player's record on lined games that have a result.

    A pick counts when it matches the recorded result, which already has the
    line applied. That holds whether or not the wrong picks have been deleted
    yet, so graded and ungraded weeks score the same way.
    """
    tallies: dict[str, list[int]] = {}
    weeks_seen: dict[str, set[int]] = {}
    for number, game in lined_games(season):
        if not game.played:
            continue
        for key, line in season.weeks[number].lines.items():
            t = tallies.setdefault(key, [0, 0])
            t[1] += 1
            t[0] += _same(line.correct_picks.get(game.index), game.winner)
            weeks_seen.setdefault(key, set()).add(number)
    return {
        key: LineRecord(c, d, len(weeks_seen.get(key, ())))
        for key, (c, d) in tallies.items()
    }


def pool_line_rate(records: dict[str, LineRecord]) -> float:
    """The whole pool's hit rate on lined games: all correct over all decided."""
    decided = sum(r.decided for r in records.values())
    return sum(r.correct for r in records.values()) / decided if decided else 0.0


def underdog_record(season: Season) -> tuple[int, int]:
    """(underdog got the point, lined games decided) so far this season."""
    dog = decided = 0
    for _, game in lined_games(season):
        if game.played:
            decided += 1
            dog += not _same(game.winner, game.line_favourite)
    return dog, decided


@dataclass(frozen=True)
class Prediction:
    pick: str
    chance: float        # probability the pick is right, 0.5..1
    against_line: bool
    reason: str

    @property
    def coin_flip(self) -> bool:
        return self.chance < 0.52


def predict(game: "Game", vegas_favourite: str | None, points: float | None) -> Prediction | None:
    """The pick for one game, from the Vegas spread and the pool's rule.

    `vegas_favourite` is "home" or "away"; `points` is the Vegas spread. With
    no spread entered there is nothing to predict from, so the answer is None.

    Straight-up games take the Vegas favourite. On a lined game the favourite
    must win by more than the line - by at least floor(line) + 1 - so a win
    by exactly a whole-number line goes to the underdog. The chance is that
    of the expected margin (the Vegas spread) clearing that bar, with results
    spread SPREAD_SD points either side of the spread.
    """
    if vegas_favourite not in ("home", "away") or points is None:
        return None
    home_margin = points if vegas_favourite == "home" else -points

    line = getattr(game, "line", None)
    if line is None:
        if points == 0:
            return Prediction(game.home, 0.5, False, "pick'em - no favourite")
        pick = game.home if home_margin > 0 else game.away
        return Prediction(pick, win_chance(abs(home_margin)), False,
                          f"Vegas favourite by {points:g}")

    favourite = getattr(game, "line_favourite", "")
    fav_is_home = _same(favourite, game.home)
    underdog = getattr(game, "line_underdog", "") or (game.away if fav_is_home else game.home)
    fav_margin = home_margin if fav_is_home else -home_margin
    need = math.floor(line) + 1
    p_fav = cover_chance(fav_margin, need)
    vegas_says = f"Vegas has {favourite} by {fav_margin:g}" if fav_margin >= 0 \
        else f"Vegas has {favourite} as the underdog"
    if p_fav > 0.5:
        return Prediction(favourite, p_fav, True, f"needs to win by {need}+; {vegas_says}")
    return Prediction(underdog, 1 - p_fav, True, f"{favourite} needs {need}+; {vegas_says}")


def upcoming_week(season: Season) -> int:
    """The week to predict.

    The week after the last one that is mostly decided - more than half its
    games have a result. So on Sunday night, with only the late games left,
    it looks ahead to next week; on Thursday, with one game in, it stays on
    the week being played.

    The answer may be a week whose sheet is still blank. The parser leaves
    such weeks out of the Season entirely, so this cannot simply pick from
    `season.weeks`; the page says the slate hasn't been entered instead.
    """
    mostly_done = [
        number for number, week in season.weeks.items()
        if week.games and sum(g.played for g in week.games) * 2 > len(week.games)
    ]
    after = max(mostly_done, default=0)
    return min(after + 1, WEEKS_IN_SEASON)


@dataclass(frozen=True)
class SlateOutlook:
    expected: float      # picks expected to come in, across the games priced
    priced: int          # games with a spread entered
    strong: int          # picks at 60% or better
    coin_flips: int      # picks too close to call


def slate_outlook(guesses: list[Prediction | None]) -> SlateOutlook:
    """What a week's picks add up to."""
    priced = [g for g in guesses if g is not None]
    return SlateOutlook(
        expected=sum(g.chance for g in priced),
        priced=len(priced),
        strong=sum(1 for g in priced if g.chance >= 0.60),
        coin_flips=sum(1 for g in priced if g.coin_flip),
    )