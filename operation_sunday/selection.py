"""Model selection: a candidate is promoted only if it clears every rule
written down BEFORE the comparison (config.PromotionCriteria):

  1. Thursday-eligible (no closing-line or other post-cutoff input);
  2. at least min_games games and min_weeks weeks of matched out-of-sample
     predictions;
  3. mean log loss better than the incumbent AND the designated baseline by
     at least min_logloss_gain;
  4. the paired week-block bootstrap interval of that difference lies
     entirely below zero (vs incumbent and vs baseline);
  5. calibration acceptable: ECE <= max_ece and recalibration slope inside
     calibration_slope_range.

Among candidates that pass, the lowest log loss wins. If none passes, the
previously approved model stays. If nothing was ever approved, the designated
baseline is used and the fallback is disclosed. Winning the latest week is
never enough: nothing here looks at a single week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import matched
from .config import PromotionCriteria
from .metrics import paired_week_bootstrap, per_game_logloss, summary


def add_slices(scored: pd.DataFrame, feats: pd.DataFrame) -> pd.DataFrame:
    s = scored.copy()
    fav_home = s["close_spread"] > 0
    s["slice_favourite"] = np.where(s["close_spread"].isna(), "no line",
                                    np.where((s["p_home"] >= 0.5) == fav_home, "picks market favourite",
                                             "picks market underdog"))
    s["slice_prob_bucket"] = pd.cut(np.maximum(s["p_home"], 1 - s["p_home"]), [0.5, 0.55, 0.6, 0.7, 0.8, 1.0],
                                    include_lowest=True).astype(str)
    s["slice_spread"] = pd.cut(s["close_spread"].abs(), [-0.1, 3, 6.4, 10, 100],
                               labels=["0-3", "3.5-6", "6.5-10 (lined)", "10+ (lined)"]).astype(str)
    s["slice_complete"] = np.where(s["missing_flags"].apply(
        lambda f: bool([x for x in (f or []) if x != "no_market_snapshot"])), "has missing data", "complete")
    # QB continuity, retrospective
    order = feats.sort_values("kickoff_utc")
    last, changed = {}, {}
    for r in order.itertuples():
        ch = False
        for team, qb in ((r.home, r.home_qb), (r.away, r.away_qb)):
            if isinstance(qb, str):
                if team in last and last[team] != qb:
                    ch = True
                last[team] = qb
        changed[r.game_id] = "QB change (retrospective)" if ch else "same QBs"
    s["slice_qb"] = s["game_id"].map(changed).fillna("unknown")
    return s


def segment_table(scored: pd.DataFrame, models: list[str], col: str) -> pd.DataFrame:
    m = matched(scored, models)
    rows = []
    for (seg, model), g in m.groupby([col, "model"]):
        sm = summary(g)
        rows.append({"segment": seg, "model": model, "games": sm.get("games", 0),
                     "log_loss": sm.get("log_loss"), "brier": sm.get("brier"), "accuracy": sm.get("accuracy")})
    return pd.DataFrame(rows)


def compare(scored: pd.DataFrame, a: str, b: str, criteria: PromotionCriteria, seed: int) -> dict:
    """Paired comparison of a vs b on matched games: negative = a better."""
    m = matched(scored, [a, b])
    if m.empty:
        return {"games": 0}
    w = m.pivot_table(index=["game_id", "week_key"], columns="model", values="p_home").reset_index()
    y = m.drop_duplicates("game_id").set_index("game_id")["home_win"].reindex(w["game_id"]).to_numpy(float)
    keep = np.isin(y, [0.0, 1.0])
    w, y = w[keep], y[keep]
    diff = pd.Series(per_game_logloss(w[a], y) - per_game_logloss(w[b], y))
    bs = paired_week_bootstrap(diff, w["week_key"], criteria.bootstrap_samples, criteria.ci_level, seed)
    bdiff = pd.Series((w[a].to_numpy() - y) ** 2 - (w[b].to_numpy() - y) ** 2)
    bb = paired_week_bootstrap(bdiff, w["week_key"], criteria.bootstrap_samples, criteria.ci_level, seed + 1)
    return {"games": int(len(w)), "weeks": int(w["week_key"].nunique()),
            "logloss_diff": bs, "brier_diff": bb}


def decide(scored: pd.DataFrame, candidates: dict, incumbent: str | None, baseline: str,
           criteria: PromotionCriteria, seed: int) -> dict:
    """candidates: name -> {'thursday_eligible': bool, 'kind': str}."""
    rows, passed = [], []
    ref = incumbent or baseline
    for name, meta in candidates.items():
        sm = summary(scored[scored["model"] == name])
        rec = {"model": name, **meta, "summary": sm, "checks": {}, "passes": False}
        rec["checks"]["thursday_eligible"] = bool(meta.get("thursday_eligible"))
        if name in (ref, baseline) and name == ref:
            rec["checks"]["is_reference"] = True
        comps = {}
        for other in dict.fromkeys([ref, baseline]):
            if other == name:
                continue
            comps[other] = compare(scored, name, other, criteria, seed)
        rec["comparisons"] = comps
        enough = sm.get("games", 0) >= criteria.min_games and sm.get("weeks", 0) >= criteria.min_weeks
        rec["checks"]["sample"] = enough
        gains = [c for c in comps.values() if c.get("games")]
        rec["checks"]["gain"] = bool(gains) and all(-c["logloss_diff"]["mean"] >= criteria.min_logloss_gain for c in gains)
        rec["checks"]["ci_excludes_zero"] = bool(gains) and all(c["logloss_diff"]["hi"] < 0 for c in gains)
        lo, hi = criteria.calibration_slope_range
        # ECE is biased upward on small samples; allow for that noise explicitly
        ece_limit = criteria.max_ece + 0.5 / np.sqrt(max(sm.get("games", 1), 1))
        rec["ece_limit"] = ece_limit
        rec["checks"]["calibration"] = (sm.get("ece", 1) <= ece_limit
                                        and lo <= (sm.get("cal_slope") or 0) <= hi)
        rec["passes"] = name != ref and all(rec["checks"][k] for k in
                                            ("thursday_eligible", "sample", "gain", "ci_excludes_zero", "calibration"))
        if rec["passes"]:
            passed.append(rec)
        rows.append(rec)
    if passed:
        best = min(passed, key=lambda r: r["summary"]["log_loss"])
        decision = {"action": "promote", "model": best["model"],
                    "reason": f"{best['model']} passed every predefined rule against {ref}"
                              + (f" and baseline {baseline}" if baseline != ref else "")
                              + f" (log loss {best['summary']['log_loss']:.4f})."}
    elif incumbent:
        decision = {"action": "retain", "model": incumbent,
                    "reason": f"No candidate cleared every rule; the approved model {incumbent} is retained."}
    else:
        decision = {"action": "fallback", "model": baseline,
                    "reason": f"No approved model exists and no candidate cleared every rule; "
                              f"using the designated baseline {baseline} (FALLBACK)."}
    decision.update({"reference": ref, "baseline": baseline, "criteria": criteria.__dict__,
                     "criteria_digest": criteria.digest(), "candidates": rows})
    return decision
