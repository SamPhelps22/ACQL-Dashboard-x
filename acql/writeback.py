"""Write edits back into ACQL Dashboard.xlsx, safely.

The workbook is formula-driven: the Dashboard sheet is built almost entirely
from XLOOKUP / SORTBY / INDIRECT over the Season and Winnings tables. Those
formulas are the workbook's value, so this module never writes over one.

Three rules hold every save:

  1. **Input cells only.** Before writing, the target cell is read with
     formulas intact. If it currently holds a formula, the write is refused
     and reported rather than silently destroying it.
  2. **Back up first.** A timestamped copy is taken before the first edit of
     a session, so any save can be undone by restoring a file.
  3. **Verify after.** The saved file is reopened and the written cells are
     read back; a mismatch is raised rather than reported as success.

openpyxl preserves this workbook's tables, conditional formatting, data
validation and merged ranges. It does drop *cached* formula results, so Excel
recalculates on open - expected, and harmless here since the workbook carries
no charts, pivot tables or images.

Which cells are actually inputs
-------------------------------
Inspecting the workbook shows it is almost entirely derived. The only literal
cells - and therefore the only ones this module offers to edit - are on the
Week sheets:

    row 4 / row 5   the week's home and away teams
    row 6           the result of each game
    F..U per player the player's picks
    V, W, X         big-loser picks        Y   suicide pick

plus the per-week game counts on Season row 3. Everything downstream (each
player's wins, rank, games behind, money owed, the Season grid, the Winnings
grid and the whole Dashboard sheet) is an Excel formula fed by those cells, so
entering results here makes Excel recompute the rest on open. Season and
Winnings weekly cells are array formulas and are deliberately not writable.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import BACKUP_DIR, BIG_LOSER_PICKS, GAMES_PER_WEEK, WEEKS_IN_SEASON
from .names import AliasTable, normalize
from .sources.workbook import (
    COL_FIRST_GAME,
    COL_LOSER_1,
    COL_PLAYER,
    COL_SUICIDE,
    ROW_AWAY,
    ROW_FIRST_PLAYER,
    ROW_HOME,
    ROW_LAST_PLAYER,
    ROW_RESULT,
    SEASON_FIRST_ROW,
    SEASON_GAMES_ROW,
    SEASON_FIRST_WEEK_COL,
    SEASON_LAST_ROW,
)

MAX_BACKUPS = 25


class WriteBackError(RuntimeError):
    """Raised when an edit cannot be applied safely."""


@dataclass
class Edit:
    """One pending cell change."""

    sheet: str
    row: int
    column: int
    value: object
    description: str = ""

    @property
    def address(self) -> str:
        from openpyxl.utils import get_column_letter

        return f"{self.sheet}!{get_column_letter(self.column)}{self.row}"


@dataclass
class WriteResult:
    applied: list[Edit] = field(default_factory=list)
    refused: list[tuple[Edit, str]] = field(default_factory=list)
    backup: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.refused

    def summary(self) -> str:
        parts = [f"{len(self.applied)} cell(s) updated"]
        if self.refused:
            parts.append(f"{len(self.refused)} refused")
        if self.backup:
            parts.append(f"backup: {self.backup.name}")
        return ", ".join(parts)


def make_backup(path: Path) -> Path:
    """Copy the workbook into backups/ with a timestamped name."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{path.stem}-{stamp}{path.suffix}"
    shutil.copy2(path, target)
    _prune_backups(path.stem)
    return target


