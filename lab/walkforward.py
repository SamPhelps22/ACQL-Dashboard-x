"""Phase 2: walk-forward backtests on the historical dataset.

    python -m lab.walkforward        writes lab/reports/walkforward.md

Two questions, kept apart because their evidence is of different quality:

A. Current Deadeye vs the market alone, on identical games.
   Verified inputs only: every line, model forecast and weight was in hand
   at the week's lock (lab/history). Each game is priced by production's own
   code - `pricing.price` for Deadeye, `analytics.predict_margin` on the bare
   line for the market - and scored under the pool's real line from the
   commissioner's sheet. Today that is 2026 weeks 3-5 only.

B. A wider margin curve vs the current one, season by season.
   The candidate is production's own curve with a larger `sd` (the same way
   production already widens it for games the models disagree about). For
   each test season the width is chosen on earlier seasons only, then scored
   on that season. This uses nflverse's UNDATED lines, probably closing
   lines, and the backtest's proxy for where the commissioner would put a
   line (acql.backtest.pool_line) - so it is a best case under assumptions,
   and says so.

Predictions are made first, from the records alone; outcomes are read only
afterwards, to score them. Ties on straight-up games are left out of both:
how the pool grades a tie is not recorded (lab/history pool_rules).
"""

from __future__ import annotations

import math
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acql import analytics, predictions, pricing  # noqa: E402 - read-only reuse
from acql import backtest as proxy  # noqa: E402
from acql.models import Game  # noqa: E402

from lab.history import asof, build  # noqa: E402

REPORT_FILE = ROOT / "lab" / "reports" / "walkforward.md"

CURRENT_SD = analytics.SPREAD_SD
#: Widths tried for the candidate curve. predict_margin rounds sd to 0.1.
CANDIDATE_SDS = (8.7, 9.0, 9.3, 9.6, 9.9, 10.2, 10.5, 10.8, 11.1, 11.4, 11.7, 12.0)
TRAIN_FROM, TEST_FROM, TEST_TO = 2006, 2010, 2025
BOOTSTRAP, SEED = 2000, 2026
FLOOR = 1e-9


# ---- shared pieces ------------------------------------------------------------------
def game_for(home: str, away: str, pool_home_line: float | None) -> Game:
    """A slate game as production's pricing expects it, from team codes."""
    if pool_home_line is None:
        return Game(1, home, away)
    favourite = home if pool_home_line > 0 else away
    return Game(1, home, away, line=abs(pool_home_line), line_favourite=favourite)


def credited(home: str, away: str, pool_home_line: float | None, home_margin: int) -> str | None:
    """Who the pool credits, under its rule (analytics.line_need); None for a
    straight-up tie, whose grading is not recorded."""
    if pool_home_line is None:
        if home_margin == 0:
            return None
        return home if home_margin > 0 else away
    favourite, underdog = (home, away) if pool_home_line > 0 else (away, home)
    fav_margin = home_margin if pool_home_line > 0 else -home_margin
    return favourite if fav_margin >= analytics.line_need(abs(pool_home_line)) else underdog


def scored(pick: str, chance: float, winner: str) -> tuple[int, float]:
    """(right, log loss) of a pick that came with a chance of being right."""
    p = chance if pick == winner else 1 - chance
    return int(pick == winner), -math.log(max(p, FLOOR))


def bootstrap(diffs: list[float], groups: list | None = None, *, n: int = BOOTSTRAP,
              seed: int = SEED) -> tuple[float, float, float]:
    """(mean, low, high): a 95% percentile interval for the mean difference.

    With `groups`, whole groups are resampled together (a season, say), so
    games that share something are not counted as independent evidence.
    """
    if not diffs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    mean = statistics.fmean(diffs)
    if groups is None:
        draws = [statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n)]
    else:
        by = {}
        for g, d in zip(groups, diffs):
            by.setdefault(g, []).append(d)
        keys = sorted(by)
        draws = []
        for _ in range(n):
            picked = [d for k in rng.choices(keys, k=len(keys)) for d in by[k]]
            draws.append(statistics.fmean(picked))
    draws.sort()
    return mean, draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


