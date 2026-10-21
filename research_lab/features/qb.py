"""Quarterback features, as of a snapshot.

A passer's rating is his opponent-adjusted EPA per dropback, recency-weighted
and shrunk toward the level of backups (estimated from the snapshot itself:
dropbacks by passers who were not their team's main passer). The surrounding
offence is kept apart: `team_pass` is the team's opponent-adjusted pass
offence rating, so `qb_vs_team` says whether this passer is better or worse
than what the team has been with whoever played.

Who starts depends on the information set:

    last       the main passer of the team's most recent completed game (week start)
    injury     `last`, unless the final injury report - timestamped before the
               forecast - lists him Out or Doubtful; then the team's other passer
               with the most recent dropbacks (pre-kickoff; only 2010-2024 have timestamps)
    confirmed  the actual starter (nflverse home_qb_id/away_qb_id), known ~90 min before kickoff
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from . import ratings

HALF_LIFE_GAMES = 16.0
LOOKBACK_SEASONS = 4
PRIOR_DROPBACKS = 250.0
STAT_PRIOR_DB = 400.0


def passer_table(snap, season: int, week: int, team_ratings: pd.DataFrame) -> pd.DataFrame:
    q = snap.qb_games
    q = q[q["season"] >= season - LOOKBACK_SEASONS]
    if not len(q):
        return pd.DataFrame()
    q = q.merge(snap.games[["game_id", "kickoff"]], on="game_id")
    adj = team_ratings.set_index("team")["def_pass_epa"] if len(team_ratings) else pd.Series(dtype=float)
    q = q.assign(opp_adj=q["opp"].map(adj).fillna(0.0))
    q["epa_db"] = q["qb_epa"] / q["dropbacks"]
    q["resid"] = q["epa_db"] - q["opp_adj"]
    # recency: games back for this passer (0 = latest)
    q = q.sort_values("kickoff")
    q["back"] = q.groupby("passer_id").cumcount(ascending=False)
    q["w"] = 0.5 ** (q["back"] / HALF_LIFE_GAMES) * q["dropbacks"]
    backups = q[~q["main"]]
    prior = float(np.average(backups["resid"], weights=backups["dropbacks"])) if len(backups) else -0.1
    league_sack = q["sacks"].sum() / q["dropbacks"].sum()
    league_int = q["ints"].sum() / q["dropbacks"].sum()
    league_cpoe = (q["cpoe_sum"].sum() / q["cpoe_n"].sum()) if q["cpoe_n"].sum() else 0.0
    hit_epa = q["epa_hit"].sum() / max(q["hits"].sum(), 1)

    def agg(g):
        w, db = g["w"], g["dropbacks"]
        sw = w.sum()
        wf = w / db.clip(lower=1)                      # per-dropback weight factor
        eff_db = (wf * db).sum()
        return pd.Series({
            "qb_rating": (np.sum(w * g["resid"]) + PRIOR_DROPBACKS * prior) / (sw + PRIOR_DROPBACKS),
            "qb_sack": ((wf * g["sacks"]).sum() + STAT_PRIOR_DB * league_sack) / (eff_db + STAT_PRIOR_DB),
            "qb_int": ((wf * g["ints"]).sum() + STAT_PRIOR_DB * league_int) / (eff_db + STAT_PRIOR_DB),
            "qb_cpoe": ((wf * g["cpoe_sum"]).sum() + 200 * league_cpoe) / ((wf * g["cpoe_n"]).sum() + 200),
            "qb_hit_epa": ((wf * g["epa_hit"]).sum() + 60 * hit_epa) / ((wf * g["hits"]).sum() + 60),
            "qb_rush": ((0.5 ** (g["back"] / HALF_LIFE_GAMES)) * g["qb_run_epa"]).sum()
                       / ((0.5 ** (g["back"] / HALF_LIFE_GAMES)).sum() + 4),
            "qb_career_db": db.sum(),
            "last_team": g["team"].iloc[-1],
            "last_kickoff": g["kickoff"].iloc[-1],
        })

    cols = ["w", "dropbacks", "resid", "sacks", "ints", "cpoe_sum", "cpoe_n", "epa_hit", "hits", "back",
            "qb_run_epa", "team", "kickoff"]
    t = q.groupby("passer_id")[cols].apply(agg)
    t.attrs["prior"] = prior
    return t


def starters(snap, week: pd.DataFrame, mode: str) -> dict:
    """(game_id, side) -> (passer_id or None, changed flag)."""
    q = snap.qb_games
    main = q[q["main"] == True].merge(snap.games[["game_id", "kickoff"]], on="game_id").sort_values("kickoff")  # noqa: E712
    last = main.groupby("team")["passer_id"].last().to_dict()
    recent = main.groupby("team")["passer_id"].apply(lambda s: list(s.iloc[-8:])).to_dict()
    out = {}
    inj_out = set()
    if mode == "injury" and snap.store is not None and len(week):
        s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
        for g in week.itertuples():
            rep = snap.store.injuries_before(s, w, g.ts_pre_kickoff)
            rep = rep[(rep["position"] == "QB") & rep["report_status"].isin(["Out", "Doubtful"])]
            inj_out |= set(rep["gsis_id"])
    for g in week.itertuples():
        for side, team in (("h", g.home_team), ("a", g.away_team)):
            prev = last.get(team)
            if mode == "confirmed":
                pid = getattr(g, f"{'home' if side == 'h' else 'away'}_qb_id", None)
                pid = pid if isinstance(pid, str) else prev
            elif mode == "injury" and prev in inj_out:
                others = [p for p in reversed(recent.get(team, [])) if p != prev and p not in inj_out]
                if not others:
                    sub = q[(q["team"] == team) & (q["passer_id"] != prev)]
                    others = list(sub.sort_values("game_id")["passer_id"].iloc[-1:])
                pid = others[0] if others else None
            else:
                pid = prev
            out[(g.game_id, side)] = (pid, pid != prev)
    return out


FEATS = ["qb_rating", "qb_sack", "qb_int", "qb_cpoe", "qb_hit_epa", "qb_rush", "qb_exp"]


def builder(mode: str):
    def build(snap, week):
        if not len(week):
            return pd.DataFrame()
        s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
        tr = ratings.unit_ratings(snap.team_games, snap.games, s, w)
        pt = passer_table(snap, s, w, tr)
        st = starters(snap, week, mode)
        trd = tr.set_index("team") if len(tr) else pd.DataFrame()
        prior = pt.attrs.get("prior", -0.1) if len(pt) else -0.1
        rows = []
        for g in week.itertuples():
            row = {"game_id": g.game_id}
            for side, team, opp in (("h", g.home_team, g.away_team), ("a", g.away_team, g.home_team)):
                pid, changed = st[(g.game_id, side)]
                known = pid is not None and len(pt) and pid in pt.index
                r = pt.loc[pid] if known else None
                row[f"{side}_qb_rating"] = r["qb_rating"] if known else prior
                for f in ("qb_sack", "qb_int", "qb_cpoe", "qb_hit_epa", "qb_rush"):
                    row[f"{side}_{f}"] = r[f] if known else np.nan
                row[f"{side}_qb_exp"] = np.log1p(r["qb_career_db"]) if known else 0.0
                row[f"{side}_qb_changed"] = float(changed)
                row[f"{side}_qb_unknown"] = float(not known)
                g_r = (lambda c: trd[c].get(team, 0.0)) if len(trd) else (lambda c: 0.0)
                o_r = (lambda c: trd[c].get(opp, 0.0)) if len(trd) else (lambda c: 0.0)
                row[f"{side}_team_pass"] = g_r("off_pass_epa")
                row[f"{side}_team_run"] = g_r("off_run_epa")
                row[f"{side}_qb_vs_team"] = row[f"{side}_qb_rating"] - row[f"{side}_team_pass"]
                row[f"{side}_opp_def_pass"] = o_r("def_pass_epa")
                row[f"{side}_opp_def_run"] = o_r("def_run_epa")
                row[f"{side}_opp_rush"] = o_r("def_hit_rate")
                row[f"{side}_def_pass"] = g_r("def_pass_epa")
            row["neutral"] = g.neutral
            rows.append(row)
        return pd.DataFrame(rows)
    build.__name__ = f"qb_{mode}"
    return build
