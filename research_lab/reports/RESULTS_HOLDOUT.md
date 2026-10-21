# Frozen holdout results (2024-2025)

Period: **2024-2025 (frozen holdout)**. Regular-season games: 544; scored on the matched set every model priced: **544** (ties excluded from probability scores).

**Information sets.** `week_start` = Tuesday 09:00 ET, completed games only (prospective-equivalent).
`pre_kickoff` = adds confirmed starters / timestamped final injury report (~90 min before kickoff; after the ACQL card
deadline). `closing_retrospective` = closing lines and/or observed weather: a benchmark, not a forecast anyone could
have made at the card deadline. Deadeye's line-only proxy is Deadeye's own margin->chance curve applied to the
nflverse **closing** spread; it is not Deadeye's recorded forecast.

## Probability scores (matched games)

| model | info_set | uses_market | n | log_loss | log_loss_cal | brier | accuracy | ece | margin_mae | total_mae |
|---|---|---|---|---|---|---|---|---|---|---|
| G_market_stack | closing_retrospective | True | 543 | 0.5963 |  | 0.2053 | 0.6851 | 0.0284 |  |  |
| deadeye_line_only_proxy | closing_retrospective | True | 543 | 0.5974 | 0.5976 | 0.2059 | 0.6832 | 0.0263 | 9.6713 |  |
| G_market_equal | closing_retrospective | True | 543 | 0.5976 |  | 0.2059 | 0.6832 | 0.0271 |  |  |
| G_market_weighted | closing_retrospective | True | 543 | 0.5976 |  | 0.2059 | 0.6832 | 0.0271 |  |  |
| market_spread_close | closing_retrospective | True | 543 | 0.5980 | 0.5980 | 0.2062 | 0.6832 | 0.0341 | 9.6713 | 10.0203 |
| market_ml_close | closing_retrospective | True | 543 | 0.5984 | 0.5976 | 0.2061 | 0.6851 | 0.0313 | 9.6713 | 10.0203 |
| D_market_full | closing_retrospective | True | 543 | 0.5987 | 0.5985 | 0.2063 | 0.6832 | 0.0303 | 9.6713 | 10.0203 |
| challenger_elo | week_start | False | 543 | 0.6245 | 0.6246 | 0.2175 | 0.6556 | 0.0525 | 10.1435 |  |
| A_qb_confirmed | pre_kickoff | False | 543 | 0.6266 | 0.6276 | 0.2179 | 0.6667 | 0.0466 | 10.1154 | 10.5083 |
| A_qb_injury | pre_kickoff | False | 543 | 0.6273 | 0.6278 | 0.2181 | 0.6667 | 0.0443 | 10.1262 | 10.4960 |
| G_free_stack | week_start | False | 543 | 0.6275 |  | 0.2182 | 0.6611 | 0.0385 |  |  |
| F_matchup_interaction | week_start | False | 543 | 0.6283 | 0.6271 | 0.2190 | 0.6593 | 0.0550 | 10.1543 | 10.4890 |
| E_bayes_plugin | week_start | False | 543 | 0.6290 | 0.6290 | 0.2196 | 0.6556 | 0.0415 | 10.2011 | 10.3581 |
| E_bayes | week_start | False | 543 | 0.6290 | 0.6289 | 0.2196 | 0.6556 | 0.0380 | 10.2011 | 10.3581 |
| F_matchup_additive | week_start | False | 543 | 0.6299 | 0.6292 | 0.2196 | 0.6593 | 0.0545 | 10.1612 | 10.5169 |
| C_base | week_start | False | 543 | 0.6300 | 0.6295 | 0.2198 | 0.6556 | 0.0566 | 10.1687 | 10.4694 |
| C_sit_weather | closing_retrospective | False | 543 | 0.6307 | 0.6299 | 0.2202 | 0.6483 | 0.0451 | 10.2134 | 10.4483 |
| C_situational | week_start | False | 543 | 0.6308 | 0.6301 | 0.2202 | 0.6556 | 0.0448 | 10.2097 | 10.5305 |
| A_qb_weekstart | week_start | False | 543 | 0.6315 | 0.6316 | 0.2202 | 0.6667 | 0.0425 | 10.1706 | 10.4892 |
| G_free_equal | week_start | False | 543 | 0.6316 |  | 0.2199 | 0.6703 | 0.0378 |  |  |
| G_free_weighted | week_start | False | 543 | 0.6316 |  | 0.2199 | 0.6703 | 0.0378 |  |  |
| B_drive_sim | week_start | False | 543 | 0.6387 | 0.6392 | 0.2240 | 0.6372 | 0.0458 | 10.2684 | 10.2169 |
| logistic_pointdiff | week_start | False | 543 | 0.6516 | 0.6526 | 0.2300 | 0.6188 | 0.0689 | 10.4768 |  |

`log_loss_cal` = after Platt scaling fitted on the same model's earlier seasons only (first two scored seasons uncalibrated are excluded from that column's average, so it covers fewer games).