def outcomes(conn: sqlite3.Connection) -> dict[str, int]:
    """game_id -> home margin. Read only to score predictions already made."""
    return dict(conn.execute("SELECT game_id, home_margin FROM outcomes"))


# ---- A: Deadeye vs the market on verified games ----------------------------------------
@dataclass(frozen=True)
class VerifiedPick:
    record_id: str
    game_id: str
    season: int
    week: int
    home: str
    away: str
    pool_home_line: float | None
    weight: float
    market: analytics.Prediction
    deadeye: analytics.Prediction
    deadeye_default: analytics.Prediction    # at the starting weight, as a sensitivity check


def verified_picks(conn: sqlite3.Connection) -> tuple[list[VerifiedPick], list[str]]:
    """Every eligible week-lock record, priced both ways. Reads no outcomes."""
    notes: list[str] = []
    slate_rows = conn.execute(
        "SELECT record_id, season, week FROM prediction_records WHERE cutoff_kind = 'week_lock' "
        "AND spread_home IS NOT NULL AND n_models > 0 ORDER BY record_id").fetchall()
    slates: dict[tuple[int, int], list[str]] = {}
    for rid, season, week in slate_rows:
        slates.setdefault((season, week), []).append(rid)
    weights = {(s, w): x for s, w, x in conn.execute("SELECT season, week, weight FROM production_weights")}
    out = []
    for (season, week), rids in sorted(slates.items()):
        forecasts = {rid: asof.production_forecast(conn, rid) for rid in rids}
        lean = predictions.home_lean(list(forecasts.values()))
        typical = predictions.typical_disagreement(list(forecasts.values()))
        weight = weights.get((season, week))
        if weight is None:
            notes.append(f"{season} week {week}: no production weight on record - left out")
            continue
        for rid in rids:
            row = conn.execute(
                "SELECT game_id, home_code, away_code, spread_home, pool_line_status, pool_line_home "
                "FROM prediction_records WHERE record_id = ?", (rid,)).fetchone()
            gid, home, away, spread, status, pool_home_line = row
            if status not in ("lined", "straight_up"):
                continue
            game = game_for(home, away, pool_home_line)

            def deadeye_at(w: float) -> analytics.Prediction:
                ctx = pricing.Context(week=week, forecasts={1: forecasts[rid]}, lean=lean,
                                      typical=typical, weight=w)
                return pricing.price(game, ctx).prediction()

            out.append(VerifiedPick(
                record_id=rid, game_id=gid, season=season, week=week, home=home, away=away,
                pool_home_line=pool_home_line, weight=weight,
                market=analytics.predict_margin(game, spread, sd=CURRENT_SD),
                deadeye=deadeye_at(weight),
                deadeye_default=deadeye_at(predictions.CONSENSUS_WEIGHT)))
    return out, notes


def score_verified(picks: list[VerifiedPick], margins: dict[str, int]) -> dict:
    rows, ties, unplayed = [], 0, 0
    for p in picks:
        if p.game_id not in margins:
            unplayed += 1
            continue
        winner = credited(p.home, p.away, p.pool_home_line, margins[p.game_id])
        if winner is None:
            ties += 1
            continue
        m_hit, m_ll = scored(p.market.pick, p.market.chance, winner)
        d_hit, d_ll = scored(p.deadeye.pick, p.deadeye.chance, winner)
        z_hit, z_ll = scored(p.deadeye_default.pick, p.deadeye_default.chance, winner)
        rows.append({"pick": p, "winner": winner, "market": (m_hit, m_ll), "deadeye": (d_hit, d_ll),
                     "default": (z_hit, z_ll), "differs": p.market.pick != p.deadeye.pick})
    return {"rows": rows, "ties": ties, "unplayed": unplayed}


# ---- B: the curve's width, walk-forward ------------------------------------------------
@dataclass(frozen=True)
class HistGame:
    game_id: str
    season: int
    week: int
    home: str
    away: str
    spread: float
    pool_home_line: float | None


