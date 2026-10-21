# Operation Sunday — 2026 week 7 (REG)

_Research / shadow-production output. Deadeye's production card, ACQL scoring, the public site and the dashboard are not changed by anything here._

## 1. Thursday deadline and lock status

- Nominal deadline (Thursday 18:00 America/New_York): `2026-10-22T22:00:00+00:00`
- First counted kickoff: `2026-10-23T00:15:00+00:00`
- **Lock time: `2026-10-22T22:00:00+00:00`** (Thursday deadline); run due `2026-10-22T10:00:00+00:00`
- Package: `2026-REG-07-r0` — status **locked**, locked `2026-10-21T19:57:04+00:00`, mode **live**, on time: **yes**
- Content hash: `553456ac84abb2fe7c890779f9e144171c741ed6b248ce72c31d2bb20b2287d6`


## 2. Selected model

- **elo**, version `elo@5a85bf3d33df`
- Decision: **fallback** — No approved model exists and no candidate cleared every rule; using the designated baseline elo (FALLBACK).
- Fallback: No approved model exists and no candidate cleared every rule; using the designated baseline elo (FALLBACK).
- Promotion criteria digest `89345cd9065a44f0`: {"min_games": 500, "min_weeks": 30, "min_logloss_gain": 0.002, "ci_level": 0.95, "bootstrap_samples": 2000, "max_ece": 0.035, "calibration_slope_range": [0.75, 1.25]}
- Experiment record: `exp-20261021T195704Z-195702`

## 3. [PREGAME FORECAST] This week's locked forecasts

| game | kickoff (UTC) | P(home) | exp margin | exp total | ACQL pick | P(pick credited) | pool line | flags |
|---|---|---|---|---|---|---|---|---|
| NE @ CHI | 2026-10-23T00:15:00+00:00 | 0.4856 | – | – | NE | 0.5144 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| PIT @ NO | 2026-10-25T13:30:00+00:00 | 0.3334 | – | – | PIT | 0.6666 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| CIN @ BAL | 2026-10-25T17:00:00+00:00 | 0.6126 | – | – | BAL | 0.6126 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| CLE @ TEN | 2026-10-25T17:00:00+00:00 | 0.3790 | – | – | CLE | 0.6210 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| IND @ MIN | 2026-10-25T17:00:00+00:00 | 0.8108 | – | – | MIN | 0.8108 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| MIA @ NYJ | 2026-10-25T17:00:00+00:00 | 0.5798 | – | – | NYJ | 0.5798 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| NYG @ HOU | 2026-10-25T17:00:00+00:00 | 0.7167 | – | – | HOU | 0.7167 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| SF @ ATL | 2026-10-25T17:00:00+00:00 | 0.2876 | – | – | SF | 0.7124 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| TB @ CAR | 2026-10-25T17:00:00+00:00 | 0.6659 | – | – | CAR | 0.6659 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| DEN @ ARI | 2026-10-25T20:05:00+00:00 | 0.2704 | – | – | DEN | 0.7296 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| GB @ DET | 2026-10-25T20:25:00+00:00 | 0.5919 | – | – | DET | 0.5919 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| LA @ LV | 2026-10-25T20:25:00+00:00 | 0.3726 | – | – | LA | 0.6274 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| KC @ SEA | 2026-10-26T00:20:00+00:00 | 0.6621 | – | – | SEA | 0.6621 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |
| DAL @ PHI | 2026-10-27T00:15:00+00:00 | 0.6422 | – | – | PHI | 0.6422 | – | no_market_snapshot, pool_line_unknown_no_spread_at_cutoff |

## 4. Games where models disagree [PREGAME]

| game | home_rate | elo | bayes_strength | logistic | situational | spread (max-min) | sides differ |
|---|---|---|---|---|---|---|---|
| DEN @ ARI | 0.5598 | 0.2704 | 0.3507 | 0.3421 | 0.5681 | 0.2977 | YES |
| SF @ ATL | 0.5598 | 0.2876 | 0.3566 | 0.3709 | 0.5525 | 0.2721 | YES |
| IND @ MIN | 0.5598 | 0.8108 | 0.7037 | 0.7751 | 0.5997 | 0.2510 |  |
| CLE @ TEN | 0.5598 | 0.3790 | 0.4384 | 0.4367 | 0.5685 | 0.1895 | YES |
| LA @ LV | 0.5598 | 0.3726 | 0.3990 | 0.4084 | 0.5550 | 0.1872 | YES |
| PIT @ NO | 0.5000 | 0.3334 | 0.3868 | 0.3398 | 0.4265 | 0.1666 |  |
| NYG @ HOU | 0.5598 | 0.7167 | 0.6945 | 0.6957 | 0.5685 | 0.1569 |  |
| TB @ CAR | 0.5598 | 0.6659 | 0.6136 | 0.6141 | 0.5451 | 0.1207 |  |

