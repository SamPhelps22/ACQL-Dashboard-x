# Development results (walk-forward, 2012-2023)

Period: **2012-2023 (development)**. Regular-season games: 3119; scored on the matched set every model priced: **3119** (ties excluded from probability scores).

**Information sets.** `week_start` = Tuesday 09:00 ET, completed games only (prospective-equivalent).
`pre_kickoff` = adds confirmed starters / timestamped final injury report (~90 min before kickoff; after the ACQL card
deadline). `closing_retrospective` = closing lines and/or observed weather: a benchmark, not a forecast anyone could
have made at the card deadline. Deadeye's line-only proxy is Deadeye's own margin->chance curve applied to the
nflverse **closing** spread; it is not Deadeye's recorded forecast.

## Probability scores (matched games)

| model | info_set | uses_market | n | log_loss | log_loss_cal | brier | accuracy | ece | margin_mae | total_mae |
|---|---|---|---|---|---|---|---|---|---|---|
| deadeye_line_only_proxy | closing_retrospective | True | 3107 | 0.6106 | 0.6108 | 0.2116 | 0.6614 | 0.0266 | 10.0785 |  |
| market_spread_close | closing_retrospective | True | 3107 | 0.6111 | 0.6114 | 0.2117 | 0.6614 | 0.0244 | 10.0785 | 10.5729 |
| market_ml_close | closing_retrospective | True | 3107 | 0.6113 | 0.6113 | 0.2118 | 0.6624 | 0.0203 | 10.0785 | 10.5729 |
| D_market_full | closing_retrospective | True | 3107 | 0.6116 | 0.6120 | 0.2119 | 0.6611 | 0.0185 | 10.0785 | 10.5729 |
| G_market_weighted | closing_retrospective | True | 3107 | 0.6123 | 0.6163 | 0.2123 | 0.6601 | 0.0163 |  |  |
| G_market_equal | closing_retrospective | True | 3107 | 0.6129 | 0.6171 | 0.2126 | 0.6608 | 0.0144 |  |  |
| G_market_stack | closing_retrospective | True | 3107 | 0.6139 | 0.6182 | 0.2130 | 0.6592 | 0.0150 |  |  |
| A_qb_confirmed | pre_kickoff | False | 3107 | 0.6262 | 0.6256 | 0.2182 | 0.6521 | 0.0279 | 10.2930 | 11.1406 |
| A_qb_injury | pre_kickoff | False | 3107 | 0.6294 | 0.6291 | 0.2197 | 0.6434 | 0.0222 | 10.3372 | 11.1334 |
| G_free_equal | week_start | False | 3107 | 0.6299 | 0.6332 | 0.2199 | 0.6395 | 0.0228 |  |  |
| G_free_weighted | week_start | False | 3107 | 0.6301 | 0.6335 | 0.2200 | 0.6392 | 0.0247 |  |  |
| A_qb_weekstart | week_start | False | 3107 | 0.6303 | 0.6300 | 0.2201 | 0.6408 | 0.0245 | 10.3410 | 11.1356 |
| G_free_stack | week_start | False | 3107 | 0.6304 | 0.6336 | 0.2201 | 0.6402 | 0.0197 |  |  |
| E_bayes_plugin | week_start | False | 3107 | 0.6307 | 0.6310 | 0.2203 | 0.6424 | 0.0145 | 10.3754 | 10.9561 |
| E_bayes | week_start | False | 3107 | 0.6307 | 0.6309 | 0.2203 | 0.6424 | 0.0164 | 10.3754 | 10.9561 |
| challenger_elo | week_start | False | 3107 | 0.6326 | 0.6327 | 0.2212 | 0.6427 | 0.0168 | 10.3880 |  |
| C_situational | week_start | False | 3107 | 0.6329 | 0.6327 | 0.2214 | 0.6382 | 0.0254 | 10.3650 | 11.0655 |
| C_base | week_start | False | 3107 | 0.6334 | 0.6335 | 0.2215 | 0.6376 | 0.0220 | 10.3648 | 11.1262 |
| C_sit_weather | closing_retrospective | False | 3107 | 0.6342 | 0.6339 | 0.2220 | 0.6373 | 0.0257 | 10.3822 | 11.0546 |
| B_drive_sim | week_start | False | 3107 | 0.6350 | 0.6329 | 0.2222 | 0.6440 | 0.0310 | 10.3578 | 10.9906 |
| F_matchup_additive | week_start | False | 3107 | 0.6356 | 0.6358 | 0.2225 | 0.6373 | 0.0223 | 10.3987 | 11.1237 |
| F_matchup_interaction | week_start | False | 3107 | 0.6368 | 0.6368 | 0.2230 | 0.6334 | 0.0178 | 10.4222 | 11.1237 |
| logistic_pointdiff | week_start | False | 3107 | 0.6590 | 0.6590 | 0.2326 | 0.6106 | 0.0336 | 10.7608 |  |

`log_loss_cal` = after Platt scaling fitted on the same model's earlier seasons only (first two scored seasons uncalibrated are excluded from that column's average, so it covers fewer games).

