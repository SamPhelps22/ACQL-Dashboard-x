# PROGRESS — Deadeye historical dataset and backtests

**Goal.** A reproducible as-of-cutoff dataset (phase 1), walk-forward
backtests on it (phase 2), and the nudge tested over many seasons (phase 3).
Production (`acql/`) stays unchanged.

**Status (2026-10-12)**
- Phase 1 was committed as `6ad873f`, phase 2 as `240c3b6`, and phase 3 as
  `620b46c`.
- The challengers (`lab/challengers.py`) are built and verified. They are not
  committed yet, waiting on Sam's approval.

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

**Challengers (`lab/reports/challengers.md`)**
- Both are fitted on earlier seasons only and tested on 2013–2026, using the
  same 3,447 graded games as the baselines.
- **Best single model.** A nudge toward the one model that fitted best (mostly
  `linedok`, at a weight of 0.18–0.46).
  - 2,009 right, against 2,026 for the market alone and 2,024 for Deadeye.
  - Log loss +0.0013 vs the market (−0.0004 to +0.0030 by season).
- **Learned blend.** A ridge regression on every model's disagreement with
  the line.
  - The penalty it chose was mostly very large: it shrinks toward the market.
  - 2,002 right; log loss +0.0012 vs the market (−0.0007 to +0.0033).
- Neither beats the market or Deadeye. Against the closing line, both are
  about 50%.
- **Conclusion.** These archives carry no usable signal beyond the midweek
  line, for any of the three ways of using them tried.

**Next (Sam to decide)**
- Approve committing the challengers.
- Options for production:
  - leave it as is (it is no worse than the market);
  - drop to the market alone, or lower the starting weight. That needs
    approval and a rollback note.
- More verified weeks would still help: typed-spread timestamps (a production
  change), or timestamped odds.

**Open questions for Sam**
- The pool's real pick deadline.
- What `old_rule` was.
- How ties are graded.
- Whether the four store pick sheets really are 2023.
