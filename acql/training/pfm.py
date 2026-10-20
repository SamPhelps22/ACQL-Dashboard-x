"""PFM against Deadeye: does Pro Football Mania's rating say anything the card did not already know?

The question is narrow on purpose. Not "do PFM's best teams win" - the
betting line knows that - but: with Deadeye's own chance in hand (the line,
moved a share of the way toward the computer models), does adding a PFM
difference between the two sides make the chance better on games it has not
seen? And the same with the bare line in place of Deadeye, to see whether
PFM could stand in for the models' share rather than ride on top of it.

Variants, each its own column of chances, each reproducible from the books
and the PFM snapshots alone:

    A  Deadeye, as the dashboard priced it (production, untouched)
    B  the betting line alone, on the dashboard's curve (no models' share)
    C  A + the PFM Team Score difference
    C2 B + the PFM Team Score difference (PFM in place of the models' share)
    C3 A + the change in that difference since PFM's previous update
    D  A + one grade difference at a time (QB, roster, ..., explosiveness)
    E  A + all eight grade differences together, shrunk (ridge) - never with
       the Team Score as well, which is made of seven of them
    F  A + only the PFM facts that had already earned a place on earlier
       weeks (the rule below); with no such fact F is A
    closing  the closing line - a yardstick only, never a feature

How each added fact is taught: as week w begins, a logistic fit of the
credited side on the fact, with the variant's own chance as a fixed offset
(so a coefficient of zero gives back the variant's chance exactly), no
intercept, and a fixed shrinkage (RIDGE) chosen before any result was seen.
The fact is standardised with the mean and spread of the training games only.
Until MIN_TRAIN training games have the fact, nothing is taught and the
variant equals its base.

What PFM may be seen, and when:

    snapshots   the app's own pulls (feeds/pfm.py): usable for a week only
                when read before that week's deadline (pfm.as_of)
    history     the weekly scores each team page lists (BASELINE, W1, ...),
                read later. A score labelled Wn is taken as PFM's view after
                week n, usable for week n+1 when it was published before that
                deadline: the date is the update's own where the changes page
                gives it, otherwise the Tuesday before the deadline (inferred,
                and flagged). Only the Team Score has a history; the grades
                exist from the first snapshot on.

Nothing here reaches a pick. The dashboard reads only the result file it
writes (data/training/pfm/latest.json), through acql/model/pfmcheck.py.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import data, evaluate, probability

log = logging.getLogger(__name__)

FEATURE_VERSION = "pfm-features-1"
MODEL_VERSION = "pfm-shadow-1"
#: Shrinkage on each standardised coefficient (the logistic fit's prior
#: precision). Fixed in advance: four games' worth of doubt per fact.
RIDGE = 4.0
#: Fewest training games with the fact before anything is taught.
MIN_TRAIN = 40
#: Fewest earlier test games, and a 95% range wholly below zero, before a fact earns a place in F.
EARN_GAMES = 150
#: As feeds/pfm.py: an update older than this at the deadline is stale.
STALE_DAYS = 9
#: The grades, oriented home less road.
GRADES = ("qb_stability", "roster_strength", "coaching_direction", "recent_performance", "offense_strength",
          "defense_strength", "franchise_direction", "explosiveness")
#: Matchup terms: one side's attack against the other's defence, home less road.
MATCHUPS = {"off_vs_def": "offense_strength", "qb_vs_def": "qb_stability", "expl_vs_def": "explosiveness"}
CANDIDATES = ("score_diff", "score_move") + tuple(f"d_{g}" for g in GRADES) + tuple(MATCHUPS)
ABOUT = {
    "score_diff": "PFM Team Score, home less road",
    "score_move": "how far that difference moved at PFM's latest update",
    **{f"d_{g}": g.replace("_", " ") + ", home less road" for g in GRADES},
    "off_vs_def": "home offense less road defense, less the same the other way",
    "qb_vs_def": "home QB stability less road defense, less the same the other way",
    "expl_vs_def": "home explosiveness less road defense, less the same the other way",
}
#: The matchup terms are sums of two grade differences ((h.a - r.d) - (r.a - h.d) = d_a + d_d): they are
#: tried one at a time, never inside E with the grades they are made of.


def _folder():
    where = data.folder() / "pfm"
    where.mkdir(parents=True, exist_ok=True)
    return where


# ---- what PFM said, as each deadline stood ---------------------------------------------------------
def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def history_points(snapshot: dict) -> pd.DataFrame:
    """Every weekly score a snapshot's team pages list: code, label, after_week
    (0 for BASELINE), score, and the update date where PFM states one."""
    rows = []
    published: dict[tuple[str, str], str] = {}
    teams = snapshot.get("teams") or {}
    # the changes page dates an update; its "after" score is the label it made
    for event in snapshot.get("changes") or []:
        history = (teams.get(event.get("code")) or {}).get("history") or []
        for i, (label, value) in enumerate(history):
            before = history[i - 1][1] if i else None
            if (event.get("current_score") is not None and abs(value - event["current_score"]) <= 0.051
                    and before is not None and event.get("previous_score") is not None
                    and abs(before - event["previous_score"]) <= 0.051):
                published[(event["code"], label)] = event["date"]
    for code, entry in teams.items():
        history = entry.get("history") or []
        for i, (label, value) in enumerate(history):
            after = 0 if label == "BASELINE" else int(label[1:]) if label[1:].isdigit() else None
            if after is None:
                continue
            stated = published.get((code, label))
            if stated is None and i == len(history) - 1:
                stated = snapshot.get("effective_date")         # the newest point is the update the page states
            rows.append({"code": code, "label": label, "after_week": after, "score": float(value),
                         "published": stated, "previous": float(history[i - 1][1]) if i else np.nan})
    return pd.DataFrame(rows, columns=["code", "label", "after_week", "score", "published", "previous"])


def _lock_day(locked_at: float) -> date:
    return datetime.fromtimestamp(float(locked_at), timezone.utc).date()


def pfm_for_week(week: int, locked_at: float, snaps: list[dict], points: pd.DataFrame) -> dict:
    """What PFM said that could have been known by this week's deadline:
    {code: {score, previous, grades...}} plus where it came from. Snapshots
    read before the deadline come first; otherwise the history point from
    after the previous week, if it was published (or, inferred, due) by then."""
    from ..feeds import pfm
    snap = pfm.as_of(locked_at, snaps)
    if snap is not None:
        teams = {}
        for code, entry in (snap.get("teams") or {}).items():
            history = entry.get("history") or []
            teams[code] = {"score": entry.get("score"), **{g: entry.get(g) for g in GRADES},
                           "previous": history[-2][1] if len(history) >= 2 else None}
        return {"from": "snapshot", "file": snap.get("file"), "effective_date": snap.get("effective_date"),
                "collected_at": snap.get("collected_at"), "inferred": False, "teams": teams}
    if points.empty:
        return {"from": "", "teams": {}}
    lock_day = _lock_day(locked_at)
    chosen = points[points["after_week"] == week - 1]
    teams, inferred, dates = {}, False, set()
    for row in chosen.itertuples():
        stated = _day(row.published)
        when = stated or (lock_day - timedelta(days=2))         # PFM updates on the Tuesday before
        if when > lock_day or (stated is not None and stated >= lock_day):
            continue                                          # published too late for this card
        inferred |= stated is None
        dates.add(when.isoformat())
        teams[row.code] = {"score": row.score, "previous": None if np.isnan(row.previous) else row.previous,
                           **{g: None for g in GRADES}}
    return {"from": "history" if teams else "", "inferred": inferred, "teams": teams,
            "effective_date": max(dates) if dates else None, "collected_at": None, "file": None}


# ---- the games ---------------------------------------------------------------------------------
def _pair(home: dict | None, away: dict | None, key: str) -> float:
    a = None if home is None else home.get(key)
    b = None if away is None else away.get(key)
    return float(a) - float(b) if a is not None and b is not None else np.nan


def table(books: pd.DataFrame, snaps: list[dict], closing: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row a game: the production numbers as the books hold them, the
    variants' bases, and every PFM fact as it could be known at the deadline."""
    if books.empty:
        return pd.DataFrame()
    newest = max(snaps, key=lambda s: float(s.get("collected_at") or 0)) if snaps else None
    points = history_points(newest) if newest is not None else history_points({})
    curve = probability.InUse()
    rows = []
    seen: dict[int, dict] = {}
    for game in books.itertuples(index=False):
        g = game._asdict()
        week, lock = int(g["week"]), float(g["locked_at"])
        if week not in seen:
            seen[week] = pfm_for_week(week, lock, snaps, points)
        known = seen[week]
        home, away = known["teams"].get(g["home"]), known["teams"].get(g["away"])
        pool_line = float(g.get("pool_line")) if g.get("pool_line") is not None else np.nan
        favourite = str(g.get("pool_favourite") or "")
        line = g.get("line_used")
        row = {k: g.get(k) for k in ("season", "week", "home", "away", "game", "locked_at", "actual",
                                     "credited_home", "pool_line", "pool_favourite", "deadeye_live",
                                     "deadeye_chance", "line_used", "used_at", "taken_at", "line_deadline")}
        row["market_chance"] = (probability.home_chance(curve, float(line), pool_line, favourite)
                                if line is not None and not np.isnan(line) else np.nan)
        row["pfm_from"] = known["from"] if home is not None and away is not None else ""
        row["pfm_inferred"] = bool(known.get("inferred")) and row["pfm_from"] == "history"
        row["pfm_effective"] = known.get("effective_date") if row["pfm_from"] else None
        row["pfm_file"] = known.get("file") if row["pfm_from"] else None
        stated = _day(known.get("effective_date"))
        row["pfm_age_days"] = ((_lock_day(lock) - stated).days if stated and row["pfm_from"] else np.nan)
        row["pfm_home"] = None if home is None else home.get("score")
        row["pfm_away"] = None if away is None else away.get("score")
        row["score_diff"] = _pair(home, away, "score")
        moved_home = (None if home is None or home.get("previous") is None or home.get("score") is None
                      else float(home["score"]) - float(home["previous"]))
        moved_away = (None if away is None or away.get("previous") is None or away.get("score") is None
                      else float(away["score"]) - float(away["previous"]))
        row["score_move"] = moved_home - moved_away if moved_home is not None and moved_away is not None else np.nan
        for grade in GRADES:
            row[f"d_{grade}"] = _pair(home, away, grade)
        for name, attack in MATCHUPS.items():
            a = _pair(home, away, attack)
            # (home attack - road defence) - (road attack - home defence) = attack diff + defence diff
            d = _pair(home, away, "defense_strength")
            row[name] = a + d if not (np.isnan(a) or np.isnan(d)) else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    for column in ("deadeye_chance", "market_chance", "credited_home", "actual", "line_used", "deadeye_live"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["closing_chance"] = np.nan
    frame["line_closing"] = np.nan
    if closing is not None and not closing.empty:
        keyed = {(int(r.season), int(r.week), r.home, r.away): r.line_closing for r in closing.itertuples()}
        for i, r in frame.iterrows():
            value = keyed.get((int(r.season), int(r.week), r.home, r.away))
            if value is not None and not np.isnan(value):
                frame.at[i, "line_closing"] = float(value)
                frame.at[i, "closing_chance"] = probability.home_chance(
                    curve, float(value), float(r.pool_line), str(r.pool_favourite or ""))
    return frame


# ---- teaching one fact on top of a base chance --------------------------------------------------
def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_offset(x: np.ndarray, y: np.ndarray, offset: np.ndarray, ridge: float = RIDGE, steps: int = 50) -> np.ndarray:
    """Coefficients b of P(y) = logistic(offset + x b), no intercept, shrunk
    toward zero by `ridge`, by Newton's method. Deterministic."""
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    b = np.zeros(x.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(offset + x @ b, -30, 30)))
        grad = x.T @ (p - y) + ridge * b
        hess = (x * (p * (1 - p))[:, None]).T @ x + ridge * np.eye(len(b))
        move = np.linalg.solve(hess, grad)
        b -= move
        if np.abs(move).max() < 1e-10:
            break
    return b


