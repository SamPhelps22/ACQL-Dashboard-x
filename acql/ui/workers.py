"""The window's work off its own thread: loading the season, and the quiet
look at the scoreboard."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import analytics, oddslock, predictions, results
from ..config import Settings
from ..names import AliasTable
from ..repository import load_season
from .pages.base import write_log


class Loader(QThread):
    """Parses the spreadsheets off the UI thread so the window stays live."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        #: Ask the scoreboard about every unfinished week now, whatever the time.
        self.force_results = False

    def run(self) -> None:
        try:
            aliases = AliasTable.load()
            # The pick sheets, the pool's lines and the results (asked of
            # ESPN for any week still being played) all go in here, off the
            # UI thread; a problem with any of them is a warning, not a failure.
            season = load_season(self.settings, aliases, force=self.force_results)
        except Exception:  # noqa: BLE001 - reported in the UI, never swallowed
            self.failed.emit(traceback.format_exc())
            return
        # Predictions for the week ahead are picked up here rather than only
        # when the Next Week page is opened, so one press of Refresh takes in
        # everything that has been dropped in the folder.
        try:
            ahead = analytics.upcoming_week(season)
            week = season.weeks.get(ahead)
            got, where, fresh = predictions.refresh_from_disk(
                ahead, getattr(season, "workbook_path", None),
                sorted(week.games, key=lambda g: g.index) if week else [],
                locked=oddslock.locked_for(season, ahead),
            )
            if fresh and got:
                season.warnings.append(
                    f"Week {ahead} predictions read from "
                    f"{Path(where).name}: {len(got)} games."
                )
        except Exception as exc:                      # noqa: BLE001
            season.warnings.append(f"Couldn't read the predictions file: {exc}")
        try:                                          # starting QBs for Game Day (qbcheck.py)
            from .. import qbcheck
            qbcheck.refresh(results.season_year(season))
        except Exception:                             # noqa: BLE001 - optional, never blocks a load
            pass
        self.finished_ok.emit(season)


def _finals(year: int, weeks: list[int]) -> int:
    return sum(1 for week in weeks for score in results.load(year, week) if score.final)


class ResultsCheck(QThread):
    """The window's quiet look at the scoreboard, off the UI thread."""

    found = Signal(bool)        # whether a game has finished since the last look

    def __init__(self, year: int, weeks: list[int], graded: list[int] | None = None, *,
                 every: float | None = None, force: bool = False) -> None:
        super().__init__()
        self.year, self.weeks = year, list(weeks)
        #: The weeks whose finals matter: those the dashboard grades. The
        #: rest are only looked at for their fixtures (the odds lock).
        self.graded = list(self.weeks if graded is None else graded)
        self.every, self.force = every, force

    def run(self) -> None:
        try:
            before = _finals(self.year, self.graded)
            got, _problems = results.refresh(self.year, self.weeks, every=self.every, force=self.force)
            self.found.emit(bool(got) and _finals(self.year, self.graded) > before)
        except Exception as exc:  # noqa: BLE001 - a missed look is no matter
            write_log(f"results check failed: {exc!r}")
            self.found.emit(False)