## 5. QB and injury uncertainty

QB availability and injuries are **not modelled**: Starting QB is only known for sure at kickoff in this data (nflverse lists actual starters); no timestamped Thursday starter evidence exists, so it is excluded from leakage-sensitive evaluation. No timestamped historical injury reports are stored; post-cutoff injury news cannot be separated. Check late QB news manually; a change after the lock is recorded as a post-lock note and never alters the locked package.

## 6. [RETROSPECTIVE] Candidates and benchmarks on identical games

Walk-forward, out-of-sample, matched games only. `market_close` and `deadeye_line_proxy` use the **closing line** (not available on Thursday) and are benchmarks, never inputs. `deadeye_line_proxy` is a **reconstructed line-only proxy**, not Deadeye's recorded forecasts.

| model | Thursday-eligible | games | log loss | Brier | accuracy | ECE | cal slope | margin MAE | margin RMSE |
|---|---|---|---|---|---|---|---|---|---|
| home_rate | yes | 3471 | 0.6875 | 0.2472 | 0.5549 | 0.0133 | 1.4031 | – | – |
| elo | yes | 3471 | 0.6314 | 0.2207 | 0.6439 | 0.0189 | 0.9411 | – | – |
| bayes_strength | yes | 3471 | 0.6304 | 0.2202 | 0.6462 | 0.0175 | 1.0257 | 10.3505 | 13.3141 |
| logistic | yes | 3471 | 0.6317 | 0.2208 | 0.6416 | 0.0201 | 0.9958 | – | – |
| situational | yes | 3471 | 0.6888 | 0.2478 | 0.5552 | 0.0114 | 0.2717 | – | – |
| ens_equal_football | yes | 3471 | 0.6332 | 0.2215 | 0.6399 | 0.0419 | 1.3379 | – | – |
| ens_stack_football | yes | 3471 | 0.6311 | 0.2205 | 0.6445 | 0.0274 | 1.0889 | – | – |
| ens_perf_football | yes | 3471 | 0.6313 | 0.2206 | 0.6448 | 0.0286 | 1.1838 | – | – |
| market_close | NO (benchmark) | 3471 | 0.6121 | 0.2120 | 0.6646 | 0.0299 | 1.2335 | 10.0230 | 12.9918 |
| deadeye_line_proxy | NO (benchmark) | 3471 | 0.6101 | 0.2113 | 0.6646 | 0.0225 | 0.9837 | 10.0230 | 12.9918 |

Recorded Deadeye forecasts: No recorded Deadeye cards in the dashboard store.

### Paired comparisons (week-block bootstrap; negative = candidate better)

| candidate | vs | games | weeks | Δ log loss | 95% CI lo | 95% CI hi | passes all rules | failed checks |
|---|---|---|---|---|---|---|---|---|
| home_rate | elo | 3471 | 231 | 0.0561 | 0.0449 | 0.0675 | no | gain, ci_excludes_zero, calibration |
| bayes_strength | elo | 3471 | 231 | -0.0010 | -0.0051 | 0.0028 | no | gain, ci_excludes_zero |
| logistic | elo | 3471 | 231 | 0.0003 | -0.0033 | 0.0039 | no | gain, ci_excludes_zero |
| situational | elo | 3471 | 231 | 0.0574 | 0.0457 | 0.0692 | no | gain, ci_excludes_zero, calibration |
| market_close | elo | 3471 | 231 | -0.0193 | -0.0259 | -0.0130 | no | thursday_eligible |
| deadeye_line_proxy | elo | 3471 | 231 | -0.0213 | -0.0288 | -0.0143 | no | thursday_eligible |
| ens_equal_football | elo | 3471 | 231 | 0.0018 | -0.0023 | 0.0055 | no | gain, ci_excludes_zero, calibration |
| ens_stack_football | elo | 3471 | 231 | -0.0003 | -0.0033 | 0.0025 | no | gain, ci_excludes_zero |
| ens_perf_football | elo | 3471 | 231 | -0.0001 | -0.0035 | 0.0029 | no | gain, ci_excludes_zero |
| ens_market_close_bench | elo | 3471 | 231 | -0.0159 | -0.0209 | -0.0113 | no | thursday_eligible |

## 7. [RETROSPECTIVE] Out-of-sample performance by season

