"""Checks on Model B's simulated distributions against what happened.

    pit         where each real margin / total falls in its own simulated distribution;
                uniform deciles = honest spreads (too many in the end deciles = too narrow)
    key numbers how often games end on margins of 3, 7, 10, 14 and in ties, simulated vs real
    totals      mean and spread of simulated vs real totals
    convergence the same games at N = 250 ... 16000 draws: the win chance settles, and its Monte
                Carlo error is far below forecast error at the N used
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config
from ..backtest import engine
from ..data.store import Store
from . import drives


def run(seasons=range(2021, 2024), store: Store | None = None) -> dict:
    store = store or Store.load()
    model = drives.DriveSim(keep=True)
    frames = [engine.predict_week(model, store, s, w) for s, w in engine.weeks(store, seasons)]
    fc = pd.concat(frames, ignore_index=True)
    res = store.games.set_index("game_id")
    pit_m, pit_t, sim_key, real_key, sim_tot, real_tot = [], [], [], [], [], []
    for gid, (h, a) in model.dist.items():
        r = res.loc[gid]
        if not r["completed"]:
            continue
        m, t = (h - a).astype(float), (h + a).astype(float)
        u = np.random.default_rng(1).random()
        pit_m.append(np.mean(m < r["margin"]) + u * np.mean(m == r["margin"]))
        pit_t.append(np.mean(t < r["total_points"]) + u * np.mean(t == r["total_points"]))
        sim_key.append([np.mean(np.abs(m) == k) for k in (0, 3, 7, 10, 14)])
        real_key.append([float(abs(r["margin"]) == k) for k in (0, 3, 7, 10, 14)])
        sim_tot.append((t.mean(), t.std()))
        real_tot.append(r["total_points"])
    dec = lambda x: np.histogram(x, bins=np.linspace(0, 1, 11))[0].tolist()   # noqa: E731
    out = {"seasons": [min(seasons), max(seasons)], "games": len(pit_m),
           "pit_margin_deciles": dec(pit_m), "pit_total_deciles": dec(pit_t),
           "key_numbers": {"margins": [0, 3, 7, 10, 14], "simulated": np.mean(sim_key, axis=0).round(4).tolist(),
                           "real": np.mean(real_key, axis=0).round(4).tolist()},
           "totals": {"sim_mean": float(np.mean([s[0] for s in sim_tot])), "real_mean": float(np.mean(real_tot)),
                      "sim_sd_within_game": float(np.mean([s[1] for s in sim_tot])),
                      "real_sd_around_sim_mean": float(np.std(np.array(real_tot) - np.array([s[0] for s in sim_tot])))}}
    # convergence on a few games of the last week
    s, w = engine.weeks(store, seasons)[-1]
    conv = []
    for n in (250, 1000, 4000, 16000):
        m = drives.DriveSim(n_sims=n)
        f = engine.predict_week(m, store, s, w)
        conv.append({"n": n, "p_home": f["p_home_raw"].round(4).tolist()[:6]})
    out["convergence"] = conv
    out["mc_se_at_4000"] = float(np.sqrt(0.25 / 4000))
    (config.OUTPUTS / "sim_validation.json").write_text(json.dumps(out, indent=1))
    return out