## Paired log-loss difference vs `market_ml_close`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| G_market_stack | 543 | 36 | -0.0021 | -0.0057 | 0.0018 | 0.8510 | no clear difference |
| deadeye_line_only_proxy | 543 | 36 | -0.0010 | -0.0049 | 0.0028 | 0.6780 | no clear difference |
| G_market_equal | 543 | 36 | -0.0008 | -0.0024 | 0.0009 | 0.8190 | no clear difference |
| G_market_weighted | 543 | 36 | -0.0008 | -0.0024 | 0.0009 | 0.8190 | no clear difference |
| market_spread_close | 543 | 36 | -0.0004 | -0.0036 | 0.0029 | 0.5705 | no clear difference |
| D_market_full | 543 | 36 | 0.0003 | -0.0027 | 0.0031 | 0.4120 | no clear difference |
| challenger_elo | 543 | 36 | 0.0261 | 0.0075 | 0.0473 | 0.0010 | worse (CI > 0) |
| A_qb_confirmed | 543 | 36 | 0.0282 | 0.0123 | 0.0438 | 0.0005 | worse (CI > 0) |
| A_qb_injury | 543 | 36 | 0.0289 | 0.0134 | 0.0461 | 0.0005 | worse (CI > 0) |
| G_free_stack | 543 | 36 | 0.0291 | 0.0118 | 0.0477 | 0.0005 | worse (CI > 0) |
| F_matchup_interaction | 543 | 36 | 0.0299 | 0.0157 | 0.0441 | 0.0000 | worse (CI > 0) |
| E_bayes_plugin | 543 | 36 | 0.0306 | 0.0152 | 0.0456 | 0.0000 | worse (CI > 0) |
| E_bayes | 543 | 36 | 0.0306 | 0.0153 | 0.0456 | 0.0000 | worse (CI > 0) |
| F_matchup_additive | 543 | 36 | 0.0315 | 0.0159 | 0.0471 | 0.0000 | worse (CI > 0) |
| C_base | 543 | 36 | 0.0316 | 0.0154 | 0.0479 | 0.0000 | worse (CI > 0) |
| C_sit_weather | 543 | 36 | 0.0323 | 0.0179 | 0.0469 | 0.0000 | worse (CI > 0) |
| C_situational | 543 | 36 | 0.0324 | 0.0175 | 0.0475 | 0.0000 | worse (CI > 0) |
| A_qb_weekstart | 543 | 36 | 0.0331 | 0.0164 | 0.0510 | 0.0005 | worse (CI > 0) |
| G_free_equal | 543 | 36 | 0.0332 | 0.0146 | 0.0538 | 0.0005 | worse (CI > 0) |
| G_free_weighted | 543 | 36 | 0.0332 | 0.0146 | 0.0538 | 0.0005 | worse (CI > 0) |
| B_drive_sim | 543 | 36 | 0.0403 | 0.0265 | 0.0540 | 0.0000 | worse (CI > 0) |
| logistic_pointdiff | 543 | 36 | 0.0531 | 0.0323 | 0.0718 | 0.0000 | worse (CI > 0) |

## Paired log-loss difference vs `deadeye_line_only_proxy`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| G_market_stack | 543 | 36 | -0.0011 | -0.0066 | 0.0043 | 0.6530 | no clear difference |
| G_market_equal | 543 | 36 | 0.0002 | -0.0042 | 0.0045 | 0.4775 | no clear difference |
| G_market_weighted | 543 | 36 | 0.0002 | -0.0042 | 0.0045 | 0.4775 | no clear difference |
| market_spread_close | 543 | 36 | 0.0006 | -0.0017 | 0.0029 | 0.3085 | no clear difference |
| market_ml_close | 543 | 36 | 0.0010 | -0.0028 | 0.0049 | 0.3220 | no clear difference |
| D_market_full | 543 | 36 | 0.0012 | -0.0019 | 0.0045 | 0.2395 | no clear difference |
| challenger_elo | 543 | 36 | 0.0271 | 0.0075 | 0.0486 | 0.0010 | worse (CI > 0) |
| A_qb_confirmed | 543 | 36 | 0.0292 | 0.0125 | 0.0455 | 0.0005 | worse (CI > 0) |
| A_qb_injury | 543 | 36 | 0.0298 | 0.0134 | 0.0469 | 0.0005 | worse (CI > 0) |
| G_free_stack | 543 | 36 | 0.0301 | 0.0117 | 0.0492 | 0.0005 | worse (CI > 0) |
| F_matchup_interaction | 543 | 36 | 0.0308 | 0.0160 | 0.0458 | 0.0000 | worse (CI > 0) |
| E_bayes_plugin | 543 | 36 | 0.0315 | 0.0150 | 0.0478 | 0.0000 | worse (CI > 0) |
| E_bayes | 543 | 36 | 0.0316 | 0.0153 | 0.0478 | 0.0000 | worse (CI > 0) |
| F_matchup_additive | 543 | 36 | 0.0325 | 0.0161 | 0.0490 | 0.0000 | worse (CI > 0) |
| C_base | 543 | 36 | 0.0326 | 0.0156 | 0.0498 | 0.0000 | worse (CI > 0) |
| C_sit_weather | 543 | 36 | 0.0333 | 0.0177 | 0.0487 | 0.0000 | worse (CI > 0) |
| C_situational | 543 | 36 | 0.0334 | 0.0177 | 0.0496 | 0.0000 | worse (CI > 0) |
| A_qb_weekstart | 543 | 36 | 0.0341 | 0.0164 | 0.0517 | 0.0005 | worse (CI > 0) |
| G_free_equal | 543 | 36 | 0.0342 | 0.0145 | 0.0546 | 0.0005 | worse (CI > 0) |
| G_free_weighted | 543 | 36 | 0.0342 | 0.0145 | 0.0546 | 0.0005 | worse (CI > 0) |
| B_drive_sim | 543 | 36 | 0.0413 | 0.0262 | 0.0563 | 0.0000 | worse (CI > 0) |
| logistic_pointdiff | 543 | 36 | 0.0541 | 0.0322 | 0.0742 | 0.0000 | worse (CI > 0) |

