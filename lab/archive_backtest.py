"""Phase 3: Deadeye vs the market alone over every season the Prediction
Tracker's season archives cover.

    python -m lab.archive_backtest      writes lab/reports/archive_backtest.md

The question phase 2 could only ask of 45 games: does nudging the line toward
the computer models (production's `pricing.price`) beat the line alone? Here
it is asked of every regular-season game from 2010 on, three ways, on
identical games:

  market         `analytics.predict_margin` on the line alone
  Deadeye 0.33   `pricing.price` at production's starting weight
  Deadeye fitted `pricing.price` at the weight production's own fit
                 (`predictions.replay_week` + `fit_from`) gives each week from
                 that season's earlier weeks only, as production does live

Everything comes from the season archives (lab.history.build
import_pt_archives), which are UNDATED: the site does not say when each number
was posted. The line used is the archive's midweek line, which matched the
line Deadeye actually priced 2026 week 3 from (the archive's `line` is a later
update); 2010-2012 have no midweek column, so their latest line is used and
the table says so. The pool line is a proxy (acql.backtest.pool_line, set
against the opening line, as the commissioner sets his). Results are read
only after every game is priced.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acql import analytics, predictions, pricing  # noqa: E402 - read-only reuse
from acql import backtest as proxy  # noqa: E402

from lab import walkforward as wf  # noqa: E402
from lab.history import asof, build  # noqa: E402

REPORT_FILE = ROOT / "lab" / "reports" / "archive_backtest.md"
FIRST, LAST = 2010, 2026
START = predictions.CONSENSUS_WEIGHT


# ---- the games, as the archives give them ------------------------------------------------
@dataclass(frozen=True)
class ArchiveGame:
    game_id: str
    season: int
    week: int
    home: str
    away: str
    forecast: predictions.Forecast     # market = the line used; opening = the archive's opener
    line_used: str                     # "midweek" or "latest"
    pool_home_line: float | None       # the proxy pool line, home side
    close: float | None                # nflverse's undated (probably closing) spread


def load(conn: sqlite3.Connection, first: int = FIRST, last: int = LAST) -> list[ArchiveGame]:
    """Every game with an archive line and at least one model. Reads no outcomes."""
    lines: dict[str, dict[str, float]] = {}
    for gid, timing, value in conn.execute(
            "SELECT game_id, timing, home_value FROM odds_snapshots WHERE source_id LIKE 'ptarchive:%' "
            "AND market = 'spread' AND timing IN (?, ?, ?)", asof.ARCHIVE_TIMINGS):
        lines.setdefault(gid, {})[timing] = value
    models: dict[str, list[tuple[str, float]]] = {}
    for gid, model, margin in conn.execute(
            "SELECT game_id, model, home_margin FROM model_forecasts WHERE source_id LIKE 'ptarchive:%'"):
        models.setdefault(gid, []).append((model, margin))
    close = dict(conn.execute("SELECT game_id, home_value FROM odds_snapshots "
                              "WHERE source_id = 'nflverse_games' AND market = 'spread'"))
    out = []
    for gid, season, week, home, away, neutral in conn.execute(
            "SELECT game_id, season, week, home_code, away_code, neutral FROM games "
            "WHERE season BETWEEN ? AND ? ORDER BY season, week, game_id", (first, last)):
        found = lines.get(gid, {})
        midweek, latest = found.get("archive_midweek"), found.get("archive_latest")
        market = midweek if midweek is not None else latest
        if market is None or not models.get(gid):
            continue
        opening = found.get("archive_opening")
        set_against = opening if opening is not None else market
        line = proxy.pool_line(set_against)
        forecast = predictions.Forecast(
            road=away, home=home, market=market, opening=opening,
            opinions=tuple(m for _, m in sorted(models[gid])), neutral=bool(neutral))
        out.append(ArchiveGame(gid, season, week, home, away, forecast,
                               "midweek" if midweek is not None else "latest",
                               None if line is None else (line if set_against > 0 else -line),
                               close.get(gid)))
    return out


def weeks_of(games: list[ArchiveGame]) -> dict[tuple[int, int], list[ArchiveGame]]:
    out: dict[tuple[int, int], list[ArchiveGame]] = {}
    for g in games:
        out.setdefault((g.season, g.week), []).append(g)
    return out


# ---- pricing ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Priced:
    game: ArchiveGame
    weight: float                     # the fitted weight this week was priced with
    market: analytics.Prediction
    fixed: analytics.Prediction       # Deadeye at START
    fitted: analytics.Prediction      # Deadeye at `weight`
    fixed_margin: float
    fitted_margin: float


def price_week(games: list[ArchiveGame], weight: float) -> list[Priced]:
    """One week's slate, priced by production's code. Reads no outcomes."""
    forecasts = [g.forecast for g in games]
    lean = predictions.home_lean(forecasts)
    typical = predictions.typical_disagreement(forecasts)
    out = []
    for g in games:
        slate_game = wf.game_for(g.home, g.away, g.pool_home_line)

        def deadeye(w: float) -> pricing.Price:
            ctx = pricing.Context(week=g.week, forecasts={1: g.forecast}, lean=lean,
                                  typical=typical, weight=w)
            return pricing.price(slate_game, ctx)

        fixed, fitted = deadeye(START), deadeye(weight)
        out.append(Priced(g, weight, analytics.predict_margin(slate_game, g.forecast.market,
                                                              sd=analytics.SPREAD_SD),
                          fixed.prediction(), fitted.prediction(), fixed.margin, fitted.margin))
    return out


def graded_slate(games: list[ArchiveGame], margins: dict[str, int]):
    """A finished week as production's weight fit sees one: Game rows with the
    pool's winner filled in (straight-up ties left blank, so they are skipped)."""
    slate, forecasts = [], []
    for index, g in enumerate(games, start=1):
        if g.game_id not in margins:
            continue
        winner = wf.credited(g.home, g.away, g.pool_home_line, margins[g.game_id]) or ""
        base = wf.game_for(g.home, g.away, g.pool_home_line)
        slate.append(replace(base, index=index, winner=winner))
        forecasts.append(g.forecast)
    return slate, forecasts


