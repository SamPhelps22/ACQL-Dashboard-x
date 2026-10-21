# Operation Sunday — evidence report (release 1.0, 2026-10-21)

**Bottom line.** The system is built and tested end to end, and it locked a live 2026 week 7 package on time.
On reproducible out-of-sample evidence, **no Thursday-eligible football model or ensemble beats the simple
Elo baseline** by a margin the predefined rules accept. So the system currently runs on the **designated
baseline (Elo) as a disclosed fallback**. The closing market is clearly better (about −0.02 log loss), but it
is not available at the Thursday cutoff, so it stays a benchmark. **No model improvement is claimed.**

All numbers below come from `python -m operation_sunday backtest`, `ablation` and `run`, using nflverse
`games.csv` fetched 2026-10-21. The CSVs are in this folder.

## 1. Tests run

| Suite | Result |
|---|---|
| `tests/test_operation_sunday.py` (new, 38 tests) | **OK**. Covers scheduling/DST, early kickoffs, postponements, cutoff enforcement, immutability (DB triggers), late-lock labelling, no backdating, revisions, insert-only results, hash tampering, training eligibility, future-result perturbation, same-week leakage, post-cutoff market, closing-line isolation, duplicates, bad kickoffs, missing data, probability validity, reproducibility, OOF-only ensembles, ensemble/holdout separation, holdout guard, promote/retain/fallback, small-sample refusal, ACQL scoring, ingest failure, stale data, interrupted-run recovery without duplicates, model-failure fallback, late runs |
| `tests/run_tests.py` | 230 tests: 3 errors, 7 skipped. **Pre-existing and unrelated**: `ImportError: libEGL.so.1` (Qt system library missing in this sandbox). Identical result with the new code stashed. |
| `tests/test_gameday_live.py` | 29 tests: 1 error, same `libEGL.so.1` cause. Pre-existing and unrelated. |
| `test_training`, `test_pfm`, `test_chaos`, `test_model_lab`, `test_pushalerts`, `test_sunday`, `test_calibration` | all OK |
| `nfl_pickem` pytest suite | not run (it needs DuckDB/pytest/scikit-learn, not in this environment); no file in `nfl_pickem/` was changed |

## 2. Out-of-sample results, development seasons 2012–2024
Walk-forward with a weekly refit; each week is predicted at its own Thursday lock. Regular season only;
3,379 matched games (`evidence_dev_2012_2024_summary.csv`).

| Model | Thursday-eligible | Log loss | Brier | Accuracy | ECE |
|---|---|---|---|---|---|
| home_rate (simplest baseline) | yes | 0.6874 | 0.2471 | 0.555 | 0.012 |
| **elo** (designated baseline) | yes | 0.6308 | 0.2204 | 0.645 | 0.018 |
| bayes_strength | yes | **0.6297** | **0.2198** | 0.647 | 0.019 |
| logistic | yes | 0.6312 | 0.2205 | 0.643 | 0.021 |
| situational | yes | 0.6889 | 0.2478 | 0.555 | 0.011 |
| ens_equal_football | yes | 0.6327 | 0.2212 | 0.641 | 0.042 |
| ens_stack_football | yes | 0.6305 | 0.2202 | 0.645 | 0.029 |
| ens_perf_football | yes | 0.6307 | 0.2203 | 0.646 | 0.030 |
| market_close | **no** (closing line) | 0.6108 | 0.2114 | 0.666 | 0.031 |
| deadeye_line_proxy | **no** (closing line, *reconstructed*) | 0.6086 | 0.2106 | 0.666 | 0.023 |

Paired against Elo with a week-block bootstrap. This is the selection window of the live week 7 run:
dev seasons plus 2026 weeks 1–6, 3,471 games, 231 weeks. Negative means the candidate is better.

| Candidate | Δ log loss | 95% CI | Verdict |
|---|---|---|---|
| bayes_strength | −0.0010 | [−0.0051, +0.0028] | indistinguishable |
| logistic | +0.0003 | [−0.0033, +0.0039] | indistinguishable |
| ens_stack_football | −0.0003 | [−0.0033, +0.0025] | indistinguishable |
| ens_perf_football | −0.0001 | [−0.0035, +0.0029] | indistinguishable |
| ens_equal_football | +0.0018 | [−0.0023, +0.0055] | worse; miscalibrated (slope 1.34) |
| market_close (benchmark) | −0.0193 | [−0.0259, −0.0130] | better, but not available on Thursday |
| deadeye_line_proxy (benchmark) | −0.0213 | [−0.0288, −0.0143] | better, but not available on Thursday |

**ACQL points (same slate, same rules, pool lines rebuilt from the closing spread):** realised points per week:
market_close 8.64, deadeye_line_proxy 8.67, ens_perf 8.41, elo 8.40, logistic 8.36, bayes_strength 8.36,
home_rate 7.75. At about 15 games a week, the football models are about 0.25 points per week behind the
closing-line benchmarks.

