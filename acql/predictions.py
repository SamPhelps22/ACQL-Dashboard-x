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
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from .config import ROOT
from .lines import TEAMS
from .models import Game

#: Where older versions kept the predictions; read in once by store.py.
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

#: How much of the models' disagreement with the market to believe, on a game
#: where they are no more strung out than the rest of the week's card. The
#: closing line is hard to beat, so the market number leads and the models
#: nudge it.
#:
#: The file's own "probability home covers" column implies about 0.7, which
#: would have the models beating the closing line by more than anyone
#: reliably does. That column is worth nothing anyway: checked across a
#: week's games it is the model AVERAGE put through a normal curve with a
#: fixed 19.9-point spread - the implied spread came out at 19.86 with a
#: variation of 0.26 across sixteen games, which is a constant. It carries
#: no information the average does not, and the average is the least
#: accurate summary on the sheet. Same for "probability home wins": the same
#: average through a 14.36-point curve. Neither is used here.
CONSENSUS_WEIGHT = 0.33

#: The weight is scaled by how much this game's models disagree against the
#: week's own normal, and held between these multiples of it - so a game
#: nobody can price still counts for something, and one they all agree on
#: cannot take over the pick from the market.
MIN_WEIGHT_SHARE = 0.35
MAX_WEIGHT_SHARE = 1.60

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
# Other abbreviations in common use for the same teams. Scores files often
# write Arizona "AZ" (and some sites "ARZ"), which read as no team at all
# before - every Cardinals game in such a file was silently dropped.
_CANON = {"jac": "jax", "wsh": "was", "az": "ari", "arz": "ari", "lvr": "lv"}


# ---- naming ----------------------------------------------------------------
def display_team(name: object) -> str:
    """A team as the pages show it: "Minnesota", never "minnesota" or "CHICAGO".

    The workbook writes the away side in lower case and the home side in
    capitals, which is a fine convention for a spreadsheet and a jarring one
    on a table of games. Anything that is not a team comes back tidied but
    otherwise as it was.
    """
    text = " ".join(str(name or "").split())
    code = team_code(text)
    if code and code in DISPLAY:
        return DISPLAY[code]
    return text.title() if text.isupper() or text.islower() else text


def display_matchup(away: object, home: object) -> str:
    return f"{display_team(away)} @ {display_team(home)}"



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
    # The furthest a model went either way. Only the summary table carries
    # these; the CSV has every model, so it has them implicitly.
    low: float | None = None
    high: float | None = None
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
        """What the models make the game, outliers left out.

        With every model in hand the wildest fifth at each end is dropped and
        the rest averaged. With only the summary table, the median is taken
        over the average: checked against results, the median ranked ninth of
        the thirty-three numbers on the sheet and the average thirtieth - one
        model 20 points out drags an average and moves a median not at all.
        """
        middle = trimmed(list(self.opinions))
        if middle:
            return statistics.fmean(middle)
        return self.median if self.median is not None else self.file_average

    @property
    def disagreement(self) -> float | None:
        """How far apart the models that count are.

        The file's own linestd is measured over every model including the
        wild ones, so it says more about them than about the game. It is
        still the best available when the individual models are not to hand.
        """
        middle = trimmed(list(self.opinions))
        if len(middle) > 1:
            return statistics.pstdev(middle)
        return self.file_spread

    @property
    def spread_of_opinion(self) -> str:
        """The range the models covered, for a tooltip. Empty without one."""
        if self.low is None or self.high is None:
            return ""
        return f"models ranged {self.low:+.1f} to {self.high:+.1f}"

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

    def model_weight(
        self,
        base: float = CONSENSUS_WEIGHT,
        typical: float | None = None,
    ) -> float:
        """How much of the models' disagreement with the market to believe.

        Not a fixed share. The consensus is an estimate, and how far the
        models are strung out is a measure of how good an estimate it is: on
        a game they all price within two points of each other, their middle
        is worth listening to; on one where they range from -27 to +3, it is
        the average of a shrug. The market, meanwhile, is the single most
        accurate number on the sheet whatever the models are doing.

        So the weight is scaled by this game's disagreement against the
        week's own typical disagreement - halved when the models are twice as
        strung out as usual, raised when they are unusually of one mind, and
        capped so it can never run away with the pick.

        Measuring against the week rather than a fixed constant matters: a
        week of close games and a week of blowouts have different normal
        levels of disagreement, and only the difference from normal says
        anything.
        """
        spread = self.disagreement
        if not spread or not typical or typical <= 0:
            return base
        scaled = base * 2 * typical ** 2 / (typical ** 2 + spread ** 2)
        return max(MIN_WEIGHT_SHARE * base, min(MAX_WEIGHT_SHARE * base, scaled))

    def expected(
        self,
        weight: float = CONSENSUS_WEIGHT,
        lean: float = 0.0,
        typical: float | None = None,
    ) -> float | None:
        """The margin to predict from: the market, nudged toward the models."""
        edge = self.live_edge(lean)
        if edge is None:
            return self.market if self.market is not None else self.consensus
        return self.market + self.model_weight(weight, typical) * edge

    def extra_spread(
        self,
        weight: float = CONSENSUS_WEIGHT,
        typical: float | None = None,
    ) -> float:
        """Extra uncertainty from the models not agreeing with each other.

        Taken in the same proportion as their opinion is: believing a third
        of their disagreement with the market means carrying a third of the
        disagreement among themselves.
        """
        return self.model_weight(weight, typical) * (self.disagreement or 0.0)


