#!/usr/bin/env python3
"""Tests for Project Challenger (challenger/).

Run from the project root:

    python tests/test_challenger.py          # or: python -m pytest tests/test_challenger.py

Almost everything runs on the synthetic league (challenger/synthetic.py), so
no network or downloaded data is needed. The leakage tests change results
that lie in the future of a forecast and check the forecast does not move -
and, as a control, that later forecasts do. One class at the end uses the
real nflverse cache when it is present and is skipped otherwise.
"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from challenger import backtest, config, data, elo, features, journal, metrics, pbp, predictions, synthetic  # noqa: E402
from challenger.calibration import Platt  # noqa: E402

CFG = config.small_test_config()


def _league():
    raw, tg, qb = synthetic.league()
    return data.load_games(frame=raw), tg, qb


def _features(games, tg, qb, cfg=CFG):
    X = features.add_differences(features.build(games, tg, qb, cfg), cfg.use_epa)
    y = X["game_id"].map(games.set_index("game_id")["home_win"])
    return X, y


def _perturb_after(games, tg, qb, when, seed=99):
    """Scramble every result and pbp row of games kicking off at or after `when`."""
    rng = np.random.default_rng(seed)
    g = games.copy()
    late = g["kickoff_utc"] >= when
    g.loc[late, "home_score"] = rng.integers(0, 50, late.sum())
    g.loc[late, "away_score"] = rng.integers(0, 50, late.sum())
    g = data.load_games(frame=g.drop(columns=["home", "away", "kickoff_utc", "kickoff_assumed", "neutral",
                                              "completed", "home_win", "playoff", "home_team_raw", "away_team_raw"]))
    ids = set(g.loc[g["kickoff_utc"] >= when, "game_id"])
    tg2, qb2 = tg.copy(), qb.copy()
    cols = [c for c in tg2.columns if c.startswith(("off_", "def_")) and not c.endswith("_plays")]
    tg2[cols] = tg2[cols].astype(float)
    sel = tg2["game_id"].isin(ids)
    tg2.loc[sel, cols] = rng.normal(0, 1, (sel.sum(), len(cols)))
    sel = qb2["game_id"].isin(ids)
    qb2["epa_sum"] = qb2["epa_sum"].astype(float)
    qb2.loc[sel, "epa_sum"] = rng.normal(0, 30, sel.sum())
    qb2.loc[sel, "qb_id"] = "QB-SWAPPED"
    return g, tg2, qb2


class Independence(unittest.TestCase):
    """The model pipeline never touches Deadeye, the dashboard, nfl_pickem or the arena."""

    MODEL_MODULES = ("__init__", "config", "data", "pbp", "venues", "elo", "features", "models", "calibration",
                     "backtest", "predictions", "journal", "synthetic", "metrics", "shadow", "runs")

    def test_no_forbidden_imports(self):
        for name in self.MODEL_MODULES:
            path = ROOT / "challenger" / f"{name}.py"
            if not path.exists():
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [("." * node.level) + (node.module or "")]
                for m in mods:
                    self.assertFalse(m.startswith(("acql", "nfl_pickem", "nflpickem")), f"{name} imports {m}")
                    self.assertNotIn("arena", m, f"{name} imports the arena ({m})")

    def test_no_deadeye_files_read(self):
        for name in self.MODEL_MODULES:
            path = ROOT / "challenger" / f"{name}.py"
            if not path.exists() or name == "shadow":
                continue
            text = path.read_text().lower()
            for marker in ("acql-forecasts", "nflpredictions", "acql-spreads", "acql.db", "backtest_results.json"):
                self.assertNotIn(marker, text, f"{name} mentions {marker}")

    def test_feature_lists_hold_no_market_or_outcome(self):
        games, tg, qb = _league()
        X, _ = _features(games, tg, qb)
        cols = set(features.gbm_features(X)) | set(features.LR_FEATURES)
        self.assertFalse(cols & set(data.MARKET_COLUMNS))
        self.assertFalse(cols & set(data.OUTCOME_COLUMNS))
        self.assertFalse(set(X.columns) & set(data.OUTCOME_COLUMNS))
        self.assertFalse(set(X.columns) & set(data.MARKET_COLUMNS))

    def test_market_free_run_refuses_market_columns(self):
        games, tg, qb = _league()
        X, y = _features(games, tg, qb)
        X["spread_line"] = 1.0
        with self.assertRaises(ValueError):
            backtest.walk_forward(X, y, CFG, [2104])

    def test_outcome_columns_refused(self):
        games, tg, qb = _league()
        X, y = _features(games, tg, qb)
        X["home_score"] = 1
        with self.assertRaises(ValueError):
            backtest.walk_forward(X, y, CFG, [2104], market=True)


class Leakage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games, cls.tg, cls.qb = _league()
        cls.X, cls.y = _features(cls.games, cls.tg, cls.qb)

    def test_timestamps_ordered(self):
        X = self.X
        self.assertTrue((X["deadline_utc"] < X["kickoff_utc"]).all())
        have = X["data_cutoff_utc"].notna()
        self.assertTrue((X.loc[have, "data_cutoff_utc"] <= X.loc[have, "deadline_utc"]).all())

    def test_own_result_does_not_move_own_features(self):
        g = self.games.copy()
        target = g[(g["season"] == 2104) & (g["week"] == 5)].iloc[3]
        i = g.index[g["game_id"] == target["game_id"]][0]
        g.loc[i, "home_score"], g.loc[i, "away_score"] = 70, 0
        g["home_win"] = np.where(g["home_score"] > g["away_score"], 1.0, 0.0)
        X2, _ = _features(g, self.tg, self.qb)
        a = self.X[self.X["game_id"] == target["game_id"]].drop(columns=["h_qb_id", "a_qb_id", "h_qb_name", "a_qb_name"])
        b = X2[X2["game_id"] == target["game_id"]].drop(columns=["h_qb_id", "a_qb_id", "h_qb_name", "a_qb_name"])
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

    def test_same_week_thursday_game_is_unseen(self):
        """A Sunday forecast is made before Thursday's kickoff, so Thursday's result can't reach it."""
        wk = self.games[(self.games["season"] == 2105) & (self.games["week"] == 4)]
        thursday = wk["kickoff_utc"].min()
        g2, tg2, qb2 = _perturb_after(self.games, self.tg, self.qb, thursday)
        X2, _ = _features(g2, tg2, qb2)
        ids = wk["game_id"]
        cols = [c for c in self.X.columns if c not in ("h_qb_name", "a_qb_name")]
        a = self.X[self.X["game_id"].isin(ids)][cols].reset_index(drop=True)
        b = X2[X2["game_id"].isin(ids)][cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_future_results_do_not_change_earlier_predictions(self):
        """The headline leakage test: scramble every result from mid-2105 on; nothing earlier may move."""
        seasons = [2104, 2105, 2106]
        base, _ = backtest.walk_forward(self.X, self.y, CFG, seasons)
        cut = self.games[(self.games["season"] == 2105) & (self.games["week"] == 6)]["kickoff_utc"].min()
        g2, tg2, qb2 = _perturb_after(self.games, self.tg, self.qb, cut)
        X2, y2 = _features(g2, tg2, qb2)
        moved, _ = backtest.walk_forward(X2, y2, CFG, seasons)
        key = ["model", "game_id"]
        j = base.merge(moved, on=key, suffixes=("", "_2"))
        early = j["deadline_utc"] < cut
        self.assertGreater(early.sum(), 100)
        np.testing.assert_array_equal(j.loc[early, "p_home"].to_numpy(), j.loc[early, "p_home_2"].to_numpy())
        # control: forecasts after the cut do react (otherwise the test proves nothing)
        late = ~early
        self.assertGreater(np.abs(j.loc[late, "p_home"] - j.loc[late, "p_home_2"]).max(), 1e-3)

    def test_backtest_is_deterministic(self):
        a, _ = backtest.walk_forward(self.X, self.y, CFG, [2105])
        b, _ = backtest.walk_forward(self.X, self.y, CFG, [2105])
        np.testing.assert_array_equal(a["p_home"].to_numpy(), b["p_home"].to_numpy())

    def test_training_never_uses_test_season(self):
        _, records = backtest.walk_forward(self.X, self.y, CFG, [2105])
        r = records[0]
        self.assertEqual(r["train_seasons"], "2101-2104")
        self.assertTrue(all(f < 2105 for f in r["inner_folds"]))

    def test_probabilities_valid(self):
        p, _ = backtest.walk_forward(self.X, self.y, CFG, [2106])
        self.assertTrue(p["p_home"].between(0, 1).all())
        np.testing.assert_allclose(p["p_home"] + p["p_away"], 1.0)
        self.assertEqual(set(p["model"]), set(backtest.MODELS))
        self.assertFalse(set(p.columns) & predictions.FORBIDDEN)

    def test_models_find_planted_signal(self):
        p, _ = backtest.walk_forward(self.X, self.y, CFG, [2105, 2106])
        j = p.merge(self.games[["game_id", "home_win"]], on="game_id")
        j = j[j["home_win"].notna()]
        for m in ("challenger", "logistic"):
            d = j[j["model"] == m]
            self.assertLess(metrics.summary(d["p_home"], d["home_win"])["log_loss"], 0.69)


class Store(unittest.TestCase):
    def test_write_once(self):
        frame = pd.DataFrame([{c: 0 for c in predictions.COLUMNS}])
        frame["p_home"], frame["p_away"] = 0.6, 0.4
        with tempfile.TemporaryDirectory() as tmp:
            path = predictions.write_once(frame, Path(tmp), "r1", {})
            self.assertTrue(predictions.verify(path))
            predictions.write_once(frame, Path(tmp), "r1", {})          # same bytes: fine
            frame.loc[0, "p_home"] = 0.7
            with self.assertRaises(predictions.ImmutableError):
                predictions.write_once(frame, Path(tmp), "r1", {})
            bad = frame.assign(home_score=3)
            with self.assertRaises(ValueError):
                predictions.write_once(bad, Path(tmp), "r2", {})


class Journal(unittest.TestCase):
    def _rec(self, gid, kick, p=0.6):
        return {"game_id": gid, "model_version": "v", "kickoff_utc": kick, "deadline_utc": kick, "p_home": p}

    def test_forecast_after_kickoff_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = pd.Timestamp("2030-01-01T12:00Z")
            journal.append_forecasts("challenger", [self._rec("g1", "2030-01-02T00:00Z")], now=now, folder=Path(tmp))
            with self.assertRaises(journal.JournalError):
                journal.append_forecasts("challenger", [self._rec("g2", "2030-01-01T11:00Z")], now=now,
                                         folder=Path(tmp))

    def test_tampering_detected_and_blocks_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = pd.Timestamp("2030-01-01T12:00Z")
            journal.append_forecasts("challenger", [self._rec("g1", "2030-01-02T00:00Z"),
                                                    self._rec("g2", "2030-01-02T00:00Z")], now=now, folder=Path(tmp))
            self.assertTrue(journal.verify("challenger", Path(tmp))[0])
            path = Path(tmp) / "challenger.jsonl"
            path.write_text(path.read_text().replace('"p_home":0.6', '"p_home":0.9', 1))
            self.assertFalse(journal.verify("challenger", Path(tmp))[0])
            with self.assertRaises(journal.JournalError):
                journal.append_forecasts("challenger", [self._rec("g3", "2030-01-02T00:00Z")], now=now,
                                         folder=Path(tmp))

    def test_outcome_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = {"game_id": "g1", "kickoff_utc": "2030-01-01T18:00Z", "home_score": 20, "away_score": 17}
            with self.assertRaises(journal.JournalError):
                journal.append_outcomes([rec], now=pd.Timestamp("2030-01-01T19:00Z"), folder=Path(tmp))
            later = pd.Timestamp("2030-01-02T00:00Z")
            journal.append_outcomes([rec], now=later, folder=Path(tmp))
            journal.append_outcomes([rec], now=later, folder=Path(tmp))           # same score: nothing new
            journal.append_outcomes([{**rec, "home_score": 21}], now=later, folder=Path(tmp))
            rows = journal.read("outcomes", Path(tmp))
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[1]["correction"])

    def test_scored_forecast_is_last_before_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            kick, dl = "2030-01-03T18:00Z", "2030-01-02T18:00Z"
            for when, p in (("2030-01-01T00:00Z", 0.55), ("2030-01-02T12:00Z", 0.60), ("2030-01-03T00:00Z", 0.70)):
                journal.append_forecasts("challenger", [{**self._rec("g1", kick, p), "deadline_utc": dl}],
                                         now=pd.Timestamp(when), folder=Path(tmp))
            s = journal.scored_forecasts("challenger", Path(tmp))
            self.assertEqual(len(s), 1)
            self.assertAlmostEqual(float(s["p_home"].iloc[0]), 0.60)