## 3. Final holdout, 2025 (one viewing, logged)
Rules were frozen first (criteria digest `89345cd9065a44f0`). The access is recorded in
`holdout_access.jsonl`. 271 games (`evidence_holdout_2025_summary.csv`).

| Model | Log loss | Accuracy |
|---|---|---|
| elo | **0.6393** | 0.642 |
| bayes_strength | 0.6418 | 0.627 |
| logistic | 0.6434 | 0.624 |
| ensembles (all three)\* | 0.6415 | 0.627 |
| market_close (benchmark) | 0.6105 | 0.653 |

\*The holdout run evaluated 2025 on its own. With no earlier out-of-fold predictions in that run, and
holdout predictions never used for weights, all three ensembles fell back to equal weights. This is a
limitation of this single viewing, not a tuned result. The holdout agrees with development: Elo is not
beaten.

## 4. Feature-family ablations (matched games, 2012–2024; `evidence_ablation_2012_2024.csv`)
"Market" arms use the **closing** line, so they are benchmark-only.

| Family | Football w/o → with: Δ log loss [95% CI] | Vs market alone (benchmark) | Decision |
|---|---|---|---|
| team strength | **−0.0577 [−0.0689, −0.0471]**, +139 ACQL pts total | −0.0003 [−0.0020, +0.0014] | keep. It is the whole football signal, but adds nothing beyond the closing line. |
| rest | +0.0001 [−0.0016, +0.0017] | +0.0008 | no repeatable value |
| travel | +0.0002 [−0.0002, +0.0006] | +0.0004 [+0.0001, +0.0007] (slightly harmful) | no value |
| situational | +0.0018 [−0.0002, +0.0037] | +0.0017 | slightly harmful (overfitting) |
| market (closing) | −0.0192 [−0.0247, −0.0139] | — | large, but not Thursday-available |
| qb, injuries, weather, tactical, drive_sim | **not testable**: no point-in-time data (see §6) | | excluded |

The stacking and performance-weighted ensembles shrink toward equal weights, so they gain nothing from the
weak families. The equal-weight ensemble is hurt by the near-constant `situational` component, which is
what the "ensemble must earn its complexity" rule is meant to catch.

## 5. Live run (shadow)
`run` on 2026-10-21 for 2026 week 7: lock at 2026-10-22 22:00 UTC (Thursday 18:00 EDT). Package
`2026-REG-07-r0` was locked on time with content hash `553456ac…`, model `elo@5a85bf3d33df`, decision
**fallback**. There was no market snapshot, so every pick is straight-up and flagged. Report:
`SAMPLE_WEEKLY_REPORT_2026_W07.md`. This ran in a scratch state folder; nothing was published.

## 6. Limitations and incomplete work
1. **No Thursday market archive.** The best signal available, the market, can't be validated at the
   Thursday cutoff historically. Snapshots passed with `--market` are stored in each locked package and
   re-used, so `market_snapshot` and `ens_market_informed` gain evidence week by week. Until they reach the
   promotion sample (500 games, 30 weeks), they can't be promoted. **Recommendation:** supply a Thursday
   snapshot every week. **Adopted (2026-10-21):** snapshots are now read automatically from the dashboard's
   stored Odds API fetches each run, and the job is scheduled by `schedule.ps1`. `market_snapshot` stays a
   candidate that must earn promotion on journaled Thursday evidence; it is not made the default by policy.
2. **QB availability, injuries, weather, tactical matchups, drive simulation:** not built. nflverse lists
   actual starters (known at kickoff), there are no timestamped injury reports, weather is observed, and the
   play-by-play point-in-time aggregation isn't wired in. These are excluded from every model, and the report
   says so each week. The QB slice in reports is retrospective only.
3. **Recorded Deadeye forecasts:** the adapter reads the dashboard's saved cards and keeps `rebuilt`
   cards apart. This checkout has none, so the Deadeye comparison here is the **reconstructed line-only
   proxy on the closing line**, labelled as such. Matching recorded cards to game ids for scoring isn't
   automated yet.
4. **Pool lines in backtests** are rebuilt from the closing spread with the commissioner's measured habit
   (`acql.model.backtest.pool_line`). They are not the real sheets.
5. Elo and Kalman parameters are fixed literature/prior values, not tuned. The logistic L2 strength is tuned
   only inside each training window.
6. Results are assumed published 4 hours after kickoff (`result_delay_hours`). Overtime or late games past
   that would only matter if a lock fell inside that gap, which never happens with Thursday locks.
7. The holdout ensembles were equal-weight in the one viewing (see §3).
8. CI runs the new suite in the existing workflow. It doesn't schedule the weekly job; scheduling is
   left to cron or Task Scheduler (see OPERATIONS.md).
