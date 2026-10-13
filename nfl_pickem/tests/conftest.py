import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nflpickem import db  # noqa: E402
from nflpickem.config import load_config  # noqa: E402
from nflpickem.ingest import synthetic  # noqa: E402

SMALL = dict(n_teams=8, n_seasons=5, weeks=8, seed=11, played_weeks_last_season=5)


@pytest.fixture()
def cfg():
    return load_config(use_local=False, overrides={
        "backtest": {"first_eval_season": 2103, "last_eval_season": 2199, "holdout_seasons": [],
                     "min_train_seasons": 2},
        "data": {"model_dir": str(Path(__file__).parent / ".." / "data" / "test_models")},
        "models": {"logistic_C_grid": [0.1, 1.0]},
    })


@pytest.fixture()
def con():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def synth_con(con):
    synthetic.load_into(con, **SMALL)
    return con


@pytest.fixture()
def synth_inputs(synth_con):
    games = db.load_games(synth_con)
    stats = synth_con.execute("SELECT * FROM team_game_stats").df()
    odds = synth_con.execute("SELECT * FROM odds_snapshots").df()
    return games, stats, odds


def make_game(gid, season, week, ko, home, away, hs=None, as_=None, **kw):
    row = {"game_id": gid, "season": season, "week": week, "game_type": "REG", "game_date": pd.Timestamp(ko).date(),
           "kickoff_utc": pd.Timestamp(ko), "home_team": home, "away_team": away,
           "home_score": hs, "away_score": as_, "game_status": "final" if hs is not None else "scheduled",
           "location": "Home", "div_game": 0, "roof": "outdoors", "temp": None, "wind": None,
           "home_qb_id": f"{home}_QB", "away_qb_id": f"{away}_QB", "home_qb_name": None, "away_qb_name": None,
           "data_source": "test", "updated_at": pd.Timestamp("2020-01-01")}
    row.update(kw)
    return row
