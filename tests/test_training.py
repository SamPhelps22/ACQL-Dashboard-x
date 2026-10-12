#!/usr/bin/env python3
"""Tests for Deadeye's training ground (acql/training).

Run from the project root:

    python tests/test_training.py

Kept apart from run_tests.py so the two can be worked on at once. Everything
here but the last class runs on made-up games - tables with a known answer
planted in them, so it can be checked that the pipeline finds an edge that is
there, finds none where there is none, and cannot see a result before the
game. The numbers in them mean nothing about football. No Qt is imported.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql import analytics, luck, modellab, predictions
from acql.models import Game
from acql.training import data, evaluate, features, probability, recipes, registry, snapshots, study, walkforward

TEAMS = sorted(predictions.DISPLAY)


def made_up(seasons: int = 7, weeks: int = 10, games: int = 14, knows: float = 1.0, seed: int = 1) -> pd.DataFrame:
    """A table of invented games. The models all see something the line does
    not (`hidden`), and `knows` is how much of it turns up in the result: 1
    plants a real edge, 0 plants none."""
    draw = np.random.default_rng(seed)
    rows = []
    for season in range(2001, 2001 + seasons):
        for week in range(1, weeks + 1):
            order = draw.permutation(len(TEAMS))
            for g in range(games):
                home, away = TEAMS[order[2 * g]], TEAMS[order[2 * g + 1]]
                line = round(draw.normal(0, 6) * 2) / 2
                hidden = draw.normal(0, 5)
                actual = float(round(line + knows * hidden + draw.normal(0, 8)))
                row = {"season": season, "week": week, "home": home, "away": away, "source": "archive",
                       "game": data.game_key(season, week, away, home), "actual": actual,
                       "home_points": 20.0 + max(actual, 0), "away_points": 20.0 + max(-actual, 0),
                       "line_updated": line, "line_opening": line + round(draw.normal(0, 1) * 2) / 2}
                for k in range(8):
                    row[f"m:m{k}"] = line + hidden + draw.normal(0, 2)
                rows.append(row)
    frame = pd.DataFrame(rows)
    data._habit_lines(frame)
    return frame


def walked(knows: float, line_up=None, **shape) -> walkforward.Result:
    setting = features.SETTINGS["updated"]
    prepared = features.prepare(made_up(knows=knows, **shape), setting)
    return walkforward.run(prepared, setting, line_up() if line_up else recipes.with_models(trees=False))


def miss(result: walkforward.Result, name: str, keep: np.ndarray) -> float:
    return float(((result.margins[name][keep] - result.games["actual"].to_numpy(dtype=float)[keep]) ** 2).mean())


# ---- the pool's rules and the curve: the same answers the dashboard gives ----------------------------
class Rules(unittest.TestCase):
    def test_who_is_credited(self):
        credited = probability.credited_home(
            np.array([7.0, 6.0, -7.0, -6.0, 3.0, -3.0, 0.0, np.nan, 7.0]),
            np.array([7.0, 7.0, 7.0, 7.0, np.nan, np.nan, np.nan, np.nan, 6.5]),
            ["home", "home", "away", "away", "", "", "", "", "home"])
        # a win by exactly the line goes to the favourite; one short goes to the underdog
        np.testing.assert_array_equal(credited[:6], [1.0, 0.0, 0.0, 1.0, 1.0, 0.0])
        self.assertTrue(np.isnan(credited[6]))          # a tie on a straight game credits nobody
        self.assertTrue(np.isnan(credited[7]))          # no result
        self.assertEqual(credited[8], 1.0)              # a 6.5 line needs 7

    def test_chances_are_the_dashboards_own(self):
        """Game for game, the curve in use here gives what luck.credited_chance gives."""
        curve = probability.InUse()
        for margin in (-13.5, -6.6, -3.0, -0.4, 0.0, 0.2, 2.5, 3.0, 6.9, 7.0, 10.3, 16.0):
            for line, favourite in ((None, ""), (7.0, "home"), (7.0, "away"), (9.5, "home"), (13.0, "away"), (3.0, "home")):
                game = Game(1, "GREEN BAY", "chicago", line=line,
                            line_favourite="" if line is None else ("GREEN BAY" if favourite == "home" else "chicago"))
                theirs = luck.credited_chance(game, margin, game.home)
                mine = probability.home_chance(curve, margin, np.nan if line is None else line, favourite)
                self.assertAlmostEqual(mine, theirs, places=9, msg=f"margin {margin}, line {line} {favourite}")

    def test_a_refit_at_the_same_widths_is_the_same_curve(self):
        keys = np.array([analytics.KEY_WEIGHT.get(abs(d), 1.0) for d in analytics.MARGIN_RANGE])
        for margin in (0.0, 2.5, 7.0, 13.5):
            mine = probability.distributions(np.array([margin]), analytics.SPREAD_SD, analytics.TAIL_RATIO,
                                             analytics.TAIL_SHARE, keys)[0]
            theirs = np.array([p for _, p in analytics.margin_distribution(margin)])
            np.testing.assert_allclose(mine, theirs, atol=1e-9)

    def test_key_numbers_counted_the_dashboards_way(self):
        mine = probability.key_weights(analytics.MARGIN_FREQUENCY)
        theirs = np.array([analytics.KEY_WEIGHT.get(abs(d), 1.0) for d in analytics.MARGIN_RANGE])
        np.testing.assert_allclose(mine, theirs, atol=1e-12)

    def test_big_loser_chance_is_the_dashboards_own(self):
        margins = np.array([-14.0, -7.0, -3.0, 0.0, 2.5, 10.0])
        np.testing.assert_allclose(probability.rout_chances(margins),
                                   [analytics.rout_chance(m) for m in margins], atol=1e-12)

    def test_curves_learn_only_from_what_they_are_given(self):
        draw = np.random.default_rng(3)
        line = np.round(draw.normal(0, 6, 3000) * 2) / 2
        tight = np.round(line + draw.normal(0, 7, 3000))
        loose = np.round(line + draw.normal(0, 16, 3000))
        narrow, wide = probability.Refitted().fit(line, tight), probability.Refitted().fit(line, loose)
        # results that scatter more make a 7-point favourite less sure of winning
        self.assertGreater(probability.clears(narrow, 7.0, 1), probability.clears(wide, 7.0, 1))
        counted = probability.Counted().fit(line, tight)
        self.assertAlmostEqual(float(counted.at_least(3.0)[0]), 1.0, places=9)
        self.assertGreater(probability.clears(counted, 7.0, 1), probability.clears(counted, 1.0, 1))


# ---- the table: what is read, what is refused, what is left out and said --------------------------------
ARCHIVE = """Home,Road,line,lineopen,linemidweek,linesag,linemass,lineavg,linestd,week,hscore,rscore,neutral
Green Bay,Chicago,6.5,7,6.5,5.1,8.2,6.6,1.5,1,27,10,0
Dallas,N.Y. Giants,-3,-2.5,-3,-1,-4.2,-2.6,1.1,1,13,20,0
Miami,Buffalo,2,2.5,2,1.5,3,2.2,0.7,1,17,14,0
Denver,Kansas City,-1,-1,-1,0.5,-2,-0.8,1,1,24,21,0
Seattle,Arizona,4,4,4,3,5,4,1,1,30,3,0
Atlantis,Chicago,3,3,3,3,3,3,1,2,10,7,0
Detroit,Minnesota,1,1,1,2,0,1,1,2,,,0
Philadelphia,Dallas,3,3,3,2,4,3,1,19,24,21,0
"""


def verse_rows() -> pd.DataFrame:
    def row(week, home, away, hp, ap, kind="REG", closing=0.0):
        return {"season": 2005, "week": week, "kind": kind, "home": home, "away": away, "home_points": hp,
                "away_points": ap, "line_closing": closing, "total_closing": 44.0, "win_closing": 0.5, "rest": 0.0,
                "division": False, "neutral": False, "kickoff": 1.0e9}
    return pd.DataFrame([
        row(1, "gb", "chi", 27.0, 10.0, closing=6.0),
        row(1, "nyg", "dal", 20.0, 13.0, closing=3.5),        # the archive has this one the other way round
        row(1, "mia", "buf", 21.0, 14.0, closing=2.0),         # ...and a different score for this one
        row(1, "den", "kc", 24.0, 21.0, closing=-14.0),        # ...and a line 13 points from this one's
        row(1, "sea", "ari", 30.0, 3.0, closing=4.5),
        row(19, "phi", "dal", 24.0, 21.0, kind="DIV", closing=3.0),
    ])


class Table(unittest.TestCase):
    def test_archive_is_read_checked_and_joined(self):
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "nfl05.csv").write_text(ARCHIVE, encoding="utf-8")
            (Path(scratch) / "nfltotals05.csv").write_text("not,this,one\n", encoding="utf-8")
            self.assertEqual(list(data.archive_files(Path(scratch))), [2005])
            notes = data.Notes()
            found = data.history(Path(scratch), verse_rows(), notes)
        said = {i.code: i.rows for i in notes.items}
        self.assertEqual(sorted(found["game"]), ["2005-01-ari@sea", "2005-01-chi@gb", "2005-01-dal@nyg"])
        self.assertEqual(said["team"], 1)               # "Atlantis" is no team: left out, and said
        self.assertEqual(said["score"], 1)              # a score nflverse disagrees with: left out, not overwritten
        self.assertEqual(said["line"], 1)               # a line the wrong side of nflverse's by 13: left out
        self.assertEqual(said["postseason"], 1)
        self.assertEqual(said["unplayed"], 1)
        self.assertEqual(said["turned"], 1)
        turned = found.set_index("game").loc["2005-01-dal@nyg"]
        # the file has Dallas at home as a 3-point underdog; nflverse has the Giants at home, so: Giants by 3
        self.assertEqual((turned["home"], turned["line_updated"], turned["line_opening"], turned["actual"]),
                         ("nyg", 3.0, 2.5, 7.0))
        self.assertEqual((turned["m:sag"], turned["m:mass"]), (1.0, 4.2))
        packers = found.set_index("game").loc["2005-01-chi@gb"]
        self.assertEqual((packers["m:sag"], packers["m:mass"], packers["line_closing"]), (5.1, 8.2, 6.0))
        self.assertNotIn("m:avg", found.columns)        # the site's own average is not a model
        self.assertNotIn("m:midweek", found.columns)    # and its midweek line is a line
        self.assertEqual(packers["line_midweek"], 6.5)
        # the pool line the commissioner would have posted: the next whole number above the opening 7
        self.assertEqual((packers["pool_line"], packers["pool_favourite"]), (8.0, "home"))

    def test_check_says_what_it_takes_out(self):
        frame = made_up(seasons=2, weeks=5, games=12)
        frame["m:line2"] = frame["line_updated"] + 0.1                          # a betting line among the models
        frame.loc[frame.season == 2002, "m:m0"] = -frame.loc[frame.season == 2002, "m:m0"]   # one season backwards
        frame.loc[3, "m:m1"] = 250.0                                            # a misprint
        frame["line_updated"] = frame["line_updated"].astype(object)
        frame.loc[4, "line_updated"] = "seven"                                  # not a number
        frame = pd.concat([frame, frame.iloc[[10]]], ignore_index=True)         # the same game twice
        notes = data.Notes()
        clean = data.check(frame, notes)
        codes = [i.code for i in notes.items]
        self.assertEqual(len(clean), len(frame) - 2)                            # both copies of the doubled game go
        self.assertIn("duplicate", codes)
        self.assertNotIn("m:line2", clean.columns)
        self.assertIn("a betting line", codes)
        self.assertTrue(clean.loc[clean.season == 2002, "m:m0"].isna().all())
        self.assertFalse(clean.loc[clean.season == 2001, "m:m0"].isna().any())
        self.assertTrue(np.isnan(clean.loc[3, "m:m1"]))
        self.assertTrue(np.isnan(clean.loc[4, "line_updated"]))
        self.assertIn("type", codes)

    def test_a_number_taken_after_the_game_is_not_a_forecast(self):
        frame = made_up(seasons=1, weeks=2, games=4)
        frame["line_deadline"] = frame["line_updated"]
        frame["kickoff"], frame["locked_at"], frame["taken_at"] = 1000.0, 900.0, 800.0
        frame.loc[0, "taken_at"] = 1001.0               # after its own kickoff: the game goes
        frame.loc[1, "taken_at"] = 950.0                # after the deadline, before the game: no deadline line
        notes = data.Notes()
        clean = data.check(frame, notes)
        self.assertEqual(len(clean), len(frame) - 1)
        self.assertEqual(int(clean["line_deadline"].isna().sum()), 1)
        self.assertEqual([i.code for i in notes.of("error")], ["time", "time"])

    def test_a_later_number_is_refused(self):
        frame = made_up(seasons=1, weeks=2, games=14)
        frame["win_closing"], frame["total_closing"], frame["line_closing"] = 0.6, 44.0, frame["line_updated"]
        notes = data.Notes()
        early = features.prepare(frame, features.SETTINGS["opening"], notes)
        self.assertTrue(early["ml_gap"].isna().all() and early["total"].isna().all())
        self.assertTrue(early["move"].isna().all())     # the opening line has not moved from itself
        self.assertTrue(any(i.code == "refused" and "win_closing" in i.detail for i in notes.items))
        late = features.prepare(frame, features.SETTINGS["closing"])
        self.assertTrue(late["ml_gap"].notna().all() and late["move"].notna().all())

    def test_the_gap_is_the_one_the_picks_use(self):
        prepared = features.prepare(made_up(seasons=1, weeks=1, games=14), features.SETTINGS["updated"])
        models = [c for c in prepared.columns if c.startswith("m:")]
        slate = [predictions.Forecast(road=r["away"], home=r["home"], market=r["market"], opening=r["opening"],
                                      opinions=tuple(r[m] for m in models)) for _, r in prepared.iterrows()]
        lean, typical = predictions.home_lean(slate), predictions.typical_disagreement(slate)
        for (_, row), forecast in zip(prepared.iterrows(), slate):
            self.assertAlmostEqual(row["gap"], forecast.edge, places=9)
            self.assertAlmostEqual(row["apart"], forecast.disagreement, places=9)
            self.assertAlmostEqual(row["week_lean"], lean, places=9)
            self.assertAlmostEqual(row["typical"], typical, places=9)
        mine = recipes.deadeye_margins(prepared, 0.33)
        for value, forecast in zip(mine, slate):
            self.assertAlmostEqual(value, forecast.expected(0.33, lean, typical), places=9)

    def test_a_recipe_is_never_handed_the_answers(self):
        prepared = features.prepare(made_up(seasons=1, weeks=1), features.SETTINGS["updated"])
        asked = features.question(prepared)
        self.assertFalse(set(features.ANSWERS) & set(asked.columns))
        self.assertIn("market", asked.columns)

    def test_an_input_that_has_seen_the_result_is_caught(self):
        prepared = features.prepare(made_up(seasons=2, knows=0.3), features.SETTINGS["updated"])
        self.assertEqual(features.suspects(prepared), [])
        prepared["move"] = prepared["target"] + 0.5     # the result, filed under an honest name
        self.assertEqual([name for name, _ in features.suspects(prepared)], ["move"])


# ---- the walk-forward: finds what is there, invents nothing, cannot look ahead ---------------------------
class Walk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = walked(knows=1.0)
        cls.none = walked(knows=0.0, seed=5)

    def test_early_seasons_are_only_taught_from(self):
        asked = self.real.games.loc[self.real.asked, "season"]
        self.assertEqual(int(asked.min()), 2001 + walkforward.WARM_UP)
        self.assertEqual(self.real.seasons, list(range(2004, 2008)))
        self.assertEqual(self.real.held_back(2), [2006, 2007])
        self.assertEqual(self.real.held_back(3), [])            # too few seasons to hold three back

    def test_a_planted_edge_is_found(self):
        keep = self.real.common(["Ridge on the line's error", "Trained nudge", "Weighted crowd", recipes.LINE])
        self.assertGreater(int(keep.sum()), 400)
        line = miss(self.real, recipes.LINE, keep)
        for name in ("Ridge on the line's error", "Trained nudge", "Weighted crowd", "Straight-line fit"):
            self.assertLess(miss(self.real, name, keep), line - 10, name)
        nudges = [f["per unit"]["gap"] for f in self.real.fits if f["recipe"] == "Trained nudge" and f.get("per unit")]
        # the first season asked about has no seasons before it to choose a pull on, and is held well back
        self.assertLess(nudges[0], 0.5)
        self.assertTrue(all(0.7 < share < 1.1 for share in nudges[1:]), nudges)     # after that: the models knew all of it
        chosen = [f["share"] for f in self.real.fits if f["recipe"].endswith("share chosen on the past")]
        self.assertTrue(all(share >= 0.75 for share in chosen), chosen)

    def test_no_edge_is_invented(self):
        keep = self.none.common(["Ridge on the line's error", "Trained nudge", recipes.LINE])
        line = self.none.margins[recipes.LINE][keep]
        for name in ("Ridge on the line's error", "Trained nudge", "Weighted crowd"):
            self.assertLess(float(np.abs(self.none.margins[name][keep] - line).mean()), 0.5, name)
        chosen = [f["share"] for f in self.none.fits if f["recipe"].endswith("share chosen on the past")]
        self.assertEqual(set(chosen), {0.0})                    # believe none of it: the line was right
        pulls = [f["pull"] for f in self.none.fits if f["recipe"] == "Trained nudge" and "pull" in f]
        self.assertEqual(set(pulls[1:]), {max(recipes.PULLS)})

    def test_it_is_sealed(self):
        setting = features.SETTINGS["updated"]
        prepared = features.prepare(made_up(seasons=6), setting)
        ok, what = walkforward.sealed(prepared, setting, lambda: recipes.with_models(trees=False), 200505)
        self.assertTrue(ok, what)

    def test_the_seal_catches_a_cheat(self):
        setting = features.SETTINGS["updated"]
        prepared = features.prepare(made_up(seasons=6), setting)

        class Looker(recipes.Recipe):
            """Reads the results of the very week it is asked about, out of the table it was walked over."""
            name = "Looker"

            def __init__(self, frame):
                self.frame = frame

            def predict(self, rows):
                answers = dict(zip(self.frame["game"], self.frame["actual"]))
                return np.array([answers[g] for g in rows["game"]], dtype=float)

        # walkforward hands a recipe no table to look in; this one is given the walk's own, as a broken walk would
        import acql.training.walkforward as wf
        real_run = wf.run

        def leaky(prepared, setting, made, **kw):
            return real_run(prepared, setting, [recipes.Line(), Looker(prepared)], **kw)
        wf.run = leaky
        try:
            ok, what = walkforward.sealed(prepared, setting, lambda: [], 200505)
        finally:
            wf.run = real_run
        self.assertFalse(ok)
        self.assertIn("Looker", what)

    def test_scales_come_from_the_games_taught_on_alone(self):
        prepared = features.prepare(made_up(seasons=5), features.SETTINGS["updated"])
        past, later = prepared[prepared.season < 2005], features.question(prepared[prepared.season == 2005])
        for recipe in (recipes.ridge(), recipes.ridge(by_model=True), recipes.Weighted(), recipes.trained_nudge()):
            recipe.tune(past)
            recipe.fit(past)
            whole, part = recipe.predict(later), recipe.predict(later.iloc[:9])
            np.testing.assert_allclose(whole[:9], part, atol=1e-9, err_msg=recipe.name)   # a game's price does not depend on its neighbours

    def test_a_missing_input_is_filled_and_counted(self):
        prepared = features.prepare(made_up(seasons=5), features.SETTINGS["updated"])
        past, later = prepared[prepared.season < 2005], features.question(prepared[prepared.season == 2005]).copy()
        recipe = recipes.ridge()
        recipe.fit(past)
        later.loc[later.index[:7], "move"] = np.nan
        said = recipe.predict(later)
        self.assertFalse(np.isnan(said).any())
        self.assertEqual(recipe.filled, {"move": 7})

    def test_too_little_to_learn_from_says_nothing(self):
        prepared = features.prepare(made_up(seasons=1, weeks=2), features.SETTINGS["updated"])
        recipe = recipes.ridge()
        recipe.fit(prepared)
        self.assertTrue(np.isnan(recipe.predict(features.question(prepared))).all())

    def test_the_most_cautious_setting_the_best_cannot_beat(self):
        draw = np.random.default_rng(0)
        noise = draw.normal(0, 1, 500) ** 2
        same = {"bold": noise, "careful": noise + draw.normal(0, 0.01, 500)}
        self.assertEqual(recipes._closest(same, ["careful", "bold"]), "careful")
        clear = {"bold": noise, "careful": noise + 1.0}
        self.assertEqual(recipes._closest(clear, ["careful", "bold"]), "bold")


# ---- scoring -----------------------------------------------------------------------------------------
class Scoring(unittest.TestCase):
    def test_a_coin_flip_scores_what_a_coin_flip_scores(self):
        came = np.array([1.0, 0.0, 1.0, 0.0])
        flat = evaluate.score(np.full(4, 0.5), came)
        self.assertAlmostEqual(flat.logloss, 0.6931, places=4)
        self.assertAlmostEqual(flat.brier, 0.25)
        self.assertEqual(flat.right, 0)                         # 50% favours nobody, as the Model Lab scores it
        sure = evaluate.score(np.array([0.9, 0.1, 0.8, 0.3]), came, np.array([7.0, -7.0, 3.0, -1.0]),
                              np.array([10.0, -3.0, -4.0, np.nan]))
        self.assertEqual((sure.right, sure.games, sure.scored), (4, 4, 3))
        self.assertAlmostEqual(sure.expected, 0.9 + 0.9 + 0.8 + 0.7)
        self.assertAlmostEqual(sure.miss, (3 + 4 + 7) / 3)
        self.assertAlmostEqual(sure.lean, (-3 - 4 + 7) / 3)

    def test_chances_are_held_as_the_model_lab_holds_them(self):
        self.assertAlmostEqual(evaluate.score(np.array([1.0]), np.array([0.0])).logloss, -np.log(0.01), places=9)

    def test_a_duel_reads_the_range_not_the_record(self):
        draw = np.random.default_rng(4)
        weeks = np.repeat(np.arange(60), 14)
        truth = draw.uniform(0.3, 0.7, len(weeks))
        came = (draw.uniform(size=len(weeks)) < truth).astype(float)
        good, flat = truth, np.full(len(weeks), 0.5 + 1e-6)
        won = evaluate.duel(good, flat, came, weeks)
        self.assertGreater(won.low, 0)
        self.assertTrue(won.reading.startswith("better"))
        self.assertTrue(evaluate.duel(flat, good, came, weeks).reading.startswith("worse"))
        twin = evaluate.duel(good, np.clip(good + draw.normal(0, 0.01, len(weeks)), 0.02, 0.98), came, weeks)
        self.assertTrue(twin.low < 0 < twin.high)
        self.assertTrue(twin.reading.startswith("cannot be told apart"))
        self.assertEqual(won.split, won.only_first + won.only_second)

    def test_the_rule_for_a_switch_is_the_model_labs(self):
        for games, edge, right, service in ((60, 0.02, 40, 35), (150, 0.02, 100, 95), (150, 0.02, 90, 95),
                                            (150, 0.004, 100, 95), (150, -0.01, 100, 95)):
            mine = evaluate.Standing(games, edge, right, service).verdict
            theirs = modellab.Entry("Challenger", "", games=games, right=right, shared=games, shared_right=right,
                                    deadeye_right=service, shared_logloss=0.0, deadeye_logloss=edge * games).verdict
            self.assertEqual(mine, theirs)

    def test_changed_sides_lists_the_games_and_how_they_came_out(self):
        result = walked(knows=1.0, seasons=5)
        chances = study.chances_for(result)
        keep = result.common(["Trained nudge", recipes.LINE])
        table = evaluate.changed_sides(result, chances, "Trained nudge", recipes.LINE, keep)
        duel = evaluate.against(result, chances, "Trained nudge", recipes.LINE, keep)
        self.assertEqual(len(table), duel.sides)
        self.assertEqual(int(table["helped"].sum()), duel.only_first)
        self.assertEqual(len(table) - int(table["helped"].sum()), duel.only_second)


# ---- what is kept: taught challengers, frozen weeks ------------------------------------------------------
class Kept(unittest.TestCase):
    def setUp(self):
        self.prepared = features.prepare(made_up(seasons=5), features.SETTINGS["updated"])
        self.past = self.prepared[self.prepared.season < 2005]
        self.later = features.question(self.prepared[self.prepared.season == 2005])

    def test_a_kept_recipe_prices_as_it_did(self):
        recipe = recipes.ridge(by_model=True)
        recipe.tune(self.past)
        recipe.fit(self.past)
        with tempfile.TemporaryDirectory() as scratch:
            path = registry.save(recipe, setting="updated", before=2005, where=Path(scratch) / "ridge.json")
            again = registry.load(path)
            self.assertIsNotNone(again)
            np.testing.assert_allclose(again.predict(self.later), recipe.predict(self.later), atol=1e-9)
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((body["taught_through"], body["setting"], body["status"]),
                             (2004, "updated", registry.STATUS))

    def test_a_recipe_that_cannot_be_loaded_is_none_not_an_error(self):
        recipe = recipes.ridge()
        recipe.fit(self.past)
        with tempfile.TemporaryDirectory() as scratch:
            path = registry.save(recipe, setting="updated", before=2005, where=Path(scratch) / "ridge.json")
            self.assertIsNone(registry.load(Path(scratch) / "not-there.json"))
            body = json.loads(path.read_text(encoding="utf-8"))
            for spoil in ({"weights": [9.0] * len(body["weights"])}, {"training": "0.0"}, {"inputs": body["inputs"][:1]},
                          {"kind": "trees"}):
                path.write_text(json.dumps({**body, **spoil}), encoding="utf-8")
                self.assertIsNone(registry.load(path), spoil)
            path.write_text("{ not json", encoding="utf-8")
            self.assertIsNone(registry.load(path))
        self.assertIsNone(registry.save(recipes.Line(), setting="updated", before=2005))   # nothing to keep

    def test_a_week_is_frozen_once_before_its_deadline(self):
        rows = pd.DataFrame([
            {"season": 2030, "week": 4, "home": "gb", "away": "chi", "game": "2030-04-chi@gb", "locked_at": 1000.0,
             "credited_home": np.nan, "line_deadline": 6.5, "line_opening": 7.0, "line_used": 6.5, "m:sag": 5.0},
            {"season": 2030, "week": 3, "home": "dal", "away": "nyg", "game": "2030-03-nyg@dal", "locked_at": 400.0,
             "credited_home": 1.0, "line_deadline": 3.0, "line_opening": 3.0, "line_used": 3.0, "m:sag": 2.0},
        ])
        with tempfile.TemporaryDirectory() as scratch:
            real, snapshots.folder = snapshots.folder, lambda: Path(scratch)
            try:
                done = snapshots.take(rows, now=900.0)
                self.assertEqual([p.name for p, _ in done], ["2030-04.json"])       # week 3 has a result: past freezing
                moved = rows.assign(**{"line_deadline": 4.0, "m:sag": 9.0, "m:new": 1.0})
                self.assertIn("kept as it was", snapshots.take(moved, now=1100.0)[0][1])    # after the lock: stands
                self.assertEqual(snapshots.read(done[0][0])["games"][0]["line_deadline"], 6.5)
                snapshots.take(rows.assign(line_deadline=6.0), now=950.0)           # a later look, still before it
                self.assertEqual(snapshots.read(done[0][0])["games"][0]["line_deadline"], 6.0)
                back = snapshots.overlay(moved)
                frozen = back.set_index("game").loc["2030-04-chi@gb"]
                self.assertEqual((frozen["line_deadline"], frozen["m:sag"]), (6.0, 5.0))
                self.assertTrue(np.isnan(frozen["m:new"]))                          # a model the card never saw
                self.assertEqual(back.set_index("game").loc["2030-03-nyg@dal", "line_deadline"], 4.0)
            finally:
                snapshots.folder = real

    def test_a_late_freeze_is_marked_late(self):
        rows = pd.DataFrame([{"season": 2030, "week": 5, "home": "gb", "away": "chi", "game": "2030-05-chi@gb",
                              "locked_at": 1000.0, "credited_home": np.nan, "line_used": 6.5}])
        with tempfile.TemporaryDirectory() as scratch:
            real, snapshots.folder = snapshots.folder, lambda: Path(scratch)
            try:
                path, what = snapshots.take(rows, now=2000.0)[0]
                self.assertIn("LATE", what)
                self.assertFalse(snapshots.read(path)["before_deadline"])
                self.assertTrue(snapshots.frozen().empty)                           # never mistaken for the real thing
            finally:
                snapshots.folder = real


# ---- the live model is out of reach ---------------------------------------------------------------------
class Apart(unittest.TestCase):
    def test_nothing_in_the_dashboard_imports_the_training_ground(self):
        pattern = re.compile(r"acql\.training|from\s+\.+training\b|from\s+\.+\s+import[^\n]*\btraining\b")
        guilty = [str(path.relative_to(ROOT)) for path in (ROOT / "acql").rglob("*.py")
                  if "training" not in path.relative_to(ROOT / "acql").parts
                  and pattern.search(path.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(guilty, [])

    def test_the_whole_run_stands_on_nothing(self):
        """With no archives, no nflverse and no database, a run still finishes and says why it is empty."""
        with tempfile.TemporaryDirectory() as scratch:
            from acql.training import report
            real_history, real_folder = data.history, data.folder
            data.history = lambda *a, notes=None, **k: pd.DataFrame()
            data.folder = lambda: Path(scratch)
            try:
                found = study.run(books_too=False)
                text = report.render(found)
            finally:
                data.history, data.folder = real_history, real_folder
        self.assertFalse(found.has_models)
        self.assertIn("nothing", [i.code for i in found.notes.of("error")])
        self.assertIn("The main experiment could not be run", text)


# ---- against the real dashboard, when its files are here -------------------------------------------------
class Real(unittest.TestCase):
    def test_this_seasons_table_is_the_model_labs(self):
        """Scored here, Deadeye and the line come out exactly as the Model Lab has them."""
        from acql import store
        if not store.db_path().is_file():
            self.skipTest("no dashboard database here")
        notes = data.Notes()
        with study.books():
            from acql.config import Settings
            from acql.names import AliasTable
            from acql.repository import load_season
            season = load_season(Settings.load(), AliasTable.load(), online=False)
            if season.is_empty:
                self.skipTest("no season loaded")
            lab = modellab.run(season)
            rows = data.check(data.this_season(season, notes), notes)
        found = study.this_season(rows, "used", notes)
        service, line = lab.service, lab.entry(modellab.LINE)
        if found is None or service is None or line is None:
            self.skipTest("nothing graded yet")
        marks = found.marks()
        for mine, theirs in ((marks[study.LIVE], service), (marks[recipes.LINE], line)):
            self.assertEqual((mine.games, mine.right), (theirs.games, theirs.right))
            self.assertAlmostEqual(mine.logloss, theirs.mean_logloss, places=6)
            self.assertAlmostEqual(mine.brier, theirs.mean_brier, places=6)

    def test_real_history_passes_its_own_checks(self):
        from acql import nflverse
        if not nflverse.available():
            self.skipTest("the nflverse files are not in data/nflverse")
        notes = data.Notes()
        history = data.check(data.history(notes=notes), notes)
        self.assertGreater(len(history), 6000)
        self.assertFalse([i for i in notes.of("error") if i.code == "sign"])        # no season runs backwards
        self.assertLess(sum(i.rows for i in notes.of("error")), 0.01 * len(history))   # and little is left out
        prepared = features.prepare(history, features.SETTINGS["closing"] if "line_closing" in history.columns
                                    and history["line_closing"].notna().any() else features.SETTINGS["updated"])
        self.assertEqual(features.suspects(prepared), [])
        # a favourite of a touchdown or more at home wins far more often than not: the sign is the home side's
        big = prepared[prepared["market"] >= 7]
        self.assertGreater(float((big["actual"] > 0).mean()), 0.7)


def main() -> int:
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
