"""Models B (logistic regression) and C (gradient boosting), plus calibration.

Both predict P(home win). Preprocessing (imputation, scaling) lives inside a
scikit-learn Pipeline so it is fitted on training rows only. Hyper-parameters
are chosen on a chronologically later validation block, never on test data.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)
EPS = 1e-6


def clip(p) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)


def logit(p) -> np.ndarray:
    p = clip(p)
    return np.log(p / (1 - p))


def safe_log_loss(y, p) -> float:
    return float(log_loss(np.asarray(y, dtype=int), clip(p), labels=[0, 1]))


# ------------------------------------------------------------------ logistic
def make_logistic(C: float = 0.1, seed: int = 42) -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(C=C, l1_ratio=0.0, max_iter=5000, random_state=seed)),
    ])


# ----------------------------------------------------------------------- gbm
def resolve_gbm_library(preference: str = "auto") -> str:
    order = ["lightgbm", "xgboost", "sklearn"] if preference == "auto" else [preference]
    for lib in order:
        try:
            if lib == "lightgbm":
                import lightgbm  # noqa: F401
            elif lib == "xgboost":
                import xgboost  # noqa: F401
            return lib
        except ImportError:
            continue
    return "sklearn"


GBM_GRID = {"max_leaves": [4, 8], "n_estimators": [150, 300], "learning_rate": [0.03]}


def make_gbm(library: str, max_leaves: int = 4, n_estimators: int = 200,
             learning_rate: float = 0.03, seed: int = 42):
    """Deliberately small, regularised trees: NFL outcomes are noisy."""
    if library == "lightgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(num_leaves=max_leaves, n_estimators=n_estimators, learning_rate=learning_rate,
                              min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                              reg_lambda=1.0, random_state=seed, n_jobs=1, verbose=-1, deterministic=True)
    if library == "xgboost":
        from xgboost import XGBClassifier
        return XGBClassifier(max_leaves=max_leaves, grow_policy="lossguide", max_depth=0,
                             n_estimators=n_estimators, learning_rate=learning_rate, min_child_weight=10,
                             subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, random_state=seed,
                             n_jobs=1, eval_metric="logloss", tree_method="hist")
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_leaf_nodes=max(2, max_leaves), max_iter=n_estimators,
                                          learning_rate=learning_rate, min_samples_leaf=40,
                                          l2_regularization=1.0, random_state=seed)


# --------------------------------------------------------------- calibration
class Calibrator:
    """Platt (logistic on logit p) or isotonic calibration of probabilities."""

    def __init__(self, method: str = "none"):
        self.method = method
        self._m = None

    def fit(self, p, y) -> "Calibrator":
        y = np.asarray(y, dtype=int)
        if self.method == "platt":
            self._m = LogisticRegression(C=1e6, max_iter=1000).fit(logit(p).reshape(-1, 1), y)
        elif self.method == "isotonic":
            self._m = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(clip(p), y)
        return self

    def transform(self, p) -> np.ndarray:
        if self.method == "none" or self._m is None:
            return clip(p)
        if self.method == "platt":
            return self._m.predict_proba(logit(p).reshape(-1, 1))[:, 1]
        return clip(self._m.predict(clip(p)))


def choose_calibration(p, y, setting: str) -> Calibrator:
    """Return a fitted calibrator. 'auto' keeps calibration only if, fitted on the
    first half (chronological) of the held-out predictions, it lowers log loss on
    the second half; the chosen method is then refit on all held-out rows."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=int)
    if setting != "auto":
        return Calibrator(setting).fit(p, y) if len(p) >= 50 or setting == "none" else Calibrator("none")
    if len(p) < 200:
        return Calibrator("none")
    half = len(p) // 2
    best, best_ll = "none", safe_log_loss(y[half:], p[half:])
    for method in ("platt", "isotonic"):
        ll = safe_log_loss(y[half:], Calibrator(method).fit(p[:half], y[:half]).transform(p[half:]))
        if ll < best_ll - 1e-4:
            best, best_ll = method, ll
    return Calibrator(best).fit(p, y)


