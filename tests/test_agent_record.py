#!/usr/bin/env python3
"""Safety checks for the Operation Sunday agent record and promotion gate."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acql.training import agent_record  # noqa: E402

SAMPLE = ROOT / "docs" / "operation-sunday-agents" / "experiments" / "meta-learner-midweek-holdout-20261023"


def canonical_hash(record: dict) -> str:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def promotion_pair() -> tuple[dict, dict]:
    experiment = json.loads((SAMPLE / "record.json").read_text(encoding="utf-8"))
    validation = json.loads((SAMPLE / "validation.json").read_text(encoding="utf-8"))
    experiment["payload"]["candidate"]["artifact_sha256"] = "a" * 64
    experiment["payload"]["dataset"]["feature_timestamps"] = "verified"
    experiment["payload"]["protocol"]["exact_deadline_data"] = True
    validation["payload"]["status"] = "accepted"
    validation["payload"]["checks"] = {key: True for key in agent_record.CHECKS}
    validation["payload"]["experiment_record_sha256"] = canonical_hash(experiment)
    return experiment, validation


class AgentRecordTests(unittest.TestCase):
    def setUp(self):
        self.experiment = json.loads((SAMPLE / "record.json").read_text(encoding="utf-8"))
        self.validation = json.loads((SAMPLE / "validation.json").read_text(encoding="utf-8"))

    def test_sample_experiment_and_validation_are_well_formed(self):
        self.assertEqual(agent_record.validate_record(self.experiment), [])
        self.assertEqual(agent_record.validate_record(self.validation), [])
        self.assertEqual(self.validation["payload"]["experiment_record_sha256"], canonical_hash(self.experiment))

    def test_workflow_defaults_are_bounded_and_disable_external_fetches(self):
        config = json.loads((ROOT / "docs" / "operation-sunday-agents" / "workflow-config.json")
                            .read_text(encoding="utf-8"))
        budget = config["budgets"]
        self.assertEqual(budget["max_concurrent_experiments"], 1)
        self.assertEqual(budget["max_full_experiments_per_invocation"], 1)
        self.assertGreater(budget["max_minutes_per_experiment"], 0)
        self.assertFalse(config["network"]["external_data_fetch"])
        self.assertFalse(config["network"]["paid_api_requests"])
        self.assertTrue(config["worktree"]["required_for_candidate_code"])

    def test_sample_experiment_is_rejected_and_not_promotable(self):
        blockers = agent_record.promotion_blockers(self.experiment, self.validation)
        self.assertTrue(any("did not accept" in reason for reason in blockers))
        self.assertTrue(any("owner approval is missing" in reason for reason in blockers))
        self.assertTrue(any("prediction cutoff" in reason for reason in blockers))

    def test_independent_validation_must_have_a_distinct_agent_id(self):
        invalid = copy.deepcopy(self.validation)
        invalid["agent_id"] = invalid["payload"]["research_agent_id"]
        self.assertIn("an independent validation record must have a different agent_id",
                      agent_record.validate_record(invalid))

    def test_validation_must_fingerprint_the_exact_experiment(self):
        experiment, validation = promotion_pair()
        validation["payload"]["experiment_record_sha256"] = "b" * 64
        blockers = agent_record.promotion_blockers(experiment, validation, {
            "approved_by": "owner", "approved_at": "2026-10-26", "scope": "production model promotion"
        })
        self.assertTrue(any("does not fingerprint" in reason for reason in blockers))

    def test_research_agent_cannot_self_validate_or_pass_missing_safety_checks(self):
        experiment, validation = promotion_pair()
        validation["agent_id"] = experiment["agent_id"]
        validation["payload"]["experiment_record_sha256"] = canonical_hash(experiment)
        blockers = agent_record.promotion_blockers(experiment, validation, {
            "approved_by": "owner", "approved_at": "2026-10-26", "scope": "production model promotion"
        })
        self.assertTrue(any("not independent" in reason for reason in blockers))
        self.assertFalse(any("owner approval is missing" in reason for reason in blockers))

    def test_every_approval_prerequisite_must_pass_before_review(self):
        experiment, validation = promotion_pair()
        approval = {
            "approved_by": "owner",
            "approved_at": "2026-10-26",
            "scope": "production model promotion",
        }
        self.assertEqual(agent_record.promotion_blockers(experiment, validation, approval), [])

    def test_promotion_check_never_mutates_records(self):
        experiment, validation = promotion_pair()
        before = copy.deepcopy((experiment, validation))
        agent_record.promotion_blockers(experiment, validation)
        self.assertEqual((experiment, validation), before)

    def test_bad_artifact_hash_is_reported(self):
        invalid = copy.deepcopy(self.experiment)
        invalid["payload"]["candidate"]["artifact_sha256"] = "not-a-hash"
        self.assertIn("payload.candidate.artifact_sha256 must be a lowercase SHA-256 or null",
                      agent_record.validate_record(invalid))

    def test_malformed_enum_values_are_reported_without_crashing(self):
        invalid = copy.deepcopy(self.experiment)
        invalid["record_type"] = []
        invalid["payload"]["status"] = []
        self.assertTrue(agent_record.validate_record(invalid))
        self.assertIn("experiment and validation records must be JSON objects",
                      agent_record.promotion_blockers([], self.validation))


if __name__ == "__main__":
    unittest.main(verbosity=2)
