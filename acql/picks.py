"""The pool's raw pick sheet - everyone's picks for a week, before grading.

This is the file the commissioner publishes each week and that gets pasted
into the workbook: a column per game, a row per coach, and at the end each
coach's three Big Loser picks and their Suicide pick. The sheet it comes on
looks like this:

    row 1                         ACQL WEEK 2 ...
    row 2                         (phi by 8)          the pool's line
    row 3   cleveland             new orleans         the road team
    row 5   TAMPA BAY             BALTIMORE           the home team
    row 7+  Phelpy   TAMPA BAY    BALTIMORE  ...      one row a coach

Nothing here grades anything. What it is for is the one number that cannot
be worked out from anywhere else: how much of the pool is on each side. A
pick that is right and popular wins nothing; the whole of the gain on the
field is in being right where the others are wrong, and until this file is
loaded that share has to be estimated from a curve.

The week is read from the sheet's own title rather than the file name,
because the files are numbered by something other than the week.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ROOT
from .predictions import team_code

PICKS_FILE = ROOT / "acql-picks.json"

FIRST_PLAYER_ROW = 7
AWAY_ROW, HOME_ROW, NOTE_ROW = 3, 5, 2
TITLE = re.compile(r"WEEK\s*(\d+)", re.IGNORECASE)
LOSER_HEADER = re.compile(r"LOSER\s*(\d)", re.IGNORECASE)
SUICIDE_HEADER = re.compile(r"SUICIDE", re.IGNORECASE)
# Rows at the bottom that summarise rather than pick.
SUMMARY_ROW = re.compile(r"^\s*(picked|total|average|avg)\b", re.IGNORECASE)


class Unreadable(Exception):
    """The file could not be opened at all - the message says what to do."""


def _grid(path: str | Path) -> list[list[str]]:
    """The sheet as rows of strings, from either .xlsx or an older .xls.

    openpyxl reads the modern format; the old one needs xlrd, which is not
    always installed. Saying so plainly beats a traceback about magic bytes.
    """
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError as problem:            # pragma: no cover
            raise Unreadable("openpyxl isn't installed, so no spreadsheet can be read") from problem
        book = openpyxl.load_workbook(path, data_only=True)
        sheet = book["picks"] if "picks" in book.sheetnames else book.worksheets[0]
        return [
            ["" if cell.value is None else str(cell.value).strip() for cell in row]
            for row in sheet.iter_rows()
        ]
    try:
        import xlrd
    except ImportError as problem:
        raise Unreadable(
            f"{path.name} is in the old .xls format, which needs the xlrd package. "
            f"Either run \"pip install xlrd\", or open the file and save it again "
            f"as .xlsx - both work."
        ) from problem
    book = xlrd.open_workbook(path)
    names = book.sheet_names()
    sheet = book.sheet_by_name("picks" if "picks" in names else names[0])
    return [
        [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
        for r in range(sheet.nrows)
    ]


def _cell(rows: list[list[str]], row: int, col: int) -> str:
    """1-based, and off the end of the sheet is simply empty."""
    if 1 <= row <= len(rows) and 1 <= col <= len(rows[row - 1]):
        return rows[row - 1][col - 1]
    return ""


@dataclass(frozen=True)
class GamePicks:
    """One game, and who took which side."""

    away: str
    home: str
    note: str                       # the pool's line, as written on the sheet
    picks: dict[str, str] = field(default_factory=dict)     # coach -> team picked

    @property
    def counted(self) -> int:
        return sum(1 for team in self.picks.values() if team_code(team))

    def share_on(self, team: str) -> float | None:
        """The fraction of the pool that took this team, or None if nobody did."""
        wanted = team_code(team)
        if not wanted or not self.counted:
            return None
        return sum(
            1 for pick in self.picks.values() if team_code(pick) == wanted
        ) / self.counted


@dataclass(frozen=True)
class WeekPicks:
    """Everyone's card for one week."""

    week: int
    games: list[GamePicks] = field(default_factory=list)
    losers: dict[str, list[str]] = field(default_factory=dict)    # coach -> 3 teams
    suicide: dict[str, str] = field(default_factory=dict)         # coach -> team
    source: str = ""

    @property
    def coaches(self) -> list[str]:
        names = {name for game in self.games for name in game.picks}
        return sorted(names | set(self.losers) | set(self.suicide))

    def game_for(self, away: str, home: str) -> GamePicks | None:
        """The sheet's row for a matchup, whichever way round it is written."""
        want = {team_code(away), team_code(home)}
        if "" in want or len(want) != 2:
            return None
        for game in self.games:
            if {team_code(game.away), team_code(game.home)} == want:
                return game
        return None

    def loser_counts(self) -> list[tuple[str, int]]:
        """How many coaches took each Big Loser, most popular first."""
        tally = Counter(
            team_code(team) for picks in self.losers.values() for team in picks
            if team_code(team)
        )
        return tally.most_common()

    def loser_share(self, team: str) -> float:
        """The fraction of coaches with this team among their three."""
        wanted = team_code(team)
        if not wanted or not self.losers:
            return 0.0
        return sum(
            1 for picks in self.losers.values()
            if any(team_code(t) == wanted for t in picks)
        ) / len(self.losers)


