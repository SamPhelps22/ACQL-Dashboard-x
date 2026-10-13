"""Integration tests: synthetic end-to-end weekly workflow."""

import pandas as pd
import pytest

from nflpickem import pipeline
from nflpickem.confidence import validate_allocation


def test_end_to_end_predict_freeze_export_grade(synth_con, cfg, tmp_path):
    now = pipeline.effective_now(synth_con)
    run_id, picks = pipeline.predict_week(synth_con, cfg, now=now)
    assert run_id and len(picks) == 4  # 8 synthetic teams -> 4 games
    validate_allocation(picks)
    assert picks.blended_home_probability.between(0, 1).all()
    assert (picks.expected_points == picks.selected_team_probability * picks.confidence_points).all()
    stored = pipeline.get_run(synth_con, run_id)
    assert len(stored) == 4 and stored.model_version.nunique() == 1
    run = synth_con.execute("SELECT data_cutoff, generated_at FROM prediction_runs WHERE run_id=?", [run_id]).fetchone()
    assert run[0] <= now and run[1] is not None

    path = pipeline.export_csv(picks, tmp_path / "p.csv", "SYNTHETIC")
    csv = pd.read_csv(path)
    assert list(csv.columns[:3]) == ["data_label", "season", "week"]
    assert (csv.data_label == "SYNTHETIC").all()


def test_past_week_repredicted_as_of_its_cutoff(synth_con, cfg):
    season = int(synth_con.execute("SELECT max(season) FROM games").fetchone()[0])
    run_id, picks = pipeline.predict_week(synth_con, cfg, season, 3)
    cutoff = synth_con.execute("SELECT data_cutoff FROM prediction_runs WHERE run_id=?", [run_id]).fetchone()[0]
    first_ko = synth_con.execute("SELECT min(kickoff_utc) FROM games WHERE season=? AND week=3", [season]).fetchone()[0]
    assert cutoff < first_ko
    assert picks.model_version.iloc[0].split("-")[1] < pd.Timestamp(first_ko).strftime("%Y%m%d")


def test_frozen_snapshot_is_immutable_and_reruns_dont_touch_it(synth_con, cfg):
    season = int(synth_con.execute("SELECT max(season) FROM games").fetchone()[0])
    run_id, picks = pipeline.predict_week(synth_con, cfg, season, 2)
    pipeline.freeze_run(synth_con, run_id)
    pipeline.freeze_run(synth_con, run_id)  # idempotent
    before = pipeline.get_run(synth_con, run_id)
    with pytest.raises(pipeline.FrozenRunError):
        pipeline.delete_run(synth_con, run_id)
    with pytest.raises(pipeline.FrozenRunError):
        pipeline.save_run(synth_con, picks, season, 2, pd.Timestamp("2100-01-01"), None, cfg, run_id=run_id)
    run2, _ = pipeline.predict_week(synth_con, cfg, season, 2)
    assert run2 != run_id
    pd.testing.assert_frame_equal(before, pipeline.get_run(synth_con, run_id))
    assert pipeline.submitted_run(synth_con, season, 2) == run_id
    pipeline.delete_run(synth_con, run2)  # drafts can be deleted
    assert pipeline.get_run(synth_con, run2).empty


def test_grading_and_tracker_idempotent(synth_con, cfg):
    season = int(synth_con.execute("SELECT max(season) FROM games").fetchone()[0])
    for wk in (2, 3):
        rid, _ = pipeline.predict_week(synth_con, cfg, season, wk)
        pipeline.freeze_run(synth_con, rid)
    assert pipeline.grade_all(synth_con, cfg) == 2
    assert pipeline.grade_all(synth_con, cfg) == 2
    n = synth_con.execute("SELECT count(*) FROM pool_results").fetchone()[0]
    assert n == 8
    t = pipeline.season_tracker(synth_con, cfg["pool"]["pool_id"])
    assert list(t.week) == [2, 3] and (t.points <= t.max_points).all()
    assert t.cumulative_points.iloc[-1] == t.points.sum()


def test_grade_requires_frozen_run(synth_con, cfg):
    with pytest.raises(RuntimeError):
        pipeline.grade_week(synth_con, cfg, 2105, 1)


def test_import_pool_scores(synth_con, cfg):
    df = pd.DataFrame({"season": [2105, 2105], "week": [1, 1], "participant": ["me", "bob"], "points": [20, 25],
                       "is_me": [True, False]})
    assert pipeline.import_pool_scores(synth_con, df, "p") == 2
    with pytest.raises(ValueError):
        pipeline.import_pool_scores(synth_con, df.drop(columns="points"), "p")


def test_weekly_job_with_missing_odds(synth_con, cfg, tmp_path):
    synth_con.execute("DELETE FROM odds_snapshots WHERE captured_at IS NOT NULL")  # provider down
    rep = pipeline.run_weekly(synth_con, cfg, freeze=True, update=False, export_dir=tmp_path)
    picks = pipeline.get_run(synth_con, rep["run_id"])
    assert (picks.odds_status == "missing").all()
    assert picks.data_flags.str.contains("NO_ODDS").all()
    assert picks.blended_home_probability.notna().all()
    rep2 = pipeline.run_weekly(synth_con, cfg, freeze=True, update=False, export_dir=tmp_path)
    assert rep2["freeze"].startswith("skipped")


def test_cli_demo_smoke(tmp_path):
    from nflpickem.cli import main
    db = str(tmp_path / "demo.duckdb")
    assert main(["--db", db, "demo", "--seasons", "4"]) == 0
    assert main(["--db", db, "status"]) == 0
