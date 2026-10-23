"""The strategy lab: many ways of pricing a game, tried the same fair way, against Deadeye and the market.

The question is not "which model is cleverest" but "which way of pricing a
game would have helped on games nobody had seen". So every strategy here -
from the betting line alone to a learned combination of all the others - is
put through one protocol, written down before anything was scored (PROTOCOL):

    the clock       games are walked forward a season at a time. A strategy
                    taught for season S has seen only seasons before S. Team
                    ratings (Elo, the scoring model) move a week at a time
                    and only on results from earlier weeks.
    the timing      the headline is priced at the archive's midweek line - the
                    nearest thing it keeps to the pool's Thursday deadline.
                    Opening and last-updated lines are run as diagnostics,
                    and the closing line is reported for reference only.
    the split       development seasons choose; test seasons (2023 on) are
                    only scored after the finalists are frozen (freeze.json,
                    with its fingerprint) - and how often the test seasons
                    have been opened under this protocol is counted.
    the tries       every candidate tried is counted, and the p-values are
                    Holm-corrected over all of them, so trying more ideas
                    makes each one harder, not easier, to pass.
    the cards       probability (log loss, Brier, calibration, sharpness)
                    and the pool (ACQL picks credited a week) are scored
                    apart and never added together.
    promotion       only a "nomination", written to nominee.json, and only if
                    every gate in PROTOCOL holds. Nothing here changes a pick:
                    the dashboard does not import this package, and the switch
                    is the owner's.

Strategy families:

    market          the line at that timing, through the dashboard's curve
    deadeye         the picks' own rule (recipes.deadeye_margins), same curve
    elo             team Elo from past results only, its margin on the curve
    scoring         points-for / points-against ratings (exponentially
                    weighted), a predicted score for each side, its margin
                    on the curve
    logistic        a regularised logistic regression straight on "was the
                    home side credited", from the market's chance and the
                    pregame facts
    lightgbm / xgboost   shallow gradient-boosted trees on the same inputs
                    (only when the library is installed - never a requirement)
    mean            the plain average of a few strategies' log-odds
    stack           the meta-learner: a logistic regression on the other
                    strategies' out-of-sample log-odds, optionally with
                    pregame context (how big the line is, how far apart the
                    models are, early season) so it can learn *when* a
                    strategy helps. Taught only on out-of-sample predictions
                    from earlier seasons.

Two protocols. strategy-lab-1 (PROTOCOL) asked one question - was the home
side credited under the pool's line - and so mixed two objectives. Its test
seasons have been opened. strategy-lab-2 (PROTOCOL_2) splits them into two
tracks that are taught, chosen and judged apart, each with its own champion:

    probability     did the home side win? (ties left out) - log loss against
                    the market and Deadeye, every chance on the straight-up curve
    acql            was the home side credited under the pool's line? - ACQL
                    picks credited a week against Deadeye's card

Development (2018-2022) chooses each track's finalists. 2023-2026 were opened
under strategy-lab-1, so here they are scored only as "seen" and are never
evidence. The test is the forecasts locked before each Thursday deadline from
2026 week 8 on (lablocks.py); only they can earn a nomination.

No Qt here.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..model import predictions
from . import data, evaluate, features, probability, recipes, scorecards

log = logging.getLogger("acql.training")

LAB_VERSION = "1.0"

PROTOCOL = {
    "id": "strategy-lab-1",
    "registered": "2026-10-23",
    "primary_timing": "midweek",
    "diagnostic_timings": ["opening", "updated"],
    "test_seasons": [2023, 2024, 2025, 2026],
    "warm_up_seasons": 3,
    "meta_warm_up_seasons": 2,
    "alpha": 0.05,
    "correction": "holm over every candidate tried, each comparison set apart",
    "min_test_games": 150,
    "min_test_weeks": 30,
    "calibration_slack": 0.010,
    "max_finalists": 6,
    "redundant_correlation": 0.95,
    "gates": [
        "test: 150+ games and 30+ weeks",
        "development: better than Deadeye on log loss, Holm-adjusted p < 0.05",
        "test: better than Deadeye on log loss, Holm-adjusted p < 0.05 (over the finalists)",
        "test: better than the market on log loss, p < 0.05 (adds something the line does not have)",
        "test: calibration error no worse than Deadeye's + 0.010",
        "test: ACQL picks a week not clearly worse than Deadeye's (95% range reaches zero or above)",
        "the leak check passed",
        "fewer than 1% of the archive's rows left out as faulty",
    ],
}


#: The two objectives, set apart (written 2026-10-23, before any locked week had a result).
TRACKS = {
    "probability": {"target": "home_win", "question": "did the home side win (ties left out)",
                    "chance": "the home side's chance of winning, on the straight-up curve",
                    "measure": "log loss against Deadeye and the market"},
    "acql": {"target": "credited", "question": "was the home side credited under the pool's line",
             "chance": "the home side's chance of being credited",
             "measure": "ACQL picks credited a week against Deadeye's card"},
}

PROTOCOL_2 = {
    "id": "strategy-lab-2",
    "registered": "2026-10-23",
    "builds_on": "strategy-lab-1 (same strategies and walk; its test seasons are spent)",
    "tracks": TRACKS,
    "primary_timing": "midweek",
    "diagnostic_timings": ["opening", "updated"],
    "development_seasons": "every season asked about before 2023",
    "seen_seasons": [2023, 2024, 2025, 2026],
    "seen_note": "opened under strategy-lab-1 - scored here for the record, never as evidence",
    "test": "forecasts locked before each Thursday deadline (lab lock), from 2026 week 8 on",
    "test_from": [2026, 8],
    "warm_up_seasons": 3,
    "meta_warm_up_seasons": 2,
    "alpha": 0.05,
    "correction": "holm: on development over every candidate tried under either protocol for that track; "
                  "on the locked weeks over that track's frozen finalists",
    "max_finalists": 6,
    "min_test_games": 150,
    "min_test_weeks": 10,
    "calibration_slack": 0.010,
    "redundant_correlation": 0.95,
    "gates": {
        "probability": [
            "development: ahead of Deadeye on home-win log loss (chosen there; the edge need not be significant)",
            "locked weeks: 150+ graded games over 10+ weeks",
            "locked weeks: better than Deadeye on home-win log loss, Holm-adjusted p < 0.05 over the track's finalists",
            "locked weeks: better than the market on home-win log loss, p < 0.05",
            "locked weeks: calibration error no worse than Deadeye's + 0.010",
            "the leak check passed; fewer than 1% of the archive's rows left out as faulty",
        ],
        "acql": [
            "development: ahead of Deadeye on ACQL picks credited a week",
            "locked weeks: 150+ graded games over 10+ weeks, on the commissioner's own pool lines",
            "locked weeks: more ACQL picks a week than Deadeye's, Holm-adjusted p < 0.05 over the track's finalists",
            "locked weeks: credited-chance log loss not clearly worse than Deadeye's (95% range reaches zero)",
            "the leak check passed; fewer than 1% of the archive's rows left out as faulty",
        ],
    },
}


def protocol_mark(protocol: dict = PROTOCOL) -> str:
    return hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()[:12]


def folder() -> Path:
    where = data.folder() / "lab"
    where.mkdir(parents=True, exist_ok=True)
    return where


# ==== team ratings from past results only ==========================================================
ELO_SCALE = 25.0          # rating points to a point of margin


@dataclass(frozen=True)
class EloSettings:
    k: float = 20.0
    hfa: float = 1.6              # points
    regress: float = 1 / 3        # toward the middle as each season begins

    @property
    def key(self) -> str:
        return f"elo:{self.k:g}:{self.hfa:g}"


@dataclass(frozen=True)
class ScoreSettings:
    half_life: float = 8.0        # games
    regress: float = 1 / 3

    @property
    def key(self) -> str:
        return f"score:{self.half_life:g}"


def results_universe(history: pd.DataFrame, extra: pd.DataFrame | None = None, *, verse: bool = True) -> pd.DataFrame:
    """Every game whose teams are known - nflverse's schedule and results
    (regular season and playoffs), the archive's own, and any extra rows
    (this season's books) - one row a game, scores where they are in."""
    frames = []
    try:
        schedule = data.nflverse_games() if verse else pd.DataFrame()
        if len(schedule):
            frames.append(schedule[["season", "week", "home", "away", "home_points", "away_points", "neutral"]])
    except Exception as exc:  # noqa: BLE001 - the archive's own scores still serve
        log.warning("nflverse games not read: %s", exc)
    for more in (history, extra):
        if more is not None and len(more):
            cols = [c for c in ("season", "week", "home", "away", "home_points", "away_points", "neutral")
                    if c in more.columns]
            frames.append(more[cols])
    if not frames:
        return pd.DataFrame(columns=["season", "week", "home", "away", "home_points", "away_points", "neutral"])
    out = pd.concat(frames, ignore_index=True)
    out["source_rank"] = np.arange(len(out))
    out["season"], out["week"] = out["season"].astype(int), out["week"].astype(int)
    out["game"] = [data.game_key(s, w, a, h) for s, w, a, h in zip(out["season"], out["week"], out["away"], out["home"])]
    out["has_score"] = out["home_points"].notna() & out["away_points"].notna()
    # one row a game: the first with a score wins
    out = out.sort_values(["game", "has_score", "source_rank"], ascending=[True, False, True]).drop_duplicates("game")
    out["order"] = out["season"] * 100 + out["week"]
    return out.sort_values(["order", "game"]).reset_index(drop=True)


def ratings(universe: pd.DataFrame, elo: EloSettings = EloSettings(),
            score: ScoreSettings = ScoreSettings()) -> pd.DataFrame:
    """Each game's pregame Elo margin and scoring-model margin and total
    (points for the home side), from results of EARLIER weeks only.

    The whole of a week is priced from the state before it, then the week's
    results are taken in - so a Thursday game never informs that Sunday."""
    elo_r: dict[str, float] = {}
    off: dict[str, float] = {}
    dfn: dict[str, float] = {}
    league = {"mean": 21.5, "home": 2.0}
    decay = 1 - 0.5 ** (1 / score.half_life)
    out = np.full((len(universe), 3), np.nan)
    season_seen = None
    orders = universe["order"].to_numpy()
    teams_h, teams_a = universe["home"].tolist(), universe["away"].tolist()
    hp, ap = universe["home_points"].to_numpy(dtype=float), universe["away_points"].to_numpy(dtype=float)
    neutral = universe["neutral"].fillna(0).to_numpy(dtype=float) if "neutral" in universe else np.zeros(len(universe))
    bounds = np.flatnonzero(np.r_[True, orders[1:] != orders[:-1], True])
    for start, end in zip(bounds[:-1], bounds[1:]):
        season = int(orders[start] // 100)
        if season != season_seen:
            for t in elo_r:
                elo_r[t] = elo_r[t] * (1 - elo.regress) + 1500 * elo.regress
            for t in off:
                off[t] = off[t] * (1 - score.regress) + league["mean"] * score.regress
                dfn[t] = dfn[t] * (1 - score.regress) + league["mean"] * score.regress
            season_seen = season
        # price the week from the state before it
        for i in range(start, end):
            h, a = teams_h[i], teams_a[i]
            hfa = 0.0 if neutral[i] else 1.0
            out[i, 0] = (elo_r.get(h, 1500.0) - elo_r.get(a, 1500.0)) / ELO_SCALE + hfa * elo.hfa
            mu = league["mean"]
            ph = mu + (off.get(h, mu) - mu) + (dfn.get(a, mu) - mu) + hfa * league["home"] / 2
            pa = mu + (off.get(a, mu) - mu) + (dfn.get(h, mu) - mu) - hfa * league["home"] / 2
            out[i, 1], out[i, 2] = ph - pa, ph + pa
        # then take its results in
        for i in range(start, end):
            if np.isnan(hp[i]) or np.isnan(ap[i]):
                continue
            h, a = teams_h[i], teams_a[i]
            rh, ra = elo_r.get(h, 1500.0), elo_r.get(a, 1500.0)
            hfa = 0.0 if neutral[i] else elo.hfa * ELO_SCALE
            expect = 1 / (1 + 10 ** (-(rh + hfa - ra) / 400))
            margin = hp[i] - ap[i]
            won = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
            winner_gap = (rh + hfa - ra) if margin > 0 else (ra - rh - hfa)
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_gap * 0.001 + 2.2) if margin else 1.0
            change = elo.k * mult * (won - expect)
            elo_r[h], elo_r[a] = rh + change, ra - change
            mu = league["mean"]
            for team, scored, allowed in ((h, hp[i], ap[i]), (a, ap[i], hp[i])):
                off[team] = off.get(team, mu) + decay * (scored - off.get(team, mu))
                dfn[team] = dfn.get(team, mu) + decay * (allowed - dfn.get(team, mu))
            league["mean"] += 0.01 * ((hp[i] + ap[i]) / 2 - league["mean"])
            if not neutral[i]:
                league["home"] += 0.005 * (margin - league["home"])
    frame = pd.DataFrame({"game": universe["game"].to_numpy(), elo.key: out[:, 0],
                          score.key: out[:, 1], score.key + ":total": out[:, 2]})
    return frame


# ==== the table a strategy sees ===================================================================
_CURVE = probability.InUse()


def curve_chance(margin: np.ndarray, pool_line: np.ndarray, favourite: list[str]) -> np.ndarray:
    """The home side's chance of being credited, on the dashboard's own curve."""
    out = np.full(len(margin), np.nan)
    kept: dict = {}
    for i, (m, line, side) in enumerate(zip(margin, pool_line, favourite)):
        if np.isnan(m):
            continue
        key = (round(float(m), 1), None if np.isnan(line) else float(line), side)
        if key not in kept:
            kept[key] = probability.home_chance(_CURVE, key[0], float(line), side)
        out[i] = kept[key]
    return out


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(x) -> np.ndarray:
    return 1 / (1 + np.exp(-np.asarray(x, dtype=float)))


ELO_GRID = (EloSettings(), EloSettings(k=30.0), EloSettings(k=12.0), EloSettings(hfa=2.5))
SCORE_GRID = (ScoreSettings(), ScoreSettings(half_life=4.0), ScoreSettings(half_life=16.0))
DEFAULT_ELO, DEFAULT_SCORE = ELO_GRID[0].key, SCORE_GRID[0].key


def home_won(actual: np.ndarray) -> np.ndarray:
    """1 where the home side won, 0 where it lost, nan for a tie or no result."""
    a = np.asarray(actual, dtype=float)
    return np.where(np.isnan(a) | (a == 0), np.nan, (a > 0).astype(float))


TARGETS = ("credited", "home_win")


def table(history: pd.DataFrame, timing: str, *, universe: pd.DataFrame | None = None,
          notes: data.Notes | None = None, rated: pd.DataFrame | None = None,
          target: str = "credited") -> pd.DataFrame:
    """One row a graded game at this timing: the answer, the market's and
    Deadeye's chances, the team ratings, and every pregame input.

    `target` is the question every chance answers, and `y` its answer:
    "credited" (the pool's line decides, as strategy-lab-1 had it) or
    "home_win" (the straight-up curve for every game; a tie is no answer).
    The `credited` column is kept either way, for the pool card."""
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    notes = notes or data.Notes()
    setting = features.SETTINGS[timing]
    prepared = features.prepare(history, setting, notes)
    if prepared.empty:
        return prepared
    if rated is None:
        universe = universe if universe is not None else results_universe(history)
        rated = rating_columns(universe)
    out = prepared.merge(rated, on="game", how="left")
    line, fav = out["pool_line"].to_numpy(dtype=float), out["pool_favourite"].fillna("").tolist()
    if target == "home_win":
        line, fav = np.full(len(out), np.nan), [""] * len(out)
        out["y"] = home_won(out["actual"].to_numpy(dtype=float))
    else:
        out["y"] = out["credited"].to_numpy(dtype=float)
    out["deadeye_margin"] = recipes.deadeye_margins(out, predictions.CONSENSUS_WEIGHT)
    out.loc[out["n_models"].fillna(0) < features.ENOUGH_MODELS, "deadeye_margin"] = np.nan
    out["p_market"] = curve_chance(out["market"].to_numpy(dtype=float), line, fav)
    out["p_deadeye"] = curve_chance(out["deadeye_margin"].to_numpy(dtype=float), line, fav)
    for col in [c for c in rated.columns if c != "game" and not c.endswith(":total")]:
        out["p_" + col] = curve_chance(out[col].to_numpy(dtype=float), line, fav)
        out["view_" + col] = out[col] - out["market"]
    out["l_market"], out["l_deadeye"] = logit(out["p_market"]), logit(out["p_deadeye"])
    out["view_deadeye"] = out["deadeye_margin"] - out["market"]
    out["abs_market"] = out["market"].abs()
    out["early"] = (out["week"] <= 4).astype(float)
    tot = DEFAULT_SCORE + ":total"
    out["score_total_rel"] = out[tot] - out.groupby("order")[tot].transform("median") if tot in out else np.nan
    # The same games for either target; a tie's y is nan, so it is never taught on or scored.
    keep = out["credited"].notna() & out["p_market"].notna() & out["p_deadeye"].notna()
    return out[keep | out["credited"].isna()].reset_index(drop=True)


def rating_columns(universe: pd.DataFrame) -> pd.DataFrame:
    """Every Elo and scoring setting on the grid, one column each, by game."""
    rated = None
    for i, elo in enumerate(ELO_GRID):
        score = SCORE_GRID[i] if i < len(SCORE_GRID) else SCORE_GRID[0]
        got = ratings(universe, elo, score)
        if i >= len(SCORE_GRID):
            got = got[["game", elo.key]]
        rated = got if rated is None else rated.merge(got, on="game")
    return rated


# ==== strategies ==================================================================================
#: Pregame inputs a learned strategy may be handed (never an answer, never a later line).
INPUT_BLOCKS = {
    "market": ("l_market", "abs_market"),
    "deadeye": ("view_deadeye",),
    "models": ("gap_net", "gap_agree", "apart", "n_models", "week_lean"),
    "movement": ("move",),
    "elo": ("view_" + DEFAULT_ELO,),
    "scoring": ("view_" + DEFAULT_SCORE, "score_total_rel"),
    "schedule": ("rest", "division", "neutral", "early"),
}


@dataclass
class Spec:
    family: str
    name: str
    params: dict = field(default_factory=dict)
    inputs: tuple = ()
    members: tuple = ()           # for mean / stack: ids of other specs
    round: int = 1
    baseline: bool = False

    @property
    def id(self) -> str:
        body = {"family": self.family, "params": self.params, "inputs": list(self.inputs),
                "members": list(self.members), "lab": LAB_VERSION}
        return self.family + "-" + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:8]

    @property
    def learned(self) -> bool:
        return self.family in ("logistic", "lightgbm", "xgboost")

    @property
    def meta(self) -> bool:
        return self.family in ("mean", "stack")

    def describe(self) -> dict:
        return {"id": self.id, "family": self.family, "name": self.name, "params": self.params,
                "inputs": list(self.inputs), "members": list(self.members), "round": self.round,
                "baseline": self.baseline}


