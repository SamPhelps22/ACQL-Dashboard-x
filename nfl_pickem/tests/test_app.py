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
    monkeypatch.setenv("NFLPICKEM_NO_LOCAL", "1")   # the user's own settings stay out
    return path


@pytest.mark.parametrize("page", ["picks", "matchup", "backtest", "tracker", "settings"])
def test_pages_render(demo_db, page):
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=120)
    at.session_state["force_page"] = page
    at.run()
    assert not at.exception, at.exception
    assert any("SYNTHETIC" in w.value for w in at.warning) or page == "settings"


def test_tracker_explains_points_that_do_not_fit_the_slate(demo_db, tmp_path, monkeypatch):
    """A custom_points list shorter than the slate shows an error, not a traceback."""
    import json
    from nflpickem import config
    local = tmp_path / "settings.local.json"
    local.write_text(json.dumps({"pool": {"points_mode": "custom", "custom_points": [1]}}))
    monkeypatch.delenv("NFLPICKEM_NO_LOCAL")
    monkeypatch.setattr(config, "LOCAL_OVERRIDES", local)
    at = AppTest.from_file("../app/streamlit_app.py", default_timeout=120)
    at.session_state["force_page"] = "tracker"
    at.run()
    assert not at.exception, at.exception
    assert any("custom_points" in e.value for e in at.error)


def test_local_settings_can_be_switched_off(tmp_path, monkeypatch):
    import json
    from nflpickem import config
    local = tmp_path / "settings.local.json"
    local.write_text(json.dumps({"pool": {"tie_rule": "full"}}))
    monkeypatch.setattr(config, "LOCAL_OVERRIDES", local)
    monkeypatch.delenv("NFLPICKEM_NO_LOCAL", raising=False)
    assert config.load_config()["pool"]["tie_rule"] == "full"
    monkeypatch.setenv("NFLPICKEM_NO_LOCAL", "1")
    assert config.load_config()["pool"]["tie_rule"] != "full"
