"""Command line: python -m challenger <command>.

    fetch              download the nflverse schedule and play-by-play (cached under data/challenger)
    tune-elo           re-run the Elo grid on 2002-2009 (prints; the chosen values are pinned in config.py)
    backtest           walk-forward backtest:  --split dev|holdout  [--variant market_free|market_informed|no_epa]
    evaluate           head-to-head vs Deadeye, the market and ACQL scoring:  --split dev|holdout
    shadow             journal forecasts for an upcoming week:  --season 2026 --week 7
    capture-deadeye    journal Deadeye's own forecast for that week (independently)
    record-outcomes    append final scores for journaled games that have finished
    shadow-report      score the prospective journal
    verify             check every stored prediction file and journal against its hashes
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m challenger", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "tune-elo", "backtest", "evaluate", "shadow", "capture-deadeye",
                                        "record-outcomes", "shadow-report", "verify"])
    ap.add_argument("--split", choices=["dev", "holdout"], default="dev")
    ap.add_argument("--variant", default="market_free", choices=["market_free", "market_informed", "no_epa"])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int)
    ap.add_argument("--file")
    ap.add_argument("--first-season", type=int, default=2001)
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.command == "fetch":
        from . import data, pbp

        data.fetch_schedule(force=True)
        last = int(data.load_games()["season"].max())
        data.fetch_pbp(range(args.first_season, last + 1), refresh=(last,))
        teams, _ = pbp.aggregate(range(args.first_season, last + 1))
        print(f"schedule + pbp {args.first_season}-{last} cached; {len(teams)} team-games aggregated")
    elif args.command == "tune-elo":
        import pandas as pd

        from . import data, elo, features
        from .config import DEFAULT

        g = data.load_games()
        g = g[g["season"] >= 1999].reset_index(drop=True)
        best, table = elo.tune(g, (2002, 2009), features.deadlines(g, DEFAULT),
                               g["kickoff_utc"] + pd.Timedelta(hours=DEFAULT.game_duration_hours))
        print(table.head(15).to_string())
        print(best)
    elif args.command == "backtest":
        from . import runs

        print(json.dumps(runs.run(args.split, args.variant), indent=1))
    elif args.command == "evaluate":
        from .arena import run

        s = run.evaluate(args.split)
        print(json.dumps({"coverage": s["coverage"], "acql": s["acql"]}, indent=1))
    elif args.command == "shadow":
        from . import shadow

        print(json.dumps(shadow.forecast_week(args.season, args.week, refresh=not args.no_refresh), indent=1))
    elif args.command == "capture-deadeye":
        from .arena import capture

        print(json.dumps(capture.capture_deadeye(args.season, args.week, args.file), indent=1, default=str))
    elif args.command == "record-outcomes":
        from . import shadow

        print(f"{shadow.record_outcomes(args.season, refresh=not args.no_refresh)} outcomes appended")
    elif args.command == "shadow-report":
        from .arena import capture

        print(json.dumps(capture.shadow_report(), indent=1, default=str))
    elif args.command == "verify":
        from . import journal, predictions
        from .config import RESULTS

        ok = True
        for path in sorted((RESULTS / "backtests").glob("predictions_*.csv.gz")):
            good = predictions.verify(path)
            ok &= good
            print(f"{'ok    ' if good else 'BROKEN'} {path.name}")
        for kind in journal.KINDS:
            good, why = journal.verify(kind)
            ok &= good
            print(f"{'ok    ' if good else 'BROKEN'} journal/{kind}.jsonl ({why}, {len(journal.read(kind))} records)")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
