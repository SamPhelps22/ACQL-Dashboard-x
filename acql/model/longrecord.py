"""The computer models' long record: each one's season totals since 2000.

The Prediction Tracker publishes, for every season, how each computer model
did over the whole of it: how often it had the winner, its record against the
spread, and how far its margins were from the results. The betting line is
scored on the same page, so is the middle of all the models, and so is the
site's own "computer adjusted line" - the line moved toward the models, which
is what the picks here do.

One page a season is kept in data/tracker (27 pages, 1.2 MB, fetched once by
hand; nothing here goes back for more). They are season totals. No single
game's forecast is in them, so they cannot say what a new way of averaging
the models would have done - only how each model, and the line beside it, did
over a year.

Three things are worked out:

    the record       each model over every season it was published, beside
                     the betting line over the same seasons
    carry-over       does a model that beat the others one season beat them
                     the next? If it does not, there is nothing to weight by.
    line and crowd   season by season: the betting line, the middle of the
                     models, and the line moved toward the models

No Qt here.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from ..store import data_dir

FOLDER_NAME = "tracker"
#: Games in a season before a model's season counts: it priced most of it.
MIN_GAMES = 150
#: A season's page is the whole season once its busiest row has this many games.
FULL_SEASON = 200
#: Seasons before a model is listed in the long record.
MIN_SEASONS = 3
#: A model's form going into a season is its last this-many full seasons (at least two of them).
FORM_SEASONS = 3
#: How many seasons count as "lately".
LATELY = 5

LINE, OPENING, MIDWEEK, ADJUSTED = "lineupdated", "lineopening", "linemidweek", "computeradjustedline"
MEDIAN, AVERAGE = "systemmedian", "systemaverage"
MARKET = (LINE, OPENING, MIDWEEK, ADJUSTED)
CROWD = (MEDIAN, AVERAGE)
#: The same system under a name the site cut short or changed.
SAME = {"turnoveradjregressio": "turnoveradjregression", "directorofinformationc": "directorofinformation",
        "computeradjustedli": "computeradjustedline"}
#: The weekly file's short names (computers.py), as the season pages write them.
CODES = {
    "sag": "Sagarin Rating", "sagr": "Sagarin Recent", "sagpred": "Sagarin Points", "saggm": "Sagarin Golden Mean",
    "mass": "Massey Ratings", "pi": "Pi-Rate Ratings", "pim": "Pi-Rate Mean", "pib": "Pi-Rate Bias",
    "donchess": "Donchess Inference", "dok": "Dokter Entropy", "bihl": "Bihl Rankings", "rwp": "Laffaye RWP",
    "excel": "RP Excel", "gt": "Game Time Decision", "pve": "PvE Sports Ratings", "betbetter": "Bet Better",
    "talis": "Talisman Red", "clean": "Cleanup Hitter", "hanson": "Dan Hanson", "nfelo": "NFELO",
    "dwig": "Dwiggins", "blitz": "Statblitz Index", "ffw": "FF-Winners", "stjohn": "Lou St. John",
    "espn": "ESPN FPI", "pfz": "PerformanZ Ratings", "l1": "Least Abs. Val Reg", "l2": "Least Squares",
    "l2to": "Turnover Adj. regression", "l2h": "LS - w/ team HFA", "johnson": "Roger Johnson",
    "curry": "Daniel Curry Index", "ash": "Ashby AccuRatings", "moore": "Sonny Moore", "pyth": "Pythagorean Ratings",
    "pig": "Pigskin Index", "elo": "Beck Elo", "eff": "Scoring Effeciency", "log": "Logistic Regression",
    "kerns": "Stephen Kerns", "coff": "John Coffey", "ppg": "Points Per Game", "teamrank": "TeamRankings.com",
    "dunk": "Dunkel Index", "doi": "Director of Information", "kam": "Kambour Rating", "newbury": "Max Newbury",
    "congrove": "Congrove Computer Ranking", "midweek": "Line (Midweek)",
}


def key_of(name: str) -> str:
    """A system's name with only its letters and digits, so one season's spelling finds another's."""
    plain = "".join(c for c in str(name).casefold() if c.isalnum())
    return SAME.get(plain, plain)


def folder() -> Path:
    return data_dir() / FOLDER_NAME


