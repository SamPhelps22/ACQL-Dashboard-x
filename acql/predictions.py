"""Model predictions for a week's games, read from a downloaded CSV.

The file is the one The Prediction Tracker publishes each week - a row per
game, a column per computer model, and then the market line and a few
summary columns:

    line        the betting line, from the HOME team's point of view, so
                +6.5 means the home team is favoured by 6.5
    lineopen    the opening line; lineca another book's number
    lineavg     the average of every model that priced the game
    linemedian  the middle model
    linestd     how far apart the models are - the spread of opinion
    phwin       the file's own chance the home team wins outright
    phcover     the file's own chance the home team covers the line

Everything in here is sign-consistent with that file: a positive number is
points in the HOME team's favour. Nothing in this module needs the file to
have any particular set of model columns; it reads what is there.

Two things come out of it. The market line fills in the Vegas spread that
the Next Week page otherwise has to be typed by hand, and the model average
gives a second opinion - where the models and the bookmakers disagree is
exactly where a pool line is worth a second look.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from .config import ROOT
from .lines import TEAMS
from .models import Game

FORECASTS_FILE = ROOT / "acql-forecasts.json"

# Columns that are not a model's prediction.
MARKET_COLUMNS = ("line", "lineca", "lineopen")
SUMMARY_COLUMNS = ("lineavg", "linemedian", "linestd", "phwin", "phcover", "neutral")

#: How far the market has to have moved against a model edge before that edge
#: is discounted away entirely. The models in these files are published early
#: in the week; when the line has moved a long way since it opened, the market
#: has learned something the models never saw - a quarterback's hamstring,
#: usually - and the gap between them is staleness, not insight.
ADVERSE_MOVE = 6.0

#: How much of the models' disagreement with the market to believe. The
#: closing line is hard to beat, so the market number leads and the model
#: average nudges it. The file's own phcover column implies about 0.7, which
#: would have the models beating the closing line by more than anyone
#: reliably does; a third is the cautious version of the same idea.
CONSENSUS_WEIGHT = 0.33

# How the workbook writes each team, so a slate built from the file reads the
# same way as one typed into the sheet.
DISPLAY = {
    "ari": "Arizona", "atl": "Atlanta", "bal": "Baltimore", "buf": "Buffalo",
    "car": "Carolina", "chi": "Chicago", "cin": "Cincinnati", "cle": "Cleveland",
    "dal": "Dallas", "den": "Denver", "det": "Detroit", "gb": "Green Bay",
    "hou": "Houston", "ind": "Indianapolis", "jax": "Jacksonville",
    "kc": "Kansas City", "lac": "Los Angeles Chargers", "lar": "Los Angeles Rams",
    "lv": "Las Vegas", "mia": "Miami", "min": "Minnesota", "ne": "New England",
    "no": "New Orleans", "nyg": "New York Giants", "nyj": "New York Jets",
    "phi": "Philadelphia", "pit": "Pittsburgh", "sea": "Seattle",
    "sf": "San Francisco", "tb": "Tampa Bay", "ten": "Tennessee",
    "was": "Washington",
}
_CANON = {"jac": "jax", "wsh": "was"}


# ---- naming ----------------------------------------------------------------
def _words(text: object) -> str:
    """"N.Y. Jets" -> "ny jets"; punctuation is never meaningful here."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(text or "").casefold()).split())


@lru_cache(maxsize=1)
def _team_lookup() -> tuple[dict[str, str], dict[str, set[str]], dict[str, set[str]]]:
    """Alias -> code, nickname -> codes, city -> codes. Built once.

    This used to be rebuilt inside `team_code`, which meant walking all
    thirty-two teams and every spelling of each on every call. `team_code` is
    the innermost thing in the app - one week of pick sheets asks for it about
    sixty thousand times - so that walk was most of what the dashboard did.
    """
    exact: dict[str, str] = {}
    by_nickname: dict[str, set[str]] = {}
    by_city: dict[str, set[str]] = {}
    for abbr, aliases in TEAMS.items():
        abbr = _CANON.get(abbr, abbr)
        for alias in aliases:
            spelling = _words(alias)
            if not spelling:
                continue
            exact.setdefault(spelling, abbr)
            # Every alias contributes its last word as a nickname, so adding
            # "san diego chargers" to the list cannot cost "chargers" its
            # meaning - which is exactly what happens if only the last alias
            # is treated as the nickname.
            by_nickname.setdefault(spelling.split()[-1], set()).add(abbr)
            by_city.setdefault(spelling, set()).add(abbr)
    return exact, by_nickname, by_city