def _fill(X: np.ndarray, means: np.ndarray) -> np.ndarray:
    X = X.copy()
    bad = np.isnan(X)
    if bad.any():
        X[bad] = np.take(means, np.nonzero(bad)[1])
    return X


def fit_logistic(X: np.ndarray, y: np.ndarray, penalty: float, offset: np.ndarray | None = None) -> np.ndarray:
    """Ridge-penalised logistic regression by Newton steps; the first column is
    the constant (not penalised). With an `offset` (the market's log-odds) the
    penalty pulls toward "the market was right", not toward a coin flip."""
    beta = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], penalty * len(y))
    pen[0] = 0.0
    off = np.zeros(len(y)) if offset is None else np.asarray(offset, dtype=float)
    for _ in range(60):
        p = sigmoid(off + X @ beta)
        w = p * (1 - p)
        grad = X.T @ (y - p) - pen * beta
        hess = (X * w[:, None]).T @ X + np.diag(pen) + 1e-9 * np.eye(X.shape[1])
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    return beta


class Model:
    """A strategy that can be taught and asked."""

    def __init__(self, spec: Spec) -> None:
        self.spec = spec
        self.state: dict = {}

    def fit(self, rows: pd.DataFrame, y: np.ndarray) -> None:
        pass

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError


class Fixed(Model):
    """A chance column worked out from pregame numbers alone: nothing to teach."""

    def predict(self, rows):
        return rows[self.spec.params["column"]].to_numpy(dtype=float)


