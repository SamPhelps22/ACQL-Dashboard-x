"""python -m research_lab <command>

    fetch          download the public nflverse files (manifest with hashes)
    build          derive team-game, QB-game and drive tables from play-by-play
    inventory      data coverage report -> research_lab/docs/DATA_INVENTORY.md
    dev            walk-forward backtest 2009-2023, ensembles, evaluation 2012-2023, ablation
    freeze         record the frozen configuration (required before `holdout`)
    holdout        score the frozen holdout (2024-2025) once
    extensions     Model H (2021-2025) and 2026-to-date comparison with Deadeye's recomputed forecasts
    shadow         record forecasts for the next unplayed week (append-only journal)
    grade          grade shadow forecasts whose games are final
    report         rebuild the markdown reports from saved outputs
"""

from __future__ import annotations

import json
import sys
import time
import warnings

import pandas as pd

from . import config

warnings.filterwarnings("ignore", category=RuntimeWarning)


def _save(obj, name):
    config.OUTPUTS.mkdir(parents=True, exist_ok=True)
    (config.OUTPUTS / name).write_text(json.dumps(obj, indent=1, default=str))


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "fetch":
        from .data import fetch
        print(fetch.fetch())
        print("dataset_version", fetch.dataset_version())
    elif cmd == "build":
        from .data import pbp
        print(pbp.build())
    elif cmd == "inventory":
        from .data import inventory
        print(inventory.write())
    elif cmd in ("dev", "smoke"):
        from . import pipeline
        from .data.store import Store
        seasons = range(pipeline.WARM_FROM, config.DEV_TO + 1) if cmd == "dev" else range(2009, 2014)
        scored = range(config.DEV_FROM, config.DEV_TO + 1) if cmd == "dev" else range(2012, 2014)
        tag = cmd
        store = Store.load()
        fc = pipeline.backtest(seasons, tag, store=store)
        g, _ = pipeline.ensembles(fc, store, scored, tag)
        g = __import__("research_lab.backtest.engine", fromlist=["x"]).calibrate(
            g.drop(columns=["p_home_cal", "p_away_cal"]), store=store)
        allf = pd.concat([fc, g], ignore_index=True)
        allf.to_csv(config.OUTPUTS / f"forecasts_all_{tag}.csv.gz", index=False)
        ev = pipeline.evaluate(allf, store, scored, f"{min(scored)}-{max(scored)} (development)")
        _save(ev, f"eval_{tag}.json")
        ab = pipeline.run_ablation(allf, store, scored, f"{min(scored)}-{max(scored)}")
        ab.to_csv(config.OUTPUTS / f"ablation_{tag}.csv", index=False)
        from .reports import build
        build.all_reports()
    elif cmd == "freeze":
        from .experiments import registry
        rec = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": registry.commit(),
               "note": " ".join(argv[1:])}
        (config.ROOT / "research_lab" / "experiments" / "freeze.json").write_text(json.dumps(rec, indent=1))
        registry.record("freeze", "holdout freeze", rec, "ok")
        print(rec)
    elif cmd == "holdout":
        from . import pipeline
        from .backtest import engine
        from .data.store import Store
        freeze = config.ROOT / "research_lab" / "experiments" / "freeze.json"
        if not freeze.exists():
            print("refusing: run `python -m research_lab freeze` first")
            return 2
        store = Store.load()
        dev = pd.read_csv(config.OUTPUTS / "forecasts_dev.csv.gz")
        hold = pipeline.backtest(range(config.HOLDOUT[0], config.HOLDOUT[1] + 1), "holdout", store=store)
        both = pd.concat([dev, hold], ignore_index=True)
        both = engine.calibrate(both.drop(columns=["p_home_cal", "p_away_cal"]), store=store)
        g, _ = pipeline.ensembles(both, store, range(config.HOLDOUT[0], config.HOLDOUT[1] + 1), "holdout")
        g = engine.calibrate(pd.concat([g]).drop(columns=["p_home_cal", "p_away_cal"]), store=store)
        allf = pd.concat([both, g], ignore_index=True)
        allf = allf[allf["season"] >= config.HOLDOUT[0]]
        allf.to_csv(config.OUTPUTS / "forecasts_all_holdout.csv.gz", index=False)
        ev = pipeline.evaluate(allf, store, range(config.HOLDOUT[0], config.HOLDOUT[1] + 1),
                               f"{config.HOLDOUT[0]}-{config.HOLDOUT[1]} (frozen holdout)")
        _save(ev, "eval_holdout.json")
        ab = pipeline.run_ablation(pd.concat([pd.read_csv(config.OUTPUTS / "forecasts_all_dev.csv.gz"), allf]),
                                   store, range(config.HOLDOUT[0], config.HOLDOUT[1] + 1),
                                   f"{config.HOLDOUT[0]}-{config.HOLDOUT[1]} holdout")
        ab.to_csv(config.OUTPUTS / "ablation_holdout.csv", index=False)
        from .reports import build
        build.all_reports()
    elif cmd == "extensions":
        from . import extensions
        from .data.store import Store
        store = Store.load()
        print(extensions.current_season(store))
        if (config.ROOT / "research_lab" / "experiments" / "freeze.json").exists():
            print(extensions.model_h(store))
        from .reports import build
        build.all_reports()
    elif cmd == "shadow":
        from .shadow import journal, report
        r = journal.forecast_next()
        print(r)
        if "week" in r:
            print(report.write(r["season"], r["week"]))
    elif cmd == "grade":
        from .shadow import journal, report
        print(journal.grade())
        for s_, w_ in sorted({(e["season"], e["week"]) for e in journal.read()}):
            print(report.write(s_, w_))
    elif cmd == "report":
        from .reports import build
        build.all_reports()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
