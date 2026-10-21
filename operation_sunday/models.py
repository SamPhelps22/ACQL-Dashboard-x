"""Candidate models. Each one is fitted only on rows it is handed (the
walk-forward decides which), labels are real outcomes only, and every fitted
state is plain numbers so it can be saved and reproduced exactly.

Status of each candidate (also in CANDIDATE_TABLE / docs):

  home_rate        designated simplest baseline (training home win rate)
  elo              Elo from published results, untuned literature defaults
  bayes_strength   Kalman team-strength posterior -> P(win), margin, total
  logistic         L2 logistic regression on all eligible football features
  situational      logistic on rest / travel / situational features only
  market_snapshot  de-vigged market at the cutoff; eligible ONLY when a
                   snapshot timestamped <= cutoff exists (live weeks)
  market_close     closing line -> P(win). BENCHMARK ONLY, never a Thursday input
  deadeye_line_proxy  Deadeye's line math (acql.analytics) on the CLOSING line.
                   A RECONSTRUCTED line-only proxy - not a Deadeye forecast.
  ens_*            ensembles over out-of-fold predictions (ensemble.py)
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd

from .features import FAMILIES, FEATURE_VERSION

EPS = 1e-6


def _phi(x):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(x, float) / math.sqrt(2)))


def clip(p):
    return np.clip(np.asarray(p, float), 0.01, 0.99)


def logit(p):
    p = clip(p)
    return np.log(p / (1 - p))


def decided(rows: pd.DataFrame) -> pd.DataFrame:
    """Training rows: finished, not a tie (ties carry no winner label)."""
    return rows[rows["home_win"].isin([0.0, 1.0])]


class Model:
    name = "model"
    kind = "football"           # football | market | benchmark | baseline | ensemble
    thursday_eligible = True    # may feed a Thursday forecast
    label = ""
    supports_margin = False
    supports_total = False
    params: dict = {}

    def config(self) -> dict:
        return {"name": self.name, "params": self.params, "feature_version": FEATURE_VERSION}

    @property
    def version(self) -> str:
        blob = json.dumps(self.config(), sort_keys=True, default=str).encode()
        return f"{self.name}@{hashlib.sha256(blob).hexdigest()[:10]}"

    def fit(self, train: pd.DataFrame) -> "Model":
        return self

    def state(self) -> dict:
        return {}

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def _out(self, rows, p, margin=None, total=None):
        p = clip(p)
        return pd.DataFrame({"p_home": p,
                             "exp_margin": margin if margin is not None else np.nan,
                             "exp_total": total if total is not None else np.nan}, index=rows.index)


class HomeRate(Model):
    name, kind, label = "home_rate", "baseline", "Training-set home win rate"

    def fit(self, train):
        d = decided(train[train["neutral"] == 0])
        self.rate = float(d["home_win"].mean()) if len(d) else 0.55
        return self

    def state(self):
        return {"rate": self.rate}

    def predict(self, rows):
        return self._out(rows, np.where(rows["neutral"] > 0, 0.5, getattr(self, "rate", 0.55)))


class EloModel(Model):
    name, label = "elo", "Elo (K=20, HFA 48, untuned defaults)"

    def predict(self, rows):
        hfa = np.where(rows["neutral"] > 0, 0, 48.0)
        return self._out(rows, 1 / (1 + 10 ** (-(rows["elo_diff"] + hfa) / 400)))


class BayesStrength(Model):
    name, label = "bayes_strength", "Kalman team-strength posterior"
    supports_margin = supports_total = True

    def fit(self, train):
        d = train[train["status"] == "final"]
        resid = (d["margin"] - d["kal_margin"]).to_numpy()
        self.sigma = float(np.sqrt(np.mean(resid ** 2))) if len(resid) > 50 else 13.5
        return self

    def state(self):
        return {"sigma": self.sigma}

    def predict(self, rows):
        sd = getattr(self, "sigma", 13.5)
        return self._out(rows, _phi(rows["kal_margin"] / sd), rows["kal_margin"].to_numpy(),
                         rows["kal_total"].to_numpy())


def fit_logistic(X, y, l2, w=None, iters=50):
    """Newton/IRLS L2 logistic regression; intercept unpenalised. Deterministic."""
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = np.full(k + 1, l2)
    pen[0] = 0.0
    w = np.ones(n) if w is None else w
    for _ in range(iters):
        z = Xb @ beta
        p = 1 / (1 + np.exp(-z))
        g = Xb.T @ (w * (p - y)) + pen * beta
        H = (Xb * (w * p * (1 - p))[:, None]).T @ Xb + np.diag(pen + 1e-9)
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


class Logistic(Model):
    """Standardisation and the L2 strength are fitted on training rows only;
    the strength is chosen on the most recent slice of the training window."""
    name, label = "logistic", "L2 logistic regression (football features)"
    GRID = (0.3, 3.0, 30.0, 300.0)
    VALID_GAMES = 400

    def __init__(self, families=("team_strength", "rest", "travel", "situational"), name=None, label=None):
        self.families = tuple(families)
        self.cols = [c for f in self.families for c in FAMILIES[f]]
        if name:
            self.name = name
        if label:
            self.label = label
        self.params = {"families": list(self.families), "grid": list(self.GRID), "valid_games": self.VALID_GAMES}
        if "market" in self.families:
            self.kind = "market"

    def _xy(self, d):
        X = d[self.cols].astype(float).to_numpy()
        return X, d["home_win"].to_numpy(float)

    def fit(self, train):
        d = decided(train).dropna(subset=self.cols)
        if len(d) < 50:
            self.beta = None
            return self
        d = d.sort_values("kickoff_utc")
        X, y = self._xy(d)
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        best, self.l2 = 1e18, self.GRID[1]
        if len(d) > 2 * self.VALID_GAMES:
            cut = len(d) - self.VALID_GAMES
            for l2 in self.GRID:
                b = fit_logistic(Z[:cut], y[:cut], l2)
                p = clip(1 / (1 + np.exp(-(np.hstack([np.ones((len(d) - cut, 1)), Z[cut:]]) @ b))))
                ll = -np.mean(y[cut:] * np.log(p) + (1 - y[cut:]) * np.log(1 - p))
                if ll < best - 1e-12:
                    best, self.l2 = ll, l2
        self.beta = fit_logistic(Z, y, self.l2)
        return self

    def state(self):
        if getattr(self, "beta", None) is None:
            return {"fitted": False}
        return {"cols": self.cols, "l2": self.l2, "beta": self.beta.round(8).tolist(),
                "mu": self.mu.round(8).tolist(), "sd": self.sd.round(8).tolist()}

    def predict(self, rows):
        if getattr(self, "beta", None) is None:
            return self._out(rows, np.full(len(rows), np.nan))
        X = rows[self.cols].astype(float).to_numpy()
        ok = ~np.isnan(X).any(1)
        Z = (np.nan_to_num(X) - self.mu) / self.sd
        p = 1 / (1 + np.exp(-(self.beta[0] + Z @ self.beta[1:])))
        p = np.where(ok, p, np.nan)
        return pd.DataFrame({"p_home": np.where(ok, clip(np.nan_to_num(p, nan=0.5)), np.nan),
                             "exp_margin": np.nan, "exp_total": np.nan}, index=rows.index)


class MarketSnapshotModel(Model):
    name, kind, label = "market_snapshot", "market", "De-vigged market at the cutoff (snapshot <= cutoff)"

    def predict(self, rows):
        p = 1 / (1 + np.exp(-rows["mkt_logit"].astype(float)))
        return pd.DataFrame({"p_home": p, "exp_margin": np.nan, "exp_total": np.nan}, index=rows.index)


class MarketClose(Model):
    name, kind, label = "market_close", "benchmark", "CLOSING line (retrospective benchmark only)"
    thursday_eligible = False
    supports_margin = True

    def predict(self, rows):
        s = rows["close_spread"].astype(float).to_numpy()
        p = np.where(np.isnan(s), np.nan, clip(_phi(np.nan_to_num(s) / 13.45)))
        return pd.DataFrame({"p_home": p, "exp_margin": s, "exp_total": rows["close_total"].to_numpy(float)},
                            index=rows.index)


class DeadeyeLineProxy(Model):
    """Isolated evaluation adapter: Deadeye's own line->chance math
    (acql.analytics.win_chance, ties counted half) applied to the CLOSING line.
    Labelled a RECONSTRUCTED LINE-ONLY PROXY. Actual recorded Deadeye cards are
    loaded separately (acql_rules.recorded_deadeye) when they exist."""
    name, kind = "deadeye_line_proxy", "benchmark"
    label = "Deadeye line-only proxy on closing line (RECONSTRUCTED, not a recorded Deadeye forecast)"
    thursday_eligible = False
    supports_margin = True

    def predict(self, rows):
        from acql import analytics  # read-only import of the production math
        out = []
        for s in rows["close_spread"].astype(float):
            if np.isnan(s):
                out.append(np.nan)
                continue
            wh, wa = analytics.win_chance(s), analytics.win_chance(-s)
            out.append(wh + (1 - wh - wa) / 2)
        return pd.DataFrame({"p_home": np.asarray(out, float), "exp_margin": rows["close_spread"].to_numpy(),
                             "exp_total": np.nan}, index=rows.index)


def base_candidates() -> list[Model]:
    return [
        HomeRate(), EloModel(), BayesStrength(), Logistic(),
        Logistic(("rest", "travel", "situational"), name="situational",
                 label="Situational/environmental logistic (rest, travel, site only)"),
        MarketSnapshotModel(), MarketClose(), DeadeyeLineProxy(),
    ]


def build(name: str) -> Model:
    for m in base_candidates():
        if m.name == name:
            return m
    raise KeyError(name)
