"""ACQL pool evaluation, kept apart from the probability models.

ACQL's actual rules (from the dashboard's code and its CALIBRATION_AUDIT):
every game on the week's NFL slate is picked; each credited pick is one
point; there are NO confidence points. A favourite of 6.5 or more carries a
pool line and is credited only if it wins by at least the line (a win by
exactly a whole-number line goes to the favourite). A tied straight-up game
credits nobody.

So the brief's "assign confidence values 1..N" does not describe ACQL. Both
are evaluated here, clearly separated:

  acql_*         ACQL's real rules. Each model's card takes, game by game, the
                 side it thinks more likely to be credited.
  confidence_*   a standard 1..N confidence pool (straight-up winners, the
                 surest pick gets N points) - NOT ACQL's rules, included
                 because the brief asked for it.

Pool lines: on the eight weeks whose pick sheets are in the repository
(acql-picks.json: 2023 weeks 8/10/11/13, 2026 weeks 1-4), the commissioner's
real lines and every coach's real picks are used. For the long replay the
line is reconstructed from the closing spread with the commissioner's
measured habit (acql.model.backtest.pool_line) - the same for every model.
Opponents' picks are never invented: the replay scores cards against the
rules only; the field comparison uses real sheets only.

Converting a win chance into a cover chance needs a margin distribution.
Challenger (and the closing-spread baseline) use a normal margin with SD
13.5 points around the margin implied by the chance - a standard NFL figure,
fixed before any evaluation. Deadeye's sources use Deadeye's own curves.
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

from ..config import ROOT
from . import deadeye

SIGMA = 13.5


def need(line: float) -> int:
    return math.ceil(line - 1e-9)


def credited_normal(home_mu: float, line: float | None, home_fav: bool | None) -> float:
    """Chance the home side is credited, for a normal margin centred on home_mu."""
    if line is None:
        return float(1 - norm.cdf((0.5 - home_mu) / SIGMA) + 0.5 * (norm.cdf((0.5 - home_mu) / SIGMA) - norm.cdf((-0.5 - home_mu) / SIGMA)))
    fav_mu = home_mu if home_fav else -home_mu
    p_fav = float(1 - norm.cdf((need(line) - 0.5 - fav_mu) / SIGMA))
    return p_fav if home_fav else 1 - p_fav


def implied_margin(p_home: float) -> float:
    return SIGMA * norm.ppf(min(max(p_home, 1e-4), 1 - 1e-4))


def credited_side(row) -> str | None:
    """Who the pool credits, from the real score and the line."""
    margin = row.home_score - row.away_score
    if row.line is None or (isinstance(row.line, float) and np.isnan(row.line)):
        return None if margin == 0 else ("home" if margin > 0 else "away")
    fav_margin = margin if row.line_home_fav else -margin
    fav = "home" if row.line_home_fav else "away"
    return fav if fav_margin >= need(row.line) else ("away" if fav == "home" else "home")


def card_probabilities(slate: pd.DataFrame, model: str) -> np.ndarray:
    """Each game's chance the home side is credited, as `model` sees it."""
    out = []
    for r in slate.itertuples(index=False):
        line = None if pd.isna(r.line) else float(r.line)
        fav = None if line is None else bool(r.line_home_fav)
        if model == "home_team":
            out.append(1.0)
        elif model == "deadeye_proxy":
            out.append(deadeye.credited_home_proxy(r.m_deadeye_proxy, line, fav))
        elif model in ("deadeye_core_closing", "deadeye_live"):
            sd = getattr(r, f"sd_{model}", None)
            sd = 8.7 if sd is None or pd.isna(sd) else sd
            out.append(deadeye.credited_home_curve(getattr(r, f"m_{model}"), sd, line, fav))
        elif model == "market_spread_line":
            out.append(credited_normal(float(r.spread_line), line, fav))
        elif line is None:
            out.append(float(getattr(r, f"p_{model}")))      # a straight game is just the win chance
        else:
            out.append(credited_normal(implied_margin(getattr(r, f"p_{model}")), line, fav))
    return np.array(out)


