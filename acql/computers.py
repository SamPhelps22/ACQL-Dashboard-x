"""The computer models, one by one.

The Prediction Tracker's weekly file has a column for every computer model
that priced a game. The picks read them as one crowd (predictions.py): the
wildest fifth at each end is dropped and the rest are averaged. That throws
each model's name away, so nothing could say which of them are any good,
which are copies of one another, or whether the crowd knows anything the
betting line does not.

This keeps the names. Each week's file is read again while it is still on
disk and every model's number is written down beside its game ("computers"
in the store) - only where the file still says what the week was priced
from, so a later copy of the file never rewrites a week already played.

From that, over the games already played:

    model by model    how far each was from the result, beside the betting
                      line on the same games
    the residual      when the models' middle sits a point off the line, how
                      much of that point turns up in the result
    ways to average   the middle the picks use, against a plain average, the
                      median and other trims
    look-alikes       models whose numbers move together, and how many
                      independent opinions the crowd really amounts to
    checks            a column that runs backwards, or a betting line that is
                      being counted as a model

Every margin is points for the home team of the week's own game. Every count
is small - a few dozen games - and is shown with the count beside it. Nothing
here changes a pick: it measures, and the Model Lab's rule decides.

No Qt here.
"""

from __future__ import annotations

import csv
import math
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import predictions, pricing, store
from .models import Season
from .predictions import team_code

KIND = "computers"
#: Played games before a model's own record is worth ranking it by.
MIN_GAMES = 30
#: Games two models both priced before their numbers are compared.
MIN_SHARED = 24
#: Games a column needs before it is checked for running backwards.
MIN_CHECK = 12
#: Two models whose views of the line move together this closely are one opinion.
LOOK_ALIKE = 0.90
#: A model has to have priced this share of the games to count toward the crowd's size.
COVERS = 0.9
#: Columns the file keeps among the models that are betting lines.
MARKET_LIKE = ("midweek",)
#: A column this close to the betting line, game after game, is a betting line.
SAME_AS_LINE = 0.25
#: The fewest games the residual is worked out on.
MIN_RESIDUAL = 8

#: The file's short names, spelled out where there is no doubt whose they are.
NAMES = {
    "sag": "Sagarin", "sagr": "Sagarin Recent", "sagpred": "Sagarin Predictor", "saggm": "Sagarin Golden Mean",
    "mass": "Massey", "nfelo": "nfelo", "espn": "ESPN FPI", "elo": "Elo", "pyth": "Pythagorean",
    "eff": "Scoring Efficiency", "log": "Logistic Regression", "teamrank": "TeamRankings", "dunk": "Dunkel",
    "moore": "Moore", "dok": "Dokter Entropy", "donchess": "Donchess", "talis": "Talisman Red", "pugh": "Pugh",
    "betbetter": "Bet Better", "gt": "Game Time Decision", "johnson": "Roger Johnson", "ash": "Ashby",
    "kam": "Kambour", "midweek": "Midweek betting line",
}


def label(code: str) -> str:
    """A model as the pages write it: "Sagarin (sag)", or the file's own short name."""
    name = NAMES.get(code)
    return f"{name} ({code})" if name else code.upper()