## Paired log-loss difference vs `challenger_elo`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| G_market_stack | 543 | 36 | -0.0282 | -0.0500 | -0.0078 | 0.9990 | better (CI < 0) |
| deadeye_line_only_proxy | 543 | 36 | -0.0271 | -0.0486 | -0.0075 | 0.9990 | better (CI < 0) |
| G_market_equal | 543 | 36 | -0.0269 | -0.0482 | -0.0079 | 0.9990 | better (CI < 0) |
| G_market_weighted | 543 | 36 | -0.0269 | -0.0482 | -0.0079 | 0.9990 | better (CI < 0) |
| market_spread_close | 543 | 36 | -0.0265 | -0.0488 | -0.0069 | 0.9990 | better (CI < 0) |
| market_ml_close | 543 | 36 | -0.0261 | -0.0473 | -0.0075 | 0.9990 | better (CI < 0) |
| D_market_full | 543 | 36 | -0.0259 | -0.0480 | -0.0068 | 0.9990 | better (CI < 0) |
| A_qb_confirmed | 543 | 36 | 0.0021 | -0.0150 | 0.0194 | 0.3815 | no clear difference |
| A_qb_injury | 543 | 36 | 0.0027 | -0.0115 | 0.0167 | 0.3270 | no clear difference |
| G_free_stack | 543 | 36 | 0.0030 | -0.0091 | 0.0147 | 0.2915 | no clear difference |
| F_matchup_interaction | 543 | 36 | 0.0037 | -0.0088 | 0.0160 | 0.2690 | no clear difference |
| E_bayes_plugin | 543 | 36 | 0.0045 | -0.0065 | 0.0143 | 0.1985 | no clear difference |
| E_bayes | 543 | 36 | 0.0045 | -0.0066 | 0.0142 | 0.2020 | no clear difference |
| F_matchup_additive | 543 | 36 | 0.0054 | -0.0066 | 0.0171 | 0.1845 | no clear difference |
| C_base | 543 | 36 | 0.0055 | -0.0056 | 0.0174 | 0.1680 | no clear difference |
| C_sit_weather | 543 | 36 | 0.0062 | -0.0063 | 0.0184 | 0.1625 | no clear difference |
| C_situational | 543 | 36 | 0.0063 | -0.0060 | 0.0183 | 0.1495 | no clear difference |
| A_qb_weekstart | 543 | 36 | 0.0070 | -0.0062 | 0.0205 | 0.1520 | no clear difference |
| G_free_equal | 543 | 36 | 0.0071 | -0.0072 | 0.0212 | 0.1605 | no clear difference |
| G_free_weighted | 543 | 36 | 0.0071 | -0.0072 | 0.0212 | 0.1605 | no clear difference |
| B_drive_sim | 543 | 36 | 0.0142 | 0.0011 | 0.0266 | 0.0180 | worse (CI > 0) |
| logistic_pointdiff | 543 | 36 | 0.0270 | 0.0014 | 0.0503 | 0.0170 | worse (CI > 0) |

**Multiple comparisons.** 66 paired log-loss comparisons are reported here (plus Brier versions). At 95% about one in twenty intervals excludes zero by chance alone, so an isolated 'better' or 'worse' among many should not be read as a finding without replication on the holdout.

## Log loss by season

| season | market_ml_close | deadeye_line_only_proxy | D_market_full | G_market_stack | G_free_stack | G_free_equal | A_qb_confirmed | A_qb_weekstart | E_bayes | C_situational | B_drive_sim | challenger_elo | F_matchup_interaction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | 0.5875 | 0.5849 | 0.5869 | 0.5826 | 0.6108 | 0.6108 | 0.6073 | 0.6140 | 0.6189 | 0.6247 | 0.6352 | 0.6098 | 0.6206 |
| 2025 | 0.6094 | 0.6101 | 0.6105 | 0.6101 | 0.6442 | 0.6526 | 0.6460 | 0.6491 | 0.6391 | 0.6369 | 0.6422 | 0.6393 | 0.6360 |

