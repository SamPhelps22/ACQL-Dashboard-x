"""Command-line interface: python -m nflpickem <command> [options]."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import db
from .config import load_config, resolve_path

log = logging.getLogger("nflpickem")

# Backtest windows for the synthetic league (seasons 2101+).
DEMO_OVERRIDES = {"backtest": {"first_eval_season": 2103, "last_eval_season": 2199,
                               "holdout_seasons": [], "min_train_seasons": 2}}


def _connect(cfg: dict, args) -> "db.duckdb.DuckDBPyConnection":
    path = args.db or (cfg["data"]["demo_db_path"] if getattr(args, "demo", False) else cfg["data"]["db_path"])
    return db.connect(resolve_path(path))


def _cfg_for(con, cfg: dict) -> dict:
    if db.get_meta(con, "data_mode") == "synthetic":
        from .config import _deep_merge
        return _deep_merge(cfg, DEMO_OVERRIDES)
    return cfg


def _parse_now(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def cmd_init(cfg, args):
    con = _connect(cfg, args)
    print(json.dumps(db.validate_database(con), indent=2, default=str))


def cmd_demo(cfg, args):
    from .ingest import synthetic
    path = resolve_path(args.db or cfg["data"]["demo_db_path"])
    if path.exists():
        path.unlink()
    con = db.connect(path)
    now = synthetic.load_into(con, n_seasons=args.seasons, seed=args.seed)
    print(f"SYNTHETIC demo database written to {path} (pinned 'now' = {now:%Y-%m-%d}).")
    print("This is NOT real NFL data. Next: python -m nflpickem --demo backtest && python -m nflpickem --demo predict")


def cmd_ingest(cfg, args):
    from .ingest import nflverse
    con = _connect(cfg, args)
    first = args.first_season or int(cfg["data"]["first_season"])
    games = nflverse.ingest_schedule(con, first)
    last = int(games.loc[games["game_status"] == "final", "season"].max())
    seasons = list(range(first, last + 1)) if not args.seasons else args.seasons
    if not args.skip_pbp:
        nflverse.ingest_pbp(con, seasons, resolve_path(cfg["data"]["cache_dir"]), keep_cache=args.keep_cache,
                            force=args.force)
    if not args.skip_injuries and cfg["data"].get("injury_provider") == "nflverse":
        nflverse.ingest_injuries(con, last)
    db.set_meta(con, "data_mode", "real")
    print(json.dumps(db.validate_database(con), indent=2, default=str))


def cmd_update(cfg, args):
    from .pipeline import update_data
    con = _connect(cfg, args)
    print(json.dumps(update_data(con, cfg, now=_parse_now(args.now)), indent=2, default=str))


def cmd_backtest(cfg, args):
    from .backtest import run_backtest
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    if args.blend_mode:
        cfg["blend"]["mode"] = args.blend_mode
    res = run_backtest(con, cfg, seasons=args.seasons, include_holdout=args.include_holdout)
    pd.set_option("display.width", 200)
    print(f"Backtest {res.backtest_id}  seasons={res.seasons}  holdout_included={args.include_holdout}")
    print("\nProbability metrics (out-of-sample, ties excluded):")
    print(res.metrics.round(4).to_string(index=False))
    print("\nConfidence-pool simulation:")
    print(res.pool.round(2).to_string(index=False))
    print("\nBlend vs baselines (mean weekly point difference, 95% CI):")
    for p in res.paired:
        print(f"  {p['a']:8s} - {p['b']:9s}: {p['mean_diff']:+.2f}  [{p['ci_low']:+.2f}, {p['ci_high']:+.2f}]  over {p['weeks']} weeks")
    print("\nEx-post market/ML ratio analysis (NOT used for selection):")
    print(res.blend_ratio_analysis.round(4).to_string(index=False))
    if args.report:
        out = resolve_path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        res.metrics.to_csv(out.with_name(out.stem + "_metrics.csv"), index=False)
        res.metrics_by_season.to_csv(out.with_name(out.stem + "_by_season.csv"), index=False)
        res.pool.to_csv(out.with_name(out.stem + "_pool.csv"), index=False)
        res.weekly.to_csv(out.with_name(out.stem + "_weekly.csv"), index=False)
        res.blend_ratio_analysis.to_csv(out.with_name(out.stem + "_blend_ratios.csv"), index=False)
        print(f"\nCSV reports written next to {out}")


def cmd_ablation(cfg, args):
    from .ablation import run_ablation
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    table, paired = run_ablation(con, cfg, seasons=args.seasons)
    pd.set_option("display.width", 220)
    print("Walk-forward ablation (development seasons, holdout excluded):")
    print(table.pivot_table(index="variant", columns="model", values="log_loss").round(4).to_string())
    print("\nAverage weekly pool points:")
    print(table.pivot_table(index="variant", columns="model", values="avg_weekly_points").round(2).to_string())
    print("\nPaired weekly point differences (95% CI):")
    print(paired[["variant", "model", "vs", "mean_diff", "ci_low", "ci_high", "weeks"]].round(2).to_string(index=False))
    if args.report:
        out = resolve_path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(out.with_name(out.stem + "_ablation.csv"), index=False)
        paired.to_csv(out.with_name(out.stem + "_ablation_paired.csv"), index=False)


def cmd_train(cfg, args):
    from .pipeline import effective_now, train_production
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    pm = train_production(con, cfg, effective_now(con, _parse_now(args.now)))
    print(f"Trained {pm.model_version} (through {pm.trained_through}); weights {pm.weights} [{pm.weights_source}]; "
          f"calibration {pm.calibrators}; params {pm.models.params}")


def cmd_predict(cfg, args):
    from .pipeline import data_mode, export_csv, freeze_run, predict_week
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    run_id, picks = predict_week(con, cfg, args.season, args.week, now=_parse_now(args.now),
                                 retrain=not args.use_saved_model)
    mode = data_mode(con)
    if mode == "synthetic":
        print("*** SYNTHETIC DEMO DATA - these are NOT real NFL forecasts ***")
    s, w = int(picks.season.iloc[0]), int(picks.week.iloc[0])
    cols = ["confidence_points", "away_team", "home_team", "selected_team", "selected_team_probability",
            "expected_points", "market_home_probability", "blended_home_probability", "odds_status", "data_flags"]
    print(f"Season {s} week {w}  run_id={run_id}  model={picks.model_version.iloc[0]}")
    print(picks[cols].round(3).to_string(index=False))
    print(f"Expected points: {picks.expected_points.sum():.2f} of {picks.confidence_points.sum()}")
    if args.freeze:
        freeze_run(con, run_id)
        print(f"Run {run_id} FROZEN as the submitted picks for week {w}.")
    label = "SYNTHETIC DEMO - NOT REAL NFL" if mode == "synthetic" else "nflverse data"
    path = export_csv(picks, Path(args.export or resolve_path(cfg["data"]["export_dir"]) /
                                  f"picks_{s}_wk{w:02d}_{run_id}.csv"), label)
    print(f"CSV: {path}")


def cmd_report(cfg, args):
    from .pipeline import list_runs
    from .reports import load_reports, to_markdown
    con = _connect(cfg, args)
    run_id = args.run_id or list_runs(con).run_id.iloc[0]
    reps = load_reports(con, run_id)
    if not reps:
        raise RuntimeError(f"No reports stored for {run_id}")
    order = sorted(reps.values(), key=lambda r: -r["confidence_points"])
    text = f"# Matchup reports - run {run_id}\n\n" + "\n\n".join(to_markdown(r) for r in order)
    if db.get_meta(con, "data_mode") == "synthetic":
        text = "**SYNTHETIC DEMO DATA - not real NFL forecasts**\n\n" + text
    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote {args.out}")
    else:
        print(text)


def cmd_review(cfg, args):
    from .review import review_week, systematic_check
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    r = review_week(con, cfg, args.season, args.week)
    if "games" not in r:
        print(r)
        return
    print(f"Season {r['season']} week {r['week']} run {r['run_id']}: {r['points']:.1f} pts "
          f"(market-only sheet {r['market_sheet_points']:.1f}, expected {r['expected_points']:.1f}) "
          f"over {r['games_graded']} graded games")
    print(f"Model log loss {r['model']['log_loss']:.4f} / Brier {r['model']['brier']:.4f};  "
          f"market {r['market']['log_loss']:.4f} / {r['market']['brier']:.4f}")
    print("Miss causes:", r["miss_causes"] or "none")
    print(pd.DataFrame(r["games"]).round(3).to_string(index=False))
    print("\nCalibration of submitted picks across graded weeks:")
    print(systematic_check(con, cfg).to_string(index=False))


def cmd_lines(cfg, args):
    from . import poollines
    from .pipeline import effective_now, next_slate
    con = _connect(cfg, args)
    season, week = args.season, args.week
    if season is None or week is None:
        nxt = next_slate(con, effective_now(con))
        if nxt is None:
            raise RuntimeError("No upcoming week; pass --season and --week")
        season, week = nxt
    if args.set:
        entries = []
        for item in args.set:
            parts = item.replace("=", " ").split()
            if len(parts) != 2:
                raise ValueError(f"Use 'TEAM LINE', e.g. 'KC 7' (got {item!r})")
            entries.append((parts[0], float(parts[1])))
        poollines.set_lines(con, season, week, entries)
    games = con.execute("SELECT game_id, away_team, home_team FROM games WHERE season=? AND week=? "
                        "ORDER BY kickoff_utc", [season, week]).df()
    posted = poollines.entered(con, season, week).set_index("game_id")
    print(f"Pool lines for {season} week {week} (entered by you; others are straight or estimated at predict time):")
    for r in games.itertuples():
        line = f"{posted.loc[r.game_id, 'favourite_team']} by {posted.loc[r.game_id, 'line']:g}" \
            if r.game_id in posted.index else "-"
        print(f"  {r.away_team:>3} @ {r.home_team:<3}  {line}")
    if args.set:
        print("Re-run `python -m nflpickem predict` to pick with these lines.")


def cmd_freeze(cfg, args):
    from .pipeline import freeze_run
    con = _connect(cfg, args)
    freeze_run(con, args.run_id)
    print(f"Frozen {args.run_id}")


def cmd_grade(cfg, args):
    from .pipeline import grade_all, grade_week, season_tracker
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    if args.season and args.week:
        print(grade_week(con, cfg, args.season, args.week).to_string(index=False))
    else:
        print(f"Graded {grade_all(con, cfg)} submitted weeks")
    print(season_tracker(con, cfg["pool"]["pool_id"]).to_string(index=False))


def cmd_weekly(cfg, args):
    from .pipeline import run_weekly
    con = _connect(cfg, args)
    cfg = _cfg_for(con, cfg)
    print(json.dumps(run_weekly(con, cfg, freeze=args.freeze, update=not args.no_update,
                                now=_parse_now(args.now)), indent=2, default=str))


def cmd_import_scores(cfg, args):
    from .pipeline import import_pool_scores
    con = _connect(cfg, args)
    n = import_pool_scores(con, pd.read_csv(args.csv), cfg["pool"]["pool_id"])
    print(f"Imported {n} score rows")


def cmd_status(cfg, args):
    con = _connect(cfg, args)
    rep = db.validate_database(con)
    rep["data_mode"] = db.get_meta(con, "data_mode", "empty")
    rep["last_update"] = db.get_meta(con, "last_update")
    print(json.dumps(rep, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nflpickem", description=__doc__)
    p.add_argument("--db", help="DuckDB path (default from config.toml)")
    p.add_argument("--demo", action="store_true", help="use the synthetic demo database")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create/validate the database schema").set_defaults(fn=cmd_init)
    d = sub.add_parser("demo", help="build the SYNTHETIC demo database")
    d.add_argument("--seasons", type=int, default=8)
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(fn=cmd_demo)

    i = sub.add_parser("ingest", help="load historical nflverse data")
    i.add_argument("--first-season", type=int)
    i.add_argument("--seasons", type=int, nargs="*", help="play-by-play seasons (default: all)")
    i.add_argument("--skip-pbp", action="store_true")
    i.add_argument("--skip-injuries", action="store_true")
    i.add_argument("--keep-cache", action="store_true", help="keep raw play-by-play parquet files")
    i.add_argument("--force", action="store_true", help="re-download seasons already complete")
    i.set_defaults(fn=cmd_ingest)

    u = sub.add_parser("update", help="incremental refresh of schedule, lines, pbp, injuries")
    u.add_argument("--now")
    u.set_defaults(fn=cmd_update)

    b = sub.add_parser("backtest", help="walk-forward backtest")
    b.add_argument("--seasons", type=int, nargs="*")
    b.add_argument("--include-holdout", action="store_true")
    b.add_argument("--blend-mode", choices=["fixed", "learned"])
    b.add_argument("--report", help="write CSV reports with this path prefix, e.g. data/exports/backtest")
    b.set_defaults(fn=cmd_backtest)

    a = sub.add_parser("ablation", help="walk-forward feature-group ablation")
    a.add_argument("--seasons", type=int, nargs="*")
    a.add_argument("--report")
    a.set_defaults(fn=cmd_ablation)

    t = sub.add_parser("train", help="train production models")
    t.add_argument("--now")
    t.set_defaults(fn=cmd_train)

    pr = sub.add_parser("predict", help="predict a week and allocate confidence points")
    pr.add_argument("--season", type=int)
    pr.add_argument("--week", type=int)
    pr.add_argument("--now", help="ISO timestamp (UTC) to predict as of")
    pr.add_argument("--freeze", action="store_true", help="freeze this run as the submitted picks")
    pr.add_argument("--export", help="CSV output path")
    pr.add_argument("--use-saved-model", action="store_true")
    pr.set_defaults(fn=cmd_predict)

    rp = sub.add_parser("report", help="print/write matchup reports for a run (default: latest)")
    rp.add_argument("--run-id")
    rp.add_argument("--out", help="write markdown to this file")
    rp.set_defaults(fn=cmd_report)

    rv = sub.add_parser("review", help="post-week review: results vs predictions, miss causes, calibration")
    rv.add_argument("--season", type=int, required=True)
    rv.add_argument("--week", type=int, required=True)
    rv.set_defaults(fn=cmd_review)

    ln = sub.add_parser("lines", help="enter/show the commissioner's pool lines for a week")
    ln.add_argument("--season", type=int)
    ln.add_argument("--week", type=int)
    ln.add_argument("--set", nargs="*", help="favourite and line, e.g. --set \"KC 7\" \"BUF 13\" (0 clears)")
    ln.set_defaults(fn=cmd_lines)

    f = sub.add_parser("freeze", help="freeze a prediction run as submitted")
    f.add_argument("run_id")
    f.set_defaults(fn=cmd_freeze)

    g = sub.add_parser("grade", help="grade submitted runs and update the season tracker")
    g.add_argument("--season", type=int)
    g.add_argument("--week", type=int)
    g.set_defaults(fn=cmd_grade)

    w = sub.add_parser("weekly", help="full weekly job (update, grade, predict, export)")
    w.add_argument("--freeze", action="store_true")
    w.add_argument("--no-update", action="store_true")
    w.add_argument("--now")
    w.set_defaults(fn=cmd_weekly)

    s = sub.add_parser("import-scores", help="import competitor weekly scores CSV")
    s.add_argument("csv")
    s.set_defaults(fn=cmd_import_scores)

    sub.add_parser("status", help="database status report").set_defaults(fn=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    try:
        args.fn(cfg, args)
    except (RuntimeError, ValueError, KeyError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
