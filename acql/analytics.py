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
from .models import Game, Player, Season

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


def line_threshold(spread: float, most: int = 30, sd: float = SPREAD_SD) -> int:
    """The biggest whole-number pool line the favourite is still worth taking at.

    Useful before the commissioner posts a line: "take them at 6 or less".
    """
    best = 0
    for line in range(most + 1):
        if cover_chance(spread, line + 1, sd) > 0.5:
            best = line
    return best


# ======================================================================
# The Big Loser mini pool
# ======================================================================
# A big loser is a team that loses by MORE than 14, so 15 is the bar. The
# pool's lines have no effect here - it is the raw result that counts.
BIG_LOSER_MARGIN = 14


@dataclass(frozen=True)
class BigLoser:
    """A candidate for the Big Loser pool: a team, and how likely a hiding is."""

    team: str
    opponent: str
    margin: float        # their expected margin, negative when they are the dog
    chance: float        # chance they lose by MORE than BIG_LOSER_MARGIN


def big_loser_chance(margin: float, sd: float = SPREAD_SD) -> float:
    """Chance a team with this expected margin loses by more than 14.

    `margin` is from the team's own side, so -10 means they are ten-point
    underdogs. Losing by 15 or more means the other side clearing 15, which
    is what cover_chance answers.
    """
    return cover_chance(-margin, BIG_LOSER_MARGIN + 1, sd)


def big_losers(games: list[tuple[str, str, float]], sd: float = SPREAD_SD) -> list[BigLoser]:
    """Both teams in every game, worst beating first.

    Each entry is (home, away, expected home margin). Every team is a
    candidate - a favourite can be blown out too, it is just rarer - and the
    list comes back in the order you would pick from it.
    """
    out: list[BigLoser] = []
    for home, away, margin in games:
        out.append(BigLoser(away, home, -margin, big_loser_chance(-margin, sd)))
        out.append(BigLoser(home, away, margin, big_loser_chance(margin, sd)))
    out.sort(key=lambda b: -b.chance)
    return out


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


def lined_games(season: Season) -> list[tuple[int, Game]]:
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
    reason: str          # short enough for a table cell
    detail: str = ""     # the long version, for a tooltip

    @property
    def coin_flip(self) -> bool:
        return self.chance < 0.52


PICK_EM = 0.25       # a margin this small either way is a coin flip, not a side


def _points(value: float) -> str:
    """7, 6.5, 10.4 - a margin written the way a spread is written."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def predict(game: Game, vegas_favourite: str | None, points: float | None) -> Prediction | None:
    """The pick for one game, from the Vegas spread and the pool's rule.

    `vegas_favourite` is "home" or "away"; `points` is the Vegas spread. With
    no spread entered there is nothing to predict from, so the answer is None.
    """
    if vegas_favourite not in ("home", "away") or points is None:
        return None
    return predict_margin(game, points if vegas_favourite == "home" else -points)


def predict_margin(
    game: Game,
    home_margin: float | None,
    *,
    sd: float = SPREAD_SD,
    source: str = "Vegas",
) -> Prediction | None:
    """The pick for one game from an expected margin, positive for the home team.

    Straight-up games take whoever is favoured. On a lined game the pool's
    favourite must win by more than the line - by at least floor(line) + 1 -
    so a win by exactly a whole-number line goes to the underdog. The chance
    is that of the expected margin clearing that bar, with results spread
    `sd` points either side of it.

    `sd` is a way in for a game nobody agrees about: widen it and every
    chance moves toward a coin flip, which is what disagreement means.
    `source` only names where the margin came from, for the reason text.
    """
    if home_margin is None:
        return None
    sd = round(max(sd, 1.0), 1)

    line = getattr(game, "line", None)
    if line is None:
        if abs(home_margin) < PICK_EM:
            return Prediction(game.home, 0.5, False, "pick 'em", "No favourite.")
        pick = game.home if home_margin > 0 else game.away
        return Prediction(
            pick, cover_chance(abs(home_margin), 1, sd), False,
            f"{pick} by {_points(abs(home_margin))}",
            f"Straight-up game. {source.capitalize()} makes it {pick} by "
            f"{_points(abs(home_margin))}.",
        )

    favourite = getattr(game, "line_favourite", "")
    fav_is_home = _same(favourite, game.home)
    underdog = getattr(game, "line_underdog", "") or (game.away if fav_is_home else game.home)
    fav_margin = home_margin if fav_is_home else -home_margin
    need = math.floor(line) + 1
    p_fav = cover_chance(fav_margin, need, sd)
    says = f"{source.capitalize()} makes it {favourite} by {_points(fav_margin)}" \
        if fav_margin >= PICK_EM else f"{source.capitalize()} doesn't even have {favourite} favoured"
    detail = (
        f"{favourite} have to win by {need} or more to take this one, because a "
        f"win by exactly {_points(line)} goes to {underdog}. {says}, which clears {need} "
        f"about {p_fav:.0%} of the time."
    )
    if fav_margin < PICK_EM:
        short = f"{favourite} need {need}+ and aren't even favoured"
    elif p_fav > 0.5:
        short = f"{favourite} need {need}+ and are favoured by {_points(fav_margin)}"
    else:
        short = f"{favourite} need {need}+ but are favoured by only {_points(fav_margin)}"
    if p_fav > 0.5:
        return Prediction(favourite, p_fav, True, short, detail)
    return Prediction(underdog, 1 - p_fav, True, short, detail)


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


# ======================================================================
# The rest of the pool
# ======================================================================
# A pick'em pool takes the favourite more often than the favourite wins, and
# more so the bigger the number. Published pools sit around 0.19 on this
# curve; measured over 22 unlined games of this pool's own raw pick sheets it
# came out at 0.49 - they are far chalkier than a public pool, with 89% on
# every favourite of three points or more. This is the measurement shrunk
# toward the published figure, because 22 games is not a season: it puts a
# 3-point favourite on 77% of cards against a 60% chance of winning, and a
# 7-point one on 94%. The practical meaning is that an unlined game has no
# leverage in it at all.
CROWD_SLOPE = 0.40
# On a game with a pool line the crowd mostly ignores the line and takes the
# better team anyway - measured at 72.6% over ten lined games, with a range
# of 40% to 83%. This is where that starts before a pool's own habit is
# measured, and how many lined games it takes for the measurement to lead.
CHALK_PRIOR = 0.73
CHALK_WEIGHT = 8


def crowd_on_favourite(spread: float) -> float:
    """The share of a pick'em pool expected to take a favourite this big."""
    return 1 / (1 + math.exp(-CROWD_SLOPE * abs(spread)))


