"""Weekly learning loop: grade a submitted (or latest) run against results,
compare with a market-only sheet for the same slate, and classify each miss.

Miss categories (first matching rule wins), designed to avoid over-reacting to
single upsets:
  data_issue        - the run had no/stale odds or an unknown starting QB
  lineup_change     - the QB who actually started differs from the one assumed
  market_moved      - the closing line moved >= 5 points toward the actual winner
                      after our odds snapshot
  model_deviation   - our pick differed from the market favourite and lost
  coin_flip         - pick probability < 0.60: an expected miss
  variance          - a confident pick lost with no data problem; one upset is not
                      evidence of a systematic weakness (see calibration check)
Systematic weaknesses are judged only from the calibration table across many
weeks (bucket observed rate outside a ~95% binomial band).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .confidence import ScoringRules, allocate, grade_sheet
from .evaluation import prob_metrics
from .models.market import moneyline_home_probability, spread_home_probability
from .reports import load_reports


def _run_for_week(con, season: int, week: int) -> str | None:
    row = con.execute("""SELECT run_id FROM prediction_runs WHERE season=? AND week=?
                         ORDER BY frozen DESC, frozen_at DESC NULLS LAST, generated_at DESC LIMIT 1""",
                      [season, week]).fetchone()
    return row[0] if row else None


def _closing_probs(con, game_ids: list[str]) -> pd.Series:
    if not game_ids:
        return pd.Series(dtype=float)
    q = f"""SELECT game_id, home_moneyline, away_moneyline, home_spread FROM odds_snapshots
            WHERE is_closing AND game_id IN ({','.join('?' * len(game_ids))})"""
    df = con.execute(q, game_ids).df()
    if df.empty:
        return pd.Series(dtype=float)
    p = [moneyline_home_probability(r.home_moneyline, r.away_moneyline) for r in df.itertuples()]
    p = [x if not np.isnan(x) else spread_home_probability(s) for x, s in zip(p, df.home_spread)]
    return pd.Series(p, index=df.game_id).groupby(level=0).mean()


def review_week(con, cfg: dict, season: int, week: int, run_id: str | None = None) -> dict:
    run_id = run_id or _run_for_week(con, season, week)
    if run_id is None:
        raise RuntimeError(f"No prediction run for {season} week {week}")
    picks = con.execute("SELECT * FROM predictions WHERE run_id = ?", [run_id]).df()
    games = con.execute("SELECT game_id, home_score, away_score, game_status, home_qb_id, away_qb_id "
                        "FROM games WHERE season=? AND week=?", [season, week]).df()
    rules = ScoringRules.from_config(cfg["pool"])
    graded = grade_sheet(picks, games[["game_id", "home_score", "away_score", "game_status"]], rules)
    done = graded[graded.actual_result.isin(["win", "loss", "tie"])].copy()
    if done.empty:
        return {"run_id": run_id, "season": season, "week": week, "status": "no completed games yet"}
    hs, as_ = done.home_score.astype(float), done.away_score.astype(float)
    done["home_result"] = np.where(hs > as_, 1.0, np.where(hs < as_, 0.0, 0.5))
    closing = _closing_probs(con, done.game_id.tolist())
    reports = load_reports(con, run_id)
    g = games.set_index("game_id")
    causes = []
    for r in done.itertuples():
        if r.actual_result != "loss":
            causes.append("")
            continue
        rep = reports.get(r.game_id, {})
        assumed = rep.get("qb_ids", {})
        actual = {r.home_team: g.loc[r.game_id, "home_qb_id"], r.away_team: g.loc[r.game_id, "away_qb_id"]}
        winner_home = r.home_result == 1.0
        close = closing.get(r.game_id, np.nan)
        snap = r.market_home_probability
        if r.odds_status in ("missing", "stale") or "QB_UNKNOWN" in str(r.data_flags):
            causes.append("data_issue")
        elif assumed and any(assumed.get(t) and actual.get(t) and assumed.get(t) != actual.get(t) for t in actual):
            causes.append("lineup_change")
        elif not np.isnan(close) and not pd.isna(snap) and ((close - snap) if winner_home else (snap - close)) >= 0.05:
            causes.append("market_moved")
        elif not pd.isna(snap) and (snap >= 0.5) != (r.selected_team == r.home_team):
            causes.append("model_deviation")
        elif r.selected_team_probability < 0.60:
            causes.append("coin_flip")
        else:
            causes.append("variance")
    done["miss_cause"] = causes
    # market-only sheet on the same slate for comparison
    mk = picks.assign(_p=picks.market_home_probability)
    mk_alloc = allocate(mk, rules, prob_col="_p")
    mk_graded = grade_sheet(mk_alloc, games[["game_id", "home_score", "away_score", "game_status"]], rules)
    model_m = prob_metrics(done.home_result.to_numpy(), done.blended_home_probability.to_numpy())
    market_m = prob_metrics(done.home_result.to_numpy(), done.market_home_probability.to_numpy())
    return {
        "run_id": run_id, "season": season, "week": week,
        "games_graded": int(len(done)),
        "points": float(done.points_earned.sum()),
        "market_sheet_points": float(mk_graded[mk_graded.game_id.isin(done.game_id)].points_earned.sum()),
        "expected_points": float(done.expected_points.sum()),
        "model": model_m, "market": market_m,
        "miss_causes": done.loc[done.miss_cause != "", "miss_cause"].value_counts().to_dict(),
        "games": done[["game_id", "away_team", "home_team", "selected_team", "selected_team_probability",
                       "confidence_points", "points_earned", "actual_result", "market_home_probability",
                       "blended_home_probability", "miss_cause"]].assign(
            closing_home_probability=done.game_id.map(closing)).to_dict(orient="records"),
    }


def systematic_check(con, cfg: dict) -> pd.DataFrame:
    """Calibration of submitted probabilities across all graded weeks.

    Flags buckets whose observed win rate falls outside an approximate 95% band;
    only these (not individual upsets) justify revisiting the model.
    """
    df = con.execute("""SELECT p.selected_team_probability AS p, r.actual_result
                        FROM pool_results r JOIN predictions p ON p.run_id = r.run_id AND p.game_id = r.game_id
                        WHERE r.actual_result IN ('win', 'loss')""").df()
    if df.empty:
        return df
    df["won"] = (df.actual_result == "win").astype(float)
    df["bucket"] = pd.cut(df.p, [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], include_lowest=True)
    t = df.groupby("bucket", observed=True).agg(games=("won", "size"), predicted=("p", "mean"),
                                                observed=("won", "mean")).reset_index()
    se = np.sqrt(t.predicted * (1 - t.predicted) / t.games)
    t["flag"] = np.where((t.games >= 20) & ((t.observed - t.predicted).abs() > 1.96 * se),
                         "investigate", "consistent with noise")
    t["bucket"] = t.bucket.astype(str)
    return t