class Pieces(unittest.TestCase):
    def test_elo_symmetry_and_home_edge(self):
        st = elo.EloState(config.DEFAULT.elo)
        _, _, _, p = st.pregame("A", "B", neutral=True)
        self.assertAlmostEqual(p, 0.5)
        _, _, _, p = st.pregame("A", "B", neutral=False)
        self.assertGreater(p, 0.5)
        st.update("A", "B", False, 0.0)            # a tie at home is a small loss of rating for the home side
        self.assertLess(st.rating("A"), st.rating("B"))

    def test_platt_learns_overconfidence(self):
        rng = np.random.default_rng(0)
        true = rng.uniform(0.3, 0.7, 4000)
        y = (rng.uniform(size=4000) < true).astype(float)
        stretched = 1 / (1 + np.exp(-3 * np.log(true / (1 - true))))
        cal = Platt().fit(stretched, y)
        self.assertLess(cal.a, 0.6)
        self.assertLess(metrics.summary(cal(stretched), y)["log_loss"], metrics.summary(stretched, y)["log_loss"])

    def test_pbp_aggregation_small(self):
        rows = []
        for i in range(10):
            rows.append({"game_id": "g", "season": 2020, "week": 1, "posteam": "AAA", "defteam": "BBB",
                         "pass": 1 if i < 6 else 0, "rush": 0 if i < 6 else 1, "epa": 0.1 * i,
                         "success": float(i % 2), "yards_gained": 25 if i == 0 else 3, "down": 3 if i < 2 else 1,
                         "third_down_converted": 1 if i == 0 else 0, "third_down_failed": 1 if i == 1 else 0,
                         "qb_dropback": 1 if i < 6 else 0, "sack": 1 if i == 5 else 0, "qb_hit": 0,
                         "interception": 1 if i == 4 else 0, "fumble_lost": 0, "fixed_drive": 1,
                         "fixed_drive_result": "Touchdown", "drive_inside20": 1, "passer_id": "Q1" if i < 6 else None,
                         "passer": "Q.One", "rusher_id": "R1", "qb_epa": 0.1 * i, "cpoe": 1.0, "play_type": "pass"})
        p = pd.DataFrame(rows)
        tg = pbp.team_games(p)
        r = tg.iloc[0]
        self.assertEqual(r["off_plays"], 10)
        self.assertAlmostEqual(r["off_epa"], 0.45)
        self.assertAlmostEqual(r["off_third"], 0.5)
        self.assertAlmostEqual(r["off_sack"], 1 / 6)
        self.assertAlmostEqual(r["off_turnover"], 0.1)
        self.assertAlmostEqual(r["off_explosive"], 0.1)
        self.assertAlmostEqual(r["off_rz"], 1.0)
        q = pbp.qb_games(p)
        self.assertEqual(q["starter"].sum(), 1)
        self.assertEqual(int(q["dropbacks"].iloc[0]), 6)

    def test_bootstrap_interval_covers_mean(self):
        rng = np.random.default_rng(1)
        d = rng.normal(0.01, 0.1, 500)
        ci = metrics.bootstrap_paired(d, np.repeat(np.arange(50), 10))
        self.assertLess(ci["lo"], ci["mean"])
        self.assertGreater(ci["hi"], ci["mean"])

    def test_scoring_rules(self):
        s = metrics.summary([0.5, 0.9], [1, 0])
        self.assertAlmostEqual(s["accuracy"], 0.25)
        self.assertAlmostEqual(s["brier"], (0.25 + 0.81) / 2)