def chalk(week: WeekPicks) -> dict[str, float]:
    """How much each coach went with the crowd, 0..1, over one week.

    A coach's figure is the average share of the pool that was on the same
    side as them, game by game. Around 0.8 is this pool's habit; well under
    it is a coach who takes unpopular sides, which is the only way anyone
    finishes a week clear of the field.
    """
    totals: dict[str, list[float]] = {}
    for game in week.games:
        for coach, team in game.picks.items():
            share = game.share_on(team)
            if share is not None:
                totals.setdefault(coach, []).append(share)
    return {
        coach: sum(shares) / len(shares)
        for coach, shares in totals.items() if shares
    }


def load_all() -> dict[int, WeekPicks]:
    """Every stored week, reading the file once."""
    out: dict[int, WeekPicks] = {}
    for key in _read_store():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        sheet = load(number)
        if sheet is not None:
            out[number] = sheet
    return out


def read_file(path: str | Path) -> WeekPicks:
    """Parse a pick sheet. Raises Unreadable if it isn't one."""
    rows = _grid(path)
    if not rows:
        raise Unreadable(f"{Path(path).name} has nothing in it")

    found = TITLE.search(" ".join(rows[0]))
    if not found:
        raise Unreadable(
            f"{Path(path).name} doesn't say which week it is - the top row of a "
            f"pick sheet reads something like \"ACQL WEEK 2\""
        )
    week = int(found.group(1))

    width = max(len(row) for row in rows)
    losers: dict[int, int] = {}          # column -> which of the three
    suicide_col = 0
    games: list[tuple[int, str, str, str]] = []
    for col in range(1, width + 1):
        header = _cell(rows, HOME_ROW, col)
        if LOSER_HEADER.search(header):
            losers[col] = int(LOSER_HEADER.search(header).group(1))
            continue
        if SUICIDE_HEADER.search(header):
            suicide_col = col
            continue
        away = _cell(rows, AWAY_ROW, col)
        if away and header and team_code(away) and team_code(header):
            games.append((col, away, header, _cell(rows, NOTE_ROW, col)))
    if not games:
        raise Unreadable(
            f"{Path(path).name} has no games in it - a pick sheet has the road "
            f"team on row {AWAY_ROW} and the home team on row {HOME_ROW}"
        )

    picks: dict[int, dict[str, str]] = {col: {} for col, *_ in games}
    loser_picks: dict[str, list[str]] = {}
    suicide: dict[str, str] = {}
    for number in range(FIRST_PLAYER_ROW, len(rows) + 1):
        name = _cell(rows, number, 1)
        if not name or SUMMARY_ROW.match(name):
            continue
        # A coach is a row with picks on it. Separators, notes and whatever
        # else is typed down the left-hand column are not coaches, and
        # counting them makes every share in the pool come out too small.
        chosen = {col: _cell(rows, number, col) for col, *_ in games}
        if not any(team_code(team) for team in chosen.values()):
            continue
        for col, team in chosen.items():
            if team:
                picks[col][name] = team
        losing = [_cell(rows, number, col) for col in sorted(losers, key=losers.get)]
        if any(losing):
            loser_picks[name] = losing
        if suicide_col:
            pick = _cell(rows, number, suicide_col)
            if pick:
                suicide[name] = pick

    return WeekPicks(
        week=week,
        games=[GamePicks(away, home, note, picks[col]) for col, away, home, note in games],
        losers=loser_picks,
        suicide=suicide,
        source=str(path),
    )


