# PROGRESS — Deadeye historical dataset and backtests

**Goal.** A reproducible as-of-cutoff dataset (phase 1), walk-forward
backtests on it (phase 2), and the nudge tested over many seasons (phase 3).
Production (`acql/`) stays unchanged.

**Status (2026-10-12)**
- Phase 1 was committed as `6ad873f`, phase 2 as `240c3b6`.
- Phase 3 is built and verified. It is not committed yet, waiting on Sam's
  approval.

**Decisions**
- The lab lives in `lab/`, which production never imports. Outputs go to
  `lab/data/` (gitignored). Cutoffs are `week_lock` and `kickoff`.
- Undated lines (nflverse, typed spreads) go only into `*_unverified` fields.
  The store is read through a read-only URI only.
- The Prediction Tracker season archives (`nfl10.csv` … `nfl26.csv`, uploaded
  by Sam) are kept byte for byte in `lab/data/raw/predictiontracker/seasons/`,
  read-only, each with a `.meta.json`.
  - They have no `available_at`, so they never fill a record.
  - Their lines carry `archive_*` timings, which records leave out entirely.
  - They are not committed, because the site states no license.
- Phase 3 uses the archive's **midweek** line. On 2026 week 3 it matched the
  line production priced from on 14 of 16 games; the archive's `line` column
  is a later update. 2010–2012 have no midweek column, so their latest line
  is used.
- The proxy pool line is set against the opening line, as
  `pricing.opening_spread` says the commissioner does.

**Phase 3 results (`lab/reports/archive_backtest.md`)**
- **Coverage.** 4,223 games, 2010 through 2026 week 3; all matched the
  schedule. The one miss is the cancelled 2022 BUF–CIN game.
- **Market alone vs Deadeye, 4,215 graded games.**
  - Market alone 2,462 right, Deadeye fitted 2,463, Deadeye at 0.33 2,460.
  - Log loss, Deadeye minus market: +0.0008 (−0.0005 to +0.0021), so no
    evidence either way, with the point estimate slightly worse.
  - Margin error: no difference.
  - Against nflverse's closing line, Deadeye's side covered 50.2% (48.8% to
    51.6%).
- **In hindsight,** no fixed weight from 0 to 0.6 beats the market by
  anything that matters.
- **Fidelity.** On 2026 week 3, Deadeye from the archive was within 0.06
  points on average of Deadeye from the weekly file production imported.
- **Found in passing.** Production counts the `linemidweek` market column as a
  model. Not changed, since that needs approval.

**Next (Sam to decide)**
- Approve committing phase 3.
- The nudge shows no measurable value over the market across 16 seasons.
  Options:
  - leave production as is;
  - lower the starting weight, which needs approval and a rollback note;
  - test challengers in the lab (single models, a learned blend) against the
    same games.
- More verified weeks would still help: typed-spread timestamps (a production
  change), or timestamped odds.

**Open questions for Sam**
- The pool's real pick deadline.
- What `old_rule` was.
- How ties are graded.
- Whether the four store pick sheets really are 2023.
