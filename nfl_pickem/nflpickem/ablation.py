"""Feature-group ablation: does each football-intelligence group improve
out-of-sample predictions beyond the base model and the market?

Every variant runs the same walk-forward backtest (dev seasons only; holdout
excluded) on the same point-in-time feature table, changing only which feature
groups the ML/residual models see. Decisions about which groups to enable are
made from these development-period results, never from the holdout.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone

import pandas as pd

from .backtest import features_from_db, run_backtest
from .evaluation import paired_week_difference

log = logging.getLogger(__name__)

VARIANTS = {
    "base": [],
    "base+units": ["units"],
    "base+qb_rating": ["qb_rating"],
    "base+matchup": ["matchup"],
    "base+all": ["units", "qb_rating", "matchup"],
}
TRACKED = ["market", "logistic", "gbm", "residual", "ml_only", "blend"]


def run_ablation(con, cfg: dict, variants: dict[str, list[str]] | None = None,
                 seasons: list[int] | None = None) -> pd.DataFrame:
    variants = variants or VARIANTS
    feats = features_from_db(con, cfg)
    rows, weekly = [], {}
    for name, groups in variants.items():
        c = copy.deepcopy(cfg)
        c["features"]["groups"] = list(groups)
        res = run_backtest(con, c, seasons=seasons, save=False, features=feats)
        pool = res.pool.set_index("model")
        for _, m in res.metrics.iterrows():
            if m.model not in TRACKED:
                continue
            rows.append({"variant": name, "model": m.model, "games": m.games, "accuracy": m.accuracy,
                         "log_loss": m.log_loss, "brier": m.brier,
                         "avg_weekly_points": pool.loc[m.model, "avg_weekly"]})
        weekly[name] = res.weekly
        log.info("Ablation variant %s done", name)
    table = pd.DataFrame(rows)
    # paired weekly comparisons vs the base variant and vs the market
    base = weekly[next(iter(variants))]
    comps = []
    for name, wk in weekly.items():
        for model in ("logistic", "gbm", "residual", "blend"):
            a = wk[wk.model == model].assign(model=f"{model}@{name}")
            b = base[base.model == model].assign(model=f"{model}@base")
            mk = wk[wk.model == "market"]
            both = pd.concat([a, b, mk])
            if name != next(iter(variants)):
                d = paired_week_difference(both, f"{model}@{name}", f"{model}@base")
                comps.append({"variant": name, "model": model, "vs": "same model, base features", **d})
            d = paired_week_difference(both, f"{model}@{name}", "market")
            comps.append({"variant": name, "model": model, "vs": "market", **d})
    paired = pd.DataFrame(comps)
    created = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("CREATE TABLE IF NOT EXISTS ablation_runs (created_at TIMESTAMP, seasons VARCHAR, "
                "table_json VARCHAR, paired_json VARCHAR)")
    con.execute("INSERT INTO ablation_runs VALUES (?, ?, ?, ?)",
                [created, json.dumps(seasons or "dev"), table.to_json(orient="records"),
                 paired.to_json(orient="records")])
    return table, paired


def latest_ablation(con) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    try:
        row = con.execute("SELECT table_json, paired_json FROM ablation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not row:
        return None
    return pd.read_json(__import__("io").StringIO(row[0])), pd.read_json(__import__("io").StringIO(row[1]))
