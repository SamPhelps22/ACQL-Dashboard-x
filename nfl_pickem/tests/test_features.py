import numpy as np
import pandas as pd
import pytest

from nflpickem.features import (LeakageError, build_features, compute_cutoffs, model_feature_columns,
                                FeatureSettings, validate_point_in_time)

from conftest import make_game


def test_cutoffs_slate_and_per_game():
    g = pd.DataFrame([make_game("a", 2020, 1, "2020-09-10 20:00", "H", "A"),
                      make_game("b", 2020, 1, "2020-09-13 17:00", "X", "Y")])
    c = compute_cutoffs(g, "slate", 1.0)
    assert c["a"] == c["b"] == pd.Timestamp("2020-09-10 19:00")
    c2 = compute_cutoffs(g, "per_game", 2.0)
    assert c2["b"] == pd.Timestamp("2020-09-13 15:00")
    c3 = compute_cutoffs(g, "slate", 1.0, as_of=pd.Timestamp("2020-09-09"))
    assert c3["b"] == pd.Timestamp("2020-09-09")


def test_features_pass_point_in_time_validation(synth_inputs, cfg):
    f = build_features(*synth_inputs, cfg)
    validate_point_in_time(f)
    assert (f["home_feature_ts"].dropna() < f.loc[f.home_feature_ts.notna(), "cutoff"]).all()
    assert (f["cutoff"] <= f["kickoff_utc"]).all()
    for c in model_feature_columns(FeatureSettings.from_config(cfg["features"])):
        assert c in f.columns


def test_validation_detects_leakage(synth_inputs, cfg):
    f = build_features(*synth_inputs, cfg)
    bad = f.copy()
    bad.loc[5, "home_feature_ts"] = bad.loc[5, "kickoff_utc"] + pd.Timedelta(hours=3)
    with pytest.raises(LeakageError):
        validate_point_in_time(bad)
    bad2 = f.copy()
    bad2.loc[5, "odds_captured_at"] = bad2.loc[5, "cutoff"] + pd.Timedelta(minutes=1)
    with pytest.raises(LeakageError):
        validate_point_in_time(bad2)


def test_no_future_leakage_changing_future_results_does_not_change_past_features(synth_inputs, cfg):
    games, stats, odds = synth_inputs
    base = build_features(games, stats, odds, cfg)
    pivot = games[games.season == games.season.max() - 1].kickoff_utc.median()
    g2, s2 = games.copy(), stats.copy()
    future = g2.kickoff_utc > pivot
    g2.loc[future, "home_score"], g2.loc[future, "away_score"] = 99, 0
    fut_ids = set(g2.loc[future, "game_id"])
    s2.loc[s2.game_id.isin(fut_ids), "off_epa_sum"] = 500.0
    changed = build_features(g2, s2, odds, cfg)
    cols = [c for c in model_feature_columns(FeatureSettings.from_config(cfg["features"]))] + ["elo_home_prob"]
    past = base.cutoff < pivot
    pd.testing.assert_frame_equal(base.loc[past, cols].reset_index(drop=True),
                                  changed.loc[past, cols].reset_index(drop=True))
    # sanity: something after the pivot did change
    assert not np.allclose(base.loc[~past, "elo_diff"].to_numpy(), changed.loc[~past, "elo_diff"].to_numpy())


def test_game_not_finished_by_cutoff_is_excluded():
    # Team H plays at 17:00 and again at 19:00 the same day (artificial). The
    # first game's state is available at 21:00, after the second game's cutoff.
    from nflpickem.config import load_config
    cfg = load_config(use_local=False, overrides={"pool": {"cutoff_mode": "per_game"}})
    g = pd.DataFrame([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 30, 0),
                      make_game("b", 2020, 2, "2020-09-13 19:00", "H", "B")])
    stats = pd.DataFrame([{"game_id": "a", "team": t, "plays": 60, "off_epa_sum": 6.0 if t == "H" else -6.0,
                           "off_success_sum": 30, "pass_plays": 30, "pass_epa_sum": 1, "explosive_plays": 5,
                           "turnovers": 1, "def_plays": 60, "def_epa_sum": -6.0 if t == "H" else 6.0,
                           "def_success_sum": 30, "def_explosive_plays": 5, "takeaways": 1, "source": "t"}
                          for t in ("H", "A")])
    f = build_features(g, stats, pd.DataFrame(columns=["game_id", "captured_at", "provider", "home_moneyline",
                                                       "away_moneyline", "home_spread"]), cfg)
    row = f.set_index("game_id").loc["b"]
    assert pd.isna(row.home_feature_ts)
    assert row.home_elo == 1505


def test_rest_bye_short_week(cfg):
    g = pd.DataFrame([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 20, 10),
                      make_game("b", 2020, 2, "2020-09-17 17:00", "H", "B", 20, 10),
                      make_game("c", 2020, 3, "2020-10-04 17:00", "C", "H")])
    f = build_features(g, pd.DataFrame(columns=["game_id", "team"]), pd.DataFrame(
        columns=["game_id", "captured_at", "provider", "home_moneyline", "away_moneyline", "home_spread"]), cfg)
    f = f.set_index("game_id")
    assert f.loc["b", "home_short_week"] == 1 and f.loc["b", "home_rest_days"] == 4
    assert f.loc["c", "away_off_bye"] == 1
    assert f.loc["a", "home_first_game"] == 1 and f.loc["a", "rest_diff"] == 0


def test_tie_label(cfg):
    g = pd.DataFrame([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 17, 17)])
    f = build_features(g, pd.DataFrame(columns=["game_id", "team"]), pd.DataFrame(
        columns=["game_id", "captured_at", "provider", "home_moneyline", "away_moneyline", "home_spread"]), cfg)
    assert f.iloc[0].home_result == 0.5


def test_missing_odds_flagged(synth_inputs, cfg):
    games, stats, odds = synth_inputs
    drop = games.game_id.iloc[:10]
    f = build_features(games, stats, odds[~odds.game_id.isin(drop)], cfg)
    f = f.set_index("game_id")
    assert (f.loc[drop, "odds_status"] == "missing").all()
    assert f.loc[drop, "market_home_prob"].isna().all()