def walk_forward(games: list[ArchiveGame], margins: dict[str, int]) -> list[Priced]:
    """Every week priced with the weight fitted on its own season's EARLIER weeks.

    Production does exactly this live (pricing.model_weight(before=week)),
    starting each season from the starting weight. A week's own results are
    only replayed after it has been priced, for the weeks that follow.
    """
    out: list[Priced] = []
    by_week = weeks_of(games)
    for season in sorted({s for s, _ in by_week}):
        replays: list[predictions.WeekReplay] = []
        for week in sorted(w for s, w in by_week if s == season):
            fit = predictions.fit_from(replays) if replays else None
            weight = fit.weight if fit else START
            out.extend(price_week(by_week[(season, week)], weight))
            slate, forecasts = graded_slate(by_week[(season, week)], margins)    # after pricing
            replays.append(predictions.replay_week(week, slate, forecasts))
    return out


# ---- scoring ------------------------------------------------------------------------------
def score(priced: list[Priced], margins: dict[str, int]) -> list[dict]:
    """Per game: pool-proxy right/log loss, squared margin error, and the side
    taken against nflverse's closing number (None for no side or a push)."""
    rows = []
    for p in priced:
        g = p.game
        if g.game_id not in margins:
            continue
        actual = margins[g.game_id]
        winner = wf.credited(g.home, g.away, g.pool_home_line, actual)
        row = {"game": g, "weight": p.weight, "actual": actual, "winner": winner}
        for key, pred, margin in (("market", p.market, g.forecast.market),
                                  ("fixed", p.fixed, p.fixed_margin),
                                  ("fitted", p.fitted, p.fitted_margin)):
            row[key] = None if winner is None else wf.scored(pred.pick, pred.chance, winner)
            row[f"{key}_sq"] = (margin - actual) ** 2
            row[f"{key}_ats"] = against_close(margin, g.close, actual)
        row["differs"] = winner is not None and p.market.pick != p.fitted.pick
        rows.append(row)
    return rows


