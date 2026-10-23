#!/usr/bin/env python3
"""Tests for the strategy lab (acql/training/strategylab.py) and its locked forecasts (lablocks.py).

    python tests/test_strategy_lab.py

On made-up games: team ratings only look backwards, a result scrambled
later moves nothing priced earlier, a planted edge is found and no edge is
not, the multiple-testing correction only ever gets stricter, and a locked
week can be neither rewritten nor quietly edited. No Qt is imported, and
nothing touches the real data folder.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_training import made_up  # noqa: E402

from acql.training import lablocks, strategylab as lab  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)
_KEPT: dict = {}


def history(knows: float, seasons: int = 9) -> pd.DataFrame:
    key = (knows, seasons)
    if key not in _KEPT:
        _KEPT[key] = made_up(seasons=seasons, weeks=12, knows=knows, seed=3)
    return _KEPT[key].copy()


def framed(knows: float, seasons: int = 9) -> pd.DataFrame:
    h = history(knows, seasons)
    return lab.table(h, "updated", universe=lab.results_universe(h, verse=False))


def small_line_up() -> list[lab.Spec]:
    specs = [lab.MARKET_SPEC, lab.DEADEYE_SPEC,
             lab.Spec("elo", "Elo", {"column": "p_" + lab.DEFAULT_ELO}),
             lab.Spec("logistic", "Logistic: market + Deadeye's view", {}, lab.inputs_of("market", "deadeye")),
             lab.Spec("logistic", "Logistic: market + Elo", {}, lab.inputs_of("market", "elo"))]
    specs.append(lab.Spec("stack", "Meta", {}, members=(lab.MARKET_SPEC.id, lab.DEADEYE_SPEC.id, specs[2].id)))
    specs.append(lab.Spec("mean", "Mean", members=(lab.MARKET_SPEC.id, lab.DEADEYE_SPEC.id)))
    return specs


class Ratings(unittest.TestCase):
    def test_a_week_is_priced_before_its_results_are_taken_in(self):
        h = history(0.0)
        u = lab.results_universe(h, verse=False)
        clean = lab.ratings(u)
        cut = int(u["order"].iloc[len(u) // 2])
        spoiled = u.copy()
        later = spoiled["order"] >= cut
        spoiled.loc[later, "home_points"] = spoiled.loc[later, "home_points"].to_numpy()[::-1]
        dirty = lab.ratings(spoiled)
        upto = (u["order"] <= cut).to_numpy()
        for col in clean.columns[1:]:
            np.testing.assert_allclose(clean.loc[upto, col], dirty.loc[upto, col], err_msg=col)
        after = (u["order"] > cut).to_numpy()
        self.assertFalse(np.allclose(clean.loc[after, lab.DEFAULT_ELO], dirty.loc[after, lab.DEFAULT_ELO]))

    def test_a_better_team_gets_a_better_rating(self):
        rows = []
        for week in range(1, 13):
            rows.append({"season": 2001, "week": week, "home": "gb", "away": "chi", "home_points": 30.0,
                         "away_points": 10.0, "neutral": 0})
        u = lab.results_universe(pd.DataFrame(rows), verse=False)
        r = lab.ratings(u)
        self.assertGreater(r[lab.DEFAULT_ELO].iloc[-1], r[lab.DEFAULT_ELO].iloc[0])
        self.assertGreater(r[lab.DEFAULT_SCORE].iloc[-1], r[lab.DEFAULT_SCORE].iloc[0])


class Statistics(unittest.TestCase):
    def test_holm(self):
        got = lab.holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(got["a"], 0.03)
        self.assertAlmostEqual(got["c"], 0.06)
        self.assertAlmostEqual(got["b"], 0.06)       # never below an earlier step

    def test_earlier_tries_only_make_it_stricter(self):
        once = lab.holm({"a": 0.01})
        counted = lab.holm({"a": 0.01}, tried=10)
        self.assertGreater(counted["a"], once["a"])
        self.assertAlmostEqual(counted["a"], 0.10)

    def test_paired_is_level_on_the_same_chances(self):
        p = np.array([0.6, 0.4, 0.7, 0.55])
        y = np.array([1.0, 0.0, 0.0, 1.0])
        found = lab.paired(p, p, y, np.array([1, 1, 2, 2]))
        self.assertEqual(found["edge"], 0.0)
        self.assertGreaterEqual(found["p"], 0.5)

    def test_a_logistic_on_nothing_stays_with_the_market(self):
        draw = np.random.default_rng(4)
        market = draw.uniform(0.25, 0.75, 4000)
        y = (draw.uniform(size=4000) < market).astype(float)
        rows = pd.DataFrame({"l_market": lab.logit(market), "noise": draw.normal(size=4000),
                             "abs_market": 0.0, "season": np.repeat(np.arange(2001, 2009), 500)})
        model = lab.build(lab.Spec("logistic", "t", {}, ("noise",)))
        model.fit(rows, y)
        said = model.predict(rows)
        self.assertLess(np.abs(said - market).max(), 0.05)


class Walk(unittest.TestCase):
    def test_nothing_priced_before_a_week_moves_when_later_results_are_scrambled(self):
        h = history(1.0)
        ok, what = lab.sealed(h, "updated", small_line_up(), 2007 * 100 + 6)
        self.assertTrue(ok, what)

    def test_a_planted_edge_is_found_and_none_is_not(self):
        for knows, should in ((1.0, True), (0.0, False)):
            f = framed(knows)
            specs = small_line_up()
            chances, _ = lab.walk(f, specs)
            dev, _ = lab._masks(f, chances, specs)
            self.assertGreater(dev.sum(), 300)
            scored = lab.score_window(f, chances, specs, dev)
            best = scored[specs[3].id]["vs_deadeye"]
            if should:
                self.assertGreater(best["edge"], 0, best)
                self.assertLess(best["p"], 0.05, best)
            else:
                self.assertGreater(best["p"], 0.01, best)

    def test_learned_strategies_are_only_asked_after_their_warm_up(self):
        f = framed(0.0)
        specs = small_line_up()
        # a meta-learner over a learned strategy waits for that strategy's out-of-sample record
        specs.append(lab.Spec("stack", "Meta over learned", {}, members=(lab.MARKET_SPEC.id, specs[3].id)))
        chances, _ = lab.walk(f, specs)
        seasons = sorted(f["season"].unique())
        first = f["season"] == seasons[lab.PROTOCOL["warm_up_seasons"] - 1]
        self.assertTrue(chances.loc[first, specs[3].id].isna().all())
        self.assertTrue(chances.loc[first, lab.MARKET_SPEC.id].notna().all())
        meta_first = f["season"] == seasons[lab.PROTOCOL["warm_up_seasons"] + 1]
        self.assertTrue(chances.loc[meta_first, specs[-1].id].isna().all())
        meta_go = f["season"] == seasons[lab.PROTOCOL["warm_up_seasons"] + lab.PROTOCOL["meta_warm_up_seasons"]]
        self.assertTrue(chances.loc[meta_go, specs[-1].id].notna().all())

    def test_the_test_seasons_are_only_scored_for_frozen_finalists(self):
        t = lab.Timing("updated", pd.DataFrame(), pd.DataFrame(), [], {}, np.array([]), np.array([]), {})
        with self.assertRaises(RuntimeError):
            lab.score_test(t, ["x"], {})
        with self.assertRaises(RuntimeError):
            lab.score_test(t, ["x"], {"finalists": ["y"]})

    @unittest.skipUnless(lab.have("lightgbm"), "lightgbm not installed")
    def test_boosted_trees_start_from_the_market(self):
        f = framed(0.0)
        spec = lab.Spec("lightgbm", "t", {"num_leaves": 3}, lab.inputs_of("market", "deadeye"))
        chances, _ = lab.walk(f, [lab.MARKET_SPEC, lab.DEADEYE_SPEC, spec])
        said = chances[spec.id].dropna()
        market = chances.loc[said.index, lab.MARKET_SPEC.id]
        self.assertGreater(np.corrcoef(said, market)[0, 1], 0.8)


class Locks(unittest.TestCase):
    def setUp(self):
        self.where = Path(tempfile.mkdtemp())
        self.made = [{"game": "2026-08-car@gb", "chances": {"market-x": 0.6}}]

    def tearDown(self):
        for p in self.where.glob("*"):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)

    def test_a_week_is_locked_once(self):
        lablocks.lock(2026, 8, 2000.0, self.made, now=1000.0, root=self.where)
        before = lablocks.path_for(2026, 8, self.where).read_bytes()
        with self.assertRaises(lablocks.LockRefused):
            lablocks.lock(2026, 8, 2000.0, [{"game": "2026-08-car@gb", "chances": {"market-x": 0.9}}],
                          now=1500.0, root=self.where)
        self.assertEqual(lablocks.path_for(2026, 8, self.where).read_bytes(), before)
        self.assertEqual(lablocks.verify(self.where), [])

    def test_no_lock_after_the_deadline(self):
        with self.assertRaises(lablocks.LockRefused):
            lablocks.lock(2026, 8, 2000.0, self.made, now=2000.0, root=self.where)
        self.assertFalse(lablocks.path_for(2026, 8, self.where).exists())

    def test_an_edit_is_caught(self):
        path = lablocks.lock(2026, 8, 2000.0, self.made, now=1000.0, root=self.where)
        lablocks.lock(2026, 9, 3000.0, self.made, now=1100.0, root=self.where)
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        body = json.loads(path.read_text())
        body["forecasts"][0]["chances"]["market-x"] = 0.99
        path.write_text(json.dumps(body))
        found = lablocks.verify(self.where)
        self.assertTrue(any("changed since it was locked" in f for f in found), found)

    def test_a_file_outside_the_chain_is_caught(self):
        (self.where / "2026-w10.json").write_text("{}")
        self.assertTrue(any("not in the chain" in f for f in lablocks.verify(self.where)))


def _results(sid: str, dev_edge: float = 0.01, leak: bool = True) -> dict:
    """The least of a two-track run's results that judging needs."""
    dev = {"vs_deadeye": {"edge": dev_edge}, "picks_vs_deadeye": {"edge": dev_edge * 10}}
    return {"run": "t", "primary_timing": "midweek", "faulty_share": 0.0,
            "finalists": {t: [sid] for t in lab.TRACKS},
            "leak": {t: (leak, "") for t in lab.TRACKS},
            "tracks": {t: {"timings": {"midweek": {"specs": {sid: {"dev": dev}}}}} for t in lab.TRACKS}}