def typical_disagreement(forecasts: list[Forecast]) -> float:
    """How strung out the models usually are on this week's card.

    The middle game of the week, so a single unpriceable game cannot move it.
    Measuring each game against this rather than against a fixed number keeps
    the comparison honest across a quiet week and a wild one.
    """
    spreads = [f.disagreement for f in forecasts if f.disagreement]
    return statistics.median(spreads) if spreads else 0.0


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


# ---- the summary table, pasted rather than downloaded -----------------------
# The Prediction Tracker publishes the same week twice: a CSV with a column
# per model, and a summary table meant for reading, which is what a person
# actually has in front of them. The table carries everything that matters -
# both lines, the middle of the models, how far apart they are, and the
# site's own two probabilities - so it is worth being able to paste.
#
#     Home          Visitor      Opening  Updated  Midweek   Avg   Median  SD    Min    Max    PWin   PCover
#     Green Bay     Atlanta       6.50     5.00      .       7.50   6.79   4.31  0.49  18.26  0.6995 0.5501
#
# Ten numbers at the end of the line, two team names of unknown length at the
# front. The numbers are counted from the right, and the names are split by
# asking which arrangement gives two teams that exist.
SUMMARY_FIELDS = 10
# A "." stands in for a line that was never posted.
BLANK = {".", "-", "--", "n/a", "na", ""}


def _summary_number(token: str) -> float | None:
    return None if token.strip().casefold() in BLANK else _number(token)


def _split_teams(words: list[str]) -> tuple[str, str] | None:
    """Two team names out of a run of words, without knowing where to cut.

    "Green Bay Atlanta" is three words and only one of the two cuts leaves a
    pair of real teams. Ties are broken toward the longer home name, since
    that is where the two-word cities are.
    """
    for cut in range(len(words) - 1, 0, -1):
        home, road = " ".join(words[:cut]), " ".join(words[cut:])
        if team_code(home) and team_code(road):
            return home, road
    return None


def parse_summary_text(text: str) -> list[Forecast]:
    """Read the pasted summary table. Anything that is not a game is skipped."""
    out: list[Forecast] = []
    for raw in str(text or "").splitlines():
        words = raw.split()
        if len(words) < SUMMARY_FIELDS + 2:
            continue
        numbers = [_summary_number(w) for w in words[-SUMMARY_FIELDS:]]
        # The header line has words where the numbers should be.
        if sum(1 for n in numbers if n is not None) < 5:
            continue
        pair = _split_teams(words[:-SUMMARY_FIELDS])
        if pair is None:
            continue
        home, road = pair
        opening, updated, _midweek, average, median, spread, low, high, win, cover = numbers
        out.append(Forecast(
            road=road,
            home=home,
            # The updated line is the one to price against - it is the market's
            # last word, and it measured as the most accurate number on the
            # sheet. The opening line is kept so the movement can be seen.
            market=updated if updated is not None else opening,
            opening=opening,
            opinions=(),
            median=median,
            file_average=average,
            file_spread=spread,
            source_win=win,
            source_cover=cover,
            low=low,
            high=high,
        ))
    return out


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