## Paired log-loss difference vs `market_ml_close`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| deadeye_line_only_proxy | 3107 | 207 | -0.0007 | -0.0024 | 0.0010 | 0.7850 | no clear difference |
| market_spread_close | 3107 | 207 | -0.0002 | -0.0019 | 0.0014 | 0.5920 | no clear difference |
| D_market_full | 3107 | 207 | 0.0004 | -0.0012 | 0.0019 | 0.3115 | no clear difference |
| G_market_weighted | 3107 | 207 | 0.0010 | -0.0007 | 0.0029 | 0.1290 | no clear difference |
| G_market_equal | 3107 | 207 | 0.0017 | -0.0002 | 0.0036 | 0.0380 | no clear difference |
| G_market_stack | 3107 | 207 | 0.0026 | 0.0002 | 0.0053 | 0.0175 | worse (CI > 0) |
| A_qb_confirmed | 3107 | 207 | 0.0150 | 0.0096 | 0.0208 | 0.0000 | worse (CI > 0) |
| A_qb_injury | 3107 | 207 | 0.0182 | 0.0118 | 0.0248 | 0.0000 | worse (CI > 0) |
| G_free_equal | 3107 | 207 | 0.0186 | 0.0120 | 0.0256 | 0.0000 | worse (CI > 0) |
| G_free_weighted | 3107 | 207 | 0.0188 | 0.0123 | 0.0257 | 0.0000 | worse (CI > 0) |
| A_qb_weekstart | 3107 | 207 | 0.0190 | 0.0125 | 0.0256 | 0.0000 | worse (CI > 0) |
| G_free_stack | 3107 | 207 | 0.0192 | 0.0125 | 0.0260 | 0.0000 | worse (CI > 0) |
| E_bayes_plugin | 3107 | 207 | 0.0194 | 0.0130 | 0.0257 | 0.0000 | worse (CI > 0) |
| E_bayes | 3107 | 207 | 0.0194 | 0.0130 | 0.0258 | 0.0000 | worse (CI > 0) |
| challenger_elo | 3107 | 207 | 0.0214 | 0.0142 | 0.0281 | 0.0000 | worse (CI > 0) |
| C_situational | 3107 | 207 | 0.0216 | 0.0143 | 0.0283 | 0.0000 | worse (CI > 0) |
| C_base | 3107 | 207 | 0.0222 | 0.0157 | 0.0284 | 0.0000 | worse (CI > 0) |
| C_sit_weather | 3107 | 207 | 0.0229 | 0.0159 | 0.0296 | 0.0000 | worse (CI > 0) |
| B_drive_sim | 3107 | 207 | 0.0238 | 0.0167 | 0.0308 | 0.0000 | worse (CI > 0) |
| F_matchup_additive | 3107 | 207 | 0.0243 | 0.0177 | 0.0308 | 0.0000 | worse (CI > 0) |
| F_matchup_interaction | 3107 | 207 | 0.0255 | 0.0186 | 0.0321 | 0.0000 | worse (CI > 0) |
| logistic_pointdiff | 3107 | 207 | 0.0477 | 0.0380 | 0.0584 | 0.0000 | worse (CI > 0) |

## Paired log-loss difference vs `deadeye_line_only_proxy`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| market_spread_close | 3107 | 207 | 0.0005 | -0.0005 | 0.0014 | 0.1570 | no clear difference |
| market_ml_close | 3107 | 207 | 0.0007 | -0.0010 | 0.0024 | 0.2150 | no clear difference |
| D_market_full | 3107 | 207 | 0.0010 | -0.0005 | 0.0026 | 0.0865 | no clear difference |
| G_market_weighted | 3107 | 207 | 0.0017 | -0.0002 | 0.0038 | 0.0440 | no clear difference |
| G_market_equal | 3107 | 207 | 0.0023 | 0.0002 | 0.0046 | 0.0140 | worse (CI > 0) |
| G_market_stack | 3107 | 207 | 0.0033 | 0.0004 | 0.0063 | 0.0090 | worse (CI > 0) |
| A_qb_confirmed | 3107 | 207 | 0.0156 | 0.0096 | 0.0223 | 0.0000 | worse (CI > 0) |
| A_qb_injury | 3107 | 207 | 0.0188 | 0.0119 | 0.0261 | 0.0000 | worse (CI > 0) |
| G_free_equal | 3107 | 207 | 0.0193 | 0.0121 | 0.0267 | 0.0000 | worse (CI > 0) |
| G_free_weighted | 3107 | 207 | 0.0195 | 0.0124 | 0.0267 | 0.0000 | worse (CI > 0) |
| A_qb_weekstart | 3107 | 207 | 0.0197 | 0.0126 | 0.0268 | 0.0000 | worse (CI > 0) |
| G_free_stack | 3107 | 207 | 0.0198 | 0.0126 | 0.0272 | 0.0000 | worse (CI > 0) |
| E_bayes_plugin | 3107 | 207 | 0.0201 | 0.0131 | 0.0272 | 0.0000 | worse (CI > 0) |
| E_bayes | 3107 | 207 | 0.0201 | 0.0131 | 0.0272 | 0.0000 | worse (CI > 0) |
| challenger_elo | 3107 | 207 | 0.0220 | 0.0143 | 0.0294 | 0.0000 | worse (CI > 0) |
| C_situational | 3107 | 207 | 0.0223 | 0.0146 | 0.0297 | 0.0000 | worse (CI > 0) |
| C_base | 3107 | 207 | 0.0228 | 0.0158 | 0.0298 | 0.0000 | worse (CI > 0) |
| C_sit_weather | 3107 | 207 | 0.0236 | 0.0159 | 0.0311 | 0.0000 | worse (CI > 0) |
| B_drive_sim | 3107 | 207 | 0.0244 | 0.0165 | 0.0323 | 0.0000 | worse (CI > 0) |
| F_matchup_additive | 3107 | 207 | 0.0250 | 0.0178 | 0.0321 | 0.0000 | worse (CI > 0) |
| F_matchup_interaction | 3107 | 207 | 0.0262 | 0.0185 | 0.0336 | 0.0000 | worse (CI > 0) |
| logistic_pointdiff | 3107 | 207 | 0.0484 | 0.0382 | 0.0595 | 0.0000 | worse (CI > 0) |

## Paired log-loss difference vs `challenger_elo`

Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.

