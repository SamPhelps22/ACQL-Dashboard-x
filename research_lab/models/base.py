"""What every model is: shown a point-in-time snapshot and the week's blinded games, it
returns one row per game. Nothing else reaches it."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config
from ..data.store import Snapshot

SQRT2 = np.sqrt(2.0)


def norm_cdf(x):
    from math import erf
    x = np.asarray(x, dtype=float)
    return 0.5 * (1.0 + np.vectorize(erf)(x / SQRT2))


def norm_ppf(p):
    """Inverse normal CDF (Acklam's rational approximation; |error| < 1.2e-9)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549671010422069e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    q = np.where(p < 0.5, p, 1 - p)
    out = np.empty_like(q)
    lo = q < 0.02425
    t = np.sqrt(-2 * np.log(q[lo]))
    out[lo] = (((((c[0]*t+c[1])*t+c[2])*t+c[3])*t+c[4])*t+c[5]) / ((((d[0]*t+d[1])*t+d[2])*t+d[3])*t+1)
    m = ~lo
    r = q[m] - 0.5
    s = r * r
    out[m] = (((((a[0]*s+a[1])*s+a[2])*s+a[3])*s+a[4])*s+a[5])*r / (((((b[0]*s+b[1])*s+b[2])*s+b[3])*s+b[4])*s+1)
    x = np.where(p < 0.5, out, -out)
    # one Halley step against the exact CDF
    e = norm_cdf(x) - p
    u = e * np.sqrt(2 * np.pi) * np.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def margin_to_p(margin, sd=config.MARGIN_SD):
    return np.clip(norm_cdf(np.asarray(margin, float) / sd), 1e-4, 1 - 1e-4)


def p_to_margin(p, sd=config.MARGIN_SD):
    return norm_ppf(p) * sd


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


class Model:
    name = "model"
    version = "0"
    info_set = config.WEEK_START
    uses_market = False
    provenance = "nflverse games + play-by-play"

    def predict(self, snap: Snapshot, week: pd.DataFrame) -> pd.DataFrame:
        """Columns: game_id, p_home, and optionally exp_margin, exp_total, margin_sd, missing (dict)."""
        raise NotImplementedError


# ---- small numpy learners (no scipy / sklearn dependency) ----------------------------------
def ridge(X: np.ndarray, y: np.ndarray, lam: float, w: np.ndarray | None = None,
          penalize_intercept: bool = False) -> np.ndarray:
    """Ridge with an unpenalised intercept in column 0 (callers add it)."""
    w = np.ones(len(y)) if w is None else w
    XtW = X.T * w
    P = lam * np.eye(X.shape[1])
    if not penalize_intercept:
        P[0, 0] = 0.0
    return np.linalg.solve(XtW @ X + P, XtW @ y)


def logistic(X: np.ndarray, y: np.ndarray, lam: float = 1.0, w: np.ndarray | None = None,
             iters: int = 50, offset: np.ndarray | None = None) -> np.ndarray:
    """L2-penalised logistic regression by Newton's method; column 0 is the (unpenalised) intercept.

    `y` may be fractional (a tie = 0.5)."""
    n, k = X.shape
    w = np.ones(n) if w is None else w
    off = np.zeros(n) if offset is None else offset
    beta = np.zeros(k)
    P = lam * np.eye(k)
    P[0, 0] = 1e-8
    for _ in range(iters):
        eta = X @ beta + off
        p = expit(eta)
        g = X.T @ (w * (p - y)) + P @ beta
        H = (X.T * (w * p * (1 - p))) @ X + P
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


class Standardizer:
    """Learns each column's centre and scale (and fill value) on the training rows only."""

    def fit(self, X: np.ndarray) -> "Standardizer":
        self.mu = np.nanmean(X, axis=0)
        self.mu = np.where(np.isnan(self.mu), 0.0, self.mu)
        sd = np.nanstd(X, axis=0)
        self.sd = np.where((sd > 1e-9) & ~np.isnan(sd), sd, 1.0)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mu) / self.sd
        return np.where(np.isnan(Z), 0.0, Z)
