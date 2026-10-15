"""Deadeye's training, from the command line.

    python -m acql.training run        every experiment on what is on disk, and the report
    python -m acql.training report     the newest run's report, written again (nothing is run again)
    python -m acql.training audit      what data there is to learn from - nothing taught
    python -m acql.training snapshot   freeze this week's numbers as they stand (before the deadline)
    python -m acql.training weekly     what the scheduled task runs: the snapshot, and a fresh run
                                       when the newest is a week old (the Model Lab shows its verdict)
    python -m acql.training check      only the check that no result can leak backwards
    python -m acql.training patterns   home-underdog patterns from outside, counted on our seasons
    python -m acql.training decay      how much of the models' gap from the line survives open to close
    python -m acql.training margin     four ways of taking the bookmaker's margin out, against results
    python -m acql.training features   each football fact on its own, on top of the line, at each timing
    python -m acql.training fetch     the season archives from The Prediction Tracker (about 2 MB;
                                       the one thing here that goes online, and only when asked)

Everything is written under data/training. The dashboard's database is read
from a copy, the dashboard can be open, and nothing here changes a pick.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import data


def _logging(verbose: bool) -> None:
    root = logging.getLogger("acql.training")
    root.setLevel(logging.INFO)
    root.handlers.clear()
    screen = logging.StreamHandler(sys.stderr)
    screen.setLevel(logging.INFO if verbose else logging.WARNING)
    screen.setFormatter(logging.Formatter("  %(message)s"))
    root.addHandler(screen)
    try:
        kept = logging.FileHandler(data.folder() / "training-log.txt", encoding="utf-8")
        kept.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(kept)
    except OSError:
        pass


def _progress():
    last = {"what": "", "at": 0.0}

    def tell(what: str, done: int, of: int) -> None:
        now = time.monotonic()
        if what != last["what"] or done == of or now - last["at"] > 5:
            print(f"  {what}: {done}/{of}", flush=True)
            last.update(what=what, at=now)
    return tell


def run(args) -> int:
    from . import report, study
    print("Training run - this reads a copy of the dashboard's database and changes nothing in it.", flush=True)
    found = study.run(trees=not args.no_trees, seal=not args.no_check, books_too=not args.no_books,
                      progress=None if args.quiet else _progress())
    report.keep_whole(found)
    folder = report.write(found)
    errors = found.notes.of("error")
    print(f"\nDone in {found.took:.0f}s. {len(errors)} problem(s) left rows out; "
          f"{len(found.notes.of('warning'))} warning(s).")
    print(f"Report:  {folder / 'report.md'}")
    print(f"Latest:  {data.folder() / 'latest' / 'report.md'}")
    if not found.has_models:
        print("\nThe computer models are not on disk game by game, so the main experiment did not run.\n"
              "See section 1 of the report for what to fetch.")
    return 0 if all(ok for _, _, ok, _ in found.seals) else 2


def again(args) -> int:
    """The newest run's report, written again from what the run kept."""
    from . import report
    found = report.kept_whole()
    if found is None:
        print("No run has been kept to write up - run `python -m acql.training run` first.")
        return 1
    folder = report.write(found)
    print(f"Report:  {folder / 'report.md'}")
    return 0


def audit(args) -> int:
    from . import features, study
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    now = study.load_books(notes) if not args.no_books else None
    print(f"\nPast seasons: {len(history):,} finished games"
          + (f", {int(history['season'].min())}-{int(history['season'].max())}" if len(history) else ""))
    if len(history):
        print(data.coverage(history).to_string(index=False))
        models = data.model_columns(history)
        print(f"\nComputer models game by game: {len(models)} columns"
              + ("" if models else " - none (the season archives are not in data/tracker/archive)"))
        if models:
            print(data.models_by_season(history).to_string(index=False))
    missing = [name for season, name, _ in data.archive_wanted() if season not in data.archive_files()]
    if missing:
        print(f"\nSeason archives not on disk: {len(missing)} ({missing[0]} ... {missing[-1]})")
    if now is not None and len(now):
        graded = now[now["credited_home"].notna()]
        print(f"\nThis season on the dashboard's records: {len(now)} games, {len(graded)} graded")
        by_week = graded.groupby("week").agg(
            games=("game", "count"), line_at_deadline=("line_deadline", "count"),
            line_untimed=("line_untimed", "count"), opening=("line_opening", "count"))
        by_week["with_models"] = (graded[data.model_columns(graded)].notna().sum(axis=1) >= features.ENOUGH_MODELS
                                  ).groupby(graded["week"]).sum()
        print(by_week.to_string())
    print("\nLeft out or doubted:")
    for issue in notes.items:
        print(f"  {issue.level:<8} {issue.code:<18} {issue.rows or '':>5}  {issue.detail}")
    if not notes.items:
        print("  nothing")
    return 0


def snapshot(args) -> int:
    from . import snapshots, study
    notes = data.Notes()
    rows = study.load_books(notes, frozen=False)
    if rows.empty:
        print("Nothing to freeze: this season's records could not be read.")
        for issue in notes.items:
            print(f"  {issue.level}: {issue.detail}")
        return 1
    try:
        with study.books():
            report = snapshots.injury_report(set(rows.get("home", [])) | set(rows.get("away", [])))
    except Exception as exc:  # noqa: BLE001 - a snapshot without injuries beats none at all
        print(f"Injury report not read ({exc}); the snapshot goes ahead without it.")
        report = None
    done = snapshots.take(rows, injuries=report)
    if not done:
        print("Nothing to freeze: every week on the books already has a result in.")
    for path, what in done:
        print(f"{path.name}: {what}")
    return 0


#: A run is this old before the weekly job makes another.
RUN_EVERY_S = 6 * 86400


