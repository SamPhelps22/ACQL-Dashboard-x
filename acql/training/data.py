"""The training table: one row a game, every number from before the game.

Three places a game's numbers can come from, and what each is good for:

    the season archives   The Prediction Tracker keeps one file a season
                          (nfl99.csv to this year's): every game with each
                          computer model's margin, the opening line, the line
                          as last updated, and the final score. The only long
                          record of the models game by game. Kept in
                          data/tracker/archive once fetched; nothing here
                          goes online for them.
    nflverse              the closing line, the over/under and the moneylines
                          for every game since 1999 (data/nflverse). No
                          computer models. Used to check the archive's scores
                          and sides, and for what a closing number can say.
    this season's own     what the dashboard itself kept: the predictions
                          file as it was read in, each fetch of the lines
                          with its time, the pool's real lines and results.
                          The only rows whose numbers carry a time.

Every margin is points for the HOME team, as everywhere else in the app.
Each line column says when it was taken (TIMINGS); a recipe pricing a game
as of the pool's deadline may not look at a number taken after it.

Nothing is filled in. A game with no opening line has no opening line, a
model that did not price a game has no number for it, and every row left out
is counted and said why (Notes).

No Qt here.
"""

from __future__ import annotations

import calendar
import csv
import gzip
import logging
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..model import backtest
from ..model.predictions import team_code
from ..store import data_dir

log = logging.getLogger("acql.training")

#: When a number was taken, earliest first.
TIMINGS = ("opening", "midweek", "deadline", "updated", "closing")
#: Every computer model's column starts with this.
MODEL = "m:"
#: A model kept without its name (the multiset of opinions is known, not whose each was).
NAMELESS = "m:?"

FOLDER_NAME = "training"
ARCHIVE_FOLDER = ("tracker", "archive")
ARCHIVE_URL = "https://www.thepredictiontracker.com/nfl{yy:02d}.csv"
ARCHIVE_FIRST = 1999
_ARCHIVE_NAME = re.compile(r"^nfl(\d{2})\.csv$", re.IGNORECASE)

#: The archive's own columns that are betting lines, and when each was taken
#: (the opening line is "open" in 2002's file and "lineopen" ever after).
ARCHIVE_LINES = {"line": "updated", "lineopen": "opening", "open": "opening", "linemidweek": "midweek"}
#: ...and the ones that are the site's summaries of the models, not models:
#: their average, their median, their spread, and the site's own line moved toward them.
ARCHIVE_SUMMARIES = ("lineavg", "linemedian", "linemed", "linestd", "lineca", "linemin", "linemax")
#: The road side's score: "vscore" to 2006, "rscore" since.
ROAD_SCORES = ("rscore", "vscore")
#: A bare "Los Angeles" is two teams now and so no team at all (team_code) -
#: but in these seasons' files it could only be the one that was there.
ONLY_ONE = {("los angeles", 2016): "lar"}

#: Three models the weekly file names one way and the season archives
#: another. Matched on the numbers themselves: the same games, the same
#: forecasts to the second decimal, under both names.
WEEKLY_NAMES = {"pfz": "pz", "sagpred": "sagp", "moore": "more"}
#: nflverse's abbreviations where team_code does not already know them.
VERSE_CODES = {"OAK": "lv", "SD": "lac", "STL": "lar", "LA": "lar"}

#: A betting line further from zero than this, or a model further than that, is a mistake in the file.
MOST_LINE, MOST_MODEL = 30.0, 60.0
#: A column this close to the betting line, game after game, is a betting line (as computers.py has it).
SAME_AS_LINE = 0.25
#: Games before a column, or a season, is checked for running backwards.
MIN_CHECK = 12
#: The archive's updated line and nflverse's closing line are the same market
#: a few days apart: further apart than this on a game and one of them is wrong.
LINES_AGREE = 10.0


# ---- what went wrong, said out loud --------------------------------------------------------------
@dataclass(frozen=True)
class Issue:
    level: str          # "error": rows were left out; "warning": numbers were; "note": worth knowing
    code: str           # "duplicate", "sign", "score", ...
    detail: str
    rows: int = 0


