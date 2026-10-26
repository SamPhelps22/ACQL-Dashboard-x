"""Validate the versioned hand-off records used by the Operation Sunday agents.

This checks record structure and promotion prerequisites only. It never runs an
experiment, changes a forecast, or promotes a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

RECORD_VERSION = 1
RECORD_TYPES = {"experiment", "validation", "analytics"}
EXPERIMENT_STATUSES = {"proposed", "running", "complete", "blocked"}
VALIDATION_STATUSES = {"accepted", "rejected", "inconclusive", "blocked"}
CHECKS = {
    "same_games",
    "same_deadlines",
    "same_scoring_rules",
    "same_baseline_versions",
    "leakage_passed",
    "adequate_sample",
    "feature_timestamps_verified",
    "preregistration_honored",
    "regression_tests_passed",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def _mapping(value: Any, name: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return {}
    return value


def _text(value: Any, name: str, errors: list[str], *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        errors.append(f"{name} must be a non-empty string")


def _date(value: Any, name: str, errors: list[str]) -> None:
    _text(value, name, errors)
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            errors.append(f"{name} must be an ISO date (YYYY-MM-DD)")


def _bool(value: Any, name: str, errors: list[str]) -> None:
    if not isinstance(value, bool):
        errors.append(f"{name} must be true or false")


def _choice(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def validate_record(record: Any) -> list[str]:
    """Return structural or policy errors for an experiment, validation, or analytics record."""
    if not isinstance(record, dict):
        return ["record must be a JSON object"]

    errors: list[str] = []
    if record.get("record_version") != RECORD_VERSION:
        errors.append(f"record_version must be {RECORD_VERSION}")
    record_type = record.get("record_type")
    if not _choice(record_type, RECORD_TYPES):
        errors.append(f"record_type must be one of: {', '.join(sorted(RECORD_TYPES))}")
    experiment_id = record.get("experiment_id")
    if not isinstance(experiment_id, str) or not _ID.fullmatch(experiment_id):
        errors.append("experiment_id must be a 3-80 character kebab-case identifier")
    _date(record.get("recorded_at"), "recorded_at", errors)
    _text(record.get("agent_id"), "agent_id", errors)
    payload = _mapping(record.get("payload"), "payload", errors)

    if record_type == "experiment":
        for key in ("status", "hypothesis", "objective", "decision"):
            _text(payload.get(key), f"payload.{key}", errors)
        if not _choice(payload.get("status"), EXPERIMENT_STATUSES):
            errors.append(f"payload.status must be one of: {', '.join(sorted(EXPERIMENT_STATUSES))}")

        prereg = _mapping(payload.get("preregistration"), "payload.preregistration", errors)
        _date(prereg.get("registered_at"), "payload.preregistration.registered_at", errors)
        for key in ("protocol", "primary_metric", "success_criteria"):
            _text(prereg.get(key), f"payload.preregistration.{key}", errors)

        candidate = _mapping(payload.get("candidate"), "payload.candidate", errors)
        for key in ("name", "source_commit"):
            _text(candidate.get(key), f"payload.candidate.{key}", errors)
        _mapping(candidate.get("parameters"), "payload.candidate.parameters", errors)
        digest = candidate.get("artifact_sha256")
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            errors.append("payload.candidate.artifact_sha256 must be a lowercase SHA-256 or null")

        dataset = _mapping(payload.get("dataset"), "payload.dataset", errors)
        for key in ("name", "version", "fingerprint", "season_range", "feature_timestamps"):
            _text(dataset.get(key), f"payload.dataset.{key}", errors)
        if not _choice(dataset.get("feature_timestamps"), {"verified", "partial", "unavailable"}):
            errors.append("payload.dataset.feature_timestamps must be verified, partial, or unavailable")
        if not isinstance(dataset.get("source_files"), list):
            errors.append("payload.dataset.source_files must be an array")
        elif not all(isinstance(item, str) and item.strip() for item in dataset["source_files"]):
            errors.append("payload.dataset.source_files entries must be non-empty strings")
        availability = dataset.get("feature_availability")
        if not isinstance(availability, list) or not availability:
            errors.append("payload.dataset.feature_availability must be a non-empty array")
        else:
            for index, item in enumerate(availability):
                entry = _mapping(item, f"payload.dataset.feature_availability[{index}]", errors)
                for key in ("feature", "timestamp_source", "notes"):
                    _text(entry.get(key), f"payload.dataset.feature_availability[{index}].{key}", errors)
                _bool(entry.get("cutoff_verified"),
                      f"payload.dataset.feature_availability[{index}].cutoff_verified", errors)

        protocol = _mapping(payload.get("protocol"), "payload.protocol", errors)
        for key in ("version", "code_version", "prediction_cutoff", "scoring_rules_version",
                    "development_period", "validation_period", "uncertainty_method"):
            _text(protocol.get(key), f"payload.protocol.{key}", errors)
        baselines = protocol.get("baselines")
        if not isinstance(baselines, list) or not baselines:
            errors.append("payload.protocol.baselines must be a non-empty array")
        else:
            for index, item in enumerate(baselines):
                baseline = _mapping(item, f"payload.protocol.baselines[{index}]", errors)
                _text(baseline.get("name"), f"payload.protocol.baselines[{index}].name", errors)
                _text(baseline.get("version"), f"payload.protocol.baselines[{index}].version", errors)
        _bool(protocol.get("same_games"), "payload.protocol.same_games", errors)
        _bool(protocol.get("exact_deadline_data"), "payload.protocol.exact_deadline_data", errors)
        seed = protocol.get("random_seed")
        if "random_seed" not in protocol:
            errors.append("payload.protocol.random_seed is required (use null when not applicable)")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            errors.append("payload.protocol.random_seed must be an integer or null")

        execution = _mapping(payload.get("execution"), "payload.execution", errors)
        _text(execution.get("resource_use"), "payload.execution.resource_use", errors)
        elapsed = execution.get("elapsed_seconds")
        if elapsed is not None and (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0):
            errors.append("payload.execution.elapsed_seconds must be a non-negative number or null")
        for key in ("commands", "failures", "tool_usage"):
            values = execution.get(key)
            if not isinstance(values, list) or (key != "failures" and not values):
                errors.append(f"payload.execution.{key} must be an array"
                              + (" with at least one entry" if key != "failures" else ""))
            elif not all(isinstance(item, str) and item.strip() for item in values):
                errors.append(f"payload.execution.{key} entries must be non-empty strings")

        results = _mapping(payload.get("results"), "payload.results", errors)
        metrics = results.get("metrics")
        if not isinstance(metrics, list):
            errors.append("payload.results.metrics must be an array")
        else:
            for index, item in enumerate(metrics):
                metric = _mapping(item, f"payload.results.metrics[{index}]", errors)
                for key in ("name", "unit"):
                    _text(metric.get(key), f"payload.results.metrics[{index}].{key}", errors)
                for key in ("value", "ci_low", "ci_high"):
                    value = metric.get(key)
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                        errors.append(f"payload.results.metrics[{index}].{key} must be a number or null")
                for key in ("games", "weeks"):
                    value = metric.get(key)
                    if key == "weeks" and value is None:
                        continue
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        errors.append(f"payload.results.metrics[{index}].{key} must be a non-negative integer"
                                      + (" or null" if key == "weeks" else ""))
                if metric.get("ci_low") is not None and metric.get("ci_high") is not None:
                    if (isinstance(metric["ci_low"], (int, float))
                            and isinstance(metric["ci_high"], (int, float))
                            and metric["ci_low"] > metric["ci_high"]):
                        errors.append(f"payload.results.metrics[{index}] has ci_low above ci_high")
                if not isinstance(metric.get("seasons"), list) or not all(
                        isinstance(value, int) and not isinstance(value, bool) for value in metric["seasons"]):
                    errors.append(f"payload.results.metrics[{index}].seasons must be an integer array")
                _text(metric.get("notes"), f"payload.results.metrics[{index}].notes", errors, allow_empty=True)
        if not _choice(results.get("leakage_check"), {"passed", "failed", "not_run"}):
            errors.append("payload.results.leakage_check must be passed, failed, or not_run")
        for key in ("subgroups", "notes"):
            values = results.get(key)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                errors.append(f"payload.results.{key} must be an array of strings")

    elif record_type == "validation":
        for key in ("research_agent_id", "status", "independence_basis", "decision"):
            _text(payload.get(key), f"payload.{key}", errors)
        if not _choice(payload.get("status"), VALIDATION_STATUSES):
            errors.append(f"payload.status must be one of: {', '.join(sorted(VALIDATION_STATUSES))}")
        _bool(payload.get("independent"), "payload.independent", errors)
        if payload.get("independent") is True and record.get("agent_id") == payload.get("research_agent_id"):
            errors.append("an independent validation record must have a different agent_id")
        if not isinstance(payload.get("experiment_record_sha256"), str) or not _SHA256.fullmatch(
                payload.get("experiment_record_sha256", "")):
            errors.append("payload.experiment_record_sha256 must be a lowercase SHA-256")
        checks = _mapping(payload.get("checks"), "payload.checks", errors)
        for key in sorted(CHECKS):
            _bool(checks.get(key), f"payload.checks.{key}", errors)
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("payload.evidence must be a non-empty array")
        elif not all(isinstance(item, str) and item.strip() for item in evidence):
            errors.append("payload.evidence entries must be non-empty strings")

    elif record_type == "analytics":
        _text(payload.get("summary"), "payload.summary", errors)
        if not isinstance(payload.get("findings"), list) or not all(
                isinstance(item, str) for item in payload.get("findings", [])):
            errors.append("payload.findings must be an array")
        if not isinstance(payload.get("next_hypotheses"), list) or not all(
                isinstance(item, str) for item in payload.get("next_hypotheses", [])):
            errors.append("payload.next_hypotheses must be an array")

    return errors


def promotion_blockers(experiment: dict, validation: dict, approval: Any = None) -> list[str]:
    """Explain why an experiment is not eligible for owner-reviewed promotion.

    This is a fail-closed checklist, not authorization and not a production
    write. A person must still review and apply any production change.
    """
    if not isinstance(experiment, dict) or not isinstance(validation, dict):
        return ["experiment and validation records must be JSON objects"]
    blockers = []
    exp_errors = validate_record(experiment)
    val_errors = validate_record(validation)
    if exp_errors:
        blockers.append("experiment record is invalid: " + "; ".join(exp_errors))
    if val_errors:
        blockers.append("validation record is invalid: " + "; ".join(val_errors))
    if experiment.get("record_type") != "experiment" or validation.get("record_type") != "validation":
        blockers.append("promotion requires an experiment record and a separate validation record")
        return blockers

    if experiment.get("experiment_id") != validation.get("experiment_id"):
        blockers.append("validation record refers to a different experiment")
    exp = experiment.get("payload") if isinstance(experiment.get("payload"), dict) else {}
    val = validation.get("payload") if isinstance(validation.get("payload"), dict) else {}
    expected_digest = hashlib.sha256(
        json.dumps(experiment, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if val.get("experiment_record_sha256") != expected_digest:
        blockers.append("validation record does not fingerprint this exact experiment record")
    if exp.get("status") != "complete":
        blockers.append("experiment is not complete")
    if val.get("status") != "accepted":
        blockers.append("independent validation did not accept the candidate")
    if val.get("independent") is not True or validation.get("agent_id") == experiment.get("agent_id"):
        blockers.append("validation is not independent of research")

    candidate = exp.get("candidate") if isinstance(exp.get("candidate"), dict) else {}
    if not isinstance(candidate.get("artifact_sha256"), str) or not _SHA256.fullmatch(
            candidate.get("artifact_sha256", "")):
        blockers.append("candidate artifact is not pinned by SHA-256")
    dataset = exp.get("dataset") if isinstance(exp.get("dataset"), dict) else {}
    if dataset.get("feature_timestamps") != "verified":
        blockers.append("feature availability timestamps are not verified")
    protocol = exp.get("protocol") if isinstance(exp.get("protocol"), dict) else {}
    if protocol.get("exact_deadline_data") is not True:
        blockers.append("historical data does not establish the applicable prediction cutoff")
    checks = val.get("checks") if isinstance(val.get("checks"), dict) else {}
    for key in sorted(CHECKS):
        if checks.get(key) is not True:
            blockers.append(f"validation check failed or is missing: {key.replace('_', ' ')}")

    if not isinstance(approval, dict):
        blockers.append("explicit owner approval is missing")
    else:
        _text(approval.get("approved_by"), "approval.approved_by", blockers)
        _text(approval.get("approved_at"), "approval.approved_at", blockers)
        if approval.get("scope") != "production model promotion":
            blockers.append("approval scope must be 'production model promotion'")
    return blockers


def _load(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON record {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON record {path} must contain an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate", help="validate one versioned agent record")
    check.add_argument("record")
    gate = commands.add_parser("promotion-check", help="list fail-closed promotion prerequisites")
    gate.add_argument("experiment")
    gate.add_argument("validation")
    gate.add_argument("--approval", help="owner-signed approval JSON; this check never promotes")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_record(_load(args.record))
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print(f"valid record: {args.record}")
            return 0
        approval = _load(args.approval) if args.approval else None
        blockers = promotion_blockers(_load(args.experiment), _load(args.validation), approval)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if blockers:
        print("Promotion blocked (no production changes were made):")
        for blocker in blockers:
            print(f"- {blocker}")
        return 2
    print("Prerequisites recorded; owner review and a separate production change are still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