class ArenaRules(unittest.TestCase):
    """The pool's scoring rule (needs the dashboard importable; it is in this repo)."""

    def test_credited_side(self):
        from challenger.arena import pool

        row = pd.Series({"home_score": 27, "away_score": 20, "line": 7.0, "line_home_fav": True})
        self.assertEqual(pool.credited_side(row), "home")        # a win by exactly the line goes to the favourite
        row["line"] = 7.5
        self.assertEqual(pool.credited_side(row), "away")
        row = pd.Series({"home_score": 17, "away_score": 17, "line": None, "line_home_fav": None})
        self.assertIsNone(pool.credited_side(row))

    def test_normal_conversion(self):
        from challenger.arena import pool

        self.assertAlmostEqual(pool.credited_normal(0.0, None, None), 0.5, places=6)
        self.assertLess(pool.credited_normal(7.0, 7.5, True), 0.5)
        self.assertGreater(pool.credited_normal(10.0, 7.0, True), 0.5)


REAL = (data.schedule_path().exists() and data.pbp_path(2024).exists() and data.pbp_path(2025).exists())


@unittest.skipUnless(REAL, "real nflverse cache not present (python -m challenger fetch)")
class RealData(unittest.TestCase):
    def test_real_future_scramble_leaves_features_alone(self):
        cfg = config.DEFAULT
        games = data.load_games()
        games = games[games["season"].between(2023, 2025)].reset_index(drop=True)
        tg, qb = pbp.aggregate([2023, 2024, 2025])
        X = features.build(games, tg, qb, cfg)
        cut = games[(games["season"] == 2025) & (games["week"] == 10)]["kickoff_utc"].min()
        g2, tg2, qb2 = _perturb_after(games, tg, qb, cut)
        X2 = features.build(g2, tg2, qb2, cfg)
        early = X["deadline_utc"] < cut
        pd.testing.assert_frame_equal(X[early].reset_index(drop=True), X2[early].reset_index(drop=True))
        self.assertFalse(X[~early]["h_off_epa"].equals(X2[~early]["h_off_epa"]))


def main() -> int:
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
