"""Probability calibration, fitted only on out-of-fold predictions from earlier seasons."""

from __future__ import annotations

import numpy as np

EPS = 1e-6


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


class Platt:
    """p -> sigmoid(a * logit(p) + b), fitted by maximum likelihood (lightly regularised toward identity)."""

    def __init__(self, a: float = 1.0, b: float = 0.0) -> None:
        self.a, self.b = a, b

    def fit(self, p, y, ridge: float = 1.0) -> "Platt":
        z, y = logit(p), np.asarray(y, dtype=float)
        a, b = 1.0, 0.0
        for _ in range(50):                      # Newton steps on the penalised log likelihood
            q = sigmoid(a * z + b)
            w = q * (1 - q)
            ga = np.sum((q - y) * z) + ridge * (a - 1.0)
            gb = np.sum(q - y) + ridge * b
            haa = np.sum(w * z * z) + ridge
            hab = np.sum(w * z)
            hbb = np.sum(w) + ridge
            det = haa * hbb - hab * hab
            if det <= 0:
                break
            da = (hbb * ga - hab * gb) / det
            db = (haa * gb - hab * ga) / det
            a, b = a - da, b - db
            if abs(da) + abs(db) < 1e-10:
                break
        self.a, self.b = float(a), float(b)
        return self

    def __call__(self, p) -> np.ndarray:
        return sigmoid(self.a * logit(p) + self.b)

    def state(self) -> dict:
        return {"a": self.a, "b": self.b}


class Identity:
    def fit(self, p, y, ridge: float = 1.0) -> "Identity":
        return self

    def __call__(self, p) -> np.ndarray:
        return np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)

    def state(self) -> dict:
        return {}


def make(kind: str):
    return Platt() if kind == "platt" else Identity()