# How much of a week's slate a file has to cover before it is taken for that
# week's file. Well over half, so a file for a different week - which shares
# no games at all - cannot be mistaken for this one.
MATCH_SHARE = 0.6
MATCH_LEAST = 4


def candidate_files(workbook: str | Path | None = None) -> list[Path]:
    """Every predictions-looking CSV in the usual folders, newest first."""
    found: list[tuple[float, Path]] = []
    for folder in search_folders(workbook):
        try:
            entries = list(folder.glob("*.csv"))
        except OSError:
            continue
        for path in entries:
            if not _LOOKS_RIGHT.search(path.stem):
                continue
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
    found.sort(key=lambda pair: -pair[0])
    return [path for _, path in found]


def covers_slate(path: Path, slate: list[Game]) -> bool:
    """Whether this file is about these games.

    The file name is the usual way to know which week a download is for, but
    the site does not always put it there and a browser will happily save
    "nflpredictions (2).csv". The games themselves say it without ambiguity:
    a week's file shares its whole slate with that week and nothing with any
    other.
    """
    if not slate:
        return False
    try:
        forecasts = read_csv(path)
    except (OSError, ValueError, csv.Error):
        return False
    if not forecasts:
        return False
    hits = len(match_games(sorted(slate, key=lambda g: g.index), forecasts).by_game)
    return hits >= max(MATCH_LEAST, int(len(slate) * MATCH_SHARE))


def find_file(
    week: int,
    workbook: str | Path | None = None,
    slate: list[Game] | None = None,
) -> Path | None:
    """The newest predictions CSV for this week.

    A name that says the week wins, because it is unambiguous and costs
    nothing to read. Failing that, and given a slate to check against, the
    newest file whose games are this week's games - so a download keeps
    working when the week is nowhere in its name.
    """
    best: tuple[float, Path] | None = None
    for path in candidate_files(workbook):
        if week_in_name(path) != week:
            continue
        try:
            when = path.stat().st_mtime
        except OSError:
            continue
        if best is None or when > best[0]:
            best = (when, path)
    if best is not None:
        return best[1]

    for path in candidate_files(workbook):
        # A file that names a different week is that week's, whatever its
        # contents say; only unnamed ones are opened and checked.
        if week_in_name(path) is None and covers_slate(path, slate or []):
            return path
    return None


def store_stamp() -> tuple:
    """Changes whenever the stored predictions do - for caches built on them."""
    from . import store
    return store.stamp("forecasts")


def _read_store() -> dict:
    from . import store
    return store.items("forecasts")


def save(week: int, forecasts: list[Forecast], source: str = "") -> None:
    """Keep a week's file, so it is there again next time the app opens."""
    from . import store
    try:
        store.put("forecasts", str(week), {
            "source": str(source),
            "imported": time.time(),
            "games": [asdict(f) for f in forecasts],
        })
    except store.StoreError:
        pass


def _with_odds(week: int, games: list[Forecast], imported: object) -> list[Forecast]:
    """Lay any fetched lines (odds.py) over the stored file's numbers."""
    try:
        from . import odds  # lazy: odds reads this module's names
        return odds.overlay(week, games, float(imported or 0))
    except Exception:  # noqa: BLE001 - a broken odds store must not hide the file
        return games


def load(week: int) -> tuple[list[Forecast], str]:
    """(forecasts, where they came from) for a week, or ([], "").

    Lines fetched with "Update lines" are laid over the file's own market
    numbers when they are newer, and stand in for the file when there is none.
    """
    entry = _read_store().get(str(week))
    if not isinstance(entry, dict):
        fetched = _with_odds(week, [], 0)
        return (fetched, "The Odds API") if fetched else ([], "")
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
    return _with_odds(week, games, entry.get("imported", 0)), str(entry.get("source", ""))


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
        games = _with_odds(week, games, entry.get("imported", 0))
        if games:
            out[week] = games
    # weeks with fetched lines and no file
    try:
        from . import odds
        for key in (odds._read().get("weeks") or {}):
            week = int(key)
            if week not in out:
                fetched = _with_odds(week, [], 0)
                if fetched:
                    out[week] = fetched
    except Exception:  # noqa: BLE001
        pass
    return out


