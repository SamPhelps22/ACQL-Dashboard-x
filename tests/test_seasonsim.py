"""The small-line reading, the share's fit, and the season simulated week by week.

    python tests/test_seasonsim.py

Scratch data only: no network, no database, nothing of the pool's read.
"""

from __future__ import annotations

import csv
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acql import analytics                                    # noqa: E402
from acql.feeds import lines                                  # noqa: E402
from acql.model import predictions, pricing, seasonsim, waterfall     # noqa: E402
from acql.models import Game, PlayerWeek, Season, Week        # noqa: E402


class SmallLines(unittest.TestCase):
    def test_same_side_never_larger_and_rising(self):
        last = -99.0
        for tenth in range(-200, 201):
            line = tenth / 10
            read = analytics.meant_margin(line)
            self.assertLessEqual(abs(read), abs(line) + 1e-12)
            self.assertEqual(read > 0, line > 0)
            self.assertEqual(read < 0, line < 0)
            self.assertGreater(read, last)                    # a bigger line is never read as a smaller margin
            last = read

    def test_mirror(self):
        for line in (0.5, 1, 2.5, 3, 3.5, 7):
            self.assertAlmostEqual(analytics.meant_margin(-line), -analytics.meant_margin(line))

    def test_only_small_lines_move(self):
        self.assertAlmostEqual(analytics.meant_margin(1.0), 0.5, delta=0.05)       # about half at a point
        self.assertTrue(2.3 < analytics.meant_margin(3.0) < 2.8)
        for line in (5.0, 6.5, 7.0, 10.0, 14.0):
            self.assertAlmostEqual(analytics.meant_margin(line), line, places=2)

    def test_what_it_does_to_a_chance(self):
        # the market's own moneylines put a 2.5-point favourite near 56%, a 3-point one near 60%
        self.assertAlmostEqual(analytics.win_chance(round(analytics.meant_margin(2.5), 1)), 0.565, delta=0.01)
        self.assertAlmostEqual(analytics.win_chance(round(analytics.meant_margin(3.0), 1)), 0.597, delta=0.01)

    def test_there_and_back(self):
        for line in (-9.5, -3, -1, 0, 0.5, 1.5, 2.5, 3, 3.5, 4, 8):
            self.assertAlmostEqual(analytics.line_for_margin(analytics.meant_margin(line)), line, places=6)

    def test_switched_off(self):
        kept = analytics.SMALL_LINE_SHADE
        try:
            analytics.SMALL_LINE_SHADE = 0
            self.assertEqual(analytics.meant_margin(2.5), 2.5)
            self.assertEqual(analytics.line_for_margin(2.5), 2.5)
        finally:
            analytics.SMALL_LINE_SHADE = kept


class Priced(unittest.TestCase):
    def _one(self, market: float, opinions=(), line=None, favourite="", **more):
        game = Game(1, "Kansas City", "Denver", line=line, line_favourite=favourite)
        forecast = predictions.Forecast("Denver", "Kansas City", market=market, opinions=tuple(opinions), **more)
        ctx = pricing.Context(1, {1: forecast}, 0.0, 1.0, predictions.CONSENSUS_WEIGHT)
        return game, ctx, pricing.price(game, ctx)

    def test_a_small_line_is_read_down_and_the_side_kept(self):
        for market in (-3.0, -1.5, 1.0, 2.5, 3.0):
            _, _, price = self._one(market)
            self.assertEqual(price.base, market)                              # the line shown is the line quoted
            self.assertAlmostEqual(price.fair, analytics.meant_margin(market))
            self.assertAlmostEqual(price.margin, price.fair)
            said = price.prediction()
            self.assertEqual(said.pick, "Kansas City" if market > 0 else "Denver")
            self.assertGreater(said.chance, 0.5)
            self.assertLess(said.chance, analytics.win_chance(abs(market)))   # the same side, less sure

    def test_a_big_line_is_untouched(self):
        _, _, price = self._one(7.5, line=7.0, favourite="Kansas City")
        self.assertAlmostEqual(price.margin, 7.5, places=3)

    def test_the_moneyline_still_leads_a_straight_up_game(self):
        _, _, price = self._one(2.5, market_win=0.58)
        self.assertAlmostEqual(price.margin, analytics.spread_for_win_chance(0.58))
        _, _, far = self._one(2.5, market_win=0.80)                           # 80% is ten points: one of them is stale
        self.assertAlmostEqual(far.margin, analytics.meant_margin(2.5))

    def test_a_typed_spread_is_read_the_same_way(self):
        game = Game(1, "Kansas City", "Denver")
        price = pricing.price(game, pricing.Context(1), lines.Spread("home", 2.5), typed=True)
        self.assertEqual(price.base, 2.5)
        self.assertAlmostEqual(price.margin, analytics.meant_margin(2.5))

    def test_the_steps_still_add_up(self):
        for market, opinions in ((2.5, (4.0, 4.5, 5.0, 3.5, 4.0, 5.5)), (-1.0, ()), (6.5, (9.0, 8.5, 8.0, 9.5, 8.0, 9.0))):
            game, ctx, price = self._one(market, opinions)
            found = waterfall.steps(game, ctx, price)
            self.assertAlmostEqual(waterfall.total(found), price.margin, places=9)
            self.assertEqual(any(s.label == "A line this small" for s in found), abs(market) < 4)


