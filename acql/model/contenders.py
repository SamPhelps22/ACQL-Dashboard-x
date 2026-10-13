"""Two more contenders for the Model Lab: the Analyst and the Machine.

Deadeye starts from the betting line. These two never see a line at all:
they are taught on every final score from 2011 to last season and then asked
about this season's games cold - so their record here is on games they had
not seen, which is the only record worth keeping.

    The Analyst   a regression: a straight-line weighting of the dashboard's
                  own team ratings and how each side has played lately
    The Machine   gradient-boosted trees on the very same inputs - a few
                  hundred small yes/no rules, each correcting the ones before

Both get the same eleven numbers about a game, all of them known before it
kicks off and all of them from final scores alone: what the ratings expect,
each team's rating, each team's average margin over its last four games and
in its last one, how many games each has played, and the week of the season.

They are here to be measured, not trusted: with nothing but scores to go on,
neither should be expected to beat a market that knows who is injured. If
one ever does over enough games, the Model Lab will say so.

No Qt here, and nothing but numpy.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from . import teamstrength
from ..models import Game, Season
from .predictions import team_code

ANALYST, MACHINE = "The Analyst", "The Machine"
#: Games of a team's recent form.
RECENT = 4
#: The first season is spent finding the ratings' feet, and is not taught from.
WARM_UP = 1
#: Nobody is ever expected to win by more than this.
MOST = 24.0
#: The regression's pull toward zero, so two inputs that say the same thing share the credit.
RIDGE = 25.0
#: The trees: how many, how much each one is trusted, how small a group one may split off.
TREES, LEARNING_RATE, MIN_LEAF, CUTS = 160, 0.05, 80, 15
#: Each tree is grown on this share of the games, chosen by a fixed draw so a
#: rebuild gives the same Machine.
SAMPLE, SEED = 0.7, 2011

INPUTS = ("ratings margin", "home rating", "road rating", "home last four", "road last four",
          "home last game", "road last game", "home games", "road games", "week", "form gap")


def _inputs(own: float, home_rating: float, away_rating: float, home: list[float], away: list[float],
            week: int) -> list[float]:
    h4 = sum(home) / len(home) if home else 0.0
    a4 = sum(away) / len(away) if away else 0.0
    return [own, home_rating, away_rating, h4, a4, home[-1] if home else 0.0, away[-1] if away else 0.0,
            float(len(home)), float(len(away)), float(week), h4 - a4]


# ---- the trees -----------------------------------------------------------------------------------
def _split(X: np.ndarray, r: np.ndarray, cuts: list[np.ndarray]):
    """The one yes/no question that best separates what is left to explain."""
    n, total = len(r), float(r.sum())
    best = (0.0, None, None)
    base = total * total / n
    for j, edges in enumerate(cuts):
        if not len(edges):
            continue
        left = X[:, j][:, None] <= edges[None, :]
        count = left.sum(axis=0)
        ok = (count >= MIN_LEAF) & (n - count >= MIN_LEAF)
        if not ok.any():
            continue
        s_left = (r[:, None] * left).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            gain = np.where(ok, s_left ** 2 / count + (total - s_left) ** 2 / (n - count) - base, -1.0)
        k = int(gain.argmax())
        if gain[k] > best[0]:
            best = (float(gain[k]), j, float(edges[k]))
    return best[1], best[2]


def _grow(X: np.ndarray, r: np.ndarray, cuts: list[np.ndarray], depth: int):
    """A small tree: (input, threshold, below, above), or just a number at a leaf."""
    if depth == 0 or len(r) < 2 * MIN_LEAF:
        return float(r.mean()) if len(r) else 0.0
    j, edge = _split(X, r, cuts)
    if j is None:
        return float(r.mean())
    below = X[:, j] <= edge
    return (j, edge, _grow(X[below], r[below], cuts, depth - 1), _grow(X[~below], r[~below], cuts, depth - 1))


def _leaf(tree, x) -> float:
    while isinstance(tree, tuple):
        tree = tree[2] if x[tree[0]] <= tree[1] else tree[3]
    return tree


def _leaves(tree, X: np.ndarray) -> np.ndarray:
    if not isinstance(tree, tuple):
        return np.full(len(X), tree)
    below = X[:, tree[0]] <= tree[1]
    out = np.empty(len(X))
    out[below] = _leaves(tree[2], X[below])
    out[~below] = _leaves(tree[3], X[~below])
    return out


def boost(X: np.ndarray, y: np.ndarray) -> tuple[float, list]:
    """Gradient boosting for squared error: (the starting guess, the trees)."""
    start = float(y.mean())
    guess = np.full(len(y), start)
    cuts = [np.unique(np.quantile(X[:, j], np.linspace(0.06, 0.94, CUTS))) for j in range(X.shape[1])]
    draw = np.random.default_rng(SEED)
    trees = []
    for _ in range(TREES):
        some = draw.random(len(y)) < SAMPLE
        tree = _grow(X[some], (y - guess)[some], cuts, depth=2)
        trees.append(tree)
        guess += LEARNING_RATE * _leaves(tree, X)
    return start, trees


def ridge(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """A regression with a pull toward zero: (each input's mean, its spread, its weight, the constant)."""
    mean, spread = X.mean(axis=0), X.std(axis=0)
    spread[spread == 0] = 1.0
    Z = (X - mean) / spread
    weights = np.linalg.solve(Z.T @ Z + RIDGE * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return mean, spread, weights, float(y.mean())


# ---- taught on the past -----------------------------------------------------------------------
@dataclass
class Taught:
    year: int
    games: int = 0                              # games they were taught on
    line: tuple | None = None                   # the Analyst
    start: float = 0.0                          # the Machine
    trees: list = field(default_factory=list)
    #: each team's last few margins as each week of this season began, and as they stand
    weeks: dict[int, dict[str, list[float]]] = field(default_factory=dict)
    latest: dict[str, list[float]] = field(default_factory=dict)

    def recent(self, week: int) -> dict[str, list[float]]:
        if week in self.weeks:
            return self.weeks[week]
        later = [w for w in self.weeks if w > week]
        return self.weeks[min(later)] if later else self.latest

    def margins(self, inputs: list[float]) -> tuple[float | None, float | None]:
        """(the Analyst's home margin, the Machine's) for a game's inputs."""
        if self.line is None:
            return None, None
        x = np.array(inputs)
        mean, spread, weights, constant = self.line
        analyst = float(((x - mean) / spread) @ weights + constant)
        machine = self.start + LEARNING_RATE * sum(_leaf(tree, x) for tree in self.trees)
        return max(-MOST, min(MOST, analyst)), max(-MOST, min(MOST, float(machine)))


_KEPT: dict[tuple, Taught] = {}


def teach(year: int) -> Taught:
    """Both contenders, taught on every season before `year`. Remembered until the history grows."""
    games = teamstrength.history(year)
    key = (year, len(games))
    if key in _KEPT:
        return _KEPT[key]
    rated, starts, _final, _last = teamstrength._walk(games)
    recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=RECENT))
    made = Taught(year)
    first = games[0][0] if games else year
    rows, answers = [], []
    season = week = None
    for s, w, home, away, margin in games:
        if s != season:
            recent.clear()                      # last season's form is last season's
            season, week = s, None
        if w != week:
            week = w
            if s == year:
                made.weeks[w] = {t: list(v) for t, v in recent.items()}
        if s < year and s >= first + WARM_UP:
            at = starts[(s, w)]
            rows.append(_inputs(rated[(s, w, frozenset((home, away)))], at.teams.get(home, 0.0),
                                at.teams.get(away, 0.0), list(recent[home]), list(recent[away]), w))
            answers.append(margin)
        recent[home].append(margin)
        recent[away].append(-margin)
    made.latest = {t: list(v) for t, v in recent.items()} if season == year else {}
    made.games = len(rows)
    if len(rows) >= 10 * MIN_LEAF:
        made.line, made.start, made.trees = _fitted(np.array(rows), np.array(answers))
    _KEPT.clear()
    _KEPT[key] = made
    return made