def summary(week: WeekPicks) -> str:
    """One line about a sheet, for the page to show."""
    alive = sum(1 for pick in week.suicide.values() if team_code(pick))
    parts = [_plural(len(week.coaches), "coach", "coaches")]
    if week.losers:
        parts.append(f"{len(week.losers)} big-loser cards")
    if week.suicide:
        parts.append(f"{alive} alive in the suicide pool")
    return " \u00b7 ".join(parts)


def _plural(count: int, word: str, many: str = "") -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


# ---- keeping them between runs ---------------------------------------------
def _read_store() -> dict:
    try:
        raw = json.loads(PICKS_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save(week: WeekPicks) -> None:
    store = _read_store()
    store[str(week.week)] = {
        "source": week.source,
        "imported": time.time(),
        "games": [asdict(game) for game in week.games],
        "losers": week.losers,
        "suicide": week.suicide,
    }
    try:
        PICKS_FILE.write_text(json.dumps(store, indent=1), encoding="utf-8")
    except OSError:
        pass


def load(week: int) -> WeekPicks | None:
    entry = _read_store().get(str(week))
    if not isinstance(entry, dict):
        return None
    games = []
    for row in entry.get("games", []):
        if isinstance(row, dict):
            games.append(GamePicks(
                away=str(row.get("away", "")), home=str(row.get("home", "")),
                note=str(row.get("note", "")), picks=dict(row.get("picks") or {}),
            ))
    if not games:
        return None
    return WeekPicks(
        week=week, games=games,
        losers={k: list(v) for k, v in (entry.get("losers") or {}).items()},
        suicide=dict(entry.get("suicide") or {}),
        source=str(entry.get("source", "")),
    )


def search_folders(workbook: str | Path | None = None) -> list[Path]:
    """Where a downloaded pick sheet is likely to be."""
    from .predictions import search_folders as folders
    return folders(workbook)


def find_files(workbook: str | Path | None = None) -> list[Path]:
    """Every pick sheet in the usual folders, newest first.

    The file name carries a number that is not the week, so the week has to
    be read out of each one; they are all offered and the caller sorts it out.
    """
    found: list[tuple[float, Path]] = []
    for folder in search_folders(workbook):
        for pattern in ("picks*.xls", "picks*.xlsx", "*picks*.xls", "*picks*.xlsx"):
            for path in folder.glob(pattern):
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    continue
    seen, out = set(), []
    for _, path in sorted(found, reverse=True):
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def refresh_from_disk(workbook: str | Path | None = None) -> list[int]:
    """Read any pick sheet that isn't stored yet. Returns the weeks read."""
    store = _read_store()
    added = []
    for path in find_files(workbook):
        try:
            when = path.stat().st_mtime
        except OSError:
            continue
        # Skip a file that has already been read, unless it has changed.
        already = [
            entry for entry in store.values()
            if isinstance(entry, dict) and entry.get("source") == str(path)
            and float(entry.get("imported") or 0) >= when
        ]
        if already:
            continue
        try:
            week = read_file(path)
        except (Unreadable, OSError, ValueError):
            continue
        save(week)
        store = _read_store()
        added.append(week.week)
    return sorted(set(added))