@dataclass
class Taught:
    chance: np.ndarray                  # the variant's chance, game by game (nan where it had no base)
    taught: np.ndarray                  # True where a coefficient was taught (not just the base)
    weights: dict = field(default_factory=dict)  # week -> coefficients (standardised), for the report


def walk(frame: pd.DataFrame, base: str, facts: list[str] | tuple[str, ...], ridge: float = RIDGE,
         min_train: int = MIN_TRAIN, until_week: int | None = None) -> Taught:
    """The variant `base` + `facts`, walked forward a week at a time. A game's
    chance is taught only on graded games of earlier weeks; a game without
    every fact keeps its base chance."""
    p_base = frame[base].to_numpy(dtype=float)
    out = p_base.copy()
    taught = np.zeros(len(frame), dtype=bool)
    weights: dict = {}
    if not facts:
        return Taught(out, taught, weights)
    x_all = frame[list(facts)].to_numpy(dtype=float)
    has = ~np.isnan(x_all).any(axis=1) & ~np.isnan(p_base)
    y_all = frame["credited_home"].to_numpy(dtype=float)
    weeks = frame["week"].to_numpy(dtype=int)
    for week in sorted(set(weeks.tolist())):
        if until_week is not None and week > until_week:
            break
        train = (weeks < week) & has & ~np.isnan(y_all)
        test = (weeks == week) & has
        if train.sum() < min_train or not test.any():
            continue
        mean, sd = x_all[train].mean(axis=0), x_all[train].std(axis=0)
        sd = np.where(sd > 1e-9, sd, 1.0)
        z = (x_all - mean) / sd
        b = fit_offset(z[train], y_all[train], _logit(p_base[train]), ridge)
        out[test] = 1 / (1 + np.exp(-np.clip(_logit(p_base[test]) + z[test] @ b, -30, 30)))
        taught[test] = True
        weights[int(week)] = [float(v) for v in b]
    return Taught(out, taught, weights)