| model | n | weeks | diff | lo | hi | p_a_better | verdict |
|---|---|---|---|---|---|---|---|
| deadeye_line_only_proxy | 3107 | 207 | -0.0220 | -0.0294 | -0.0143 | 1.0000 | better (CI < 0) |
| market_spread_close | 3107 | 207 | -0.0215 | -0.0289 | -0.0141 | 1.0000 | better (CI < 0) |
| market_ml_close | 3107 | 207 | -0.0214 | -0.0281 | -0.0142 | 1.0000 | better (CI < 0) |
| D_market_full | 3107 | 207 | -0.0210 | -0.0280 | -0.0136 | 1.0000 | better (CI < 0) |
| G_market_weighted | 3107 | 207 | -0.0204 | -0.0273 | -0.0131 | 1.0000 | better (CI < 0) |
| G_market_equal | 3107 | 207 | -0.0197 | -0.0265 | -0.0126 | 1.0000 | better (CI < 0) |
| G_market_stack | 3107 | 207 | -0.0187 | -0.0257 | -0.0113 | 1.0000 | better (CI < 0) |
| A_qb_confirmed | 3107 | 207 | -0.0064 | -0.0126 | -0.0001 | 0.9755 | better (CI < 0) |
| A_qb_injury | 3107 | 207 | -0.0032 | -0.0095 | 0.0027 | 0.8505 | no clear difference |
| G_free_equal | 3107 | 207 | -0.0027 | -0.0073 | 0.0017 | 0.8905 | no clear difference |
| G_free_weighted | 3107 | 207 | -0.0025 | -0.0072 | 0.0019 | 0.8695 | no clear difference |
| A_qb_weekstart | 3107 | 207 | -0.0024 | -0.0085 | 0.0035 | 0.7805 | no clear difference |
| G_free_stack | 3107 | 207 | -0.0022 | -0.0067 | 0.0021 | 0.8440 | no clear difference |
| E_bayes_plugin | 3107 | 207 | -0.0020 | -0.0058 | 0.0017 | 0.8505 | no clear difference |
| E_bayes | 3107 | 207 | -0.0019 | -0.0058 | 0.0017 | 0.8500 | no clear difference |
| C_situational | 3107 | 207 | 0.0003 | -0.0052 | 0.0055 | 0.4610 | no clear difference |
| C_base | 3107 | 207 | 0.0008 | -0.0038 | 0.0052 | 0.3590 | no clear difference |
| C_sit_weather | 3107 | 207 | 0.0015 | -0.0040 | 0.0070 | 0.2940 | no clear difference |
| B_drive_sim | 3107 | 207 | 0.0024 | -0.0029 | 0.0074 | 0.1765 | no clear difference |
| F_matchup_additive | 3107 | 207 | 0.0030 | -0.0020 | 0.0079 | 0.1255 | no clear difference |
| F_matchup_interaction | 3107 | 207 | 0.0042 | -0.0010 | 0.0093 | 0.0580 | no clear difference |
| logistic_pointdiff | 3107 | 207 | 0.0264 | 0.0170 | 0.0356 | 0.0000 | worse (CI > 0) |

**Multiple comparisons.** 66 paired log-loss comparisons are reported here (plus Brier versions). At 95% about one in twenty intervals excludes zero by chance alone, so an isolated 'better' or 'worse' among many should not be read as a finding without replication on the holdout.

## Log loss by season

| season | market_ml_close | deadeye_line_only_proxy | D_market_full | G_market_stack | G_free_stack | G_free_equal | A_qb_confirmed | A_qb_weekstart | E_bayes | C_situational | B_drive_sim | challenger_elo | F_matchup_interaction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2012 | 0.6001 | 0.5970 | 0.6003 | 0.6003 | 0.6217 | 0.6222 | 0.6157 | 0.6140 | 0.6223 | 0.6268 | 0.6283 | 0.6247 | 0.6268 |
| 2013 | 0.5923 | 0.5911 | 0.5941 | 0.5928 | 0.6119 | 0.6083 | 0.6152 | 0.6196 | 0.6129 | 0.6064 | 0.6143 | 0.6228 | 0.6284 |
| 2014 | 0.6023 | 0.6025 | 0.6023 | 0.6017 | 0.6020 | 0.5998 | 0.6086 | 0.6120 | 0.5968 | 0.6103 | 0.6125 | 0.6005 | 0.6050 |
| 2015 | 0.6521 | 0.6536 | 0.6491 | 0.6496 | 0.6419 | 0.6441 | 0.6412 | 0.6461 | 0.6441 | 0.6483 | 0.6496 | 0.6428 | 0.6575 |
| 2016 | 0.6288 | 0.6288 | 0.6296 | 0.6315 | 0.6394 | 0.6394 | 0.6504 | 0.6519 | 0.6396 | 0.6476 | 0.6429 | 0.6301 | 0.6532 |
| 2017 | 0.5856 | 0.5823 | 0.5844 | 0.6095 | 0.6200 | 0.6200 | 0.6162 | 0.6260 | 0.6179 | 0.6218 | 0.6226 | 0.6200 | 0.6264 |
| 2018 | 0.6111 | 0.6100 | 0.6106 | 0.6139 | 0.6313 | 0.6313 | 0.6254 | 0.6240 | 0.6171 | 0.6148 | 0.6228 | 0.6333 | 0.6231 |
| 2019 | 0.6136 | 0.6134 | 0.6165 | 0.6190 | 0.6365 | 0.6331 | 0.6220 | 0.6309 | 0.6344 | 0.6360 | 0.6349 | 0.6335 | 0.6338 |
| 2020 | 0.5901 | 0.5891 | 0.5915 | 0.5885 | 0.6275 | 0.6276 | 0.6138 | 0.6163 | 0.6304 | 0.6339 | 0.6342 | 0.6218 | 0.6324 |
| 2021 | 0.6216 | 0.6272 | 0.6237 | 0.6218 | 0.6447 | 0.6441 | 0.6329 | 0.6377 | 0.6536 | 0.6540 | 0.6499 | 0.6568 | 0.6533 |
| 2022 | 0.6085 | 0.6070 | 0.6095 | 0.6082 | 0.6364 | 0.6365 | 0.6339 | 0.6360 | 0.6432 | 0.6452 | 0.6512 | 0.6404 | 0.6451 |
| 2023 | 0.6273 | 0.6234 | 0.6266 | 0.6289 | 0.6493 | 0.6495 | 0.6381 | 0.6464 | 0.6523 | 0.6467 | 0.6538 | 0.6609 | 0.6538 |

## Early vs late season (log loss)

