import pandas as pd

from nflpickem import pipeline
from nflpickem.reports import load_reports, to_markdown
from nflpickem.review import review_week, systematic_check


def test_reports_built_and_stored(synth_con, cfg):
    run_id, picks = pipeline.predict_week(synth_con, cfg, now=pipeline.effective_now(synth_con))
    reps = load_reports(synth_con, run_id)
    assert set(reps) == set(picks.game_id)
    r = next(iter(reps.values()))
    for key in ("predicted_winner", "win_probability", "market_probability", "factors", "uncertainties",
                "data", "confidence_rank"):
        assert key in r
    assert len(r["factors"]) <= 5
    assert abs(sum(r["win_probability"].values()) - 1) < 1e-6
    assert all(f["kind"] == "measured" for f in r["factors"])
    md = to_markdown(r)
    assert r["predicted_winner"] in md and "Uncertainties" in md


def test_report_flags_missing_odds(synth_con, cfg):
    synth_con.execute("DELETE FROM odds_snapshots WHERE captured_at IS NOT NULL")
    run_id, _ = pipeline.predict_week(synth_con, cfg, now=pipeline.effective_now(synth_con))
    r = next(iter(load_reports(synth_con, run_id).values()))
    assert r["market_probability"] is None
    assert any("No market odds" in u for u in r["uncertainties"])


def test_review_week_and_calibration(synth_con, cfg):
    season = int(synth_con.execute("SELECT max(season) FROM games").fetchone()[0])
    rid, _ = pipeline.predict_week(synth_con, cfg, season, 3)
    pipeline.freeze_run(synth_con, rid)
    pipeline.grade_all(synth_con, cfg)
    rv = review_week(synth_con, cfg, season, 3)
    assert rv["games_graded"] == 4 and rv["run_id"] == rid
    games = pd.DataFrame(rv["games"])
    losses = games[games.actual_result == "loss"]
    allowed = {"data_issue", "lineup_change", "market_moved", "model_deviation", "coin_flip", "variance"}
    assert set(losses.miss_cause) <= allowed
    assert (games[games.actual_result == "win"].miss_cause == "").all()
    assert "market_sheet_points" in rv
    cal = systematic_check(synth_con, cfg)
    assert {"bucket", "games", "predicted", "observed", "flag"} <= set(cal.columns)


def test_review_pending_week(synth_con, cfg):
    run_id, picks = pipeline.predict_week(synth_con, cfg, now=pipeline.effective_now(synth_con))
    s, w = int(picks.season.iloc[0]), int(picks.week.iloc[0])
    assert review_week(synth_con, cfg, s, w)["status"] == "no completed games yet"
