#!/usr/bin/env python3
"""Tests for Operation Sunday (weekly learning, selection, Thursday lock).

Run from the project root:   python tests/test_operation_sunday.py

No network: everything runs on the labelled synthetic league
(operation_sunday.data.synthetic_games) or small hand-made frames.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from operation_sunday import acql_rules, data, schedule  # noqa: E402
from operation_sunday.backtest import (HoldoutGuard, HoldoutLocked, attach_outcomes, eval_week_keys,  # noqa: E402
                                       training_rows, walk_forward)
from operation_sunday.config import PromotionCriteria, load_settings  # noqa: E402
from operation_sunday.ensemble import ensemble_walk_forward  # noqa: E402
from operation_sunday.features import MarketSnapshot, build_features  # noqa: E402
from operation_sunday.journal import Journal, LockError, forecast_hash  # noqa: E402
from operation_sunday.models import BayesStrength, EloModel, Logistic, base_candidates  # noqa: E402
from operation_sunday.pipeline import run_week  # noqa: E402
from operation_sunday.registry import Registry  # noqa: E402
from operation_sunday.selection import decide  # noqa: E402
from operation_sunday.tz import USRuleZone, get_zone, to_utc  # noqa: E402

UTC = timezone.utc
SMALL = PromotionCriteria(min_games=100, min_weeks=10, bootstrap_samples=300)


def settings(tmp, **kw):
    base = dict(state_dir=str(tmp), first_training_season=2101, dev_eval_seasons=(2104, 2105),
                holdout_seasons=(2107,), promotion=SMALL)
    base.update(kw)
    return load_settings("/nonexistent.json", **base)


GAMES = data.synthetic_games()


def dataset(games=None, loaded_at=None):
    g = GAMES if games is None else games
    g, w = data.validate(g)
    return data.Dataset(g, data.version_of(g), "synthetic", loaded_at or datetime(2009, 1, 1, tzinfo=UTC), w)


def game_row(gid, season, week, when_utc, home="AAA", away="BBB", hs=20.0, as_=17.0, status="final"):
    return {"game_id": gid, "season": season, "week": week, "game_type": "REG",
            "kickoff_utc": pd.Timestamp(when_utc), "kickoff_time_known": True, "home": home, "away": away,
            "home_score": hs, "away_score": as_, "neutral": False, "div_game": 0, "roof": "outdoors",
            "status": status, "close_spread": 3.0, "close_total": 44.0, "home_ml": np.nan, "away_ml": np.nan,
            "home_qb": None, "away_qb": None}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- scheduling
class ScheduleTests(Tmp):
    def test_dst_is_resolved_per_week(self):
        s = settings(self.tmp, first_training_season=2000)
        g = pd.DataFrame([game_row("a", 2026, 7, "2026-10-25T17:00Z", status="scheduled"),
                          game_row("b", 2026, 9, "2026-11-08T18:00Z", status="scheduled")])
        d7 = schedule.deadline_for(g, 2026, 7, s)
        d9 = schedule.deadline_for(g, 2026, 9, s)
        self.assertEqual(d7.lock_utc.isoformat(), "2026-10-22T22:00:00+00:00")   # EDT
        self.assertEqual(d9.lock_utc.isoformat(), "2026-11-05T23:00:00+00:00")   # EST

    def test_early_kickoff_moves_lock(self):
        s = settings(self.tmp)
        g = pd.DataFrame([game_row("w", 2026, 12, "2026-11-26T01:00Z", status="scheduled"),   # Wed 20:00 ET
                          game_row("t", 2026, 12, "2026-11-26T18:00Z", status="scheduled"),
                          game_row("s", 2026, 12, "2026-11-29T18:00Z", status="scheduled"),
                          game_row("s2", 2026, 12, "2026-11-29T21:00Z", status="scheduled")])
        d = schedule.deadline_for(g, 2026, 12, s)
        self.assertEqual(d.lock_utc, pd.Timestamp("2026-11-26T01:00Z").to_pydatetime())
        self.assertIn("first kickoff", d.reason)
        s2 = settings(self.tmp, kickoff_margin_minutes=30)
        self.assertEqual(schedule.deadline_for(g, 2026, 12, s2).lock_utc,
                         pd.Timestamp("2026-11-26T00:30Z").to_pydatetime())

    def test_postponed_game_drops_out(self):
        s = settings(self.tmp)
        g = pd.DataFrame([game_row("x", 2026, 5, "2026-10-08T13:00Z", status="canceled"),
                          game_row("y", 2026, 5, "2026-10-11T17:00Z", status="scheduled")])
        d = schedule.deadline_for(g, 2026, 5, s)
        self.assertEqual(d.games, 1)
        self.assertEqual(d.lock_utc.isoformat(), "2026-10-08T22:00:00+00:00")

    def test_configurable_deadline_and_zone(self):
        s = settings(self.tmp, timezone="America/Los_Angeles", deadline_hour=12)
        g = pd.DataFrame([game_row("y", 2026, 5, "2026-10-11T17:00Z", status="scheduled")])
        self.assertEqual(schedule.deadline_for(g, 2026, 5, s).lock_utc.isoformat(), "2026-10-08T19:00:00+00:00")

    def test_rule_zone_matches_zoneinfo(self):
        rule = USRuleZone("America/New_York", -5)
        for stamp in ("2026-03-07T12:00", "2026-03-09T12:00", "2026-10-31T12:00", "2026-11-02T12:00", "2026-07-04T12:00"):
            naive = datetime.fromisoformat(stamp)
            self.assertEqual(naive.replace(tzinfo=rule).utcoffset(),
                             naive.replace(tzinfo=get_zone("America/New_York")).utcoffset(), stamp)

    def test_missing_clock_errs_early(self):
        raw = pd.DataFrame([{"game_id": "g", "season": 2026, "game_type": "REG", "week": 1, "gameday": "2026-09-13",
                             "gametime": None, "away_team": "A", "home_team": "B", "away_score": None, "home_score": None}])
        g = data.normalise_nflverse(raw)
        self.assertFalse(bool(g["kickoff_time_known"].iloc[0]))
        self.assertEqual(g["kickoff_utc"].iloc[0], pd.Timestamp("2026-09-13T04:00Z"))

    def test_timing_labels(self):
        s = settings(self.tmp)
        g = pd.DataFrame([game_row("y", 2026, 5, "2026-10-11T17:00Z", status="scheduled")])
        d = schedule.deadline_for(g, 2026, 5, s)
        self.assertEqual(schedule.timing(d, d.run_due_utc - timedelta(hours=1)).status, "on_time")
        self.assertEqual(schedule.timing(d, d.run_due_utc + timedelta(hours=1)).status, "late_start")
        late = schedule.timing(d, d.lock_utc + timedelta(minutes=1))
        self.assertEqual(late.status, "late")
        self.assertIn("LATE RUN", late.alert)


# ---------------------------------------------------------------- data validation
class DataTests(unittest.TestCase):
    def test_duplicates_dropped(self):
        g = pd.concat([GAMES.head(5), GAMES.head(1)])
        clean, warnings = data.validate(g)
        self.assertEqual(len(clean), 5)
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_future_score_ignored_and_bad_week_flagged(self):
        g = GAMES[GAMES["season"] == 2101].copy()
        g.loc[g.index[0], "kickoff_utc"] = pd.Timestamp("2001-12-30T18:00Z")   # wrong week
        clean, warnings = data.validate(g, now=datetime(2001, 9, 10, tzinfo=UTC))
        self.assertTrue(any("spanning" in w for w in warnings))
        self.assertTrue(any("future" in w for w in warnings))
        self.assertTrue(clean.loc[clean["game_id"] == g["game_id"].iloc[0], "home_score"].isna().all())


# ---------------------------------------------------------------- leakage
class LeakageTests(Tmp):
    def setUp(self):
        super().setUp()
        self.s = settings(self.tmp)
        self.f = build_features(GAMES, self.s)

    def test_training_rows_respect_cutoff(self):
        key = eval_week_keys(self.f, [2105])[5]
        cut = self.f[self.f["week_key"] == key]["cutoff_utc"].iloc[0]
        tr = training_rows(self.f, cut)
        self.assertTrue((tr["published_utc"] <= cut).all())
        self.assertFalse(tr["week_key"].apply(lambda k: k == key).any())

    def test_future_results_do_not_change_earlier_predictions(self):
        keys = eval_week_keys(self.f, [2105])
        target = keys[6]
        cut = self.f[self.f["week_key"] == target]["cutoff_utc"].iloc[0]
        g2 = GAMES.copy()
        later = g2["kickoff_utc"] >= cut
        rng = np.random.default_rng(1)
        g2.loc[later, "home_score"] = rng.integers(0, 50, later.sum()).astype(float)
        g2.loc[later, "away_score"] = rng.integers(0, 50, later.sum()).astype(float)
        f2 = build_features(g2, self.s)
        models = [EloModel(), BayesStrength(), Logistic()]
        a = walk_forward(self.f, models, keys[:7], self.s)
        b = walk_forward(f2, models, keys[:7], self.s)
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

    def test_same_week_thursday_result_is_not_a_feature(self):
        key = eval_week_keys(self.f, [2105])[3]
        week = self.f[self.f["week_key"] == key].sort_values("kickoff_utc")
        thursday = week.iloc[0]["game_id"]
        g2 = GAMES.copy()
        g2.loc[g2["game_id"] == thursday, ["home_score", "away_score"]] = [70.0, 0.0]
        f2 = build_features(g2, self.s)
        cols = ["elo_diff", "kal_margin", "kal_total"]
        pd.testing.assert_frame_equal(week[cols].reset_index(drop=True),
                                      f2[f2["week_key"] == key].sort_values("kickoff_utc")[cols].reset_index(drop=True))

    def test_post_cutoff_market_is_ignored(self):
        key = eval_week_keys(self.f, [2105])[3]
        row = self.f[self.f["week_key"] == key].iloc[0]
        late = MarketSnapshot(row["game_id"], row["cutoff_utc"].to_pydatetime() + timedelta(minutes=1), 0.9)
        early = MarketSnapshot(row["game_id"], row["cutoff_utc"].to_pydatetime() - timedelta(hours=1), 0.6)
        f2 = build_features(GAMES, self.s, [late])
        r2 = f2[f2["game_id"] == row["game_id"]].iloc[0]
        self.assertTrue(np.isnan(r2["mkt_logit"]))
        self.assertIn("market_after_cutoff_ignored", r2["missing_flags"])
        f3 = build_features(GAMES, self.s, [late, early])
        self.assertAlmostEqual(1 / (1 + np.exp(-f3[f3["game_id"] == row["game_id"]].iloc[0]["mkt_logit"])), 0.6)

    def test_closing_line_never_reaches_eligible_models(self):
        keys = eval_week_keys(self.f, [2105])[:4]
        f2 = self.f.copy()
        f2["close_spread"] = -f2["close_spread"] * 3
        elig = [m for m in base_candidates() if m.thursday_eligible and m.kind != "market"]
        a = walk_forward(self.f, elig, keys, self.s)
        b = walk_forward(f2, elig, keys, self.s)
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
        self.assertFalse(any(m.thursday_eligible for m in base_candidates() if m.name in ("market_close", "deadeye_line_proxy")))

    def test_missing_data_flagged(self):
        first = self.f[self.f["season"] == 2101].iloc[0]
        self.assertIn("rest_unknown", first["missing_flags"])
        self.assertIn("no_team_history", first["missing_flags"])


# ---------------------------------------------------------------- holdout, reproducibility, ensembles
class EvaluationTests(Tmp):
    def setUp(self):
        super().setUp()
        self.s = settings(self.tmp)
        self.f = build_features(GAMES, self.s)

    def test_holdout_refused_unless_unlocked(self):
        keys = eval_week_keys(self.f, [2107])[:2]
        with self.assertRaises(HoldoutLocked):
            walk_forward(self.f, [EloModel()], keys, self.s)
        walk_forward(self.f, [EloModel()], keys, self.s, unlock_reason="final evaluation, rules frozen")
        self.assertEqual(HoldoutGuard(self.s).viewings(), 1)

    def test_reproducible(self):
        keys = eval_week_keys(self.f, [2104])[:5]
        a = walk_forward(self.f, base_candidates()[:5], keys, self.s)
        b = walk_forward(build_features(GAMES, self.s), base_candidates()[:5], keys, self.s)
        pd.testing.assert_frame_equal(a, b)
        reg = Registry(self.tmp)
        m = Logistic().fit(training_rows(self.f, self.f["cutoff_utc"].max()))
        self.assertEqual(reg.save_artifact("logistic", m.config(), m.state(), "c", "d"),
                         reg.save_artifact("logistic", m.config(), m.state(), "c", "d"))

    def test_ensemble_uses_only_out_of_fold_past(self):
        keys = eval_week_keys(self.f, [2104, 2105])
        base = [m for m in base_candidates() if m.name in ("elo", "bayes_strength", "logistic", "situational")]
        scored = attach_outcomes(walk_forward(self.f, base, keys, self.s), self.f)
        e1, _ = ensemble_walk_forward(scored, (2107,))
        # flip outcomes of the last 5 weeks: ensemble predictions before them must not move
        late_keys = set(keys[-5:])
        s2 = scored.copy()
        m = s2["week_key"].isin(late_keys) & s2["home_win"].isin([0.0, 1.0])
        s2.loc[m, "home_win"] = 1 - s2.loc[m, "home_win"]
        e2, _ = ensemble_walk_forward(s2, (2107,))
        early = ~e1["week_key"].isin(late_keys)
        pd.testing.assert_frame_equal(e1[early].reset_index(drop=True), e2[~e2["week_key"].isin(late_keys)].reset_index(drop=True))

    def test_ensemble_never_trains_on_holdout(self):
        keys = eval_week_keys(self.f, [2105])
        base = [m for m in base_candidates() if m.name in ("elo", "bayes_strength", "logistic", "situational")]
        scored = attach_outcomes(walk_forward(self.f, base, keys, self.s), self.f)
        _, w_all = ensemble_walk_forward(scored, ())
        _, w_hold = ensemble_walk_forward(scored, (2105,))
        self.assertEqual(w_hold["ens_stack_football"]["oof_games"], 0)
        self.assertGreater(w_all["ens_stack_football"]["oof_games"], 0)


# ---------------------------------------------------------------- selection and fallback
class SelectionTests(unittest.TestCase):
    def _scored(self, p_good_noise):
        rng = np.random.default_rng(3)
        n_weeks, per = 40, 15
        rows = []
        for w in range(n_weeks):
            for i in range(per):
                true = rng.uniform(0.2, 0.8)
                y = float(rng.uniform() < true)
                gid = f"g{w}_{i}"
                base = {"game_id": gid, "week_key": (2100, "REG", w), "season": 2100, "home_win": y,
                        "margin": 3.0, "close_spread": 3.0, "exp_margin": np.nan}
                rows.append({**base, "model": "elo", "p_home": 0.5 + (true - 0.5) * 0.3})
                rows.append({**base, "model": "good", "p_home": float(np.clip(true + rng.normal(0, p_good_noise), 0.02, 0.98))})
                rows.append({**base, "model": "noise", "p_home": 0.5 + (true - 0.5) * 0.3 + rng.normal(0, 0.01)})
        return pd.DataFrame(rows)

    META = {"elo": {"thursday_eligible": True}, "good": {"thursday_eligible": True},
            "noise": {"thursday_eligible": True}}

    def test_promote_retain_fallback(self):
        sc = self._scored(0.02)
        d = decide(sc, self.META, None, "elo", SMALL, 1)
        self.assertEqual((d["action"], d["model"]), ("promote", "good"))
        d2 = decide(sc[sc["model"] != "good"], {k: v for k, v in self.META.items() if k != "good"}, None, "elo", SMALL, 1)
        self.assertEqual((d2["action"], d2["model"]), ("fallback", "elo"))
        d3 = decide(sc[sc["model"] != "good"], {k: v for k, v in self.META.items() if k != "good"}, "noise", "elo", SMALL, 1)
        self.assertEqual((d3["action"], d3["model"]), ("retain", "noise"))

    def test_small_sample_never_promotes(self):
        sc = self._scored(0.02)
        tiny = sc[sc["week_key"].apply(lambda k: k[2] < 3)]
        d = decide(tiny, self.META, None, "elo", SMALL, 1)
        self.assertEqual(d["action"], "fallback")

    def test_ineligible_never_promotes(self):
        sc = self._scored(0.02)
        meta = {**self.META, "good": {"thursday_eligible": False}}
        self.assertNotEqual(decide(sc, meta, None, "elo", SMALL, 1)["model"], "good")


# ---------------------------------------------------------------- ACQL rules
class AcqlRuleTests(unittest.TestCase):
    def test_pool_line_threshold(self):
        self.assertIsNone(acql_rules.pool_line_for(6.0))
        self.assertEqual(acql_rules.pool_line_for(6.5), 7.0)
        self.assertEqual(acql_rules.pool_line_for(-7.0), 8.0)

    def test_credited_side(self):
        self.assertEqual(acql_rules.credited_side(3, 3.0), "home")
        self.assertEqual(acql_rules.credited_side(0, 3.0), None)
        self.assertEqual(acql_rules.credited_side(7, 6.5), "home")      # line 7, win by exactly 7 counts
        self.assertEqual(acql_rules.credited_side(6, 6.5), "away")
        self.assertEqual(acql_rules.credited_side(-8, -7.0), "away")    # away fav, line 8
        self.assertEqual(acql_rules.credited_side(-7, -7.0), "home")

    def test_pick_probability_respects_line(self):
        self.assertAlmostEqual(acql_rules.credited_home_prob(0.6, 3.0), 0.6)
        self.assertLess(acql_rules.credited_home_prob(0.75, 7.0), 0.75)

    def test_one_point_per_correct_pick(self):
        sc = pd.DataFrame({"model": ["m", "m"], "p_home": [0.7, 0.4], "close_spread": [3.0, 3.0],
                           "margin": [3.0, 3.0], "week_key": [(1, "REG", 1)] * 2})
        pts = acql_rules.pool_points(sc)
        self.assertEqual(pts["points"].tolist(), [1.0, 0.0])


# ---------------------------------------------------------------- journal
def _forecast(gid="g1", p=0.6, created="2026-10-21T12:00:00+00:00", **kw):
    f = {"season": 2026, "week": 7, "game_id": gid, "home": "AAA", "away": "BBB",
         "kickoff_utc": "2026-10-25T17:00:00+00:00", "created_at": created, "cutoff_utc": "2026-10-22T22:00:00+00:00",
         "model_name": "elo", "model_version": "elo@abc", "training_cutoff": "2026-10-22T22:00:00+00:00",
         "feature_cutoff": "2026-10-22T22:00:00+00:00", "market_ts": None, "p_home": p, "p_away": 1 - p,
         "exp_margin": float("nan"), "exp_total": float("nan"), "provenance_json": "{}", "missing_flags_json": "[]",
         "selection_decision": "fallback", "pick": "AAA", "p_pick_credited": p, "pool_line": None}
    f.update(kw)
    return f


HEADER = {"model_name": "elo", "model_version": "elo@abc", "selection": {}, "market_snapshot": {}}
DEADLINE = datetime(2026, 10, 22, 22, tzinfo=UTC)


SIM = datetime(2026, 10, 21, 13, tzinfo=UTC)


class JournalTests(Tmp):
    """Fixed 2026 dates, so these use replay mode (simulated clock)."""

    def draft(self, j, fc, **kw):
        return j.save_draft(2026, 7, "REG", DEADLINE, HEADER, fc, mode="replay", now=SIM, **kw)

    def test_lock_is_immutable(self):
        j = Journal(self.tmp / "j.sqlite")
        pid = self.draft(j, [_forecast()])
        out = j.lock(pid, ["g1"], SIM)
        self.assertTrue(out["in_time"])
        self.assertIsNone(out["on_time"])          # replays are never on-time live forecasts
        self.assertTrue(j.check_integrity(pid))
        for sql in ("UPDATE forecasts SET p_home=0.9", "DELETE FROM forecasts", "UPDATE packages SET model_name='x'",
                    "DELETE FROM packages"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                j.conn.execute(sql)
        with self.assertRaises(LockError):
            self.draft(j, [_forecast(p=0.9)])

    def test_draft_replaced_not_duplicated(self):
        j = Journal(self.tmp / "j.sqlite")
        self.draft(j, [_forecast()])
        pid = self.draft(j, [_forecast(p=0.55)])
        self.assertEqual(len(j.forecasts(pid)), 1)
        self.assertEqual(len(j.packages()), 1)

    def test_verification_rejects_bad_packages(self):
        j = Journal(self.tmp / "j.sqlite")
        cases = {
            "missing": ([_forecast()], ["g1", "g2"]),
            "probability": ([_forecast(p=1.0)], ["g1"]),
            "feature cutoff": ([_forecast(feature_cutoff="2026-10-23T00:00:00+00:00")], ["g1"]),
            "market": ([_forecast(market_ts="2026-10-23T00:00:00+00:00")], ["g1"]),
            "after kickoff": ([_forecast(created="2026-10-26T00:00:00+00:00")], ["g1"]),
            "version": ([_forecast(model_version="elo")], ["g1"]),
        }
        for name, (fc, slate) in cases.items():
            pid = self.draft(j, fc)
            with self.assertRaises(LockError, msg=name):
                j.lock(pid, slate, SIM)

    def test_live_late_lock_labelled_not_backdated(self):
        j = Journal(self.tmp / "j.sqlite")
        from operation_sunday.tz import iso, utc_now
        now = utc_now()
        deadline = now - timedelta(hours=1)
        f = _forecast(created=iso(now), kickoff_utc=iso(now + timedelta(days=3)), cutoff_utc=iso(deadline),
                      training_cutoff=iso(deadline), feature_cutoff=iso(deadline))
        pid = j.save_draft(2026, 7, "REG", deadline, HEADER, [f])
        with self.assertRaises(LockError):          # a live lock cannot claim another time
            j.lock(pid, ["g1"], deadline - timedelta(hours=2))
        out = j.lock(pid, ["g1"])
        self.assertFalse(out["on_time"])
        self.assertGreaterEqual(j.package(2026, 7)["locked_at"], iso(now))
        self.assertTrue(any(a["level"] == "late" for a in j.alerts()))
        with self.assertRaises(LockError):          # nor can a live draft be backdated
            j.save_draft(2026, 8, "REG", deadline, HEADER, [f], now=deadline - timedelta(days=1))

    def test_revision_preserves_original(self):
        j = Journal(self.tmp / "j.sqlite")
        pid = self.draft(j, [_forecast()])
        j.lock(pid, ["g1"], SIM)
        with self.assertRaises(LockError):
            j.create_revision(2026, 7, "REG", " ", HEADER, [_forecast(p=0.7)], ["g1"], SIM)
        out = j.create_revision(2026, 7, "REG", "feed published wrong kickoff; rerun", HEADER, [_forecast(p=0.7)],
                                ["g1"], SIM)
        self.assertEqual(out["revision"], 1)
        self.assertEqual(j.official(2026, 7)[1][0]["p_home"], 0.6)
        self.assertEqual(j.package(2026, 7, revision=1)["supersedes"], pid)

    def test_results_insert_only(self):
        j = Journal(self.tmp / "j.sqlite")
        self.assertTrue(j.record_result("g1", 2026, 7, 20, 17))
        self.assertFalse(j.record_result("g1", 2026, 7, 20, 17))
        self.assertFalse(j.record_result("g1", 2026, 7, 21, 17))
        self.assertEqual(j.conn.execute("SELECT COUNT(*) FROM result_corrections").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            j.conn.execute("UPDATE results SET home_score=0")

    def test_hash_detects_tampering(self):
        f = _forecast()
        h = forecast_hash(f)
        self.assertNotEqual(h, forecast_hash({**f, "p_home": 0.61}))


# ---------------------------------------------------------------- registry
class RegistryTests(Tmp):
    def test_promote_and_rollback(self):
        r = Registry(self.tmp)
        r.promote("elo", "e1", "first")
        r.promote("logistic", "e2", "better")
        self.assertEqual(r.approved()["model"], "logistic")
        r.rollback("regression found")
        self.assertEqual(r.approved()["model"], "elo")
        r.rollback("again")
        self.assertIsNone(r.approved())
        self.assertEqual(len(r.history()), 4)


# ---------------------------------------------------------------- the weekly job
class PipelineTests(Tmp):
    NOW = datetime(2008, 10, 1, tzinfo=UTC)   # synthetic season 2108 is calendar 2008

    def test_weekly_run_locks_and_recovers(self):
        s = settings(self.tmp)
        ds = dataset(loaded_at=self.NOW)
        with self.assertRaises(RuntimeError):
            run_week(s, now=self.NOW, dataset=ds, fail_stage="train", write_report=False)
        res = run_week(s, now=self.NOW, dataset=ds)
        self.assertEqual(res.status, "locked")
        self.assertTrue(res.lock["in_time"])
        self.assertEqual(res.lock["mode"], "replay")
        j = Journal(s.state_path / "journal.sqlite")
        self.assertEqual(len(j.packages()), 1)
        pkg, fc = j.official(res.season, res.week)
        self.assertEqual(len(fc), len({f["game_id"] for f in fc}))
        self.assertTrue(all(abs(f["p_home"] + f["p_away"] - 1) < 1e-12 for f in fc))
        self.assertTrue(j.check_integrity(pkg["package_id"]))
        statuses = {r["status"] for r in j.conn.execute("SELECT status FROM runs")}
        self.assertIn("failed", statuses)
        self.assertTrue(Path(res.report_path).exists())
        # a second run after the lock never changes the package
        res2 = run_week(s, now=self.NOW + timedelta(hours=1), dataset=ds)
        self.assertEqual(res2.status, "already_locked")
        self.assertEqual(j.official(res.season, res.week)[0]["content_hash"], pkg["content_hash"])
        self.assertTrue(Registry(s.state_path).experiments())

    def test_late_run_alerts(self):
        s = settings(self.tmp)
        ds = dataset(loaded_at=self.NOW)
        f = build_features(ds.games, s)
        wk = f[(f["season"] == 2108)].sort_values("cutoff_utc")
        key = wk["week_key"].iloc[0]
        lock = wk[wk["week_key"] == key]["cutoff_utc"].iloc[0].to_pydatetime()
        late_now = lock + timedelta(hours=3)    # after the Thursday 20:15 game kicked off
        res = run_week(s, season=2108, week=key[2], now=late_now, dataset=ds, write_report=False)
        self.assertFalse(res.lock["in_time"])
        self.assertTrue(any("LATE" in a for a in res.alerts))
        self.assertTrue(any("already kicked off" in a for a in res.alerts))

    def test_stale_data_and_ingest_failure(self):
        s = settings(self.tmp, games_csv_url="http://127.0.0.1:9/none.csv")
        old = dataset(loaded_at=self.NOW - timedelta(days=5))
        res = run_week(s, now=self.NOW, dataset=old, write_report=False)
        self.assertTrue(any("STALE" in w for w in res.warnings))
        s2 = settings(self.tmp / "b", games_csv_url="http://127.0.0.1:9/none.csv")
        with self.assertRaises(RuntimeError):
            run_week(s2, now=self.NOW, fetch=True, write_report=False)

    def test_model_failure_falls_back_to_baseline(self):
        s = settings(self.tmp)
        Registry(s.state_path).promote("no_such_model", "e0", "bad entry")
        import operation_sunday.selection as sel
        orig = sel.decide

        def forced(*a, **k):
            d = orig(*a, **k)
            d.update({"action": "retain", "model": "no_such_model"})
            return d
        import operation_sunday.pipeline as pl
        pl.decide = forced
        try:
            res = run_week(s, now=self.NOW, dataset=dataset(loaded_at=self.NOW), write_report=False)
        finally:
            pl.decide = orig
        pkg = Journal(s.state_path / "journal.sqlite").official(res.season, res.week)[0]
        self.assertEqual(pkg["model_name"], "elo")
        self.assertIn("baseline", pkg["fallback"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