class Notes:
    """Everything the build left out or doubted. Nothing is skipped quietly:
    each is kept here, written to the log, and printed in the report."""

    def __init__(self) -> None:
        self.items: list[Issue] = []

    def _add(self, level: str, code: str, detail: str, rows: int) -> None:
        self.items.append(Issue(level, code, detail, int(rows)))
        log.log({"error": logging.ERROR, "warning": logging.WARNING}.get(level, logging.INFO),
                "%s [%s] %s%s", level, code, detail, f" ({rows} rows)" if rows else "")

    def error(self, code: str, detail: str, rows: int = 0) -> None:
        self._add("error", code, detail, rows)

    def warning(self, code: str, detail: str, rows: int = 0) -> None:
        self._add("warning", code, detail, rows)

    def note(self, code: str, detail: str, rows: int = 0) -> None:
        self._add("note", code, detail, rows)

    def of(self, level: str) -> list[Issue]:
        return [i for i in self.items if i.level == level]

    def as_rows(self) -> list[dict]:
        return [asdict(i) for i in self.items]


# ---- where things live ---------------------------------------------------------------------------
def folder() -> Path:
    """data/training, made on first use. It ignores itself, so nothing a run
    writes - reports, taught models, the working copy of the database - can
    be committed by accident."""
    where = data_dir() / FOLDER_NAME
    where.mkdir(parents=True, exist_ok=True)
    ignore = where / ".gitignore"
    if not ignore.exists():
        try:
            ignore.write_text("*\n", encoding="utf-8")
        except OSError:
            pass
    return where


def archive_folder() -> Path:
    return data_dir().joinpath(*ARCHIVE_FOLDER)


def archive_files(where: Path | None = None) -> dict[int, Path]:
    """{season: its file} for every season archive on disk."""
    where = where or archive_folder()
    out = {}
    try:
        paths = sorted(where.glob("nfl*.csv"))
    except OSError:
        return out
    for path in paths:
        found = _ARCHIVE_NAME.match(path.name)
        if found:
            yy = int(found.group(1))
            out[1900 + yy if yy >= 90 else 2000 + yy] = path
    return dict(sorted(out.items()))


def archive_wanted(last: int | None = None) -> list[tuple[int, str, str]]:
    """(season, file name, where it is published) for every archive the site keeps."""
    last = last or date.today().year
    return [(s, f"nfl{s % 100:02d}.csv", ARCHIVE_URL.format(yy=s % 100)) for s in range(ARCHIVE_FIRST, last + 1)]


# ---- small readers -------------------------------------------------------------------------------
def _number(value: object) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text or text in (".", "-", "NA", "na", "N/A"):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _implied(price: float | None) -> float | None:
    """The chance an American price implies: -150 is 60%, +130 is 43.5%."""
    if price is None or not price:
        return None
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def fair_win(home_price: float | None, away_price: float | None) -> float | None:
    """The home side's chance of winning outright, from the two moneylines
    with the bookmaker's margin taken out (as odds.parse does it)."""
    ours, theirs = _implied(home_price), _implied(away_price)
    if not ours or not theirs:
        return None
    return ours / (ours + theirs)


def _kickoff(day: str, clock: str) -> float | None:
    """Seconds since 1970 for nflverse's game day and its Eastern kickoff time."""
    from ..feeds.oddslock import _eastern_hours
    try:
        y, m, d = (int(part) for part in day.split("-"))
        hour, minute = (int(part) for part in clock.split(":")[:2]) if clock else (13, 0)
        return float(calendar.timegm((y, m, d, hour + _eastern_hours(date(y, m, d)), minute, 0, 0, 0, 0)))
    except (ValueError, AttributeError):
        return None


def _verse_team(abbr: str) -> str:
    return VERSE_CODES.get(abbr.strip().upper()) or team_code(abbr)


def game_key(season: int, week: int, away: str, home: str) -> str:
    return f"{int(season)}-{int(week):02d}-{away}@{home}"