def earned(frame: pd.DataFrame, before_week: int, base: str = "deadeye_chance") -> list[str]:
    """The facts that had, on test weeks before `before_week` only, at least
    EARN_GAMES taught games and a 95% range of log-loss change wholly below
    zero against the base. The rule F uses; it never looks at `before_week` itself."""
    keep = []
    early = frame[frame["week"] < before_week]
    graded = early["credited_home"].notna().to_numpy()
    for fact in CANDIDATES:
        walked = walk(early, base, [fact])
        use = walked.taught & graded & ~np.isnan(early[base].to_numpy(dtype=float))
        if use.sum() < EARN_GAMES:
            continue
        came = early["credited_home"].to_numpy(dtype=float)[use]
        gain = evaluate.losses(walked.chance[use], came) - evaluate.losses(early[base].to_numpy(dtype=float)[use], came)
        low, high = evaluate.interval(gain, early["week"].to_numpy()[use])
        if high < 0:
            keep.append(fact)
    return keep


def walk_earned(frame: pd.DataFrame) -> Taught:
    """F: each week, Deadeye plus only the facts earned before it."""
    out = frame["deadeye_chance"].to_numpy(dtype=float).copy()
    taught = np.zeros(len(frame), dtype=bool)
    chosen = {}
    for week in sorted(set(frame["week"].astype(int).tolist())):
        facts = earned(frame, week)
        chosen[week] = facts
        if not facts:
            continue
        walked = walk(frame, "deadeye_chance", facts, until_week=week)
        here = (frame["week"].to_numpy(dtype=int) == week) & walked.taught
        out[here], taught[here] = walked.chance[here], True
    return Taught(out, taught, {"chosen": chosen})


