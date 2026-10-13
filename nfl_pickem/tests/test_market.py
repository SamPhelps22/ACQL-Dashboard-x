import math

import pandas as pd
import pytest

from nflpickem.models.market import (american_to_implied, devig, market_probabilities, moneyline_home_probability,
                                     spread_home_probability)


@pytest.mark.parametrize("odds,expected", [(100, 0.5), (-100, 0.5), (150, 0.4), (-150, 0.6), (-400, 0.8), (300, 0.25)])
def test_american_to_implied(odds, expected):
    assert american_to_implied(odds) == pytest.approx(expected)


@pytest.mark.parametrize("bad", [None, "abc", 0, 50, -99, float("nan"), float("inf")])
def test_invalid_odds_are_nan(bad):
    assert math.isnan(american_to_implied(bad))


@pytest.mark.parametrize("method", ["multiplicative", "additive", "power"])
def test_devig_sums_to_one_and_removes_margin(method):
    qh, qa = american_to_implied(-150), american_to_implied(130)
    assert qh + qa > 1
    ph, pa = devig(qh, qa, method)
    assert ph + pa == pytest.approx(1.0)
    assert ph < qh and pa < qa
    assert 0.55 < ph < 0.6


def test_devig_multiplicative_exact():
    ph, pa = devig(0.6, 0.5)
    assert ph == pytest.approx(0.6 / 1.1)


def test_devig_symmetric_line():
    ph, _ = devig(american_to_implied(-110), american_to_implied(-110))
    assert ph == pytest.approx(0.5)


def test_devig_invalid():
    assert math.isnan(devig(float("nan"), 0.5)[0])
    with pytest.raises(ValueError):
        devig(0.5, 0.5, "bogus")


def test_moneyline_and_spread_probability():
    assert moneyline_home_probability(-200, 170) > 0.6
    assert spread_home_probability(0) == pytest.approx(0.5)
    assert spread_home_probability(-7) > 0.65  # home favoured by 7
    assert spread_home_probability(7) < 0.35
    assert math.isnan(spread_home_probability(None))


def test_market_probabilities_uses_only_pre_cutoff_snapshots_and_aggregates():
    cut = pd.Series({"g1": pd.Timestamp("2024-09-08 16:00")})
    odds = pd.DataFrame([
        {"game_id": "g1", "captured_at": pd.Timestamp("2024-09-07"), "provider": "a",
         "home_moneyline": -200, "away_moneyline": 170, "home_spread": -4.5},
        {"game_id": "g1", "captured_at": pd.Timestamp("2024-09-07"), "provider": "b",
         "home_moneyline": -150, "away_moneyline": 130, "home_spread": -3.0},
        # after the cutoff -> must be ignored
        {"game_id": "g1", "captured_at": pd.Timestamp("2024-09-08 17:00"), "provider": "a",
         "home_moneyline": 300, "away_moneyline": -400, "home_spread": 8.0},
    ])
    m = market_probabilities(odds, cut, stale_hours=48).iloc[0]
    expected = (moneyline_home_probability(-200, 170) + moneyline_home_probability(-150, 130)) / 2
    assert m.market_home_prob == pytest.approx(expected)
    assert m.odds_status == "current"
    assert m.odds_captured_at <= cut["g1"]


def test_stale_and_spread_fallback_and_closing_proxy():
    cut = pd.Series({"g1": pd.Timestamp("2024-09-08"), "g2": pd.Timestamp("2024-09-08")})
    odds = pd.DataFrame([
        {"game_id": "g1", "captured_at": pd.Timestamp("2024-09-01"), "provider": "a",
         "home_moneyline": None, "away_moneyline": None, "home_spread": -3.0},
        {"game_id": "g2", "captured_at": pd.NaT, "provider": "nflverse",
         "home_moneyline": -120, "away_moneyline": 100, "home_spread": -1.5},
    ])
    m = market_probabilities(odds, cut, stale_hours=24).set_index("game_id")
    assert m.loc["g1", "odds_status"] == "stale"
    assert m.loc["g1", "market_home_prob"] == pytest.approx(spread_home_probability(-3.0))
    assert m.loc["g2", "odds_status"] == "closing_proxy"
    m2 = market_probabilities(odds, cut, closing_line_proxy=False).set_index("game_id")
    assert "g2" not in m2.index