# ---- nflverse: every game, with the numbers it closed at ----------------------------------------
def nflverse_games(path: Path | None = None) -> pd.DataFrame:
    """Every game in nflverse's file, played or not, regular season or not.
    Empty when the file is not there."""
    from ..feeds.nflverse import FOLDER, GAMES_FILE
    path = path or FOLDER / GAMES_FILE
    rows = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            raw = list(csv.DictReader(handle))
    except OSError:
        return pd.DataFrame()
    for row in raw:
        home, away = _verse_team(row.get("home_team", "")), _verse_team(row.get("away_team", ""))
        if not home or not away:
            continue
        home_points, away_points = _number(row.get("home_score")), _number(row.get("away_score"))
        played = home_points is not None and away_points is not None
        rows.append({
            "season": int(row["season"]), "week": int(row["week"]), "kind": row.get("game_type", ""),
            "home": home, "away": away,
            "home_points": home_points if played else np.nan, "away_points": away_points if played else np.nan,
            "line_closing": _number(row.get("spread_line")),
            "total_closing": _number(row.get("total_line")),
            "win_closing": fair_win(_number(row.get("home_moneyline")), _number(row.get("away_moneyline"))),
            "rest": (_number(row.get("home_rest")) or 0.0) - (_number(row.get("away_rest")) or 0.0),
            "division": row.get("div_game") == "1",
            "neutral": str(row.get("location", "")).strip().casefold() == "neutral",
            "kickoff": _kickoff(row.get("gameday", ""), row.get("gametime", "")),
        })
    return pd.DataFrame(rows)


# ---- the season archives ------------------------------------------------------------------------
def read_archive(path: Path, season: int, notes: Notes) -> list[dict]:
    """One season's archive as rows, margins as the file has them (home side).

    Tolerant of what it finds: the columns have changed over twenty-seven
    seasons. Any column called line-something that is not one of the site's
    own lines or summaries is a computer model, named by the rest of its
    header (as computers.read_named names them).
    """
    out, strangers = [], 0
    try:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
            raw = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        notes.error("unreadable", f"{path.name} could not be read: {exc}")
        return out
    for record in raw:
        row = {(k or "").strip().casefold(): v for k, v in record.items() if k is not None}
        home_name = str(row.get("home") or "").strip()
        road_name = str(row.get("road") or row.get("visitor") or row.get("away") or "").strip()
        if not home_name and not road_name:
            continue
        home = team_code(home_name) or ONLY_ONE.get((home_name.casefold(), season), "")
        away = team_code(road_name) or ONLY_ONE.get((road_name.casefold(), season), "")
        if not home or not away or home == away:
            strangers += 1
            continue
        week = _number(row.get("week"))
        made = {
            "season": season, "week": int(week) if week is not None else 0, "home": home, "away": away,
            "home_points": _number(row.get("hscore")),
            "away_points": next((n for n in (_number(row.get(c)) for c in ROAD_SCORES) if n is not None), None),
            "neutral": bool(_number(row.get("neutral"))),
        }
        for column, timing in ARCHIVE_LINES.items():
            if made.get(f"line_{timing}") is None:
                made[f"line_{timing}"] = _number(row.get(column))
        for key, value in row.items():
            if key.startswith("line") and len(key) > 4 and key not in ARCHIVE_LINES and key not in ARCHIVE_SUMMARIES:
                number = _number(value)
                if number is not None:
                    made[MODEL + key[4:]] = number
        out.append(made)
    if strangers:
        notes.error("team", f"{path.name}: rows naming a team the dashboard does not know were left out", strangers)
    if raw and not out:
        notes.error("format", f"{path.name}: no game could be read - the columns are not the ones expected "
                              f"({', '.join(list(raw[0])[:8])}...)")
    return out


def _turned(row: dict) -> dict:
    """The same game with home and away the other way round."""
    out = dict(row)
    out["home"], out["away"] = row["away"], row["home"]
    out["home_points"], out["away_points"] = row["away_points"], row["home_points"]
    for key, value in row.items():
        if (key.startswith("line_") or key.startswith(MODEL)) and value is not None:
            out[key] = -value
    return out