def against_close(expected: float, close: float | None, actual: int) -> int | None:
    """1 if the side `expected` takes against the closing spread covered, 0 if
    not, None when it takes no side or the game landed on the number."""
    if close is None or abs(expected - close) < 1e-9 or actual == close:
        return None
    return int((expected > close) == (actual > close))


HINDSIGHT_WEIGHTS = (0.0, 0.1, 0.2, 0.33, 0.4, 0.5, 0.6)


def hindsight(games: list[ArchiveGame], margins: dict[str, int],
              weights=HINDSIGHT_WEIGHTS) -> list[tuple[float, int, float, float]]:
    """(weight, right, log loss, margin RMSE) for each fixed weight, every season pooled."""
    out = []
    by_week = weeks_of(games)
    for weight in weights:
        hits, losses, squares = 0, [], []
        for week_games in by_week.values():
            for p in price_week(week_games, weight):
                if p.game.game_id not in margins:
                    continue
                actual = margins[p.game.game_id]
                squares.append((p.fitted_margin - actual) ** 2)
                winner = wf.credited(p.game.home, p.game.away, p.game.pool_home_line, actual)
                if winner is None:
                    continue
                hit, loss = wf.scored(p.fitted.pick, p.fitted.chance, winner)
                hits += hit
                losses.append(loss)
        out.append((weight, hits, _mean(losses), math.sqrt(_mean(squares))))
    return out


# ---- fidelity: the archive against what production actually priced ------------------------
def fidelity(conn: sqlite3.Connection, games: list[ArchiveGame]) -> list[dict]:
    """Weeks with both a verified record (the weekly file production imported)
    and an archive row: Deadeye's margin from each, at the same weight."""
    archive = {g.game_id: g for g in games}
    weeks: dict[tuple[int, int], list[str]] = {}
    for rid, gid, season, week in conn.execute(
            "SELECT record_id, game_id, season, week FROM prediction_records WHERE cutoff_kind = 'week_lock' "
            "AND spread_home IS NOT NULL AND n_models > 0 ORDER BY record_id"):
        if gid in archive:
            weeks.setdefault((season, week), []).append(rid)
    out = []
    for (season, week), rids in sorted(weeks.items()):
        verified = {rid.split("|")[0]: asof.production_forecast(conn, rid) for rid in rids}
        all_verified = [asof.production_forecast(conn, rid) for rid, in conn.execute(
            "SELECT record_id FROM prediction_records WHERE cutoff_kind = 'week_lock' AND season = ? "
            "AND week = ? AND spread_home IS NOT NULL AND n_models > 0", (season, week))]
        lean_v = predictions.home_lean(all_verified)
        typical_v = predictions.typical_disagreement(all_verified)
        week_games = [g for g in games if (g.season, g.week) == (season, week)]
        lean_a = predictions.home_lean([g.forecast for g in week_games])
        typical_a = predictions.typical_disagreement([g.forecast for g in week_games])
        for gid, f in sorted(verified.items()):
            a = archive[gid]
            game = wf.game_for(a.home, a.away, None)
            mine = pricing.price(game, pricing.Context(week, {1: f}, lean_v, typical_v, START)).margin
            theirs = pricing.price(game, pricing.Context(week, {1: a.forecast}, lean_a, typical_a,
                                                         START)).margin
            out.append({"game_id": gid, "season": season, "week": week, "verified_line": f.market,
                        "archive_line": a.forecast.market, "verified_models": f.models,
                        "archive_models": a.forecast.models, "verified": mine, "archive": theirs})
    return out


