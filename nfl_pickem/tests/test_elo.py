import pandas as pd
import pytest

from nflpickem.models.elo import EloModel, EloParams, expected_home

from conftest import make_game


def games_df(rows):
    return pd.DataFrame(rows)


def test_expected_home_with_hfa():
    assert expected_home(1500, 1500, 0) == pytest.approx(0.5)
    assert expected_home(1500, 1500, 48) > 0.5


def test_winner_gains_and_zero_sum():
    g = games_df([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 30, 10)])
    gr, st = EloModel().run(g)
    post = st.set_index("team").rating_post
    assert post["H"] > 1505 > post["A"]
    assert post["H"] - 1505 == pytest.approx(1505 - post["A"])
    assert gr.iloc[0].home_elo_pre == 1505


def test_tie_moves_ratings_toward_each_other():
    g = games_df([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 10, 10)])
    st = EloModel(EloParams(home_field_advantage=48)).run(g)[1].set_index("team").rating_post
    assert st["H"] < 1505 < st["A"]  # home was expected to win


def test_season_regression_and_point_in_time_lookup():
    g = games_df([make_game("a", 2020, 1, "2020-09-13 17:00", "H", "A", 40, 0),
                  make_game("b", 2021, 1, "2021-09-12 17:00", "H", "A")])
    m = EloModel(EloParams(season_regression=0.5))
    _, st = m.run(g)
    post_h = st.set_index("team").rating_post["H"]
    q = pd.DataFrame({"team": ["H", "H"], "season": [2020, 2021],
                      "cutoff": [pd.Timestamp("2020-09-13 16:00"), pd.Timestamp("2021-09-12 16:00")]})
    r = m.ratings_at(st, q)
    assert r.iloc[0] == 1505  # before game a finished
    assert r.iloc[1] == pytest.approx(post_h + 0.5 * (1505 - post_h))


def test_neutral_site_has_no_hfa():
    m = EloModel()
    p = m.predict([1505], [1505], pd.Series(["Neutral"]))
    assert p[0] == pytest.approx(0.5)