def history_games(conn: sqlite3.Connection, first: int = TRAIN_FROM, last: int = TEST_TO) -> list[HistGame]:
    """Regular-season games with an undated nflverse spread, and the proxy pool line."""
    out = []
    for gid, season, week, home, away, spread in conn.execute(
            "SELECT g.game_id, g.season, g.week, g.home_code, g.away_code, s.home_value "
            "FROM games g JOIN odds_snapshots s ON s.game_id = g.game_id "
            "AND s.source_id = 'nflverse_games' AND s.market = 'spread' "
            "WHERE g.season BETWEEN ? AND ? ORDER BY g.season, g.week, g.game_id", (first, last)):
        line = proxy.pool_line(spread)
        out.append(HistGame(gid, season, week, home, away, spread,
                            None if line is None else (line if spread > 0 else -line)))
    return out


def price_history(games: list[HistGame], sds=CANDIDATE_SDS) -> dict[tuple[str, float], analytics.Prediction]:
    """(game, sd) -> production's prediction at that width. Reads no outcomes."""
    out = {}
    for g in games:
        game = game_for(g.home, g.away, g.pool_home_line)
        for sd in sds:
            out[(g.game_id, sd)] = analytics.predict_margin(game, g.spread, sd=sd)
    return out


def choose_sd(games: list[HistGame], priced: dict, margins: dict[str, int], sds=CANDIDATE_SDS) -> tuple[float, int]:
    """The width with the lowest average log loss over these games (ties: the current one)."""
    loss = {sd: 0.0 for sd in sds}
    n = 0
    for g in games:
        if g.game_id not in margins:
            continue
        winner = credited(g.home, g.away, g.pool_home_line, margins[g.game_id])
        if winner is None:
            continue
        n += 1
        for sd in sds:
            pred = priced[(g.game_id, sd)]
            loss[sd] += scored(pred.pick, pred.chance, winner)[1]
    if not n:
        return CURRENT_SD, 0
    return min(sds, key=lambda sd: (loss[sd] / n, abs(sd - CURRENT_SD))), n


def walk_forward(games: list[HistGame], priced: dict, margins: dict[str, int],
                 test_from: int = TEST_FROM, test_to: int = TEST_TO, sds=CANDIDATE_SDS) -> list[dict]:
    """Each test season scored with the width its earlier seasons chose."""
    seasons = []
    for season in range(test_from, test_to + 1):
        train = [g for g in games if g.season < season]          # earlier seasons ONLY
        sd, trained_on = choose_sd(train, priced, margins, sds)
        rows = []
        for g in games:
            if g.season != season or g.game_id not in margins:
                continue
            winner = credited(g.home, g.away, g.pool_home_line, margins[g.game_id])
            if winner is None:
                continue
            now, new = priced[(g.game_id, CURRENT_SD)], priced[(g.game_id, sd)]
            rows.append({"game": g, "current": scored(now.pick, now.chance, winner),
                         "candidate": scored(new.pick, new.chance, winner),
                         "changed": now.pick != new.pick})
        seasons.append({"season": season, "sd": sd, "trained_on": trained_on, "rows": rows})
    return seasons


def flips(sd: float, spreads=None, reach: int = 2) -> list[tuple[float, int, str, str]]:
    """Where a curve of width `sd` picks a different side from the current one.

    (spread, pool line, current pick, candidate pick) for every favourite's
    spread from 1 to 20 and every whole-number line within `reach` points of
    it. A width can only change a pick near 50%, so this is where it matters.
    """
    spreads = spreads or [x / 2 for x in range(2, 41)]
    out = []
    for spread in spreads:
        for line in range(max(1, math.floor(spread) - reach), math.ceil(spread) + reach + 1):
            game = game_for("fav", "dog", float(line))
            now = analytics.predict_margin(game, spread, sd=CURRENT_SD)
            new = analytics.predict_margin(game, spread, sd=sd)
            if now.pick != new.pick:
                out.append((spread, line, now.pick, new.pick))
    return out


# ---- report ----------------------------------------------------------------------------
def _pct(x: float) -> str:
    return f"{x:.1%}"


def _ci(mean: float, lo: float, hi: float, digits: int = 4, pct: bool = False) -> str:
    if pct:
        return f"{mean:+.1%} ({lo:+.1%} to {hi:+.1%})"
    return f"{mean:+.{digits}f} ({lo:+.{digits}f} to {hi:+.{digits}f})"