def _locked(n: int, weeks: int, finalist_knows: bool, seed: int = 5) -> pd.DataFrame:
    """Locked rows: the truth q; the finalist says q (or noise), Deadeye and the market a blurred q."""
    draw = np.random.default_rng(seed)
    q = draw.uniform(0.2, 0.8, n)
    y = (draw.uniform(size=n) < q).astype(float)
    blur = lambda: lab.sigmoid(lab.logit(q) + draw.normal(0, 0.9, n))  # noqa: E731
    return pd.DataFrame({"game": [f"g{i}" for i in range(n)], "week": [f"w{i % weeks:02d}" for i in range(n)],
                         "y": y, "fin-1": q if finalist_knows else blur(),
                         lab.MARKET_SPEC.id: blur(), lab.DEADEYE_SPEC.id: blur()})


class Tracks(unittest.TestCase):
    """strategy-lab-2: the two questions are answered, taught and judged apart."""

    def test_each_target_has_its_own_answer(self):
        h = history(0.5)
        uni = lab.results_universe(h, verse=False)
        cred = lab.table(h, "updated", universe=uni, target="credited")
        win = lab.table(h, "updated", universe=uni, target="home_win")
        self.assertEqual(list(cred["game"]), list(win["game"]))           # the same games either way
        np.testing.assert_array_equal(cred["y"].to_numpy(), cred["credited"].to_numpy())
        a = win["actual"].to_numpy(dtype=float)
        played = ~np.isnan(a) & (a != 0)
        np.testing.assert_array_equal(win["y"].to_numpy()[played], (a[played] > 0).astype(float))
        self.assertTrue(np.isnan(win["y"].to_numpy()[a == 0]).all())     # a tie answers nothing
        with self.assertRaises(ValueError):
            lab.table(h, "updated", universe=uni, target="spread")

    def test_the_home_win_chance_ignores_the_pool_line(self):
        h = history(0.5)
        uni = lab.results_universe(h, verse=False)
        cred = lab.table(h, "updated", universe=uni, target="credited")
        win = lab.table(h, "updated", universe=uni, target="home_win")
        lined = cred["pool_line"].notna().to_numpy()
        straight = lab.curve_chance(win["market"].to_numpy(dtype=float), np.full(len(win), np.nan), [""] * len(win))
        np.testing.assert_allclose(win["p_market"].to_numpy(), straight)
        np.testing.assert_allclose(win["p_market"].to_numpy()[~lined], cred["p_market"].to_numpy()[~lined])
        if lined.any():   # favourites asked to cover a pool line are less likely credited than to win
            self.assertTrue((np.abs(win["p_market"].to_numpy()[lined] - 0.5)
                             > np.abs(cred["p_market"].to_numpy()[lined] - 0.5) - 1e-9).all())

    def test_a_track_is_sealed_on_its_own_answer(self):
        ok, what = lab.sealed(history(1.0), "updated", small_line_up(), 2007 * 100 + 6, target="home_win")
        self.assertTrue(ok, what)

    def test_picks_count_only_the_games_on_another_side(self):
        y = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
        same = np.array([0.6, 0.4, 0.3, 0.7, 0.6, 0.4])
        weeks = np.array([1, 1, 2, 2, 3, 3])
        level = lab.picks_paired(same, same, y, weeks)
        self.assertEqual((level["edge"], level["flips"]), (0.0, 0))
        better = same.copy()
        better[2], better[3] = 0.7, 0.3                                   # week 2 turned the right way
        found = lab.picks_paired(better, same, y, weeks)
        self.assertEqual(found["flips"], 2)
        self.assertAlmostEqual(found["edge"], 2 / 3)

    def test_a_finalist_that_knows_more_is_nominated_on_enough_locked_weeks(self):
        res = _results("fin-1")
        got = lablocks.judge_rows({t: _locked(420, 30, True) for t in lab.TRACKS}, res)
        self.assertEqual(got["probability"]["nominee"], "fin-1", got["probability"]["finalists"]["fin-1"]["gates"])

    def test_too_few_locked_games_never_nominate(self):
        got = lablocks.judge_rows({t: _locked(120, 9, True) for t in lab.TRACKS}, _results("fin-1"))
        for track in lab.TRACKS:
            self.assertIsNone(got[track]["nominee"])
            self.assertFalse(got[track]["finalists"]["fin-1"]["gates"]["locked: 150+ games over 10+ weeks"])

    def test_no_edge_no_nomination_and_a_failed_leak_check_blocks(self):
        got = lablocks.judge_rows({t: _locked(420, 30, False) for t in lab.TRACKS}, _results("fin-1"))
        self.assertIsNone(got["probability"]["nominee"])
        blocked = lablocks.judge_rows({t: _locked(420, 30, True) for t in lab.TRACKS}, _results("fin-1", leak=False))
        self.assertIsNone(blocked["probability"]["nominee"])
        behind = lablocks.judge_rows({t: _locked(420, 30, True) for t in lab.TRACKS}, _results("fin-1", dev_edge=-0.01))
        self.assertIsNone(behind["probability"]["nominee"])

    def test_locked_rows_answer_each_question_from_the_results(self):
        where = Path(tempfile.mkdtemp())
        try:
            forecasts = [{"game": "2026-08-car@gb", "tracks": {"probability": {"m": 0.7}, "acql": {"m": 0.55}}},
                         {"game": "2026-08-bal@buf", "tracks": {"probability": {"m": 0.4}, "acql": {"m": 0.45}}}]
            lablocks.lock(2026, 8, 2000.0, forecasts, now=1000.0, root=where)
            books = pd.DataFrame({"season": [2026, 2026], "week": [8, 8], "home": ["gb", "buf"], "away": ["car", "bal"],
                                  # gb won by 3 but did not cover its 7-point pool line; bal@buf a tie
                                  "home_points": [24.0, 20.0], "away_points": [21.0, 20.0],
                                  "credited_home": [0.0, 1.0]})
            rows = lablocks.locked_rows(where, books)
            self.assertEqual(rows["probability"]["y"].tolist(), [1.0])     # the tie answers nothing
            self.assertEqual(rows["acql"]["y"].tolist(), [0.0, 1.0])
            self.assertEqual(rows["probability"]["m"].tolist(), [0.7])
            self.assertEqual(lablocks.verify(where), [])
        finally:
            for p in where.glob("*"):
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)

    def test_a_meta_learner_brings_its_members_into_the_leak_check(self):
        specs = small_line_up()
        meta = lab.Spec("stack", "Meta over learned", {}, members=(lab.MARKET_SPEC.id, specs[3].id))
        specs.append(meta)
        picked = {s.id for s in lab.with_members(specs, [meta.id])}
        self.assertEqual(picked, {meta.id, lab.MARKET_SPEC.id, specs[3].id})
        ok, what = lab.sealed(history(1.0), "updated", lab.with_members(specs, [meta.id, lab.DEADEYE_SPEC.id]),
                              2007 * 100 + 6, target="home_win")
        self.assertTrue(ok, what)

    def test_the_protocols_stay_apart(self):
        self.assertEqual(lab.PROTOCOL["id"], "strategy-lab-1")
        self.assertNotEqual(lab.protocol_mark(lab.PROTOCOL), lab.protocol_mark(lab.PROTOCOL_2))
        self.assertEqual(set(lab.PROTOCOL_2["gates"]), set(lab.TRACKS))
        self.assertEqual({a["target"] for a in lab.TRACKS.values()}, set(lab.TARGETS))


class Apart(unittest.TestCase):
    def test_the_dashboard_never_imports_the_lab(self):
        for path in (ROOT / "acql").rglob("*.py"):
            if "training" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("strategylab", text, path)
            self.assertNotIn("lablocks", text, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