| phase | market_ml_close | deadeye_line_only_proxy | D_market_full | G_market_stack | G_free_stack | G_free_equal | A_qb_confirmed | A_qb_weekstart | E_bayes | C_situational | B_drive_sim | challenger_elo | F_matchup_interaction |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| weeks 1-4 | 0.6363 | 0.6383 | 0.6376 | 0.6360 | 0.6434 | 0.6423 | 0.6512 | 0.6535 | 0.6468 | 0.6512 | 0.6507 | 0.6463 | 0.6552 |
| weeks 10-18 | 0.6001 | 0.5973 | 0.5993 | 0.6059 | 0.6278 | 0.6273 | 0.6177 | 0.6233 | 0.6262 | 0.6272 | 0.6314 | 0.6298 | 0.6299 |
| weeks 5-9 | 0.6089 | 0.6097 | 0.6105 | 0.6086 | 0.6235 | 0.6234 | 0.6193 | 0.6220 | 0.6244 | 0.6268 | 0.6276 | 0.6254 | 0.6327 |

## Does explicit uncertainty help? (E_bayes vs E_bayes_plugin)

Same filter, same means; E_bayes widens each forecast by its posterior state variance, the plug-in uses a fixed spread. Negative = uncertainty helps.

| phase | n | diff | lo | hi | p_a_better |
|---|---|---|---|---|---|
| weeks 1-4 | 752 | -0.00005 | -0.00075 | 0.00065 | 0.53400 |
| weeks 5-9 | 846 | 0.00018 | -0.00030 | 0.00066 | 0.23050 |
| weeks 10-18 | 1509 | -0.00003 | -0.00031 | 0.00023 | 0.56200 |
| all | 3107 | 0.00002 | -0.00022 | 0.00028 | 0.42700 |

## Favourite / underdog picks (straight-up accuracy)

How often each model's pick is the closing-market favourite, and how often it is right when it is and isn't.

| model | picks_market_fav | acc_when_fav | picks_market_dog | acc_when_dog |
|---|---|---|---|---|
| A_qb_confirmed | 2698 | 0.679 | 417 | 0.460 |
| A_qb_weekstart | 2648 | 0.676 | 467 | 0.428 |
| B_drive_sim | 2651 | 0.677 | 464 | 0.438 |
| C_situational | 2685 | 0.672 | 430 | 0.412 |
| D_market_full | 3104 | 0.660 | 11 | 0.455 |
| E_bayes | 2684 | 0.674 | 431 | 0.429 |
| F_matchup_interaction | 2677 | 0.669 | 438 | 0.400 |
| G_free_equal | 2691 | 0.671 | 424 | 0.415 |
| G_free_stack | 2693 | 0.672 | 422 | 0.417 |
| G_market_stack | 3044 | 0.662 | 71 | 0.437 |
| challenger_elo | 2621 | 0.678 | 494 | 0.437 |
| deadeye_line_only_proxy | 3115 | 0.659 | 0 |  |
| market_ml_close | 3087 | 0.661 | 28 | 0.571 |

## Reliability (said vs came, by probability band)

**market_ml_close**

| band | n | said | came |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.097 | 0.000 |
| 0.1-0.2 | 57 | 0.163 | 0.193 |
| 0.2-0.3 | 226 | 0.256 | 0.210 |
| 0.3-0.4 | 405 | 0.354 | 0.374 |
| 0.4-0.5 | 446 | 0.447 | 0.436 |
| 0.5-0.6 | 526 | 0.553 | 0.544 |
| 0.6-0.7 | 658 | 0.648 | 0.621 |
| 0.7-0.8 | 564 | 0.749 | 0.769 |
| 0.8-0.9 | 214 | 0.842 | 0.853 |
| 0.9-1.0 | 20 | 0.918 | 0.950 |

**E_bayes**

| band | n | said | came |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.090 | 0.333 |
| 0.1-0.2 | 30 | 0.166 | 0.133 |
| 0.2-0.3 | 170 | 0.260 | 0.318 |
| 0.3-0.4 | 340 | 0.361 | 0.341 |
| 0.4-0.5 | 574 | 0.451 | 0.435 |
| 0.5-0.6 | 732 | 0.548 | 0.538 |
| 0.6-0.7 | 642 | 0.647 | 0.667 |
| 0.7-0.8 | 444 | 0.744 | 0.743 |
| 0.8-0.9 | 164 | 0.840 | 0.851 |
| 0.9-1.0 | 20 | 0.919 | 0.900 |

**G_free_stack**

| band | n | said | came |
|---|---|---|---|
| 0.0-0.1 | 3 | 0.076 | 0.333 |
| 0.1-0.2 | 53 | 0.166 | 0.283 |
| 0.2-0.3 | 183 | 0.258 | 0.260 |
| 0.3-0.4 | 353 | 0.357 | 0.354 |
| 0.4-0.5 | 523 | 0.452 | 0.456 |
| 0.5-0.6 | 684 | 0.552 | 0.523 |
| 0.6-0.7 | 622 | 0.647 | 0.673 |
| 0.7-0.8 | 460 | 0.747 | 0.714 |
| 0.8-0.9 | 213 | 0.839 | 0.840 |
| 0.9-1.0 | 25 | 0.921 | 0.920 |

**B_drive_sim**

| band | n | said | came |
|---|---|---|---|
| 0.1-0.2 | 13 | 0.172 | 0.154 |
| 0.2-0.3 | 99 | 0.264 | 0.263 |
| 0.3-0.4 | 344 | 0.358 | 0.315 |
| 0.4-0.5 | 696 | 0.453 | 0.435 |
| 0.5-0.6 | 881 | 0.548 | 0.573 |
| 0.6-0.7 | 694 | 0.646 | 0.677 |
| 0.7-0.8 | 329 | 0.741 | 0.798 |
| 0.8-0.9 | 63 | 0.832 | 0.913 |

## ACQL cards under the repository's rules

One point per correct pick; favourites of 6.5+ carry a pool line `max(7, floor(spread)+1)` and must win by `ceil(line)` (acql.model.backtest.pool_line, acql.analytics.line_need). Pool lines are **reconstructed from the closing spread** for every season; the repository records one ruleset, applied throughout. Intervals resample whole weeks.