@lru_cache(maxsize=4096)
def _code_for(text: str) -> str:
    """The lookup itself, over already-normalised text, remembered per spelling."""
    code = _CANON.get(text, text)
    if code in DISPLAY:
        return code
    exact, by_nickname, by_city = _team_lookup()
    named = exact.get(text)
    if named:
        return named
    for table, key in ((by_nickname, text.split()[-1]), (by_city, text)):
        owners = table.get(key)
        if owners and len(owners) == 1:
            return next(iter(owners))
    return ""


def team_code(name: object) -> str:
    """The three-letter code for a team, however the file spells it.

    Files write "LA Chargers", sheets write "Los Angeles Chargers", and
    either might write just "Chargers". An exact name wins; otherwise the
    nickname ("chargers", "jets") decides, and then the city - but only when
    the city belongs to one team, so a bare "Los Angeles" stays unmatched
    rather than guessing between two.
    """
    text = _words(name)
    return _code_for(text) if text else ""


def forget_teams() -> None:
    """Drop both caches, for a test that edits the team tables."""
    _team_lookup.cache_clear()
    _code_for.cache_clear()


def _number(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


# ---- one game --------------------------------------------------------------
TRIM_SHARE = 0.2     # how much of each end of the models to ignore
MIN_KEPT = 5         # below this there is nothing to trim


def trimmed(values: list[float], share: float = TRIM_SHARE) -> list[float]:
    """The middle of a set of opinions, with the wildest at each end dropped.

    The models in these files are not equally sane. On one game they ran from
    a 20-point home win to an 11-point road win, and a straight average of
    that is worth less than the middle of it: the same game's middle 60% sat
    inside three points of each other. Dropping a fifth off each end costs
    almost nothing when the models agree and saves the number when they
    don't.
    """
    ordered = sorted(values)
    cut = int(len(ordered) * share)
    kept = ordered[cut: len(ordered) - cut] if cut else ordered
    return kept if len(kept) >= MIN_KEPT else ordered


@dataclass(frozen=True)
class Forecast:
    """One row of the file. Every margin is from the home team's side."""

    road: str
    home: str
    market: float | None = None        # the betting line
    opening: float | None = None
    opinions: tuple[float, ...] = ()   # every model that priced the game
    median: float | None = None
    file_average: float | None = None  # lineavg, as the file publishes it
    file_spread: float | None = None   # linestd, likewise
    source_win: float | None = None    # the file's own home win chance
    source_cover: float | None = None
    neutral: bool = False

    @property
    def road_code(self) -> str:
        return team_code(self.road)

    @property
    def home_code(self) -> str:
        return team_code(self.home)

    @property
    def models(self) -> int:
        return len(self.opinions)

    @property
    def consensus(self) -> float | None:
        """What the models make the game, outliers left out."""
        middle = trimmed(list(self.opinions))
        return statistics.fmean(middle) if middle else self.file_average

    @property
    def disagreement(self) -> float | None:
        """How far apart the models that count are.

        The file's own linestd is measured over every model including the
        wild ones, so it says more about them than about the game.
        """
        middle = trimmed(list(self.opinions))
        if len(middle) > 1:
            return statistics.pstdev(middle)
        return self.file_spread

    @property
    def edge(self) -> float | None:
        """How many points the models like the home team more than the market.

        This is the raw number. Most of it is usually not about this game at
        all - see `home_lean`, which takes the slate's shared lean out.
        """
        consensus = self.consensus
        if self.market is None or consensus is None:
            return None
        return consensus - self.market

    @property
    def movement(self) -> float | None:
        """How far the line has moved since it opened, in the home team's favour."""
        if self.market is None or self.opening is None:
            return None
        return self.market - self.opening

    def live_edge(self, lean: float = 0.0) -> float | None:
        """This game's own edge, with stale disagreement taken out.

        Two corrections, in order. The slate's shared lean goes first, since
        it is not about this game. Then whatever the market has moved against
        what is left: a line that has moved three points away from the models
        since it opened has moved on news they were never given, so their
        disagreement is discounted in proportion - and discounted away
        completely by ADVERSE_MOVE points.
        """
        edge = self.edge
        if edge is None:
            return None
        edge -= lean
        move = self.movement
        if move is not None and edge * move < 0:
            edge *= max(0.0, 1 - min(abs(move), ADVERSE_MOVE) / ADVERSE_MOVE)
        return edge

    def expected(self, weight: float = CONSENSUS_WEIGHT, lean: float = 0.0) -> float | None:
        """The margin to predict from: the market, nudged toward the models."""
        edge = self.live_edge(lean)
        if edge is None:
            return self.market if self.market is not None else self.consensus
        return self.market + weight * edge

    def extra_spread(self, weight: float = CONSENSUS_WEIGHT) -> float:
        """Extra uncertainty from the models not agreeing with each other.

        Taken in the same proportion as their opinion is: believing a third
        of their disagreement with the market means carrying a third of the
        disagreement among themselves.
        """
        return weight * (self.disagreement or 0.0)


def home_lean(forecasts: list[Forecast]) -> float:
    """How far the models lean toward home teams, across a whole slate.

    Model after model differs from the market in the same direction on the
    same weekend, because they carry a bigger home-field advantage than the
    market now prices - on one slate every game but four leaned home, by 1.7
    points in the middle. That part is not a read on any game, so taking the
    slate's shared lean out first leaves the disagreement that is actually
    about this matchup. The median is used, so three real outliers can't
    invent a lean of their own.
    """
    edges = [f.edge for f in forecasts if f.edge is not None]
    return statistics.median(edges) if len(edges) >= 6 else 0.0


def read_csv(path: str | Path) -> list[Forecast]:
    """Every game in a predictions file, in the order the file lists them."""
    rows: list[Forecast] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {(k or "").strip().casefold(): v for k, v in raw.items()}
            road, home = row.get("road", ""), row.get("home", "")
            if not str(road).strip() or not str(home).strip():
                continue
            priced = [
                number for key, value in row.items()
                if key.startswith("line")
                and key not in MARKET_COLUMNS + SUMMARY_COLUMNS
                for number in (_number(value),)
                if number is not None
            ]
            market = next(
                (v for v in (_number(row.get(c)) for c in MARKET_COLUMNS) if v is not None),
                None,
            )
            rows.append(Forecast(
                road=str(road).strip(),
                home=str(home).strip(),
                market=market,
                opening=_number(row.get("lineopen")),
                opinions=tuple(priced),
                median=_number(row.get("linemedian")),
                file_average=_number(row.get("lineavg")),
                file_spread=_number(row.get("linestd")),
                source_win=_number(row.get("phwin")),
                source_cover=_number(row.get("phcover")),
                neutral=bool(_number(row.get("neutral"))),
            ))
    return rows


# ---- matching a file to the week's slate ------------------------------------
@dataclass(frozen=True)
class Match:
    """What a file had to say about the games actually on the sheet."""

    by_game: dict[int, Forecast]
    flipped: list[int]          # games the sheet has home and away the other way
    missing: list[str]          # slate games the file didn't cover
    unused: list[str]           # file games not on the slate


def match_games(games: list[Game], forecasts: list[Forecast]) -> Match:
    """Line the file's rows up with the week's games, by team rather than order.

    A sheet occasionally has the home and away teams the wrong way round; the
    pairing still matches, and the row is reported so the margin can be
    turned around instead of being read backwards.
    """
    remaining = list(forecasts)
    by_game: dict[int, Forecast] = {}
    flipped: list[int] = []
    missing: list[str] = []
    for game in games:
        home, away = team_code(game.home), team_code(game.away)
        hit = next(
            (f for f in remaining if f.home_code == home and f.road_code == away), None
        )
        turned = False
        if hit is None and home and away:
            hit = next(
                (f for f in remaining if f.home_code == away and f.road_code == home), None
            )
            turned = hit is not None
        if hit is None:
            missing.append(f"{game.away} @ {game.home}")
            continue
        remaining.remove(hit)
        by_game[game.index] = hit
        if turned:
            flipped.append(game.index)
    return Match(by_game, flipped, missing, [f"{f.road} @ {f.home}" for f in remaining])


def home_margin(game: Game, forecast: Forecast, margin: float | None) -> float | None:
    """A file margin put the right way round for this game's home team."""
    if margin is None:
        return None
    if team_code(game.home) == forecast.home_code:
        return margin
    return -margin


def slate_from(forecasts: list[Forecast]) -> list[Game]:
    """Games built from the file, for a week the sheet doesn't have yet."""
    return [
        Game(index, DISPLAY.get(f.home_code, f.home), DISPLAY.get(f.road_code, f.road))
        for index, f in enumerate(forecasts, start=1)
    ]


def summary(forecasts: list[Forecast]) -> str:
    """One line about a file, for the page to show after a load."""
    priced = [f for f in forecasts if f.market is not None]
    models = [f.models for f in forecasts if f.models]
    average = round(statistics.fmean(models)) if models else 0
    lean = home_lean(forecasts)
    parts = [_count(len(forecasts), "game")]
    if len(priced) < len(forecasts):
        parts.append(f"{len(priced)} with a betting line")
    if average:
        parts.append(f"{average} models a game")
    if abs(lean) >= 0.25:
        parts.append(
            f"a {abs(lean):.1f}-point {'home' if lean > 0 else 'road'} lean removed"
        )
    return " \u00b7 ".join(parts)


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


# ---- finding and remembering files -----------------------------------------
_WEEK_IN_NAME = re.compile(r"(?:week|wk)[^0-9]{0,2}([0-9]{1,2})", re.IGNORECASE)
_LOOKS_RIGHT = re.compile(r"nfl|predict|line|odds", re.IGNORECASE)


def week_in_name(path: str | Path) -> int | None:
    """3 from "nflpredictions_week_3.csv"; None when the name doesn't say."""
    found = _WEEK_IN_NAME.search(Path(path).stem)
    return int(found.group(1)) if found else None


def search_folders(workbook: str | Path | None = None) -> list[Path]:
    """Where a downloaded predictions file is likely to be sitting."""
    folders = [ROOT, ROOT / "predictions", Path.home() / "Downloads"]
    if workbook:
        folders.insert(0, Path(workbook).parent)
    seen, out = set(), []
    for folder in folders:
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        if resolved not in seen and resolved.is_dir():
            seen.add(resolved)
            out.append(resolved)
    return out


def find_file(week: int, workbook: str | Path | None = None) -> Path | None:
    """The newest CSV in the usual folders whose name names this week."""
    best: tuple[float, Path] | None = None
    for folder in search_folders(workbook):
        try:
            entries = list(folder.glob("*.csv"))
        except OSError:
            continue
        for path in entries:
            if week_in_name(path) != week or not _LOOKS_RIGHT.search(path.stem):
                continue
            try:
                when = path.stat().st_mtime
            except OSError:
                continue
            if best is None or when > best[0]:
                best = (when, path)
    return best[1] if best else None


def _read_store() -> dict:
    try:
        raw = json.loads(FORECASTS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save(week: int, forecasts: list[Forecast], source: str = "") -> None:
    """Keep a week's file, so it is there again next time the app opens."""
    store = _read_store()
    store[str(week)] = {
        "source": str(source),
        "imported": time.time(),
        "games": [asdict(f) for f in forecasts],
    }
    try:
        FORECASTS_FILE.write_text(json.dumps(store, indent=1), encoding="utf-8")
    except OSError:
        pass


def load(week: int) -> tuple[list[Forecast], str]:
    """(forecasts, where they came from) for a week, or ([], "")."""
    entry = _read_store().get(str(week))
    if not isinstance(entry, dict):
        return [], ""
    games = []
    for row in entry.get("games", []):
        if not isinstance(row, dict):
            continue
        fields = {k: row.get(k) for k in Forecast.__dataclass_fields__ if k in row}
        if "opinions" in fields:      # a tuple on the way out, a list on the way in
            fields["opinions"] = tuple(fields["opinions"] or ())
        try:
            games.append(Forecast(**fields))
        except TypeError:
            continue
    return games, str(entry.get("source", ""))


def stored_source(week: int) -> str:
    return load(week)[1]


def stored_weeks() -> dict[int, list[Forecast]]:
    """Every week that has a file kept for it, read in one pass.

    Grading the season means looking at a dozen weeks at once, and reading
    the store once beats opening it a dozen times.
    """
    out: dict[int, list[Forecast]] = {}
    for key, entry in _read_store().items():
        try:
            week = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        games = []
        for row in entry.get("games", []):
            if not isinstance(row, dict):
                continue
            fields = {k: row.get(k) for k in Forecast.__dataclass_fields__ if k in row}
            if "opinions" in fields:
                fields["opinions"] = tuple(fields["opinions"] or ())
            try:
                games.append(Forecast(**fields))
            except TypeError:
                continue
        if games:
            out[week] = games
    return out


def refresh_from_disk(week: int, workbook: str | Path | None = None) -> tuple[list[Forecast], str, bool]:
    """Load a week's predictions, picking up a newly downloaded file.

    Returns (forecasts, where they came from, whether a new file was read).
    A file only replaces what is stored when it is a different file or a
    newer copy of it, so dropping this week's download into the workbook's
    folder - or leaving it in Downloads - is the whole of the work.
    """
    kept, source = load(week)
    found = find_file(week, workbook)
    if found is None:
        return kept, source, False
    entry = _read_store().get(str(week), {})
    imported = entry.get("imported", 0) if isinstance(entry, dict) else 0
    try:
        newer = found.stat().st_mtime > float(imported or 0)
    except OSError:
        newer = False
    if kept and str(found) == source and not newer:
        return kept, source, False
    try:
        fresh = read_csv(found)
    except (OSError, ValueError, csv.Error):
        return kept, source, False
    if not fresh:
        return kept, source, False
    save(week, fresh, str(found))
    return fresh, str(found), True