| season | model | games | log loss | accuracy |
|---|---|---|---|---|
| 2012 | elo | 255 | 0.6248 | 0.6392 |
| 2012 | market_close | 255 | 0.6020 | 0.6431 |
| 2013 | elo | 255 | 0.6229 | 0.6314 |
| 2013 | market_close | 255 | 0.5963 | 0.7137 |
| 2014 | elo | 255 | 0.6004 | 0.7020 |
| 2014 | market_close | 255 | 0.6056 | 0.6667 |
| 2015 | elo | 256 | 0.6428 | 0.6719 |
| 2015 | market_close | 256 | 0.6484 | 0.6250 |
| 2016 | elo | 254 | 0.6301 | 0.6378 |
| 2016 | market_close | 254 | 0.6300 | 0.6417 |
| 2017 | elo | 256 | 0.6200 | 0.6719 |
| 2017 | market_close | 256 | 0.5899 | 0.7031 |
| 2018 | elo | 254 | 0.6335 | 0.6220 |
| 2018 | market_close | 254 | 0.6114 | 0.6614 |
| 2019 | elo | 255 | 0.6336 | 0.6392 |
| 2019 | market_close | 255 | 0.6127 | 0.6431 |
| 2020 | elo | 255 | 0.6218 | 0.6588 |
| 2020 | market_close | 255 | 0.5947 | 0.6745 |
| 2021 | elo | 271 | 0.6564 | 0.6015 |
| 2021 | market_close | 271 | 0.6217 | 0.6236 |
| 2022 | elo | 269 | 0.6404 | 0.6394 |
| 2022 | market_close | 269 | 0.6100 | 0.6617 |
| 2023 | elo | 272 | 0.6609 | 0.6029 |
| 2023 | market_close | 272 | 0.6239 | 0.6801 |
| 2024 | elo | 272 | 0.6098 | 0.6691 |
| 2024 | market_close | 272 | 0.5940 | 0.7132 |
| 2026 | elo | 92 | 0.6547 | 0.6087 |
| 2026 | market_close | 92 | 0.6583 | 0.6304 |

### Recent 8 evaluated weeks, with uncertainty

| model | weeks | games | log loss | 95% CI lo | 95% CI hi |
|---|---|---|---|---|---|
| elo | 8 | 124 | 0.6557 | 0.5934 | 0.7251 |

_Eight weeks is ~120 games: intervals this wide cannot separate models._

## 8. [RETROSPECTIVE] Probability calibration of the selected model

ECE 0.0189, recalibration slope 0.941

| bucket | n | forecast | observed |
|---|---|---|---|
| 0.0-0.1 | 2 | 0.0962 | 0.0000 |
| 0.1-0.2 | 52 | 0.1623 | 0.2308 |
| 0.2-0.3 | 217 | 0.2598 | 0.3180 |
| 0.3-0.4 | 397 | 0.3558 | 0.3476 |
| 0.4-0.5 | 577 | 0.4511 | 0.4263 |
| 0.5-0.6 | 714 | 0.5495 | 0.5406 |
| 0.6-0.7 | 714 | 0.6483 | 0.6345 |
| 0.7-0.8 | 511 | 0.7474 | 0.7260 |
| 0.8-0.9 | 262 | 0.8368 | 0.8511 |
| 0.9-1.0 | 25 | 0.9161 | 0.8800 |

### By favourite/underdog

| segment | model | games | log_loss | brier | accuracy |
|---|---|---|---|---|---|
| picks market favourite | elo | 2895 | 0.6116 | 0.2114 | 0.6850 |
| picks market favourite | market_close | 3467 | 0.6120 | 0.2119 | 0.6651 |
| picks market underdog | elo | 576 | 0.7308 | 0.2674 | 0.4375 |
| picks market underdog | market_close | 4 | 0.6931 | 0.2500 | 0.2500 |

### By probability bucket

| segment | model | games | log_loss | brier | accuracy |
|---|---|---|---|---|---|
| (0.499, 0.55] | elo | 669 | 0.6906 | 0.2487 | 0.5291 |
| (0.499, 0.55] | market_close | 383 | 0.6935 | 0.2502 | 0.5039 |
| (0.55, 0.6] | elo | 622 | 0.6787 | 0.2428 | 0.5836 |
| (0.55, 0.6] | market_close | 921 | 0.6815 | 0.2442 | 0.5744 |
| (0.6, 0.7] | elo | 1111 | 0.6493 | 0.2285 | 0.6409 |
| (0.6, 0.7] | market_close | 1382 | 0.6207 | 0.2148 | 0.6852 |
| (0.7, 0.8] | elo | 728 | 0.6001 | 0.2049 | 0.7129 |
| (0.7, 0.8] | market_close | 577 | 0.5239 | 0.1702 | 0.7834 |
| (0.8, 1.0] | elo | 341 | 0.4377 | 0.1337 | 0.8416 |
| (0.8, 1.0] | market_close | 208 | 0.3420 | 0.0958 | 0.8942 |