## Early vs late season (log loss)

| phase | market_ml_close | deadeye_line_only_proxy | D_market_full | G_market_stack | G_free_stack | G_free_equal | A_qb_confirmed | A_qb_weekstart | E_bayes | C_situational | B_drive_sim | challenger_elo | F_matchup_interaction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| weeks 1-4 | 0.6428 | 0.6430 | 0.6400 | 0.6392 | 0.6349 | 0.6329 | 0.6437 | 0.6328 | 0.6515 | 0.6489 | 0.6602 | 0.6432 | 0.6514 |
| weeks 5-9 | 0.6021 | 0.5949 | 0.6017 | 0.5935 | 0.6376 | 0.6416 | 0.6418 | 0.6418 | 0.6469 | 0.6456 | 0.6601 | 0.6498 | 0.6429 |
| weeks 10-18 | 0.5756 | 0.5775 | 0.5777 | 0.5777 | 0.6187 | 0.6257 | 0.6104 | 0.6254 | 0.6089 | 0.6144 | 0.6172 | 0.6023 | 0.6097 |

## Does explicit uncertainty help? (E_bayes vs E_bayes_plugin)

Same filter, same means; E_bayes widens each forecast by its posterior state variance, the plug-in uses a fixed spread. Negative = uncertainty helps.

| phase | n | diff | lo | hi | p_a_better |
|---|---|---|---|---|---|
| weeks 1-4 | 127 | -0.00030 | -0.00320 | 0.00215 | 0.55900 |
| weeks 5-9 | 145 | -0.00037 | -0.00168 | 0.00076 | 0.70400 |
| weeks 10-18 | 271 | 0.00037 | -0.00009 | 0.00086 | 0.05400 |
| all | 543 | 0.00002 | -0.00079 | 0.00073 | 0.45750 |

## Favourite / underdog picks (straight-up accuracy)

How often each model's pick is the closing-market favourite, and how often it is right when it is and isn't.

| model | picks_market_fav | acc_when_fav | picks_market_dog | acc_when_dog |
|---|---|---|---|---|
| A_qb_confirmed | 475 | 0.699 | 69 | 0.435 |
| A_qb_weekstart | 463 | 0.704 | 81 | 0.444 |
| B_drive_sim | 453 | 0.691 | 91 | 0.363 |
| C_situational | 455 | 0.701 | 89 | 0.416 |
| D_market_full | 544 | 0.682 | 0 |  |
| E_bayes | 457 | 0.700 | 87 | 0.414 |
| F_matchup_interaction | 461 | 0.701 | 83 | 0.422 |
| G_free_equal | 461 | 0.707 | 83 | 0.458 |
| G_free_stack | 470 | 0.698 | 74 | 0.419 |
| G_market_stack | 535 | 0.686 | 9 | 0.556 |
| challenger_elo | 455 | 0.701 | 89 | 0.416 |
| deadeye_line_only_proxy | 544 | 0.682 | 0 |  |
| market_ml_close | 541 | 0.684 | 3 | 0.667 |

## Reliability (said vs came, by probability band)

**market_ml_close**

| band | n | said | came |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.088 | 0.000 |
| 0.1-0.2 | 10 | 0.166 | 0.100 |
| 0.2-0.3 | 49 | 0.254 | 0.235 |
| 0.3-0.4 | 76 | 0.350 | 0.316 |
| 0.4-0.5 | 88 | 0.444 | 0.398 |
| 0.5-0.6 | 97 | 0.557 | 0.577 |
| 0.6-0.7 | 92 | 0.646 | 0.652 |
| 0.7-0.8 | 85 | 0.745 | 0.718 |
| 0.8-0.9 | 42 | 0.850 | 0.929 |
| 0.9-1.0 | 4 | 0.910 | 1.000 |

**E_bayes**

| band | n | said | came |
|---|---|---|---|
| 0.1-0.2 | 4 | 0.162 | 0.250 |
| 0.2-0.3 | 28 | 0.248 | 0.357 |
| 0.3-0.4 | 62 | 0.353 | 0.266 |
| 0.4-0.5 | 120 | 0.454 | 0.392 |
| 0.5-0.6 | 117 | 0.551 | 0.538 |
| 0.6-0.7 | 111 | 0.650 | 0.649 |
| 0.7-0.8 | 70 | 0.746 | 0.771 |
| 0.8-0.9 | 31 | 0.846 | 0.871 |
| 0.9-1.0 | 1 | 0.905 | 1.000 |

**G_free_stack**

| band | n | said | came |
|---|---|---|---|
| 0.0-0.1 | 1 | 0.091 | 1.000 |
| 0.1-0.2 | 13 | 0.173 | 0.462 |
| 0.2-0.3 | 31 | 0.261 | 0.242 |
| 0.3-0.4 | 74 | 0.360 | 0.284 |
| 0.4-0.5 | 108 | 0.449 | 0.407 |
| 0.5-0.6 | 98 | 0.549 | 0.541 |
| 0.6-0.7 | 101 | 0.650 | 0.644 |
| 0.7-0.8 | 70 | 0.744 | 0.771 |
| 0.8-0.9 | 42 | 0.843 | 0.810 |
| 0.9-1.0 | 6 | 0.920 | 1.000 |