# ---- reading the pages --------------------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    """One system, one season, as the site scored it."""

    season: int
    name: str
    winners: float              # share of games it had the winner
    cover: float                # share of games it was on the right side of the spread
    miss: float                 # its average miss, in points
    bias: float                 # its average error: plus is too kind to home teams
    games: int
    ats_won: int
    ats_lost: int

    @property
    def key(self) -> str:
        return key_of(self.name)


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def parse(text: str, season: int) -> list[Row]:
    """The rows of one season's page."""
    start = text.find("results_table")
    out = []
    for row in _ROW.findall(text[start:] if start >= 0 else text):
        cells = [" ".join(_TAG.sub("", c).split()) for c in _CELL.findall(row)]
        if len(cells) != 12:
            continue
        try:
            out.append(Row(season, cells[1], float(cells[2]), float(cells[3]), float(cells[4]), float(cells[5]),
                           int(cells[7]), int(cells[10]), int(cells[11])))
        except ValueError:
            continue
    return out


_LOADED: dict[str, tuple[tuple, dict[int, list[Row]]]] = {}


def seasons(where: Path | None = None) -> dict[int, list[Row]]:
    """Every saved season, read once until the files change."""
    where = where or folder()
    try:
        files = sorted(where.glob("nflresults-*.html"))
        stamp = tuple((f.name, f.stat().st_size, f.stat().st_mtime) for f in files)
    except OSError:
        return {}
    kept = _LOADED.get(str(where))
    if kept is not None and kept[0] == stamp:
        return kept[1]
    out: dict[int, list[Row]] = {}
    for path in files:
        try:
            year = int(path.stem[-4:])
            rows = parse(path.read_text(encoding="utf-8", errors="replace"), year)
        except (OSError, ValueError):
            continue
        if rows:
            out[year] = rows
    _LOADED[str(where)] = (stamp, out)
    return out


def _full(rows: list[Row]) -> bool:
    return max((r.games for r in rows), default=0) >= FULL_SEASON


def _models(rows: list[Row]) -> list[Row]:
    """The computer models that priced most of a season - no lines, no averages of the others."""
    return [r for r in rows if r.key not in MARKET + CROWD and r.games >= MIN_GAMES]


def _row(rows: list[Row], key: str) -> Row | None:
    return next((r for r in rows if r.key == key), None)


def _line(rows: list[Row]) -> Row | None:
    """The betting line a season is measured against: as it closed, else as it opened."""
    return _row(rows, LINE) or _row(rows, OPENING)


# ---- the record ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Career:
    key: str
    name: str
    seasons: int
    first: int
    last: int
    games: int
    miss: float                 # average miss over all of it
    line_miss: float            # the betting line's, over the same seasons
    ahead: int                  # seasons it was closer than the line...
    of: int                     # ...of the seasons the line was scored too
    ats_won: int
    ats_lost: int
    current: bool               # still published this season

    @property
    def edge(self) -> float:
        """Points closer than the betting line, on average (minus: further away)."""
        return self.line_miss - self.miss

    @property
    def cover(self) -> float:
        played = self.ats_won + self.ats_lost
        return self.ats_won / played if played else 0.0


def careers(found: dict[int, list[Row]]) -> list[Career]:
    """Each model over every full season it priced, best against the line first."""
    latest = max(found, default=0)
    current = {r.key for r in found.get(latest, [])}
    by_key: dict[str, list[tuple[Row, Row | None]]] = {}
    for year in sorted(found):
        rows = found[year]
        if not _full(rows):
            continue
        line = _line(rows)
        for r in _models(rows):
            by_key.setdefault(r.key, []).append((r, line))
    out = []
    for key, pairs in by_key.items():
        lined = [(r, line) for r, line in pairs if line is not None]
        if len(pairs) < MIN_SEASONS or not lined:
            continue
        games = sum(r.games for r, _ in pairs)
        weight = sum(r.games for r, _ in lined)
        out.append(Career(
            key=key, name=pairs[-1][0].name, seasons=len(pairs), first=pairs[0][0].season, last=pairs[-1][0].season,
            games=games,
            miss=sum(r.miss * r.games for r, _ in lined) / weight,
            line_miss=sum(line.miss * r.games for r, line in lined) / weight,
            ahead=sum(1 for r, line in lined if r.miss < line.miss), of=len(lined),
            ats_won=sum(r.ats_won for r, _ in pairs), ats_lost=sum(r.ats_lost for r, _ in pairs),
            current=key in current,
        ))
    out.sort(key=lambda c: (-c.edge, c.name))
    return out