### By QB continuity (retrospective slice)

| segment | model | games | log_loss | brier | accuracy |
|---|---|---|---|---|---|
| QB change (retrospective) | elo | 714 | 0.6536 | 0.2299 | 0.6275 |
| QB change (retrospective) | market_close | 714 | 0.6081 | 0.2103 | 0.6695 |
| same QBs | elo | 2757 | 0.6257 | 0.2183 | 0.6482 |
| same QBs | market_close | 2757 | 0.6131 | 0.2124 | 0.6634 |

### By market spread range

| segment | model | games | log_loss | brier | accuracy |
|---|---|---|---|---|---|
| 0-3 | elo | 1304 | 0.7087 | 0.2569 | 0.5222 |
| 0-3 | market_close | 1304 | 0.6851 | 0.2460 | 0.5537 |
| 10+ (lined) | elo | 321 | 0.4067 | 0.1219 | 0.8567 |
| 10+ (lined) | market_close | 321 | 0.3917 | 0.1157 | 0.8660 |
| 3.5-6 | elo | 1017 | 0.6520 | 0.2294 | 0.6480 |
| 3.5-6 | market_close | 1017 | 0.6430 | 0.2254 | 0.6568 |
| 6.5-10 (lined) | elo | 829 | 0.5716 | 0.1912 | 0.7479 |
| 6.5-10 (lined) | market_close | 829 | 0.5447 | 0.1793 | 0.7708 |

### By data completeness

| segment | model | games | log_loss | brier | accuracy |
|---|---|---|---|---|---|
| complete | elo | 3249 | 0.6309 | 0.2205 | 0.6427 |
| complete | market_close | 3249 | 0.6104 | 0.2112 | 0.6667 |
| has missing data | elo | 222 | 0.6397 | 0.2241 | 0.6622 |
| has missing data | market_close | 222 | 0.6367 | 0.2229 | 0.6351 |

## 9. [RETROSPECTIVE] ACQL scoring comparison

One point per credited pick; favourites of 6.5+ carry a pool line reconstructed from the closing spread with the commissioner's measured habit (acql.model.backtest.pool_line). Same slate, rules and eligibility for every model.

| model | weeks | games | realised / week | expected / week |
|---|---|---|---|---|
| bayes_strength | 231 | 3484 | 8.3593 | 9.0781 |
| deadeye_line_proxy | 231 | 3484 | 8.6710 | 8.8818 |
| elo | 231 | 3484 | 8.4026 | 9.2202 |
| ens_equal_football | 231 | 3484 | 8.3333 | 9.1414 |
| ens_perf_football | 231 | 3484 | 8.4069 | 9.1113 |
| ens_stack_football | 231 | 3484 | 8.3680 | 9.1128 |
| home_rate | 231 | 3484 | 7.7532 | 9.6430 |
| logistic | 231 | 3484 | 8.3636 | 9.1413 |
| market_close | 231 | 3484 | 8.6407 | 8.9287 |
| situational | 231 | 3484 | 7.7749 | 9.6512 |

## 10. [COMPLETED RESULTS] Earlier locked packages

_none_

## 11. Changes since the previous approved version

- no approved model yet

## 12. Features and components

- `ens_equal_football` (equal, 3457 out-of-fold games): elo=0.250, bayes_strength=0.250, logistic=0.250, situational=0.250
- `ens_market_close_bench` (stack, 3457 out-of-fold games): elo=0.206, bayes_strength=0.003, logistic=0.025, situational=0.000, market_close=0.903
- `ens_perf_football` (perf, 3457 out-of-fold games): elo=0.279, bayes_strength=0.380, logistic=0.250, situational=0.092
- `ens_stack_football` (stack, 3457 out-of-fold games): elo=0.345, bayes_strength=0.368, logistic=0.261, situational=0.000
- Not testable this release (excluded from every model): **qb** — Starting QB is only known for sure at kickoff in this data (nflverse lists actual starters); no timestamped Thursday starter evidence exists, so it is excluded from leakage-sensitive evaluation.; **injuries** — No timestamped historical injury reports are stored; post-cutoff injury news cannot be separated.; **weather** — Historical temperature/wind are game-time observations, not forecasts available Thursday.; **tactical** — Needs point-in-time play-by-play matchup aggregates; not built in this release.; **drive_sim** — Needs point-in-time drive-level play-by-play; not built in this release.

Feature-family ablations: `python -m operation_sunday ablation` (see docs/EVIDENCE_REPORT.md).

## 13. Data freshness and warnings

- none

## 14. Decision

**FALLBACK** — No approved model exists and no candidate cleared every rule; using the designated baseline elo (FALLBACK).