def variants(frame: pd.DataFrame) -> dict[str, Taught]:
    """Every variant's chances on the table, in the order they are reported."""
    out = {
        "A Deadeye (production)": Taught(frame["deadeye_chance"].to_numpy(dtype=float), np.zeros(len(frame), bool)),
        "B Line alone": Taught(frame["market_chance"].to_numpy(dtype=float), np.zeros(len(frame), bool)),
        "C Deadeye + PFM score": walk(frame, "deadeye_chance", ["score_diff"]),
        "C2 Line + PFM score": walk(frame, "market_chance", ["score_diff"]),
        "C3 Deadeye + PFM movement": walk(frame, "deadeye_chance", ["score_move"]),
    }
    for grade in GRADES:
        out[f"D Deadeye + {grade.replace('_', ' ')}"] = walk(frame, "deadeye_chance", [f"d_{grade}"])
    for name in MATCHUPS:
        out[f"D Deadeye + {name.replace('_', ' ')}"] = walk(frame, "deadeye_chance", [name])
    out["E Deadeye + all grades (ridge)"] = walk(frame, "deadeye_chance", [f"d_{g}" for g in GRADES])
    out["F Deadeye + earned PFM facts"] = walk_earned(frame)
    return out


# ---- marking ---------------------------------------------------------------------------------
@dataclass
class Mark:
    name: str
    games: int
    taught: int
    logloss: float | None
    brier: float | None
    accuracy: float | None
    calibration: float | None
    vs_a: float | None              # log loss a game against A on the same games (minus: better)
    low: float | None
    high: float | None
    brier_vs_a: float | None


def mark(frame: pd.DataFrame, found: dict[str, Taught], only_taught: bool = True) -> tuple[list[Mark], np.ndarray]:
    """Every variant on the same graded games: those where every variant has a
    chance and, when `only_taught`, where C (the main question) was taught."""
    came = frame["credited_home"].to_numpy(dtype=float)
    weeks = frame["week"].to_numpy(dtype=int)
    common = ~np.isnan(came)
    for t in found.values():
        common &= ~np.isnan(t.chance)
    if only_taught:
        common &= found["C Deadeye + PFM score"].taught
    a = found["A Deadeye (production)"].chance
    out = []
    for name, t in found.items():
        if not common.any():
            out.append(Mark(name, 0, 0, None, None, None, None, None, None, None, None))
            continue
        s = evaluate.score(t.chance[common], came[common])
        gain = evaluate.losses(t.chance[common], came[common]) - evaluate.losses(a[common], came[common])
        low, high = evaluate.interval(gain, weeks[common])
        brier = ((evaluate.held(t.chance[common]) - came[common]) ** 2
                 - (evaluate.held(a[common]) - came[common]) ** 2)
        out.append(Mark(name, int(common.sum()), int((t.taught & common).sum()), s.logloss, s.brier, s.rate, s.off,
                        float(gain.mean()), None if np.isnan(low) else low, None if np.isnan(high) else high,
                        float(brier.mean())))
    return out, common


def benchmark(frame: pd.DataFrame, keep: np.ndarray) -> dict | None:
    """The closing line on the same games, where it is known - a yardstick, not a variant."""
    p = frame["closing_chance"].to_numpy(dtype=float)
    came = frame["credited_home"].to_numpy(dtype=float)
    use = keep & ~np.isnan(p)
    if not use.any():
        return None
    s = evaluate.score(p[use], came[use])
    a = frame["deadeye_chance"].to_numpy(dtype=float)[use]
    return {"games": int(use.sum()), "logloss": s.logloss, "brier": s.brier, "accuracy": s.rate,
            "deadeye_logloss_same_games": float(evaluate.losses(a, came[use]).mean())}


