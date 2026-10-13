import numpy as np
import pandas as pd
import pytest

from nflpickem.features import FeatureSettings, build_features, model_feature_columns, validate_point_in_time
from nflpickem.football import FEATURE_GROUPS, _ewma_states
from nflpickem.ingest.nflverse import aggregate_pbp_detail
from nflpickem.models.ml import MarketResidualModel


@pytest.fixture()
def full_inputs(synth_con):
    from nflpickem.backtest import load_football_inputs, load_inputs
    return (*load_inputs(synth_con), load_football_inputs(synth_con))


def test_football_features_present_and_point_in_time(full_inputs, cfg):
    games, stats, odds, fb = full_inputs
    f = build_features(games, stats, odds, cfg, **fb)
    validate_point_in_time(f)
    for cols in FEATURE_GROUPS.values():
        for c in cols:
            assert c in f.columns
    later = f[f.season == f.season.max()]
    assert later["pass_matchup"].notna().mean() > 0.9
    assert (f["football_feature_ts"].dropna() < f.loc[f.football_feature_ts.notna(), "cutoff"]).all()


def test_football_no_future_leakage(full_inputs, cfg):
    games, stats, odds, fb = full_inputs
    base = build_features(games, stats, odds, cfg, **fb)
    pivot = games[games.season == games.season.max() - 1].kickoff_utc.median()
    fut = set(games.loc[games.kickoff_utc > pivot, "game_id"])
    d2 = fb["detail"].copy()
    d2.loc[d2.game_id.isin(fut), "dropback_epa_sum"] = 999.0
    q2 = fb["qbs"].copy()
    q2.loc[q2.game_id.isin(fut), "epa_sum"] = 999.0
    changed = build_features(games, stats, odds, cfg, detail=d2, qbs=q2)
    cols = sum(FEATURE_GROUPS.values(), [])
    past = base.cutoff < pivot
    pd.testing.assert_frame_equal(base.loc[past, cols].reset_index(drop=True),
                                  changed.loc[past, cols].reset_index(drop=True))
    assert not np.allclose(base.loc[~past, "qb_rating_diff"].fillna(0), changed.loc[~past, "qb_rating_diff"].fillna(0))


def test_missing_detail_gives_nan_features(synth_inputs, cfg):
    f = build_features(*synth_inputs, cfg)
    assert f["pass_matchup"].isna().all()


def test_feature_groups_selection(cfg):
    fs = FeatureSettings.from_config({**cfg["features"], "groups": ["qb_rating"]})
    cols = model_feature_columns(fs)
    assert "qb_rating_diff" in cols and "pass_matchup" not in cols
    with pytest.raises(ValueError):
        model_feature_columns(fs, ["bogus"])


def test_ewma_shrinkage_toward_prior():
    df = pd.DataFrame({"team": ["A"] * 3, "game_id": ["g1", "g2", "g3"], "season": [2020] * 3,
                       "kickoff_utc": pd.to_datetime(["2020-09-10", "2020-09-17", "2020-09-24"]),
                       "x": [1.0, 1.0, 1.0]})
    prior = pd.DataFrame({"x": [0.0]}, index=[2020])
    st = _ewma_states(df, "team", ["x"], None, 8, prior, prior_weight=3)
    vals = st["x"].to_numpy()
    assert 0 < vals[0] < vals[1] < vals[2] < 1  # shrunk, converging toward the observed 1.0


def test_aggregate_pbp_detail():
    rows = []
    base = {"game_id": "g", "posteam": "KC", "defteam": "BAL", "success": 1, "interception": 0, "fumble_lost": 0,
            "qb_kneel": 0, "qb_spike": 0, "two_point_attempt": 0, "qb_hit": 0, "cpoe": np.nan, "drive": 1,
            "fixed_drive_result": "Touchdown", "wp": 0.5, "passer_player_id": "Q1", "passer_player_name": "QB",
            "rusher_player_id": None, "third_down_converted": 0, "third_down_failed": 0}
    rows.append({**base, "play_type": "pass", "epa": 1.0, "yards_gained": 25, "qb_dropback": 1, "sack": 0,
                 "qb_scramble": 0, "down": 1, "yardline_100": 30, "cpoe": 10.0})
    rows.append({**base, "play_type": "pass", "epa": -2.0, "yards_gained": -7, "qb_dropback": 1, "sack": 1,
                 "qb_scramble": 0, "down": 3, "yardline_100": 15, "third_down_failed": 1, "wp": 0.97})
    rows.append({**base, "play_type": "run", "epa": 0.4, "yards_gained": 5, "qb_dropback": 0, "sack": 0,
                 "qb_scramble": 0, "down": 2, "yardline_100": 10, "passer_player_id": None, "rusher_player_id": "R1"})
    d, q = aggregate_pbp_detail(pd.DataFrame(rows))
    r = d.iloc[0]
    assert r.dropbacks == 2 and r.sacks == 1 and r.dropback_epa_sum == pytest.approx(-1.0)
    assert r.rush_plays == 1 and r.early_plays == 2 and r.early_pass == 1
    assert r.third_att == 1 and r.third_conv == 0 and r.rz_drives == 1 and r.rz_td_drives == 1
    assert r.neutral_plays == 2 and r.explosive_passes == 1 and r.cpoe_n == 1
    assert q.iloc[0].qb_id == "Q1" and q.iloc[0].dropbacks == 2


def test_market_residual_reduces_to_market_with_heavy_penalty():
    rng = np.random.default_rng(0)
    n = 800
    m = rng.uniform(0.2, 0.8, n)
    y = (rng.random(n) < m).astype(float)
    X = pd.DataFrame({"noise": rng.normal(size=n)})
    mod = MarketResidualModel(alpha=1e6).fit(X, m, y)
    p = mod.predict_proba_market(X, m)
    assert np.corrcoef(p, m)[0, 1] > 0.99
    assert abs(mod.coef_[2]) < 1e-3
    # a genuinely informative feature gets weight with a light penalty
    sig = rng.normal(size=n)
    truth = 1 / (1 + np.exp(-(np.log(m / (1 - m)) + 0.8 * sig)))
    y2 = (rng.random(n) < truth).astype(float)
    mod2 = MarketResidualModel(alpha=1.0).fit(pd.DataFrame({"sig": sig}), m, y2)
    assert mod2.coef_[2] > 0.4
    assert np.isnan(mod2.predict_proba_market(pd.DataFrame({"sig": [0.0]}), np.array([np.nan]))[0])
