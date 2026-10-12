"""The three A.C.Q.L. contests, replayed season by season.

    python -m acql.training contests      writes data/training/contests.md and contests.json

For every regular-season game the season archives have (data.history), each
forecast picks the way the A.C.Q.L. card would:

    main game    straight games: the predicted winner; line games: the side
                 the pool would credit under the line (a win by exactly a
                 whole-number line goes to the favourite)
    Big Loser    the three teams with the best chance of losing by 15 or more
                 (analytics.big_loser_chance), lines playing no part
    suicide      each week, the unused team likeliest to survive (survivor.
                 survive_chance - against the line on a line game), one season
                 at a time from week 1, never the same team twice

Forecasts compared on identical games: the market line, Deadeye (the line
nudged toward the trimmed model consensus at the starting weight, exactly as
predictions.Forecast.expected), the consensus alone, and every computer model
with enough games.

What is and is not known, said everywhere it matters:

  * Every pick is made from numbers posted before the game; no result, and
    nothing from a later week, is read until the pick is made. Nothing here
    is fitted on the results, so there is nothing to leak.
  * The archives are UNDATED: when each forecast was posted, or whether it was
    revised, is not in the files. The line is the archive's midweek line;
    2010-2012 have none, so their last-updated line is used (later, so
    sharper) and the table says which.
  * The commissioner's lines exist for this season only. Line games in past
    seasons are his habit applied to the opening line (data._habit_lines):
    a proxy, not his real lines.
  * How a tie is graded is not recorded. A tied game is left out of the main
    game and counts as a loss in the suicide pool (as the dashboard grades
    one today); the count of each is reported.
  * The Big Loser chance curve was fitted on 1999-2025 closing spreads, so its
    numbers are in-sample here. It only ranks the candidates, though, and
    a bigger expected loss always ranks higher, so the three picked do not
    depend on the fit.

No Qt here.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from .. import analytics, predictions, survivor
from . import data

FIRST, LAST = 2010, 2025
MARKET, DEADEYE, CONSENSUS = "Market line", "Deadeye", "Model consensus"
#: A model needs this many games to be scored on its own.
MIN_MODEL_GAMES = 500
DRAWS, SEED = 2000, 2026


# ---- the frame --------------------------------------------------------------------------
def frame(first: int = FIRST, last: int = LAST, notes: data.Notes | None = None) -> pd.DataFrame:
    """Finished games of the seasons asked for, with the line each pick is made from."""
    found = data.history(notes=notes)
    if found.empty:
        return found
    found = found[(found.season >= first) & (found.season <= last)].copy()
    midweek = found["line_midweek"] if "line_midweek" in found else pd.Series(np.nan, index=found.index)
    found["line_used"] = midweek.where(midweek.notna(), found["line_updated"])
    found["line_from"] = np.where(midweek.notna(), "midweek", "updated")
    return found[found["line_used"].notna()].reset_index(drop=True)


def model_columns(games: pd.DataFrame) -> list[str]:
    return [c for c in data.model_columns(games) if games[c].notna().sum() >= MIN_MODEL_GAMES]


def forecasts(games: pd.DataFrame) -> dict[str, np.ndarray]:
    """Forecast name -> home margin per game (NaN where it has none)."""
    models = data.model_columns(games)
    out = {MARKET: games["line_used"].to_numpy(float)}
    consensus = np.full(len(games), np.nan)
    deadeye = np.full(len(games), np.nan)
    for (season, week), rows in games.groupby(["season", "week"]).groups.items():
        rows = list(rows)
        made = []
        for i in rows:
            opinions = tuple(float(v) for v in games.loc[i, models] if not pd.isna(v))
            opening = games.at[i, "line_opening"]
            made.append(predictions.Forecast(
                road=games.at[i, "away"], home=games.at[i, "home"], market=float(games.at[i, "line_used"]),
                opening=None if pd.isna(opening) else float(opening), opinions=opinions))
        lean = predictions.home_lean(made)
        typical = predictions.typical_disagreement(made)
        for i, f in zip(rows, made):
            if f.opinions:
                consensus[i] = f.consensus
            deadeye[i] = f.expected(predictions.CONSENSUS_WEIGHT, lean, typical)
    out[DEADEYE] = deadeye
    out[CONSENSUS] = consensus
    for c in model_columns(games):
        out[c] = games[c].to_numpy(float)
    return out


# ---- the main game ------------------------------------------------------------------------
@lru_cache(maxsize=200_000)
def _favourite_credited_chance(fav_margin: float, line: float) -> float:
    return float(analytics.cover_chance(fav_margin, analytics.line_need(line)))


def main_pick(home_margin: float, pool_line: float | None, pool_favourite: str) -> str | None:
    """"home"/"away": the side the A.C.Q.L. card takes, from a home margin."""
    if home_margin is None or math.isnan(home_margin):
        return None
    if pool_line is None or math.isnan(pool_line) or not pool_favourite:
        return "home" if home_margin >= 0 else "away"           # a pick 'em goes home, as predict_margin does
    fav_margin = home_margin if pool_favourite == "home" else -home_margin
    p_fav = _favourite_credited_chance(round(fav_margin, 2), float(pool_line))
    return pool_favourite if p_fav > 0.5 else ("away" if pool_favourite == "home" else "home")


def credited(actual: float, pool_line: float | None, pool_favourite: str) -> str | None:
    """"home"/"away" as the pool credits the game; None for a straight-up tie."""
    if pool_line is None or math.isnan(pool_line) or not pool_favourite:
        return None if actual == 0 else ("home" if actual > 0 else "away")
    fav_by = actual if pool_favourite == "home" else -actual
    if fav_by >= analytics.line_need(pool_line):
        return pool_favourite
    return "away" if pool_favourite == "home" else "home"


def main_game(games: pd.DataFrame, made: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Forecast -> 1 right / 0 wrong / NaN (no pick or a tie) per game."""
    lines = games["pool_line"].to_numpy(float)
    favourites = games["pool_favourite"].fillna("").to_numpy(str)
    truth = [credited(a, l, f) for a, l, f in zip(games["actual"], lines, favourites)]
    out = {}
    for name, margins in made.items():
        right = np.full(len(games), np.nan)
        for i, (m, l, f, t) in enumerate(zip(margins, lines, favourites, truth)):
            pick = main_pick(m, l, f)
            if pick is not None and t is not None:
                right[i] = float(pick == t)
        out[name] = right
    return out