# ---- carry-over ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class CarryOver:
    """Whether being better than the other models one season says anything about the next."""

    pairs: int = 0                      # model-seasons followed into the season after
    miss_r: float | None = None         # how much of a season's standing on miss carries over (0 none, 1 all)
    cover_r: float | None = None        # the same for the record against the spread
    top_was: float | None = None        # the closest quarter of one season: points closer than the typical model...
    top_next: float | None = None       # ...and how much closer the same models were the season after
    cover_was: float | None = None      # the best quarter against the spread one season: their share...
    cover_next: float | None = None     # ...and their share the season after
    hot_seasons: int = 0                # seasons last year's single closest model was followed
    hot_beat_typical: int = 0           # seasons it was closer than the typical model again
    hot_beat_line: int = 0              # seasons it was closer than the betting line

    @property
    def verdict(self) -> str:
        """"none", "some" or "strong": what past form is worth."""
        if self.miss_r is None:
            return "none"
        return "strong" if self.miss_r >= 0.5 else "some" if self.miss_r >= 0.2 else "none"


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 8:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-12 or syy <= 1e-12:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sxx * syy) ** 0.5


def carry_over(found: dict[int, list[Row]]) -> CarryOver:
    years = [y for y in sorted(found) if _full(found[y])]
    # each model's standing in a season: points closer than that season's typical model (plus is better)
    standing: dict[int, dict[str, float]] = {}
    covers: dict[int, dict[str, float]] = {}
    for year in years:
        models = _models(found[year])
        if len(models) < 8:
            continue
        typical = statistics.median(r.miss for r in models)
        standing[year] = {r.key: typical - r.miss for r in models}
        covers[year] = {r.key: r.cover for r in models if r.ats_won + r.ats_lost >= MIN_GAMES}
    was, then, cover_was, cover_then = [], [], [], []
    top_was, top_then, best_was, best_then = [], [], [], []
    hot = beat_typical = beat_line = 0
    for year in years:
        if year not in standing or year + 1 not in standing:
            continue
        now, after = standing[year], standing[year + 1]
        shared = sorted(now.keys() & after.keys())
        was += [now[k] for k in shared]
        then += [after[k] for k in shared]
        quarter = sorted(shared, key=lambda k: -now[k])[:max(1, len(shared) // 4)]
        top_was += [now[k] for k in quarter]
        top_then += [after[k] for k in quarter]
        both = sorted(covers[year].keys() & covers[year + 1].keys())
        cover_was += [covers[year][k] for k in both]
        cover_then += [covers[year + 1][k] for k in both]
        best = sorted(both, key=lambda k: -covers[year][k])[:max(1, len(both) // 4)]
        best_was += [covers[year][k] for k in best]
        best_then += [covers[year + 1][k] for k in best]
        if shared:
            leader = max(shared, key=lambda k: now[k])
            hot += 1
            beat_typical += after[leader] > 0
            line, row = _line(found[year + 1]), _row(found[year + 1], leader)
            beat_line += line is not None and row is not None and row.miss < line.miss
    if not was:
        return CarryOver()
    return CarryOver(
        pairs=len(was), miss_r=_correlation(was, then), cover_r=_correlation(cover_was, cover_then),
        top_was=statistics.fmean(top_was), top_next=statistics.fmean(top_then),
        cover_was=statistics.fmean(best_was) if best_was else None,
        cover_next=statistics.fmean(best_then) if best_then else None,
        hot_seasons=hot, hot_beat_typical=beat_typical, hot_beat_line=beat_line,
    )


def form(found: dict[int, list[Row]], before: int, seasons: int = FORM_SEASONS) -> dict[str, float]:
    """Each model's form going into a season: points closer than the typical
    model (plus is better), averaged over the full seasons just before it.
    Nothing from `before` on is looked at, so it can be used to choose models
    for that season without having seen it."""
    years = [y for y in sorted(found) if y < before and _full(found[y])][-seasons:]
    marks: dict[str, list[float]] = {}
    for year in years:
        models = _models(found[year])
        if len(models) < 8:
            continue
        typical = statistics.median(r.miss for r in models)
        for r in models:
            marks.setdefault(r.key, []).append(typical - r.miss)
    return {key: statistics.fmean(values) for key, values in marks.items() if len(values) >= min(2, seasons)}


# ---- the line and the crowd, season by season ---------------------------------------------------
@dataclass(frozen=True)
class SeasonLine:
    season: int
    models: int                         # computer models that priced most of it
    line: float | None                  # the betting line's average miss
    median: float | None                # the middle of the models'
    adjusted: float | None              # the line moved toward the models (the site's own)
    adjusted_ats: tuple[int, int] | None    # ...and its record against the line
    ahead: int                          # models closer than the line
    best: str                           # the closest model
    best_miss: float | None


def by_season(found: dict[int, list[Row]]) -> list[SeasonLine]:
    out = []
    for year in sorted(found):
        rows = found[year]
        if not _full(rows):
            continue
        models, line = _models(rows), _line(rows)
        median, adjusted = _row(rows, MEDIAN), _row(rows, ADJUSTED)
        best = min(models, key=lambda r: r.miss, default=None)
        out.append(SeasonLine(
            season=year, models=len(models), line=line.miss if line else None,
            median=median.miss if median else None, adjusted=adjusted.miss if adjusted else None,
            adjusted_ats=(adjusted.ats_won, adjusted.ats_lost) if adjusted else None,
            ahead=sum(1 for r in models if line is not None and r.miss < line.miss),
            best=best.name if best else "", best_miss=best.miss if best else None,
        ))
    return out


# ---- the whole of it ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Record:
    careers: list[Career] = field(default_factory=list)
    carry: CarryOver = CarryOver()
    seasons: list[SeasonLine] = field(default_factory=list)
    first: int = 0
    last: int = 0
    form: dict[str, float] = field(default_factory=dict)       # each model's form going into the season after `last`

    def standing(self, code: str) -> float | None:
        """One of the weekly file's models going into this season: points closer than
        the typical model over its last few seasons (None: no long record)."""
        name = CODES.get(code)
        return self.form.get(key_of(name)) if name else None

    def career(self, code: str) -> Career | None:
        """The long record of one of the weekly file's models, by its short name there."""
        name = CODES.get(code)
        key = key_of(name) if name else ""
        return next((c for c in self.careers if c.key == key), None) if key else None

    @property
    def model_seasons(self) -> tuple[int, int]:
        """(model-seasons closer than the line, model-seasons in all)."""
        return sum(s.ahead for s in self.seasons if s.line is not None), \
            sum(s.models for s in self.seasons if s.line is not None)

    @property
    def crowd(self) -> tuple[int, int, float] | None:
        """(seasons the models' middle was closer than the line, seasons with both, its average edge)."""
        both = [s for s in self.seasons if s.line is not None and s.median is not None]
        if not both:
            return None
        return (sum(1 for s in both if s.median < s.line), len(both),
                statistics.fmean(s.line - s.median for s in both))

    @property
    def nudged(self) -> tuple[int, int, float, int, int] | None:
        """The line moved toward the models: (seasons closer than the line, seasons, average edge,
        games on the right side of the line, games on the wrong side)."""
        both = [s for s in self.seasons if s.line is not None and s.adjusted is not None]
        if not both:
            return None
        won = sum(s.adjusted_ats[0] for s in both if s.adjusted_ats)
        lost = sum(s.adjusted_ats[1] for s in both if s.adjusted_ats)
        return (sum(1 for s in both if s.adjusted < s.line), len(both),
                statistics.fmean(s.line - s.adjusted for s in both), won, lost)

    @property
    def nudged_lately(self) -> tuple[int, int, int] | None:
        """The line moved toward the models over the last few seasons: (right side of the line, wrong side, seasons)."""
        both = [s for s in self.seasons if s.adjusted_ats][-LATELY:]
        if not both:
            return None
        return sum(s.adjusted_ats[0] for s in both), sum(s.adjusted_ats[1] for s in both), len(both)


def build(where: Path | None = None) -> Record:
    found = seasons(where)
    full = [y for y in sorted(found) if _full(found[y])]
    if not full:
        return Record()
    return Record(careers(found), carry_over(found), by_season(found), full[0], full[-1],
                  form(found, full[-1] + 1))
