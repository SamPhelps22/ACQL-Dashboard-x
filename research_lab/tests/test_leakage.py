"""Leakage: rewriting the future must not change any earlier forecast.

For each model, forecasts of 2012 week 6 are made twice - once on the real
data and once with every game after that week's forecast time rewritten at
random (scores, lines, play-by-play). They must be identical. A second test
rewrites the target games' own results.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from research_lab.backtest import engine
from research_lab.ensemble import stack
from research_lab.models import baselines, bayes, market, matchup, qb, situational
from research_lab.simulation import drives
from research_lab.tests import fixtures

SEASON, WEEK = 2012, 6


def _models():
    return [baselines.ChallengerElo(), baselines.SimpleLogistic(), baselines.MarketMoneyline(),
            bayes.BayesTeams(), qb.QBWeekStart(), qb.QBConfirmed(), matchup.MatchupInteraction(),
            situational.Situational(), situational.SituationalWeather(), market.MarketFull(),
            drives.DriveSim(n_sims=300)]


@unittest.skipUnless(fixtures.available(), "lab data not fetched (python -m research_lab fetch && build)")
class FutureDoesNotLeak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = fixtures.store()
        g = cls.real.games
        wk = g[(g["season"] == SEASON) & (g["week"] == WEEK)]
        cls.cutoff = wk["ts_week_start"].iloc[0]
        cls.last_kickoff = wk["kickoff"].max()

    def _pair(self, model_factory, fake_store):
        a = engine.predict_week(model_factory(), self.real, SEASON, WEEK)
        b = engine.predict_week(model_factory(), fake_store, SEASON, WEEK)
        return a.sort_values("game_id").reset_index(drop=True), b.sort_values("game_id").reset_index(drop=True)

    def test_future_games_rewritten(self):
        fake = fixtures.scrambled_after(self.cutoff, lines_after=self.last_kickoff)
        # the rewrite really changed later games
        later = self.real.games["kickoff"] > self.cutoff
        self.assertFalse(np.array_equal(self.real.games.loc[later, "margin"].values,
                                        fake.games.loc[later, "margin"].values))
        for i, _ in enumerate(_models()):
            make = lambda i=i: _models()[i]        # noqa: E731 - fresh instance each time
            a, b = self._pair(make, fake)
            with self.subTest(model=a["model"].iloc[0]):
                self.assertGreater(len(a), 0)
                np.testing.assert_array_equal(a["p_home_raw"].values, b["p_home_raw"].values)
                for col in ("exp_margin", "exp_total"):
                    np.testing.assert_array_equal(a[col].astype(float).values, b[col].astype(float).values)

    def test_target_results_hidden(self):
        """Changing the predicted games' own results changes nothing."""
        g = self.real.games.copy()
        tgt = (g["season"] == SEASON) & (g["week"] == WEEK)
        g.loc[tgt, ["home_score", "away_score"]] = g.loc[tgt, ["away_score", "home_score"]].values + 17
        g["margin"] = g["home_score"] - g["away_score"]
        g["home_win"] = np.where(g["margin"] > 0, 1.0, np.where(g["margin"] < 0, 0.0, 0.5))
        from research_lab.data.store import Store
        fake = Store(g, self.real.team_games.drop(columns="completed_at"), self.real.qb_games.drop(columns="completed_at"),
                     self.real.drives.drop(columns="completed_at"), self.real.injuries)
        for make in (baselines.ChallengerElo, bayes.BayesTeams, qb.QBWeekStart):
            a, b = self._pair(make, fake)
            np.testing.assert_array_equal(a["p_home_raw"].values, b["p_home_raw"].values)

    def test_blind_drops_outcomes_and_late_columns(self):
        from research_lab import config
        from research_lab.data import games as games_mod
        wk = self.real.games.head(5)
        for info in (config.WEEK_START, config.PRE_KICKOFF, config.CLOSING_RETRO):
            cols = set(games_mod.blind(wk, info).columns)
            self.assertFalse(cols & {"home_score", "away_score", "margin", "result", "total", "home_win",
                                     "total_points"})
        self.assertFalse(set(games_mod.blind(wk, config.WEEK_START).columns) & {"spread_line", "home_qb_id", "temp"})
        self.assertFalse(set(games_mod.blind(wk, config.PRE_KICKOFF).columns) & {"spread_line", "temp", "wind"})

    def test_snapshot_only_completed_before(self):
        snap = self.real.snapshot(self.cutoff)
        self.assertTrue((snap.games["completed_at"] <= self.cutoff).all())
        self.assertTrue(set(snap.team_games["game_id"]) <= set(snap.games["game_id"]))
        self.assertTrue(set(snap.drives["game_id"]) <= set(snap.games["game_id"]))


class EnsembleUsesEarlierSeasonsOnly(unittest.TestCase):
    def test_target_outcomes_do_not_change_weights(self):
        rng = np.random.default_rng(0)
        n_season = 200
        rows, outs = [], []
        for s in range(2010, 2016):
            for i in range(n_season):
                gid = f"{s}_{i}"
                truth = rng.normal()
                y = float(truth + rng.normal() > 0)
                outs.append({"game_id": gid, "home_win": y})
                for m, noise in (("m1", 0.5), ("m2", 1.0), ("m3", 2.0)):
                    p = 1 / (1 + np.exp(-(truth + rng.normal(0, noise))))
                    rows.append({"game_id": gid, "season": s, "week": 1 + i % 17, "home_team": "H", "away_team": "A",
                                 "kickoff": "2015-01-01T00:00:00+00:00", "forecast_ts": "2014-12-30T00:00:00+00:00",
                                 "feature_cutoff": "2014-12-29T00:00:00+00:00", "model": m, "p_home_raw": p})
        fc, oc = pd.DataFrame(rows), pd.DataFrame(outs)
        a, _ = stack.run(fc, oc, ["m1", "m2", "m3"], "G", "week_start", False, [2015], log=lambda *_: None)
        flipped = oc.copy()
        late = flipped["game_id"].str.startswith("2015")
        flipped.loc[late, "home_win"] = 1 - flipped.loc[late, "home_win"]
        b, _ = stack.run(fc, flipped, ["m1", "m2", "m3"], "G", "week_start", False, [2015], log=lambda *_: None)
        np.testing.assert_array_equal(a["p_home_raw"].values, b["p_home_raw"].values)


class CalibrationUsesEarlierSeasonsOnly(unittest.TestCase):
    def test_platt_ignores_current_and_future(self):
        rng = np.random.default_rng(1)
        rows = [{"game_id": f"{s}_{i}", "season": s, "model": "m", "p_home_raw": rng.uniform(0.2, 0.8)}
                for s in range(2010, 2016) for i in range(100)]
        df = pd.DataFrame(rows)
        oc = pd.DataFrame({"game_id": df["game_id"], "home_win": rng.integers(0, 2, len(df)).astype(float)})
        a = engine.calibrate(df, outcomes=oc)
        oc2 = oc.copy()
        later = df["season"] >= 2014
        oc2.loc[later, "home_win"] = 1 - oc2.loc[later, "home_win"]
        b = engine.calibrate(df, outcomes=oc2)
        early = df["season"] <= 2014
        np.testing.assert_array_equal(a.loc[early, "p_home_cal"].astype(float).values,
                                      b.loc[early, "p_home_cal"].astype(float).values)


if __name__ == "__main__":
    unittest.main()
