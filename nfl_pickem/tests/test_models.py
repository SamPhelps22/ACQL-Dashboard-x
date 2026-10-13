import numpy as np
import pandas as pd
import pytest

from nflpickem.features import FeatureSettings, build_features, model_feature_columns
from nflpickem.models.ml import Calibrator, choose_calibration, make_logistic, resolve_gbm_library, tune_and_fit


def test_imputation_fitted_on_training_only():
    tr = pd.DataFrame({"x": [1.0, 2.0, 3.0, np.nan], "y": [0, 0, 1, 1]})
    m = make_logistic().fit(tr[["x"]], tr["y"])
    assert m.named_steps["impute"].statistics_[0] == pytest.approx(2.0)
    te = pd.DataFrame({"x": [100.0, np.nan]})
    m.predict_proba(te)  # NaN handled with the training median
    assert m.named_steps["impute"].statistics_[0] == pytest.approx(2.0)


def test_calibrators_monotone_and_bounded():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 500)
    y = (rng.random(500) < p ** 1.5).astype(int)
    for method in ("platt", "isotonic"):
        c = Calibrator(method).fit(p, y)
        out = c.transform(np.linspace(0.05, 0.95, 20))
        assert np.all(np.diff(out) >= -1e-9) and np.all((out > 0) & (out < 1))
    assert choose_calibration(p[:50], y[:50], "auto").method == "none"  # too few rows


def test_gbm_library_resolution():
    assert resolve_gbm_library("auto") in {"lightgbm", "xgboost", "sklearn"}
    assert resolve_gbm_library("sklearn") == "sklearn"


def test_models_predict_probabilities(synth_inputs, cfg):
    f = build_features(*synth_inputs, cfg)
    cols = model_feature_columns(FeatureSettings.from_config(cfg["features"]))
    done = f[f.game_status == "final"]
    seasons = sorted(done.season.unique())
    m = tune_and_fit(done[done.season < seasons[-2]], done[done.season == seasons[-2]], cols, cfg)
    p = m.predict(done[done.season == seasons[-1]])
    for k in ("logistic", "gbm"):
        assert np.all((p[k] > 0) & (p[k] < 1))
    assert m.params["train_rows"] == len(done[(done.season < seasons[-1]) & done.home_result.isin([0, 1])])