def pool_chalk(season: Season) -> tuple[float, int]:
    """(share of this pool that takes the favourite on a lined game, games seen).

    Worked backwards out of the sheets: on a decided game the players still
    holding a pick are the ones who were right, so the share who took the
    pool's favourite is either that share or its complement, depending on
    which way the game went. Shrunk toward CHALK_PRIOR, because a handful of
    lined games is not a habit yet.
    """
    shares = []
    for number, game in lined_games(season):
        if not game.played:
            continue
        players = list(season.weeks[number].lines.values())
        if not players:
            continue
        right = sum(
            1 for entry in players
            if _same(entry.correct_picks.get(game.index), game.winner)
        )
        share = right / len(players)
        shares.append(share if _same(game.winner, game.line_favourite) else 1 - share)
    if not shares:
        return CHALK_PRIOR, 0
    seen = len(shares)
    measured = statistics.fmean(shares)
    return (seen * measured + CHALK_WEIGHT * CHALK_PRIOR) / (seen + CHALK_WEIGHT), seen


def leverage(chance: float, share: float) -> float:
    """Games gained on the average card by making this pick.

    Being right when everyone else is right wins nothing; the whole of the
    gain on the field is the chance of being right minus the share of the
    pool already on that side. It is why a 55% pick that 20% of the pool
    holds is worth more than an 80% pick that 85% of them hold.
    """
    return chance - share


@dataclass(frozen=True)
class Scorecard:
    """How the picks have actually done, against how they said they would."""

    hits: int
    picks: int
    expected: float      # the chances added up: how many it thought it would get
    weeks: int
    lined_hits: int = 0  # of those, the ones played under the pool's line rule
    lined_picks: int = 0

    @property
    def straight_hits(self) -> int:
        """Games picked the ordinary way - who wins, full stop."""
        return self.hits - self.lined_hits

    @property
    def straight_picks(self) -> int:
        return self.picks - self.lined_picks

    @property
    def rate(self) -> float:
        return self.hits / self.picks if self.picks else 0.0

    @property
    def expected_rate(self) -> float:
        return self.expected / self.picks if self.picks else 0.0

    @property
    def surprise(self) -> float:
        """Hits above (or below) what it expected. Near zero is the goal.

        Below zero means the chances are too bold, above means too shy;
        either way, a dozen games is noise, so this needs most of a season
        before it means anything.
        """
        return self.hits - self.expected


def grade(entries: list[tuple[int, Prediction, str]]) -> Scorecard:
    """Score (week, prediction, who actually got the game) against the results.

    The two kinds of pick are counted apart, because they answer different
    questions. A straight game asks who wins and is directly comparable with
    anybody else's record; a lined game asks whether the favourite wins by
    more than the pool's number, which nothing outside this pool is even
    trying to answer. Adding them together and quoting one percentage
    flatters the total.
    """
    hits = sum(1 for _, guess, winner in entries if _same(guess.pick, winner))
    lined = [e for e in entries if e[1].against_line]
    return Scorecard(
        hits=hits,
        picks=len(entries),
        expected=sum(guess.chance for _, guess, _ in entries),
        weeks=len({week for week, _, _ in entries}),
        lined_hits=sum(1 for _, guess, winner in lined if _same(guess.pick, winner)),
        lined_picks=len(lined),
    )


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