def redundancy(frame: pd.DataFrame) -> dict:
    """How much of PFM the line and Deadeye already carry: correlations on every
    game with the fact (no result is used), and what is left of the PFM
    difference once the line is taken out of it."""
    out: dict = {}
    for fact in ("score_diff",) + tuple(f"d_{g}" for g in GRADES):
        both = frame[[fact, "line_used", "deadeye_live"]].dropna()
        if len(both) < 10:
            continue
        x, line, dead = (both[c].to_numpy(dtype=float) for c in (fact, "line_used", "deadeye_live"))
        slope, inter = np.polyfit(line, x, 1)
        left = x - (slope * line + inter)
        out[fact] = {"games": len(both), "with_line": float(np.corrcoef(x, line)[0, 1]),
                     "with_deadeye": float(np.corrcoef(x, dead)[0, 1]),
                     "share_left_after_line": float(left.var() / x.var()) if x.var() > 0 else None}
    grades = frame[[f"d_{g}" for g in GRADES] + ["score_diff"]].dropna()
    if len(grades) >= 10:
        out["grades_with_score"] = {g: float(np.corrcoef(grades[f"d_{g}"], grades["score_diff"])[0, 1])
                                    for g in GRADES}
    return out


def descriptive(frame: pd.DataFrame) -> dict | None:
    """In-sample and descriptive only, never a verdict: does the PFM difference
    line up with what Deadeye's margin missed by? (actual - Deadeye margin)."""
    both = frame[["score_diff", "actual", "deadeye_live", "week"]].dropna()
    if len(both) < 10:
        return None
    miss = both["actual"] - both["deadeye_live"]
    corr = float(np.corrcoef(both["score_diff"], miss)[0, 1])
    draws = np.random.default_rng(evaluate.SEED)
    idx = np.arange(len(both))
    weeks = both["week"].to_numpy()
    groups = [idx[weeks == w] for w in sorted(set(weeks.tolist()))]
    sims = []
    for _ in range(2000):
        pick = np.concatenate([groups[i] for i in draws.integers(0, len(groups), len(groups))])
        if len(pick) < 3:
            continue
        a, b = both["score_diff"].to_numpy()[pick], miss.to_numpy()[pick]
        if a.std() > 0 and b.std() > 0:
            sims.append(np.corrcoef(a, b)[0, 1])
    low, high = (np.percentile(sims, [2.5, 97.5]) if sims else (np.nan, np.nan))
    slope = float(np.polyfit(both["score_diff"], miss, 1)[0])
    return {"games": len(both), "corr_with_miss": corr, "low": float(low), "high": float(high),
            "points_per_pfm_point": slope}


def by_group(frame: pd.DataFrame, found: dict[str, Taught], keep: np.ndarray, names: list[str]) -> dict:
    """Log loss a game by week, by favourite/underdog at home, and by size of line."""
    came = frame["credited_home"].to_numpy(dtype=float)
    groups = {
        "week": frame["week"].astype(int).astype(str).to_numpy(),
        "home side": np.where(frame["deadeye_chance"].to_numpy(dtype=float) >= 0.5, "home favoured", "home underdog"),
        "line size": pd.cut(frame["line_used"].abs(), [-0.1, 2.99, 6.99, 99], labels=["under 3", "3 to 6.5", "7 and up"]
                            ).astype(str).to_numpy(),
    }
    out = {}
    for kind, labels in groups.items():
        rows = []
        for label in sorted(set(labels[keep].tolist())):
            use = keep & (labels == label)
            rows.append({"group": label, "games": int(use.sum()),
                         **{n: float(evaluate.losses(found[n].chance[use], came[use]).mean()) for n in names}})
        out[kind] = rows
    return out


# ---- staying sealed ------------------------------------------------------------------------------
def sealed(frame: pd.DataFrame, week: int) -> tuple[bool, str]:
    """Scramble every result from `week` on and show that no chance for `week`
    moves: nothing taught for a week can have seen its own results or later ones."""
    if frame.empty or week not in set(frame["week"].astype(int).tolist()):
        return True, "no such week"
    before = variants(frame)
    shaken = frame.copy()
    later = shaken["week"].astype(int) >= week
    draw = np.random.default_rng(7)
    shaken.loc[later, "credited_home"] = draw.integers(0, 2, int(later.sum())).astype(float)
    shaken.loc[later, "actual"] = draw.normal(0, 14, int(later.sum())).round()
    after = variants(shaken)
    here = frame["week"].astype(int).to_numpy() == week
    moved = [n for n in before if not np.allclose(before[n].chance[here], after[n].chance[here], equal_nan=True)]
    return (not moved), ("no chance moved" if not moved else "moved: " + ", ".join(moved))


# ---- the whole study -------------------------------------------------------------------------------
def verdict(marks: list[Mark]) -> tuple[str, str]:
    """('improvement' | 'inconclusive' | 'no improvement', the sentence that says why)."""
    main = next((m for m in marks if m.name.startswith("C Deadeye")), None)
    if main is None or main.games == 0:
        return "inconclusive", "No game yet had a PFM rating from before its deadline and a taught coefficient."
    if main.games < EARN_GAMES:
        return "inconclusive", (f"{main.games} games is too few to tell: the 95% range on the change runs "
                                f"{_signed(main.low)} to {_signed(main.high)} log loss a game. At least "
                                f"{EARN_GAMES} taught games over several weeks are needed before PFM could earn "
                                "a place.")
    if main.high is not None and main.high < 0:
        return "improvement", (f"Over {main.games} games Deadeye + PFM score was better by {-main.vs_a:.4f} a game, "
                               "a range wholly on the better side. A reason to look, never a switch: promotion is "
                               "Sam's decision.")
    if main.low is not None and main.low > 0:
        return "no improvement", f"Over {main.games} games adding PFM made Deadeye worse ({main.vs_a:+.4f} a game)."
    return "inconclusive", (f"Over {main.games} games the change was {main.vs_a:+.4f} a game, with a range "
                            f"({_signed(main.low)} to {_signed(main.high)}) that takes in zero.")


