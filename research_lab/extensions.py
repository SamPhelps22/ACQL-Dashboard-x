"""Two evaluations outside the main matched set:

* Model H (scheme matchups) - its data starts in 2018, so it is scored on 2021-2023 (development) and
  2024-2025 (holdout) only, against its own base and against Model E on the same games.
* 2026 to date - lab models walk forward through the completed 2026 weeks and are compared with
  Deadeye's recomputed forecasts (its own code on its own input files). The lab forecasts are a
  retrospective reconstruction (made today, from data filtered to what was known before each week);
  only the shadow journal holds genuinely prospective forecasts.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config, pipeline
from .adapters import deadeye
from .backtest import engine
from .data.store import Store
from .metrics import scoring
from .models import bayes, scheme


def model_h(store: Store | None = None, log=print) -> dict:
    store = store or Store.load()
    rows = []
    out = {"note": "H_scheme = H_base + coverage-weighted pass EPA, pressure, personnel and formation tendencies "
                   "(nflverse participation, 2018+). Scored where two prior seasons of coverage data exist. "
                   "Negative diff = scheme features help."}
    for label, seasons in (("development 2021-2023", range(2021, 2024)), ("holdout 2024-2025", range(2024, 2026))):
        fc = engine.run([scheme.SchemeBase(), scheme.Scheme(), bayes.BayesTeams()], store, seasons, log=log)
        res = store.games[store.games["season"].isin(list(seasons)) & (store.games["game_type"] == "REG")]
        w = scoring.wide(fc, res[["game_id", "season", "week", "home_win"]]).dropna(subset=["H_base", "H_scheme", "E_bayes"])
        for a, b in (("H_scheme", "H_base"), ("H_scheme", "E_bayes"), ("H_base", "E_bayes")):
            r = scoring.paired(w, a, b)
            r.update(period=label, ll_a=float(scoring.log_loss(w[a], w["home_win"])[w["home_win"].isin([0, 1])].mean()),
                     ll_b=float(scoring.log_loss(w[b], w["home_win"])[w["home_win"].isin([0, 1])].mean()))
            rows.append({k: r[k] for k in ("period", "a", "b", "n", "ll_a", "ll_b", "diff", "lo", "hi")})
    out["rows"] = rows
    (config.OUTPUTS / "model_h.json").write_text(json.dumps(out, indent=1))
    return out


def current_season(store: Store | None = None, log=print) -> dict:
    store = store or Store.load()
    s = config.CURRENT_SEASON
    done = store.games[(store.games["season"] == s) & store.games["completed"] & (store.games["game_type"] == "REG")]
    weeks = sorted(done["week"].unique())
    models = [m for m in pipeline.models() if m.name in
              ("market_ml_close", "challenger_elo", "A_qb_weekstart", "A_qb_confirmed", "B_drive_sim",
               "C_situational", "E_bayes", "F_matchup_interaction")]
    frames = [engine.predict_week(m, store, s, w, completed_only=True) for m in models for w in weeks]
    fc = pd.concat(frames, ignore_index=True)
    dd = deadeye.recomputed(store.games)
    dd = dd[dd["game_id"].isin(done["game_id"])]
    dd = dd.assign(p_home_raw=dd["p_home"])[["game_id", "model", "p_home_raw"]]
    lo = deadeye.line_only_proxy(done).rename(columns={"p_home": "p_home_raw"})[["game_id", "model", "p_home_raw"]]
    allf = pd.concat([fc[["game_id", "model", "p_home_raw"]], dd, lo], ignore_index=True)
    res = done[["game_id", "season", "week", "home_win", "margin"]]
    w = scoring.wide(allf, res)
    m = w.dropna(subset=["deadeye_recomputed"])
    rows = []
    for name in sorted(allf["model"].unique()):
        d = m.dropna(subset=[name]).assign(p=lambda x, n=name: x[n])
        sm = scoring.summary(d)
        r = {"model": name, "n": sm["n"], "log_loss": sm["log_loss"], "brier": sm["brier"], "accuracy": sm["accuracy"]}
        if name != "deadeye_recomputed":
            pr = scoring.paired(m, name, "deadeye_recomputed")
            r.update(vs_deadeye=pr["diff"], lo=pr["lo"], hi=pr["hi"])
        rows.append(r)
    out = {"note": f"2026 weeks {', '.join(map(str, sorted(m['week'].unique())))} with Deadeye inputs in the repository "
                   f"({len(m)} games). Deadeye recomputed = its own code at the default share on the tracker files / "
                   "recorded inputs (weeks 1-2 had typed lines and no models, so Deadeye = the line there). "
                   "Market is the nflverse closing moneyline. Tiny sample: no conclusion is possible from it.",
           "rows": sorted(rows, key=lambda r: r["log_loss"])}
    (config.OUTPUTS / "deadeye_2026.json").write_text(json.dumps(out, indent=1, default=float))
    return out
