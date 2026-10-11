"""The dashboard's background work with no window: for Task Scheduler.

The window keeps the season current by itself while it is open - it asks
ESPN for results, reloads, fetches the replay's scoring plays and brings the
website up to date. This does the same rounds from a scheduled task, so the
website stays current whether or not anyone has the dashboard open:

    python -m acql.headless --daily     every step, asked of ESPN whatever the time
    python -m acql.headless --poll      only when a look is due (a game under way,
                                        a finished game without its replay) -
                                        otherwise it leaves in a second

schedule.ps1 registers both: --daily at 3am, --poll every ten minutes on
game days. Everything it does goes in the dashboard's log (acql-log.txt),
each line starting "headless:".

Both also keep the week ahead's numbers fresh until its odds lock: the
computer models' predictions file and the betting lines (with an Odds API
key), twice a day and every two hours on the day of the lock - so Deadeye's
card is always priced on the latest line, and kept as it stood at the lock
even when nobody opens the dashboard that week.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

from . import analytics, oddslock, predictions, results
from .config import DATA_DIR, Settings
from .names import AliasTable
from .repository import load_season

#: Held while a run is going, so a poll can't start on top of the 3am run.
LOCK_FILE = Path(DATA_DIR) / "headless.lock"

#: The week ahead's lines are refreshed this often...
LINES_EVERY = 12 * 3600
#: ...and this often on the day its odds lock.
LINES_EVERY_LOCK_DAY = 2 * 3600
#: Lines aren't posted much further ahead than this.
LINES_AHEAD = 6 * 86400
#: A refresh that failed isn't tried again for this long.
LINES_RETRY = 30 * 60
#: The computer models' predictions, as The Prediction Tracker publishes them.
PREDICTIONS_URL = "https://www.thepredictiontracker.com/nflpredictions.csv"
#: The Odds API's free plan is 500 requests a month: this many are left for
#: pressing Update lines by hand.
ODDS_RESERVE = 40


def _log(text: str) -> None:
    from .ui.pages.base import write_log
    write_log(f"headless: {text}")
    print(text, flush=True)


class _RunLock:
    """An OS lock on a file: released by Windows even if the run is killed."""

    def __init__(self, path: Path) -> None:
        self.path, self.handle = path, None

    def __enter__(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def __exit__(self, *_exc) -> None:
        if self.handle is not None:
            self.handle.close()


def _poll_due() -> bool:
    """Cheap look, without reading a spreadsheet: is ESPN worth asking now?
    This week, next week and last week (a Monday night final lands on Tuesday)."""
    from . import timeline
    year = results.season_year()
    weeks = set(results.calendar_weeks(year))
    weeks |= {w - 1 for w in weeks if w > 1}
    if results.due(year, weeks):
        return True
    finished = [w for w in sorted(weeks) if results.over(year, w)]
    return (bool(finished) and timeline.due(year, finished)) or _lines_due() is not None


# ---- the week ahead's lines -----------------------------------------------------------
def _week_ahead(year: int, now: float) -> int | None:
    """The next week whose odds haven't locked yet."""
    return next((w for w in results.calendar_weeks(year, now) if oddslock.lock_time(year, w) > now), None)


def _lines_due(now: float | None = None) -> int | None:
    """The week ahead, when its predictions and lines are due a refresh."""
    from . import store
    now = time.time() if now is None else now
    year = results.season_year()
    week = _week_ahead(year, now)
    if week is None:
        return None
    to_lock = oddslock.lock_time(year, week) - now
    if to_lock > LINES_AHEAD:
        return None
    try:
        tried = float(store.get("headless", "lines_tried", 0) or 0)
    except store.StoreError:
        tried = 0.0
    if now - tried < LINES_RETRY:
        return None
    every = LINES_EVERY_LOCK_DAY if to_lock < 86400 else LINES_EVERY
    return week if now - predictions.market_time(week) >= every else None