| model | weeks | total | per_week | sd_week | vs deadeye_line_only_proxy /wk | 95% CI (deadeye_line_only_proxy) | vs market_ml_close /wk | 95% CI (market_ml_close) |
|---|---|---|---|---|---|---|---|---|
| market_ml_close | 207 | 1762 | 8.512 | 1.898 | 0.005 | [-0.04, +0.06] |  |  |
| deadeye_line_only_proxy | 207 | 1761 | 8.507 | 1.918 |  |  | -0.005 | [-0.06, +0.04] |
| market_spread_close | 207 | 1761 | 8.507 | 1.918 | 0.000 | [+0.00, +0.00] | -0.005 | [-0.06, +0.04] |
| D_market_full | 207 | 1760 | 8.502 | 1.898 | -0.005 | [-0.03, +0.02] | -0.010 | [-0.07, +0.05] |
| A_qb_confirmed | 207 | 1740 | 8.406 | 1.923 | -0.101 | [-0.35, +0.15] | -0.106 | [-0.35, +0.14] |
| G_market_equal | 207 | 1726 | 8.338 | 1.939 | -0.169 | [-0.44, +0.11] | -0.174 | [-0.44, +0.09] |
| G_market_weighted | 207 | 1721 | 8.314 | 1.974 | -0.193 | [-0.46, +0.08] | -0.198 | [-0.47, +0.08] |
| challenger_elo | 207 | 1721 | 8.314 | 1.886 | -0.193 | [-0.45, +0.06] | -0.198 | [-0.46, +0.04] |
| G_market_stack | 207 | 1718 | 8.300 | 1.948 | -0.208 | [-0.49, +0.07] | -0.213 | [-0.49, +0.07] |
| A_qb_injury | 207 | 1712 | 8.271 | 1.996 | -0.237 | [-0.50, +0.02] | -0.242 | [-0.51, +0.02] |
| A_qb_weekstart | 207 | 1710 | 8.261 | 1.971 | -0.246 | [-0.51, +0.01] | -0.251 | [-0.51, +0.00] |
| B_drive_sim | 207 | 1710 | 8.261 | 1.980 | -0.246 | [-0.47, -0.01] | -0.251 | [-0.48, -0.01] |
| E_bayes | 207 | 1701 | 8.217 | 2.009 | -0.290 | [-0.55, -0.04] | -0.295 | [-0.55, -0.04] |
| E_bayes_plugin | 207 | 1701 | 8.217 | 2.009 | -0.290 | [-0.55, -0.04] | -0.295 | [-0.55, -0.04] |
| C_situational | 207 | 1687 | 8.150 | 2.065 | -0.357 | [-0.61, -0.10] | -0.362 | [-0.61, -0.10] |
| G_free_equal | 207 | 1686 | 8.145 | 2.066 | -0.362 | [-0.65, -0.09] | -0.367 | [-0.65, -0.09] |
| G_free_stack | 207 | 1683 | 8.130 | 2.097 | -0.377 | [-0.66, -0.10] | -0.382 | [-0.67, -0.10] |
| C_base | 207 | 1682 | 8.126 | 2.051 | -0.382 | [-0.65, -0.14] | -0.386 | [-0.65, -0.14] |
| G_free_weighted | 207 | 1679 | 8.111 | 2.095 | -0.396 | [-0.68, -0.13] | -0.401 | [-0.68, -0.12] |
| C_sit_weather | 207 | 1678 | 8.106 | 2.050 | -0.401 | [-0.66, -0.15] | -0.406 | [-0.67, -0.15] |
| F_matchup_additive | 207 | 1668 | 8.058 | 2.061 | -0.449 | [-0.71, -0.20] | -0.454 | [-0.72, -0.21] |
| F_matchup_interaction | 207 | 1664 | 8.039 | 2.002 | -0.469 | [-0.72, -0.23] | -0.473 | [-0.72, -0.24] |
| logistic_pointdiff | 207 | 1656 | 8.000 | 1.862 | -0.507 | [-0.78, -0.26] | -0.512 | [-0.78, -0.27] |

### ACQL points by season

| season | A_qb_confirmed | A_qb_weekstart | B_drive_sim | C_situational | D_market_full | E_bayes | F_matchup_interaction | G_free_equal | G_free_stack | G_market_stack | challenger_elo | deadeye_line_only_proxy | market_ml_close |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2012 | 143 | 143 | 132 | 138 | 141 | 133 | 134 | 129 | 132 | 133 | 138 | 141 | 141 |
| 2013 | 151 | 141 | 150 | 152 | 156 | 152 | 144 | 155 | 152 | 159 | 146 | 156 | 157 |
| 2014 | 150 | 146 | 148 | 138 | 144 | 153 | 140 | 140 | 139 | 139 | 152 | 144 | 143 |
| 2015 | 140 | 139 | 142 | 143 | 145 | 134 | 135 | 133 | 139 | 138 | 151 | 145 | 144 |
| 2016 | 129 | 132 | 136 | 126 | 136 | 129 | 128 | 130 | 129 | 144 | 143 | 137 | 138 |
| 2017 | 142 | 142 | 149 | 144 | 147 | 152 | 146 | 145 | 145 | 148 | 153 | 147 | 150 |
| 2018 | 148 | 141 | 138 | 144 | 149 | 141 | 144 | 139 | 139 | 138 | 136 | 149 | 149 |
| 2019 | 141 | 140 | 136 | 140 | 140 | 134 | 136 | 136 | 132 | 137 | 142 | 140 | 140 |
| 2020 | 140 | 150 | 133 | 127 | 139 | 139 | 136 | 136 | 133 | 135 | 133 | 139 | 140 |
| 2021 | 146 | 135 | 141 | 128 | 135 | 135 | 122 | 134 | 134 | 135 | 129 | 135 | 135 |
| 2022 | 156 | 152 | 152 | 153 | 161 | 143 | 150 | 155 | 155 | 144 | 152 | 161 | 159 |
| 2023 | 154 | 149 | 153 | 154 | 167 | 156 | 149 | 154 | 154 | 168 | 146 | 167 | 166 |