class Logistic(Model):
    """Corrections to the market's log-odds, by a ridge logistic regression.
    The pull (penalty) is chosen on the last season taught on, the rest taught
    on the seasons before it; then taught again on all of them."""

    PENALTIES = (1e-4, 1e-3, 1e-2, 1e-1, 1.0)

    def _inputs(self, rows) -> pd.DataFrame:
        return rows[list(self.spec.inputs)]

    def _offset(self, rows) -> np.ndarray:
        return rows["l_market"].to_numpy(dtype=float)

    def _x(self, framed: pd.DataFrame) -> np.ndarray:
        X = framed.to_numpy(dtype=float)
        X = (_fill(X, self.mean) - self.mean) / self.sd
        return np.column_stack([np.ones(len(X)), X])

    def fit(self, rows, y):
        framed, off = self._inputs(rows), self._offset(rows)
        X = framed.to_numpy(dtype=float)
        self.mean = np.nan_to_num(np.nanmean(X, axis=0)) if len(X) else np.zeros(X.shape[1])
        self.sd = np.nan_to_num(np.nanstd(X, axis=0), nan=1.0) if len(X) else np.ones(X.shape[1])
        self.sd[self.sd < 1e-9] = 1.0
        seasons = rows["season"].to_numpy()
        inner = seasons < seasons.max()
        Xa = self._x(framed)
        penalty = self.spec.params.get("penalty")
        if penalty is None and inner.sum() > 200 and (~inner).sum() > 50:
            best, chosen = np.inf, self.PENALTIES[-1]
            for pen in self.PENALTIES:
                b = fit_logistic(Xa[inner], y[inner], pen, off[inner])
                loss = float(evaluate.losses(sigmoid(off[~inner] + Xa[~inner] @ b), y[~inner]).mean())
                if loss < best - 1e-12:
                    best, chosen = loss, pen
            penalty = chosen
        penalty = self.PENALTIES[-1] if penalty is None else penalty
        self.beta = fit_logistic(Xa, y, penalty, off)
        self.state = {"penalty": penalty, "weights": dict(zip(["constant", *framed.columns],
                                                             [round(float(b), 4) for b in self.beta]))}

    def predict(self, rows):
        return sigmoid(self._offset(rows) + self._x(self._inputs(rows)) @ self.beta)


class Boosted(Model):
    """Shallow gradient-boosted trees (lightgbm or xgboost) growing corrections
    to the market's log-odds (its starting score), stopped early on the last
    season taught on."""

    def fit(self, rows, y):
        X = rows[list(self.spec.inputs)].to_numpy(dtype=float)
        off = rows["l_market"].to_numpy(dtype=float)
        seasons = rows["season"].to_numpy()
        inner = seasons < seasons.max()
        p = dict(self.spec.params)
        rounds = int(p.pop("rounds", 400))
        if self.spec.family == "lightgbm":
            import lightgbm as lgb
            base = dict(objective="binary", learning_rate=0.03, num_leaves=7, min_child_samples=60,
                        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
                        random_state=7, verbose=-1, deterministic=True, num_threads=1)
            base.update(p)
            train = lgb.Dataset(X[inner], y[inner], init_score=off[inner], free_raw_data=False)
            valid = lgb.Dataset(X[~inner], y[~inner], init_score=off[~inner], reference=train)
            probe = lgb.train(base, train, num_boost_round=rounds, valid_sets=[valid],
                              callbacks=[lgb.early_stopping(40, verbose=False)])
            best = max(int(probe.best_iteration or rounds), 1)
            self.model = lgb.train(base, lgb.Dataset(X, y, init_score=off), num_boost_round=best)
        else:
            import xgboost as xgb
            base = dict(objective="binary:logistic", eta=0.03, max_depth=2, min_child_weight=20, subsample=0.8,
                        colsample_bytree=0.8, reg_lambda=5.0, seed=7, nthread=1, tree_method="hist",
                        eval_metric="logloss")
            if "learning_rate" in p:
                p["eta"] = p.pop("learning_rate")
            base.update(p)
            train = xgb.DMatrix(X[inner], y[inner], base_margin=off[inner])
            valid = xgb.DMatrix(X[~inner], y[~inner], base_margin=off[~inner])
            probe = xgb.train(base, train, rounds, evals=[(valid, "v")], early_stopping_rounds=40,
                              verbose_eval=False)
            best = max(int(probe.best_iteration) + 1, 1)
            self.model = xgb.train(base, xgb.DMatrix(X, y, base_margin=off), best)
        self.state = {"trees": best}

    def predict(self, rows):
        X = rows[list(self.spec.inputs)].to_numpy(dtype=float)
        off = rows["l_market"].to_numpy(dtype=float)
        if self.spec.family == "lightgbm":
            return sigmoid(off + self.model.predict(X, raw_score=True))
        import xgboost as xgb
        return self.model.predict(xgb.DMatrix(X, base_margin=off))


class Mean(Model):
    def predict(self, rows):
        return sigmoid(np.mean([logit(rows["oos:" + m]) for m in self.spec.members], axis=0))


class Stack(Logistic):
    """The meta-learner. It starts from the first member (the market) and
    learns how much to move toward each other strategy's out-of-sample view
    (its log-odds less the market's) - and, with context, how that weight
    changes with the size of the line, how far apart the models are, and
    early season - so it can learn *when* a strategy is worth listening to."""

    def _offset(self, rows):
        return logit(rows["oos:" + self.spec.members[0]])

    def _inputs(self, rows):
        cols = {"market": self._offset(rows)}
        market = cols["market"]
        for m in self.spec.members[1:]:
            view = logit(rows["oos:" + m]) - market
            cols["view " + m] = view
            for c in self.spec.params.get("context", ()):
                cols[f"view {m} x {c}"] = view * np.nan_to_num(rows[c].to_numpy(dtype=float))
        return pd.DataFrame(cols, index=rows.index)


KINDS = {"market": Fixed, "deadeye": Fixed, "elo": Fixed, "scoring": Fixed, "logistic": Logistic,
         "lightgbm": Boosted, "xgboost": Boosted, "mean": Mean, "stack": Stack}


def build(spec: Spec) -> Model:
    return KINDS[spec.family](spec)


def have(library: str) -> bool:
    try:
        __import__(library)
        return True
    except Exception:  # noqa: BLE001
        return False