**B_drive_sim**

| band | n | said | came |
|---|---|---|---|
| 0.1-0.2 | 1 | 0.196 | 1.000 |
| 0.2-0.3 | 20 | 0.265 | 0.350 |
| 0.3-0.4 | 52 | 0.361 | 0.356 |
| 0.4-0.5 | 123 | 0.456 | 0.358 |
| 0.5-0.6 | 147 | 0.552 | 0.517 |
| 0.6-0.7 | 116 | 0.648 | 0.664 |
| 0.7-0.8 | 66 | 0.745 | 0.773 |
| 0.8-0.9 | 19 | 0.833 | 0.895 |

## ACQL cards under the repository's rules

One point per correct pick; favourites of 6.5+ carry a pool line `max(7, floor(spread)+1)` and must win by `ceil(line)` (acql.model.backtest.pool_line, acql.analytics.line_need). Pool lines are **reconstructed from the closing spread** for every season; the repository records one ruleset, applied throughout. Intervals resample whole weeks.

| model | weeks | total | per_week | sd_week | vs deadeye_line_only_proxy /wk | 95% CI (deadeye_line_only_proxy) | vs market_ml_close /wk | 95% CI (market_ml_close) |
|---|---|---|---|---|---|---|---|---|
| market_ml_close | 36 | 325 | 9.028 | 2.372 | 0.028 | [+0.00, +0.08] |  |  |
| D_market_full | 36 | 324 | 9.000 | 2.342 | 0.000 | [+0.00, +0.00] | -0.028 | [-0.08, +0.00] |
| deadeye_line_only_proxy | 36 | 324 | 9.000 | 2.342 |  |  | -0.028 | [-0.08, +0.00] |
| market_spread_close | 36 | 324 | 9.000 | 2.342 | 0.000 | [+0.00, +0.00] | -0.028 | [-0.08, +0.00] |
| G_market_equal | 36 | 318 | 8.833 | 1.859 | -0.167 | [-0.83, +0.53] | -0.194 | [-0.86, +0.50] |
| G_market_stack | 36 | 318 | 8.833 | 1.765 | -0.167 | [-0.81, +0.50] | -0.194 | [-0.83, +0.50] |
| G_market_weighted | 36 | 318 | 8.833 | 1.859 | -0.167 | [-0.83, +0.53] | -0.194 | [-0.86, +0.50] |
| G_free_equal | 36 | 316 | 8.778 | 2.257 | -0.222 | [-0.92, +0.44] | -0.250 | [-0.92, +0.42] |
| G_free_weighted | 36 | 316 | 8.778 | 2.257 | -0.222 | [-0.92, +0.44] | -0.250 | [-0.92, +0.42] |
| F_matchup_interaction | 36 | 310 | 8.611 | 1.917 | -0.389 | [-1.03, +0.25] | -0.417 | [-1.06, +0.22] |
| A_qb_weekstart | 36 | 309 | 8.583 | 2.260 | -0.417 | [-1.08, +0.25] | -0.444 | [-1.11, +0.22] |
| G_free_stack | 36 | 307 | 8.528 | 2.104 | -0.472 | [-1.08, +0.17] | -0.500 | [-1.11, +0.11] |
| challenger_elo | 36 | 305 | 8.472 | 2.158 | -0.528 | [-1.25, +0.25] | -0.556 | [-1.28, +0.22] |
| A_qb_injury | 36 | 304 | 8.444 | 2.286 | -0.556 | [-1.25, +0.14] | -0.583 | [-1.25, +0.08] |
| E_bayes | 36 | 304 | 8.444 | 2.286 | -0.556 | [-1.36, +0.22] | -0.583 | [-1.39, +0.19] |
| E_bayes_plugin | 36 | 304 | 8.444 | 2.286 | -0.556 | [-1.36, +0.22] | -0.583 | [-1.39, +0.19] |
| F_matchup_additive | 36 | 304 | 8.444 | 2.157 | -0.556 | [-1.28, +0.17] | -0.583 | [-1.28, +0.11] |
| C_situational | 36 | 302 | 8.389 | 1.931 | -0.611 | [-1.25, +0.08] | -0.639 | [-1.28, +0.03] |
| C_base | 36 | 301 | 8.361 | 2.167 | -0.639 | [-1.36, +0.06] | -0.667 | [-1.36, +0.03] |
| B_drive_sim | 36 | 300 | 8.333 | 2.014 | -0.667 | [-1.33, +0.00] | -0.694 | [-1.36, -0.03] |
| C_sit_weather | 36 | 299 | 8.306 | 2.162 | -0.694 | [-1.31, -0.08] | -0.722 | [-1.31, -0.14] |
| A_qb_confirmed | 36 | 297 | 8.250 | 2.500 | -0.750 | [-1.50, +0.03] | -0.778 | [-1.53, -0.03] |
| logistic_pointdiff | 36 | 292 | 8.111 | 1.848 | -0.889 | [-1.56, -0.30] | -0.917 | [-1.58, -0.31] |