# ---- Big Loser ---------------------------------------------------------------------------------
@dataclass
class LoserWeek:
    season: int
    week: int
    picks: list[str]
    hits: int
    chance: float                   # the three's summed chance, as the curve has it


def big_losers(games: pd.DataFrame, margins: np.ndarray) -> list[LoserWeek]:
    """Each week's three, picked from one forecast's margins."""
    out = []
    for (season, week), rows in games.groupby(["season", "week"]).groups.items():
        candidates = []
        for i in rows:
            m = margins[i]
            if m is None or math.isnan(m):
                continue
            actual = games.at[i, "actual"]
            for team, own, lost_by in ((games.at[i, "home"], m, -actual), (games.at[i, "away"], -m, actual)):
                candidates.append((analytics.big_loser_chance(own), team, lost_by))
        candidates.sort(key=lambda c: -c[0])
        three = candidates[:3]
        if len(three) < 3:
            continue
        out.append(LoserWeek(int(season), int(week), [t for _, t, _ in three],
                             sum(1 for _, _, by in three if by >= analytics.BIG_LOSER_MARGIN + 1),
                             sum(c for c, _, _ in three)))
    return out


# ---- the suicide pool ------------------------------------------------------------------------------
@dataclass
class SuicideSeason:
    season: int
    picks: list[tuple[int, str, float, bool | None]] = field(default_factory=list)   # week, team, chance, survived
    out_week: int | None = None
    ties: int = 0


