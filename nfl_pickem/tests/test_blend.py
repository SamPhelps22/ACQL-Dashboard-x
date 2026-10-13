import numpy as np
import pandas as pd
import pytest

from nflpickem.models.ensemble import blend, learn_weights, normalize, simplex_grid, weights_from_config


def test_weights_from_config_default_70_30():
    w = weights_from_config({"market_weight": 0.7, "ml_weights": {"elo": 1, "logistic": 1, "gbm": 1}})
    assert w["market"] == pytest.approx(0.7)
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["elo"] == pytest.approx(0.1)


def test_blend_probability_space():
    p = blend({"market": [0.8], "elo": [0.6]}, {"market": 0.7, "elo": 0.3})
    assert p[0] == pytest.approx(0.74)


def test_blend_logit_space_between_inputs():
    p = blend({"market": [0.8], "elo": [0.6]}, {"market": 0.5, "elo": 0.5}, space="logit")
    assert 0.6 < p[0] < 0.8


def test_blend_missing_market_renormalises():
    p = blend({"market": [np.nan, 0.9], "elo": [0.6, 0.6]}, {"market": 0.7, "elo": 0.3})
    assert p[0] == pytest.approx(0.6)
    assert p[1] == pytest.approx(0.81)


def test_blend_all_missing_is_nan():
    p = blend({"market": [np.nan], "elo": [np.nan]}, {"market": 0.5, "elo": 0.5})
    assert np.isnan(p[0])


def test_blend_validation():
    with pytest.raises(ValueError):
        normalize({"market": 0, "elo": 0})
    with pytest.raises(ValueError):
        blend({"market": [0.5]}, {"market": 1.0}, space="bogus")


def test_simplex_grid():
    g = simplex_grid(["a", "b", "c"], 0.5)
    assert len(g) == 6 and all(sum(w.values()) == pytest.approx(1) for w in g)


def test_learn_weights_prefers_informative_component():
    rng = np.random.default_rng(0)
    truth = rng.uniform(0.2, 0.8, 600)
    y = (rng.random(600) < truth).astype(float)
    df = pd.DataFrame({"market": truth, "elo": np.full(600, 0.5), "logistic": rng.uniform(0.2, 0.8, 600),
                       "gbm": np.full(600, 0.5), "home_result": y})
    w, _ = learn_weights(df, step=0.25)
    assert w["market"] >= 0.75


def test_learn_weights_needs_data():
    with pytest.raises(ValueError):
        learn_weights(pd.DataFrame({"market": [0.5], "elo": [0.5], "logistic": [0.5], "gbm": [0.5],
                                    "home_result": [1.0]}))


def test_blend_with_fallback_when_market_only_weights_and_no_odds():
    from nflpickem.models.ensemble import blend_with_fallback
    p = blend_with_fallback({"market": [np.nan, 0.7], "elo": [0.6, 0.6], "logistic": [0.8, 0.5], "gbm": [0.7, 0.5]},
                            {"market": 1.0})
    assert p[0] == pytest.approx(0.7) and p[1] == pytest.approx(0.7)
