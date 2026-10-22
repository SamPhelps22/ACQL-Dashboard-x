#!/usr/bin/env python3
"""Tests for the probability-calibration audit (acql/training/calibration.py).

Run from the project root:

    python tests/test_calibration.py

Three kinds of test, none of which reads the archives:

    the arithmetic   variances add and SDs don't; a difference of two
                     independent scores; no division by two; the remaining
                     SD with part of a game left; the normal curve's symmetry
    the curve        the dashboard's margin curve: home and away mirror each
                     other, ties are counted once, chances stay inside (0, 1)
                     and rise with the margin, the per-game widening adds in
                     variance, never in SD
    pinned outputs   today's production numbers - win chances, cover chances,
                     a priced slate - written down, so the audit (or anything
                     else) changing them shows up as a failure here

No Qt is imported.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import analytics
from acql.model import predictions, pricing
from acql.models import Game
from acql.training import calibration


class Arithmetic(unittest.TestCase):
    def test_variances_add_not_sds(self):
        self.assertAlmostEqual(calibration.margin_sd(10.0, 10.0), math.sqrt(200.0))
        self.assertNotAlmostEqual(calibration.margin_sd(10.0, 10.0), 20.0)            # ESPN's sum of SDs
        self.assertNotAlmostEqual(calibration.margin_sd(10.0, 10.0), 10.0)            # the reply's /2
        self.assertAlmostEqual(calibration.combined_sd(3.0, 4.0), 5.0)
        self.assertAlmostEqual(calibration.combined_sd(8.7), 8.7)

    def test_difference_of_independent_scores(self):
        draw = np.random.default_rng(3)
        home, away = draw.normal(24, 9.0, 400_000), draw.normal(21, 7.0, 400_000)
        self.assertAlmostEqual(float((home - away).std()), calibration.margin_sd(9.0, 7.0), delta=0.05)

    def test_correlated_scores(self):
        # scores that move together make a narrower margin
        self.assertLess(calibration.margin_sd(10.0, 10.0, 0.2), calibration.margin_sd(10.0, 10.0))
        self.assertAlmostEqual(calibration.margin_sd(10.0, 10.0, 1.0), 0.0)

    def test_remaining_sd_shrinks_by_root_of_time(self):
        self.assertAlmostEqual(calibration.remaining_sd(14.0, 0.5), 14.0 * math.sqrt(0.5))
        self.assertAlmostEqual(calibration.remaining_sd(14.0, 1.0), 14.0)
        self.assertAlmostEqual(calibration.remaining_sd(14.0, 0.0), 0.0)
        self.assertAlmostEqual(calibration.remaining_sd(14.0, 1.7), 14.0)              # held to the game

    def test_normal_symmetry_and_bounds(self):
        margins = np.array([-21.0, -7.0, -3.0, 0.0, 3.0, 7.0, 21.0])
        home = calibration.normal_home(margins, 13.0)
        self.assertTrue(np.allclose(home + calibration.normal_home(-margins, 13.0), 1.0))
        self.assertAlmostEqual(float(home[3]), 0.5)
        self.assertTrue(((home > 0) & (home < 1)).all())
        self.assertTrue((np.diff(home) > 0).all())
        self.assertTrue(np.isnan(calibration.normal_home(np.array([np.nan]), 13.0)[0]))


class Curve(unittest.TestCase):
    def test_mirror(self):
        """A home side favoured by m covering n is the road side, favoured by
        -m, failing to cover -n+1: one curve for both orientations."""
        worst = 0.0
        for mu in np.arange(-14.0, 14.01, 0.5):
            for need in range(-20, 21):
                worst = max(worst, abs(analytics.cover_chance(mu, need)
                                       - (1 - analytics.cover_chance(-mu, -need + 1))))
        self.assertLess(worst, 1e-9)

    def test_ties_counted_once(self):
        for spread in (0.0, 3.0, 7.0, 14.0):
            tie = dict(analytics.margin_distribution(spread))[0]
            total = analytics.win_chance(spread) + analytics.win_chance(-spread) + tie
            self.assertAlmostEqual(total, 1.0, places=9)
            self.assertLess(tie, 0.006)

    def test_home_chance_symmetric_and_bounded(self):
        for m in (-17.5, -6.5, -3.0, -0.5, 0.0, 2.5, 9.0, 24.0):
            p = calibration.curve_home(m)
            self.assertAlmostEqual(p + calibration.curve_home(-m), 1.0, places=9)
            self.assertTrue(0.0 < p < 1.0)
        self.assertAlmostEqual(calibration.curve_home(0.0), 0.5, places=9)
        chances = [calibration.curve_home(m) for m in np.arange(-20, 20.5, 0.5)]
        self.assertTrue(all(b > a for a, b in zip(chances, chances[1:])))

    def test_home_chance_matches_the_picks(self):
        """The audit's tie-free chance is within 0.3 points of the pick chance
        analytics.predict_margin gives (which counts a tie as a miss)."""
        for m in (1.0, 3.0, 6.5, 10.0):
            pick = analytics.predict_margin(Game(1, "Chicago", "Detroit"), m).chance
            self.assertLess(abs(calibration.curve_home(m) - pick), 0.003)

    def test_curve_sd_is_not_8_7(self):
        """8.7 is the narrow bell's width, not the margin's SD: the whole curve
        runs about 13 points either side, as NFL margins around the line do."""
        self.assertTrue(12.5 < calibration.curve_sd(0.0) < 13.6)
        self.assertTrue(12.5 < calibration.curve_sd(7.0) < 13.6)

    def test_widening_adds_in_variance(self):
        """pricing.price widens by hypot(8.7, extra); the curve's variance grows
        by about extra^2 - not by 2*8.7*extra + extra^2, as adding SDs would."""
        base = calibration.curve_sd(3.0) ** 2
        for extra in (2.0, 4.0):
            grown = calibration.curve_sd(3.0, math.hypot(analytics.SPREAD_SD, extra)) ** 2 - base
            self.assertAlmostEqual(grown, extra ** 2, delta=0.15 * extra ** 2)
            self.assertLess(grown, (analytics.SPREAD_SD + extra) ** 2 - analytics.SPREAD_SD ** 2)

    def test_wider_is_less_sure(self):
        sure = [analytics.cover_chance(6.5, 1, sd) for sd in (8.7, 9.0, 10.0, 12.0)]
        self.assertTrue(all(b < a for a, b in zip(sure, sure[1:])))

    def test_scaled_curve_is_the_curve_at_one(self):
        margins = np.array([-7.0, -3.0, 0.0, 2.5, 10.0])
        self.assertTrue(np.allclose(calibration.scaled_curve_home(margins, 1.0), calibration.curves_home(margins),
                                    atol=1e-6))

    def test_moneyline_and_spread_are_kept_apart(self):
        """A straight-up game anchors on the moneyline only when it is within
        reach of the spread; a lined game always keeps the spread."""
        game = Game(1, "Chicago", "Detroit")
        forecast = predictions.Forecast(road="Detroit", home="Chicago", market=3.0, market_win=0.80)
        self.assertEqual(pricing._anchor(game, forecast, 3.0), 3.0)                   # 80% is ~10 points: too far
        near = predictions.Forecast(road="Detroit", home="Chicago", market=3.0, market_win=0.62)
        self.assertAlmostEqual(pricing._anchor(game, near, 3.0), analytics.spread_for_win_chance(0.62))
        lined = Game(1, "Chicago", "Detroit", line=3.0, line_favourite="Chicago")
        self.assertEqual(pricing._anchor(lined, near, 3.0), 3.0)


class Scoring(unittest.TestCase):
    def test_honest_chances_score_honest(self):
        draw = np.random.default_rng(11)
        p = draw.uniform(0.1, 0.9, 20_000)
        y = (draw.uniform(size=p.size) < p).astype(float)
        m = calibration.mark(p, y, ranges=False)
        self.assertAlmostEqual(m.slope, 1.0, delta=0.06)
        self.assertAlmostEqual(m.intercept, 0.0, delta=0.04)
        self.assertLess(m.ece, 0.02)

    def test_too_sure_shows_a_low_slope(self):
        draw = np.random.default_rng(12)
        p = draw.uniform(0.1, 0.9, 20_000)
        y = (draw.uniform(size=p.size) < p).astype(float)
        sure = calibration._sigmoid(2.0 * calibration._logit(p))
        self.assertAlmostEqual(calibration.mark(sure, y, ranges=False).slope, 0.5, delta=0.05)

    def test_wilson(self):
        low, high = calibration.wilson(70, 100)
        self.assertAlmostEqual(low, 0.6041, places=3)
        self.assertAlmostEqual(high, 0.7810, places=3)

    def test_paired_sign(self):
        y = np.array([1.0, 0.0] * 50)
        good, bad = np.where(y == 1, 0.8, 0.2), np.full(100, 0.5)
        weeks = np.repeat(np.arange(10), 10)
        self.assertGreater(calibration.paired(good, bad, y, weeks)["logloss"]["gain"], 0)

    def test_fits_only_look_back(self):
        """A season's fitted value comes from earlier seasons alone: scrambling
        a later season's answers leaves every earlier chance where it was."""
        draw = np.random.default_rng(5)
        season = np.repeat([2018, 2019, 2020, 2021], 300)
        market = draw.normal(0, 6, season.size)
        y = (draw.uniform(size=season.size) < calibration.normal_home(market, 13.0)).astype(float)

        def walk(answers):
            return calibration.season_fitted(
                season, lambda before: calibration.best_normal(market[before], answers[before]),
                lambda s, now: calibration.normal_home(market[now], s))[0]

        clean = walk(y)
        spoiled = y.copy()
        spoiled[season == 2021] = draw.permutation(spoiled[season == 2021])
        dirty = walk(spoiled)
        self.assertTrue(np.isnan(clean[season == 2018]).all())
        self.assertTrue(np.allclose(clean[season <= 2021], dirty[season <= 2021], equal_nan=True))

    def test_candidates_on_a_made_up_slate(self):
        """Every candidate is a chance between 0 and 1, the market's own curve
        included, and Deadeye's game width is never under 8.7."""
        rows = []
        draw = np.random.default_rng(9)
        teams = sorted(predictions.DISPLAY)
        for season in (2018, 2019):
            for week in (1, 2):
                for g in range(8):
                    market = float(draw.normal(0, 5))
                    row = {"season": season, "week": week, "order": season * 100 + week, "game": f"{season}{week}{g}",
                           "home": teams[2 * g + 1], "away": teams[2 * g], "market": market, "opening": market - 0.5,
                           "actual": float(round(draw.normal(market, 13))) or 1.0, "n_models": 6}
                    for k in range(6):
                        row[f"m:x{k}"] = market + float(draw.normal(0.5, 2))
                    rows.append(row)
        rows[3]["actual"], rows[5]["actual"] = 0.0, np.nan          # a tie, and a game not yet played
        chances, about, fits, games = calibration.candidates(pd.DataFrame(rows))
        for name, said in chances.items():
            known = said[~np.isnan(said)]
            self.assertTrue(((known > 0) & (known < 1)).all(), name)
        self.assertTrue((games["width"] >= analytics.SPREAD_SD - 1e-9).all())
        # neither the tie nor the unplayed game is ever scored
        found = calibration.Timing("x", "x", games, chances, about, fits, dev=[2019], final=[])
        keep = found.keep()
        self.assertFalse(keep[3] or keep[5])
        self.assertFalse(np.isnan(found.y[keep]).any())
        self.assertTrue(keep.any())


