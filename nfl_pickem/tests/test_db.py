import pandas as pd
import pytest

from nflpickem import db
from nflpickem.ingest import nflverse

from conftest import make_game

RAW = pd.DataFrame([
    {"game_id": "2024_01_BAL_KC", "season": 2024, "game_type": "REG", "week": 1, "gameday": "2024-09-05",
     "gametime": "20:20", "away_team": "BAL", "away_score": 20, "home_team": "KC", "home_score": 27,
     "location": "Home", "away_moneyline": 120, "home_moneyline": -142, "spread_line": 3.0, "div_game": 0,
     "roof": "outdoors", "temp": 80, "wind": 5, "away_qb_id": "q1", "home_qb_id": "q2",
     "away_qb_name": "L", "home_qb_name": "P"},
    {"game_id": "2024_02_OAK_SD", "season": 2024, "game_type": "REG", "week": 2, "gameday": "2024-09-15",
     "gametime": "16:05", "away_team": "OAK", "away_score": None, "home_team": "SD", "home_score": None,
     "location": "Home", "away_moneyline": 150, "home_moneyline": -175, "spread_line": 3.5, "div_game": 1,
     "roof": "dome", "temp": None, "wind": None, "away_qb_id": None, "home_qb_id": None,
     "away_qb_name": None, "home_qb_name": None},
    {"game_id": "2023_17_BUF_CIN", "season": 2023, "game_type": "REG", "week": 17, "gameday": "2024-01-02",
     "gametime": "20:30", "away_team": "BUF", "away_score": None, "home_team": "CIN", "home_score": None,
     "location": "Home", "away_moneyline": None, "home_moneyline": None, "spread_line": None, "div_game": 0,
     "roof": "outdoors", "temp": None, "wind": None, "away_qb_id": None, "home_qb_id": None,
     "away_qb_name": None, "home_qb_name": None},
])
NOW = pd.Timestamp("2024-09-10").to_pydatetime()


def test_schema_tables(con):
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    for t in ("games", "odds_snapshots", "predictions", "pool_results", "prediction_runs", "team_game_stats"):
        assert t in tables


def test_parse_schedule_status_teams_and_utc():
    g = nflverse.parse_schedule(RAW, now=NOW).set_index("game_id")
    assert g.loc["2024_01_BAL_KC", "game_status"] == "final"
    assert g.loc["2024_02_OAK_SD", "game_status"] == "scheduled"
    assert g.loc["2023_17_BUF_CIN", "game_status"] == "canceled"  # never played
    assert g.loc["2024_02_OAK_SD", "home_team"] == "LAC" and g.loc["2024_02_OAK_SD", "away_team"] == "LV"
    assert g.loc["2024_01_BAL_KC", "kickoff_utc"] == pd.Timestamp("2024-09-06 00:20")  # 20:20 EDT


def test_parse_odds_spread_sign_and_closing_flag():
    g = nflverse.parse_schedule(RAW, now=NOW)
    o = nflverse.parse_odds(RAW, g, now=NOW).set_index("game_id")
    assert o.loc["2024_01_BAL_KC", "home_spread"] == -3.0  # home favoured -> negative
    assert bool(o.loc["2024_01_BAL_KC", "is_closing"]) and pd.isna(o.loc["2024_01_BAL_KC", "captured_at"])
    assert o.loc["2024_02_OAK_SD", "captured_at"] == pd.Timestamp(NOW)
    assert "2023_17_BUF_CIN" not in o.index


def test_ingest_is_idempotent_and_handles_reschedule(con):
    nflverse.ingest_schedule(con, 2020, raw=RAW, now=NOW)
    nflverse.ingest_schedule(con, 2020, raw=RAW, now=NOW)
    assert con.execute("SELECT count(*) FROM games").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM odds_snapshots").fetchone()[0] == 2
    moved = RAW.copy()
    moved.loc[1, "gameday"] = "2024-09-17"  # rescheduled: same stable id, new kickoff
    nflverse.ingest_schedule(con, 2020, raw=moved, now=NOW)
    assert con.execute("SELECT count(*) FROM games").fetchone()[0] == 3
    ko = con.execute("SELECT kickoff_utc FROM games WHERE game_id='2024_02_OAK_SD'").fetchone()[0]
    assert pd.Timestamp(ko).day == 17


def test_duplicates_deduped(con):
    rows = [make_game("x", 2020, 1, "2020-09-13 17:00", "H", "A", 1, 0),
            make_game("x", 2020, 1, "2020-09-13 17:00", "H", "A", 2, 0)]
    db.upsert_games(con, pd.DataFrame(rows))
    assert con.execute("SELECT home_score FROM games").fetchall() == [(2,)]


def test_validation_rejects_bad_games(con):
    bad = pd.DataFrame([make_game("x", 2020, 1, "2020-09-13 17:00", "H", "H", 1, 0)])
    with pytest.raises(ValueError):
        db.upsert_games(con, bad)
    bad2 = pd.DataFrame([make_game("y", 2020, 1, "2020-09-13 17:00", "H", "A", game_status="final")])
    with pytest.raises(ValueError):
        db.upsert_games(con, bad2)


def test_aggregate_pbp():
    pbp = pd.DataFrame([
        {"game_id": "g", "posteam": "KC", "defteam": "BAL", "play_type": "pass", "epa": 1.0, "success": 1,
         "yards_gained": 25, "interception": 0, "fumble_lost": 0, "qb_kneel": 0, "qb_spike": 0, "two_point_attempt": 0},
        {"game_id": "g", "posteam": "KC", "defteam": "BAL", "play_type": "run", "epa": -0.5, "success": 0,
         "yards_gained": 2, "interception": 0, "fumble_lost": 1, "qb_kneel": 0, "qb_spike": 0, "two_point_attempt": 0},
        {"game_id": "g", "posteam": "KC", "defteam": "BAL", "play_type": "run", "epa": -0.1, "success": 0,
         "yards_gained": -1, "interception": 0, "fumble_lost": 0, "qb_kneel": 1, "qb_spike": 0, "two_point_attempt": 0},
        {"game_id": "g", "posteam": "BAL", "defteam": "KC", "play_type": "punt", "epa": 0.2, "success": 0,
         "yards_gained": 0, "interception": 0, "fumble_lost": 0, "qb_kneel": 0, "qb_spike": 0, "two_point_attempt": 0},
    ])
    a = nflverse.aggregate_pbp(pbp).set_index("team")
    assert a.loc["KC", "plays"] == 2  # kneel and punt excluded
    assert a.loc["KC", "off_epa_sum"] == pytest.approx(0.5)
    assert a.loc["KC", "explosive_plays"] == 1 and a.loc["KC", "turnovers"] == 1
    assert a.loc["BAL", "def_epa_sum"] == pytest.approx(0.5) and a.loc["BAL", "takeaways"] == 1


def test_validate_database_report(synth_con):
    rep = db.validate_database(synth_con)
    assert rep["games"] > 0 and rep["orphan_odds"] == 0 and rep["final_without_stats"] == 0
    assert rep["data_sources"] == ["synthetic"]