def refresh_from_disk(
    week: int,
    workbook: str | Path | None = None,
    slate: list[Game] | None = None,
) -> tuple[list[Forecast], str, bool]:
    """Load a week's predictions, picking up a newly downloaded file.

    Returns (forecasts, where they came from, whether a new file was read).
    A file only replaces what is stored when it is a different file or a
    newer copy of it, so dropping this week's download into the workbook's
    folder - or leaving it in Downloads - is the whole of the work.
    """
    kept, source = load(week)
    found = find_file(week, workbook, slate)
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


# ---- fitting the weight to what actually happened ---------------------------
#: Graded picks before a fitted weight is trusted over the default. Sixteen
#: games a week, so this is three or four weeks of results. Below it the
#: best-scoring weight is mostly noise: on a single week, some weight always
#: wins by luck.
MIN_FIT_GAMES = 48

#: The weights tried. A twentieth is finer than the data can tell apart, but
#: it costs nothing and keeps the reported number from looking invented. The
#: default is always among them, whatever it is, because it has to be scored
#: on the same games as everything else to be compared with them.
def fit_steps(default: float) -> tuple[float, ...]:
    return tuple(sorted({i / 20 for i in range(21)} | {round(default, 4)}))

#: How much better a fitted weight must score than the default before any of
#: it is used, as a share of the default's loss. Under this the two are the
#: same answer and the default is the one with a reason behind it.
FIT_MARGIN = 0.01

#: What the starting weight is worth, in games of evidence. The fitted number
#: is not switched to, it is moved toward, in proportion to how much has been
#: seen: a season of results gets a bit less than half the way there.
#:
#: This is not caution for its own sake. Replaying invented seasons where the
#: right weight was known, the best-scoring weight varied by +/-0.17 over 192
#: games and still +/-0.07 over 1,536 - the signal is a point or two of margin
#: against thirteen points of football, and one season cannot resolve it. A
#: weight that jumped to whatever last month scored best would mostly be
#: chasing noise, and would move the picks around for no reason.
FIT_PRIOR_GAMES = 300

#: However the evidence points, the weight stays inside this range. The market
#: leads and the models nudge; a fit that wants otherwise is telling us the
#: data is thin, not that the bookmakers have been solved.
FIT_FLOOR, FIT_CEILING = 0.10, 0.60


@dataclass(frozen=True)
class WeightFit:
    """What replaying the season at each weight says about the best one."""

    weight: float               # the weight to use: fitted, or the default
    fitted: float               # what scored best, whether or not it is used
    default: float
    games: int
    weeks: tuple[int, ...]
    hits: int
    default_hits: int
    loss: float                 # average surprise per pick at `fitted`, lower is better
    default_loss: float         # the same for `default`
    enough: bool                # whether there is enough to believe it

    @property
    def improvement(self) -> int:
        return self.hits - self.default_hits

    def describe(self) -> str:
        """One line for the page, in the pool's own terms."""
        if not self.games:
            return ""
        if not self.enough:
            short = MIN_FIT_GAMES - self.games
            return (
                f"Model weight {self.default:.0%}, the starting figure - "
                f"{short} more graded {'pick' if short == 1 else 'picks'} before "
                f"this season's results can set it."
            )
        if self.weight == self.default:
            return (
                f"Model weight {self.default:.0%}: replaying "
                f"{self.games} graded picks, nothing scored better."
            )
        return (
            f"Model weight {self.weight:.0%}, moved from the {self.default:.0%} "
            f"it started at toward the {self.fitted:.0%} that scored best over "
            f"{self.games} graded picks in {len(self.weeks)} weeks. It keeps "
            f"moving as more weeks are scored."
        )