# ==== the candidates ==============================================================================
MARKET_SPEC = Spec("market", "Market (the line, on the curve)", {"column": "p_market"}, baseline=True)
DEADEYE_SPEC = Spec("deadeye", f"Deadeye at {predictions.CONSENSUS_WEIGHT:.0%} (in use)",
                    {"column": "p_deadeye"}, baseline=True)


def inputs_of(*blocks: str) -> tuple:
    return tuple(c for b in blocks for c in INPUT_BLOCKS[b])


def first_round() -> list[Spec]:
    """The candidates written down before anything was scored."""
    out = [MARKET_SPEC, DEADEYE_SPEC]
    for e in ELO_GRID:
        out.append(Spec("elo", f"Elo k={e.k:g}, home {e.hfa:g}", {"column": "p_" + e.key}))
    for s in SCORE_GRID:
        out.append(Spec("scoring", f"Scoring model, half-life {s.half_life:g} games", {"column": "p_" + s.key}))
    logit_sets = {
        "Logistic: market only (recalibrated line)": ("market",),
        "Logistic: market + Deadeye's view": ("market", "deadeye"),
        "Logistic: market + the models": ("market", "models"),
        "Logistic: market + Elo": ("market", "elo"),
        "Logistic: market + scoring model": ("market", "scoring"),
        "Logistic: market + movement + schedule": ("market", "movement", "schedule"),
        "Logistic: everything": tuple(INPUT_BLOCKS),
    }
    for name, blocks in logit_sets.items():
        out.append(Spec("logistic", name, {}, inputs_of(*blocks)))
    every = inputs_of(*INPUT_BLOCKS) + ("market",)
    if have("lightgbm"):
        out.append(Spec("lightgbm", "LightGBM, 7 leaves", {"num_leaves": 7}, every))
        out.append(Spec("lightgbm", "LightGBM, 3 leaves", {"num_leaves": 3}, every))
    if have("xgboost"):
        out.append(Spec("xgboost", "XGBoost, depth 2", {"max_depth": 2}, every))
    base = [MARKET_SPEC.id, DEADEYE_SPEC.id, _id_of(out, "elo", DEFAULT_ELO), _id_of(out, "scoring", DEFAULT_SCORE)]
    out.append(Spec("mean", "Average of market and Deadeye", members=tuple(base[:2])))
    out.append(Spec("mean", "Average of market, Deadeye, Elo, scoring", members=tuple(base)))
    out.append(Spec("stack", "Meta-learner: market, Deadeye, Elo, scoring", {}, members=tuple(base)))
    out.append(Spec("stack", "Meta-learner with context (line size, model spread, early season)",
                    {"context": ["abs_market", "apart", "early"]}, members=tuple(base)))
    learned = [s.id for s in out if s.learned]
    out.append(Spec("stack", "Meta-learner over every learned strategy", {},
                    members=tuple([MARKET_SPEC.id, DEADEYE_SPEC.id] + learned)))
    return out


def _id_of(specs: list[Spec], family: str, key: str) -> str:
    return next(s.id for s in specs if s.family == family and s.params.get("column") == "p_" + key)


def second_round(specs: list[Spec], dev: dict, closed: set[str]) -> list[Spec]:
    """Proposals made from the first round's development results - never from the test seasons.

    * a meta-learner over only the strategies that beat the market on development
    * the best boosted-tree setting's neighbours
    * a logistic regression grown block by block, keeping a block only if it helped
    A proposal already tried under this protocol (`closed`) is still scored - so a run
    can be reproduced - but is marked as tried before, and it is counted once in the
    multiple-testing penalty however many runs try it."""
    out: list[Spec] = []
    by_id = {s.id: s for s in specs}
    ahead = [i for i, r in dev.items() if i in by_id and not by_id[i].meta and not by_id[i].baseline
             and r["vs_market"]["edge"] > 0]
    if ahead:
        out.append(Spec("stack", "Meta-learner over strategies ahead of the market in development", {},
                        members=tuple([MARKET_SPEC.id, DEADEYE_SPEC.id] + sorted(ahead)), round=2))
    trees = [s for s in specs if s.family in ("lightgbm", "xgboost") and s.id in dev]
    if trees:
        best = min(trees, key=lambda s: dev[s.id]["logloss"])
        if best.family == "lightgbm":
            for leaves, lr in ((best.params.get("num_leaves", 7), 0.015), (max(2, best.params.get("num_leaves", 7) - 2), 0.03)):
                out.append(Spec("lightgbm", f"LightGBM, {leaves} leaves, rate {lr}", {"num_leaves": leaves,
                                "learning_rate": lr}, best.inputs, round=2))
        else:
            out.append(Spec("xgboost", "XGBoost, depth 1", {"max_depth": 1}, best.inputs, round=2))
    grown, kept_blocks = None, ["market"]
    base_loss = dev.get(_id_for_blocks(specs, ("market",)), {}).get("logloss")
    if base_loss is not None:
        for block in ("deadeye", "models", "elo", "scoring", "movement", "schedule"):
            single = _id_for_blocks(specs, ("market", block))
            if single in dev and dev[single]["logloss"] < base_loss:
                kept_blocks.append(block)
        if len(kept_blocks) > 2:
            grown = Spec("logistic", "Logistic: market + every block that helped alone (" +
                         ", ".join(kept_blocks[1:]) + ")", {}, inputs_of(*kept_blocks), round=2)
            out.append(grown)
    return [s for s in out if s.id not in by_id]


def _id_for_blocks(specs, blocks) -> str | None:
    want = inputs_of(*blocks)
    return next((s.id for s in specs if s.family == "logistic" and tuple(s.inputs) == want), None)


# ==== the walk ====================================================================================
def _answer(frame: pd.DataFrame) -> np.ndarray:
    """What every chance in the frame is scored against (see table's `target`)."""
    return frame["y" if "y" in frame.columns else "credited"].to_numpy(dtype=float)


def walk(frame: pd.DataFrame, specs: list[Spec], *, warm: int = PROTOCOL["warm_up_seasons"],
         meta_warm: int = PROTOCOL["meta_warm_up_seasons"], until: int | None = None,
         oos: pd.DataFrame | None = None, progress=None) -> tuple[pd.DataFrame, dict]:
    """Every strategy's out-of-sample chance for every game, a season at a time.

    Returns (chances: one column per spec id, nan where it was not asked;
    states: what each learned strategy had settled on as each season began).
    `oos` carries chances already worked out for other specs (round two adds
    to round one without walking it again)."""
    games = frame
    seasons = sorted(set(games["season"].astype(int).tolist()))
    season_of = games["season"].to_numpy()
    y_all = _answer(games)
    out = oos.copy() if oos is not None else pd.DataFrame(index=games.index)
    states: dict = {}
    # fixed strategies: every row
    for spec in specs:
        if spec.id in out.columns:
            continue
        if not spec.learned and not spec.meta:
            out[spec.id] = build(spec).predict(games)
    order = games["order"].to_numpy()
    learned = [s for s in specs if s.learned and s.id not in out.columns]
    metas = [s for s in specs if s.meta and s.id not in out.columns]
    for s in learned + metas:
        out[s.id] = np.nan
    asked = seasons[warm:]
    for step, season in enumerate(asked):
        here = season_of == season
        if until is not None:
            here &= order <= until
            if not here.any():
                break
        before = (season_of < season) & ~np.isnan(y_all)
        for spec in learned:
            model = build(spec)
            try:
                model.fit(games[before], y_all[before])
                out.loc[here, spec.id] = model.predict(games[here])
                states.setdefault(spec.id, {})[int(season)] = model.state
            except Exception as exc:  # noqa: BLE001 - one strategy failing costs only itself
                log.warning("%s failed for %s: %s", spec.name, season, exc)
        withoos = games.assign(**{"oos:" + c: out[c] for c in out.columns})
        for spec in metas:
            members_ok = np.all([~np.isnan(out[m].to_numpy()) for m in spec.members], axis=0)
            if spec.family == "mean":
                out.loc[here & members_ok, spec.id] = build(spec).predict(withoos[here & members_ok])
                continue
            taught = before & members_ok
            if len(set(season_of[taught].tolist())) < meta_warm:
                continue
            model = build(spec)
            try:
                model.fit(withoos[taught], y_all[taught])
                go = here & members_ok
                out.loc[go, spec.id] = model.predict(withoos[go])
                states.setdefault(spec.id, {})[int(season)] = model.state
            except Exception as exc:  # noqa: BLE001
                log.warning("%s failed for %s: %s", spec.name, season, exc)
        if progress:
            progress(step + 1, len(asked))
    return out, states