def history(where: Path | None = None, verse: pd.DataFrame | None = None,
            notes: Notes | None = None) -> pd.DataFrame:
    """Every finished regular-season game there is a record of, one row each.

    With the season archives on disk each row carries the computer models;
    each is matched to nflverse's game (when that file is there too) to check
    its score and its sides and to add the closing numbers. Without the
    archives it is nflverse alone: lines and results, no models.
    """
    notes = notes if notes is not None else Notes()
    verse = nflverse_games() if verse is None else verse
    files = archive_files(where)
    by_pair: dict[tuple[int, frozenset], list[dict]] = {}
    for record in verse.to_dict("records") if len(verse) else []:
        by_pair.setdefault((record["season"], frozenset((record["home"], record["away"]))), []).append(record)

    rows: list[dict] = []
    if not files:
        notes.note("archive", "no season archives in data/tracker/archive - no computer models game by game; "
                              "lines and results only")
        for record in verse.to_dict("records") if len(verse) else []:
            if record["kind"] == "REG" and not _blank(record["home_points"]) and not _blank(record["line_closing"]):
                rows.append({**record, "source": "nflverse"})
    for season, path in files.items():
        tally = {"turned": 0, "week": 0, "post": 0, "unplayed": 0, "unmatched": 0, "score": 0, "apart": 0,
                 "borrowed": 0}
        for row in read_archive(path, season, notes):
            scored = row["home_points"] is not None and row["away_points"] is not None
            match = _match(row, by_pair) if by_pair else None
            if match is None and not scored:
                tally["unplayed"] += 1
                continue
            if by_pair and match is None:
                tally["unmatched"] += 1
                continue
            if match is not None:
                if match["kind"] != "REG":
                    tally["post"] += 1
                    continue
                if match["home"] != row["home"]:
                    row = _turned(row)
                    tally["turned"] += 1
                if not scored:
                    # the file kept no score for the game; nflverse has the same game's
                    if _blank(match["home_points"]) or _blank(match["away_points"]):
                        tally["unplayed"] += 1
                        continue
                    row["home_points"], row["away_points"] = match["home_points"], match["away_points"]
                    tally["borrowed"] += 1
                elif (row["home_points"], row["away_points"]) != (match["home_points"], match["away_points"]):
                    tally["score"] += 1
                    continue
                if match["week"] != row["week"]:
                    tally["week"] += 1
                closing, updated = match["line_closing"], row.get("line_updated")
                if not _blank(closing) and updated is not None and abs(closing - updated) > LINES_AGREE:
                    tally["apart"] += 1
                    continue
                row = {**row, "week": match["week"], "neutral": bool(match["neutral"]),
                       **{k: match[k] for k in ("line_closing", "total_closing", "win_closing", "rest", "division",
                                                "kickoff")}}
            rows.append({**row, "source": "archive"})
        said = (("unmatched", "error", "match", "games nflverse has no record of were left out"),
                ("score", "error", "score", "games whose final score differs from nflverse's were left out"),
                ("apart", "error", "line", f"games whose line is more than {LINES_AGREE:g} points from nflverse's "
                                           "closing line (a sign the wrong way round, or a misprint) were left out"),
                ("post", "note", "postseason", "postseason games were left out"),
                ("unplayed", "note", "unplayed", "games without a final score yet were left out"),
                ("turned", "note", "turned", "games listed with home and away the other way round were turned"),
                ("borrowed", "note", "score", "games the file has no score for were given nflverse's final score "
                                              "for the same game"),
                ("week", "note", "week", "games were given nflverse's week number in place of the file's"))
        for key, level, code, what in said:
            if tally[key]:
                getattr(notes, level)(code, f"{path.name}: {what}", tally[key])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["actual"] = frame["home_points"].astype(float) - frame["away_points"].astype(float)
    frame["game"] = [game_key(s, w, a, h) for s, w, a, h in zip(frame.season, frame.week, frame.away, frame.home)]
    _habit_lines(frame)
    return frame.sort_values(["season", "week", "game"], kind="stable").reset_index(drop=True)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _match(row: dict, by_pair: dict) -> dict | None:
    """nflverse's game for an archive row: the same two teams in the same
    week; else (some seasons' files give no week) the one meeting of theirs
    that season with the same score; else the one with the same side at home."""
    found = by_pair.get((row["season"], frozenset((row["home"], row["away"]))), [])
    same_week = [g for g in found if g["week"] == row["week"]]
    if len(same_week) == 1:
        return same_week[0]
    if row["home_points"] is not None and row["away_points"] is not None:
        same_score = [g for g in found if (g["home"] == row["home"]
                                           and (g["home_points"], g["away_points"]) == (row["home_points"], row["away_points"]))
                      or (g["home"] == row["away"]
                          and (g["home_points"], g["away_points"]) == (row["away_points"], row["home_points"]))]
        if len(same_score) == 1:
            return same_score[0]
    same_home = [g for g in found if g["home"] == row["home"]]
    return same_home[0] if len(same_home) == 1 else None


