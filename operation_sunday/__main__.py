"""Command line.

    python -m operation_sunday calendar --season 2026
    python -m operation_sunday run [--season S --week W] [--now ISO] [--games CSV] [--no-fetch] [--no-lock]
    python -m operation_sunday backtest [--seasons 2012 ... ] [--unlock-holdout REASON] [--out DIR]
    python -m operation_sunday ablation [--seasons ...] [--out DIR]
    python -m operation_sunday status [--season S --week W]
    python -m operation_sunday rollback --reason TEXT
    python -m operation_sunday check-deadline [--now ISO]   # exits 2 if this week is not locked by its deadline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import load_settings
from .tz import parse_utc, utc_now


def _games(settings, args):
    from . import data
    path = Path(args.games) if getattr(args, "games", None) else settings.state_path / "cache" / "games.csv"
    if not path.exists():
        data.fetch(settings.games_csv_url, path)
    return data.load_csv(path, parse_utc(args.now) if getattr(args, "now", None) else utc_now())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="operation_sunday")
    ap.add_argument("--settings")
    ap.add_argument("--log", action="store_true", help="append output to <state>/run.log (for scheduled runs)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calendar"); c.add_argument("--season", type=int, required=True); c.add_argument("--games")
    r = sub.add_parser("run")
    r.add_argument("--season", type=int); r.add_argument("--week", type=int); r.add_argument("--now")
    r.add_argument("--games"); r.add_argument("--no-fetch", action="store_true"); r.add_argument("--no-lock", action="store_true")
    r.add_argument("--lock-now", action="store_true", help="lock now even outside the lock window")
    r.add_argument("--market", help="CSV of market snapshots (game_id, taken_at, home_prob/home_spread, source)")
    b = sub.add_parser("backtest"); b.add_argument("--seasons", type=int, nargs="*"); b.add_argument("--games")
    b.add_argument("--unlock-holdout"); b.add_argument("--out")
    a = sub.add_parser("ablation"); a.add_argument("--seasons", type=int, nargs="*"); a.add_argument("--games"); a.add_argument("--out")
    s = sub.add_parser("status"); s.add_argument("--season", type=int); s.add_argument("--week", type=int)
    rb = sub.add_parser("rollback"); rb.add_argument("--reason", required=True)
    cd = sub.add_parser("check-deadline"); cd.add_argument("--now"); cd.add_argument("--games")
    cd.add_argument("--since", help="only check weeks locking after this ISO time (default: the journal's first package)")
    args = ap.parse_args(argv)
    settings = load_settings(args.settings)
    if args.log:
        import contextlib
        log = settings.state_path / "run.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh, contextlib.redirect_stdout(fh), contextlib.redirect_stderr(fh):
            print(f"--- {utc_now().isoformat()} {args.cmd}")
            try:
                code = _dispatch(args, settings)
                if args.cmd == "run":     # every scheduled run also checks past deadlines
                    args.since, args.now, args.games = None, None, None
                    code = max(code, _dispatch(argparse.Namespace(**{**vars(args), "cmd": "check-deadline"}), settings))
                return code
            except Exception:  # noqa: BLE001 - keep the traceback in the log
                import traceback
                traceback.print_exc()
                return 1
    return _dispatch(args, settings)


def _dispatch(args, settings) -> int:

    if args.cmd == "calendar":
        from .schedule import season_calendar
        ds = _games(settings, args)
        for d in season_calendar(ds.games, args.season, settings):
            print(f"{d.season} {d.game_type} wk{d.week:>2}  lock {d.lock_utc.isoformat()}  ({d.reason})  run due {d.run_due_utc.isoformat()}")
        return 0
    if args.cmd == "run":
        from .pipeline import run_week
        from .data import load_snapshots
        res = run_week(settings, args.season, args.week, parse_utc(args.now) if args.now else None,
                       games_csv=args.games, fetch=not args.no_fetch, lock=False if args.no_lock else (True if args.lock_now else "auto"),
                       snapshots=load_snapshots(args.market) if args.market else None)
        print(json.dumps({"season": res.season, "week": res.week, "status": res.status, "package": res.package_id,
                          "lock": res.lock, "decision": (res.decision or {}).get("action"),
                          "model": (res.decision or {}).get("model"), "alerts": res.alerts,
                          "warnings": res.warnings, "report": res.report_path}, indent=2, default=str))
        return 0
    if args.cmd in ("backtest", "ablation"):
        from .backtest import HoldoutGuard, eval_week_keys
        from .features import build_features
        ds = _games(settings, args)
        feats = build_features(ds.games, settings)
        seasons = args.seasons or list(settings.dev_eval_seasons)
        keys = eval_week_keys(feats, seasons)
        out = Path(args.out) if args.out else settings.state_path / "backtests"
        out.mkdir(parents=True, exist_ok=True)
        if args.cmd == "ablation":
            from .ablation import run
            HoldoutGuard(settings).check(seasons)
            res = run(feats, keys, settings)
            res["table"].to_csv(out / "ablation.csv", index=False)
            print(res["table"].to_string(index=False))
            return 0
        from .pipeline import evaluate
        from .report import model_table
        from .pipeline import candidate_meta
        from .models import base_candidates
        scored, weights, _ = evaluate(feats, settings, keys, HoldoutGuard(settings), args.unlock_holdout)
        scored.to_csv(out / "predictions.csv", index=False)
        names = list(dict.fromkeys(scored["model"]))
        names = [n for n in names if scored[scored["model"] == n]["p_home"].notna().any()]
        t = model_table(scored, names, candidate_meta(base_candidates()))
        t.to_csv(out / "summary.csv", index=False)
        print(t.to_string(index=False))
        print(json.dumps(weights, indent=1, default=str))
        return 0
    if args.cmd == "status":
        from .journal import Journal
        j = Journal(settings.state_path / "journal.sqlite")
        for p in j.packages(args.season, args.week):
            print(f"{p['package_id']}: {p['status']} on_time={p['on_time']} model={p['model_version']} hash={p['content_hash']}")
        for a in j.alerts(args.season, args.week)[-10:]:
            print(f"ALERT {a['raised_at']} [{a['level']}] {a['message']}")
        return 0
    if args.cmd == "rollback":
        from .registry import Registry
        print(json.dumps(Registry(settings.state_path).rollback(args.reason), indent=2))
        return 0
    if args.cmd == "check-deadline":
        from .journal import Journal
        from .schedule import next_week, season_calendar
        now = parse_utc(args.now) if args.now else utc_now()
        ds = _games(settings, args)
        j = Journal(settings.state_path / "journal.sqlite")
        bad = 0
        pk = [p for p in j.packages() if p["mode"] == "live"]
        since = parse_utc(args.since) if args.since else (min(parse_utc(p["deadline_utc"]) for p in pk) if pk else None)
        season = int(sorted(ds.games.loc[ds.games["kickoff_utc"] <= pd.Timestamp(now), "season"].unique())[-1])
        past = [d for d in season_calendar(ds.games, season, settings) if d.lock_utc <= now]
        if since is None:
            past = past[-1:]          # nothing journaled yet: only the latest deadline is checked
        else:
            past = [d for d in past if d.lock_utc >= since]
        for d in past:
            p = j.package(d.season, d.week, d.game_type, 0)
            if not p or p["status"] != "locked":
                print(f"MISSED: {d.season} wk{d.week} had no locked package by {d.lock_utc.isoformat()}")
                bad += 1
            elif not p["on_time"]:
                print(f"LATE: {d.season} wk{d.week} locked {p['locked_at']} after {d.lock_utc.isoformat()}")
                bad += 1
            else:
                print(f"OK: {d.season} wk{d.week} locked on time {p['locked_at']} ({p['content_hash'][:12]})")
        nxt = next_week(ds.games, now, settings)
        if nxt:
            print(f"next lock: {nxt.season} wk{nxt.week} at {nxt.lock_utc.isoformat()} (run due {nxt.run_due_utc.isoformat()})")
        return 2 if bad else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