# ---- season by season: taught on the past, asked about the next -----------------------------------
KIND, SEASONS_KEY, TAUGHT_KEY = "modellab", "seasons", "taught"


def _as_tree(kept):
    """A tree as it was grown, from the lists the store keeps it as."""
    if not isinstance(kept, list):
        return float(kept)
    j, edge, below, above = kept
    return (int(j), float(edge), _as_tree(below), _as_tree(above))


def _fitted(X: np.ndarray, y: np.ndarray) -> tuple[tuple, float, list]:
    """(the Analyst's line, the Machine's start, its trees) for these games.

    Growing the trees takes a couple of seconds, and they are grown from past
    seasons only - which never change. So the fit is kept, marked with the
    exact games and settings it came from, and read back until either differs.
    """
    from .. import store
    settings = (TREES, LEARNING_RATE, MIN_LEAF, CUTS, SAMPLE, SEED, RIDGE)
    mark = hashlib.sha1(X.tobytes() + y.tobytes() + repr(settings).encode()).hexdigest()
    try:
        kept = store.get(KIND, TAUGHT_KEY, None)
        if isinstance(kept, dict) and kept.get("mark") == mark:
            mean, spread, weights, constant = kept["line"]
            return ((np.array(mean), np.array(spread), np.array(weights), float(constant)),
                    float(kept["start"]), [_as_tree(tree) for tree in kept["trees"]])
    except Exception:  # noqa: BLE001 - nothing kept that can be read: fit it again
        pass
    line = ridge(X, y)
    start, trees = boost(X, y)
    try:
        store.put(KIND, TAUGHT_KEY, {"mark": mark, "line": [line[0].tolist(), line[1].tolist(), line[2].tolist(), line[3]],
                                     "start": start, "trees": trees})
    except Exception:  # noqa: BLE001 - fitted again next session, that's all
        pass
    return line, start, trees