## Ensemble (Model G): what was chosen

Components were selected each season by forward selection on earlier seasons' out-of-fold forecasts (walk-forward validation on the last 3 training seasons; a component joins only if it lowers validation log loss by 0.0005).

| season | ensemble | chosen |
|---|---|---|
| 2012 | G_free_equal | E_bayes, C_situational |
| 2012 | G_free_weighted | E_bayes, C_situational |
| 2012 | G_free_stack | E_bayes, C_situational |
| 2013 | G_free_equal | E_bayes, A_qb_weekstart, C_situational |
| 2013 | G_free_weighted | E_bayes, A_qb_weekstart, C_situational |
| 2013 | G_free_stack | E_bayes, A_qb_weekstart |
| 2014 | G_free_equal | E_bayes, A_qb_weekstart, C_situational |
| 2014 | G_free_weighted | E_bayes, A_qb_weekstart, C_situational |
| 2014 | G_free_stack | E_bayes, A_qb_weekstart, F_matchup_additive, C_situational |
| 2015 | G_free_equal | E_bayes, A_qb_weekstart |
| 2015 | G_free_weighted | E_bayes, A_qb_weekstart |
| 2015 | G_free_stack | E_bayes, A_qb_weekstart, F_matchup_additive |
| 2016 | G_free_equal | E_bayes |
| 2016 | G_free_weighted | E_bayes, C_situational |
| 2016 | G_free_stack | E_bayes |
| 2017 | G_free_equal | challenger_elo |
| 2017 | G_free_weighted | challenger_elo |
| 2017 | G_free_stack | challenger_elo |
| 2018 | G_free_equal | challenger_elo |
| 2018 | G_free_weighted | challenger_elo |
| 2018 | G_free_stack | challenger_elo |
| 2019 | G_free_equal | E_bayes, B_drive_sim |
| 2019 | G_free_weighted | E_bayes, B_drive_sim |
| 2019 | G_free_stack | E_bayes |
| 2020 | G_free_equal | B_drive_sim, C_situational |
| 2020 | G_free_weighted | B_drive_sim, C_situational |
| 2020 | G_free_stack | B_drive_sim, C_situational |
| 2021 | G_free_equal | A_qb_weekstart, B_drive_sim |
| 2021 | G_free_weighted | A_qb_weekstart, B_drive_sim |
| 2021 | G_free_stack | A_qb_weekstart, B_drive_sim |
| 2022 | G_free_equal | A_qb_weekstart |
| 2022 | G_free_weighted | A_qb_weekstart |
| 2022 | G_free_stack | A_qb_weekstart |
| 2023 | G_free_equal | A_qb_weekstart |
| 2023 | G_free_weighted | A_qb_weekstart |
| 2023 | G_free_stack | A_qb_weekstart |
| 2012 | G_market_equal | market_ml_close |
| 2012 | G_market_weighted | market_ml_close |
| 2012 | G_market_stack | market_ml_close |
| 2013 | G_market_equal | market_ml_close |
| 2013 | G_market_weighted | market_ml_close |
| 2013 | G_market_stack | market_ml_close |
| 2014 | G_market_equal | market_ml_close |
| 2014 | G_market_weighted | market_ml_close |
| 2014 | G_market_stack | market_ml_close |
| 2015 | G_market_equal | D_market_full |
| 2015 | G_market_weighted | D_market_full |
| 2015 | G_market_stack | D_market_full, A_qb_confirmed |
| 2016 | G_market_equal | D_market_full, E_bayes, A_qb_confirmed |
| 2016 | G_market_weighted | D_market_full, E_bayes, A_qb_confirmed |
| 2016 | G_market_stack | D_market_full, A_qb_confirmed |
| 2017 | G_market_equal | challenger_elo, D_market_full |
| 2017 | G_market_weighted | challenger_elo, D_market_full |
| 2017 | G_market_stack | challenger_elo, A_qb_confirmed, F_matchup_additive |
| 2018 | G_market_equal | D_market_full, challenger_elo, market_ml_close |
| 2018 | G_market_weighted | D_market_full, challenger_elo |
| 2018 | G_market_stack | D_market_full, challenger_elo, F_matchup_additive, A_qb_confirmed |
| 2019 | G_market_equal | D_market_full |
| 2019 | G_market_weighted | D_market_full |
| 2019 | G_market_stack | D_market_full |
| 2020 | G_market_equal | market_ml_close |
| 2020 | G_market_weighted | market_ml_close |
| 2020 | G_market_stack | market_ml_close |
| 2021 | G_market_equal | market_ml_close |
| 2021 | G_market_weighted | market_ml_close |
| 2021 | G_market_stack | market_ml_close |
| 2022 | G_market_equal | market_ml_close |
| 2022 | G_market_weighted | market_ml_close |
| 2022 | G_market_stack | market_ml_close, F_matchup_additive, A_qb_weekstart |
| 2023 | G_market_equal | market_ml_close |
| 2023 | G_market_weighted | market_ml_close |
| 2023 | G_market_stack | market_ml_close, F_matchup_interaction, A_qb_weekstart, logistic_pointdiff |

### Error correlation (market-free components)

Correlation of (forecast - outcome) across games. High correlation = little to gain from combining.

| component | A_qb_weekstart | B_drive_sim | C_situational | E_bayes | F_matchup_additive | F_matchup_interaction | challenger_elo | logistic_pointdiff |
|---|---|---|---|---|---|---|---|---|
| A_qb_weekstart | 1.00 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.98 |
| B_drive_sim | 0.99 | 1.00 | 1.00 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 |
| C_situational | 0.99 | 1.00 | 1.00 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 |
| E_bayes | 0.99 | 0.99 | 0.99 | 1.00 | 1.00 | 0.99 | 0.99 | 0.98 |
| F_matchup_additive | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 |
| F_matchup_interaction | 0.99 | 1.00 | 1.00 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 |
| challenger_elo | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 1.00 | 0.97 |
| logistic_pointdiff | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 0.97 | 1.00 |

