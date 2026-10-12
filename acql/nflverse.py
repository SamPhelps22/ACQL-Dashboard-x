"""Football of its own: nflverse's game and team files, and what they are worth.

Everything Deadeye knew about football before this came from final scores
and other people's models. nflverse (github.com/nflverse/nflverse-data) keeps,
free and in plain files, what scores leave out: for every game since 1999 the
closing betting line and total, each side's days of rest and whether it was a
division game; and for every team in every week how well it actually moved
the ball - expected points added a play, yards a play, turnovers - and how
well it stopped the other side doing the same.

With those, three kinds of model can at last be set against each other over
many seasons rather than one:

    Market      the closing betting line and nothing else
    Football    the ratings, each team's efficiency over its last eight
                games, rest and the rest - and no line at all
    Hybrid      the closing line, with the football on top

Each season is predicted by models taught on the seasons before it only
(walk-forward), so no number here was fitted to the games it is scored on.
Every input is from before the game: a team's efficiency is over games it
had already played. Who started at quarterback is in the file but left out -
it is known at kickoff, not when a card goes in on Thursday.

The files live in data/nflverse (fetched by hand, 1.6 MB); nothing here
goes online. No Qt here.
"""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict, deque
from dataclasses import asdict, dataclass

import numpy as np

from . import analytics, backtest, contenders
from .config import DATA_DIR

FOLDER = DATA_DIR / "nflverse"
GAMES_FILE = "games.csv.gz"
TEAM_FILE = "stats_team_week_{season}.csv.gz"
#: Teams that moved keep their history under the name they have now.
MOVED = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
#: The first season with team files fetched; the one before it only warms the ratings up.
FIRST = 2011
#: A team's form is its last this-many games, last season's included.
WINDOW = 8
#: ...and it needs this many before its form is read at all.
ENOUGH = 3
#: Seasons to be taught on before the first one asked about.
TAUGHT_FIRST = 3
#: Against the spread, a side is only taken when the model is this far from the line...
EDGE = 0.5
#: ...and "a real disagreement" is this far.
BIG_EDGE = 2.0
#: What a bet at the usual price has to win to break even.
BREAK_EVEN = 0.524
MARKET, RATINGS, FOOTBALL, TREES, HYBRID = "Market", "Ratings alone", "Football", "Football (trees)", "Hybrid"
KINDS = (MARKET, RATINGS, FOOTBALL, TREES, HYBRID)
KIND, KEY = "modellab", "families"

FOOTBALL_INPUTS = ("ratings margin", "attack: points added a play", "defence: points added a play allowed",
                   "attack: yards a play", "defence: yards a play allowed", "turnovers a game",
                   "rest (days)", "division game", "neutral site", "week", "games of form")


def available() -> bool:
    return (FOLDER / GAMES_FILE).is_file()


