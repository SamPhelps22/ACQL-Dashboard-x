import math

import pandas as pd
import pytest

from nflpickem import pipeline, poollines
from nflpickem.confidence import ScoringRules, grade_pick


def test_need_and_estimate():
    assert poollines.need(7) == 7 and poollines.need(6.5) == 7 and poollines.need(13.5) == 14
    assert poollines.estimate(-3.0) is None
    assert poollines.estimate(-6.5) == ("home", 7.0)
    assert poollines.estimate(-7.0) == ("home", 8.0)
    assert poollines.estimate(10.5) == ("away", 11.0)
    assert poollines.estimate(float("nan")) is None


def test_credited_probability_favours_underdog_when_line_above_spread():
    p_home = 0.73                       # roughly a 7.5-point home favourite
    straight = poollines.credited_home_probability(p_home, None, None)
    lined = poollines.credited_home_probability(p_home, "home", 9.0)
    assert straight == pytest.approx(p_home)
    assert lined < 0.5 < straight       # must win by 9: the underdog is the likelier credited side
    assert poollines.credited_home_probability(0.5, "home", 7.0) < 0.5
    assert math.isnan(poollines.credited_home_probability(float("nan"), "home", 7.0))


def test_credited_side_rule():
    assert poollines.credited_side(30, 23, "home", 7.0) == "home"     # won by exactly the line
    assert poollines.credited_side(29, 23, "home", 7.0) == "away"
    assert poollines.credited_side(20, 13, "away", 6.5) == "home"     # away fav lost
    assert poollines.credited_side(13, 30, "away", 6.5) == "away"
    assert poollines.credited_side(17, 17, None, None) is None


def test_grade_pick_with_line():
    r = ScoringRules(points_mode="flat")
    assert grade_pick("DET", "KC", "DET", 27, 21, 1, r, "final", "KC", 8.0) == ("win", 1.0)
    assert grade_pick("KC", "KC", "DET", 27, 21, 1, r, "final", "KC", 8.0) == ("loss", 0.0)
    assert grade_pick("KC", "KC", "DET", 29, 21, 1, r, "final", "KC", 8.0) == ("win", 1.0)


def test_pipeline_uses_entered_lines_and_grades_with_posted_line(synth_con, cfg):
    cfg = {**cfg, "pool": {**cfg["pool"], "line_rule": "acql", "points_mode": "flat"}}
    season = int(synth_con.execute("SELECT max(season) FROM games").fetchone()[0])
    wk = synth_con.execute("SELECT game_id, home_team, away_team FROM games WHERE season=? AND week=3",
                           [season]).df()
    fav = wk.iloc[0].home_team
    poollines.set_lines(synth_con, season, 3, [(fav, 30.0)])          # an absurd line: dog must be picked
    rid, picks = pipeline.predict_week(synth_con, cfg, season, 3)
    row = picks.set_index("game_id").loc[wk.iloc[0].game_id]
    assert row.line_source == "entered" and row.pool_line == 30.0
    assert row.selected_team == wk.iloc[0].away_team
    assert (picks.confidence_points == 1).all()
    pipeline.freeze_run(synth_con, rid)
    graded = pipeline.grade_week(synth_con, cfg, season, 3)
    assert set(graded.actual_result) <= {"win", "loss"}
    with pytest.raises(ValueError):
        poollines.set_lines(synth_con, season, 3, [("NOPE", 7)])
    poollines.set_lines(synth_con, season, 3, [(fav, 0)])             # clears
    assert poollines.entered(synth_con, season, 3).empty


def test_backtest_runs_with_estimated_lines(synth_con, cfg):
    from nflpickem.backtest import run_backtest
    cfg = {**cfg, "pool": {**cfg["pool"], "line_rule": "acql", "points_mode": "flat"}}
    res = run_backtest(synth_con, cfg, save=False)
    wk = res.weekly[res.weekly.model == "market"]
    assert (wk.max_points == wk.games).all()


def test_spread_anchor_for_lined_games():
    # market: home -8.5, moneyline-implied 78%; model agrees with the market.
    p = poollines.credited_home_probability(0.78, "home", 9.0, home_spread=-8.5, p_market=0.78)
    assert p == pytest.approx(0.5, abs=0.02)            # line ~ spread: a coin flip
    unanchored = poollines.credited_home_probability(0.78, "home", 9.0)
    assert unanchored > p + 0.03                       # moneyline->margin overstates the favourite
    # model more bullish than the market moves the centre up
    assert poollines.credited_home_probability(0.85, "home", 9.0, -8.5, 0.78) > p
