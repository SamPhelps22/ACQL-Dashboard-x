"""Smoke test: every dashboard page renders against a synthetic database."""

import pytest

from nflpickem import db, pipeline
from nflpickem.ingest import synthetic

from conftest import SMALL

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


@pytest.fixture()
def demo_db(tmp_path, monkeypatch, cfg):
    path = tmp_path / "app.duckdb"
    con = db.connect(path)
    synthetic.load_into(con, **SMALL)
    season = int(con.execute("SELECT max(season) FROM games").fetchone()[0])
    rid, _ = pipeline.predict_week(con, cfg, season, 3)
    pipeline.freeze_run(con, rid)
    pipeline.grade_all(con, cfg)
    con.close()
    monkeypatch.setenv("NFLPICKEM_DB_PATH", str(path))
    # the pages must not depend on whatever settings this machine has saved
    monkeypatch.setattr("nflpickem.config.LOCAL_OVERRIDES", tmp_path / "no-settings.json")
    return path


@pytest.mark.parametrize("page", ["picks", "matchup", "backtest", "tracker", "settings"])
def test_pages_render(demo_db, page):
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=120)
    at.session_state["force_page"] = page
    at.run()
    assert not at.exception, at.exception
    assert any("SYNTHETIC" in w.value for w in at.warning) or page == "settings"


@pytest.mark.parametrize("page", ["tracker", "backtest"])
def test_too_few_custom_points_is_an_error_message_not_a_crash(demo_db, tmp_path, monkeypatch, page):
    """A saved custom_points list shorter than the slate once crashed the Season Tracker."""
    import json
    saved = tmp_path / "settings.local.json"
    saved.write_text(json.dumps({"pool": {"points_mode": "custom", "custom_points": [1]}}))
    monkeypatch.setattr("nflpickem.config.LOCAL_OVERRIDES", saved)
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=120)
    at.session_state["force_page"] = page
    at.run()
    assert not at.exception, at.exception
    if page == "tracker":
        assert any("can't score" in e.value for e in at.error)