def _signed(value) -> str:
    return "-" if value is None else f"{value:+.4f}"


def study(books: pd.DataFrame, snaps: list[dict], closing: pd.DataFrame | None = None,
          now: float | None = None) -> dict:
    """Everything the report and the dashboard show, as plain data."""
    from ..feeds import pfm
    now = time.time() if now is None else now
    frame = table(books, snaps, closing)
    result: dict = {"made": now, "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
                    "ridge": RIDGE, "min_train": MIN_TRAIN, "earn_games": EARN_GAMES,
                    "snapshots": [{"file": s.get("file"), "effective_date": s.get("effective_date"),
                                   "collected": s.get("collected"), "status": s.get("quality", {}).get("status")}
                                  for s in snaps],
                    "freshness": pfm.freshness(snaps[-1] if snaps else None, now),
                    "revisions": pfm.revisions(snaps)}
    if frame.empty:
        result.update(call="inconclusive", why="This season's books could not be read.", games=0, marks=[])
        return result
    graded = frame["credited_home"].notna()
    found = variants(frame)
    marks, keep = mark(frame, found)
    call, why = verdict(marks)
    weeks = sorted(set(frame.loc[graded, "week"].astype(int).tolist()))
    seals = [(w, *sealed(frame, w)) for w in weeks[1:]]
    names = ["A Deadeye (production)", "B Line alone", "C Deadeye + PFM score", "C2 Line + PFM score"]
    coverage = (frame[graded].groupby("week")
                .agg(games=("game", "count"), with_pfm=("score_diff", lambda s: int(s.notna().sum())),
                     from_snapshot=("pfm_from", lambda s: int((s == "snapshot").sum())),
                     from_history=("pfm_from", lambda s: int((s == "history").sum())),
                     inferred_date=("pfm_inferred", "sum"),
                     with_grades=("d_qb_stability", lambda s: int(s.notna().sum())),
                     stale=("pfm_age_days", lambda s: int((s > pfm.STALE_DAYS).sum())))
                .reset_index().to_dict("records"))
    late = int(((frame["used_at"].astype(float) > frame["locked_at"].astype(float)) & graded).sum())
    result.update(
        call=call, why=why, games=int(keep.sum()), graded=int(graded.sum()),
        marks=[m.__dict__ for m in marks], benchmark=benchmark(frame, keep),
        redundancy=redundancy(frame), descriptive=descriptive(frame),
        groups=by_group(frame, found, keep, names) if keep.any() else {},
        coverage=[{k: (int(v) if isinstance(v, (np.integer, bool, np.bool_)) else v) for k, v in r.items()}
                  for r in coverage],
        weights={n: {str(k): v for k, v in t.weights.items()} for n, t in found.items()
                 if n.startswith(("C ", "C2", "E "))},
        chosen={str(k): v for k, v in found["F Deadeye + earned PFM facts"].weights.get("chosen", {}).items()},
        seals=[{"week": int(w), "ok": bool(ok), "what": what} for w, ok, what in seals],
        late_lines=late,
        reliability={n: evaluate.reliability(found[n].chance[keep], frame["credited_home"].to_numpy(float)[keep])
                     for n in names} if keep.any() else {},
        missing_effect=_missing_effect(frame, found),
        upcoming=_upcoming(frame, found, now),
    )
    return result


def _missing_effect(frame: pd.DataFrame, found: dict[str, Taught]) -> dict:
    """What happens where PFM is missing or stale: the variant falls back to its base, game for game."""
    a, c = found["A Deadeye (production)"].chance, found["C Deadeye + PFM score"].chance
    missing = frame["score_diff"].isna().to_numpy()
    both = ~np.isnan(a) & ~np.isnan(c)
    return {"games_without_pfm": int(missing.sum()),
            "fell_back_to_base": bool(np.allclose(a[missing & both], c[missing & both])) if (missing & both).any()
            else True,
            "stale_games": int((frame["pfm_age_days"] > STALE_DAYS).sum())}


