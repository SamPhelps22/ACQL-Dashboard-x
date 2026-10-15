import numpy as np
import pandas as pd
import pytest

from nflpickem.confidence import (ExpectedPointsStrategy, OpponentAwareStrategy, ScoringRules, allocate,
                                  grade_pick, grade_sheet, select_teams, simulate_pool_win_probability,
                                  validate_allocation)


def slate(probs, kick=None):
    n = len(probs)
    return pd.DataFrame({
        "game_id": [f"g{i}" for i in range(n)],
        "home_team": [f"H{i}" for i in range(n)], "away_team": [f"A{i}" for i in range(n)],
        "kickoff_utc": kick or [pd.Timestamp("2024-09-08 17:00")] * n,
        "blended_home_probability": probs,
    })


def test_team_selection():
    s = select_teams(slate([0.7, 0.3, 0.5]))
    assert list(s.selected_team) == ["H0", "A1", "H2"]  # exact 50/50 -> home
    assert list(s.selected_team_probability) == pytest.approx([0.7, 0.7, 0.5])


def test_points_unique_1_to_n_and_ordered():
    a = allocate(slate([0.55, 0.9, 0.2, 0.62, 0.51]))
    assert sorted(a.confidence_points) == [1, 2, 3, 4, 5]
    top = a.sort_values("confidence_points", ascending=False)
    assert list(top.game_id) == ["g1", "g2", "g3", "g0", "g4"]  # 0.9, 0.8 (away), 0.62, 0.55, 0.51
    validate_allocation(a)
    assert a.expected_points.sum() == pytest.approx((top.selected_team_probability * top.confidence_points).sum())


def test_allocation_maximises_expected_points():
    rng = np.random.default_rng(1)
    s = slate(list(rng.uniform(0.05, 0.95, 7)))
    best = allocate(s).expected_points.sum()
    p = select_teams(s).selected_team_probability.to_numpy()
    for _ in range(200):
        perm = rng.permutation(np.arange(1, 8))
        assert (p * perm).sum() <= best + 1e-9


def test_deterministic_tie_breaking():
    kick = [pd.Timestamp("2024-09-08 20:00"), pd.Timestamp("2024-09-08 17:00"), pd.Timestamp("2024-09-08 17:00")]
    s = slate([0.6, 0.6, 0.4], kick)  # all 0.6 for the selected team
    a = allocate(s)
    order = list(a.sort_values("confidence_points", ascending=False).game_id)
    assert order == ["g1", "g2", "g0"]  # earlier kickoff first, then game_id
    assert allocate(s.sample(frac=1, random_state=3)).equals(a)


def test_missing_probability_falls_back_to_home_coinflip():
    a = allocate(slate([np.nan, 0.8]))
    row = a.set_index("game_id").loc["g0"]
    assert row.selected_team == "H0" and row.selected_team_probability == 0.5 and row.confidence_points == 1


def test_excluded_and_canceled_games():
    s = slate([0.9, 0.7, 0.6, 0.55])
    s["game_status"] = ["scheduled", "canceled", "scheduled", "scheduled"]
    a = allocate(s, exclude={"g3"}).set_index("game_id")
    assert a.loc["g1", "confidence_points"] == 0 and a.loc["g3", "confidence_points"] == 0
    assert sorted(a.confidence_points[a.confidence_points > 0]) == [1, 2]


def test_custom_points():
    rules = ScoringRules(points_mode="custom", custom_points=[10, 20, 30])
    a = allocate(slate([0.6, 0.9, 0.7]), rules)
    assert a.set_index("game_id").confidence_points.to_dict() == {"g1": 30, "g2": 20, "g0": 10}
    with pytest.raises(ValueError):
        allocate(slate([0.6, 0.9, 0.7, 0.8]), rules)
    with pytest.raises(ValueError):
        ScoringRules(points_mode="custom", custom_points=[5, 5, 3]).point_values(3)