# ==== scoring =====================================================================================
def metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = evaluate.held(p)
    return {"games": int(len(p)), "logloss": float(evaluate.losses(p, y).mean()),
            "brier": float(((p - y) ** 2).mean()), "calibration": evaluate.calibration_error(p, y),
            "sharpness": float(np.abs(p - 0.5).mean()), "right": int(evaluate.hits(p, y).sum()),
            "expected_right": float(np.maximum(p, 1 - p).sum())}


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def paired(first: np.ndarray, second: np.ndarray, y: np.ndarray, weeks: np.ndarray) -> dict:
    """first against second on log loss: edge > 0 means first was better. The
    standard error treats weeks, not games, as independent (games in a week
    share their news); p is one-sided, for 'first is better'."""
    d = evaluate.losses(second, y) - evaluate.losses(first, y)
    n = len(d)
    if n < 2:
        return {"games": n, "edge": float("nan"), "se": float("nan"), "low": float("nan"), "high": float("nan"),
                "p": 1.0}
    keys, where = np.unique(weeks, return_inverse=True)
    mean = float(d.mean())
    sums, counts = np.bincount(where, weights=d), np.bincount(where).astype(float)
    W = len(keys)
    var = (W / max(W - 1, 1)) * float(((sums - counts * mean) ** 2).sum()) / n ** 2
    se = math.sqrt(var) if var > 0 else 0.0
    p = 1 - _phi(mean / se) if se > 0 else (0.0 if mean > 0 else 1.0)
    return {"games": n, "weeks": W, "edge": mean, "se": se, "low": mean - 1.96 * se, "high": mean + 1.96 * se,
            "p": p}


def holm(pvalues: dict[str, float], tried: int | None = None) -> dict[str, float]:
    """Holm's step-down adjustment: each p-value made fair for how many were tried.
    `tried` counts hypotheses tested in earlier runs as well, which only ever
    makes the adjustment stricter."""
    ranked = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, running, out = max(len(ranked), tried or 0), 0.0, {}
    for i, (key, p) in enumerate(ranked):
        running = max(running, min(1.0, (m - i) * p))
        out[key] = running
    return out


def encompassing(base: np.ndarray, other: np.ndarray, y: np.ndarray) -> dict:
    """Does `other` carry information `base` does not? y ~ a + b*logit(base) + c*(logit(other) - logit(base)).
    c clearly above zero says yes; c near zero says it is redundant given `base`.
    (Fitted on the games scored - a diagnostic, not a forecast.)"""
    lb, lo = logit(base), logit(other)
    X = np.column_stack([np.ones(len(y)), lb, lo - lb])
    beta = fit_logistic(X, y, 0.0)
    p = sigmoid(X @ beta)
    cov = np.linalg.pinv((X * (p * (1 - p))[:, None]).T @ X)
    se = float(math.sqrt(max(cov[2, 2], 0.0)))
    return {"weight": float(beta[2]), "se": se, "z": float(beta[2] / se) if se else 0.0}


def view_correlation(a: np.ndarray, b: np.ndarray, market: np.ndarray) -> float:
    """How alike two strategies' disagreements with the market are (log-odds less the market's)."""
    va, vb = logit(a) - logit(market), logit(b) - logit(market)
    if va.std() < 1e-9 or vb.std() < 1e-9:
        return float("nan")
    return float(np.corrcoef(va, vb)[0, 1])


def pool(first: np.ndarray, second: np.ndarray, y: np.ndarray, weeks: np.ndarray) -> dict:
    """ACQL picks credited a week, first against second (scorecards.pool_card)."""
    return scorecards.pool_card(first, second, y, weeks)


def picks_paired(first: np.ndarray, second: np.ndarray, y: np.ndarray, weeks: np.ndarray) -> dict:
    """ACQL picks credited a week, first against second, with a one-sided p for
    'first takes more'. Each strategy takes its likelier side (evaluate.hits);
    weeks are the independent units, as in `paired`."""
    d = evaluate.hits(evaluate.held(first), y).astype(float) - evaluate.hits(evaluate.held(second), y).astype(float)
    keys, where = np.unique(weeks, return_inverse=True)
    W = len(keys)
    if W < 2:
        return {"games": int(len(d)), "weeks": W, "edge": float("nan"), "se": float("nan"),
                "low": float("nan"), "high": float("nan"), "p": 1.0}
    per_week = np.bincount(where, weights=d)
    mean = float(per_week.mean())
    se = float(per_week.std(ddof=1) / math.sqrt(W))
    p = 1 - _phi(mean / se) if se > 0 else (0.0 if mean > 0 else 1.0)
    return {"games": int(len(d)), "weeks": W, "edge": mean, "se": se, "low": mean - 1.96 * se,
            "high": mean + 1.96 * se, "p": p, "flips": int((d != 0).sum())}


CONTEXTS = {
    "line under 3": lambda f: f["abs_market"] < 3,
    "line 3 to 7": lambda f: (f["abs_market"] >= 3) & (f["abs_market"] < 7),
    "line 7 or more": lambda f: f["abs_market"] >= 7,
    "models agree (spread below the week's usual)": lambda f: f["apart"] <= f["typical"],
    "models apart": lambda f: f["apart"] > f["typical"],
    "weeks 1-4": lambda f: f["week"] <= 4,
    "weeks 5 on": lambda f: f["week"] > 4,
}


def score_window(frame, chances, specs, mask, *, with_context: bool = False, picks: bool = True) -> dict:
    """Every spec on the games in `mask` that every spec priced. `picks` adds
    the ACQL card - only meaningful when the chances are about being credited."""
    y = _answer(frame)
    weeks = frame["order"].to_numpy()
    pm, pd_ = chances[MARKET_SPEC.id].to_numpy(), chances[DEADEYE_SPEC.id].to_numpy()
    out = {}
    for spec in specs:
        p = chances[spec.id].to_numpy()
        m = mask & ~np.isnan(p)
        if m.sum() < 20:
            continue
        row = {**metrics(p[m], y[m]), "seasons": sorted({int(s) for s in frame.loc[m, "season"]}),
               "vs_deadeye": paired(p[m], pd_[m], y[m], weeks[m]),
               "vs_market": paired(p[m], pm[m], y[m], weeks[m]),
               "pool_vs_deadeye": pool(p[m], pd_[m], y[m], weeks[m]) if picks else None,
               "picks_vs_deadeye": picks_paired(p[m], pd_[m], y[m], weeks[m]) if picks else None,
               "picks_vs_market": picks_paired(p[m], pm[m], y[m], weeks[m]) if picks else None,
               "view_corr_deadeye": view_correlation(p[m], pd_[m], pm[m]),
               "beyond_market": encompassing(pm[m], p[m], y[m]) if spec.id != MARKET_SPEC.id else None,
               "beyond_deadeye": encompassing(pd_[m], p[m], y[m]) if spec.id != DEADEYE_SPEC.id else None}
        if with_context:
            row["contexts"] = {}
            for label, rule in CONTEXTS.items():
                cm = m & np.asarray(rule(frame).fillna(False), dtype=bool)
                if cm.sum() >= 60:
                    row["contexts"][label] = {"games": int(cm.sum()),
                                              **{k: v for k, v in paired(p[cm], pd_[cm], y[cm], weeks[cm]).items()
                                                 if k in ("edge", "low", "high")}}
        out[spec.id] = row
    return out


# ==== the leak check ==============================================================================
def sealed(history: pd.DataFrame, timing: str, specs: list[Spec], cut: int, seed: int = 11,
           target: str = "credited") -> tuple[bool, str]:
    """Walk to week `cut` twice - as it is, and with every result from `cut`
    on shuffled (scores and margins, so the team ratings are spoiled too) -
    and check that nothing priced up to `cut` moved."""
    draw = np.random.default_rng(seed)
    spoiled = history.copy()
    later = (spoiled["season"] * 100 + spoiled["week"]).to_numpy() >= cut
    for col in ("home_points", "away_points"):
        spoiled.loc[later, col] = draw.permutation(spoiled.loc[later, col].to_numpy())
    spoiled.loc[later, "actual"] = spoiled.loc[later, "home_points"] - spoiled.loc[later, "away_points"]
    numeric = [c for c in spoiled.columns if c.startswith(("m:", "line_")) and pd.api.types.is_float_dtype(spoiled[c])]
    after = (spoiled["season"] * 100 + spoiled["week"]).to_numpy() > cut
    for col in numeric:
        spoiled.loc[after, col] = draw.permutation(spoiled.loc[after, col].to_numpy())
    clean_t = table(history, timing, universe=results_universe(history, verse=False), target=target)
    dirty_t = table(spoiled, timing, universe=results_universe(spoiled, verse=False), target=target)
    a, _ = walk(clean_t, specs, until=cut)
    b, _ = walk(dirty_t, specs, until=cut)
    ka = clean_t["order"].to_numpy() <= cut
    kb = dirty_t["order"].to_numpy() <= cut
    ga, gb = clean_t.loc[ka, "game"].to_numpy(), dirty_t.loc[kb, "game"].to_numpy()
    if len(ga) != len(gb) or (ga != gb).any():
        return False, "the games up to the cut differ when later results are scrambled"
    for spec in specs:
        x, z = a.loc[ka, spec.id].to_numpy(), b.loc[kb, spec.id].to_numpy()
        if not np.allclose(x, z, equal_nan=True, atol=1e-9):
            moved = int((~np.isclose(x, z, equal_nan=True, atol=1e-9)).sum())
            return False, f"{spec.name}: {moved} chances up to {cut} moved when later results were scrambled"
    priced = int(np.isfinite(a.loc[ka].to_numpy(dtype=float)).any(axis=1).sum())
    return True, f"{priced} games priced up to {cut}; none moved when every later result was scrambled"