def weekly(args) -> int:
    """The scheduled job. The snapshot every time - the last one before the
    deadline is the one that stands - and the whole run about once a week.
    It goes online only if data/training/settings.json says
    {"refresh_archive": true}: then this season's archive file is fetched
    again first (one small file from The Prediction Tracker)."""
    import json
    from . import verdict
    args.quiet = args.no_trees = args.no_check = args.no_books = False
    done = snapshot(args)
    newest = verdict.latest()
    age = time.time() - float(newest.get("made", 0)) if newest else None
    if not args.force and age is not None and age < RUN_EVERY_S:
        print(f"The newest run is {age / 86400:.1f} days old - not run again yet.")
        return done
    try:
        settings = json.loads((data.folder() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    if isinstance(settings, dict) and settings.get("refresh_archive") is True:
        args.refresh = True
        fetch(args)
    args.quiet = True
    return run(args)


def check(args) -> int:
    from . import features, recipes, walkforward
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    if history.empty:
        print("No data to check.")
        return 1
    has_models = bool(data.model_columns(history))
    key = "updated" if has_models else "closing"
    setting = features.SETTINGS[key]
    prepared = features.prepare(history, setting, notes)
    make = (lambda: recipes.with_models(trees=False)) if has_models else recipes.without_models
    seasons = sorted(set(prepared["season"].tolist()))[walkforward.WARM_UP:]
    bad = 0
    for season in (seasons[len(seasons) // 3], seasons[2 * len(seasons) // 3], seasons[-2]):
        ok, what = walkforward.sealed(prepared, setting, make, season * 100 + 6)
        bad += not ok
        print(f"{'sealed' if ok else 'LEAK  '}  cut at week 6 of {season}: {what}")
    return 2 if bad else 0


def patterns(args) -> int:
    """Outside betting patterns (home underdogs) counted on our seasons - nothing taught."""
    from . import patterns as found
    text, path = found.run(sunday_only=not args.every_day)
    print(text)
    print(f"Written to {path}")
    return 0


def margin(args) -> int:
    """Four ways of taking the bookmaker's margin out of the moneylines, against the results."""
    from . import devig
    text, path = devig.run()
    print(text)
    print(f"Written to {path}")
    return 0


def decay(args) -> int:
    """How much of the models' disagreement with the line is left at each line of the week."""
    from . import decay as found
    text, path = found.run()
    print(text)
    print(f"Written to {path}")
    return 0


def featurevalue(args) -> int:
    """Each football fact added on its own to the line, walked forward, at each line timing."""
    from . import featurevalue as found
    text, path = found.run()
    print(text)
    print(f"Written to {path}")
    return 0


def fetch(args) -> int:
    """The season archives, one request each, a second apart. Files already
    on disk are left alone (this season's is fetched again with --refresh)."""
    import urllib.request
    where = data.archive_folder()
    where.mkdir(parents=True, exist_ok=True)
    have = data.archive_files(where)
    got = 0
    for season, name, url in data.archive_wanted():
        if season in have and not (args.refresh and season == max(have)):
            continue
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ACQL-Dashboard"})
            with urllib.request.urlopen(request, timeout=30) as reply:
                body = reply.read()
        except Exception as exc:  # noqa: BLE001 - reported, and the rest are still tried
            print(f"{name}: not fetched ({exc})")
            continue
        head = body[:400].decode("utf-8", "replace").casefold()
        if "home" not in head or "line" not in head:
            print(f"{name}: what came back is not a predictions file - not kept")
            continue
        (where / name).write_bytes(body)
        got += 1
        print(f"{name}: {len(body):,} bytes")
        time.sleep(1.0)
    print(f"{got} file(s) fetched into {where}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m acql.training", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="say what is being done as it is done")
    commands = parser.add_subparsers(dest="command")
    r = commands.add_parser("run", help="every experiment, and the report")
    r.add_argument("--no-trees", action="store_true", help="leave the gradient-boosted trees out (the slow part)")
    r.add_argument("--no-check", action="store_true", help="skip the no-leak check")
    r.add_argument("--no-books", action="store_true", help="past seasons only: do not read the dashboard's database")
    r.add_argument("--quiet", action="store_true")
    commands.add_parser("report", help="write the newest run's report again")
    a = commands.add_parser("audit", help="what data there is to learn from")
    a.add_argument("--no-books", action="store_true")
    commands.add_parser("snapshot", help="freeze this week's numbers as they stand")
    w = commands.add_parser("weekly", help="the scheduled job: the snapshot, and a run when one is due")
    w.add_argument("--force", action="store_true", help="run now, however new the last run is")
    commands.add_parser("check", help="the check that no result can leak backwards")
    pt = commands.add_parser("patterns", help="home-underdog patterns counted on our seasons")
    pt.add_argument("--every-day", action="store_true", help="count Thursday and Monday games too")
    commands.add_parser("margin", help="four ways of taking the margin out of the moneylines, measured")
    commands.add_parser("decay", help="the models' edge over the line, open to close, measured")
    commands.add_parser("features", help="each football fact on its own, on top of the line, measured")
    f = commands.add_parser("fetch", help="the season archives from The Prediction Tracker (goes online)")
    f.add_argument("--refresh", action="store_true", help="fetch this season's file again")
    args = parser.parse_args(argv)
    _logging(args.verbose)
    todo = {"run": run, "report": again, "audit": audit, "snapshot": snapshot, "check": check, "weekly": weekly,
            "fetch": fetch, "patterns": patterns, "margin": margin, "decay": decay,
            "features": featurevalue}.get(args.command)
    if todo is None:
        parser.print_help()
        return 0
    return todo(args)


if __name__ == "__main__":
    raise SystemExit(main())