@pytest.mark.parametrize("rule,expected", [("zero", 0.0), ("half", 5.0), ("full", 10.0)])
def test_tie_rules(rule, expected):
    assert grade_pick("H", "H", "A", 20, 20, 10, ScoringRules(tie_rule=rule)) == ("tie", expected)


def test_grade_win_loss_pending_void():
    r = ScoringRules()
    assert grade_pick("H", "H", "A", 24, 17, 5, r) == ("win", 5.0)
    assert grade_pick("A", "H", "A", 24, 17, 5, r) == ("loss", 0.0)
    assert grade_pick("A", "H", "A", None, None, 5, r, "scheduled") == ("pending", 0.0)
    assert grade_pick("A", "H", "A", None, None, 5, r, "canceled") == ("void", 0.0)
    assert grade_pick("A", "H", "A", None, None, 5, ScoringRules(postponed_rule="loss"), "postponed") == ("loss", 0.0)


def test_grade_sheet():
    a = allocate(slate([0.9, 0.2]))
    res = pd.DataFrame({"game_id": ["g0", "g1"], "home_score": [30, 10], "away_score": [3, 10],
                        "game_status": ["final", "final"]})
    g = grade_sheet(a, res, ScoringRules(tie_rule="half")).set_index("game_id")
    assert g.loc["g0", "points_earned"] == 2 and g.loc["g1", "points_earned"] == 0.5


def test_strategies():
    s = slate([0.6, 0.7])
    assert ExpectedPointsStrategy().allocate(s, ScoringRules()).equals(allocate(s))
    with pytest.raises(NotImplementedError):
        OpponentAwareStrategy().allocate(s, ScoringRules())


def test_pool_win_probability_simulation():
    s = slate([0.9, 0.6, 0.55])
    mine = allocate(s)
    same = mine.copy()
    p = s.set_index("game_id")["blended_home_probability"]
    assert simulate_pool_win_probability(mine, [same], p, n_sims=500) == pytest.approx(0.5)


def test_allocation_matches_exhaustive_optimum_on_small_slates():
    """Every permutation of 1..n tried: the allocator's expected points equal the true maximum."""
    from itertools import permutations
    rng = np.random.default_rng(7)
    for n in range(1, 7):
        for _ in range(25):
            probs = list(np.round(rng.uniform(0.02, 0.98, n), 2))   # rounding forces some exact ties
            a = allocate(slate(probs))
            validate_allocation(a)
            p = select_teams(slate(probs)).selected_team_probability.to_numpy()
            best = max(float((p * np.array(perm)).sum()) for perm in permutations(range(1, n + 1)))
            assert a.expected_points.sum() == pytest.approx(best)
            assert sorted(a.confidence_points) == list(range(1, n + 1))


@pytest.mark.parametrize("points,n,problem", [
    ([1], 4, "has 1 values but the slate has 4 games"),        # the saved setting that crashed the tracker
    ([], 3, "is empty"),
    ([5, 5, 3], 3, "unique"),
    ([3, 0, 1], 3, "positive"),
    ([3, -2, 1], 3, "positive"),
    ([3, 2.5, 1], 3, "positive whole"),
])
def test_custom_points_problems_are_reported_not_guessed(points, n, problem):
    rules = ScoringRules(points_mode="custom", custom_points=points)
    assert problem in rules.problem(n)
    with pytest.raises(ValueError, match=problem):
        rules.point_values(n)


def test_custom_points_more_than_games_uses_the_highest():
    rules = ScoringRules(points_mode="custom", custom_points=[1, 2, 3, 5, 8])
    assert rules.problem(3) is None and rules.point_values(3) == [8, 5, 3]
    assert ScoringRules().problem(16) is None


def test_saving_invalid_custom_points_is_refused():
    from nflpickem.config import load_config
    for bad in ([], [4, 4], [3, 0]):
        with pytest.raises(ValueError, match="custom_points"):
            load_config(use_local=False, overrides={"pool": {"points_mode": "custom", "custom_points": bad}})
    load_config(use_local=False, overrides={"pool": {"points_mode": "custom", "custom_points": [1]}})