def _week(number: int, rows: list[tuple[str, str, str]], scores: tuple[int, ...] = ()) -> Week:
    games = [Game(i, home, away, winner) for i, (away, home, winner) in enumerate(rows, start=1)]
    week = Week(number, games)
    for i, score in enumerate(scores):
        week.lines[f"coach{i}"] = PlayerWeek(f"Coach {i}", number, regular_wins=score, total_wins=score)
    return week


class ShareFit(unittest.TestCase):
    ROWS = [("Denver", "Kansas City", "Kansas City"), ("Dallas", "Chicago", "Dallas"), ("Miami", "Buffalo", "Buffalo")]

    def test_a_game_no_model_priced_is_no_evidence(self):
        week = _week(1, self.ROWS)
        bare = [predictions.Forecast(away, home, market=3.0) for away, home, _ in self.ROWS]
        self.assertEqual(predictions.replay_week(1, week.games, bare).games, 0)
        priced = [predictions.Forecast(away, home, market=3.0, opinions=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
                  for away, home, _ in self.ROWS]
        self.assertEqual(predictions.replay_week(1, week.games, priced).games, 3)

    def test_line_only_weeks_cannot_make_up_the_numbers(self):
        """Twenty weeks of typed-in lines, three games the models priced: still not enough to fit on."""
        week = _week(1, self.ROWS)
        bare = [predictions.Forecast(away, home, market=3.0) for away, home, _ in self.ROWS]
        priced = [predictions.Forecast(away, home, market=3.0, opinions=(-9.0, -8.0, -7.0, -8.5, -9.5, -7.5))
                  for away, home, _ in self.ROWS]
        replays = [predictions.replay_week(n, week.games, bare) for n in range(1, 21)]
        replays.append(predictions.replay_week(21, week.games, priced))
        fit = predictions.fit_from(replays)
        self.assertEqual(fit.games, 3)
        self.assertFalse(fit.enough)
        self.assertEqual(fit.weight, predictions.CONSENSUS_WEIGHT)


class Simulated(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        # week 2's Prediction Tracker file, in the project folder
        with open(self.folder / "nflpredictions week 2.csv", "w", newline="", encoding="utf-8") as handle:
            out = csv.writer(handle)
            out.writerow(["lineopen", "line", "road", "home", "linea", "lineb", "linec", "lined", "linee", "linef"])
            out.writerow([1, 1, "Denver", "Kansas City", -4, -5, -4.5, -5.5, -4, -5])       # models: Denver
            out.writerow([7, 7.5, "Dallas", "Chicago", 7, 8, 7.5, 8, 7, 7.5])
        # nflverse: weeks 1-3 of 2026 and one game of another season
        self.verse = self.folder / "games.csv.gz"
        head = ["game_id", "season", "game_type", "week", "away_team", "away_score", "home_team", "home_score",
                "location", "away_moneyline", "home_moneyline", "spread_line", "total_line"]
        rows = [
            ["a", 2026, "REG", 1, "DEN", 10, "KC", 24, "Home", 150, -170, 3.5, 44],
            ["b", 2026, "REG", 1, "DAL", 30, "CHI", 20, "Home", -300, 250, -7, 41],
            ["c", 2026, "REG", 2, "DEN", 21, "KC", 17, "Home", -105, -115, 1, 45],
            ["d", 2026, "REG", 2, "DAL", 3, "CHI", 31, "Home", 290, -350, 7.5, 40],
            ["e", 2026, "REG", 3, "MIA", 20, "BUF", 27, "Home", 200, -240, 5.5, 47],
            ["f", 2026, "REG", 3, "LA", 17, "SEA", 17, "Home", 110, -130, 2.5, 43],
            ["g", 2026, "REG", 4, "MIA", "", "KC", "", "Home", 200, -240, 5.5, 47],
            ["z", 2025, "REG", 1, "MIA", 0, "BUF", 50, "Home", 200, -240, 5.5, 47],
        ]
        with gzip.open(self.verse, "wt", encoding="utf-8", newline="") as handle:
            out = csv.writer(handle)
            out.writerow(head)
            out.writerows(rows)
        season = Season(title="ACQL 2026")
        season.weeks[1] = _week(1, [("Denver", "Kansas City", "Kansas City"), ("Dallas", "Chicago", "Dallas")], (2, 1, 0))
        season.weeks[2] = _week(2, [("Denver", "Kansas City", "Denver"), ("Dallas", "Chicago", "Chicago")], (1, 1, 2))
        self.season = season
        self.found = seasonsim.run(season, year=2026, folder=self.folder, verse=self.verse, use_store=False)

    def test_each_week_says_what_it_was_priced_from(self):
        self.assertEqual([(w.number, w.source) for w in self.found.weeks],
                         [(1, seasonsim.CLOSING), (2, seasonsim.FILE), (3, seasonsim.CLOSING)])
        self.assertEqual([w.no_sheet for w in self.found.weeks], [False, False, True])
        self.assertNotIn(4, [w.number for w in self.found.weeks])             # nothing played: nothing to walk

    def test_the_weeks_are_marked(self):
        one, two, three = self.found.weeks
        self.assertEqual((one.right, one.line_right, len(one.graded)), (2, 2, 2))
        self.assertEqual(one.place, 1)                                         # level with the best coach
        self.assertEqual((one.pool_best, round(one.pool_average, 2)), (2, 1.0))
        # week 2: the line has Kansas City by a point, the models have Denver by more: the pick leaves the line
        self.assertEqual([(c.line_pick, c.pick) for c in two.calls][0], ("Kansas City", "Denver"))
        self.assertEqual((two.right, two.line_right), (2, 1))
        self.assertEqual([c.matchup for c in two.flips], ["Denver @ Kansas City"])
        # week 3 has a tie: nobody's pick, and still a graded game
        self.assertEqual((len(three.graded), three.right), (2, 1))
        self.assertIsNone(three.place)

    def test_the_closing_moneyline_is_read(self):
        found = seasonsim.closing_lines(2026, self.verse)
        self.assertEqual(sorted(found), [1, 2, 3, 4])
        first = found[1][0]
        self.assertEqual((first.away, first.home, first.spread), ("Denver", "Kansas City", 3.5))
        self.assertAlmostEqual(first.win, (170 / 270) / (170 / 270 + 100 / 250))
        self.assertEqual(found[3][1].away, "Los Angeles Rams")                # nflverse's "LA"

    def test_every_week_is_priced_on_the_weeks_before(self):
        """Changing a later week's results must not move an earlier week."""
        self.season.weeks[2].games[0].winner = "Kansas City"
        again = seasonsim.run(self.season, year=2026, folder=self.folder, verse=self.verse, use_store=False)
        self.assertEqual(again.weeks[0], self.found.weeks[0])
        self.assertEqual([c.pick for c in again.weeks[1].calls], [c.pick for c in self.found.weeks[1].calls])

    def test_the_standing_and_the_report(self):
        self.assertEqual(self.found.standing(), (1, 3))                        # 4 right against 3, 2 and 2
        text = seasonsim.report(self.found, every_game=True)
        for wanted in ("simulated week by week", "| 2 | a file |", "| 3 † | closing line |", "No pick sheet",
                       "Denver @ Kansas City", "## Week 3", "1st among 4"):
            self.assertIn(wanted, text)

    def test_nothing_to_simulate_says_so(self):
        empty = seasonsim.run(Season(title="ACQL 2026"), year=2026, folder=self.folder,
                              verse=self.folder / "missing.csv.gz", use_store=False)
        self.assertIn("Nothing to simulate", seasonsim.report(empty))


if __name__ == "__main__":
    unittest.main()
