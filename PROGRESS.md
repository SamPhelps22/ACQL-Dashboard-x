# PROGRESS — Deadeye historical dataset and walk-forward backtest

**Goal.** A reproducible as-of-cutoff dataset (phase 1) and walk-forward
backtests on it (phase 2). Production (`acql/`) stays unchanged.

**Status (2026-10-12)**
- Phase 1 was committed as `6ad873f`.
- Phase 2 is built and verified. It is not committed yet, waiting on Sam's
  approval.

**Decisions**
- The lab lives in `lab/`, which production never imports. Outputs go to
  `lab/data/` (gitignored). Cutoffs are `week_lock` and `kickoff`.
- Undated lines (nflverse, typed spreads) go only into `*_unverified`
  fields. The store is read through a read-only URI only.
- "Current Deadeye" in phase 2 means production's own `pricing.price`, with
  the weight production held for that week (now in the dataset as
  `production_weights`).
- The store extract is versioned (`store_extract-v2-…`). Older extracts are
  kept, never overwritten.

**Phase 2 results (`lab/reports/walkforward.md`)**
- **Verified, 2026 weeks 3–5, 45 games.**
  - Market alone and Deadeye were each right 25 times.
  - Log loss, Deadeye minus market: −0.005 (95% range −0.0175 to +0.0076).
    No evidence either way.
- **Curve width, 2010–2025, 4,167 games, undated lines.**
  - Walk-forward log loss difference: −0.0002 (95% range includes 0).
  - 1 pick changed.
  - No case for changing `SPREAD_SD`.
- **Fidelity.** The lab's Deadeye matched production's saved cards on 42 of
  47 picks. All 5 differences are games with a hand-typed spread. Those
  have no timestamp, so the dataset can't use them.

**Next**
- Sam to approve committing phase 2.
- Biggest gap: more verified weeks.
  - Past Prediction Tracker files go in
    `lab/data/raw/predictiontracker/` with a `.meta.json`.
  - Timestamped odds are also needed.
- Possible production change (needs approval): store a time when a spread is
  typed, so typed spreads become verifiable.

**Open questions for Sam**
- The pool's real pick deadline.
- What `old_rule` was.
- How ties are graded.
- Whether the four store pick sheets really are 2023.
