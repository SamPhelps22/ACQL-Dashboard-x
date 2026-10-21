"""Tests written down before the games they are judged on.

The calibration audit (2026-10-18) left two leads: favourites giving under
three points looked overrated by two or three points, and home sides by
about one. Both were found by looking at the same history many ways, and a
lead found that way is half-likely to be noise. The only fair test is on
games nobody had seen when the test was written. So the plans are fixed here,
with the date they were written, and each week only games whose card was
frozen at the deadline after that date are scored.

Each plan says, before any game is scored:

    the rule        what changes from Deadeye's own number
    the games       which games it applies to, from which week on
    the measure     log loss of the chance the pool's favourite is credited,
                    the plan's against Deadeye's own on the same games
    the decision    the Model Lab's rule: at least 150 games, and better by
                    0.010 log loss a game with the range clear of zero

Shadow only: nothing here touches a pick. Promotion is Sam's decision.

    python -m acql.training prereg       score the plans on what is frozen so far

Deadeye's side of each comparison is the chance it actually recorded at the
deadline (model/known.py, frozen records only). The plan's side moves that
same game's expected margin and prices it again on the same curve, at the
width that reproduces Deadeye's recorded chance, so only the plan's change
is being measured.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time

PLANS = (
    {"id": "small-favourites-1", "registered": "2026-10-20", "first_week": 7, "season": 2026,
     "rule": "Where the betting line's favourite is giving less than 3 points, move Deadeye's "
             "expected margin 1.5 points toward the underdog.",
     "applies": "small favourites", "shift_favourite": -1.5, "shift_home": 0.0},
    {"id": "home-lean-1", "registered": "2026-10-20", "first_week": 7, "season": 2026,
     "rule": "In every game, move Deadeye's expected margin 1 point toward the road side.",
     "applies": "every game", "shift_favourite": 0.0, "shift_home": -1.0},
)
GAMES_NEEDED = 150
BETTER_BY = 0.010


def fingerprint(plan: dict) -> str:
    """A plan's fingerprint: if any word of it changes, so does this."""
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:12]


def _number(text: object) -> float | None:
    found = re.search(r"(\d+(?:\.\d+)?)\s*$", str(text or ""))
    return float(found.group(1)) if found else None


def _sd_for(margin: float, need: int, chance: float) -> float:
    """The width at which the curve gives Deadeye's recorded chance for this margin."""
    from .. import analytics
    want = chance
    low, high = analytics.SPREAD_SD, 30.0         # narrower than the standard width changes nothing
    for _ in range(40):
        mid = (low + high) / 2
        got = analytics.cover_chance(margin, need, mid)
        # a wider spread pulls the chance toward a coin flip
        if (got > want) == (margin >= need - 0.5):
            low = mid
        else:
            high = mid
    return (low + high) / 2


def games(year: int, first_week: int, last_week: int = 22) -> list[dict]:
    """Every frozen, finished game from `first_week` on: what Deadeye had and how it ended."""
    from .. import analytics
    from ..feeds import results
    from ..model import known
    from ..model.predictions import team_code
    out = []
    for week in range(first_week, last_week + 1):
        kept = known.kept(year, week)
        if not kept or not kept.get("frozen"):
            continue
        scores = results.load(year, week)
        for entry in (kept.get("games") or {}).values():
            fav = str(entry.get("favourite") or "")
            margin, chance, pick = entry.get("margin"), entry.get("chance"), str(entry.get("pick") or "")
            home = str((entry.get("home") or {}).get("team") or "")
            away = str((entry.get("away") or {}).get("team") or "")
            if not fav or margin is None or chance is None or not home or not away:
                continue
            score, flipped = results.find(scores, away, home)
            if score is None or not score.final or score.home_points is None:
                continue
            home_pts, away_pts = score.home_points, score.away_points
            if flipped:
                home_pts, away_pts = away_pts, home_pts
            fav_home = team_code(fav) == team_code(home)
            fav_margin_final = (home_pts - away_pts) if fav_home else (away_pts - home_pts)
            line = _number(entry.get("pool_line"))
            need = analytics.line_need(line) if line is not None else 1
            p_fav = chance if team_code(pick) == team_code(fav) else 1 - chance
            out.append({"week": week, "matchup": entry.get("matchup", ""), "favourite_home": fav_home,
                        "market": _number(entry.get("line")), "margin": float(margin), "need": need,
                        "p_fav": float(p_fav), "credited": fav_margin_final >= need})
    return out


def _logloss(p: float, hit: bool) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if hit else 1 - p)


def score(plan: dict, rows: list[dict]) -> dict:
    from .. import analytics
    used, diffs = [], []
    for row in rows:
        if plan["applies"] == "small favourites" and not (row["market"] is not None and row["market"] < 3):
            continue
        sd = _sd_for(row["margin"], row["need"], row["p_fav"])
        shift = plan["shift_favourite"] + (plan["shift_home"] if row["favourite_home"] else -plan["shift_home"])
        p_plan = analytics.cover_chance(row["margin"] + shift, row["need"], sd)
        base, mine = _logloss(row["p_fav"], row["credited"]), _logloss(p_plan, row["credited"])
        used.append(row)
        diffs.append(base - mine)           # positive: the plan did better
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    sd = (sum((d - mean) ** 2 for d in diffs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    half = 1.96 * sd / n ** 0.5 if n > 1 else None
    if n < GAMES_NEEDED:
        call = f"running: {n} of {GAMES_NEEDED} games"
    elif mean >= BETTER_BY and half is not None and mean - half > 0:
        call = "better than Deadeye by the Model Lab's rule - a case to put to Sam"
    else:
        call = "not better by the Model Lab's rule"
    return {"id": plan["id"], "fingerprint": fingerprint(plan), "registered": plan["registered"],
            "rule": plan["rule"], "games": n, "edge": round(mean, 5),
            "low": None if half is None else round(mean - half, 5),
            "high": None if half is None else round(mean + half, 5), "call": call,
            "weeks": sorted({r["week"] for r in used})}


def run(write: bool = True) -> list[dict]:
    """Score every plan on the frozen records so far (on a copy of the app's database)."""
    from . import data, study
    out = []
    with study.books():
        for plan in PLANS:
            out.append(score(plan, games(plan["season"], plan["first_week"])))
    if write:
        folder = data.folder() / "prereg"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "latest.json").write_text(json.dumps({"made": time.time(), "plans": out}, indent=1),
                                            encoding="utf-8")
    return out
