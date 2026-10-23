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
    python -m acql.training calibration  are Deadeye's chances honest? the margin-to-chance step, audited
    python -m acql.training fetch     the season archives from The Prediction Tracker (about 2 MB;
                                       goes online, and only when asked)
    python -m acql.training lab       the strategy lab: Elo, scoring model, logistic, boosted trees,
                                       averages and a meta-learner against Deadeye and the market,
                                       walked forward on two questions apart - did the home side win
                                       (probability) and was it credited (ACQL) - finalists frozen per
                                       track; judged only on locked weeks (--protocol 1: the old single
                                       question with its own test seasons)
                                       (lab lock | verify | score: the weekly locked forecasts, judged)
    python -m acql.training record    Deadeye's saved deadline cards, scored on both lab questions -
                                       the record kept apart from cards rebuilt or saved late
    python -m acql.training pfm       Pro Football Mania's ratings: pull a snapshot (goes online,
                                       36 pages two seconds apart), then measure them against Deadeye
                                       (--no-pull measures only; shadow only, never a pick)

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
    _weekly_pfm()
    _weekly_prereg()
    _weekly_lab_lock()
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


def calibration(args) -> int:
    """Deadeye's chances against results: the curve, its width, and recalibration, walked forward."""
    from . import calibration as found
    if args.part == "join":
        text, path = found.join()
    elif args.part:
        found.run_part(args.part)
        text, path = found.join()
    else:
        text, path = found.run()
    print(text)
    print(f"Written to {path}")
    return 0


def pfm(args) -> int:
    """PFM's ratings: one snapshot (unless --no-pull), then the study on every
    snapshot kept. Writes data/training/pfm/; the Model Lab reads latest.json."""
    from ..feeds import pfm as feed
    from . import pfm as found
    if not args.no_pull:
        got = feed.refresh()
        print(f"PFM pull: {got['what']}" + (f" ({got.get('status')}, update of {got.get('effective_date')}, "
                                             f"{got.get('pages')} pages)" if got["what"] != "failed" else
                                             f" - {got.get('detail')}"))
        for issue in got.get("issues", [])[:12]:
            print(f"  {issue['level']}: {issue['detail']}")
        print(f"  {got['freshness']['words']}")
    text, path = found.run()
    print(text.split("\n\n")[1] if "\n\n" in text else text)    # the verdict line
    print(f"Written to {path}")
    return 0


#: The weekly job pulls PFM again only when the newest snapshot is this old (PFM updates once a week).
PFM_EVERY_S = 20 * 3600


def prereg(args) -> int:
    """The pre-registered tests (prereg.py), scored on the frozen weeks so far."""
    from . import prereg as plans
    for found in plans.run():
        rng = "" if found["low"] is None else f" (range {found['low']:+.4f} to {found['high']:+.4f})"
        print(f"{found['id']} [{found['fingerprint']}]: {found['games']} games, "
              f"edge {found['edge']:+.4f}{rng} - {found['call']}")
    return 0


def _weekly_prereg() -> None:
    """The weekly job's pre-registered tests. Never stops the rest of the job."""
    try:
        prereg(None)
    except Exception as exc:  # noqa: BLE001
        print(f"Pre-registered tests skipped ({type(exc).__name__}: {exc})")


def record(args) -> int:
    """Deadeye's own record (record.py): the cards it saved before each deadline, scored on both tracks."""
    from . import record as rec
    found = rec.run(args.year)
    print(f"Deadeye's saved cards, {args.year}:")
    for week, w in found["weeks"].items():
        flag = f"  card line not this game's: {', '.join(w['line_mismatch'])}" if w["line_mismatch"] else ""
        print(f"  week {week:>2}: {w['status']:<26} {w['graded']:>2}/{w['games']} graded{flag}")
    for pile, tracks in found["tracks"].items():
        for track, s in tracks.items():
            if s.get("games", 0) < 2:
                continue
            d, m, e = s["deadeye"], s["market"], s["deadeye_vs_market"]
            rng = e.get("range") or f"{e['low']:+.4f} to {e['high']:+.4f}"
            print(f"  {pile} / {track}: {s['games']} games, {s['weeks']} weeks - log loss Deadeye {d['logloss']:.4f}, "
                  f"market {m['logloss']:.4f}; Deadeye's lead {e['edge']:+.4f} ({rng}); right {d['right']} vs {m['right']}")
    drift = found.get("replay_drift") or {}
    if drift.get("games"):
        print(f"  The books' re-priced Deadeye against the saved card: {drift['mean']:.3f} apart on average "
              f"(largest {drift['largest']:.3f}), other side on {drift['other_side']} of {drift['games']} games")
    print(f"Written: {rec.folder() / 'latest.json'}")
    return 0