def _prune_backups(stem: str) -> None:
    """Keep only the most recent MAX_BACKUPS copies of a given workbook."""
    try:
        copies = sorted(
            BACKUP_DIR.glob(f"{stem}-*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in copies[MAX_BACKUPS:]:
        try:
            stale.unlink()
        except OSError:
            pass


class WorkbookEditor:
    """Collects edits, then applies them to the workbook in one guarded save."""

    def __init__(self, path: Path, aliases: AliasTable | None = None) -> None:
        if not path or not Path(path).is_file():
            raise WriteBackError(f"Workbook not found: {path}")
        self.path = Path(path)
        self.aliases = aliases or AliasTable.load()
        self._edits: list[Edit] = []
        # Row lookups reopen the workbook, and an editor session can queue
        # dozens of per-player edits, so each sheet's roster is read once.
        self._row_cache: dict[tuple[str, int, int, int], dict[str, int]] = {}

    # ---- building up the change set ------------------------------------
    def __len__(self) -> int:
        return len(self._edits)

    @property
    def edits(self) -> list[Edit]:
        return list(self._edits)

    def clear(self) -> None:
        self._edits.clear()

    def _queue(self, sheet: str, row: int, col: int, value: object, what: str) -> None:
        # A later edit to the same cell replaces the earlier one.
        self._edits = [
            e for e in self._edits
            if not (e.sheet == sheet and e.row == row and e.column == col)
        ]
        self._edits.append(Edit(sheet, row, col, value, what))

    @staticmethod
    def _week_sheet(week: int) -> str:
        if not 1 <= week <= WEEKS_IN_SEASON:
            raise WriteBackError(f"Week {week} is outside 1-{WEEKS_IN_SEASON}.")
        return f"Week {week}"

    def set_matchup(self, week: int, game: int, home: str, away: str) -> None:
        """Set the teams for one game on a week's slate."""
        if not 1 <= game <= GAMES_PER_WEEK:
            raise WriteBackError(f"Game {game} is outside 1-{GAMES_PER_WEEK}.")
        sheet, col = self._week_sheet(week), COL_FIRST_GAME + game - 1
        self._queue(sheet, ROW_HOME, col, home, f"week {week} game {game} home team")
        self._queue(sheet, ROW_AWAY, col, away, f"week {week} game {game} away team")

    def set_result(self, week: int, game: int, winner: str) -> None:
        """Record who won one game."""
        if not 1 <= game <= GAMES_PER_WEEK:
            raise WriteBackError(f"Game {game} is outside 1-{GAMES_PER_WEEK}.")
        self._queue(
            self._week_sheet(week),
            ROW_RESULT,
            COL_FIRST_GAME + game - 1,
            winner,
            f"week {week} game {game} result",
        )

    def set_pick(self, week: int, player: str, game: int, team: str) -> None:
        """Record one player's pick for one game."""
        if not 1 <= game <= GAMES_PER_WEEK:
            raise WriteBackError(f"Game {game} is outside 1-{GAMES_PER_WEEK}.")
        sheet = self._week_sheet(week)
        row = self._find_week_row(sheet, player)
        self._queue(
            sheet, row, COL_FIRST_GAME + game - 1, team,
            f"{player} week {week} game {game} pick",
        )

    def set_suicide_pick(self, week: int, player: str, team: str) -> None:
        """Record one player's suicide-pool pick."""
        sheet = self._week_sheet(week)
        row = self._find_week_row(sheet, player)
        self._queue(sheet, row, COL_SUICIDE, team, f"{player} week {week} suicide pick")

    def set_big_loser_picks(self, week: int, player: str, picks: list[str]) -> None:
        """Record a player's three big-loser slots.

        A slot holds either the team picked or a 1 once that pick came in.
        The 1 must be written as a number: Excel's counts treat a text "1" as
        an unrelated label, so storing it as text would silently zero out the
        player's big-loser wins.
        """
        sheet = self._week_sheet(week)
        row = self._find_week_row(sheet, player)
        for i in range(BIG_LOSER_PICKS):
            value = picks[i] if i < len(picks) else ""
            self._queue(
                sheet, row, COL_LOSER_1 + i, _as_number_if_numeric(value),
                f"{player} week {week} loser pick {i + 1}",
            )

    def set_game_count(self, week: int, count: int) -> None:
        """Set how many games counted in a week (Season sheet, row 3)."""
        if not 1 <= week <= WEEKS_IN_SEASON:
            raise WriteBackError(f"Week {week} is outside 1-{WEEKS_IN_SEASON}.")
        self._queue(
            "Season", SEASON_GAMES_ROW, SEASON_FIRST_WEEK_COL + week - 1, count,
            f"week {week} game count",
        )

    # ---- locating a player's row ----------------------------------------
    def _rows_for(self, sheet_name: str, first: int, last: int, col: int) -> dict[str, int]:
        import openpyxl

        cache_key = (sheet_name, first, last, col)
        cached = self._row_cache.get(cache_key)
        if cached is not None:
            return cached

        wb = openpyxl.load_workbook(self.path, data_only=True)
        try:
            if sheet_name not in wb.sheetnames:
                raise WriteBackError(f"The workbook has no '{sheet_name}' sheet.")
            ws = wb[sheet_name]
            found: dict[str, int] = {}
            for r in range(first, last + 1):
                key = self.aliases.key(ws.cell(r, col).value)
                if key:
                    found.setdefault(key, r)
            self._row_cache[cache_key] = found
            return found
        finally:
            wb.close()

    def _find_week_row(self, sheet: str, player: str) -> int:
        rows = self._rows_for(sheet, ROW_FIRST_PLAYER, ROW_LAST_PLAYER, COL_PLAYER)
        key = self.aliases.key(player)
        if key not in rows:
            raise WriteBackError(
                f"'{player}' is not on the {sheet} sheet. "
                "Add the player in Excel first, or map the name in aliases.json."
            )
        return rows[key]

    def _find_grid_row(self, sheet: str, player: str) -> int:
        """Locate a player on the Season or Winnings sheet (validation only)."""
        rows = self._rows_for(sheet, SEASON_FIRST_ROW, SEASON_LAST_ROW, 1)
        key = self.aliases.key(player)
        if key not in rows:
            raise WriteBackError(
                f"'{player}' is not on the {sheet} sheet. "
                "Add the player in Excel first, or map the name in aliases.json."
            )
        return rows[key]

    # ---- applying ---------------------------------------------------------
    def preview(self) -> list[Edit]:
        return self.edits

    def apply(self, *, backup: bool = True, dry_run: bool = False) -> WriteResult:
        """Validate every queued edit, then save the workbook.

        Nothing is written unless every edit targets a non-formula cell, so a
        change set either lands whole or not at all.
        """
        import openpyxl

        result = WriteResult()
        if not self._edits:
            return result

        wb = openpyxl.load_workbook(self.path, data_only=False)
        try:
            for edit in self._edits:
                if edit.sheet not in wb.sheetnames:
                    result.refused.append((edit, f"no '{edit.sheet}' sheet in the workbook"))
                    continue
                current = wb[edit.sheet].cell(edit.row, edit.column).value
                if isinstance(current, str) and current.lstrip().startswith("="):
                    result.refused.append(
                        (edit, f"{edit.address} holds a formula and will not be overwritten")
                    )
                    continue
                result.applied.append(edit)

            if result.refused or dry_run:
                return result

            if backup:
                result.backup = make_backup(self.path)

            for edit in result.applied:
                wb[edit.sheet].cell(edit.row, edit.column).value = edit.value
            wb.save(self.path)
        finally:
            wb.close()

        self._verify(result)
        self._edits.clear()
        self._row_cache.clear()
        return result

    def _verify(self, result: WriteResult) -> None:
        """Reopen the saved file and confirm the values actually landed."""
        import openpyxl

        wb = openpyxl.load_workbook(self.path, data_only=False)
        try:
            for edit in result.applied:
                got = wb[edit.sheet].cell(edit.row, edit.column).value
                if _differs(got, edit.value):
                    raise WriteBackError(
                        f"Verification failed at {edit.address}: "
                        f"expected {edit.value!r} but the file holds {got!r}. "
                        + (f"The workbook was backed up to {result.backup}." if result.backup else "")
                    )
        finally:
            wb.close()


def _as_number_if_numeric(value: object) -> object:
    """Store a purely numeric entry as a number rather than as text.

    Excel distinguishes 1 from "1", and the workbook's big-loser tallies count
    the numeric form. No NFL team name is numeric, so this cannot swallow a
    legitimate pick.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else number


def _differs(actual: object, expected: object) -> bool:
    """Compare a read-back cell with what was written, tolerantly."""
    if actual is None and (expected is None or expected == ""):
        return False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) > 1e-9
    return normalize(actual) != normalize(expected)
