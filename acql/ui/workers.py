"""The window's work off its own thread: loading the season, and the quiet
look at the scoreboard."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import analytics
from ..feeds import oddslock, results
from ..model import predictions
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
        #: Do This Week's sums before handing the season over (warm_this_week).
        #: For a reload, when the last season is still on the screen meanwhile.
        self.warm = False

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
        if self.warm:
            warm_this_week(season)
        self.finished_ok.emit(season)


def warm_this_week(season) -> None:
    """This Week's sums, done ahead of time so the page opens on them.

    The card is simulated, planned for money and argued game by game, and
    that was two seconds of a still window the first time the page was opened
    after every load - on a game day, every few minutes. Everything here is
    remembered by what it was worked out from, so the page asks the same
    questions and finds the answers waiting. Nothing is written or fetched.

    A step at a time, letting go of WORKING between them: a page opened
    meanwhile waits for one step, not for all of them.
    """
    from PySide6.QtCore import QSettings

    from ..pool import bigloser, briefing, survivor
    from ..model import evidence
    from ..pool import me as owner
    from .pages.base import WORKING
    from .pages.thisweek import ME_KEY, BriefingPage

    found: dict = {}

    def card() -> None:
        style = QSettings().value(BriefingPage.STYLE_KEY, briefing.DEFAULT_STYLE)
        if style not in (briefing.STYLE_STRAIGHT, briefing.STYLE_MONEY, briefing.STYLE_WIN):
            style = briefing.DEFAULT_STYLE          # as the page's own picker falls back
        found["week"] = week = analytics.upcoming_week(season)
        found["me"] = owner.key(season) or QSettings().value(ME_KEY, "") or None
        if week:
            found["brief"] = briefing.build(season, week, style)

    def reasons() -> None:
        evidence.build(season, found["brief"], found["me"])
        evidence.scoreboard(season)

    def pools() -> None:
        bigloser.board(season, found["week"], found["brief"])
        bigloser.review(season)
        key = owner.key(season) or QSettings().value(BriefingPage.SUICIDE_KEY, "")
        if key:
            survivor.advise(season, key, found["week"])

    def season_race() -> None:
        from ..pool import leverage
        leverage.report(season, found["week"])

    def turns() -> None:
        # The "Turns at" column (model/flips.py): a search over many margins per
        # game, nearly three seconds of the page's first open after a load. Its
        # answers are kept by the chance arithmetic's own caches (analytics), so
        # the page asks the same questions and finds them done. Last, so the
        # other steps can't push them out of those caches first.
        from ..model import flips
        flips.week_flips(season, found["week"])

    for step in (card, reasons, pools, season_race, turns):
        try:
            with WORKING:
                step()
        except Exception as exc:  # noqa: BLE001 - the page works it out itself, as it always did
            write_log(f"warm-up: {step.__name__} not done ahead of time: {exc!r}")
            return
        if not getattr(found.get("brief"), "choices", None):
            return


def warm_model_lab(season) -> None:
    """The Model Lab's two slowest sums, worked out ahead and handed to the page
    once (handoff.py): every recipe over the season, and the live rule replayed.
    About a second and a half of its first open. Nothing is written or fetched."""
    from ..model import livecheck, modellab
    from . import handoff
    from .pages.base import WORKING

    for name, make in (("model lab", modellab.run), ("live check", livecheck.study)):
        try:
            with WORKING:
                handoff.give(name, season, make(season))
        except Exception as exc:  # noqa: BLE001 - the page works it out itself, as it always did
            write_log(f"warm-up: {name} not done ahead of time: {exc!r}")
            return


class Warmer(QThread):
    """The warm-up on its own, after the window has the season: the window fills
    first. After the first load it does This Week too; after a reload, whose
    loader already did This Week before handing over, only the Model Lab - so
    fresh scores never wait for it."""

    def __init__(self, season, this_week: bool = True) -> None:
        super().__init__()
        self.season = season
        self.this_week = this_week

    def run(self) -> None:
        if self.this_week:
            warm_this_week(self.season)
        warm_model_lab(self.season)


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


class TimelineFetch(QThread):
    """Finished games' scoring plays, for the website's replay of each week."""

    fetched = Signal(int)       # how many games' timelines were kept

    def __init__(self, year: int, weeks: list[int]) -> None:
        super().__init__()
        self.year, self.weeks = year, list(weeks)

    def run(self) -> None:
        try:
            from ..feeds import timeline
            kept, problems = timeline.refresh(self.year, self.weeks)
            for problem in problems:
                write_log(f"replay: {problem}")
            self.fetched.emit(kept)
        except Exception as exc:  # noqa: BLE001 - the replay waits for the next look
            write_log(f"replay timelines failed: {exc!r}")
            self.fetched.emit(0)
