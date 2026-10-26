# Operation Sunday baseline evaluation

**Audit date:** 2026-10-26  
**Purpose:** establish evidence available before adding the agent workflow. This report does not modify Deadeye, forecasts, or promotion state.

## Executive result

The repository already has a substantial research and model-validation stack. Its historical evaluations do not establish a reliable improvement over Deadeye or the market, and the current live, deadline-eligible sample is too small for a dependable claim. A completed historical ensemble study is a useful negative-control example: it looked favorable during development and was worse on its reported holdout. No candidate should be promoted from these baselines.

## Historical model performance

The local historical training report was generated on 2026-10-20. It evaluates chronological walk-forwards and reports week-clustered 95% ranges. The 2026-10-26 read-only audit reloaded the current local archives and found 6,865 finished games (1999-2026), 166 computer-model columns, and these line coverages: updated 6,857, opening 6,129, midweek 3,448, closing 6,865. These archive counts are not equivalent to timestamped Thursday forecasts.

| Comparison | Games | Market accuracy | Deadeye accuracy | Deadeye log-loss edge over market (95% range) | Reading |
|---|---:|---:|---:|---:|---|
| Updated line, walk-forward | 6,128 | 58.8% | 58.6% | -0.0004 (-0.0014 to +0.0005) | Not distinguishable |
| Opening line, walk-forward | 5,353 | 56.5% | 56.7% | +0.0007 (-0.0005 to +0.0018) | Not distinguishable |
| Midweek line, walk-forward | 2,678 | 59.1% | 58.9% | -0.0008 (-0.0019 to +0.0004) | Not distinguishable |
| Updated-line seasons held out in that report (2024-2026) | 591 | 63.8% | 63.5% | +0.0018 (-0.0005 to +0.0044) | Not distinguishable |

These metrics and the convention that positive log-loss edge favors Deadeye are copied from `data/training/latest/report.md` (local, ignored output). That report also says none of the tested model blends earned a switch. Its source datasets are local files under ignored `data/tracker/`, `data/nflverse/`, and `data/training/`; a clone without those files cannot reproduce these numbers until the data are explicitly obtained and versioned.

### Completed research-to-validation example

The archived meta-learner combined market, Deadeye, Elo, and a scoring model. Its development point estimate favored it by +0.0021 log-loss points/game, but its interval included zero. The reported held-out result was -0.0043 (-0.0077 to -0.0009), worse than Deadeye. The candidate is therefore rejected, not selected on its development rank.

The example is deliberately qualified: it is a retrospective strategy-lab run, the 2023-2026 seasons had prior exposure under the older lab protocol, the line is midweek rather than the exact Thursday cutoff, and historical feature publication timestamps are incomplete. It demonstrates a completed negative holdout decision, not prospective deadline validation. The record and reviewer checks are in [the sample experiment](experiments/meta-learner-midweek-holdout-20261023/record.json).

## Current production-record sample

The local saved-card record (`data/training/record/latest.json`) contains 29 ACQL game records over three weeks: Deadeye was right on 16/29 with log loss 0.6664 and the market on 17/29 with log loss 0.6548. The paired estimate has only three weeks; the existing evaluator leaves its uncertainty interval unset below five weeks. This is descriptive only. The probability track has 15 games in two weeks and is likewise too small. The separate 2026-10-26 Lab note reports 14 eligible Deadeye forecasts for its calibration analysis. No strategy-lab prospective locked week had yet been scored in the current two-track report.

These counts are not a sound estimate of season-long superiority or actual pool payout. Do not combine them with the historical archive rows, after-deadline saved cards, or simulated pool outcomes.

## Pool and scoring baseline

- A normal ACQL game is one credited pick; for a lined game, the pool's posted line determines which side is credited. ACQL weekly money and side pools are additional, separate outcomes.
- `acql.model.backtest` replays historical pool strategies under documented assumptions, including a proxy line and 34 simulated coaches. It is a simulation, not the exact historical commissioner roster, real payout record, or proof of an actual-pool gain.
- The strategy lab evaluates ACQL credited picks separately from straight-up probability loss. Real weekly pool performance should be reported only when the actual slate, picks, rules, and payout records are available on common weeks.

## Data and validation limitations

1. The Prediction Tracker archive is broad but the historical model forecasts do not all have publication timestamps. Midweek and closing archive fields must not be described as exact Thursday-locked information.
2. Current deadline snapshots and the forecast log enforce timestamp eligibility, but the usable prospective sample remains small. An absent timestamp is ineligible/unknown, not implicitly on time.
3. nflverse includes historical games, team-week stats, injuries, and Next Gen Stats files locally; the local Operation Sunday note says current team stats stop at 2026 week 5 and no archived 2026 injury/weather data is stored per forecast. Do not invent a point-in-time history.
4. The historical audit surfaced excluded anomalies (duplicate games, score/line disagreements, and malformed/out-of-range rows). The training data loader reports and excludes them; experiment records must preserve the warnings and exact fingerprint.
5. The existing suite covers the evaluator, walk-forward leakage tests, baselines, calibration, lock-chain tampering, timestamp eligibility, and small-sample gates. Missing evidence is mainly prospective sample size and exact historical publication-time coverage—not a reason to replace those tests.

## Reproduction and validation evidence

Commands run on the audit date using the repository's existing `.venv\Scripts\python.exe`:

```powershell
.venv\Scripts\python.exe -m acql.training audit --no-books
.venv\Scripts\python.exe tests\test_research_lab.py
.venv\Scripts\python.exe tests\test_strategy_lab.py
.venv\Scripts\python.exe tests\test_model_lab.py
```

The audit reloaded the local history as 6,865 games. The research-lab tests passed (14); strategy-lab tests passed (26); forecast/model-lab tests passed (38). The research-lab test intentionally emits its tested bad-row diagnostic. The model-lab run emitted a pre-existing `ResourceWarning` in a test helper for an unclosed test CSV; all tests passed. These are baseline results, before adding `test_agent_record.py`.

The initial worktree had user edits in `acql/lab/server.py`, `acql/ui/app.py`, `acql/ui/pool_page/000-page-top.html`, `acql/ui/pool_page/290-game-day-strip-the-slate.js`, and `tests/test_lab.py`. They were inspected and not overwritten. During the audit they appeared in commit `53ac938`; this task did not create that commit. A separate edit to `acql/ui/redzone.py` appeared by the final worktree check and was left untouched.
