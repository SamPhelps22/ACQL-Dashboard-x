"""Isolation, contract, rules, simulation, metrics and journal tests."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research_lab import acql_eval, config, contract
from research_lab.metrics import scoring
from research_lab.models import baselines
from research_lab.models.base import logistic, norm_cdf, norm_ppf
from research_lab.shadow import journal

LAB = config.ROOT / "research_lab"
ALLOWED_ACQL_IMPORTERS = {LAB / "adapters" / "deadeye.py", LAB / "acql_eval.py"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


class Isolation(unittest.TestCase):
    def test_only_the_adapters_import_the_dashboard(self):
        for path in LAB.rglob("*.py"):
            if path in ALLOWED_ACQL_IMPORTERS or "tests" in path.parts:
                continue
            bad = {n for n in _imports(path) if n == "acql" or n.startswith("acql.") or n.startswith("nflpickem")}
            self.assertFalse(bad, f"{path.relative_to(config.ROOT)} imports {bad}")

    def test_rules_module_imports_rules_only(self):
        text = (LAB / "acql_eval.py").read_text()
        self.assertIn("from acql.model.backtest import pool_line", text)
        for forbidden in ("pricing", "predictions", "Forecast"):
            self.assertNotIn(forbidden, text.replace("model's", ""))

    def test_no_model_reads_deadeye(self):
        for sub in ("models", "simulation", "features", "ensemble", "data", "backtest"):
            for path in (LAB / sub).rglob("*.py"):
                self.assertNotIn("adapters", "".join(_imports(path)), f"{path} imports the Deadeye adapter")

    def test_deadeye_and_challenger_untouched(self):
        out = subprocess.run(["git", "status", "--porcelain", "--", "acql", "nfl_pickem", "acql-forecasts.json",
                              "acql-picks.json", "acql-spreads.json"], cwd=config.ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "", "production files changed:\n" + out.stdout)


class Contract(unittest.TestCase):
    def _row(self, **kw):
        f = contract.Forecast(game_id="g", season=2020, week=1, home_team="A", away_team="B",
                              kickoff="2020-09-13T17:00:00+00:00", forecast_ts="2020-09-08T13:00:00+00:00",
                              info_set="week_start", p_home_raw=0.6, model="m", model_version="1",
                              train_cutoff="2020-09-01T00:00:00+00:00", feature_cutoff="2020-09-01T00:00:00+00:00")
        r = f.record()
        r.update(kw)
        return r

    def test_valid_row(self):
        df = pd.DataFrame([self._row()])
        self.assertEqual(contract.validate(df), [])
        self.assertAlmostEqual(df["p_home_raw"][0] + df["p_away_raw"][0], 1.0)

    def test_catches_problems(self):
        self.assertTrue(contract.validate(pd.DataFrame([self._row(p_away_raw=0.5)])))
        self.assertTrue(contract.validate(pd.DataFrame([self._row(forecast_ts="2020-09-13T18:00:00+00:00")])))
        self.assertTrue(contract.validate(pd.DataFrame([self._row(feature_cutoff="2020-09-10T00:00:00+00:00")])))
        self.assertTrue(contract.validate(pd.DataFrame([self._row(), self._row()])))
        self.assertTrue(contract.validate(pd.DataFrame([self._row(p_home_raw=1.2, p_away_raw=-0.2)])))


class Rules(unittest.TestCase):
    def test_pool_line_and_credit(self):
        # "(sf by 13)", 49ers 37-24: a win by exactly the line goes to the favourite
        self.assertEqual(acql_eval.credited(12.5, 13), "home")
        self.assertEqual(acql_eval.credited(-12.5, -13), "away")
        # "(det by 8)", Lions 31-30: recorded as a Saints win
        self.assertEqual(acql_eval.credited(7.0, 1), "away")
        # unlined: plain winner, a tie scores nobody
        self.assertEqual(acql_eval.credited(3.0, -1), "away")
        self.assertIsNone(acql_eval.credited(3.0, 0))
        # 6.5 is lined, 6 is not
        self.assertEqual(acql_eval.credited(6.5, 3), "away")
        self.assertEqual(acql_eval.credited(6.0, 3), "home")

    def test_pick_lined_game(self):
        # a 10-point home favourite the model sees as a 2-point favourite: take the dog
        self.assertEqual(acql_eval.pick(10.0, 0.55, 2.0, 13.5), "away")
        self.assertEqual(acql_eval.pick(10.0, 0.9, 20.0, 13.5), "home")
        self.assertEqual(acql_eval.pick(3.0, 0.45, None, None), "away")


class ChallengerElo(unittest.TestCase):
    def test_matches_nfl_pickem_formula(self):
        spec = importlib.util.spec_from_file_location("elo_src", config.ROOT / "nfl_pickem" / "nflpickem" / "models" / "elo.py")
        src = importlib.util.module_from_spec(spec)
        import sys
        sys.modules["elo_src"] = src
        spec.loader.exec_module(src)
        for d in (-200, -48, 0, 48, 300):
            self.assertAlmostEqual(src.expected_home(1500 + d, 1500, 0.0), baselines.elo_expected(d))
        for m, e in ((3, 50), (14, -80), (28, 200)):
            self.assertAlmostEqual(src.mov_mult(m, e), baselines.mov_mult(m, e))
        p = src.EloParams()
        self.assertEqual((p.initial_rating, p.k_factor, p.home_field_advantage, round(p.season_regression, 3)),
                         (baselines.ELO["initial"], baselines.ELO["k"], baselines.ELO["hfa"], baselines.ELO["regress"]))


class Numerics(unittest.TestCase):
    def test_norm(self):
        for x in (-2.5, -1, 0, 0.3, 1.96):
            self.assertAlmostEqual(float(norm_ppf(norm_cdf(x))), x, places=6)

    def test_logistic_recovers_coefficients(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=20000)
        y = (rng.random(20000) < 1 / (1 + np.exp(-(0.3 + 1.2 * x)))).astype(float)
        b = logistic(np.column_stack([np.ones_like(x), x]), y, lam=1e-6)
        self.assertAlmostEqual(b[0], 0.3, delta=0.06)
        self.assertAlmostEqual(b[1], 1.2, delta=0.06)

    def test_scores(self):
        self.assertAlmostEqual(float(scoring.log_loss([0.5], [1])[0]), np.log(2))
        self.assertAlmostEqual(float(scoring.brier([0.7], [1])[0]), 0.09)
        m, lo, hi, _ = scoring.block_bootstrap(np.ones(100), np.repeat(np.arange(10), 10))
        self.assertEqual((m, lo, hi), (1.0, 1.0, 1.0))

    def test_devig(self):
        self.assertAlmostEqual(float(baselines.devig(-110, -110)), 0.5)
        self.assertGreater(float(baselines.devig(-200, 170)), 0.6)


class Simulation(unittest.TestCase):
    def test_reproducible_and_sane(self):
        from research_lab.simulation import drives
        from research_lab.tests import fixtures
        if not fixtures.available():
            self.skipTest("lab data not fetched")
        st = fixtures.store()
        league = drives.League(st.drives, 2011, st.games)
        p = drives.drive_probs(league, 1.0, 1.0, 1.0)
        self.assertTrue(np.allclose(p.sum(axis=1), 1))
        a = drives.simulate(league, p, p, league.n_drives.mean(), n=2000, seed=5)
        b = drives.simulate(league, p, p, league.n_drives.mean(), n=2000, seed=5)
        np.testing.assert_array_equal(a[0], b[0])
        self.assertTrue((a[0] >= 0).all() and (a[1] >= 0).all())
        total = (a[0] + a[1]).mean()
        self.assertTrue(30 < total < 60, total)
        better = drives.drive_probs(league, 1.4, 1.2, 0.7)
        h, w = drives.simulate(league, better, p, league.n_drives.mean(), n=4000, seed=9)
        self.assertGreater(np.mean(h > w), 0.6)


class Journal(unittest.TestCase):
    def test_append_only_and_before_kickoff(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "j.jsonl"
            now = pd.Timestamp("2026-10-21T12:00:00Z")
            e = {"game_id": "g1", "model": "m", "info_set": "week_start", "model_version": "1",
                 "kickoff": "2026-10-25T17:00:00+00:00", "p_home_raw": 0.6}
            late = dict(e, game_id="g0", kickoff="2026-10-20T17:00:00+00:00")
            r = journal.append([e, late], path, now)
            self.assertEqual((r["written"], r["after_kickoff_skipped"]), (1, 1))
            r = journal.append([dict(e, p_home_raw=0.9)], path, now)
            self.assertEqual(r["duplicates_skipped"], 1)
            self.assertEqual(journal.read(path)[0]["p_home_raw"], 0.6)
            journal.correct(journal.read(path)[0], {"p_home_raw": 0.62}, "unit test", path)
            lines = journal.read(path)
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["p_home_raw"], 0.6)
            self.assertEqual(lines[1]["revision"], 1)


if __name__ == "__main__":
    unittest.main()
