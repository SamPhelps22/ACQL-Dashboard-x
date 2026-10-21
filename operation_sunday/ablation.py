"""Signal-level learning: matched-game ablations per feature family.

For each family F (team_strength, rest, travel, situational, market) the
same walk-forward is run with logistic models that differ only by F:

    market alone            vs  market + F
    football without F      vs  football with F
    full model without F    vs  full model (F restored)

"market" in the backtest means the CLOSING line (no Thursday snapshots are
archived), so every market-based arm is labelled a retrospective benchmark;
its result says how much F adds beyond a sharp market, not what a Thursday
model would have had. QB, injuries, weather, tactical and drive-simulation
families are reported as not testable, with the reason (features.UNAVAILABLE_FAMILIES).

A family is never added to the approved model because it improves a
training score: only these out-of-sample, matched, week-resampled numbers count.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .acql_rules import pool_points
from .backtest import attach_outcomes, walk_forward
from .config import Settings
from .features import FAMILIES, UNAVAILABLE_FAMILIES
from .metrics import summary
from .models import Logistic
from .selection import compare

FOOTBALL_FAMILIES = ("team_strength", "rest", "travel", "situational")


def _close_market(feats: pd.DataFrame) -> pd.DataFrame:
    f = feats.copy()
    p = 0.5 * (1 + np.vectorize(__import__("math").erf)(f["close_spread"].fillna(0) / 13.45 / np.sqrt(2)))
    p = np.clip(p, 0.01, 0.99)
    f["mkt_logit"] = np.where(f["close_spread"].notna(), np.log(p / (1 - p)), np.nan)
    return f


def run(feats: pd.DataFrame, week_keys: list, settings: Settings, families=None) -> dict:
    fam_list = list(families or FAMILIES)
    feats_m = _close_market(feats)
    arms = {}
    for fam in fam_list:
        football_wo = tuple(f for f in FOOTBALL_FAMILIES if f != fam)
        football_w = tuple(dict.fromkeys(football_wo + ((fam,) if fam != "market" else ())))
        full = FOOTBALL_FAMILIES + ("market",)
        full_wo = tuple(f for f in full if f != fam)
        arms[fam] = {
            "market_alone": ("market",),
            "market_plus": tuple(dict.fromkeys(("market", fam))),
            "football_without": football_wo,
            "football_with": football_w if fam != "market" else football_wo + ("market",),
            "full_without": full_wo,
            "full_with": full,
        }
    needed = {}
    for fam, a in arms.items():
        for arm, fams in a.items():
            needed[fams] = f"abl:{'+'.join(fams)}"
    models = [Logistic(fams, name=name) for fams, name in needed.items()]
    preds = walk_forward(feats_m, models, week_keys, settings)
    scored = attach_outcomes(preds, feats_m)
    pts = pool_points(scored)
    results = []
    for fam, a in arms.items():
        for base_arm, with_arm in (("market_alone", "market_plus"), ("football_without", "football_with"),
                                   ("full_without", "full_with")):
            m0, m1 = needed[a[base_arm]], needed[a[with_arm]]
            if m0 == m1:
                continue
            c = compare(scored, m1, m0, settings.promotion, settings.seed)
            s0, s1 = summary(scored[scored["model"] == m0]), summary(scored[scored["model"] == m1])
            p0 = pts[pts["model"] == m0]["points"].sum()
            p1 = pts[pts["model"] == m1]["points"].sum()
            uses_close = "market" in a[base_arm] or "market" in a[with_arm]
            results.append({
                "family": fam, "comparison": f"{base_arm} -> {with_arm}",
                "games": c.get("games", 0), "weeks": c.get("weeks", 0),
                "d_logloss": c["logloss_diff"]["mean"] if c.get("games") else np.nan,
                "d_logloss_lo": c["logloss_diff"]["lo"] if c.get("games") else np.nan,
                "d_logloss_hi": c["logloss_diff"]["hi"] if c.get("games") else np.nan,
                "d_brier": c["brier_diff"]["mean"] if c.get("games") else np.nan,
                "d_ece": s1.get("ece", np.nan) - s0.get("ece", np.nan),
                "d_acql_points": float(p1 - p0),
                "availability": float(feats_m[FAMILIES[fam]].notna().all(axis=1).mean()),
                "benchmark_only": uses_close,
            })
    return {"table": pd.DataFrame(results), "unavailable": UNAVAILABLE_FAMILIES}