def report_lines(conn: sqlite3.Connection) -> list[str]:
    picks, notes = verified_picks(conn)
    margins = outcomes(conn)                                   # read only from here on
    a = score_verified(picks, margins)
    rows = a["rows"]
    lines = [
        "# Walk-forward backtest (phase 2)",
        "",
        "Generated by `python -m lab.walkforward` from `lab/data/history.db`. Every number is "
        "computed; nothing is estimated by hand. Intervals are 95% bootstrap intervals; a "
        "difference whose interval includes 0 is **not** evidence that either side is better.",
        "",
        "## A. Current Deadeye vs the market alone (verified inputs)",
        "",
        "Same games, same cutoff (the week's first kickoff), same pool line. Deadeye is "
        "production's `pricing.price` with the weight production held for that week; the market "
        "is `analytics.predict_margin` on the line alone. Scored against the commissioner's line "
        "from the pool's own sheet.",
        "",
    ]
    if not rows:
        lines += ["No eligible games.", ""]
    else:
        n = len(rows)
        lines += [f"Eligible and final: **{n} games** "
                  f"({a['ties']} straight-up ties left out, {a['unplayed']} not yet played).", ""]
        table = []
        for key, label in (("market", "Market alone"), ("deadeye", "Deadeye (held weight)"),
                           ("default", f"Deadeye at {predictions.CONSENSUS_WEIGHT} (sensitivity)")):
            hits = sum(r[key][0] for r in rows)
            table.append([label, f"{hits}/{n}", _pct(hits / n), f"{statistics.fmean(r[key][1] for r in rows):.4f}"])
        lines += ["| approach | right | rate | log loss (lower is better) |", "|---|---|---|---|"]
        lines += ["| " + " | ".join(r) + " |" for r in table]
        hit_diff = [r["deadeye"][0] - r["market"][0] for r in rows]
        ll_diff = [r["deadeye"][1] - r["market"][1] for r in rows]
        lines += ["",
                  f"- Deadeye minus market, picks right per game: {_ci(*bootstrap(hit_diff), pct=True)}",
                  f"- Deadeye minus market, log loss per game: {_ci(*bootstrap(ll_diff))} (negative favours Deadeye)",
                  f"- Games where the two picked different sides: {sum(r['differs'] for r in rows)}",
                  "", "By week:", "", "| season | week | games | weight | market right | Deadeye right | different picks |",
                  "|---|---|---|---|---|---|---|"]
        weeks = sorted({(r["pick"].season, r["pick"].week) for r in rows})
        for s, w in weeks:
            wk = [r for r in rows if (r["pick"].season, r["pick"].week) == (s, w)]
            lines.append(f"| {s} | {w} | {len(wk)} | {wk[0]['pick'].weight:g} | "
                         f"{sum(r['market'][0] for r in wk)} | {sum(r['deadeye'][0] for r in wk)} | "
                         f"{sum(r['differs'] for r in wk)} |")
        lines += ["", "Games in the same week share a slate, a lean and a weight, so these intervals "
                  "are if anything too narrow. Differences here are not mistaken for skill until "
                  "far more weeks are verified."]
    if notes:
        lines += [""] + [f"- {n}" for n in notes]

    games = history_games(conn)
    priced = price_history(games)
    seasons = walk_forward(games, priced, margins)
    allrows = [r for s in seasons for r in s["rows"]]
    lines += ["", "## B. A wider margin curve vs the current one (walk-forward, undated lines)", "",
              f"Candidate widths: {', '.join(str(s) for s in CANDIDATE_SDS)} (current "
              f"{CURRENT_SD}). For each season from {TEST_FROM} to {TEST_TO}, the width with the "
              f"lowest log loss over seasons {TRAIN_FROM} up to the season before is chosen, then "
              f"scored on that season against the current curve.", "",
              "**Assumptions this rests on:** the spreads are nflverse's undated lines (probably "
              "closing, which is sharper than the Thursday line Deadeye picks from); the pool line "
              "is the backtest's proxy for the commissioner's habit (next whole number above a "
              "spread of 6.5 or more), not his real lines; straight-up ties are left out.", "",
              "| season | chosen sd | games | current right | candidate right | picks changed | "
              "log loss current | log loss candidate |", "|---|---|---|---|---|---|---|---|"]
    for s in seasons:
        r = s["rows"]
        if not r:
            continue
        lines.append(
            f"| {s['season']} | {s['sd']} | {len(r)} | {sum(x['current'][0] for x in r)} | "
            f"{sum(x['candidate'][0] for x in r)} | {sum(x['changed'] for x in r)} | "
            f"{statistics.fmean(x['current'][1] for x in r):.4f} | "
            f"{statistics.fmean(x['candidate'][1] for x in r):.4f} |")
    if allrows:
        ll = [x["candidate"][1] - x["current"][1] for x in allrows]
        hits = [x["candidate"][0] - x["current"][0] for x in allrows]
        groups = [x["game"].season for x in allrows]
        changed = [x for x in allrows if x["changed"]]
        lines += ["",
                  f"All {len(allrows)} test games:",
                  "",
                  f"- Candidate minus current, log loss per game: {_ci(*bootstrap(ll))} by game; "
                  f"{_ci(*bootstrap(ll, groups))} resampling whole seasons (negative favours the candidate)",
                  f"- Candidate minus current, picks right per game: {_ci(*bootstrap(hits), pct=True)} by game; "
                  f"{_ci(*bootstrap(hits, groups), pct=True)} resampling whole seasons",
                  f"- Picks the candidate changed: {len(changed)} of {len(allrows)}; on those, candidate "
                  f"right {sum(x['candidate'][0] for x in changed)}, current right "
                  f"{sum(x['current'][0] for x in changed)}"]
    if seasons:
        widest = max(s["sd"] for s in seasons)
        changes = flips(widest)
        lines += ["", f"### Where width {widest} would pick differently from {CURRENT_SD}", "",
                  "Every favourite's spread from 1 to 20 against every whole-number pool line within "
                  "2 points of it. The proxy line above always sits above the spread, so it can never "
                  "show a flip; the commissioner's real lines can sit at or below it.", ""]
        if changes:
            lines += ["| favourite's spread | pool line | current takes | wider takes |", "|---|---|---|---|"]
            lines += [f"| {sp} | {ln} | {a} | {b} |" for sp, ln, a, b in changes]
        else:
            lines += ["None: within this range the wider curve never changes a pick."]
        real = conn.execute(
            "SELECT COUNT(*), SUM(ABS(r.pool_line_home) <= ABS(r.spread_home_unverified)) "
            "FROM prediction_records r WHERE r.cutoff_kind = 'kickoff' AND r.pool_line_status = 'lined' "
            "AND r.spread_home_unverified IS NOT NULL").fetchone()
        lines += ["", f"On the pool's real sheets, {real[1] or 0} of {real[0]} lined games had the "
                  f"commissioner's line at or below the (undated) market spread."]
    lines += ["", "### Each width over all test seasons (descriptive, not walk-forward)", "",
              "| sd | games | right | log loss |", "|---|---|---|---|"]
    test_games = [g for g in games if TEST_FROM <= g.season <= TEST_TO and g.game_id in margins]
    for sd in CANDIDATE_SDS:
        hits, losses = [], []
        for g in test_games:
            winner = credited(g.home, g.away, g.pool_home_line, margins[g.game_id])
            if winner is None:
                continue
            h, loss = scored(priced[(g.game_id, sd)].pick, priced[(g.game_id, sd)].chance, winner)
            hits.append(h)
            losses.append(loss)
        lines.append(f"| {sd} | {len(hits)} | {sum(hits)} | {statistics.fmean(losses):.4f} |")
    return lines + [""]


def main() -> int:
    if not build.DB_FILE.exists():
        print("lab/data/history.db is missing - run: python -m lab.history.build")
        return 1
    conn = sqlite3.connect(f"{build.DB_FILE.resolve().as_uri()}?mode=ro", uri=True)
    try:
        text = "\n".join(report_lines(conn))
    finally:
        conn.close()
    REPORT_FILE.write_text(text, encoding="utf-8")
    print(f"report: {REPORT_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
