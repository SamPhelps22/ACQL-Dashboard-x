"""Three scorecards per challenger, kept apart, and the gates a promotion must pass.

The verdict (verdict.py) asks one question in one measure: is a challenger's
log loss clearly better than the rule in use? That is necessary, not enough.
A model can price chances better and still pick fewer winners under the
pool's rules, or beat Deadeye and still trail the plain betting line. So
each challenger here gets three cards that are never added together:

    probability   log loss, Brier and calibration error against the rule in use,
                  with the range its lead could lie in (whole weeks redrawn)
    baselines     the same lead against the betting line alone (the market)
    pool          ACQL picks credited under the pool's own line rules
                  (probability.credited_home), week by week against the rule
                  in use: average picks a week, weeks ahead/behind/level, and
                  the range the weekly difference could lie in

and then the gates. A challenger is only ever *recommended* for review;
the production champion stays the rule in use (Deadeye) until the owner says
otherwise. Nothing here changes a pick, and nothing in the dashboard imports
this module - the Model Lab reads the file it writes (scorecards.json).

Statuses:
    champion          the rule in use - the only one that powers picks
    eligible          passed every gate: worth the owner's review, still not a switch
    challenger        under evaluation, not clearly worse on any card
    research-only     too little evidence to judge, or a gate it cannot yet be held to
    retired           clearly worse than the rule in use on probability

No Qt here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..model import modellab
from . import evaluate, recipes

FILE = "scorecards.json"
#: Weeks a challenger must have been priced on before the pool card counts.
MIN_WEEKS = 30
#: Its chances may be at most this much less honest (calibration error) than the rule in use.
CALIBRATION_SLACK = 0.010
CHAMPION, ELIGIBLE, CHALLENGER, RESEARCH, RETIRED = "champion", "eligible", "challenger", "research-only", "retired"


def _n(value) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def _duel(found: evaluate.Duel) -> dict:
    return {"games": found.games, "edge": _n(found.edge), "low": _n(found.low), "high": _n(found.high),
            "reading": found.reading}


def pool_card(first: np.ndarray, second: np.ndarray, came: np.ndarray, weeks: np.ndarray) -> dict:
    """Picks credited under the pool's rules, week by week: `first` against `second`."""
    if not len(first):
        return {"weeks": 0}
    a = evaluate.hits(evaluate.held(first), came).astype(float)
    b = evaluate.hits(evaluate.held(second), came).astype(float)
    keys, where = np.unique(weeks, return_inverse=True)
    mine, theirs = np.bincount(where, weights=a), np.bincount(where, weights=b)
    diff = mine - theirs
    low = high = float("nan")
    if len(keys) >= 2:
        draws = np.random.default_rng(evaluate.SEED).integers(0, len(keys), size=(evaluate.DRAWS, len(keys)))
        low, high = (float(x) for x in np.percentile(diff[draws].mean(axis=1), [2.5, 97.5]))
    return {"weeks": int(len(keys)), "games": int(len(first)),
            "per_week": float(mine.mean()), "in_use_per_week": float(theirs.mean()),
            "diff_per_week": float(diff.mean()), "low": _n(low), "high": _n(high),
            "ahead": int((diff > 0).sum()), "behind": int((diff < 0).sum()), "level": int((diff == 0).sum()),
            "worst_week": float(diff.min()), "best_week": float(diff.max())}


def gates(card: dict, *, sealed: bool | None, problems: int) -> dict[str, bool]:
    """Every check a challenger must pass before it is worth the owner's review."""
    prob, held, pool = card["probability"], card.get("held_back"), card["pool"]
    return {
        "no leak found": sealed is True,
        "data clean": problems == 0,
        f"{modellab.ENOUGH_GAMES}+ games": prob["games"] >= modellab.ENOUGH_GAMES,
        f"{MIN_WEEKS}+ weeks": pool.get("weeks", 0) >= MIN_WEEKS,
        "probability lead clear of zero": prob["low"] is not None and prob["low"] > 0,
        "not behind on held-back seasons": held is None or (held.get("edge") or 0.0) >= 0,
        "calibration no worse": card["calibration"] <= card["in_use_calibration"] + CALIBRATION_SLACK,
        "not clearly worse at the pool": pool.get("high") is None or pool["high"] >= 0,
    }


def status(card: dict) -> str:
    prob = card["probability"]
    if prob["high"] is not None and prob["high"] < 0:
        return RETIRED
    if all(card["gates"].values()):
        return ELIGIBLE
    if prob["games"] < modellab.ENOUGH_GAMES or card["pool"].get("weeks", 0) < MIN_WEEKS:
        return RESEARCH
    return CHALLENGER


def build(study, in_use: str) -> dict:
    """Every challenger's three cards from a run's headline walk-forward."""
    head = study.headline
    out = {"in_use": in_use, "champion": in_use, "market": recipes.LINE, "challengers": {},
           "note": "Recommendation only: the champion is changed by the owner, never by this file."}
    if head is None or in_use not in head.together:
        out["missing"] = "no walk-forward with the computer models - nothing could be scored"
        return out
    sealed = all(ok for _, _, ok, _ in study.seals) if study.seals else None
    problems = len(study.notes.of("error"))
    keep, games = head.keep, head.result.games
    came = games["credited"].to_numpy(dtype=float)
    weeks = games["order"].to_numpy()
    held = head.result.held_back()
    marks = head.marks()
    out.update(games=int(keep.sum()), weeks=int(len(set(weeks[keep].tolist()))), sealed=sealed, problems=problems,
               setting=head.result.setting.title, held_back=[int(s) for s in held])
    for name in head.together:
        if name == in_use:
            continue
        card = {"probability": _duel(head.against(name, in_use)),
                "market": _duel(head.against(name, recipes.LINE)) if name != recipes.LINE else None,
                "held_back": _duel(head.against(name, in_use, head.within(held))) if held else None,
                "pool": pool_card(head.chances[name][keep], head.chances[in_use][keep], came[keep], weeks[keep]),
                "logloss": marks[name].logloss, "brier": marks[name].brier, "calibration": marks[name].off,
                "in_use_calibration": marks[in_use].off}
        card["gates"] = gates(card, sealed=sealed, problems=problems)
        card["status"] = status(card)
        out["challengers"][name] = card
    eligible = [n for n, c in out["challengers"].items() if c["status"] == ELIGIBLE]
    out["recommendation"] = (
        max(eligible, key=lambda n: out["challengers"][n]["probability"]["edge"] or 0.0) if eligible else None)
    return out


def write(study, folder: Path, in_use: str) -> Path:
    path = Path(folder) / FILE
    path.write_text(json.dumps(build(study, in_use), indent=1, default=float), encoding="utf-8")
    return path