def _rows(name: str) -> list[dict]:
    with gzip.open(FOLDER / name, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _team(code: str) -> str:
    return MOVED.get(code, code)


def _number(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Played:
    """One regular-season game with a result and a closing line."""

    season: int
    week: int
    game: str
    home: str
    away: str
    margin: float           # home score minus away score
    spread: float           # the closing line, home side (+ favoured)
    rest: float             # home days of rest minus the road side's
    division: bool
    neutral: bool


def games(first: int = FIRST - 1) -> list[Played]:
    """Every regular-season game from `first` on that has been played and had a line."""
    out = []
    for row in _rows(GAMES_FILE):
        season = int(row["season"])
        if season < first or row["game_type"] != "REG" or not row["home_score"] or not row["spread_line"]:
            continue
        out.append(Played(
            season=season, week=int(row["week"]), game=row["game_id"],
            home=_team(row["home_team"]), away=_team(row["away_team"]),
            margin=_number(row["home_score"]) - _number(row["away_score"]), spread=_number(row["spread_line"]),
            rest=_number(row["home_rest"]) - _number(row["away_rest"]),
            division=row["div_game"] == "1", neutral=row["location"].strip().casefold() == "neutral",
        ))
    return sorted(out, key=lambda g: (g.season, g.week, g.game))


def routs(first: int = analytics.ROUT_SEASONS[0], last: int = analytics.ROUT_SEASONS[1]) -> tuple[list[float], list[bool]]:
    """Every team's closing spread (+ favoured) and whether it lost by 15 or more,
    both teams of every game from `first` to `last` - what analytics.rout_fit is taught on."""
    played = [g for g in games(first) if g.season <= last]
    bar = analytics.BIG_LOSER_MARGIN + 1
    return ([g.spread for g in played] + [-g.spread for g in played],
            [g.margin <= -bar for g in played] + [g.margin >= bar for g in played])


def team_games(seasons) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    """{(game, team): (plays, points added, yards, turnovers)} - what a team's attack did in a game."""
    out = {}
    for season in seasons:
        try:
            rows = _rows(TEAM_FILE.format(season=season))
        except OSError:
            continue
        for row in rows:
            if row.get("season_type") != "REG":
                continue
            plays = _number(row["attempts"]) + _number(row["sacks_suffered"]) + _number(row["carries"])
            out[(row["game_id"], _team(row["team"]))] = (
                plays,
                _number(row["passing_epa"]) + _number(row["rushing_epa"]),
                _number(row["passing_yards"]) + _number(row["rushing_yards"]),
                _number(row["passing_interceptions"]) + _number(row["sack_fumbles_lost"])
                + _number(row["rushing_fumbles_lost"]) + _number(row["receiving_fumbles_lost"]),
            )
    return out


def _form(recent: deque) -> tuple[float, float, float, float, float, int]:
    """A team's last few games as rates: (attack points added a play, the same
    allowed, attack yards a play, yards a play allowed, turnovers a game - its
    own less the other side's - and how many games that rests on)."""
    n = len(recent)
    if n < ENOUGH:
        return 0.0, 0.0, 0.0, 0.0, 0.0, n
    plays = sum(g[0] for g in recent) or 1.0
    against = sum(g[4] for g in recent) or 1.0
    return (sum(g[1] for g in recent) / plays, sum(g[5] for g in recent) / against,
            sum(g[2] for g in recent) / plays, sum(g[6] for g in recent) / against,
            (sum(g[3] for g in recent) - sum(g[7] for g in recent)) / n, n)


def table() -> tuple[list[Played], np.ndarray]:
    """Every game from FIRST on with what was known before it: (the games, one
    row of FOOTBALL_INPUTS each). Ratings and form are walked forward game by
    game, so nothing in a row comes from the game it describes."""
    every = games()
    attack = team_games(sorted({g.season for g in every}))
    teams: dict[str, float] = defaultdict(float)
    edge = backtest.HOME_EDGE_START
    recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
    kept, rows, season = [], [], None
    for g in every:
        if g.season != season:
            for t in teams:
                teams[t] *= 1 - backtest.PRESEASON_REGRESSION
            season = g.season
        rated = teams[g.home] - teams[g.away] + (0.0 if g.neutral else edge)
        if g.season >= FIRST:
            h, a = _form(recent[g.home]), _form(recent[g.away])
            kept.append(g)
            rows.append([rated, h[0] - a[0], h[1] - a[1], h[2] - a[2], h[3] - a[3], h[4] - a[4],
                         g.rest, float(g.division), float(g.neutral), float(g.week), float(min(h[5], a[5]))])
        miss = max(-backtest.ERROR_CAP, min(backtest.ERROR_CAP, g.margin - rated))
        teams[g.home] += backtest.RATING_STEP * miss
        teams[g.away] -= backtest.RATING_STEP * miss
        if not g.neutral:
            edge += backtest.HOME_EDGE_STEP * miss
        mine, theirs = attack.get((g.game, g.home)), attack.get((g.game, g.away))
        if mine is not None and theirs is not None:
            recent[g.home].append(mine + theirs)
            recent[g.away].append(theirs + mine)
    return kept, np.array(rows)


# ---- the three kinds, season by season ----------------------------------------------------------
@dataclass(frozen=True)
class Line:
    """One kind of model over one season (or all of them) it had not seen."""

    kind: str
    season: int             # 0 for every season together
    games: int = 0          # games with a winner
    winners: int = 0
    miss: float = 0.0       # average miss on the margin, points
    bets: int = 0           # games it stood at least EDGE from the closing line (pushes left out)
    covers: int = 0
    big_bets: int = 0       # ...and at least BIG_EDGE from it
    big_covers: int = 0

    @property
    def rate(self) -> float:
        return self.winners / self.games if self.games else 0.0

    @property
    def cover_rate(self) -> float | None:
        return self.covers / self.bets if self.bets else None

    @property
    def big_rate(self) -> float | None:
        return self.big_covers / self.big_bets if self.big_bets else None


def _score(kind: str, season: int, guess: np.ndarray, margin: np.ndarray, spread: np.ndarray) -> Line:
    decided = margin != 0
    lean = guess - spread
    result = margin - spread
    out = {}
    for name, bar in (("", EDGE), ("big_", BIG_EDGE)):
        taken = (np.abs(lean) >= bar) & (result != 0)
        out[name + "bets"] = int(taken.sum())
        out[name + "covers"] = int(((lean > 0) == (result > 0))[taken].sum())
    return Line(kind, season, int(decided.sum()), int(((guess > 0) == (margin > 0))[decided].sum()),
                float(np.abs(guess - margin).mean()), **out)


def _total(kind: str, lines: list[Line]) -> Line:
    mine = [line for line in lines if line.kind == kind]
    played = sum(line.games for line in mine) or 1
    return Line(kind, 0, sum(l.games for l in mine), sum(l.winners for l in mine),
                sum(l.miss * l.games for l in mine) / played, sum(l.bets for l in mine),
                sum(l.covers for l in mine), sum(l.big_bets for l in mine), sum(l.big_covers for l in mine))


@dataclass(frozen=True)
class Families:
    lines: list[Line]               # every kind in every season, then every kind over all of them (season 0)
    weights: dict[str, float]       # what the hybrid, taught on everything, puts on each input

    @property
    def seasons(self) -> list[int]:
        return sorted({line.season for line in self.lines if line.season})

    def of(self, kind: str, season: int = 0) -> Line | None:
        return next((l for l in self.lines if l.kind == kind and l.season == season), None)


def walk_forward() -> Families:
    """Market, football and hybrid over every season from the fourth on, each
    taught on the seasons before it. Several seconds; kept once made (families)."""
    played, X = table()
    S = np.array([g.season for g in played])
    y = np.array([g.margin for g in played])
    spread = np.array([g.spread for g in played])
    both = np.hstack([spread[:, None], X])
    lines: list[Line] = []
    for season in sorted(set(S.tolist()))[TAUGHT_FIRST:]:
        before, now = S < season, S == season
        guesses = {MARKET: spread[now], RATINGS: X[now][:, 0]}
        mean, scale, weights, constant = contenders.ridge(X[before], y[before])
        guesses[FOOTBALL] = ((X[now] - mean) / scale) @ weights + constant
        start, trees = contenders.boost(X[before], y[before])
        guesses[TREES] = start + contenders.LEARNING_RATE * sum(contenders._leaves(t, X[now]) for t in trees)
        mean, scale, weights, constant = contenders.ridge(both[before], y[before])
        guesses[HYBRID] = ((both[now] - mean) / scale) @ weights + constant
        lines += [_score(kind, int(season), guess, y[now], spread[now]) for kind, guess in guesses.items()]
    lines += [_total(kind, lines) for kind in KINDS]
    # what the hybrid leans on, taught on every season: each input's weight for one spread of that input
    mean, scale, weights, _constant = contenders.ridge(both, y)
    leaning = dict(zip(("the closing line",) + FOOTBALL_INPUTS, (float(w) for w in weights)))
    return Families(lines, leaning)


def families(compute: bool = False) -> Families | None:
    """The record as kept, worked out first when `compute` and there is none
    for these files. None when the files aren't there, or it wasn't asked for."""
    if not available():
        return None
    from . import store
    # the files as they are, and the kinds as they are: either changing makes the kept record stale
    size = sum((FOLDER / name).stat().st_size for name in sorted(p.name for p in FOLDER.glob("*.csv.gz")))
    stamp = f"{size}:{'/'.join(KINDS)}:{len(FOOTBALL_INPUTS)}"
    try:
        found = store.get(KIND, KEY, None)
    except Exception:  # noqa: BLE001
        found = None
    if isinstance(found, dict) and found.get("stamp") == stamp and found.get("lines"):
        names = set(Line.__dataclass_fields__)
        return Families([Line(**{k: v for k, v in row.items() if k in names}) for row in found["lines"]],
                        dict(found.get("weights") or {}))
    if not compute:
        return None
    made = walk_forward()
    try:
        store.put(KIND, KEY, {"stamp": stamp, "lines": [asdict(line) for line in made.lines], "weights": made.weights})
    except Exception:  # noqa: BLE001 - shown this once, worked out again next time
        pass
    return made


# ---- how each team is playing right now ---------------------------------------------------------
#: nflverse's abbreviations where they are not the dashboard's own code.
CODES = {"LA": "lar"}


@dataclass(frozen=True)
class TeamForm:
    """A team over its last few games (WINDOW), last season's included."""

    team: str               # the dashboard's code
    games: int
    attack: float           # expected points added a play, with the ball
    defence: float          # ...allowed a play (lower is better)
    yards: float            # yards a play
    yards_allowed: float
    turnovers: float        # giveaways less takeaways, a game (lower is better)
    attack_rank: int = 0    # 1 = the league's best
    defence_rank: int = 0

    @property
    def net(self) -> float:
        """Points added a play more than it allows."""
        return self.attack - self.defence


@dataclass(frozen=True)
class Efficiency:
    teams: dict[str, TeamForm]
    season: int             # the last game counted
    week: int
    window: int = WINDOW


_EFFICIENCY: dict = {}


def efficiency() -> Efficiency | None:
    """Every team's form as the files stand, or None without them. Read once per set of files."""
    from .predictions import team_code
    try:
        files = sorted(FOLDER.glob(TEAM_FILE.format(season="*")))
        stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files[-2:] + [FOLDER / GAMES_FILE])
    except OSError:
        return None
    if not files:
        return None
    if _EFFICIENCY.get("stamp") == stamp:
        return _EFFICIENCY["found"]
    seasons = sorted(int(f.name.split("_")[-1].split(".")[0]) for f in files)[-2:]
    attack = team_games(seasons)
    recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
    last = (0, 0)
    for g in games(first=seasons[0]):
        mine, theirs = attack.get((g.game, g.home)), attack.get((g.game, g.away))
        if mine is None or theirs is None:
            continue
        recent[g.home].append(mine + theirs)
        recent[g.away].append(theirs + mine)
        last = max(last, (g.season, g.week))
    forms = {team: _form(played) for team, played in recent.items()}
    ready = {team: form for team, form in forms.items() if form[5] >= ENOUGH}
    by_attack = sorted(ready, key=lambda team: -ready[team][0])
    by_defence = sorted(ready, key=lambda team: ready[team][1])
    teams = {}
    for team, form in ready.items():
        code = CODES.get(team) or team_code(team)
        if code:
            teams[code] = TeamForm(code, form[5], form[0], form[1], form[2], form[3], form[4],
                                   by_attack.index(team) + 1, by_defence.index(team) + 1)
    found = Efficiency(teams, last[0], last[1]) if teams else None
    _EFFICIENCY.update(stamp=stamp, found=found)
    return found
