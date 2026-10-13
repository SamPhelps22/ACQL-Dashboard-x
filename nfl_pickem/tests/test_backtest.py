import pandas as pd
import pytest

from nflpickem import backtest as bt
from nflpickem.backtest import eval_seasons, run_backtest


def test_holdout_is_protected(cfg):
    cfg = {**cfg, "backtest": {**cfg["backtest"], "holdout_seasons": [2104]}}
    with pytest.raises(ValueError):
        eval_seasons(cfg, [2101, 2102, 2103, 2104], include_holdout=False, seasons=[2104])
    assert 2104 not in eval_seasons(cfg, [2101, 2102, 2103, 2104], include_holdout=False)
    assert 2104 in eval_seasons(cfg, [2101, 2102, 2103, 2104], include_holdout=True)


def test_chronological_train_test_separation(synth_con, cfg, monkeypatch):
    seen = []
    real = bt.tune_and_fit

    def spy(train, valid, cols, c):
        seen.append((train.kickoff_utc.max(), valid.kickoff_utc.min(), valid.kickoff_utc.max(),
                     set(train.season), set(valid.season)))
        return real(train, valid, cols, c)

    monkeypatch.setattr(bt, "tune_and_fit", spy)
    res = run_backtest(synth_con, cfg, save=False)
    assert seen
    for (tr_max, va_min, va_max, tr_s, va_s), season in zip(seen, res.seasons):
        assert tr_max < va_min
        assert max(tr_s) < season and va_s == {season - 1}
        test_min = res.predictions.loc[res.predictions.season == season, "kickoff_utc"].min()
        assert va_max < test_min


def test_backtest_outputs_and_storage(synth_con, cfg):
    res = run_backtest(synth_con, cfg)
    assert set(res.metrics.model) == set(bt.ALL_MODELS)
    stored = synth_con.execute("SELECT count(*) FROM backtest_predictions WHERE backtest_id=?",
                               [res.backtest_id]).fetchone()[0]
    assert stored == len(res.predictions)
    # predictions were timestamped before scoring; cutoffs precede kickoffs
    assert (res.predictions.cutoff <= res.predictions.kickoff_utc).all()
    # weekly allocation: each week's points are 1..N
    wk = res.weekly[res.weekly.model == "blend"]
    assert (wk.max_points == wk.games * (wk.games + 1) / 2).all()
    meta, preds = bt.latest_backtest(synth_con)
    assert meta["backtest_id"] == res.backtest_id and len(preds) == len(res.predictions)


def test_backtest_reproducible(synth_con, cfg):
    a = run_backtest(synth_con, cfg, save=False)
    b = run_backtest(synth_con, cfg, save=False)
    cols = ["game_id", "market", "elo", "logistic", "gbm", "blend"]
    pd.testing.assert_frame_equal(a.predictions[cols], b.predictions[cols])
    pd.testing.assert_frame_equal(a.weekly, b.weekly)


def test_learned_blend_uses_only_prior_oos(synth_con, cfg):
    cfg = {**cfg, "blend": {**cfg["blend"], "mode": "learned"}}
    res = run_backtest(synth_con, cfg, save=False)
    first = res.season_log[0]
    assert first["weights_source"] == "fixed"  # no prior out-of-sample predictions yet