def suicide(games: pd.DataFrame, margins: np.ndarray) -> list[SuicideSeason]:
    """Greedy from week 1: the unused team likeliest to survive each week.

    The pick is made before the week's results are looked at; whether it
    survived is read afterwards and never feeds a later pick except through
    the team being used. Every week is played to the end of the season so
    each weekly pick can be scored, and the week it would have gone out is
    kept as well.
    """
    out = []
    for season, season_games in games.groupby("season"):
        record = SuicideSeason(int(season))
        used: set[str] = set()
        for week, rows in season_games.groupby("week").groups.items():
            options = []
            for i in rows:
                m = margins[i]
                if m is None or math.isnan(m):
                    continue
                line = games.at[i, "pool_line"]
                line = None if pd.isna(line) else float(line)
                fav = games.at[i, "pool_favourite"] or ""
                for team, side, own in ((games.at[i, "home"], "home", m), (games.at[i, "away"], "away", -m)):
                    if team in used:
                        continue
                    chance = survivor.survive_chance(own, line, fav == side) if line is not None \
                        else survivor.survive_chance(own, None, own > 0)
                    options.append((chance, team, i, side, line, fav))
            if not options:
                continue
            chance, team, i, side, line, fav = max(options, key=lambda o: (o[0], o[1]))
            used.add(team)
            got = credited(games.at[i, "actual"], np.nan if line is None else line, fav)
            if got is None:                                  # a straight-up tie: graded as a loss today
                survived, record.ties = False, record.ties + 1
            else:
                survived = got == side
            record.picks.append((int(week), team, float(chance), survived))
            if not survived and record.out_week is None:
                record.out_week = int(week)
        out.append(record)
    return out


# ---- uncertainty ------------------------------------------------------------------------------------
def interval(values: list[float], groups: list[int]) -> tuple[float, float, float]:
    """(mean, low, high): 95% bootstrap over whole seasons."""
    if not values:
        return (float("nan"),) * 3
    rng = np.random.default_rng(SEED)
    by: dict[int, list[float]] = {}
    for g, v in zip(groups, values):
        by.setdefault(g, []).append(v)
    keys = sorted(by)
    draws = []
    for _ in range(DRAWS):
        picked = rng.choice(len(keys), size=len(keys))
        pool = [v for k in picked for v in by[keys[k]]]
        draws.append(statistics.fmean(pool))
    draws.sort()
    return statistics.fmean(values), draws[int(0.025 * DRAWS)], draws[int(0.975 * DRAWS) - 1]


# ---- the run -------------------------------------------------------------------------------------------
def run(first: int = FIRST, last: int = LAST) -> dict:
    notes = data.Notes()
    games = frame(first, last, notes)
    if games.empty:
        return {"error": "no games: the season archives or nflverse's file are not in data/"}
    made = forecasts(games)
    right = main_game(games, made)
    lined = games["pool_line"].notna().to_numpy()
    seasons = games["season"].to_numpy(int)
    weeks = games["week"].to_numpy(int)
    base_names = (MARKET, DEADEYE, CONSENSUS)
    common = np.all([~np.isnan(right[n]) for n in base_names], axis=0)

    def summary(mask: np.ndarray, name: str) -> dict:
        r = right[name][mask & ~np.isnan(right[name])]
        return {"games": int(len(r)), "right": int(r.sum()), "rate": float(r.mean()) if len(r) else None}

    result = {
        "seasons": [first, last],
        "games": int(len(games)),
        "line_from": games.groupby("season")["line_from"].agg(lambda s: "/".join(sorted(set(s)))).to_dict(),
        "notes": [f"{i.level}: {i.detail} ({i.rows})" for i in notes.items],
        "main": {}, "main_by_season": {}, "main_by_week": {}, "models": [],
        "big_loser": {}, "big_loser_by_season": {}, "suicide": {},
    }
    for name in base_names:
        result["main"][name] = {
            "straight": summary(common & ~lined, name), "line": summary(common & lined, name),
            "all": summary(common, name)}
    for name in (DEADEYE, CONSENSUS):
        diff = (right[name] - right[MARKET])[common]
        m, lo, hi = interval(list(diff), list(seasons[common]))
        result["main"][name]["vs_market"] = {"mean": m, "low": lo, "high": hi}
    for season in sorted(set(seasons)):
        mask = common & (seasons == season)
        result["main_by_season"][int(season)] = {n: summary(mask, n) for n in base_names}
    for week in sorted(set(weeks)):
        mask = common & (weeks == week)
        result["main_by_week"][int(week)] = {n: summary(mask, n) for n in base_names}
    for name in made:
        if name in base_names:
            continue
        both = ~np.isnan(right[name]) & ~np.isnan(right[MARKET])
        if both.sum() < MIN_MODEL_GAMES:
            continue
        diff = (right[name] - right[MARKET])[both]
        m, lo, hi = interval(list(diff), list(seasons[both]))
        result["models"].append({"model": name[len(data.MODEL):], "games": int(both.sum()),
                                 "rate": float(right[name][both].mean()),
                                 "market_rate": float(right[MARKET][both].mean()),
                                 "vs_market": {"mean": m, "low": lo, "high": hi},
                                 "seasons": int(len(set(seasons[both])))})
    result["models"].sort(key=lambda r: -r["vs_market"]["mean"])

    for name in base_names:
        weeks_ = big_losers(games, made[name])
        hits = [w.hits for w in weeks_]
        result["big_loser"][name] = {
            "weeks": len(weeks_), "points": int(sum(hits)), "per_week": statistics.fmean(hits) if hits else None,
            "per_pick": (sum(hits) / (3 * len(hits))) if hits else None,
            "at_least": {k: (sum(1 for h in hits if h >= k) / len(hits) if hits else None) for k in (1, 2, 3)},
            "expected_per_week": statistics.fmean(w.chance for w in weeks_) if weeks_ else None,
            "interval": interval([float(h) for h in hits], [w.season for w in weeks_])}
        result["big_loser_by_season"][name] = {
            s: statistics.fmean(w.hits for w in weeks_ if w.season == s)
            for s in sorted({w.season for w in weeks_})}

    for name in base_names:
        played = suicide(games, made[name])
        picks = [p for s in played for p in s.picks]
        alive_after = {}
        for k in range(1, 19):
            reached = [s for s in played if any(w >= k for w, *_ in s.picks)]
            if reached:
                alive_after[k] = sum(1 for s in reached if s.out_week is None or s.out_week > k) / len(reached)
        result["suicide"][name] = {
            "picks": len(picks), "won": sum(1 for p in picks if p[3]),
            "rate": statistics.fmean(1.0 if p[3] else 0.0 for p in picks) if picks else None,
            "expected": statistics.fmean(p[2] for p in picks) if picks else None,
            "ties": sum(s.ties for s in played),
            "out_week": {s.season: s.out_week for s in played},
            "alive_after": alive_after,
            "median_out": statistics.median([s.out_week or 19 for s in played]) if played else None,
        }
    return result


