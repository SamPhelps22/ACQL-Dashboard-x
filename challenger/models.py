"""The three independent baselines and the stacked Challenger model.

    Elo        challenger.elo's pregame chance, read straight off the features
    Logistic   L2 logistic regression on a short list of interpretable inputs
               (features.LR_FEATURES); missing values filled with the training
               median, inputs standardised on the training rows only
    Boosting   LightGBM on every difference, matchup and context feature;
               missing values handled natively
    Challenger a logistic stacker over the three models' logits, fitted on
               out-of-fold predictions from earlier seasons

Each model only ever sees the training rows it is fitted on; nothing is
fitted on the rows it predicts.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .calibration import logit


class LogisticModel:
    def __init__(self, features: tuple[str, ...], C: float) -> None:
        self.features = list(features)
        self.C = C

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "LogisticModel":
        from sklearn.linear_model import LogisticRegression

        A = X[self.features].astype(float)
        self.median = A.median()
        A = A.fillna(self.median).fillna(0.0)
        self.mean, self.std = A.mean(), A.std().replace(0, 1.0).fillna(1.0)
        self.model = LogisticRegression(C=self.C, max_iter=2000)
        self.model.fit(((A - self.mean) / self.std).to_numpy(), y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        A = X[self.features].astype(float).fillna(self.median).fillna(0.0)
        return self.model.predict_proba(((A - self.mean) / self.std).to_numpy())[:, 1]

    def coefficients(self) -> dict:
        return dict(zip(self.features, self.model.coef_[0].round(4).tolist())) | {"intercept": float(self.model.intercept_[0])}


class GbmModel:
    def __init__(self, features: list[str], params: dict, common: dict) -> None:
        self.features = list(features)
        self.params = dict(params)
        self.common = dict(common)

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "GbmModel":
        import lightgbm as lgb

        self.model = lgb.LGBMClassifier(**self.params, **self.common)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(X[self.features].astype(float), y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self.model.predict_proba(X[self.features].astype(float))[:, 1]

    def importance(self, top: int = 15) -> dict:
        gain = self.model.booster_.feature_importance("gain")
        order = np.argsort(-gain)[:top]
        return {self.features[i]: round(float(gain[i]), 1) for i in order}


class Stacker:
    """Logistic regression over [elo, logistic, boosting] logits."""

    def __init__(self, C: float = 1.0) -> None:
        self.C = C

    def fit(self, parts: np.ndarray, y: np.ndarray) -> "Stacker":
        from sklearn.linear_model import LogisticRegression

        self.model = LogisticRegression(C=self.C, max_iter=2000)
        self.model.fit(logit(parts), y)
        return self

    def predict(self, parts: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(logit(parts))[:, 1]

    def weights(self) -> dict:
        return {"elo": float(self.model.coef_[0][0]), "logistic": float(self.model.coef_[0][1]),
                "boosting": float(self.model.coef_[0][2]), "intercept": float(self.model.intercept_[0])}