def _upcoming(frame: pd.DataFrame, found: dict[str, Taught], now: float) -> list[dict]:
    """This week's games still to be decided, with the shadow chance next to the card's."""
    open_ = frame["credited_home"].isna().to_numpy()
    ahead = open_ & (frame["locked_at"].astype(float).to_numpy() > now)
    if not open_.any():
        return []
    # the next card still to be made; if every deadline has passed, the week still being played
    week = int(frame.loc[ahead if ahead.any() else open_, "week"].min())
    here = open_ & (frame["week"].astype(int).to_numpy() == week)
    c = shadow_now(frame, week)
    out = []
    for i in np.flatnonzero(here):
        r = frame.iloc[i]
        out.append({"week": week, "game": r["game"], "home": r["home"], "away": r["away"],
                    "locked_at": float(r["locked_at"]), "pfm_home": r["pfm_home"], "pfm_away": r["pfm_away"],
                    "pfm_from": r["pfm_from"], "pfm_effective": r["pfm_effective"],
                    "score_diff": None if np.isnan(r["score_diff"]) else float(r["score_diff"]),
                    "grades": {g: (None if np.isnan(r[f"d_{g}"]) else float(r[f"d_{g}"])) for g in GRADES},
                    "deadeye_live": None if pd.isna(r["deadeye_live"]) else float(r["deadeye_live"]),
                    "deadeye": None if pd.isna(r["deadeye_chance"]) else float(r["deadeye_chance"]),
                    "market": None if pd.isna(r["market_chance"]) else float(r["market_chance"]),
                    "line_used": None if pd.isna(r["line_used"]) else float(r["line_used"]),
                    "shadow": None if np.isnan(c[i]) else float(c[i])})
    return out


def shadow_now(frame: pd.DataFrame, week: int) -> np.ndarray:
    """C for one week still open: taught on every graded game before it."""
    walked = walk(frame, "deadeye_chance", ["score_diff"], until_week=week)
    out = np.full(len(frame), np.nan)
    here = frame["week"].astype(int).to_numpy() == week
    out[here] = walked.chance[here]
    return out


# ---- the shadow ledger: experimental chances, kept apart from the card ----------------------------
def record_shadow(result: dict, books: pd.DataFrame, now: float | None = None, where=None) -> int:
    """Append this week's shadow chances to data/training/pfm/shadow.jsonl -
    only before each game's deadline, and only once for the same inputs. The
    card's own chance is copied beside it for the record; nothing is written
    anywhere the card reads."""
    now = time.time() if now is None else now
    where = where or _folder()
    path = where / "shadow.jsonl"
    seen = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line).get("key"))
            except ValueError:
                continue
    except OSError:
        pass
    added = 0
    taken = {r["game"]: r for r in books.to_dict("records")} if not books.empty else {}
    with path.open("a", encoding="utf-8") as out:
        for game in result.get("upcoming", []):
            if now >= game["locked_at"] or game.get("shadow") is None:
                continue
            book = taken.get(game["game"], {})
            key = "|".join(str(v) for v in (game["game"], MODEL_VERSION, FEATURE_VERSION, game.get("pfm_effective"),
                                            game.get("line_used"), round(game["shadow"], 6)))
            if key in seen:
                continue
            out.write(json.dumps({
                "key": key, "made_at": now, "model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
                "game": game["game"], "week": game["week"], "home": game["home"], "away": game["away"],
                "locked_at": game["locked_at"], "official": False,
                "market": {"line_used": game.get("line_used"), "used_at": _plain(book.get("used_at")),
                           "taken_at": _plain(book.get("taken_at"))},
                "pfm": {"from": game.get("pfm_from"), "effective_date": game.get("pfm_effective"),
                        "home": game.get("pfm_home"), "away": game.get("pfm_away")},
                "deadeye_chance": game.get("deadeye"), "shadow_chance": game["shadow"],
            }, sort_keys=True, default=_plain) + "\n")
            seen.add(key)
            added += 1
    return added


