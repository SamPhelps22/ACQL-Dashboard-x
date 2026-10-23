#!/usr/bin/env python3
"""Tests for Deadeye's own record (acql/training/record.py).

    python tests/test_record.py

On made-up rows: a card is the record only when saved before the lock and not
rebuilt, a card priced from another game's line is flagged but kept, each
track scores against its own answer, and ranges are left out on too few weeks.
No Qt; nothing touches the real data folder.
"""

from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.training import record  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)


def rows(weeks: int = 6, per: int = 14, status: str = record.RECORD, seed: int = 2) -> pd.DataFrame:
    draw = np.random.default_rng(seed)
    n = weeks * per
    market = draw.normal(0, 5, n).round(1)
    actual = (market + draw.normal(0, 13, n)).round()
    lined = np.abs(market) >= 6.5
    pool_line = np.where(lined, np.floor(np.abs(market)) + 1, np.nan)
    fav = np.where(lined, np.where(market > 0, "home", "away"), "")
    need = np.where(lined, pool_line, 1)
    fav_margin = np.where(market > 0, actual, -actual)
    credited = np.where(lined, np.where(fav_margin >= need, (market > 0) * 1.0, (market <= 0) * 1.0),
                        np.where(actual == 0, np.nan, (actual > 0) * 1.0))
    return pd.DataFrame({
        "week": np.repeat(np.arange(1, weeks + 1), per), "game": [f"g{i}" for i in range(n)], "status": status,
        "card_home_credited": 1 / (1 + np.exp(-market / 6)), "card_market": market, "line_deadline": market,
        "ledger_before": True, "ledger_deadeye": market * 0.9, "ledger_market": market,
        "pool_line": pool_line, "pool_favourite": fav, "replay_home_credited": 1 / (1 + np.exp(-market / 6)),
        "credited": credited, "actual": actual})


class Piles(unittest.TestCase):
    def test_only_a_card_saved_before_the_lock_is_the_record(self):
        self.assertEqual(record.card_status(100.0, 200.0, False), record.RECORD)
        self.assertEqual(record.card_status(200.0, 200.0, False), record.LATE)
        self.assertEqual(record.card_status(100.0, None, False), record.LATE)
        self.assertEqual(record.card_status(100.0, 200.0, True), record.REBUILT)

    def test_the_piles_are_scored_apart(self):
        both = pd.concat([rows(status=record.RECORD), rows(status=record.REBUILT, seed=3)], ignore_index=True)
        found = record.score(both)
        self.assertEqual(found["tracks"][record.RECORD]["acql"]["games"],
                         int(rows()["credited"].notna().sum()))
        self.assertIn(record.REBUILT, found["tracks"])


class Lines(unittest.TestCase):
    def test_a_card_priced_from_another_games_line_is_flagged_and_kept(self):
        r = rows()
        r.loc[3, "card_market"] = r.loc[3, "line_deadline"] + 8.0
        r.loc[5, "line_deadline"] = np.nan                       # unchecked is not flagged
        found = record.score(r)
        self.assertEqual(found["weeks"][1]["line_mismatch"], ["g3"])
        self.assertEqual(found["weeks"][1]["line_checked"], 13)
        everything = found["tracks"][record.RECORD]["acql"]["games"]
        matching = found["tracks"][record.RECORD + ", lines matching"]["acql"]["games"]
        self.assertEqual(everything - matching, 1)


class Tracks(unittest.TestCase):
    def test_each_track_answers_its_own_question(self):
        c = record.chances(rows())
        a = c["actual"].to_numpy()
        played = a != 0
        np.testing.assert_array_equal(c["prob_y"].to_numpy()[played], (a[played] > 0).astype(float))
        np.testing.assert_array_equal(c["acql_y"].to_numpy(), c["credited"].to_numpy())
        lined = c["pool_line"].notna().to_numpy()
        # the pool's line makes a favourite less likely to be credited than to win
        self.assertTrue((np.abs(c["acql_market"].to_numpy()[lined] - 0.5)
                         <= np.abs(c["prob_market"].to_numpy()[lined] - 0.5) + 1e-9).all())

    def test_the_probability_track_uses_only_margins_written_before_kickoff(self):
        r = rows()
        r.loc[r["week"] == 2, "ledger_before"] = False
        found = record.score(r)
        prob = found["tracks"][record.RECORD]["probability"]
        self.assertEqual(prob["weeks"], 5)

    def test_ranges_are_left_out_on_too_few_weeks(self):
        short = record.score(rows(weeks=2))["tracks"][record.RECORD]["acql"]["deadeye_vs_market"]
        self.assertIsNone(short["low"])
        self.assertIn("left out", short["range"])
        long = record.score(rows(weeks=6))["tracks"][record.RECORD]["acql"]["deadeye_vs_market"]
        self.assertIsNotNone(long["low"])

    def test_the_replay_drift_counts_sides_turned(self):
        r = rows()
        r.loc[0, "replay_home_credited"] = 1 - r.loc[0, "card_home_credited"] if abs(
            r.loc[0, "card_home_credited"] - 0.5) > 0.01 else 0.9
        found = record.score(r)["replay_drift"]
        self.assertEqual(found["other_side"], 1)
        self.assertGreater(found["largest"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