def replay_slates(games: pd.DataFrame, forecasts: pd.DataFrame, models: list[str], seasons) -> pd.DataFrame:
    """Every completed regular-season game with each model's inputs and the reconstructed pool line."""
    g = games[(games["game_type"] == "REG") & games["completed"] & games["season"].isin(list(seasons))].copy()
    g["line"] = [deadeye.pool_line(s) if pd.notna(s) else None for s in g["spread_line"]]
    g["line"] = g["line"].astype(float)
    g["line_home_fav"] = g["spread_line"] > 0
    for m in models:
        f = forecasts[forecasts["model"] == m].drop_duplicates("game_id").set_index("game_id")
        if m.startswith("deadeye"):
            g[f"m_{m}"] = g["game_id"].map(f["deadeye_margin"])
            if "deadeye_sd" in f.columns:
                g[f"sd_{m}"] = g["game_id"].map(f["deadeye_sd"])
        if m not in ("home_team", "market_spread_line"):
            g[f"p_{m}"] = g["game_id"].map(f["p_home"])
    return g


def score_weeks(slates: pd.DataFrame, models: list[str]) -> tuple[pd.DataFrame, dict]:
    """ACQL points per model per week, on weeks where every model priced every game."""
    rows, dropped = [], []
    for (season, week), s in slates.groupby(["season", "week"]):
        needed = [f"p_{m}" for m in models if f"p_{m}" in s.columns]
        needed += [f"m_{m}" for m in models if f"m_{m}" in s.columns]
        if s[needed].isna().any().any():
            dropped.append(f"{season}-{week}")
            continue
        truth = [credited_side(r) for r in s.itertuples(index=False)]
        row = {"season": season, "week": week, "games": len(s), "lined": int(s["line"].notna().sum())}
        for m in models:
            p = card_probabilities(s, m)
            picks = np.where(p >= 0.5, "home", "away")
            row[f"acql_{m}"] = int(sum(1 for side, t in zip(picks, truth) if side == t))
            row[f"exp_{m}"] = float(np.where(p >= 0.5, p, 1 - p).sum())
            if m != "home_team":
                row.update(_confidence(s, m))
        rows.append(row)
    return pd.DataFrame(rows), {"weeks_scored": len(rows), "weeks_dropped_for_missing_forecasts": dropped}


def _straight_p(s: pd.DataFrame, m: str) -> np.ndarray:
    if f"p_{m}" in s.columns:
        return s[f"p_{m}"].to_numpy(dtype=float)
    return np.array([credited_normal(float(x), None, None) for x in s["spread_line"]])


def _confidence(s: pd.DataFrame, m: str) -> dict:
    """Standard 1..N confidence points (straight-up winners) - not ACQL's rules."""
    p = _straight_p(s, m)
    conf = np.maximum(p, 1 - p)
    order = np.lexsort((s["game_id"].to_numpy(), conf))      # least sure first; ties broken by game id
    points = np.empty(len(p))
    points[order] = np.arange(1, len(p) + 1)
    margin = (s["home_score"] - s["away_score"]).to_numpy()
    right = np.where(margin == 0, 0.0, ((p >= 0.5) == (margin > 0)).astype(float))
    return {f"confidence_{m}": float((points * right).sum())}


def rank_correlation(slates: pd.DataFrame, a: str, b: str) -> float:
    """Average within-week Spearman correlation of two models' home chances."""
    vals = []
    for _, s in slates.groupby(["season", "week"]):
        pa, pb = _straight_p(s, a), _straight_p(s, b)
        if len(s) >= 5 and np.isfinite(pa).all() and np.isfinite(pb).all() and pa.std() > 0 and pb.std() > 0:
            r = spearmanr(pa, pb).statistic
            if np.isfinite(r):
                vals.append(r)
    return float(np.mean(vals)) if vals else float("nan")