def _download_predictions(season, week: int) -> None:
    """The Prediction Tracker's file, kept only when it is this week's games."""
    import tempfile
    import urllib.request
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        _log(f"week {week} has no games set up yet - predictions not fetched")
        return
    request = urllib.request.Request(PREDICTIONS_URL, headers={"User-Agent": "ACQL-Dashboard"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        body = reply.read()
    with tempfile.TemporaryDirectory() as scratch:
        trial = Path(scratch) / "nflpredictions.csv"
        trial.write_bytes(body)
        if not predictions.covers_slate(trial, games):
            _log(f"the published predictions aren't week {week}'s games yet - not kept")
            return
        folder = predictions.ROOT / "predictions"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"nflpredictions week {week}.csv"
        if target.exists() and target.read_bytes() == body:
            return                                  # nothing new published
        target.write_bytes(body)
    got, where, fresh = predictions.refresh_from_disk(
        week, getattr(season, "workbook_path", None), games, locked=False)
    _log(f"week {week} predictions downloaded: {len(got)} games" + ("" if fresh else " (unchanged)"))


def _fetch_lines(season, week: int) -> None:
    """The latest betting lines, the way Update lines on This Week fetches them."""
    from . import briefing, cards, odds
    key = odds.api_key()
    if not key:
        return
    left = odds.remaining()
    if left is not None and left <= ODDS_RESERVE:
        _log(f"betting lines not fetched: {left} Odds API requests left this month, kept for by hand")
        return
    cards.remember_before_update(week, briefing.build(season, week))
    quotes, left = odds.fetch(key)
    update = odds.update(week, quotes, odds.week_pairs(season, week), left)
    _log(update.summary() + (f" {left} requests left this month." if left is not None else ""))


def _refresh_lines(season) -> None:
    """The week ahead's numbers brought up to date, then Deadeye's card kept."""
    from . import briefing, cards, store
    week = _lines_due()
    if week is None or oddslock.locked_for(season, week):
        return
    try:
        store.put("headless", "lines_tried", time.time())
    except store.StoreError:
        pass
    for step in (_download_predictions, _fetch_lines):
        try:
            step(season, week)
        except Exception as exc:  # noqa: BLE001 - the other source may still come through
            _log(f"week {week} {step.__name__.strip('_').replace('_', ' ')} failed: {exc}")
    # The card as it stands on the newest numbers, made before anyone's
    # picks are known, kept to grade Deadeye by (cards.record_model).
    try:
        if cards.record_model(season, week, briefing.build(season, week, use_sheet=False)):
            _log(f"Deadeye's week {week} card kept on the latest lines")
    except Exception as exc:  # noqa: BLE001
        _log(f"Deadeye's week {week} card couldn't be kept: {exc}")


def _predictions(season) -> None:
    """The week ahead's predictions file, picked up as the window's Loader does."""
    try:
        ahead = analytics.upcoming_week(season)
        week = season.weeks.get(ahead)
        got, where, fresh = predictions.refresh_from_disk(
            ahead, getattr(season, "workbook_path", None),
            sorted(week.games, key=lambda g: g.index) if week else [],
            locked=oddslock.locked_for(season, ahead),
        )
        if fresh and got:
            _log(f"week {ahead} predictions read from {Path(where).name}: {len(got)} games")
    except Exception as exc:  # noqa: BLE001
        _log(f"couldn't read the predictions file: {exc}")


def _timelines(season) -> int:
    """Finished games' scoring plays, for the website's replay of each week."""
    from . import timeline
    year = getattr(season, "results_year", 0) or 0
    weeks = sorted(n for n, w in season.weeks.items() if w.games and all(g.played for g in w.games))
    if not year or not weeks or not timeline.due(year, weeks):
        return 0
    kept, problems = timeline.refresh(year, weeks)
    for problem in problems:
        _log(f"replay: {problem}")
    if kept:
        _log(f"replay: kept {kept} game timeline(s)")
    return kept


def _publish(season) -> str | None:
    """The website, brought up to date when something it shows has changed -
    the same steps as the window's AutoPublisher, on this thread."""
    from . import siteextras, webpublish
    from .ui import poolpage
    from .ui.webpage import published

    settings = webpublish.WebSettings.load()
    if not settings.ready:
        _log("website not set up (Results > Pool page in the dashboard) - not published")
        return None
    if not siteextras.Extras.load().auto_publish:
        _log("the website's automatic updates are switched off - not published")
        return None
    weeks = poolpage.finished_weeks(season)
    if not weeks:
        return None
    page, files, data = poolpage.site(season)
    fingerprint = poolpage.site_fingerprint(data)
    if not siteextras.needs_publish(fingerprint):
        _log("website already up to date")
        return None
    from .ui import previewcard
    try:
        files[poolpage.PREVIEW] = previewcard.render(data)
    except Exception as exc:  # noqa: BLE001 - the page goes up without its preview
        _log(f"preview card failed: {exc!r}")
    try:
        files.update(poolpage.app_files())
    except Exception as exc:  # noqa: BLE001
        _log(f"home-screen icon failed: {exc!r}")
    week = max(weeks)
    url = webpublish.publish(settings, page, message=f"After week {week} (scheduled)", files=files)
    published(data, week, url)
    _log(f"website updated: {url}")
    return url


def run(*, force: bool, dry_run: bool = False) -> int:
    started = time.monotonic()
    settings = Settings.load()
    season = load_season(settings, AliasTable.load(), force=force)
    for warning in season.warnings:
        _log(f"note: {warning}")
    if season.is_empty:
        _log(f"no data found in {', '.join(map(str, settings.search_paths()))} - nothing to do")
        return 1
    fetched = getattr(season, "results_fetched", None) or []
    _log(f"loaded {len(season.players)} players, week {season.current_week}; "
         f"ESPN results for week(s) {fetched or 'none due'}")
    _predictions(season)
    _refresh_lines(season)
    if _timelines(season):
        season = load_season(settings, AliasTable.load(), online=False)
    if dry_run:
        _log(f"dry run: website not touched ({time.monotonic() - started:.0f}s)")
        return 0
    try:
        _publish(season)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        _log(f"website update failed: {exc}\n{traceback.format_exc()}")
        return 1
    _log(f"done in {time.monotonic() - started:.0f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acql.headless", description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--daily", action="store_true", help="every step, whatever the time")
    mode.add_argument("--poll", action="store_true", help="only when a look at ESPN is due")
    parser.add_argument("--dry-run", action="store_true", help="do everything but publish the website")
    args = parser.parse_args(argv)

    with _RunLock(LOCK_FILE) as mine:
        if not mine:
            _log("another run is still going - skipped")
            return 0
        try:
            if args.poll and not _poll_due():
                return 0
            _log("daily run" if args.daily else "game-day poll")
            return run(force=args.daily, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001
            _log(f"run failed: {exc!r}\n{traceback.format_exc()}")
            return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