# ------------------------------------------------------------- model fitting
@dataclass
class FittedModels:
    feature_columns: list[str]
    logistic: Pipeline | None = None
    gbm: object | None = None
    gbm_library: str = "sklearn"
    params: dict = field(default_factory=dict)
    calibrators: dict = field(default_factory=dict)

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        X = X[self.feature_columns].astype(float)
        out = {}
        if self.logistic is not None:
            out["logistic"] = self.logistic.predict_proba(X)[:, 1]
        if self.gbm is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out["gbm"] = self.gbm.predict_proba(X)[:, 1]
        for k, cal in self.calibrators.items():
            if k in out:
                out[k] = cal.transform(out[k])
        return out


def _xy(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    d = df[df["home_result"].isin([0.0, 1.0])]  # ties are excluded from classifier training
    return d[cols].astype(float), d["home_result"].astype(int).to_numpy()


def tune_and_fit(train: pd.DataFrame, valid: pd.DataFrame | None, cols: list[str], cfg: dict) -> FittedModels:
    """Select hyper-parameters on ``valid`` (strictly later than ``train``), then
    refit on train+valid. Without a validation block, use defaults."""
    mcfg = cfg["models"]
    seed = int(mcfg.get("random_seed", 42))
    lib = resolve_gbm_library(mcfg.get("gbm_library", "auto"))
    Xtr, ytr = _xy(train, cols)
    best_C, best_gbm = 0.1, {"max_leaves": 4, "n_estimators": 200, "learning_rate": 0.03}
    if valid is not None and len(valid):
        Xva, yva = _xy(valid, cols)
        if len(yva) >= 30:
            scores = {}
            for C in mcfg.get("logistic_C_grid", [0.01, 0.1, 1.0]):
                scores[C] = safe_log_loss(yva, make_logistic(C, seed).fit(Xtr, ytr).predict_proba(Xva)[:, 1])
            best_C = min(scores, key=scores.get)
            gscores = {}
            for leaves, n, lr in product(*GBM_GRID.values()):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m = make_gbm(lib, leaves, n, lr, seed).fit(Xtr, ytr)
                    gscores[(leaves, n, lr)] = safe_log_loss(yva, m.predict_proba(Xva)[:, 1])
            leaves, n, lr = min(gscores, key=gscores.get)
            best_gbm = {"max_leaves": leaves, "n_estimators": n, "learning_rate": lr}
        full = pd.concat([train, valid])
        Xtr, ytr = _xy(full, cols)
    logistic = make_logistic(best_C, seed).fit(Xtr, ytr)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        gbm = make_gbm(lib, seed=seed, **best_gbm).fit(Xtr, ytr)
    return FittedModels(feature_columns=cols, logistic=logistic, gbm=gbm, gbm_library=lib,
                        params={"logistic_C": best_C, "gbm": best_gbm, "gbm_library": lib,
                                "train_rows": int(len(ytr))})


def logistic_coefficients(models: FittedModels) -> pd.DataFrame:
    """Standardised coefficients (association, not causation)."""
    if models.logistic is None:
        return pd.DataFrame()
    imp = models.logistic.named_steps["impute"]
    names = list(imp.get_feature_names_out(models.feature_columns))
    coef = models.logistic.named_steps["model"].coef_[0]
    return pd.DataFrame({"feature": names, "coefficient": coef}).sort_values(
        "coefficient", key=np.abs, ascending=False)


def logistic_contributions(models: FittedModels, X: pd.DataFrame) -> pd.DataFrame:
    """Per-feature contribution (standardised value x coefficient, in log-odds) for
    each row. Describes what moved this model's output; it is not causal."""
    if models.logistic is None:
        return pd.DataFrame()
    pipe = models.logistic
    Z = pipe.named_steps["scale"].transform(pipe.named_steps["impute"].transform(X[models.feature_columns].astype(float)))
    names = list(pipe.named_steps["impute"].get_feature_names_out(models.feature_columns))
    coef = pipe.named_steps["model"].coef_[0]
    return pd.DataFrame(Z * coef, columns=names, index=X.index)