# ---- the pool's line on a game the commissioner never saw ---------------------------------------
LINE_ORDER = ("line_opening", "line_midweek", "line_deadline", "line_updated", "line_closing")


def _habit_lines(frame: pd.DataFrame) -> None:
    """Give each past game the pool line the commissioner would have posted.

    Only this season has his real lines. For the seasons before, his measured
    habit (backtest.pool_line: the next whole number above the spread, on
    favourites of 6.5 or more) is applied to the earliest line there is for
    the game - he posts early in the week. It is a rule standing in for a
    person, and every table built on it says so.
    """
    lines, favourites, sources = [], [], []
    columns = [c for c in LINE_ORDER if c in frame.columns]
    for record in frame[columns].to_dict("records") if columns else [{}] * len(frame):
        base = next((record[c] for c in columns if not _blank(record[c])), None)
        line = backtest.pool_line(base) if base is not None else None
        lines.append(np.nan if line is None else line)
        favourites.append("" if line is None else ("home" if base > 0 else "away"))
        sources.append("" if line is None else "habit")
    frame["pool_line"], frame["pool_favourite"], frame["pool_line_from"] = lines, favourites, sources


# ---- this season, as the dashboard kept it ------------------------------------------------------
def this_season(season, notes: Notes | None = None) -> pd.DataFrame:
    """Every game of the season the dashboard has on its books, with what it
    knew and when.

    For each game: the line as it stood at the pool's deadline (the newest
    number taken at or before the lock - a fetched line or the predictions
    file, whichever was later), the line the app actually priced from (which
    for weeks before the lock was built can be a later one), the opening
    line, every model's number, the commissioner's own line, the margin
    Deadeye priced from, and the result.

    The store must already be pointed at the database to read (a copy:
    pricing a week notes its weight down).
    """
    from ..pool import cards
    from ..feeds import oddslock, odds, results
    from ..model import predictions, pricing
    from .. import store
    notes = notes if notes is not None else Notes()
    year = results.season_year(season)
    try:
        kept_files, kept_names = store.items("forecasts"), store.items("computers")
    except store.StoreError as exc:
        notes.error("store", f"the dashboard's database could not be read: {exc}")
        return pd.DataFrame()
    rows = []
    for number in sorted(season.weeks):
        week = season.weeks[number]
        games = sorted(week.games, key=lambda g: g.index)
        if not games:
            continue
        lock = oddslock.lock_time(year, number)
        ctx = pricing.context(season, number, games)
        prices = {p.game.index: p for p in pricing.price_week(season, number, games, ctx)}
        entry = kept_files.get(str(number))
        entry = entry if isinstance(entry, dict) else {}
        imported = float(entry.get("imported") or 0.0)
        filed = {}
        for raw in entry.get("games", []):
            if isinstance(raw, dict):
                filed[(team_code(raw.get("road", "")), team_code(raw.get("home", "")))] = raw
        named_entry = kept_names.get(str(number))
        named = {(g.get("road"), g.get("home")): g.get("named") or {}
                 for g in (named_entry.get("games", []) if isinstance(named_entry, dict) else [])}
        fetched = odds.stored(number)
        snap = cards.model(number)
        used_at = predictions.market_time(number)
        for game in games:
            home, away = team_code(game.home), team_code(game.away)
            if not home or not away:
                continue
            f = ctx.forecasts.get(game.index)
            row: dict = {
                "season": year, "week": number, "home": home, "away": away, "source": "dashboard",
                "game": game_key(year, number, away, home), "index": game.index,
                "locked_at": lock, "neutral": bool(getattr(f, "neutral", False)),
                "pool_line": np.nan if game.line is None else float(game.line),
                "pool_favourite": "", "pool_line_from": "",
                "card_rebuilt": bool(getattr(snap, "rebuilt", False)) if snap is not None else None,
            }
            if game.line is not None and game.line_favourite:
                row["pool_favourite"] = "home" if team_code(game.line_favourite) == home else "away"
                row["pool_line_from"] = "commissioner"
            # the result, as the pool graded it
            if game.home_points is not None and game.away_points is not None:
                row["home_points"], row["away_points"] = float(game.home_points), float(game.away_points)
                row["actual"] = float(game.home_points - game.away_points)
            winner = team_code(game.winner) if game.played else ""
            row["credited_home"] = 1.0 if winner == home else 0.0 if winner == away else np.nan
            # the lines
            raw = filed.get((away, home)) or filed.get((home, away))
            turn = 1.0 if raw is None or team_code(raw.get("home", "")) == home else -1.0
            file_line = None if raw is None or raw.get("market") is None else turn * float(raw["market"])
            file_open = None if raw is None or raw.get("opening") is None else turn * float(raw["opening"])
            taken: list[tuple[float, float]] = []                   # (when, home margin), known by the lock
            if file_line is not None and 0 < imported <= lock:
                taken.append((imported, file_line))
            if fetched is not None:
                for key, sign in ((f"{away}@{home}", 1.0), (f"{home}@{away}", -1.0)):
                    for at, lines in fetched.history:
                        if at <= lock and key in lines:
                            taken.append((at, sign * lines[key]))
                    if row.get("line_opening") is None and key in fetched.opening and file_open is None:
                        file_open = sign * fetched.opening[key]
            if taken:
                row["taken_at"], row["line_deadline"] = max(taken)
            elif file_line is not None and imported <= 0:
                row["line_untimed"] = file_line                     # typed in afterwards: no time on it
            row["line_opening"] = file_open
            used = pricing.market_margin(game, f) if f is not None else None
            row["line_used"], row["used_at"] = used, used_at or np.nan
            if f is not None and f.market_win is not None and fetched is not None and fetched.at <= lock:
                row["win_deadline"] = f.market_win if f.home_code == home else 1 - f.market_win
            if f is not None and f.total is not None and fetched is not None and fetched.at <= lock:
                row["total_deadline"] = f.total
            # the models: by name where the names were kept, otherwise only how many and what they said
            if raw is not None and raw.get("opinions"):
                mine = named.get((team_code(raw.get("road", "")), team_code(raw.get("home", ""))))
                if mine:
                    for code, value in mine.items():
                        row[MODEL + WEEKLY_NAMES.get(str(code), str(code))] = turn * float(value)
                else:
                    for i, value in enumerate(sorted(float(v) for v in raw["opinions"])):
                        row[f"{NAMELESS}{i:02d}"] = turn * value
                row["models_at"] = imported or np.nan
            price = prices.get(game.index)
            if price is not None and price.margin is not None:
                row["deadeye_live"] = float(price.margin)
                guess = price.prediction()
                if guess is not None:
                    row["deadeye_chance"] = guess.chance if team_code(guess.pick) == home else 1 - guess.chance
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for column in ("line_deadline", "line_untimed", "line_opening", "line_used", "used_at", "taken_at", "actual",
                   "deadeye_live", "deadeye_chance", "win_deadline", "total_deadline", "models_at"):
        if column not in frame.columns:
            frame[column] = np.nan
    late = frame["used_at"].astype(float) > frame["locked_at"].astype(float)
    played = frame["credited_home"].notna()
    if (late & played).any():
        weeks = sorted(set(frame.loc[late & played, "week"].tolist()))
        notes.warning("after the deadline",
                      f"weeks {_run(weeks)}: the line the app priced these games from was taken after the pool's "
                      "deadline. Their record in the Model Lab is on a later line than a card could have used.",
                      int((late & played).sum()))
    untimed = frame["line_untimed"].notna() & played
    if untimed.any():
        weeks = sorted(set(frame.loc[untimed, "week"].tolist()))
        notes.warning("no time",
                      f"weeks {_run(weeks)}: the betting lines were typed in afterwards and carry no time, so "
                      "nothing says they were the lines at the deadline.", int(untimed.sum()))
    return frame.sort_values(["season", "week", "index"], kind="stable").reset_index(drop=True)


