# Operation Sunday

Weekly learning, model selection and the Thursday forecast lock for the ACQL pool. A research and
shadow-production workflow: it never changes Deadeye's pricing, ACQL scoring, the public site or the dashboard.

```bash
python -m operation_sunday calendar --season 2026   # when each week locks
python -m operation_sunday run                      # the weekly job: refreshes the draft, locks within 3 h of the deadline
python tests/test_operation_sunday.py               # tests (no network)
```

* `docs/AUDIT_AND_PLAN.md`: repository audit, plan, data-flow diagram
* `docs/OPERATIONS.md`: scheduling, settings, data requirements, recovery, promotion rules
* `docs/EVIDENCE_REPORT.md`: tests, results, ablations, holdout, limitations
* `docs/SAMPLE_WEEKLY_REPORT_2026_W07.md`: a real weekly report

Current status: no Thursday-eligible model beats the Elo baseline under the predefined rules, so Elo runs as a
disclosed fallback. The closing market is better but is not available on Thursday.

Scheduling: `schedule.ps1` registers "ACQL Operation Sunday" (every 2 h, 9 AM–9 PM). Thursday market
snapshots come from the dashboard's stored line fetches; no extra Odds API requests.
