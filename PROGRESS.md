# PROGRESS — historical dataset for Deadeye's walk-forward backtest

**Goal.** Build a reproducible as-of-cutoff dataset with these pieces:
- one prediction record per game per cutoff;
- separate tables for timestamped odds and individual model forecasts;
- leakage tests and a coverage report.

Production (`acql/`) stays unchanged.

**Status: first version built and verified (2026-10-12). Not committed;
waiting on Sam's approval.**

**Decisions**
- Code lives in `lab/history/`, which production never imports. Outputs go
  to `lab/data/` (gitignored).
- Cutoffs are `week_lock` (production's first-kickoff rule) and `kickoff`.
  The pool's real deadline is unknown.
- nflverse lines have no time, so they go only into `*_unverified` fields,
  flagged. `asof.production_forecast` refuses them unless
  `allow_unverified=True`.
- `data/acql.db` is read only through a read-only SQLite URI, never through
  `acql.store`. The extract leaves out settings, the API key and coaches'
  picks.
- nflverse raw data is not committed (no license file). It is pinned by
  commit and sha256 in `lab/history/sources.lock.json`.

**Done**
- Audit: `lab/reports/data-audit.md`.
- Package: `lab/history/` (`schema`, `asof`, `build`, `report`).
- Build: 7,239 games and 14,478 records.
  - All records reproduce.
  - Two builds produce identical data.
  - `data/acql.db` is unchanged.
- Coverage report: `lab/reports/coverage.md`.
- Tests: 23 new in `tests/test_lab_history.py`, wired into
  `tests/run_tests.py`.
  - The full suite runs 62: 2 pre-existing failures, 1 skipped.
  - Planted leakage bugs were caught: 7 failures for the odds bug, 2 for the
    forecasts bug.

**Next**
- Sam to approve committing.
- Get past Prediction Tracker files and timestamped historical odds. Put PT
  CSVs in `lab/data/raw/predictiontracker/` with a `.meta.json`
  (`season`, `week`, `retrieved_at`, `published_at`).
- Then a walk-forward harness that compares the market-only and current
  Deadeye baselines on identical eligible games.

**Open questions for Sam**
- The pool's real pick deadline.
- What `old_rule` in `pool_weeks.json` was.
- How ties are graded.
- Whether the 2023 pick sheets in the store are really 2023. The slates
  match 2023 uniquely, but `pool_weeks.json` mentions only 2025–2026.
