#!/usr/bin/env python3
"""Tests for the research lab's scorecards, promotion gates and lab notebook.

    python tests/test_research_lab.py

Runs on the made-up games of test_training.py: a planted edge must be found
and pass the gates, no edge must not, a leak or bad data must block a
recommendation, the pool card must count picks under the pool's own rules,
and the notebook must only ever grow. No Qt is imported.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_training import walked  # noqa: E402

from acql.training import data, journal, scorecards, study, verdict  # noqa: E402

_CACHE: dict = {}


def studied(knows: float, sealed: bool = True) -> study.Study:
    if knows not in _CACHE:
        _CACHE[knows] = walked(knows, seasons=9, weeks=12)
    result = _CACHE[knows]
    found = study.Study(data.Notes(), pd.DataFrame(), pd.DataFrame())
    found.trials["updated"] = study.Trial(result, study.chances_for(result), pd.DataFrame())
    found.seals.append(("test", 0, sealed, ""))
    return found


class PoolCard(unittest.TestCase):
    def test_counts_picks_week_by_week(self):
        came = np.array([1, 1, 0, 0, 1, 0], dtype=float)
        first = np.array([0.7, 0.6, 0.3, 0.4, 0.6, 0.6])     # 5 right: wk1 2, wk2 2, wk3 1
        second = np.array([0.3, 0.6, 0.7, 0.4, 0.6, 0.4])    # 4 right: wk1 1, wk2 1, wk3 2
        card = scorecards.pool_card(first, second, came, np.array([1, 1, 2, 2, 3, 3]))
        self.assertEqual(card["weeks"], 3)
        self.assertAlmostEqual(card["per_week"], 5 / 3)
        self.assertAlmostEqual(card["in_use_per_week"], 4 / 3)
        self.assertEqual((card["ahead"], card["behind"], card["level"]), (2, 1, 0))
        self.assertLessEqual(card["low"], card["diff_per_week"])
        self.assertGreaterEqual(card["high"], card["diff_per_week"])

    def test_a_coin_flip_favours_nobody(self):
        card = scorecards.pool_card(np.array([0.5]), np.array([0.5]), np.array([1.0]), np.array([1]))
        self.assertEqual(card["per_week"], 0.0)


class Gates(unittest.TestCase):
    def test_a_planted_edge_is_found_and_only_recommended(self):
        cards = scorecards.build(studied(1.0), verdict.IN_USE)
        self.assertEqual(cards["champion"], verdict.IN_USE)          # never changed by the lab
        self.assertNotIn(verdict.IN_USE, cards["challengers"])
        self.assertIsNotNone(cards["recommendation"])
        best = cards["challengers"][cards["recommendation"]]
        self.assertEqual(best["status"], scorecards.ELIGIBLE)
        self.assertTrue(all(best["gates"].values()))
        for name, card in cards["challengers"].items():              # three cards, never added up
            self.assertEqual({"probability", "market", "pool"} <= set(card), True, name)

    def test_no_edge_only_less_model_reliance_can_pass(self):
        # With nothing in the models, only leaning on them less than the champion can honestly win.
        import re
        from acql.model import predictions
        from acql.training import recipes
        best = scorecards.build(studied(0.0), verdict.IN_USE)["recommendation"]
        share = re.fullmatch(r"\S+ at (\d+)%", best or "")
        self.assertTrue(best in (None, recipes.LINE) or (share and int(share.group(1)) / 100
                                                           < predictions.CONSENSUS_WEIGHT), best)

    def test_a_leak_blocks_everything(self):
        cards = scorecards.build(studied(1.0, sealed=False), verdict.IN_USE)
        self.assertIsNone(cards["recommendation"])
        self.assertTrue(all(not c["gates"]["no leak found"] for c in cards["challengers"].values()))

    def test_bad_data_blocks_everything(self):
        found = studied(1.0)
        found.notes.error("test", "a row was left out")
        self.assertIsNone(scorecards.build(found, verdict.IN_USE)["recommendation"])

    def test_small_samples_are_research_only(self):
        card = {"probability": {"games": 40, "edge": 0.02, "low": 0.01, "high": 0.03}, "held_back": None,
                "pool": {"weeks": 3, "high": 1.0}, "calibration": 0.01, "in_use_calibration": 0.01}
        card["gates"] = scorecards.gates(card, sealed=True, problems=0)
        self.assertEqual(scorecards.status(card), scorecards.RESEARCH)

    def test_clearly_worse_is_retired(self):
        card = {"probability": {"games": 900, "edge": -0.02, "low": -0.03, "high": -0.01}, "held_back": None,
                "pool": {"weeks": 60, "high": 0.2}, "calibration": 0.01, "in_use_calibration": 0.01}
        card["gates"] = scorecards.gates(card, sealed=True, problems=0)
        self.assertEqual(scorecards.status(card), scorecards.RETIRED)

    def test_nothing_to_score(self):
        cards = scorecards.build(study.Study(data.Notes(), pd.DataFrame(), pd.DataFrame()), verdict.IN_USE)
        self.assertEqual(cards["challengers"], {})
        self.assertIn("missing", cards)


class Notebook(unittest.TestCase):
    def test_only_ever_grows_and_remembers(self):
        found = studied(0.0)
        cards = scorecards.build(found, verdict.IN_USE)
        head = found.headline
        games = head.result.games[head.keep]
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            journal.record(cards, games, root, root, now=1.0)
            first = (root / journal.FILE).read_text(encoding="utf-8")
            journal.record(cards, games, root, root, now=2.0)
            second = (root / journal.FILE).read_text(encoding="utf-8")
            self.assertTrue(second.startswith(first))                       # appended, never rewritten
            runs = journal.read(root / journal.FILE)
            self.assertEqual(len(runs), 2)
            self.assertEqual(runs[0]["data"], runs[1]["data"])              # same games, same fingerprint
            self.assertTrue(runs[0]["data"])
            with (root / journal.FILE).open("a") as handle:
                handle.write("not json\n")
            self.assertEqual(len(journal.read(root / journal.FILE)), 2)     # a damaged line is skipped
            json.loads((root / journal.QUEUE).read_text(encoding="utf-8"))

    def test_retired_twice_means_stop(self):
        retired = {"status": scorecards.RETIRED, "prob_edge": -0.02, "prob_low": -0.03,
                   "calibration": 0.0, "in_use_calibration": 0.0}
        runs = [{"challengers": {"X": retired}}, {"challengers": {"X": retired}}]
        queue = journal.hypotheses(runs)
        self.assertEqual([q["kind"] for q in queue], ["stop"])
        self.assertEqual(journal.hypotheses(runs[:1]), [])                  # once is not enough

    def test_not_reproducible_is_flagged(self):
        a = {"data": "abc", "code": "1", "training": "t", "challengers": {"X": {"status": "challenger"}}}
        b = {**a, "challengers": {"X": {"status": "retired"}}}
        self.assertIn("reproducibility", [q["kind"] for q in journal.hypotheses([a, b])])

    def test_fingerprint_changes_with_a_result(self):
        games = pd.DataFrame({"game": ["a", "b"], "order": [1, 1], "actual": [3.0, -7.0], "credited": [1.0, 0.0]})
        other = games.assign(actual=[3.0, -6.0])
        self.assertNotEqual(journal.fingerprint(games), journal.fingerprint(other))


class ModelLabReads(unittest.TestCase):
    def test_reads_scorecards_and_queue(self):
        from acql.model import challengers
        found = studied(1.0)
        with tempfile.TemporaryDirectory() as scratch:
            latest = Path(scratch) / "training" / "latest"
            latest.mkdir(parents=True)
            verdict.write(found, latest)
            scorecards.write(found, latest, verdict.IN_USE)
            (latest / journal.QUEUE).write_text(json.dumps([{"model": "M", "kind": "wait", "says": "s"}]))
            real = challengers.data_dir
            challengers.data_dir = lambda: Path(scratch)
            try:
                answer = challengers.read()
            finally:
                challengers.data_dir = real
        self.assertEqual(answer.champion, verdict.IN_USE)
        self.assertIsNotNone(answer.recommendation)
        self.assertEqual(len(answer.queue), 1)
        self.assertTrue(all(len(row) == len(challengers.HEADERS) for row in answer.rows))
        self.assertTrue(any(row[7] != "-" for row in answer.rows))


if __name__ == "__main__":
    unittest.main(verbosity=1)