def _run(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)


# ---- checking a table before anything is taught on it --------------------------------------------
def model_columns(frame: pd.DataFrame, named_only: bool = False) -> list[str]:
    return [c for c in frame.columns
            if c.startswith(MODEL) and not (named_only and c.startswith(NAMELESS))]


def line_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith("line_")]


def check(frame: pd.DataFrame, notes: Notes | None = None) -> pd.DataFrame:
    """The table with everything that cannot be trusted taken out, and said.

    Looked for: columns of the wrong type, the same game twice, a number no
    game could have, a season or a model whose sign runs backwards, a
    "model" that is really a betting line, and a number taken after the game
    it describes kicked off.
    """
    notes = notes if notes is not None else Notes()
    if frame.empty:
        return frame
    frame = frame.copy()
    for needed in ("season", "week", "home", "away"):
        if needed not in frame.columns:
            notes.error("columns", f"the table has no {needed!r} column - nothing can be taught on it")
            return frame.iloc[0:0]
    numeric = line_columns(frame) + model_columns(frame) + [
        c for c in ("actual", "home_points", "away_points", "pool_line", "total_closing", "win_closing",
                    "total_deadline", "win_deadline", "taken_at", "locked_at", "kickoff") if c in frame.columns]
    for column in numeric:
        before = frame[column].notna().sum()
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
        lost = int(before - frame[column].notna().sum())
        if lost:
            notes.warning("type", f"{column}: values that are not numbers were blanked", lost)

    # the same game twice
    pair = [f"{s}-{w}-{'/'.join(sorted((h, a)))}" for s, w, h, a in zip(frame.season, frame.week, frame.home, frame.away)]
    doubled = pd.Series(pair, index=frame.index).duplicated(keep=False)
    if doubled.any():
        notes.error("duplicate", "games listed more than once were left out, every copy of them: "
                    + ", ".join(sorted(set(frame.loc[doubled, 'game'].astype(str)))[:6]), int(doubled.sum()))
        frame = frame[~doubled]

    # numbers no game could have
    bad_week = ~frame["week"].between(1, 22)
    if bad_week.any():
        notes.error("week", "games with no week of the season were left out", int(bad_week.sum()))
        frame = frame[~bad_week]
    for column in ("home_points", "away_points"):
        if column in frame.columns:
            wrong = frame[column].notna() & ~frame[column].between(0, 80)
            if wrong.any():
                notes.error("score", f"{column}: games with a score no game has had were left out", int(wrong.sum()))
                frame = frame[~wrong]
    for column in line_columns(frame):
        wild = frame[column].abs() > MOST_LINE
        if wild.any():
            notes.warning("range", f"{column}: lines further than {MOST_LINE:g} points from level were blanked",
                          int(wild.sum()))
            frame.loc[wild, column] = np.nan
    for column in model_columns(frame):
        wild = frame[column].abs() > MOST_MODEL
        if wild.any():
            notes.warning("range", f"{column[len(MODEL):]}: forecasts further than {MOST_MODEL:g} points from level "
                                   "were blanked", int(wild.sum()))
            frame.loc[wild, column] = np.nan
    for column, low, high in (("win_closing", 0.0, 1.0), ("win_deadline", 0.0, 1.0),
                              ("total_closing", 20.0, 80.0), ("total_deadline", 20.0, 80.0)):
        if column in frame.columns:
            wild = frame[column].notna() & ~frame[column].between(low, high)
            if wild.any():
                notes.warning("range", f"{column}: values outside {low:g}-{high:g} were blanked", int(wild.sum()))
                frame.loc[wild, column] = np.nan

    # a number taken after the game began is not a forecast of it
    if {"taken_at", "kickoff"} <= set(frame.columns):
        late = frame["taken_at"].notna() & frame["kickoff"].notna() & (frame["taken_at"] >= frame["kickoff"])
        if late.any():
            notes.error("time", "games whose line was taken after their own kickoff were left out", int(late.sum()))
            frame = frame[~late]
    if {"taken_at", "locked_at"} <= set(frame.columns):
        late = frame["taken_at"].notna() & frame["locked_at"].notna() & (frame["taken_at"] > frame["locked_at"])
        if late.any():
            notes.error("time", "deadline lines taken after the deadline were blanked", int(late.sum()))
            frame.loc[late, "line_deadline"] = np.nan

    # signs: a favourite should win more often than not, and a model should lean the way the line does
    if "actual" in frame.columns:
        for column in line_columns(frame):
            for season, rows in frame.groupby("season"):
                both = rows[[column, "actual"]].dropna()
                if len(both) >= 4 * MIN_CHECK and _corr(both[column], both["actual"]) < 0:
                    notes.error("sign", f"{season}: {column} runs against the results - its sign is the wrong way "
                                        "round. The season's numbers in that column were blanked.", len(both))
                    frame.loc[frame.season == season, column] = np.nan
    base = _first(frame, ("line_updated", "line_closing", "line_deadline", "line_used", "line_opening"))
    if base is not None:
        dropped = []
        for column in model_columns(frame, named_only=True):
            both = frame[[column, base]].dropna()
            if len(both) < MIN_CHECK:
                continue
            if float((both[column] - both[base]).abs().mean()) < SAME_AS_LINE:
                dropped.append(column)
                continue
            for season, rows in both.groupby(frame.loc[both.index, "season"]):
                if len(rows) >= MIN_CHECK and _corr(rows[column], rows[base]) < 0:
                    notes.warning("sign", f"{season}: {column[len(MODEL):]} runs against the betting line - blanked "
                                          "for that season rather than guessed at", len(rows))
                    frame.loc[rows.index, column] = np.nan
        if dropped:
            notes.note("a betting line", "columns that sit on the betting line game after game are lines, not "
                       "models, and are not counted among them: " + ", ".join(c[len(MODEL):] for c in dropped))
            frame = frame.drop(columns=dropped)
    empty = [c for c in model_columns(frame) if not frame[c].notna().any()]
    return frame.drop(columns=empty).reset_index(drop=True)


