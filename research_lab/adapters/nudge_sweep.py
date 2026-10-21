"""Deadeye's nudge toward the computer models, swept from 0% to 100% in 5% steps.

Evaluation only. Reads the Prediction Tracker season files (data/tracker/archive/nfl{yy}.csv,
Deadeye's own training source, read with acql.training.data.read_archive) and prices every game
with Deadeye's own code - predictions.Forecast.expected (models trimmed, slate home lean removed,
the share scaled by how far apart the models are) and analytics.win_chance - at each fixed share.
Results come from nflverse. A fixed share needs no fitting, so there is nothing to leak; the
"chosen" row picks each season's share from the seasons before it only.

    python -m research_lab.adapters.nudge_sweep            # last 10 seasons with files
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .. import acql_eval, config
from ..data import games as games_mod
from ..metrics import scoring

SHARES = [round(s, 2) for s in np.arange(0, 1.0001, 0.05)]
CODE_FIX = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def _acql():
    if str(config.ROOT) not in sys.path:
        sys.path.insert(0, str(config.ROOT))
    from acql import analytics
    from acql.model import predictions
    from acql.training import data as tdata
    return analytics, predictions, tdata


def priced(seasons=None) -> pd.DataFrame:
    analytics, predictions, tdata = _acql()
    files = tdata.archive_files()
    if seasons is None:
        seasons = sorted(s for s in files if s < config.CURRENT_SEASON)[-10:]
    g = games_mod.load()
    g = g[(g["game_type"] == "REG") & g["completed"]]
    key = {(r.season, r.home_team, r.away_team): r for r in g.itertuples()}
    rows = []
    for s in seasons:
        if s not in files:
            continue
        recs = tdata.read_archive(files[s], s, tdata.Notes())
        slates: dict[int, list] = {}
        for r in recs:
            market = r.get("line_updated") if r.get("line_updated") is not None else r.get("line_opening")
            if market is None:
                continue
            ops = tuple(v for k, v in r.items() if k.startswith(tdata.MODEL) and v is not None)
            f = predictions.Forecast(road=r["away"], home=r["home"], market=float(market),
                                     opening=r.get("line_opening"), opinions=ops)
            slates.setdefault(r["week"], []).append((r, f))
        for wk, items in slates.items():
            fs = [f for _, f in items]
            lean, typ = predictions.home_lean(fs), predictions.typical_disagreement(fs)
            for r, f in items:
                h, a = CODE_FIX.get(r["home"].upper(), r["home"].upper()), CODE_FIX.get(r["away"].upper(), r["away"].upper())
                gm = key.get((s, h, a))
                flip = False
                if gm is None:
                    gm, flip = key.get((s, a, h)), True
                if gm is None or gm.home_win == 0.5:
                    continue
                row = {"game_id": gm.game_id, "season": s, "week": int(gm.week), "n_models": len(f.opinions)}
                for sh in SHARES:
                    m = f.expected(sh, lean, typ)
                    m = -m if flip else m
                    p = analytics.win_chance(m) if m >= 0 else 1 - analytics.win_chance(-m)
                    row[f"p{sh:.2f}"], row[f"m{sh:.2f}"] = float(np.clip(p, 1e-4, 1 - 1e-4)), m
                rows.append(row)
    return pd.DataFrame(rows)


def sweep(df: pd.DataFrame) -> dict:
    g = games_mod.load().set_index("game_id")
    df = df.join(g[["home_win", "margin", "spread_line"]], on="game_id")
    out = {"games": len(df), "seasons": sorted(df["season"].unique().tolist()), "shares": []}
    for sh in SHARES:
        p = df[f"p{sh:.2f}"]
        pts = [int(acql_eval.pick(sp, pp, mm, config.MARGIN_SD) == acql_eval.credited(sp, mg))
               for sp, pp, mm, mg in zip(df["spread_line"], p, df[f"m{sh:.2f}"], df["margin"])]
        d = df.assign(a=p, b=df["p0.00"], c=df["p0.25"])
        vs0 = scoring.paired(d, "a", "b")
        vs25 = scoring.paired(d, "a", "c")
        out["shares"].append({"share": sh, "log_loss": float(scoring.log_loss(p, df["home_win"]).mean()),
                              "brier": float(scoring.brier(p, df["home_win"]).mean()),
                              "acql_per_week": float(np.sum(pts) / df.groupby(["season", "week"]).ngroups),
                              "vs_line_only": vs0["diff"], "vs0_lo": vs0["lo"], "vs0_hi": vs0["hi"],
                              "vs_25": vs25["diff"], "vs25_lo": vs25["lo"], "vs25_hi": vs25["hi"]})
    # walk-forward choice: each season uses the share that did best on the seasons before it
    chosen, losses = [], []
    for s in out["seasons"][1:]:
        past = df[df["season"] < s]
        best = min(SHARES, key=lambda sh: scoring.log_loss(past[f"p{sh:.2f}"], past["home_win"]).mean())
        cur = df[df["season"] == s]
        chosen.append({"season": int(s), "share": best})
        losses.append(scoring.log_loss(cur[f"p{best:.2f}"], cur["home_win"]))
    if losses:
        out["chosen_walk_forward"] = {"by_season": chosen, "log_loss": float(np.concatenate(losses).mean())}
    out["by_season"] = [{"season": int(s), **{f"{sh:.2f}": float(scoring.log_loss(grp[f"p{sh:.2f}"], grp["home_win"]).mean())
                                               for sh in SHARES}} for s, grp in df.groupby("season")]
    return out


def main():
    df = priced()
    if not len(df):
        print("No Prediction Tracker season files in data/tracker/archive (nfl16.csv ... nfl25.csv). "
              "Download them in a browser from https://www.thepredictiontracker.com/nflYY.csv and put them there.")
        return 2
    res = sweep(df)
    (config.OUTPUTS / "nudge_sweep.json").write_text(json.dumps(res, indent=1))
    for r in res["shares"]:
        print(f"{r['share']:.2f}  ll {r['log_loss']:.4f}  vs line {r['vs_line_only']:+.4f} "
              f"[{r['vs0_lo']:+.4f},{r['vs0_hi']:+.4f}]  acql {r['acql_per_week']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