### Incremental value given all other market-free components

Walk-forward logistic stack with vs without the component (negative = it adds information).

| component | n | with_minus_without | lo | hi | p_adds |
|---|---|---|---|---|---|
| A_qb_weekstart | 3107 | -0.00273 | -0.00482 | -0.00072 | 0.99550 |
| F_matchup_additive | 3107 | -0.00052 | -0.00140 | 0.00032 | 0.89250 |
| C_situational | 3107 | -0.00018 | -0.00135 | 0.00096 | 0.63200 |
| challenger_elo | 3107 | -0.00016 | -0.00106 | 0.00078 | 0.62550 |
| B_drive_sim | 3107 | 0.00003 | -0.00046 | 0.00052 | 0.46050 |
| F_matchup_interaction | 3107 | 0.00013 | -0.00014 | 0.00038 | 0.16050 |
| E_bayes | 3107 | 0.00014 | -0.00097 | 0.00125 | 0.39400 |
| logistic_pointdiff | 3107 | 0.00021 | -0.00010 | 0.00059 | 0.11000 |

### Error correlation (market-informed components)

Correlation of (forecast - outcome) across games. High correlation = little to gain from combining.

| component | A_qb_confirmed | A_qb_weekstart | B_drive_sim | C_sit_weather | C_situational | D_market_full | E_bayes | F_matchup_additive | F_matchup_interaction | challenger_elo | logistic_pointdiff | market_ml_close |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_qb_confirmed | 1.00 | 1.00 | 0.99 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 0.98 | 0.97 | 0.98 |
| A_qb_weekstart | 1.00 | 1.00 | 0.99 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 0.99 | 0.98 | 0.98 |
| B_drive_sim | 0.99 | 0.99 | 1.00 | 0.99 | 1.00 | 0.98 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| C_sit_weather | 0.99 | 0.99 | 0.99 | 1.00 | 1.00 | 0.98 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| C_situational | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| D_market_full | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 1.00 | 0.98 | 0.98 | 0.98 | 0.98 | 0.96 | 1.00 |
| E_bayes | 0.99 | 0.99 | 0.99 | 0.99 | 0.99 | 0.98 | 1.00 | 1.00 | 0.99 | 0.99 | 0.98 | 0.98 |
| F_matchup_additive | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 1.00 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| F_matchup_interaction | 0.99 | 0.99 | 1.00 | 1.00 | 1.00 | 0.98 | 0.99 | 1.00 | 1.00 | 0.99 | 0.98 | 0.98 |
| challenger_elo | 0.98 | 0.99 | 0.99 | 0.99 | 0.99 | 0.98 | 0.99 | 0.99 | 0.99 | 1.00 | 0.97 | 0.98 |
| logistic_pointdiff | 0.97 | 0.98 | 0.98 | 0.98 | 0.98 | 0.96 | 0.98 | 0.98 | 0.98 | 0.97 | 1.00 | 0.97 |
| market_ml_close | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 | 1.00 | 0.98 | 0.98 | 0.98 | 0.98 | 0.97 | 1.00 |

### Incremental value given all other market-informed components

Walk-forward logistic stack with vs without the component (negative = it adds information).

| component | n | with_minus_without | lo | hi | p_adds |
|---|---|---|---|---|---|
| market_ml_close | 3107 | -0.00048 | -0.00137 | 0.00040 | 0.83950 |
| F_matchup_additive | 3107 | -0.00044 | -0.00145 | 0.00047 | 0.82900 |
| logistic_pointdiff | 3107 | -0.00024 | -0.00068 | 0.00017 | 0.86900 |
| D_market_full | 3107 | -0.00005 | -0.00066 | 0.00060 | 0.55800 |
| C_situational | 3107 | 0.00000 | -0.00025 | 0.00024 | 0.50750 |
| C_sit_weather | 3107 | 0.00002 | -0.00010 | 0.00015 | 0.39450 |
| A_qb_weekstart | 3107 | 0.00005 | -0.00026 | 0.00035 | 0.37900 |
| F_matchup_interaction | 3107 | 0.00006 | -0.00025 | 0.00037 | 0.35100 |
| A_qb_confirmed | 3107 | 0.00009 | -0.00038 | 0.00059 | 0.36500 |
| E_bayes | 3107 | 0.00015 | -0.00049 | 0.00082 | 0.32600 |
| B_drive_sim | 3107 | 0.00015 | -0.00018 | 0.00048 | 0.18850 |
| challenger_elo | 3107 | 0.00024 | -0.00029 | 0.00079 | 0.18200 |

## Signal discovery: feature-family ablations

Each row compares two walk-forward logistic regressions on identical games (penalty fixed in advance). `diff` = log loss with the family minus without; negative = the family adds information. Every run is in `research_lab/experiments/registry.jsonl`, including failures.