# ==== archive, registry, freeze ===================================================================
def data_fingerprint(frame: pd.DataFrame, with_answer: bool = False) -> str:
    cols = [c for c in ("game", "order", "market", "credited", "actual") + (("y",) if with_answer else ())
            if c in frame.columns]
    return hashlib.sha1(frame[cols].to_csv(index=False).encode()).hexdigest()[:12]


def registry_path() -> Path:
    return folder() / "registry.jsonl"


def registry() -> list[dict]:
    from .journal import read
    return read(registry_path())


def closed_specs(protocol_id: str, track: str | None = None) -> set[str]:
    """Every candidate ever tried under this protocol (and track): not proposed again as if new."""
    return {r["spec"]["id"] for r in registry() if r.get("protocol") == protocol_id and "spec" in r
            and (track is None or r.get("track") == track)}


def test_openings(protocol_id: str) -> int:
    return sum(1 for r in registry() if r.get("protocol") == protocol_id and r.get("kind") == "test-opened")


def archive(frame: pd.DataFrame, chances: pd.DataFrame, specs: list[Spec], timing: str, where: Path,
            dev_mask: np.ndarray | None = None, test_mask: np.ndarray | None = None, *,
            track: str | None = None, held_name: str = "test") -> dict:
    """Every strategy's chance for every game, beside the result: the run's record of what each said."""
    cols = ["game", "season", "week", "order", "home", "away", "market", "pool_line", "pool_favourite",
            "credited", "actual"] + (["y"] if track else [])
    body = frame[[c for c in cols if c in frame.columns]].copy()
    body.insert(0, "timing", timing)
    if track:
        body.insert(1, "track", track)
    if dev_mask is None:
        dev_mask = test_mask = np.zeros(len(frame), dtype=bool)
    body["kind"] = np.where(test_mask, held_name, np.where(dev_mask, "development", "not scored"))
    for spec in specs:
        body[spec.id] = chances[spec.id].round(6)
    raw = body.to_csv(index=False).encode()
    path = where / (f"predictions-{track}-{timing}.csv.gz" if track else f"predictions-{timing}.csv.gz")
    with open(path, "wb") as plain, gzip.GzipFile(filename="", mode="wb", fileobj=plain, mtime=0) as fh:
        fh.write(raw)
    return {"file": path.name, "rows": int(len(body)), "sha256": hashlib.sha256(raw).hexdigest()}