class Pinned(unittest.TestCase):
    """Production as it stood on 2026-10-18. A failure here means a pick's
    chance moved: fine if that was meant, and then these numbers change with it."""

    def test_constants(self):
        self.assertEqual(analytics.SPREAD_SD, 8.7)
        self.assertEqual(analytics.TAIL_RATIO, 2.26)
        self.assertEqual(analytics.TAIL_SHARE, 0.34)
        self.assertEqual(predictions.CONSENSUS_WEIGHT, 0.25)
        self.assertEqual((predictions.MIN_WEIGHT_SHARE, predictions.MAX_WEIGHT_SHARE), (0.35, 1.60))

    def test_win_chances(self):
        pinned = {0.0: 0.498029, 1.0: 0.536595, 2.5: 0.593395, 3.0: 0.611814, 6.5: 0.728674, 7.0: 0.743248,
                  10.0: 0.818149, 14.0: 0.886656}
        for spread, chance in pinned.items():
            self.assertAlmostEqual(analytics.win_chance(spread), chance, places=6)

    def test_cover_chances(self):
        pinned = {(3.0, 3): 0.556602, (7.0, 7): 0.512798, (7.0, 4): 0.612932, (-3.0, 1): 0.384449,
                  (10.0, 10): 0.517366}
        for (spread, need), chance in pinned.items():
            self.assertAlmostEqual(analytics.cover_chance(spread, need), chance, places=6)
        for sd, chance in {9.0: 0.723106, 10.0: 0.706441, 12.0: 0.680062}.items():
            self.assertAlmostEqual(analytics.cover_chance(6.5, 1, sd), chance, places=6)
        for p, spread in {0.6: 2.7, 0.75: 7.3, 0.25: -7.3}.items():
            self.assertEqual(analytics.spread_for_win_chance(p), spread)

    def test_priced_slate(self):
        shift = (0.0, 2.0, -1.5, 3.0, 0.5, -2.5, 1.0, 0.0)
        stretch = (1.0, 0.5, 2.0, 1.0, 3.0, 1.0, 0.7, 1.5)
        names = list(predictions.DISPLAY)
        forecasts = [predictions.Forecast(
            road=names[2 * i], home=names[2 * i + 1], market=float(i - 3) + 0.5, opening=float(i - 3),
            opinions=tuple(float(i - 3) + shift[i] + stretch[i] * d for d in (-2, -1, 0, 0.5, 1, 1.5, 3, 4)))
            for i in range(8)]
        games = [Game(index=i + 1, home=predictions.DISPLAY[f.home], away=predictions.DISPLAY[f.road])
                 for i, f in enumerate(forecasts)]
        found = predictions.match_games(games, forecasts)
        ctx = pricing.Context(week=5, forecasts=dict(found.by_game), lean=predictions.home_lean(forecasts),
                              typical=predictions.typical_disagreement(forecasts), weight=predictions.CONSENSUS_WEIGHT)
        pinned = [(-2.633681, 8.705586, "Arizona", 0.597104), (-1.1, 8.703575, "Baltimore", 0.540433),
                  (-0.614583, 8.703575, "Carolina", 0.521198), (1.104167, 8.705586, "Cleveland", 0.540433),
                  (1.638542, 8.706158, "Denver", 0.559536), (1.793403, 8.705586, "Green Bay", 0.567126),
                  (3.555928, 8.704931, "Indianapolis", 0.633453), (4.476496, 8.70476, "Kansas City", 0.664798)]
        for game, (margin, sd, pick, chance) in zip(games, pinned):
            p = pricing.price(game, ctx)
            said = p.prediction()
            self.assertEqual(p.source, "market + models")
            self.assertAlmostEqual(p.margin, margin, places=5)
            self.assertAlmostEqual(p.sd, sd, places=5)
            self.assertEqual(said.pick, pick)
            self.assertAlmostEqual(said.chance, chance, places=6)
            # the width is combined in variance: hypot, never a sum of SDs
            forecast = ctx.forecasts[game.index]
            self.assertAlmostEqual(p.sd, math.hypot(analytics.SPREAD_SD, forecast.extra_spread(ctx.weight, ctx.typical)))

    def test_dashboard_never_imports_the_audit(self):
        for path in (ROOT / "acql").rglob("*.py"):
            if "training" in path.parts:
                continue
            self.assertNotIn("calibration", " ".join(
                line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.lstrip().startswith(("import ", "from ")) and "training" in line), str(path))


if __name__ == "__main__":
    unittest.main(verbosity=1)