# ---- the real pick sheets ----------------------------------------------------------------
NOTE = re.compile(r"\(\s*([a-z .]+?)\s+by\s+([0-9.]+)\s*\)", re.IGNORECASE)


def real_weeks(games: pd.DataFrame) -> list[dict]:
    """The pick sheets on file, matched to nflverse games (season found from the slate itself)."""
    raw = json.loads((ROOT / "acql-picks.json").read_text())
    reg = games[games["game_type"] == "REG"]
    out = []
    for week_key, sheet in raw.items():
        week = int(week_key)
        pairs = [(deadeye.team_code(gm["away"]), deadeye.team_code(gm["home"])) for gm in sheet["games"]]
        best, best_hits = None, 0
        for season in sorted(reg["season"].unique()):
            wk = reg[(reg["season"] == season) & (reg["week"] == week)]
            have = set(zip(wk["away"], wk["home"]))
            hits = sum(1 for p in pairs if p in have)
            if hits > best_hits:
                best, best_hits = season, hits
        if best is None:
            continue
        wk = reg[(reg["season"] == best) & (reg["week"] == week)].set_index(["away", "home"])
        rows = []
        for gm, (away, home) in zip(sheet["games"], pairs):
            if (away, home) not in wk.index:
                continue
            game = wk.loc[(away, home)]
            line, home_fav = None, None
            found = NOTE.search(gm.get("note") or "")
            if found:
                fav = deadeye.team_code(found.group(1))
                line = float(found.group(2))
                home_fav = fav == home
                if fav not in (home, away):
                    line, home_fav = None, None
            rows.append({"game_id": game["game_id"], "season": int(best), "week": week, "home": home, "away": away,
                         "home_score": game["home_score"], "away_score": game["away_score"],
                         "spread_line": game["spread_line"], "line": line, "line_home_fav": home_fav,
                         "picks": {coach: deadeye.team_code(t) for coach, t in gm["picks"].items()}})
        out.append({"season": int(best), "week": week, "sheet_games": len(sheet["games"]), "matched": len(rows),
                    "games": rows})
    return sorted(out, key=lambda w: (w["season"], w["week"]))


def field_comparison(weeks: list[dict], forecasts: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Each model's card on the real sheets, against every coach's real score."""
    rows = []
    for w in weeks:
        s = pd.DataFrame(w["games"])
        if s.empty or s["home_score"].isna().any():
            continue
        s["line"] = s["line"].astype(float)
        truth = [credited_side(r) for r in s.itertuples(index=False)]
        credited_team = [r.home if t == "home" else r.away if t == "away" else None
                         for r, t in zip(s.itertuples(index=False), truth)]
        coaches: dict[str, int] = {}
        for r, team in zip(s.itertuples(index=False), credited_team):
            for coach, pick in r.picks.items():
                coaches[coach] = coaches.get(coach, 0) + int(team is not None and pick == team)
        scores = np.array(list(coaches.values()))
        row = {"season": w["season"], "week": w["week"], "games": len(s), "lined": int(s["line"].notna().sum()),
               "coaches": len(scores), "pool_average": float(scores.mean()), "best_coach": int(scores.max())}
        for m in models:
            f = forecasts[forecasts["model"] == m].drop_duplicates("game_id").set_index("game_id")
            if m != "home_team" and not s["game_id"].isin(f.index).all():
                row[f"{m}"] = None
                continue
            t = s.copy()
            if m.startswith("deadeye"):
                t[f"m_{m}"] = t["game_id"].map(f["deadeye_margin"])
                if "deadeye_sd" in f.columns:
                    t[f"sd_{m}"] = t["game_id"].map(f["deadeye_sd"])
            if m != "home_team":
                t[f"p_{m}"] = t["game_id"].map(f["p_home"])
            p = card_probabilities(t, m)
            pts = int(sum(1 for side, tr in zip(np.where(p >= 0.5, "home", "away"), truth) if side == tr))
            row[m] = pts
            row[f"{m}_place"] = int(1 + (scores > pts).sum())
        rows.append(row)
    return pd.DataFrame(rows)