def _plain(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return None if np.isnan(number) else number


# ---- written down ------------------------------------------------------------------------------
def write_up(result: dict) -> str:
    def f(value, digits=4):
        return "-" if value is None or (isinstance(value, float) and np.isnan(value)) else f"{value:.{digits}f}"

    lines = [f"# PFM against Deadeye ({datetime.fromtimestamp(result['made']).strftime('%Y-%m-%d %H:%M')})", "",
             f"**Verdict: {result['call']}.** {result['why']}", "",
             f"Model {result['model_version']}, features {result['feature_version']}, shrinkage {result['ridge']}, "
             f"taught after {result['min_train']} training games. Nothing here changes a pick.", "",
             f"PFM data: {result['freshness']['words']}. Snapshots kept: {len(result['snapshots'])}. "
             f"Past scores PFM has rewritten since an earlier snapshot: {len(result['revisions'])}.", ""]
    if result.get("coverage"):
        lines += ["## What PFM could be seen, week by week (graded games)", "",
                  "| Week | Games | With PFM | From a snapshot | From team-page history | Date inferred | With grades | Stale |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r['week']} | {r['games']} | {r['with_pfm']} | {r['from_snapshot']} | {r['from_history']} | "
                  f"{r['inferred_date']} | {r['with_grades']} | {r['stale']} |" for r in result["coverage"]]
        lines += [""]
    if result.get("marks"):
        lines += [f"## Out of sample, on the same {result['games']} games", "",
                  "Log loss and Brier a game (lower is better). Against A is the change from production, with "
                  "the range it could plausibly lie in (whole weeks resampled, 19 times in 20).", "",
                  "| Variant | Games | Taught | Log loss | Brier | Right | Calibration gap | Against A | Range |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for m in result["marks"]:
            lines.append(f"| {m['name']} | {m['games']} | {m['taught']} | {f(m['logloss'])} | {f(m['brier'])} | "
                         f"{f(m['accuracy'], 3)} | {f(m['calibration'], 3)} | "
                         f"{_signed(m['vs_a'])} | {_signed(m['low'])} to {_signed(m['high'])} |")
        b = result.get("benchmark")
        if b:
            lines += ["", f"Closing line, same games where known ({b['games']}): log loss {f(b['logloss'])}, "
                          f"Brier {f(b['brier'])}; Deadeye on those games {f(b['deadeye_logloss_same_games'])}. "
                          "A yardstick only - the closing line is not known at the deadline."]
        lines += [""]
    if result.get("groups"):
        lines += ["## By group (log loss a game; small groups say little)", ""]
        for kind, rows in result["groups"].items():
            names = [k for k in rows[0] if k not in ("group", "games")] if rows else []
            lines += [f"**{kind}**", "", "| Group | Games | " + " | ".join(names) + " |",
                      "|---|---|" + "---|" * len(names)]
            lines += [f"| {r['group']} | {r['games']} | " + " | ".join(f(r[n]) for n in names) + " |" for r in rows]
            lines += [""]
    if result.get("redundancy"):
        lines += ["## Overlap with what Deadeye already has (no results used)", "",
                  "| PFM fact | Games | Correlation with the line | With Deadeye's margin | Variance left after the line |",
                  "|---|---|---|---|---|"]
        for fact, r in result["redundancy"].items():
            if fact == "grades_with_score":
                continue
            lines.append(f"| {ABOUT.get(fact, fact)} | {r['games']} | {f(r['with_line'], 2)} | "
                         f"{f(r['with_deadeye'], 2)} | {f(r['share_left_after_line'], 2)} |")
        g = result["redundancy"].get("grades_with_score")
        if g:
            lines += ["", "Each grade difference against the Team Score difference: "
                      + ", ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in g.items())
                      + ". The score is a weighted sum of seven of them, so E never takes the score as well."]
        lines += [""]
    d = result.get("descriptive")
    if d:
        lines += ["## Descriptive only (in sample - not a test)", "",
                  f"Over {d['games']} graded games, the PFM score difference against what Deadeye's margin missed by: "
                  f"correlation {d['corr_with_miss']:+.2f} (weeks resampled: {d['low']:+.2f} to {d['high']:+.2f}), "
                  f"{d['points_per_pfm_point']:+.2f} points of miss per PFM point.", ""]
    if result.get("seals"):
        lines += ["## Sealed", "", "Every result from a week on scrambled; that week's chances must not move:", ""]
        lines += [f"- week {s['week']}: {'sealed' if s['ok'] else 'LEAK'} ({s['what']})" for s in result["seals"]]
        lines += [""]
    if result.get("late_lines"):
        lines += [f"Note: {result['late_lines']} graded games were priced from a line taken after the pool's "
                  "deadline (weeks the books flag). A, B and every variant built on them share that line, so the "
                  "comparison between them is fair, but none is quite the card that could have been made.", ""]
    m = result.get("missing_effect") or {}
    if m:
        lines += [f"Missing PFM: {m.get('games_without_pfm', 0)} games had no PFM difference; each kept its base "
                  f"chance ({'checked' if m.get('fell_back_to_base') else 'NOT the case - look'}).", ""]
    return "\n".join(lines)


def closing_lines(path=None) -> pd.DataFrame | None:
    """nflverse's closing lines, only for games that had kicked off before the
    file was downloaded: for a game still to come its "closing" line is just
    the line on the day of the download."""
    from pathlib import Path
    from ..feeds.nflverse import FOLDER, GAMES_FILE
    source = Path(path) if path else FOLDER / GAMES_FILE
    try:
        frame = data.nflverse_games(source)
        cut = source.stat().st_mtime
    except Exception:  # noqa: BLE001 - the yardstick is optional
        return None
    if frame.empty:
        return None
    return frame[frame["kickoff"].astype(float) < cut]


def run(now: float | None = None) -> tuple[str, object]:
    """The study on this season's books and every kept snapshot; writes the
    report, the result file the Model Lab reads, and this week's shadow chances."""
    from ..feeds import pfm
    from . import study as books_study
    notes = data.Notes()
    books = books_study.load_books(notes)
    snaps = pfm.snapshots()
    closing = closing_lines()
    result = study(books, snaps, closing, now)
    where = _folder()
    stamp = datetime.fromtimestamp(result["made"]).strftime("%Y%m%d-%H%M")
    text = write_up(result)
    (where / f"report-{stamp}.md").write_text(text, encoding="utf-8")
    (where / "report.md").write_text(text, encoding="utf-8")
    temp = where / "latest.json.part"
    temp.write_text(json.dumps(result, indent=1, default=_plain), encoding="utf-8")
    temp.replace(where / "latest.json")
    added = record_shadow(result, books, now)
    log.info("PFM study: %s, %s games; %s shadow chances recorded", result["call"], result.get("games"), added)
    return text, where / "report.md"
