"""Challengers to Deadeye's nudge, on the games phase 3 priced.

    python -m lab.challengers        writes lab/reports/challengers.md

Phase 3 found that production's nudge (the market moved a third of the way
toward the trimmed model consensus) does no better than the market alone.
These ask whether the models carry anything the market lacks when they are
used differently. Both start from the same midweek market line and add a
correction learned from EARLIER SEASONS ONLY:

  best model   The one model whose own nudge, fitted on earlier seasons,
               predicted margins best there. Its weight is fitted too.
  blend        A ridge regression of what the market got wrong (result minus
               line) on every model's disagreement with the line. The penalty
               is chosen by fitting on all but the latest training season and
               scoring on that one, then refitted on them all.

Each is scored on identical games against the market alone and Deadeye as it
runs (lab.archive_backtest). Inputs are the undated season archives, and the
pool line is the proxy, exactly as in phase 3.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acql import analytics  # noqa: E402 - read-only reuse

from lab import archive_backtest as ab  # noqa: E402
from lab import walkforward as wf  # noqa: E402
from lab.history import build  # noqa: E402

REPORT_FILE = ROOT / "lab" / "reports" / "challengers.md"
TEST_FROM = 2013                 # three seasons to learn from first
MIN_GAMES = 500                  # a model needs this many training games to be used
#: The market columns in the files: never a model here (production counts
#: linemidweek as one; a challenger has no reason to).
NOT_MODELS = {"linemidweek"}
PENALTIES = (10.0, 100.0, 1_000.0, 10_000.0, 100_000.0, 1_000_000.0, 10_000_000.0)


def named_models(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """game_id -> {model: home margin} from the season archives."""
    out: dict[str, dict[str, float]] = {}
    for gid, model, margin in conn.execute(
            "SELECT game_id, model, home_margin FROM model_forecasts WHERE source_id LIKE 'ptarchive:%'"):
        if model not in NOT_MODELS:
            out.setdefault(gid, {})[model] = margin
    return out


# ---- the two challengers --------------------------------------------------------------
@dataclass(frozen=True)
class BestModel:
    model: str | None
    weight: float
    train_rmse: float


def fit_best_model(train: list[ab.ArchiveGame], models: dict[str, dict[str, float]],
                   margins: dict[str, int], latest_season: int) -> BestModel:
    """The model whose fitted nudge has the lowest squared error over `train`.

    Only models with MIN_GAMES training games, and still published in the
    latest training season, are considered. A game the model skipped counts
    as the market alone, so a model is not flattered by the games it chose.
    """
    rows = [(g, margins[g.game_id] - g.forecast.market) for g in train if g.game_id in margins]
    if not rows:
        return BestModel(None, 0.0, float("nan"))
    base = sum(r * r for _, r in rows)
    counts: dict[str, int] = {}
    current: set[str] = set()
    for g, _ in rows:
        for m in models.get(g.game_id, {}):
            if m in NOT_MODELS:
                continue
            counts[m] = counts.get(m, 0) + 1
            if g.season == latest_season:
                current.add(m)
    best = BestModel(None, 0.0, math.sqrt(base / len(rows)))
    for m in sorted(counts):
        if counts[m] < MIN_GAMES or m not in current:
            continue
        sxy = sxx = 0.0
        for g, r in rows:
            v = models.get(g.game_id, {}).get(m)
            if v is not None:
                d = v - g.forecast.market
                sxy += d * r
                sxx += d * d
        if sxx <= 0:
            continue
        w = min(1.0, max(0.0, sxy / sxx))
        sse = base - 2 * w * sxy + w * w * sxx
        rmse = math.sqrt(sse / len(rows))
        if rmse < best.train_rmse - 1e-12:
            best = BestModel(m, w, rmse)
    return best


@dataclass(frozen=True)
class Blend:
    columns: tuple[str, ...]
    coef: tuple[float, ...]          # intercept first, then one per column
    penalty: float


def _design(games: list[ab.ArchiveGame], models: dict[str, dict[str, float]],
            columns: tuple[str, ...]) -> np.ndarray:
    x = np.zeros((len(games), len(columns) + 1))
    x[:, 0] = 1.0
    index = {c: i + 1 for i, c in enumerate(columns)}
    for row, g in enumerate(games):
        for m, v in models.get(g.game_id, {}).items():
            if m in index:
                x[row, index[m]] = v - g.forecast.market       # a missing model agrees with the line
    return x


def _ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    eye = np.eye(x.shape[1]) * penalty
    eye[0, 0] = 0.0                                             # the intercept is not shrunk
    return np.linalg.solve(x.T @ x + eye, x.T @ y)


def fit_blend(train: list[ab.ArchiveGame], models: dict[str, dict[str, float]],
              margins: dict[str, int], latest_season: int, penalties=PENALTIES) -> Blend:
    """Ridge regression of the market's error on the models' disagreement."""
    games = [g for g in train if g.game_id in margins]
    counts: dict[str, int] = {}
    current: set[str] = set()
    for g in games:
        for m in models.get(g.game_id, {}):
            if m in NOT_MODELS:
                continue
            counts[m] = counts.get(m, 0) + 1
            if g.season == latest_season:
                current.add(m)
    columns = tuple(sorted(m for m, n in counts.items() if n >= MIN_GAMES and m in current))
    if not games:
        return Blend(columns, (0.0,) * (len(columns) + 1), penalties[-1])
    y = np.array([margins[g.game_id] - g.forecast.market for g in games], dtype=float)
    x = _design(games, models, columns)
    early = np.array([g.season < latest_season for g in games])
    penalty = penalties[-1]
    if early.any() and (~early).any():
        scores = {}
        for p in penalties:
            beta = _ridge(x[early], y[early], p)
            scores[p] = float(np.mean((y[~early] - x[~early] @ beta) ** 2))
        penalty = min(penalties, key=lambda p: (scores[p], -p))   # ties: the more cautious
    beta = _ridge(x, y, penalty)
    return Blend(columns, tuple(float(b) for b in beta), penalty)


def blend_margin(blend: Blend, game: ab.ArchiveGame, models: dict[str, dict[str, float]]) -> float:
    x = _design([game], models, blend.columns)[0]
    return game.forecast.market + float(x @ np.array(blend.coef))


# ---- walk-forward ---------------------------------------------------------------------
def walk_forward(games: list[ab.ArchiveGame], models: dict[str, dict[str, float]],
                 margins: dict[str, int], test_from: int = TEST_FROM) -> tuple[dict[str, dict], list[dict]]:
    """game_id -> {challenger: expected home margin}, for every test season,
    each fitted on the seasons before it only; and what was fitted each season."""
    out: dict[str, dict] = {}
    fits = []
    seasons = sorted({g.season for g in games})
    for season in (s for s in seasons if s >= test_from):
        train = [g for g in games if g.season < season]               # earlier seasons ONLY
        known = {g.game_id: margins[g.game_id] for g in train if g.game_id in margins}
        latest = max(g.season for g in train)
        best = fit_best_model(train, models, known, latest)
        blend = fit_blend(train, models, known, latest)
        fits.append({"season": season, "best": best, "blend": blend})
        for g in games:
            if g.season != season:
                continue
            value = models.get(g.game_id, {}).get(best.model) if best.model else None
            out[g.game_id] = {
                "best": g.forecast.market + (best.weight * (value - g.forecast.market) if value is not None else 0.0),
                "blend": blend_margin(blend, g, models),
            }
    return out, fits


# ---- scoring and report ---------------------------------------------------------------
KEYS = (("market", "Market alone"), ("deadeye", "Deadeye as it runs"),
        ("best", "Best single model (nudge)"), ("blend", "Learned blend"))


def score(games: list[ab.ArchiveGame], margins: dict[str, int], challengers: dict[str, dict],
          deadeye: dict[str, ab.Priced]) -> list[dict]:
    rows = []
    for g in games:
        if g.game_id not in challengers or g.game_id not in margins or g.game_id not in deadeye:
            continue
        actual = margins[g.game_id]
        winner = wf.credited(g.home, g.away, g.pool_home_line, actual)
        slate_game = wf.game_for(g.home, g.away, g.pool_home_line)
        expected = {"market": g.forecast.market, "deadeye": deadeye[g.game_id].fitted_margin,
                    **challengers[g.game_id]}
        row = {"game": g, "winner": winner}
        for key, _ in KEYS:
            if key == "deadeye":
                pred = deadeye[g.game_id].fitted
            else:
                pred = analytics.predict_margin(slate_game, expected[key], sd=analytics.SPREAD_SD)
            row[key] = None if winner is None else wf.scored(pred.pick, pred.chance, winner)
            row[f"{key}_pick"] = pred.pick
            row[f"{key}_sq"] = (expected[key] - actual) ** 2
            row[f"{key}_ats"] = ab.against_close(expected[key], g.close, actual)
        rows.append(row)
    return rows


def _mean(xs) -> float:
    xs = list(xs)
    return statistics.fmean(xs) if xs else float("nan")


def report_lines(conn: sqlite3.Connection) -> list[str]:
    games = ab.load(conn)
    models = named_models(conn)
    margins = wf.outcomes(conn)                       # passed only to fitting on earlier seasons
    challengers, fits = walk_forward(games, models, margins)
    deadeye = {p.game.game_id: p for p in ab.walk_forward(games, margins)}
    rows = score(games, margins, challengers, deadeye)
    graded = [r for r in rows if r["winner"] is not None]
    lines = [
        "# Challengers to Deadeye's nudge",
        "",
        "Generated by `python -m lab.challengers` from `lab/data/history.db`. Every number is "
        "computed. Intervals are 95% bootstrap intervals by game and by whole season; one that "
        "includes 0 is **not** evidence either way.",
        "",
        f"Same inputs and caveats as phase 3 (`archive_backtest.md`): the undated Prediction "
        f"Tracker archives, the midweek line, and the proxy pool line. Each challenger is fitted on "
        f"earlier seasons only and scored on seasons {TEST_FROM}-{max(g.season for g in games)}; all "
        f"four approaches are scored on the same **{len(graded)}** graded games ({len(rows)} for "
        f"margin error).",
        "",
        "| approach | right | rate | log loss | margin RMSE | vs closing line |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in KEYS:
        hits = sum(r[key][0] for r in graded)
        ats = [r[f"{key}_ats"] for r in rows if r[f"{key}_ats"] is not None]
        lines.append(f"| {label} | {hits}/{len(graded)} | {hits / len(graded):.1%} | "
                     f"{_mean(r[key][1] for r in graded):.4f} | "
                     f"{math.sqrt(_mean(r[f'{key}_sq'] for r in rows)):.3f} | "
                     + (f"{sum(ats)}/{len(ats)} ({_mean(ats):.1%})" if ats else "no sides") + " |")
    groups = [r["game"].season for r in graded]
    all_groups = [r["game"].season for r in rows]
    for base, base_label in (("market", "the market"), ("deadeye", "Deadeye")):
        lines += ["", f"Against {base_label} (challenger minus {base_label}; negative log loss and "
                      f"squared error favour the challenger):", ""]
        for key, label in KEYS[2:]:
            ll = [r[key][1] - r[base][1] for r in graded]
            hit = [r[key][0] - r[base][0] for r in graded]
            sq = [r[f"{key}_sq"] - r[f"{base}_sq"] for r in rows]
            differ = [r for r in graded if r[f"{key}_pick"] != r[f"{base}_pick"]]
            lines += [f"- **{label}**: log loss {wf._ci(*wf.bootstrap(ll))} by game, "
                      f"{wf._ci(*wf.bootstrap(ll, groups))} by season; picks right "
                      f"{wf._ci(*wf.bootstrap(hit, groups), pct=True)} by season; squared error "
                      f"{wf._ci(*wf.bootstrap(sq, all_groups), digits=2)} by season; different picks "
                      f"{len(differ)} (challenger right {sum(r[key][0] for r in differ)}, "
                      f"{base_label} right {sum(r[base][0] for r in differ)})"]
    for key, label in KEYS[2:]:
        ats = [r[f"{key}_ats"] for r in rows if r[f"{key}_ats"] is not None]
        if ats:
            g_ats = [r["game"].season for r in rows if r[f"{key}_ats"] is not None]
            m, lo, hi = wf.bootstrap(ats, g_ats)
            lines.append(f"- {label} against nflverse's closing spread: {m:.1%} ({lo:.1%} to {hi:.1%} "
                         f"by season) over {len(ats)} games; 50% is no edge.")

    lines += ["", "## Season by season", "",
              "| season | games | market right | Deadeye right | best model right | blend right | "
              "RMSE market | RMSE best | RMSE blend | best model (weight) | blend penalty, models |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for fit in fits:
        s = fit["season"]
        s_rows = [r for r in rows if r["game"].season == s]
        s_graded = [r for r in s_rows if r["winner"] is not None]
        if not s_graded:
            continue
        best, blend = fit["best"], fit["blend"]
        lines.append(
            f"| {s} | {len(s_graded)} | {sum(r['market'][0] for r in s_graded)} | "
            f"{sum(r['deadeye'][0] for r in s_graded)} | {sum(r['best'][0] for r in s_graded)} | "
            f"{sum(r['blend'][0] for r in s_graded)} | "
            f"{math.sqrt(_mean(r['market_sq'] for r in s_rows)):.2f} | "
            f"{math.sqrt(_mean(r['best_sq'] for r in s_rows)):.2f} | "
            f"{math.sqrt(_mean(r['blend_sq'] for r in s_rows)):.2f} | "
            f"{best.model or 'none'} ({best.weight:.2f}) | {blend.penalty:g}, {len(blend.columns)} |")
    lines += ["", "## Reading this", "",
              "- A challenger earns a look only if it beats **both** baselines on log loss with an "
              "interval clear of 0, holds up season by season, and then holds up on dated inputs.",
              "- Nothing here changes production. Promoting anything needs Sam's approval "
              "(CLAUDE.md).", ""]
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