### ACQL points by season

| season | A_qb_confirmed | A_qb_weekstart | B_drive_sim | C_situational | D_market_full | E_bayes | F_matchup_interaction | G_free_equal | G_free_stack | G_market_stack | challenger_elo | deadeye_line_only_proxy | market_ml_close |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024 | 168 | 174 | 162 | 159 | 174 | 166 | 171 | 173 | 172 | 169 | 158 | 174 | 175 |
| 2025 | 129 | 135 | 138 | 143 | 150 | 138 | 139 | 143 | 135 | 149 | 147 | 150 | 150 |

## Ensemble (Model G): what was chosen

Components were selected each season by forward selection on earlier seasons' out-of-fold forecasts (walk-forward validation on the last 3 training seasons; a component joins only if it lowers validation log loss by 0.0005).

| season | ensemble | chosen |
|---|---|---|
| 2024 | G_free_equal | A_qb_weekstart |
| 2024 | G_free_weighted | A_qb_weekstart |
| 2024 | G_free_stack | A_qb_weekstart |
| 2025 | G_free_equal | A_qb_weekstart |
| 2025 | G_free_weighted | A_qb_weekstart |
| 2025 | G_free_stack | A_qb_weekstart, challenger_elo |
| 2024 | G_market_equal | market_ml_close |
| 2024 | G_market_weighted | market_ml_close |
| 2024 | G_market_stack | market_ml_close, logistic_pointdiff, F_matchup_additive, A_qb_weekstart |
| 2025 | G_market_equal | market_ml_close |
| 2025 | G_market_weighted | market_ml_close |
| 2025 | G_market_stack | market_ml_close, logistic_pointdiff |

### Error correlation (market-free components)

Correlation of (forecast - outcome) across games. Outcome noise is shared by every model, so these sit near 1 for any set of decent forecasts; the incremental-value table below is the sharper test.

| component | A_qb_weekstart | B_drive_sim | C_situational | E_bayes | F_matchup_additive | F_matchup_interaction | challenger_elo | logistic_pointdiff |
|---|---|---|---|---|---|---|---|---|
| A_qb_weekstart | 1.00 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.97 |
| B_drive_sim | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.99 |
| C_situational | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 |
| E_bayes | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 |
| F_matchup_additive | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 |
| F_matchup_interaction | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 |
| challenger_elo | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 1.00 | 0.97 |
| logistic_pointdiff | 0.97 | 0.99 | 0.98 | 0.98 | 0.98 | 0.98 | 0.97 | 1.00 |

### Incremental value given all other market-free components

Walk-forward logistic stack with vs without the component (negative = it adds information).

| component | n | with_minus_without | lo | hi | p_adds |
|---|---|---|---|---|---|
| challenger_elo | 543 | -0.00169 | -0.00419 | 0.00103 | 0.89600 |
| E_bayes | 543 | -0.00020 | -0.00251 | 0.00186 | 0.56800 |
| F_matchup_interaction | 543 | 0.00004 | -0.00006 | 0.00012 | 0.23000 |
| C_situational | 543 | 0.00007 | -0.00173 | 0.00178 | 0.46050 |
| logistic_pointdiff | 543 | 0.00041 | -0.00072 | 0.00156 | 0.24900 |
| F_matchup_additive | 543 | 0.00067 | -0.00143 | 0.00264 | 0.24850 |
| A_qb_weekstart | 543 | 0.00094 | -0.00662 | 0.00845 | 0.38350 |
| B_drive_sim | 543 | 0.00098 | 0.00010 | 0.00194 | 0.01200 |

### Error correlation (market-informed components)

Correlation of (forecast - outcome) across games. Outcome noise is shared by every model, so these sit near 1 for any set of decent forecasts; the incremental-value table below is the sharper test.

| component | A_qb_confirmed | A_qb_weekstart | B_drive_sim | C_sit_weather | C_situational | D_market_full | E_bayes | F_matchup_additive | F_matchup_interaction | challenger_elo | logistic_pointdiff | market_ml_close |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_qb_confirmed | 1.00 | 1.00 | 0.98 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 0.98 | 0.97 | 0.98 |
| A_qb_weekstart | 1.00 | 1.00 | 0.99 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 0.99 | 0.97 | 0.98 |
| B_drive_sim | 0.98 | 0.99 | 1.00 | 1.00 | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 0.99 | 0.99 | 0.98 |
| C_sit_weather | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| C_situational | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| D_market_full | 0.98 | 0.98 | 0.97 | 0.98 | 0.98 | 1.00 | 0.98 | 0.98 | 0.98 | 0.98 | 0.96 | 1.00 |
| E_bayes | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| F_matchup_additive | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| F_matchup_interaction | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| challenger_elo | 0.98 | 0.99 | 0.99 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 1.00 | 0.97 | 0.98 |
| logistic_pointdiff | 0.97 | 0.97 | 0.99 | 0.98 | 0.98 | 0.96 | 0.98 | 0.98 | 0.98 | 0.97 | 1.00 | 0.96 |
| market_ml_close | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 1.00 | 0.98 | 0.98 | 0.98 | 0.98 | 0.96 | 1.00 |