# ---- report -------------------------------------------------------------------------------
def _mean(xs) -> float:
    xs = list(xs)
    return statistics.fmean(xs) if xs else float("nan")


def report_lines(conn: sqlite3.Connection) -> list[str]:
    games = load(conn)
    margins = wf.outcomes(conn)
    priced = walk_forward(games, margins)
    rows = score(priced, margins)
    graded = [r for r in rows if r["winner"] is not None]
    seasons = sorted({r["game"].season for r in rows})
    lines = [
        "# Deadeye vs the market, 2010-2026 (phase 3)",
        "",
        "Generated by `python -m lab.archive_backtest` from `lab/data/history.db`. Every number is "
        "computed; nothing is estimated by hand. Intervals are 95% bootstrap intervals, by game and "
        "by whole season; a difference whose interval includes 0 is **not** evidence either way.",
        "",
        "**What this rests on.** The Prediction Tracker's season archives (`nfl10.csv` ... "
        "`nfl26.csv`, downloaded by Sam on 2026-10-12). They are **undated**: the files do not say "
        "when each forecast was posted or whether it was revised. The line is the archive's "
        "*midweek* line (2010-2012 have none, so their latest line is used). The pool line is a "
        "**proxy** for the commissioner's (the next whole number above an opening spread of 6.5 or "
        "more), not his real lines. Deadeye is production's own `pricing.price`, unchanged; "
        "production counts the file's `linemidweek` column among the models, and so does this.",
        "",
        f"Games priced: **{len(rows)}** with a result; **{len(graded)}** graded under the proxy pool "
        f"line ({len(rows) - len(graded)} straight-up ties left out).",
        "",
        "## All seasons",
        "",
        "| approach | right | rate | log loss | margin RMSE | vs closing line |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in (("market", "Market alone"), ("fixed", f"Deadeye at {START}"),
                       ("fitted", "Deadeye, weight fitted as production does")):
        hits = sum(r[key][0] for r in graded)
        ats = [r[f"{key}_ats"] for r in rows if r[f"{key}_ats"] is not None]
        lines.append(f"| {label} | {hits}/{len(graded)} | {hits / len(graded):.1%} | "
                     f"{_mean(r[key][1] for r in graded):.4f} | "
                     f"{math.sqrt(_mean(r[f'{key}_sq'] for r in rows)):.3f} | "
                     f"{sum(ats)}/{len(ats)} ({_mean(ats):.1%}) |")
    groups = [r["game"].season for r in graded]
    sq_groups = [r["game"].season for r in rows]
    lines += ["", "Differences (Deadeye minus market; negative log loss and squared error favour Deadeye):", ""]
    for key, label in (("fixed", f"Deadeye at {START}"), ("fitted", "Deadeye fitted")):
        ll = [r[key][1] - r["market"][1] for r in graded]
        hit = [r[key][0] - r["market"][0] for r in graded]
        sq = [r[f"{key}_sq"] - r["market_sq"] for r in rows]
        lines += [f"- **{label}**",
                  f"  - log loss per game: {wf._ci(*wf.bootstrap(ll))} by game; "
                  f"{wf._ci(*wf.bootstrap(ll, groups))} by season",
                  f"  - picks right per game: {wf._ci(*wf.bootstrap(hit), pct=True)} by game; "
                  f"{wf._ci(*wf.bootstrap(hit, groups), pct=True)} by season",
                  f"  - squared margin error per game: {wf._ci(*wf.bootstrap(sq), digits=2)} by game; "
                  f"{wf._ci(*wf.bootstrap(sq, sq_groups), digits=2)} by season"]
        ats = [r[f"{key}_ats"] for r in rows if r[f"{key}_ats"] is not None]
        if ats:
            ats_groups = [r["game"].season for r in rows if r[f"{key}_ats"] is not None]
            lo_hi = wf.bootstrap(ats, ats_groups)
            lines.append(f"  - side taken against nflverse's closing spread covered: {len(ats)} games, "
                         f"{_mean(ats):.1%} ({lo_hi[1]:.1%} to {lo_hi[2]:.1%} by season); 50% is no edge")
    changed = [r for r in graded if r["differs"]]
    lines += ["",
              f"Picks where fitted Deadeye and the market took different sides: {len(changed)} of "
              f"{len(graded)}; Deadeye right {sum(r['fitted'][0] for r in changed)}, market right "
              f"{sum(r['market'][0] for r in changed)}.",
              "",
              "## Season by season",
              "",
              "| season | line used | games | market right | Deadeye 0.33 right | Deadeye fitted right | "
              "different picks | log loss market | log loss fitted | RMSE market | RMSE fitted | "
              "weight range |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for season in seasons:
        s_all = [r for r in rows if r["game"].season == season]
        s = [r for r in s_all if r["winner"] is not None]
        if not s:
            continue
        used = sorted({r["game"].line_used for r in s_all})
        ws = [r["weight"] for r in s_all]
        lines.append(
            f"| {season} | {'/'.join(used)} | {len(s)} | {sum(r['market'][0] for r in s)} | "
            f"{sum(r['fixed'][0] for r in s)} | {sum(r['fitted'][0] for r in s)} | "
            f"{sum(r['differs'] for r in s)} | {_mean(r['market'][1] for r in s):.4f} | "
            f"{_mean(r['fitted'][1] for r in s):.4f} | "
            f"{math.sqrt(_mean(r['market_sq'] for r in s_all)):.2f} | "
            f"{math.sqrt(_mean(r['fitted_sq'] for r in s_all)):.2f} | {min(ws):g}-{max(ws):g} |")

    lines += ["", "## Any weight, with hindsight (descriptive, not walk-forward)", "",
              "Every game priced at each fixed weight, all seasons pooled. Choosing the best row "
              "here would use the results it is scored on, so it can only say whether *any* "
              "nudge was there to be found.", "",
              "| weight | right | log loss | margin RMSE |", "|---|---|---|---|"]
    for weight, hits, loss, rmse in hindsight(games, margins):
        lines.append(f"| {weight:g} | {hits}/{len(graded)} | {loss:.4f} | {rmse:.3f} |")

    check = fidelity(conn, games)
    lines += ["", "## Does the archive match what production saw?", ""]
    if not check:
        lines.append("No week has both a weekly file production imported and an archive row.")
    else:
        same_line = sum(abs(c["verified_line"] - c["archive_line"]) < 1e-9 for c in check)
        gaps = [abs(c["verified"] - c["archive"]) for c in check]
        weeks = sorted({(c["season"], c["week"]) for c in check})
        lines += [f"Weeks with both: {', '.join(f'{s} week {w}' for s, w in weeks)} ({len(check)} games). "
                  f"Deadeye priced at {START} from each:", "",
                  f"- the archive's midweek line equals the line production priced from on "
                  f"{same_line} of {len(check)} games;",
                  f"- models per game: production {min(c['verified_models'] for c in check)}-"
                  f"{max(c['verified_models'] for c in check)}, archive "
                  f"{min(c['archive_models'] for c in check)}-{max(c['archive_models'] for c in check)};",
                  f"- Deadeye's expected margin differs by {_mean(gaps):.2f} points on average "
                  f"(largest {max(gaps):.2f}).",
                  "",
                  "One week is all that can be checked, so how well the archive stands in for what "
                  "Deadeye would have seen in earlier seasons is an assumption, not a measurement."]
    lines += ["", "## Reading this", "",
              "- This is the first test of the nudge on more than one season. It is still not a "
              "verified backtest: undated inputs, a proxy pool line, and a midweek line that may not "
              "be the line at the pool's deadline.",
              "- Production is unchanged. Nothing here is promoted; any change to the nudge needs "
              "Sam's approval (CLAUDE.md).", ""]
    return lines


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