#: Seasons to be taught on before the first season it is asked about.
TAUGHT_FIRST = 3


@dataclass(frozen=True)
class SeasonLine:
    """One season none of them had seen: each one's winners and average miss."""

    season: int
    games: int                  # games with a winner
    ratings: int                # winners the ratings alone had
    analyst: int
    machine: int
    ratings_miss: float         # average miss on the margin, points
    analyst_miss: float
    machine_miss: float


def _all_rows(year: int):
    """(season, inputs, margin) for every game before `year` past the warm-up."""
    games = teamstrength.history(year)
    rated, starts, _final, _last = teamstrength._walk(games)
    recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=RECENT))
    first = games[0][0] if games else year
    out, season = [], None
    for s, w, home, away, margin in games:
        if s != season:
            recent.clear()
            season = s
        if first + WARM_UP <= s < year:
            at = starts[(s, w)]
            out.append((s, _inputs(rated[(s, w, frozenset((home, away)))], at.teams.get(home, 0.0),
                                   at.teams.get(away, 0.0), list(recent[home]), list(recent[away]), w), margin))
        recent[home].append(margin)
        recent[away].append(-margin)
    return out


def walk_forward(year: int) -> list[SeasonLine]:
    """Each past season in turn: both contenders taught on the seasons before
    it only, then asked about it. Takes several seconds - it is worked out
    once and kept (seasons)."""
    rows = _all_rows(year)
    if not rows:
        return []
    S = np.array([r[0] for r in rows])
    X = np.array([r[1] for r in rows])
    y = np.array([r[2] for r in rows])
    out = []
    for season in sorted(set(S.tolist()))[TAUGHT_FIRST:]:
        before, now = S < season, S == season
        if before.sum() < 6 * MIN_LEAF:
            continue
        mean, spread, weights, constant = ridge(X[before], y[before])
        start, trees = boost(X[before], y[before])
        own = X[now][:, 0]
        analyst = ((X[now] - mean) / spread) @ weights + constant
        machine = start + LEARNING_RATE * sum(_leaves(tree, X[now]) for tree in trees)
        actual = y[now]
        decided = actual != 0
        out.append(SeasonLine(
            season=int(season), games=int(decided.sum()),
            ratings=int(((own > 0) == (actual > 0))[decided].sum()),
            analyst=int(((analyst > 0) == (actual > 0))[decided].sum()),
            machine=int(((machine > 0) == (actual > 0))[decided].sum()),
            ratings_miss=float(np.abs(own - actual).mean()),
            analyst_miss=float(np.abs(analyst - actual).mean()),
            machine_miss=float(np.abs(machine - actual).mean()),
        ))
    return out


def seasons(year: int, compute: bool = False) -> list[SeasonLine] | None:
    """The season-by-season record as kept - worked out first when `compute`
    and there is none for this history. None when there is none and it wasn't asked for."""
    from dataclasses import asdict
    from .. import store
    stamp = len([g for g in teamstrength.history(year) if g[0] < year])
    try:
        found = store.get(KIND, SEASONS_KEY, None)
    except Exception:  # noqa: BLE001
        found = None
    if isinstance(found, dict) and found.get("games") == stamp and found.get("rows"):
        names = set(SeasonLine.__dataclass_fields__)
        return [SeasonLine(**{k: v for k, v in row.items() if k in names}) for row in found["rows"]]
    if not compute:
        return None
    made = walk_forward(year)
    try:
        store.put(KIND, SEASONS_KEY, {"games": stamp, "rows": [asdict(line) for line in made]})
    except Exception:  # noqa: BLE001 - shown this once, worked out again next time
        pass
    return made


def margins(season: Season | None, week: int, game: Game, year: int | None = None) -> tuple[float | None, float | None]:
    """(the Analyst's expected home margin, the Machine's) for a game of this
    season, from what was known as its week began. (None, None) for a team
    neither has ever seen."""
    from ..feeds import results
    year = year or results.season_year(season)
    taught = teach(year)
    strength = teamstrength.before(season, week, year)
    own = strength.margin(game.home, game.away)
    if own is None or taught.line is None:
        return None, None
    home, away = team_code(game.home), team_code(game.away)
    recent = taught.recent(week)
    return taught.margins(_inputs(own, strength.teams.get(home, 0.0), strength.teams.get(away, 0.0),
                                  recent.get(home, []), recent.get(away, []), week))