### Incremental value given all other market-informed components

Walk-forward logistic stack with vs without the component (negative = it adds information).

| component | n | with_minus_without | lo | hi | p_adds |
|---|---|---|---|---|---|
| market_ml_close | 543 | -0.00116 | -0.00335 | 0.00126 | 0.84700 |
| challenger_elo | 543 | -0.00035 | -0.00148 | 0.00089 | 0.74150 |
| E_bayes | 543 | -0.00012 | -0.00152 | 0.00116 | 0.56550 |
| D_market_full | 543 | 0.00001 | -0.00097 | 0.00092 | 0.47950 |
| C_sit_weather | 543 | 0.00006 | -0.00011 | 0.00022 | 0.22850 |
| A_qb_weekstart | 543 | 0.00009 | -0.00096 | 0.00111 | 0.43300 |
| B_drive_sim | 543 | 0.00014 | -0.00015 | 0.00041 | 0.17350 |
| logistic_pointdiff | 543 | 0.00021 | -0.00187 | 0.00254 | 0.43800 |
| C_situational | 543 | 0.00026 | -0.00013 | 0.00069 | 0.10350 |
| F_matchup_interaction | 543 | 0.00032 | 0.00002 | 0.00065 | 0.01900 |
| A_qb_confirmed | 543 | 0.00047 | -0.00065 | 0.00158 | 0.19450 |
| F_matchup_additive | 543 | 0.00064 | -0.00138 | 0.00261 | 0.26450 |

## Signal discovery: feature-family ablations

Each row compares two walk-forward logistic regressions on identical games (penalty fixed in advance). `diff` = log loss with the family minus without; negative = the family adds information. Every run is in `research_lab/experiments/registry.jsonl`, including failures.

| family | comparison | n | ll_with | ll_without | diff | lo | hi | p_improves | verdict |
|---|---|---|---|---|---|---|---|---|---|
| qb_weekstart | market + family vs market | 543 | 0.6011 | 0.5978 | 0.0033 | -0.0002 | 0.0067 | 0.0315 | no clear effect |
| qb_weekstart | football + family vs football | 543 | 0.6267 | 0.6290 | -0.0022 | -0.0098 | 0.0057 | 0.7125 | no clear effect |
| qb_weekstart | full vs full without family | 543 | 0.6080 | 0.6074 | 0.0006 | -0.0026 | 0.0038 | 0.3610 | no clear effect |
| qb_confirmed | market + family vs market | 543 | 0.6012 | 0.5978 | 0.0034 | -0.0010 | 0.0079 | 0.0640 | no clear effect |
| qb_confirmed | football + family vs football | 543 | 0.6204 | 0.6290 | -0.0086 | -0.0202 | 0.0041 | 0.9115 | no clear effect |
| qb_confirmed | full vs full without family | 543 | 0.6080 | 0.6071 | 0.0009 | -0.0018 | 0.0036 | 0.2395 | no clear effect |
| rest_travel | market + family vs market | 543 | 0.6011 | 0.5978 | 0.0033 | -0.0007 | 0.0073 | 0.0565 | no clear effect |
| rest_travel | football + family vs football | 543 | 0.6314 | 0.6290 | 0.0024 | -0.0024 | 0.0067 | 0.1590 | no clear effect |
| rest_travel | full vs full without family | 543 | 0.6080 | 0.6043 | 0.0037 | -0.0004 | 0.0077 | 0.0455 | no clear effect |
| environment | market + family vs market | 543 | 0.5978 | 0.5978 | 0.0000 | -0.0013 | 0.0014 | 0.4845 | no clear effect |
| environment | football + family vs football | 543 | 0.6289 | 0.6290 | -0.0001 | -0.0017 | 0.0017 | 0.5495 | no clear effect |
| environment | full vs full without family | 543 | 0.6080 | 0.6079 | 0.0001 | -0.0009 | 0.0013 | 0.4205 | no clear effect |
| tactical | market + family vs market | 543 | 0.5997 | 0.5978 | 0.0019 | -0.0007 | 0.0044 | 0.0795 | no clear effect |
| tactical | football + family vs football | 543 | 0.6306 | 0.6290 | 0.0017 | -0.0009 | 0.0040 | 0.1025 | no clear effect |
| tactical | full vs full without family | 543 | 0.6080 | 0.6059 | 0.0021 | -0.0005 | 0.0048 | 0.0620 | no clear effect |
| team_strength | market + family vs market | 543 | 0.5980 | 0.5978 | 0.0002 | -0.0003 | 0.0007 | 0.2360 | no clear effect |
| team_strength | full vs full without family | 543 | 0.6080 | 0.6084 | -0.0004 | -0.0023 | 0.0014 | 0.6840 | no clear effect |
| drive_sim | market + family vs market | 543 | 0.5976 | 0.5978 | -0.0002 | -0.0005 | 0.0001 | 0.8780 | no clear effect |
| drive_sim | football + family vs football | 543 | 0.6308 | 0.6290 | 0.0018 | -0.0001 | 0.0039 | 0.0355 | no clear effect |
| drive_sim | full vs full without family | 543 | 0.6080 | 0.6077 | 0.0003 | -0.0001 | 0.0006 | 0.0655 | no clear effect |
| unit_ratings | market + family vs market | 543 | 0.5975 | 0.5978 | -0.0003 | -0.0023 | 0.0018 | 0.6035 | no clear effect |
| unit_ratings | football + family vs football | 543 | 0.6288 | 0.6290 | -0.0002 | -0.0006 | 0.0002 | 0.8310 | no clear effect |
| unit_ratings | full vs full without family | 543 | 0.6080 | 0.6073 | 0.0007 | -0.0021 | 0.0034 | 0.3200 | no clear effect |
| market_detail | market + family vs market | 543 | 0.5980 | 0.5978 | 0.0002 | -0.0025 | 0.0028 | 0.4315 | no clear effect |
| market_detail | football + family vs football | 543 | 0.6200 | 0.6290 | -0.0090 | -0.0183 | 0.0003 | 0.9685 | no clear effect |
| market_detail | full vs full without family | 543 | 0.6080 | 0.6076 | 0.0004 | -0.0023 | 0.0030 | 0.3740 | no clear effect |