def lab(args) -> int:
    """The strategy lab (strategylab.py), or its locked weekly forecasts (lablocks.py)."""
    from . import lablocks, strategylab
    if args.action == "verify":
        problems = lablocks.verify()
        print("every lock is as it was written" if not problems else "\n".join(problems))
        return 2 if problems else 0
    if args.action == "score":
        found = lablocks.score()
        if found["weeks"]:
            print(f"one-question locks scored: {', '.join(found['weeks'])}")
            for sid, s in sorted(found["strategies"].items(), key=lambda kv: kv[1]["logloss"]):
                print(f"  {sid:<22} {s['games']:>4} games  log loss {s['logloss']:.4f}  right {s['right']}")
        judged = lablocks.judge(write=True)
        if judged is None:
            print("No two-track lab run yet (python -m acql.training lab run).")
            return 0
        for track, j in judged.items():
            print(f"\n{track} track: {j['why']}")
            for sid, r in j["finalists"].items():
                if not r.get("games"):
                    print(f"  {sid:<22}    0 games")
                    continue
                extra = (f"  picks a week vs Deadeye {r['picks_vs_deadeye']['edge']:+.2f}"
                         if "picks_vs_deadeye" in r else "")
                print(f"  {sid:<22} {r['games']:>4} games  log loss {r['logloss']:.4f}  vs Deadeye "
                      f"{r['vs_deadeye']['edge']:+.4f}{extra}")
        print(f"\nChampions: {strategylab.champions_path()}")
        return 0
    if args.action == "lock":
        season, week = lablocks.current_week()
        if season is None:
            print("No week ahead on the books to lock.")
            return 1
        print(lablocks.lock_week(season, week, window=None if args.now else lablocks.LOCK_WINDOW_S))
        return 0
    print("Strategy lab - reads the archives and a copy of nothing else; changes no pick.", flush=True)
    go = strategylab.run2 if args.protocol == "2" else strategylab.run
    found = go(auto=not args.no_auto, leak_check=not args.no_check,
               timings=[args.timing] if args.timing else None, progress=_progress())
    if args.protocol == "2":
        print(f"\nDone in {found['took']:.0f}s. Finalists frozen for both tracks; nominations come only from "
              "locked weeks (lab score).")
    else:
        print(f"\nDone in {found['took']:.0f}s. Nominee: {found['nominee'] or 'none'}.")
    print(f"Report:  {strategylab.folder() / 'latest' / 'report.md'}")
    return 0


def _weekly_lab_lock() -> None:
    """The weekly job's locked lab forecasts: only within a day or so of the
    deadline, only once a week, only if a lab run exists. Never stops the job."""
    try:
        from . import lablocks, strategylab
        if not (strategylab.folder() / "latest" / "results.json").exists():
            return
        season, week = lablocks.current_week()
        if season is not None:
            print(f"Lab lock: {lablocks.lock_week(season, week)}")
    except Exception as exc:  # noqa: BLE001
        print(f"Lab lock skipped ({type(exc).__name__}: {exc})")


def _weekly_pfm() -> None:
    """The weekly job's PFM step (Sam approved weekly pulls on 2026-10-18).
    Never stops the rest of the job."""
    try:
        from ..feeds import pfm as feed
        from . import pfm as found
        newest = feed.latest()
        if newest is None or time.time() - float(newest.get("collected_at") or 0) >= PFM_EVERY_S:
            got = feed.refresh()
            print(f"PFM pull: {got['what']} - {got['freshness']['words']}")
        found.run()
    except Exception as exc:  # noqa: BLE001 - PFM is a side study; the training run goes on
        print(f"PFM step skipped ({type(exc).__name__}: {exc})")


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
    c = commands.add_parser("calibration", help="Deadeye's chances against results, walked forward (shadow only)")
    c.add_argument("part", nargs="?", choices=("midweek", "opening", "updated", "join"),
                   help="one line timing only (then the report is joined again), or just join the parts")
    pf = commands.add_parser("pfm", help="Pro Football Mania's ratings: a snapshot, then measured (shadow only)")
    pf.add_argument("--no-pull", action="store_true", help="measure on the snapshots already kept; do not go online")
    commands.add_parser("prereg", help="the tests written down before their games, scored (shadow only)")
    rc = commands.add_parser("record", help="Deadeye's saved deadline cards, scored on both lab questions (reads only)")
    rc.add_argument("--year", type=int, default=2026)
    lb = commands.add_parser("lab", help="the strategy lab (shadow only), or its locked weekly forecasts")
    lb.add_argument("action", nargs="?", choices=("run", "lock", "verify", "score"), default="run")
    lb.add_argument("--timing", choices=("midweek", "opening", "updated"), help="one timing only")
    lb.add_argument("--no-auto", action="store_true", help="first-round candidates only, no proposals")
    lb.add_argument("--no-check", action="store_true", help="skip the leak check")
    lb.add_argument("--now", action="store_true", help="lock: lock now, however long before the deadline")
    lb.add_argument("--protocol", choices=("1", "2"), default="2",
                    help="run: strategy-lab-2 (two tracks, the default) or strategy-lab-1 "
                         "(one question; each run opens its test seasons again)")
    f = commands.add_parser("fetch", help="the season archives from The Prediction Tracker (goes online)")
    f.add_argument("--refresh", action="store_true", help="fetch this season's file again")
    args = parser.parse_args(argv)
    _logging(args.verbose)
    todo = {"run": run, "report": again, "audit": audit, "snapshot": snapshot, "check": check, "weekly": weekly,
            "fetch": fetch, "patterns": patterns, "margin": margin, "decay": decay,
            "features": featurevalue, "calibration": calibration, "pfm": pfm,
            "prereg": prereg, "lab": lab, "record": record}.get(args.command)
    if todo is None:
        parser.print_help()
        return 0
    return todo(args)


if __name__ == "__main__":
    raise SystemExit(main())