def _scored(game: Game, pick: str) -> bool | None:
    """Whether a pick matched the result. None when the game has no result.

    The workbook's result column already has the pool's line applied to it,
    so a pick is right when it names the team in that column - no margin
    arithmetic, and none available anyway.
    """
    winner = str(getattr(game, "winner", "") or "").strip()
    if not winner or not pick:
        return None
    one, two = team_code(pick), team_code(winner)
    if one and two:
        return one == two
    # Neither is a team this app knows. Comparing their codes would compare
    # one empty string with another and call every pick correct, which is the
    # worst possible way to be wrong - a fitted weight built on it would be
    # nonsense that looked perfect. The names themselves still decide.
    return " ".join(pick.split()).casefold() == " ".join(winner.split()).casefold()


def fit_weight(
    weeks: list[tuple[int, list[Game], list[Forecast]]],
    *,
    default: float = CONSENSUS_WEIGHT,
    minimum: int = MIN_FIT_GAMES,
) -> WeightFit:
    """Replay every graded pick at each weight and see which scored best.

    The question the weight answers is how far to move off the bookmakers'
    number toward the models', and it was set by argument rather than by
    measurement. This settles it against what happened: every game with both
    a stored forecast and a result is re-picked at each weight, and the
    weights are ranked by how surprised each was by the results.

    Surprise rather than hit count, because a pick is a probability: being
    right at 51% and right at 90% are not the same claim, and a weight that
    is confident and wrong should be punished for it. Hits are reported too,
    since that is the currency of the pool.

    The default wins ties, and wins anything close, so a season of noise
    cannot talk the app out of a number that has a reason behind it.
    """
    from . import analytics                     # local: analytics is the scorer,
                                                # and this keeps the import one-way

    steps = fit_steps(default)
    tally = {w: [0, 0.0] for w in steps}        # weight -> [hits, total surprise]
    used: list[int] = []
    counted = 0
    for number, games, forecasts in weeks:
        if not games or not forecasts:
            continue
        lean = home_lean(forecasts)
        typical = typical_disagreement(forecasts)
        found = match_games(sorted(games, key=lambda g: g.index), forecasts).by_game
        by_index = {g.index: g for g in games}
        scored_here = 0
        for index, forecast in found.items():
            game = by_index.get(index)
            if game is None or not str(getattr(game, "winner", "") or "").strip():
                continue
            counted_this = False
            for weight in steps:
                margin = home_margin(
                    game, forecast, forecast.expected(weight, lean, typical)
                )
                if margin is None:
                    continue
                sd = math.hypot(
                    analytics.SPREAD_SD, forecast.extra_spread(weight, typical)
                )
                guess = analytics.predict_margin(game, margin, sd=sd, source="fit")
                if guess is None:
                    continue
                right = _scored(game, guess.pick)
                if right is None:
                    continue
                counted_this = True
                chance = min(max(guess.chance, 1e-6), 1 - 1e-6)
                tally[weight][0] += int(right)
                tally[weight][1] -= math.log(chance if right else 1 - chance)
            if counted_this:
                counted += 1
                scored_here += 1
        if scored_here:
            used.append(number)

    if not counted:
        return WeightFit(default, default, default, 0, (), 0, 0, 0.0, 0.0, False)

    losses = {w: total / counted for w, (_, total) in tally.items()}
    best = min(losses, key=lambda w: (losses[w], abs(w - default)))
    default_loss = losses.get(default, losses[best])
    enough = counted >= minimum
    better = default_loss - losses[best] > FIT_MARGIN * max(default_loss, 1e-9)
    if enough and better:
        # Moved toward, not switched to: the starting weight counts for
        # FIT_PRIOR_GAMES of evidence, so early weeks barely shift it and a
        # full season moves it a good part of the way.
        blended = (counted * best + FIT_PRIOR_GAMES * default) / (counted + FIT_PRIOR_GAMES)
        weight = round(min(FIT_CEILING, max(FIT_FLOOR, blended)), 3)
    else:
        weight = default
    # The scores reported are the best-scoring weight's and the default's,
    # because those are the two that were actually replayed. The weight in
    # use sits between them and was not scored on its own - scoring it would
    # say nothing the comparison does not.
    return WeightFit(
        weight=weight,
        fitted=best,
        default=default,
        games=counted,
        weeks=tuple(sorted(used)),
        hits=tally[best][0],
        default_hits=tally[default][0],
        loss=losses[best],
        default_loss=default_loss,
        enough=enough,
    )