### Not run (no usable historical data)

| family | note |
|---|---|
| market_movement | no historical opening lines or timestamped odds in any accessible source (nflverse keeps closing numbers only; The Odds API history needs a paid key) |
| cross_book | no per-sportsbook historical quotes accessible |
| weather_forecast | no archived pre-game weather forecasts before 2022 accessible; observed weather used as an upper bound instead |

## Model H (scheme matchups) extension

H_scheme = H_base + coverage-weighted pass EPA, pressure, personnel and formation tendencies (nflverse participation, 2018+). Scored where two prior seasons of coverage data exist. Negative diff = scheme features help.

| period | a | b | n | ll_a | ll_b | diff | lo | hi |
|---|---|---|---|---|---|---|---|---|
| development 2021-2023 | H_scheme | H_base | 812 | 0.6514 | 0.6491 | 0.0023 | -0.0011 | 0.0058 |
| development 2021-2023 | H_scheme | E_bayes | 812 | 0.6514 | 0.6497 | 0.0017 | -0.0053 | 0.0081 |
| development 2021-2023 | H_base | E_bayes | 812 | 0.6491 | 0.6497 | -0.0006 | -0.0071 | 0.0052 |
| holdout 2024-2025 | H_scheme | H_base | 543 | 0.6308 | 0.6307 | 0.0001 | -0.0024 | 0.0027 |
| holdout 2024-2025 | H_scheme | E_bayes | 543 | 0.6308 | 0.6290 | 0.0017 | -0.0042 | 0.0085 |
| holdout 2024-2025 | H_base | E_bayes | 543 | 0.6307 | 0.6290 | 0.0017 | -0.0044 | 0.0085 |

## Deadeye's 2026 inputs, recomputed, against the lab (2026 to date)

2026 weeks 1, 2, 3, 4, 5 with Deadeye inputs in the repository (79 games). Deadeye recomputed = its own code at the default share on the tracker files / recorded inputs (weeks 1-2 had typed lines and no models, so Deadeye = the line there). Market is the nflverse closing moneyline. Tiny sample: no conclusion is possible from it.

| model | n | log_loss | brier | accuracy | vs_deadeye | lo | hi |
|---|---|---|---|---|---|---|---|
| C_situational | 78 | 0.6274 | 0.2195 | 0.6026 | -0.0217 | -0.0503 | 0.0069 |
| E_bayes | 78 | 0.6356 | 0.2232 | 0.6026 | -0.0136 | -0.0437 | 0.0167 |
| challenger_elo | 78 | 0.6359 | 0.2236 | 0.6282 | -0.0132 | -0.0460 | 0.0183 |
| A_qb_weekstart | 78 | 0.6367 | 0.2231 | 0.6410 | -0.0125 | -0.0413 | 0.0148 |
| A_qb_confirmed | 78 | 0.6367 | 0.2230 | 0.6538 | -0.0124 | -0.0359 | 0.0051 |
| B_drive_sim | 78 | 0.6368 | 0.2230 | 0.5897 | -0.0123 | -0.0330 | 0.0121 |
| F_matchup_interaction | 78 | 0.6465 | 0.2282 | 0.6026 | -0.0026 | -0.0396 | 0.0396 |
| deadeye_recomputed | 78 | 0.6491 | 0.2286 | 0.6282 |  |  |  |
| market_ml_close | 78 | 0.6508 | 0.2289 | 0.6410 | 0.0016 | -0.0074 | 0.0106 |
| deadeye_line_only_proxy | 78 | 0.6508 | 0.2288 | 0.6410 | 0.0017 | -0.0108 | 0.0187 |