# ---- the report ---------------------------------------------------------------------------------------
def _pct(x) -> str:
    return "—" if x is None else f"{x:.1%}"


def report(result: dict) -> str:
    if "error" in result:
        return f"# A.C.Q.L. contests, replayed\n\n{result['error']}\n"
    first, last = result["seasons"]
    lines_ = [
        f"# A.C.Q.L. contests, replayed {first}-{last}",
        "",
        "Generated by `python -m acql.training contests`. Every pick is made from numbers posted before "
        "the game and is scored only afterwards; nothing is fitted on results. Intervals are 95% "
        "bootstrap intervals over whole seasons; one that includes 0 is not evidence either way.",
        "",
        "**What this rests on.** The Prediction Tracker's season archives, which are *undated* (when each "
        "forecast was posted is not in the files); the midweek line, or the last-updated one where a "
        "season has no midweek column; and, for line games, the commissioner's habit applied to the "
        "opening line - **a proxy for his real lines**, which exist for this season only. How a tie is "
        "graded is not recorded: ties are left out of the main game and count as a loss in the suicide "
        "pool, as the dashboard grades one today.",
        "",
        f"Games: {result['games']:,}. Line used by season: "
        + ", ".join(f"{s} {v}" for s, v in result["line_from"].items()) + ".",
        "",
        "## Main game",
        "",
        "| forecast | straight picks | rate | line games (proxy) | rate | all | rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in result["main"].items():
        s, l, a = m["straight"], m["line"], m["all"]
        lines_.append(f"| {name} | {s['right']}/{s['games']} | {_pct(s['rate'])} | {l['right']}/{l['games']} | "
                      f"{_pct(l['rate'])} | {a['right']}/{a['games']} | {_pct(a['rate'])} |")
    for name in (DEADEYE, CONSENSUS):
        v = result["main"][name]["vs_market"]
        lines_.append(f"\n- {name} minus the market, picks right per game: {v['mean']:+.2%} "
                      f"({v['low']:+.2%} to {v['high']:+.2%})")
    lines_ += ["", "### By season", "", "| season | games | market | Deadeye | consensus |", "|---|---|---|---|---|"]
    for season, row in result["main_by_season"].items():
        lines_.append(f"| {season} | {row[MARKET]['games']} | {_pct(row[MARKET]['rate'])} | "
                      f"{_pct(row[DEADEYE]['rate'])} | {_pct(row[CONSENSUS]['rate'])} |")
    lines_ += ["", "### By week", "", "| week | games | market | Deadeye | consensus |", "|---|---|---|---|---|"]
    for week, row in result["main_by_week"].items():
        lines_.append(f"| {week} | {row[MARKET]['games']} | {_pct(row[MARKET]['rate'])} | "
                      f"{_pct(row[DEADEYE]['rate'])} | {_pct(row[CONSENSUS]['rate'])} |")
    lines_ += ["", f"### Each computer model against the market (games it priced, {MIN_MODEL_GAMES}+)", "",
               "| model | seasons | games | its rate | market on the same games | difference (95%) |",
               "|---|---|---|---|---|---|"]
    for r in result["models"]:
        v = r["vs_market"]
        lines_.append(f"| {r['model']} | {r['seasons']} | {r['games']} | {_pct(r['rate'])} | "
                      f"{_pct(r['market_rate'])} | {v['mean']:+.2%} ({v['low']:+.2%} to {v['high']:+.2%}) |")
    better = [r for r in result["models"] if r["vs_market"]["low"] > 0]
    lines_.append("")
    lines_.append(f"Models whose interval is clear of 0 in the market's favour or theirs: "
                  f"{len(better)} better, {sum(1 for r in result['models'] if r['vs_market']['high'] < 0)} worse, "
                  f"of {len(result['models'])}. With this many models, one or two clearing 0 by chance is expected.")

    lines_ += ["", "## Big Loser (three a week, a point for each that loses by 15+)", "",
               "| forecast | weeks | points | per week (95%) | per pick | 1+ right | 2+ right | all 3 | curve expected per week |",
               "|---|---|---|---|---|---|---|---|---|"]
    for name, b in result["big_loser"].items():
        m, lo, hi = b["interval"]
        lines_.append(f"| {name} | {b['weeks']} | {b['points']} | {m:.2f} ({lo:.2f}-{hi:.2f}) | "
                      f"{_pct(b['per_pick'])} | {_pct(b['at_least'][1])} | {_pct(b['at_least'][2])} | "
                      f"{_pct(b['at_least'][3])} | {b['expected_per_week']:.2f} |")
    lines_ += ["", "Per season (points per week): " + "; ".join(
        f"{s} {v:.2f}" for s, v in result["big_loser_by_season"][DEADEYE].items()) + " (Deadeye).",
        "", "The curve's own expectation is in-sample (it was fitted on 1999-2025); it is shown to check its "
        "calibration, not as evidence."]

    lines_ += ["", "## Suicide pool (greedy: the unused team likeliest to survive, from week 1)", "",
               "| forecast | weekly picks | survived | rate | chance it expected | ties | median week out |",
               "|---|---|---|---|---|---|---|"]
    for name, s in result["suicide"].items():
        lines_.append(f"| {name} | {s['picks']} | {s['won']} | {_pct(s['rate'])} | {_pct(s['expected'])} | "
                      f"{s['ties']} | {s['median_out']} |")
    d = result["suicide"][DEADEYE]
    lines_ += ["", "Share of seasons still alive after each week (Deadeye): " + ", ".join(
        f"wk {k} {v:.0%}" for k, v in d["alive_after"].items()) + ".",
        "", "Week out by season (Deadeye; — = survived): " + ", ".join(
        f"{s} {w or '—'}" for s, w in d["out_week"].items()) + ".",
        "", "Every weekly pick is scored even after the week it would have gone out, so the win rate counts "
        "a full season of picks; the survival line is the real game.",
        "", "## Notes from reading the archives", ""] + [f"- {n}" for n in result["notes"]] + [""]
    return "\n".join(lines_)


def write(result: dict) -> tuple:
    where = data.folder()
    (where / "contests.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    md = where / "contests.md"
    md.write_text(report(result), encoding="utf-8")
    return md, where / "contests.json"