def freeze(finalists: list[str] | dict, where: Path, run_id: str, protocol: dict = PROTOCOL) -> dict:
    """The finalists (a list, or one list per track), written down before anything held back is scored."""
    body = {"run": run_id, "protocol": protocol["id"], "protocol_mark": protocol_mark(protocol), "made": time.time(),
            "finalists": dict(finalists) if isinstance(finalists, dict) else list(finalists)}
    body["mark"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    path = where / "freeze.json"
    if path.exists():
        raise RuntimeError("this run's finalists are already frozen")
    path.write_text(json.dumps(body, indent=1), encoding="utf-8")
    return body


# ==== a whole run =================================================================================
@dataclass
class Timing:
    timing: str
    frame: pd.DataFrame
    chances: pd.DataFrame
    specs: list[Spec]
    states: dict
    dev_mask: np.ndarray
    test_mask: np.ndarray
    dev: dict
    test: dict = field(default_factory=dict)
    sealed: tuple | None = None
    track: str = ""


def _masks(frame: pd.DataFrame, chances: pd.DataFrame, specs: list[Spec],
           held: list[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Development and held-back games: answered, and priced by every strategy."""
    every = ~np.isnan(_answer(frame))
    for spec in specs:
        every &= ~np.isnan(chances[spec.id].to_numpy())
    test = frame["season"].isin(PROTOCOL["test_seasons"] if held is None else held).to_numpy()
    return every & ~test, every & test


def run_timing(history, timing, universe, rated, *, auto=True, progress=None, closed=frozenset()) -> Timing:
    frame = table(history, timing, universe=universe, rated=rated)
    specs = first_round()
    chances, states = walk(frame, specs, progress=progress)
    dev_mask, _ = _masks(frame, chances, specs)
    dev = score_window(frame, chances, specs, dev_mask)
    if auto:
        more = second_round(specs, dev, set(closed))
        if more:
            specs = specs + more
            chances, more_states = walk(frame, specs, oos=chances)
            states.update(more_states)
    dev_mask, test_mask = _masks(frame, chances, specs)
    dev = score_window(frame, chances, specs, dev_mask, with_context=True)
    return Timing(timing, frame, chances, specs, states, dev_mask, test_mask, dev)


def choose_finalists(t: Timing, closed: set[str] = frozenset()) -> tuple[list[str], dict]:
    """Holm over every candidate's development result - counting every candidate
    ever tried under this protocol, not just this run's; the best of each family go forward."""
    cands = [s for s in t.specs if not s.baseline and s.id in t.dev]
    family = len({s.id for s in cands} | (set(closed) - {MARKET_SPEC.id, DEADEYE_SPEC.id}))
    p_dead = holm({s.id: t.dev[s.id]["vs_deadeye"]["p"] for s in cands}, family)
    p_mkt = holm({s.id: t.dev[s.id]["vs_market"]["p"] for s in cands}, family)
    for s in cands:
        t.dev[s.id]["holm_vs_deadeye"], t.dev[s.id]["holm_vs_market"] = p_dead[s.id], p_mkt[s.id]
    best: dict[str, Spec] = {}
    for s in cands:
        if s.family not in best or t.dev[s.id]["logloss"] < t.dev[best[s.family].id]["logloss"]:
            best[s.family] = s
    ranked = sorted(best.values(), key=lambda s: t.dev[s.id]["logloss"])[:PROTOCOL["max_finalists"]]
    return [s.id for s in ranked], {"tried": len(cands), "family": family}


def score_test(t: Timing, finalists: list[str], frozen: dict) -> dict:
    if not frozen or frozen.get("finalists") != list(finalists):
        raise RuntimeError("the test seasons are only scored for finalists frozen beforehand")
    specs = [s for s in t.specs if s.id in finalists or s.baseline]
    out = score_window(t.frame, t.chances, specs, t.test_mask)
    p_dead = holm({i: out[i]["vs_deadeye"]["p"] for i in finalists if i in out})
    for i in finalists:
        if i in out:
            out[i]["holm_vs_deadeye"] = p_dead[i]
    return out


def gates(spec_id: str, t: Timing, *, leak_ok: bool | None, faulty_share: float) -> dict[str, bool]:
    d, x = t.dev.get(spec_id, {}), t.test.get(spec_id)
    if x is None:
        return {"is a finalist": False}
    alpha, ded = PROTOCOL["alpha"], t.test[DEADEYE_SPEC.id]
    return {
        "test: 150+ games and 30+ weeks": x["games"] >= PROTOCOL["min_test_games"]
                                           and x["vs_deadeye"].get("weeks", 0) >= PROTOCOL["min_test_weeks"],
        "development: beats Deadeye (Holm)": d.get("holm_vs_deadeye", 1.0) < alpha and d["vs_deadeye"]["edge"] > 0,
        "test: beats Deadeye (Holm)": x.get("holm_vs_deadeye", 1.0) < alpha and x["vs_deadeye"]["edge"] > 0,
        "test: beats the market": x["vs_market"]["p"] < alpha and x["vs_market"]["edge"] > 0,
        "test: calibration no worse": x["calibration"] <= ded["calibration"] + PROTOCOL["calibration_slack"],
        "test: ACQL picks not clearly worse": (x["pool_vs_deadeye"].get("high") is None
                                               or x["pool_vs_deadeye"]["high"] >= 0),
        "leak check passed": leak_ok is True,
        "data clean (<1% rows faulty)": faulty_share < 0.01,
    }


def status(spec: Spec, t: Timing, gate: dict | None) -> str:
    if spec.baseline:
        return "baseline"
    d = t.dev.get(spec.id)
    if d is None:
        return "insufficient data"
    if gate and all(gate.values()):
        return "nominated"
    redundant = (abs(d["vs_deadeye"]["edge"]) < 2 * d["vs_deadeye"]["se"]
                 and (d.get("view_corr_deadeye") or 0) >= PROTOCOL["redundant_correlation"])
    if redundant:
        return "redundant with Deadeye"
    if d["vs_deadeye"]["high"] < 0:
        return "failed: clearly worse than Deadeye"
    if spec.id in t.test:
        return "finalist, not promoted"
    if d.get("holm_vs_deadeye", 1.0) >= PROTOCOL["alpha"]:
        return "failed: no edge on development after correction"
    return "not a finalist"


def run(*, timings=None, auto: bool = True, leak_check: bool = True, progress=None) -> dict:
    """The whole lab: every timing walked, development chosen, finalists frozen, test scored, gates, archive,
    registry. Returns the results; writes data/training/lab/runs/<id>/ and data/training/lab/latest/."""
    from .journal import append, code_version
    started = time.time()
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    faulty = sum(i.rows for i in notes.of("error"))
    faulty_share = faulty / max(len(history) + faulty, 1)
    universe = results_universe(history)
    rated = rating_columns(universe)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    where = folder() / "runs" / run_id
    where.mkdir(parents=True, exist_ok=True)
    closed = closed_specs(PROTOCOL["id"])
    timings = timings or [PROTOCOL["primary_timing"], *PROTOCOL["diagnostic_timings"]]
    done: dict[str, Timing] = {}
    for timing in timings:
        tell = (lambda d, o, _t=timing: progress(f"{_t} seasons", d, o)) if progress else None
        done[timing] = run_timing(history, timing, universe, rated, auto=auto, progress=tell, closed=closed)
    primary = done[PROTOCOL["primary_timing"]]
    finalists, tried = choose_finalists(primary, closed)
    for timing, t in done.items():
        if t is not primary:
            choose_finalists(t, closed)
    frozen = freeze(finalists, where, run_id)
    reg = registry_path()
    append(reg, {"kind": "test-opened", "protocol": PROTOCOL["id"], "run": run_id, "made": time.time(),
                 "finalists": finalists, "freeze": frozen["mark"]})
    for timing, t in done.items():
        t.test = score_test(t, finalists if t is primary else
                            [i for i in finalists if i in t.dev], frozen if t is primary else
                            {**frozen, "finalists": [i for i in finalists if i in t.dev]})
    leak = None
    if leak_check:
        quick = [s for s in primary.specs if s.baseline or s.id in finalists or s.family == "elo"]
        cut_season = PROTOCOL["test_seasons"][0] - 2
        leak = sealed(history, primary.timing, quick, cut_season * 100 + 8)
        primary.sealed = leak
    out = {"run": run_id, "protocol": PROTOCOL, "protocol_mark": protocol_mark(), "lab": LAB_VERSION,
           "code": code_version(), "made": started, "took": None, "faulty_rows": faulty,
           "faulty_share": faulty_share, "finalists": finalists, "tried": tried["tried"],
           "holm_family": tried["family"], "tried_before": sorted(closed),
           "test_openings": test_openings(PROTOCOL["id"]), "leak": leak, "timings": {}, "archive": {}}
    nominee = None
    for timing, t in done.items():
        info = {"games": int(len(t.frame)), "dev_games": int(t.dev_mask.sum()), "test_games": int(t.test_mask.sum()),
                "dev_seasons": sorted({int(s) for s in t.frame.loc[t.dev_mask, "season"]}),
                "test_seasons": sorted({int(s) for s in t.frame.loc[t.test_mask, "season"]}),
                "data": data_fingerprint(t.frame), "specs": {}}
        for spec in t.specs:
            gate = gates(spec.id, t, leak_ok=leak[0] if leak else None, faulty_share=faulty_share) \
                if t is primary and spec.id in t.test and not spec.baseline else None
            st = status(spec, t, gate)
            info["specs"][spec.id] = {"spec": spec.describe(), "dev": t.dev.get(spec.id), "test": t.test.get(spec.id),
                                      "gates": gate, "status": st, "tried_before": spec.id in closed,
                                      "states": {str(k): v for k, v in t.states.get(spec.id, {}).items()}}
            if t is primary:
                append(reg, {"kind": "candidate", "protocol": PROTOCOL["id"], "run": run_id, "timing": timing,
                             "data": info["data"], "code": out["code"], "spec": spec.describe(), "status": st,
                             "dev_logloss": (t.dev.get(spec.id) or {}).get("logloss"),
                             "dev_vs_deadeye": ((t.dev.get(spec.id) or {}).get("vs_deadeye") or {}).get("edge"),
                             "test_vs_deadeye": ((t.test.get(spec.id) or {}).get("vs_deadeye") or {}).get("edge"),
                             "made": time.time()})
                if st == "nominated" and (nominee is None or
                                          t.test[spec.id]["vs_deadeye"]["edge"] > t.test[nominee]["vs_deadeye"]["edge"]):
                    nominee = spec.id
        out["timings"][timing] = info
        out["archive"][timing] = archive(t.frame, t.chances, t.specs, timing, where, t.dev_mask, t.test_mask)
    out["closing_reference"] = closing_reference(done)
    out["nominee"] = nominee
    out["took"] = time.time() - started
    (where / "results.json").write_text(json.dumps(out, indent=1, default=_json), encoding="utf-8")
    nominee_body = {"run": run_id, "nominee": nominee, "made": time.time(),
                    "note": "A nomination only. Deadeye stays the champion until the owner switches it."}
    (folder() / "nominee.json").write_text(json.dumps(nominee_body, indent=1), encoding="utf-8")
    from . import labreport
    text = labreport.write(out, where)
    latest = folder() / "latest"
    latest.mkdir(exist_ok=True)
    (latest / "report.md").write_text(text, encoding="utf-8")
    (latest / "results.json").write_text(json.dumps(out, indent=1, default=_json), encoding="utf-8")
    out["folder"] = str(where)
    return out


# ==== strategy-lab-2: the two objectives, apart ===================================================
def with_members(specs: list[Spec], ids: list[str]) -> list[Spec]:
    """These specs and every spec an average or meta-learner among them is built from, in their order."""
    by_id, want, todo = {s.id: s for s in specs}, set(), list(ids)
    while todo:
        i = todo.pop()
        if i in want or i not in by_id:
            continue
        want.add(i)
        todo.extend(by_id[i].members)
    return [s for s in specs if s.id in want]


def _dev_family(track: str, cands: set[str]) -> int:
    """The Holm family on development: this run's candidates, every one tried under
    strategy-lab-1 (the same development seasons) and every one tried before on this track."""
    earlier = closed_specs(PROTOCOL["id"]) | closed_specs(PROTOCOL_2["id"], track)
    return len(set(cands) | (earlier - {MARKET_SPEC.id, DEADEYE_SPEC.id}))


def _key(track: str, against: str) -> str:
    """The comparison a track is judged on: log loss (probability) or picks a week (acql)."""
    return ("vs_" if track == "probability" else "picks_vs_") + against


def run_track_timing(history, timing, universe, rated, track: str, *, auto=True, progress=None,
                     closed=frozenset()) -> Timing:
    """One track at one timing: taught, walked and scored on that track's own answer."""
    p2 = PROTOCOL_2
    picks = track == "acql"
    frame = table(history, timing, universe=universe, rated=rated, target=TRACKS[track]["target"])
    specs = first_round()
    chances, states = walk(frame, specs, warm=p2["warm_up_seasons"], meta_warm=p2["meta_warm_up_seasons"],
                           progress=progress)
    dev_mask, _ = _masks(frame, chances, specs, p2["seen_seasons"])
    dev = score_window(frame, chances, specs, dev_mask, picks=picks)
    if auto:
        more = second_round(specs, dev, set(closed))
        if more:
            specs = specs + more
            chances, more_states = walk(frame, specs, warm=p2["warm_up_seasons"],
                                        meta_warm=p2["meta_warm_up_seasons"], oos=chances)
            states.update(more_states)
    dev_mask, seen_mask = _masks(frame, chances, specs, p2["seen_seasons"])
    dev = score_window(frame, chances, specs, dev_mask, with_context=True, picks=picks)
    return Timing(timing, frame, chances, specs, states, dev_mask, seen_mask, dev, track=track)


def _rank(track: str, row: dict) -> tuple:
    if track == "probability":
        return (row["logloss"],)
    return (-row["picks_vs_deadeye"]["edge"], row["logloss"])


def choose_track_finalists(t: Timing) -> tuple[list[str], dict]:
    """Each track's finalists from development alone, on that track's own measure;
    Holm over every candidate tried for it (and under strategy-lab-1); the best of each family."""
    track = t.track
    cands = [s for s in t.specs if not s.baseline and s.id in t.dev]
    family = _dev_family(track, {s.id for s in cands})
    for against in ("deadeye", "market"):
        adjusted = holm({s.id: t.dev[s.id][_key(track, against)]["p"] for s in cands}, family)
        for s in cands:
            t.dev[s.id][f"holm_vs_{against}"] = adjusted[s.id]
    best: dict[str, Spec] = {}
    for s in cands:
        if s.family not in best or _rank(track, t.dev[s.id]) < _rank(track, t.dev[best[s.family].id]):
            best[s.family] = s
    ranked = sorted(best.values(), key=lambda s: _rank(track, t.dev[s.id]))[:PROTOCOL_2["max_finalists"]]
    return [s.id for s in ranked], {"tried": len(cands), "family": family}


def track_status(spec: Spec, t: Timing, finalists: list[str]) -> str:
    if spec.baseline:
        return "baseline"
    d = t.dev.get(spec.id)
    if d is None:
        return "insufficient data"
    edge = d[_key(t.track, "deadeye")]
    if t.track == "probability":
        if (abs(edge["edge"]) < 2 * edge["se"]
                and (d.get("view_corr_deadeye") or 0) >= PROTOCOL_2["redundant_correlation"]):
            return "redundant with Deadeye"
    elif edge.get("flips", 1) == 0:
        return "redundant with Deadeye (the same picks)"
    if edge["high"] < 0:
        return "failed: clearly worse than Deadeye on development"
    if spec.id in finalists:
        return ("finalist: awaiting locked weeks" if edge["edge"] > 0 else
                "finalist, not ahead of Deadeye on development (locked for the record; cannot be nominated)")
    if d.get("holm_vs_deadeye", 1.0) >= PROTOCOL_2["alpha"]:
        return "not a finalist (no edge on development after correction)"
    return "not a finalist"


def champions_path() -> Path:
    return folder() / "champions.json"


def run2(*, timings=None, auto: bool = True, leak_check: bool = True, progress=None) -> dict:
    """strategy-lab-2: both tracks walked at every timing, finalists chosen on development and frozen,
    the seen seasons scored for the record, leak check per track, archive, registry, champions.json.
    Writes data/training/lab/runs/<id>/ and data/training/lab/latest/. Changes no pick."""
    from .journal import append, code_version
    p2 = PROTOCOL_2
    started = time.time()
    notes = data.Notes()
    history = data.check(data.history(notes=notes), notes)
    faulty = sum(i.rows for i in notes.of("error"))
    faulty_share = faulty / max(len(history) + faulty, 1)
    universe = results_universe(history)
    rated = rating_columns(universe)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    where = folder() / "runs" / run_id
    where.mkdir(parents=True, exist_ok=True)
    timings = timings or [p2["primary_timing"], *p2["diagnostic_timings"]]
    primary_timing = p2["primary_timing"] if p2["primary_timing"] in timings else timings[0]
    done: dict[tuple[str, str], Timing] = {}
    closed = {track: closed_specs(p2["id"], track) for track in TRACKS}
    for track in TRACKS:
        for timing in timings:
            tell = (lambda d, o, _t=f"{track}, {timing}": progress(f"{_t} seasons", d, o)) if progress else None
            done[(track, timing)] = run_track_timing(history, timing, universe, rated, track, auto=auto,
                                                     progress=tell, closed=closed[track])
    finalists, tried = {}, {}
    for track in TRACKS:
        finalists[track], tried[track] = choose_track_finalists(done[(track, primary_timing)])
        for timing in timings:
            if timing != primary_timing:
                choose_track_finalists(done[(track, timing)])
    frozen = freeze(finalists, where, run_id, p2)
    reg = registry_path()
    append(reg, {"kind": "seen-scored", "protocol": p2["id"], "run": run_id, "made": time.time(),
                 "finalists": finalists, "freeze": frozen["mark"], "note": p2["seen_note"]})
    for (track, _timing), t in done.items():
        specs = [s for s in t.specs if s.id in finalists[track] or s.baseline]
        t.test = score_window(t.frame, t.chances, specs, t.test_mask, picks=(track == "acql"))
    leak: dict[str, tuple | None] = {track: None for track in TRACKS}
    if leak_check:
        cut = (p2["seen_seasons"][0] - 2) * 100 + 8
        for track in TRACKS:
            t = done[(track, primary_timing)]
            quick = with_members(t.specs, [s.id for s in t.specs if s.baseline or s.id in finalists[track]
                                           or s.family == "elo"])
            leak[track] = sealed(history, primary_timing, quick, cut, target=TRACKS[track]["target"])
            t.sealed = leak[track]
    out = {"run": run_id, "protocol": p2, "protocol_mark": protocol_mark(p2), "lab": LAB_VERSION,
           "code": code_version(), "made": started, "took": None, "faulty_rows": faulty, "faulty_share": faulty_share,
           "primary_timing": primary_timing, "finalists": finalists, "freeze": frozen["mark"],
           "leak": leak, "tracks": {}, "archive": {}}
    for track in TRACKS:
        tr = {"target": TRACKS[track]["target"], "finalists": finalists[track], "tried": tried[track]["tried"],
              "holm_family": tried[track]["family"], "tried_before": sorted(closed[track]), "timings": {}}
        for timing in timings:
            t = done[(track, timing)]
            info = {"games": int(len(t.frame)), "dev_games": int(t.dev_mask.sum()),
                    "seen_games": int(t.test_mask.sum()),
                    "dev_seasons": sorted({int(s) for s in t.frame.loc[t.dev_mask, "season"]}),
                    "seen_seasons": sorted({int(s) for s in t.frame.loc[t.test_mask, "season"]}),
                    "data": data_fingerprint(t.frame, with_answer=True), "specs": {}}
            for spec in t.specs:
                st = track_status(spec, t, finalists[track])
                info["specs"][spec.id] = {"spec": spec.describe(), "dev": t.dev.get(spec.id),
                                          "seen": t.test.get(spec.id), "status": st,
                                          "tried_before": spec.id in closed[track],
                                          "states": {str(k): v for k, v in t.states.get(spec.id, {}).items()}}
                if timing == primary_timing:
                    d = t.dev.get(spec.id) or {}
                    append(reg, {"kind": "candidate", "protocol": p2["id"], "track": track, "run": run_id,
                                 "timing": timing, "data": info["data"], "code": out["code"], "spec": spec.describe(),
                                 "status": st, "dev_logloss": d.get("logloss"),
                                 "dev_vs_deadeye": (d.get(_key(track, "deadeye")) or {}).get("edge"),
                                 "seen_vs_deadeye": ((t.test.get(spec.id) or {}).get(_key(track, "deadeye"))
                                                     or {}).get("edge"),
                                 "made": time.time()})
            tr["timings"][timing] = info
            out["archive"][f"{track}-{timing}"] = archive(t.frame, t.chances, t.specs, timing, where, t.dev_mask,
                                                          t.test_mask, track=track, held_name="seen")
        out["tracks"][track] = tr
    out["closing_reference"] = {track: closing_reference({k: done[(track, k)] for k in timings}) for track in TRACKS}
    out["took"] = time.time() - started
    body = json.dumps(out, indent=1, default=_json)
    (where / "results.json").write_text(body, encoding="utf-8")
    write_champions(run_id, finalists, None)
    from . import labreport
    text = labreport.write2(out, where)
    latest = folder() / "latest"
    latest.mkdir(exist_ok=True)
    (latest / "report.md").write_text(text, encoding="utf-8")
    (latest / "results.json").write_text(body, encoding="utf-8")
    out["folder"] = str(where)
    return out


def write_champions(run_id: str, finalists: dict, scored: dict | None) -> dict:
    """champions.json: one champion per track. Deadeye holds both until a finalist passes every
    gate on the locked weeks - and even then it is only a nomination; the switch is the owner's."""
    body = {"protocol": PROTOCOL_2["id"], "run": run_id, "made": time.time(), "tracks": {}}
    for track in TRACKS:
        got = (scored or {}).get(track) or {}
        body["tracks"][track] = {
            "question": TRACKS[track]["question"], "champion": DEADEYE_SPEC.id, "champion_name": DEADEYE_SPEC.name,
            "finalists": finalists.get(track, []), "nominee": got.get("nominee"),
            "why": got.get("why") or "no locked week has been scored yet - only forecasts locked before the "
                                      "deadline can earn a nomination"}
    body["note"] = "A nomination only. Deadeye stays the champion on both tracks until the owner switches it."
    champions_path().write_text(json.dumps(body, indent=1, default=_json), encoding="utf-8")
    return body


def closing_reference(done: dict[str, Timing]) -> dict:
    """On games every timing shares: the market at each timing, and Deadeye at each, against the closing line."""
    frames = {k: t.frame.set_index("game") for k, t in done.items()}
    common = None
    for f in frames.values():
        common = f.index if common is None else common.intersection(f.index)
    if common is None or not len(common):
        return {}
    any_t = next(iter(done.values()))
    base = frames[any_t.timing].loc[common]
    line, fav = base["pool_line"].to_numpy(dtype=float), base["pool_favourite"].fillna("").tolist()
    straight = any_t.track == "probability"
    if straight:
        line, fav = np.full(len(base), np.nan), [""] * len(base)
    y = _answer(base)
    keep = ~np.isnan(y)
    out = {"games": int(keep.sum())}
    closing = curve_chance(base["line_closing"].to_numpy(dtype=float), line, fav) if "line_closing" in base else None
    if closing is not None:
        out["closing market"] = metrics(closing[keep], y[keep])
    if straight and "win_closing" in base:      # the closing moneyline, de-vigged - a reference only
        ml = base["win_closing"].to_numpy(dtype=float)
        has = keep & ~np.isnan(ml)
        if has.sum() >= 20:
            out["closing moneyline (de-vigged)"] = {**metrics(ml[has], y[has]), "games": int(has.sum())}
    for k, f in frames.items():
        sub = f.loc[common]
        out[f"{k} market"] = metrics(sub["p_market"].to_numpy()[keep], y[keep])
        out[f"{k} Deadeye"] = metrics(sub["p_deadeye"].to_numpy()[keep], y[keep])
    return out


def _json(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)