# ---- keeping the names --------------------------------------------------------------------------
def read_named(path: str | Path) -> dict[tuple[str, str], dict[str, float]]:
    """(road, home) -> {model: home margin}, for every game in a predictions
    file. The same columns predictions.read_csv counts as models."""
    skip = predictions.MARKET_COLUMNS + predictions.SUMMARY_COLUMNS
    out: dict[tuple[str, str], dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {(k or "").strip().casefold(): v for k, v in raw.items()}
            road, home = team_code(row.get("road", "")), team_code(row.get("home", ""))
            if not road or not home:
                continue
            named = {}
            for key, value in row.items():
                if not key.startswith("line") or key in skip or len(key) <= 4:
                    continue
                number = predictions._number(value)
                if number is not None:
                    named[key[4:]] = number
            out[(road, home)] = named
    return out


def _same(first: list[float], second: list[float]) -> bool:
    return len(first) == len(second) and all(abs(a - b) < 1e-6 for a, b in zip(first, second))


def keep() -> dict[int, int]:
    """Write down each stored week's models by name, while its file is still
    there to read. A game is kept only when the file's numbers for it are the
    ones the week was priced from. Returns {week: games kept}."""
    out: dict[int, int] = {}
    try:
        entries, kept = store.items("forecasts"), store.items(KIND)
    except store.StoreError:
        return out
    for key, entry in entries.items():
        if not isinstance(entry, dict) or not str(key).isdigit():
            continue
        source = Path(str(entry.get("source") or ""))
        try:
            if not source.is_file():
                continue
            rows = read_named(source)
        except (OSError, ValueError, csv.Error):
            continue
        games = []
        for row in entry.get("games", []):
            if not isinstance(row, dict):
                continue
            pair = (team_code(row.get("road", "")), team_code(row.get("home", "")))
            named = rows.get(pair)
            if not named or not _same(sorted(named.values()), sorted(float(v) for v in row.get("opinions") or ())):
                continue
            games.append({"road": pair[0], "home": pair[1], "named": named})
        if not games:
            continue
        before = kept.get(key) if isinstance(kept.get(key), dict) else {}
        if before.get("games") != games:
            try:
                store.put(KIND, str(key), {"source": source.name, "kept": time.time(), "games": games})
            except store.StoreError:
                continue
        out[int(key)] = len(games)
    return out


# ---- every game, with every model's number ------------------------------------------------------
@dataclass(frozen=True)
class Reading:
    """One game. Margins are points for the home team of the week's own game."""

    week: int
    index: int
    matchup: str
    line: float | None                  # the betting line
    middle: float | None                # the models' middle, as the picks take it
    apart: float | None                 # how far apart the models that count are
    opinions: tuple[float, ...]         # every model's number, smallest first
    named: dict[str, float] = field(default_factory=dict)       # model -> its number, where the names were kept
    deadeye: float | None = None        # the margin the picks were made from
    actual: float | None = None         # the final home margin, once played

    @property
    def gap(self) -> float | None:
        """How far the models' middle sits from the betting line."""
        return None if self.line is None or self.middle is None else self.middle - self.line


def readings(season: Season) -> list[Reading]:
    """Every game the models priced this season, played or not."""
    from . import ghost
    try:
        kept = store.items(KIND)
    except store.StoreError:
        kept = {}
    out: list[Reading] = []
    for number in sorted(season.weeks):
        week = season.weeks[number]
        games = sorted(week.games, key=lambda g: g.index)
        if not games:
            continue
        ctx = pricing.context(season, number, games)
        if not any(f.opinions for f in ctx.forecasts.values()):
            continue
        prices = {p.game.index: p for p in pricing.price_week(season, number, games, ctx)}
        finals = ghost._margins(season, number, week)
        entry = kept.get(str(number))
        names = {(g.get("road"), g.get("home")): g.get("named") or {}
                 for g in (entry.get("games", []) if isinstance(entry, dict) else [])}
        for game in games:
            f = ctx.forecasts.get(game.index)
            if f is None or not f.opinions:
                continue
            turn = 1.0 if team_code(game.home) == f.home_code else -1.0
            named = {code: turn * float(value) for code, value in names.get((f.road_code, f.home_code), {}).items()}
            price = prices.get(game.index)
            out.append(Reading(
                week=number, index=game.index, matchup=game.label,
                line=pricing.market_margin(game, f),
                middle=predictions.home_margin(game, f, f.consensus),
                apart=f.disagreement,
                opinions=tuple(sorted(turn * v for v in f.opinions)),
                named=named,
                deadeye=price.margin if price is not None else None,
                actual=float(finals[game.index]) if game.played and game.index in finals else None,
            ))
    return out


def _graded(found: list[Reading]) -> list[Reading]:
    return [r for r in found if r.actual is not None and r.line is not None]


def _miss(pairs) -> float:
    return statistics.fmean(abs(a - b) for a, b in pairs)


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


# ---- model by model -----------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceLine:
    code: str
    games: int                  # played games it priced
    of: int                     # played games any named model priced
    miss: float                 # its average miss, in points
    line_miss: float            # the betting line's, on the same games
    closer: int                 # games it was closer to the result than the line
    further: int
    cover: int                  # games it was on the right side of the line...
    cover_games: int            # ...of those where it differed from the line and the result did too
    winners: int                # games it had the winner...
    winner_games: int           # ...of those with a winner and a side taken
    lean: float                 # its average error: plus is too kind to home teams

    @property
    def edge(self) -> float:
        """Points closer than the line, on average (minus: further away)."""
        return self.line_miss - self.miss

    @property
    def ranked(self) -> bool:
        return self.games >= MIN_GAMES


def leaderboard(found: list[Reading]) -> list[SourceLine]:
    """Each named model over the games already played, best against the line first."""
    graded = [r for r in _graded(found) if r.named]
    out = []
    for code in sorted({code for r in graded for code in r.named}):
        mine = [r for r in graded if code in r.named]
        sided = [r for r in mine if r.named[code] != r.line and r.actual != r.line]
        won = [r for r in mine if r.actual and r.named[code]]
        out.append(SourceLine(
            code=code, games=len(mine), of=len(graded),
            miss=_miss((r.named[code], r.actual) for r in mine),
            line_miss=_miss((r.line, r.actual) for r in mine),
            closer=sum(1 for r in mine if abs(r.named[code] - r.actual) < abs(r.line - r.actual)),
            further=sum(1 for r in mine if abs(r.named[code] - r.actual) > abs(r.line - r.actual)),
            cover=sum(1 for r in sided if (r.named[code] > r.line) == (r.actual > r.line)),
            cover_games=len(sided),
            winners=sum(1 for r in won if (r.named[code] > 0) == (r.actual > 0)),
            winner_games=len(won),
            lean=statistics.fmean(r.named[code] - r.actual for r in mine),
        ))
    out.sort(key=lambda s: (not s.ranked, -s.edge, s.code))
    return out


# ---- the residual: does the crowd know anything the line does not? -------------------------------
@dataclass(frozen=True)
class Residual:
    """The result's distance from the line, against the models' distance from it."""

    games: int
    slope: float | None         # of each point the models sit off the line, how much shows in the result
    error: float | None         # the slope's standard error
    share: float                # the share of their view the picks take

    @property
    def low(self) -> float | None:
        return None if self.slope is None or self.error is None else self.slope - 2 * self.error

    @property
    def high(self) -> float | None:
        return None if self.slope is None or self.error is None else self.slope + 2 * self.error

    @property
    def verdict(self) -> str:
        """"more", "nothing", "all" or "open": what the games so far can say."""
        if self.low is None or self.high is None:
            return "open"
        if self.low > 0:
            return "more"               # the models add something the line lacks
        if self.high < self.share:
            return "nothing"            # even the top of the range is under the share in use
        return "open"

    @property
    def reading(self) -> str:
        if self.slope is None:
            return f"Too few games to say ({self.games} so far)."
        text = (f"For each point the models' middle sat away from the betting line, the result moved "
                f"{self.slope:+.2f} of a point their way. Over {self.games} games that could really be anywhere "
                f"from {self.low:+.2f} to {self.high:+.2f}. ")
        if self.verdict == "more":
            return text + "Even the low end is above zero, so the models are adding something the line lacks."
        if self.verdict == "nothing":
            return text + (f"Even the high end is under the {self.share:.2f} the picks give them, so they are "
                           "being trusted too much.")
        return text + ("That range takes in both zero (the line already knows what they know) and the "
                       f"{self.share:.2f} the picks give them, so the games so far cannot tell the two apart.")


def residual(found: list[Reading], share: float = predictions.CONSENSUS_WEIGHT) -> Residual:
    rows = [(r.gap, r.actual - r.line) for r in _graded(found) if r.gap is not None]
    n = len(rows)
    if n < MIN_RESIDUAL:
        return Residual(n, None, None, share)
    mx = statistics.fmean(x for x, _ in rows)
    my = statistics.fmean(y for _, y in rows)
    sxx = sum((x - mx) ** 2 for x, _ in rows)
    if sxx <= 1e-9:
        return Residual(n, None, None, share)
    slope = sum((x - mx) * (y - my) for x, y in rows) / sxx
    left = sum((y - my - slope * (x - mx)) ** 2 for x, y in rows)
    return Residual(n, slope, math.sqrt(left / (n - 2) / sxx), share)


# ---- ways to average them -----------------------------------------------------------------------
@dataclass(frozen=True)
class Way:
    name: str
    games: int
    miss: float
    closer: int                 # games closer to the result than the betting line
    cover: int                  # games on the right side of the line...
    cover_games: int            # ...of those where it and the result both left the line
    in_use: bool = False


def _middle(share: float):
    return lambda values: statistics.fmean(predictions.trimmed(values, share))


IN_USE = f"Middle {1 - 2 * predictions.TRIM_SHARE:.0%} (in use)"
WAYS = (
    (IN_USE, _middle(predictions.TRIM_SHARE)),
    ("Plain average", statistics.fmean),
    ("Median", statistics.median),
    ("Middle 80%", _middle(0.1)),
    ("Middle 40%", _middle(0.3)),
)
LINE_ROW = "The betting line"


def averages(found: list[Reading]) -> list[Way]:
    """Each way of boiling the models down to one number, on the same played games."""
    graded = [r for r in _graded(found) if len(r.opinions) >= predictions.MIN_KEPT]
    if not graded:
        return []
    out = []
    for name, way in WAYS:
        made = [(way(list(r.opinions)), r) for r in graded]
        sided = [(v, r) for v, r in made if v != r.line and r.actual != r.line]
        out.append(Way(
            name, len(graded), _miss((v, r.actual) for v, r in made),
            closer=sum(1 for v, r in made if abs(v - r.actual) < abs(r.line - r.actual)),
            cover=sum(1 for v, r in sided if (v > r.line) == (r.actual > r.line)),
            cover_games=len(sided), in_use=name == IN_USE,
        ))
    out.sort(key=lambda w: w.miss)
    out.append(Way(LINE_ROW, len(graded), _miss((r.line, r.actual) for r in graded), 0, 0, 0))
    return out


# ---- when they agree, and when they do not ------------------------------------------------------
@dataclass(frozen=True)
class Group:
    name: str
    games: int
    apart: float                # how far apart the models were, on average
    line_miss: float
    middle_miss: float


def by_agreement(found: list[Reading]) -> list[Group]:
    """The played games split in two by how far apart the models were."""
    graded = [r for r in _graded(found) if r.apart is not None and r.middle is not None]
    if len(graded) < 2 * MIN_RESIDUAL:
        return []
    cut = statistics.median(r.apart for r in graded)
    out = []
    for name, rows in (("The models agreed", [r for r in graded if r.apart <= cut]),
                       ("The models were split", [r for r in graded if r.apart > cut])):
        if rows:
            out.append(Group(name, len(rows), statistics.fmean(r.apart for r in rows),
                             _miss((r.line, r.actual) for r in rows), _miss((r.middle, r.actual) for r in rows)))
    return out


# ---- look-alikes --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Alike:
    pairs: list[tuple[str, str, float, int]] = field(default_factory=list)     # (model, model, how alike, games)
    crowd: int = 0              # models that priced nearly every game
    effective: float | None = None      # how many independent opinions they amount to
    games: int = 0              # games that was worked out on


def look_alikes(found: list[Reading]) -> Alike:
    """Which models say the same thing. Compared on their view of the line
    (their number less the betting line), so two models are not called alike
    just for both knowing that a good team is playing a bad one. Needs no
    results, so games still to be played count too."""
    rows = [r for r in found if r.line is not None and r.named]
    if not rows:
        return Alike()
    codes = sorted({code for r in rows for code in r.named})
    views = {code: {(r.week, r.index): r.named[code] - r.line for r in rows if code in r.named} for code in codes}
    pairs = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            shared = sorted(views[a].keys() & views[b].keys())
            if len(shared) < MIN_SHARED:
                continue
            r = _correlation([views[a][k] for k in shared], [views[b][k] for k in shared])
            if r is not None and r >= LOOK_ALIKE:
                pairs.append((a, b, r, len(shared)))
    pairs.sort(key=lambda p: (-p[2], p[0], p[1]))

    # How many opinions the crowd amounts to: the models that priced nearly
    # everything, on the games all of them priced.
    crowd = [c for c in codes if len(views[c]) >= COVERS * len(rows)]
    games = sorted(set.intersection(*(set(views[c]) for c in crowd))) if crowd else []
    effective = None
    if len(crowd) >= 3 and len(games) >= MIN_CHECK:
        import numpy as np
        table = np.array([[views[c][k] for k in games] for c in crowd], dtype=float)
        table = table[table.std(axis=1) > 1e-9]
        if len(table) >= 3:
            values = np.clip(np.linalg.eigvalsh(np.corrcoef(table)), 0.0, None)
            if values.sum() > 0:
                effective = float(values.sum() ** 2 / (values ** 2).sum())
    return Alike(pairs, len(crowd), effective, len(games))


# ---- checks -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Flag:
    code: str
    what: str                   # "backwards", "a betting line" or "far from the rest"
    detail: str


#: A model this far from the others' middle, on average, is on another scale.
FAR_OFF = 7.0


def checks(found: list[Reading]) -> list[Flag]:
    """Columns that should not be trusted as they stand."""
    rows = [r for r in found if r.line is not None and r.named]
    out = []
    for code in sorted({code for r in rows for code in r.named}):
        mine = [r for r in rows if code in r.named]
        if len(mine) < MIN_CHECK:
            continue
        off_line = statistics.fmean(abs(r.named[code] - r.line) for r in mine)
        if code in MARKET_LIKE or off_line < SAME_AS_LINE:
            out.append(Flag(code, "a betting line",
                            f"Sits {off_line:.1f} points from the betting line on average ({len(mine)} games). "
                            "It is a line, not a model."))
            continue
        r = _correlation([x.named[code] for x in mine], [x.line for x in mine])
        if r is not None and r < 0:
            out.append(Flag(code, "backwards",
                            f"Runs against the betting line over {len(mine)} games (correlation {r:+.2f}). "
                            "Its sign may be reversed."))
            continue
        middles = [x for x in mine if x.middle is not None]
        if middles:
            away = statistics.fmean(abs(x.named[code] - x.middle) for x in middles)
            if away > FAR_OFF:
                out.append(Flag(code, "far from the rest",
                                f"Sits {away:.1f} points from the other models' middle on average "
                                f"({len(middles)} games)."))
    return out


# ---- the whole page ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Report:
    found: list[Reading] = field(default_factory=list)
    week: int = 0                       # the week shown game by game
    board: list[SourceLine] = field(default_factory=list)
    ways: list[Way] = field(default_factory=list)
    residual: Residual = Residual(0, None, None, predictions.CONSENSUS_WEIGHT)
    groups: list[Group] = field(default_factory=list)
    alike: Alike = Alike()
    flags: list[Flag] = field(default_factory=list)

    @property
    def slate(self) -> list[Reading]:
        return [r for r in self.found if r.week == self.week]

    @property
    def graded(self) -> list[Reading]:
        return _graded(self.found)

    @property
    def named_graded(self) -> int:
        return sum(1 for r in self.graded if r.named)

    @property
    def weeks(self) -> list[int]:
        return sorted({r.week for r in self.found})

    @property
    def blend(self) -> tuple[float, int] | None:
        """(points the picks' own number is closer to the result than the line alone, games)."""
        rows = [r for r in self.graded if r.deadeye is not None]
        if not rows:
            return None
        return _miss((r.line, r.actual) for r in rows) - _miss((r.deadeye, r.actual) for r in rows), len(rows)


def build(season: Season) -> Report:
    """Everything the page shows. Catches up on any names still to be kept first."""
    try:
        keep()
    except Exception:  # noqa: BLE001 - the page stands on what is already kept
        pass
    found = readings(season)
    if not found:
        return Report()
    open_weeks = [r.week for r in found if r.actual is None]
    week = min(open_weeks) if open_weeks else max(r.week for r in found)
    try:
        share = pricing.model_weight(season)[0]
    except Exception:  # noqa: BLE001 - the share the picks start from
        share = predictions.CONSENSUS_WEIGHT
    return Report(found, week, leaderboard(found), averages(found), residual(found, share),
                  by_agreement(found), look_alikes(found), checks(found))