def _corr(a: pd.Series, b: pd.Series) -> float:
    a, b = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _first(frame: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    return next((c for c in columns if c in frame.columns and frame[c].notna().any()), None)


# ---- how much of each thing there is -------------------------------------------------------------
def coverage(frame: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """For each column: how many games have it, what share that is, and over which seasons."""
    if frame.empty:
        return pd.DataFrame(columns=["column", "games", "share", "seasons"])
    columns = columns if columns is not None else [
        c for c in frame.columns if c.startswith("line_") or c in ("total_closing", "win_closing", "total_deadline",
                                                                  "win_deadline", "pool_line", "actual", "taken_at")]
    out = []
    for column in columns:
        if column not in frame.columns:
            out.append({"column": column, "games": 0, "share": 0.0, "seasons": ""})
            continue
        have = frame[column].notna() if column != "n_models" else frame[column] > 0
        seasons = frame.loc[have, "season"]
        out.append({"column": column, "games": int(have.sum()), "share": float(have.mean()),
                    "seasons": f"{int(seasons.min())}-{int(seasons.max())}" if len(seasons) else ""})
    return pd.DataFrame(out)


def models_by_season(frame: pd.DataFrame) -> pd.DataFrame:
    """Season by season: games, games with five or more models, and the middle count of models a game."""
    columns = model_columns(frame)
    out = []
    for season, rows in frame.groupby("season"):
        counted = rows[columns].notna().sum(axis=1) if columns else pd.Series(0, index=rows.index)
        out.append({"season": int(season), "games": len(rows), "with_models": int((counted >= 5).sum()),
                    "models_a_game": float(counted[counted > 0].median()) if (counted > 0).any() else 0.0,
                    "opening": int(rows["line_opening"].notna().sum()) if "line_opening" in rows else 0,
                    "midweek": int(rows["line_midweek"].notna().sum()) if "line_midweek" in rows else 0,
                    "updated": int(rows["line_updated"].notna().sum()) if "line_updated" in rows else 0,
                    "closing": int(rows["line_closing"].notna().sum()) if "line_closing" in rows else 0})
    return pd.DataFrame(out)
