#!/usr/bin/env python3
"""Tests for the Model Lab's challengers (lab/challengers.py).

    python tests/test_lab_challengers.py

Invented seasons only; no network, no Qt, no database.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import predictions  # noqa: E402
from lab import archive_backtest as ab  # noqa: E402
from lab import challengers as ch  # noqa: E402


def invented(seasons=range(2010, 2016), per_season=300, seed=1, sharp=True):
    """Games where "linegood" knows part of what the market misses (when
    `sharp`), "linenoise" knows nothing, and "linemidweek" is the line again."""
    rng = random.Random(seed)
    games, models, margins = [], {}, {}
    for season in seasons:
        for i in range(per_season):
            truth = rng.gauss(0, 6)
            hidden = rng.gauss(0, 2.5)                      # what the market has not priced
            market = round((truth - hidden) * 2) / 2
            gid = f"{season}_{i:03d}"
            games.append(ab.ArchiveGame(
                gid, season, 1 + i // 16, "kc", "bal",
                predictions.Forecast(road="bal", home="kc", market=market, opening=market, opinions=(1.0,)),
                "midweek", None, market))
            models[gid] = {"linenoise": market + rng.gauss(0, 3), "linemidweek": market}
            if sharp:
                models[gid]["linegood"] = market + hidden + rng.gauss(0, 1)
            margins[gid] = round(truth + rng.gauss(0, 10)) or 1
    return games, models, margins


def rmse(games, margins, expected):
    return (sum((expected(g) - margins[g.game_id]) ** 2 for g in games) / len(games)) ** 0.5


class TestChallengers(unittest.TestCase):
    def test_a_real_signal_is_found_by_both(self):
        games, models, margins = invented()
        train = [g for g in games if g.season < 2015]
        test = [g for g in games if g.season == 2015]
        best = ch.fit_best_model(train, models, margins, 2014)
        self.assertEqual(best.model, "linegood")
        self.assertGreater(best.weight, 0.5)
        blend = ch.fit_blend(train, models, margins, 2014)
        market = rmse(test, margins, lambda g: g.forecast.market)
        self.assertLess(rmse(test, margins, lambda g: ch.blend_margin(blend, g, models)), market)

    def test_with_no_signal_the_blend_stays_near_the_market(self):
        games, models, margins = invented(sharp=False)
        train = [g for g in games if g.season < 2015]
        blend = ch.fit_blend(train, models, margins, 2014)
        moved = [abs(ch.blend_margin(blend, g, models) - g.forecast.market) for g in games if g.season == 2015]
        self.assertLess(max(moved), 1.0)

    def test_the_midweek_line_is_never_a_model(self):
        games, models, margins = invented()
        train = [g for g in games if g.season < 2015]
        self.assertNotIn("linemidweek", ch.fit_blend(train, models, margins, 2014).columns)
        # Even where it would score best: here the line itself is the only "model".
        only_line = {gid: {"linemidweek": m["linemidweek"]} for gid, m in models.items()}
        self.assertIsNone(ch.fit_best_model(train, only_line, margins, 2014).model)

    def test_a_game_the_best_model_skipped_is_the_market(self):
        games, models, margins = invented()
        models = {gid: dict(m) for gid, m in models.items()}
        skipped = next(g for g in games if g.season == 2015)
        del models[skipped.game_id]["linegood"]
        out, _ = ch.walk_forward(games, models, margins, test_from=2015)
        self.assertEqual(out[skipped.game_id]["best"], skipped.forecast.market)

    def test_a_season_is_never_fitted_on_itself_or_later(self):
        games, models, margins = invented(seasons=range(2010, 2015))
        baseline, _ = ch.walk_forward(games, models, margins, test_from=2012)
        for season in (2012, 2013, 2014):
            tampered = dict(margins)
            for g in games:
                if g.season >= season:
                    tampered[g.game_id] = -tampered[g.game_id] * 2 + 9
            again, _ = ch.walk_forward(games, models, tampered, test_from=2012)
            for g in games:
                if g.season == season:
                    self.assertEqual(again[g.game_id], baseline[g.game_id], (season, g.game_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