| family | comparison | n | ll_with | ll_without | diff | lo | hi | p_improves | verdict |
|---|---|---|---|---|---|---|---|---|---|
| qb_weekstart | market + family vs market | 3107.0000 | 0.6128 | 0.6115 | 0.0014 | -0.0004 | 0.0031 | 0.0670 | no clear effect |
| qb_weekstart | football + family vs football | 3107.0000 | 0.6283 | 0.6310 | -0.0027 | -0.0058 | 0.0005 | 0.9490 | no clear effect |
| qb_weekstart | full vs full without family | 3107.0000 | 0.6208 | 0.6198 | 0.0010 | -0.0006 | 0.0025 | 0.1185 | no clear effect |
| qb_confirmed | market + family vs market | 3107.0000 | 0.6126 | 0.6115 | 0.0011 | -0.0008 | 0.0030 | 0.1435 | no clear effect |
| qb_confirmed | football + family vs football | 3107.0000 | 0.6239 | 0.6310 | -0.0071 | -0.0117 | -0.0022 | 0.9980 | adds (CI < 0) |
| qb_confirmed | full vs full without family | 3107.0000 | 0.6208 | 0.6198 | 0.0010 | -0.0008 | 0.0026 | 0.1295 | no clear effect |
| rest_travel | market + family vs market | 3107.0000 | 0.6136 | 0.6115 | 0.0021 | -0.0006 | 0.0047 | 0.0695 | no clear effect |
| rest_travel | football + family vs football | 3107.0000 | 0.6330 | 0.6310 | 0.0020 | -0.0010 | 0.0050 | 0.1020 | no clear effect |
| rest_travel | full vs full without family | 3107.0000 | 0.6208 | 0.6188 | 0.0020 | -0.0008 | 0.0048 | 0.0780 | no clear effect |
| environment | market + family vs market | 3107.0000 | 0.6131 | 0.6115 | 0.0016 | 0.0002 | 0.0032 | 0.0135 | hurts (CI > 0) |
| environment | football + family vs football | 3107.0000 | 0.6326 | 0.6310 | 0.0016 | 0.0001 | 0.0034 | 0.0200 | hurts (CI > 0) |
| environment | full vs full without family | 3107.0000 | 0.6208 | 0.6190 | 0.0018 | 0.0006 | 0.0032 | 0.0020 | hurts (CI > 0) |
| tactical | market + family vs market | 3107.0000 | 0.6157 | 0.6115 | 0.0042 | 0.0019 | 0.0065 | 0.0000 | hurts (CI > 0) |
| tactical | football + family vs football | 3107.0000 | 0.6350 | 0.6310 | 0.0040 | 0.0017 | 0.0064 | 0.0000 | hurts (CI > 0) |
| tactical | full vs full without family | 3107.0000 | 0.6208 | 0.6171 | 0.0037 | 0.0014 | 0.0062 | 0.0015 | hurts (CI > 0) |
| team_strength | market + family vs market | 3107.0000 | 0.6120 | 0.6115 | 0.0005 | -0.0006 | 0.0016 | 0.1830 | no clear effect |
| team_strength | full vs full without family | 3107.0000 | 0.6208 | 0.6209 | -0.0001 | -0.0012 | 0.0010 | 0.5735 | no clear effect |
| drive_sim | market + family vs market | 3107.0000 | 0.6117 | 0.6115 | 0.0002 | -0.0005 | 0.0010 | 0.2630 | no clear effect |
| drive_sim | football + family vs football | 3107.0000 | 0.6307 | 0.6310 | -0.0003 | -0.0012 | 0.0006 | 0.7315 | no clear effect |
| drive_sim | full vs full without family | 3107.0000 | 0.6208 | 0.6207 | 0.0001 | -0.0003 | 0.0004 | 0.3530 | no clear effect |
| unit_ratings | market + family vs market | 3107.0000 | 0.6114 | 0.6115 | -0.0001 | -0.0004 | 0.0003 | 0.7230 | no clear effect |
| unit_ratings | football + family vs football | 3107.0000 | 0.6312 | 0.6310 | 0.0002 | -0.0002 | 0.0006 | 0.1410 | no clear effect |
| unit_ratings | full vs full without family | 3107.0000 | 0.6208 | 0.6217 | -0.0009 | -0.0020 | 0.0003 | 0.9315 | no clear effect |
| market_detail | market + family vs market | 3107.0000 | 0.6115 | 0.6115 | 0.0000 | -0.0014 | 0.0014 | 0.4640 | no clear effect |
| market_detail | football + family vs football | 3107.0000 | 0.6260 | 0.6310 | -0.0049 | -0.0085 | -0.0013 | 0.9970 | adds (CI < 0) |
| market_detail | full vs full without family | 3107.0000 | 0.6208 | 0.6210 | -0.0002 | -0.0015 | 0.0011 | 0.5860 | no clear effect |

### Not run (no usable historical data)

| family | note |
|---|---|
| market_movement | no historical opening lines or timestamped odds in any accessible source (nflverse keeps closing numbers only; The Odds API history needs a paid key) |
| cross_book | no per-sportsbook historical quotes accessible |
| weather_forecast | no archived pre-game weather forecasts before 2022 accessible; observed weather used as an upper bound instead |

## Model B validation (drive simulation)

Seasons 2021-2023, 815 games, 4000 simulations each.

PIT deciles (count of real outcomes falling in each tenth of their own simulated distribution; uniform would be about 82 each):

| decile | margin | total |
|---|---|---|
| 1 | 59 | 70 |
| 2 | 59 | 112 |
| 3 | 88 | 102 |
| 4 | 95 | 90 |
| 5 | 109 | 96 |
| 6 | 104 | 80 |
| 7 | 76 | 75 |
| 8 | 75 | 70 |
| 9 | 57 | 68 |
| 10 | 93 | 52 |

Share of games ending on key margins:

| abs margin | simulated | real |
|---|---|---|
| 0 | 0.0059 | 0.0037 |
| 3 | 0.0810 | 0.1485 |
| 7 | 0.0890 | 0.0724 |
| 10 | 0.0579 | 0.0503 |
| 14 | 0.0494 | 0.0515 |

Totals: simulated mean 46.7 vs real 44.4; simulated spread within a game 15.1 vs real spread around the simulated mean 13.6.

Convergence (home win chance for the same six games as draws increase):

| n | g1 | g2 | g3 | g4 | g5 | g6 |
|---|---|---|---|---|---|---|
| 250 | 0.8040 | 0.5480 | 0.7180 | 0.5260 | 0.3680 | 0.7100 |
| 1000 | 0.8160 | 0.5210 | 0.6845 | 0.5280 | 0.4295 | 0.6965 |
| 4000 | 0.8206 | 0.5331 | 0.6719 | 0.5170 | 0.4364 | 0.6746 |
| 16000 | 0.8251 | 0.5309 | 0.6760 | 0.5196 | 0.4398 | 0.6754 |

Monte Carlo standard error at N=4000 is at most 0.0079. The simulated games are a single forecast each; they are never used as training rows.
