"""Deadeye, for evaluation only. The ONLY lab module allowed to import acql.model.

It produces three clearly separated benchmarks. None is fed to any lab model
(a test enforces that no module under research_lab/models, simulation,
features or ensemble imports acql), and none writes anything to acql.

    deadeye_line_only_proxy   Deadeye's base (the market line) priced by Deadeye's own
                              margin->chance curve (acql.analytics.win_chance), using the
                              nflverse CLOSING spread. A proxy: Deadeye uses the line it has
                              when the card is made, not the closing number.  2006-2025.
    deadeye_recomputed        Deadeye's own code (predictions.Forecast.expected at the
                              default share, slate lean removed, models trimmed) run on the
                              Prediction Tracker files kept in the repo root
                              (nflpredictions week {3,4,5,7}.csv) and the recorded inputs in
                              acql-forecasts.json. Same inputs Deadeye had, recomputed:
                              NOT the forecast it displayed (that lived in data/acql.db,
                              which is not in the repository), and the in-season fitted
                              share is not reproduced.
    deadeye_recorded          the forecast log, if a copy of data/acql.db is present. In this
                              repository it is not, so this benchmark is reported as missing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config

CODE_FIX = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX"}


def _acql():
    import sys
    if str(config.ROOT) not in sys.path:
        sys.path.insert(0, str(config.ROOT))
    from acql import analytics
    from acql.model import predictions
    return analytics, predictions


def line_only_proxy(games: pd.DataFrame) -> pd.DataFrame:
    analytics, _ = _acql()
    g = games[games["spread_line"].notna()]
    p = [analytics.win_chance(s) if s >= 0 else 1 - analytics.win_chance(-s) for s in g["spread_line"]]
    return pd.DataFrame({"game_id": g["game_id"].values, "p_home": np.clip(p, 1e-4, 1 - 1e-4),
                         "exp_margin": g["spread_line"].values, "model": "deadeye_line_only_proxy",
                         "info_set": config.CLOSING_RETRO})


def _code(predictions, name: str) -> str:
    c = predictions.team_code(name).upper()
    return CODE_FIX.get(c, c)


def _week_of(path: Path) -> int | None:
    m = re.search(r"week\s*(\d+)", path.name, re.I)
    return int(m.group(1)) if m else None


def recomputed(games: pd.DataFrame, season: int = config.CURRENT_SEASON) -> pd.DataFrame:
    """Deadeye's margin and chance from the tracker files and recorded inputs in the repo."""
    analytics, predictions = _acql()
    sources = []
    for path in sorted(config.ROOT.glob("nflpredictions week *.csv")):
        week = _week_of(path)
        if week is not None:
            sources.append((week, predictions.read_csv(path), path.name))
    recorded = config.ROOT / "acql-forecasts.json"
    if recorded.exists():
        data = json.loads(recorded.read_text())
        have = {w for w, _, _ in sources}
        for wk, entry in data.items():
            if int(wk) in have:
                continue
            fs = []
            for g in entry.get("games", []):
                if g.get("market") is None:
                    continue
                fs.append(predictions.Forecast(road=g["road"], home=g["home"], market=float(g["market"]),
                                               opening=g.get("opening"), opinions=tuple(g.get("opinions") or ())))
            sources.append((int(wk), fs, "acql-forecasts.json"))
    rows = []
    for week, fs, src in sources:
        lean = predictions.home_lean(fs)
        typical = predictions.typical_disagreement(fs)
        for f in fs:
            m = f.expected(predictions.CONSENSUS_WEIGHT, lean, typical)
            if m is None:
                continue
            p = analytics.win_chance(m) if m >= 0 else 1 - analytics.win_chance(-m)
            rows.append({"season": season, "week": week, "home_team": _code(predictions, f.home),
                         "away_team": _code(predictions, f.road), "p_home": float(np.clip(p, 1e-4, 1 - 1e-4)),
                         "exp_margin": m, "market": f.market, "n_models": len(f.opinions), "source": src})
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    key = games[["game_id", "season", "week", "home_team", "away_team"]]
    out = df.merge(key, on=["season", "week", "home_team", "away_team"], how="left")
    out["model"] = "deadeye_recomputed"
    out["info_set"] = "deadeye_inputs_recomputed"
    return out


def recorded(db_path: Path | None = None) -> pd.DataFrame:
    """Deadeye's own logged forecasts (forecast log, lab_ tables) if a copy of acql.db is present."""
    db_path = db_path or config.ROOT / "data" / "acql.db"
    if not db_path.exists():
        return pd.DataFrame()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)        # read-only: never writes to Deadeye's DB
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        if "lab_predictions" not in tables:
            return pd.DataFrame()
        return pd.read_sql("select * from lab_predictions", con)
    finally:
        con.close()
