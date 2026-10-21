# Challenger vs Deadeye: results

Summary of the generated reports `challenger/results/dev/REPORT.md` and
`challenger/results/holdout/REPORT.md` (every number below is copied from those files and their
CSVs; rerun `python -m challenger evaluate --split dev|holdout` to regenerate them).

**All of this is a retrospective backtest.** Challenger's historical forecasts were produced today,
walk-forward, from today's nflverse files. No Deadeye forecast recorded at the time exists for any of
these seasons. The only prospective evidence is the 2026 week 7 shadow journal (section 6), whose
games have not been played yet.

## 0. Bottom line

1. **Against Deadeye's own historical proxy** (the rating model Deadeye's backtest uses), Challenger
   **tied in development (2010-2019)** and **was better on the untouched holdout (2020-2026)**: log loss
   0.6340 vs 0.6413, difference -0.0073 [95% CI -0.0131, -0.0015], Brier -0.0030 [-0.0055, -0.0003],
   accuracy +0.2 points [-1.4, +1.9] (not significant). Six of seven holdout seasons favoured
   Challenger by point estimate. The proxy's constants were fitted on 2011-2019, so the development
   comparison flatters it; on the holdout both models are out of sample.
2. **Against Deadeye as it actually runs** - the betting line plus a share of the computer-model
   consensus - Challenger **loses clearly**. Deadeye's curve on the closing spread alone (its live
   engine with the model share set to zero) beat Challenger by 0.0263 log loss [0.0178, 0.0350] on
   the holdout and 0.0144 [0.0067, 0.0217] in development, and picked 2.9 points more winners on
   the holdout. The full live rule could only be reconstructed for 46 games (2026 weeks 3-5): too few
   to say anything.
3. **Against the market**, every market-free model loses by a wide, significant margin in both
   periods (holdout: Challenger 0.6340 vs de-vigged closing moneyline 0.6082). Part of that gap is
   the closing line's later information; most of it is the market simply being better.
4. **ACQL scoring (actual rules)**, reconstructed pool lines: on the holdout Challenger scored 8.34
   points a week vs the Deadeye proxy's 8.17 (+0.17 [-0.18, +0.50], not significant) and the closing
   line's 8.82 (-0.48 [-0.84, -0.09]). On the eight real pick sheets, Challenger scored 69 points to
   the proxy's 75, the market card's 84 and the Deadeye-curve card's 85 (the field's average coach:
   66.7) - eight weeks is noise.
5. **The most complicated model was not the best.** In development the stack beat gradient boosting
   (-0.0057 [-0.0103, -0.0012]) and was within noise of plain logistic regression and Elo; on the
   holdout the stack, boosting and logistic were all within noise of each other.

**Verdict.** Challenger works as an experiment - independent, reproducible, leakage-tested - and it
is a better *football-only* model than Deadeye's historical proxy on unseen seasons. It is **not** a
predictive improvement over Deadeye as deployed, because Deadeye starts from the market and the
market is far better than any market-free model here. Promotion is not recommended.

## 1. Matched sets

| | Development 2010-2019 | Holdout 2020-2026 |
|---|---|---|
| Regular-season games completed | 2,560 | 1,708 |
| Ties (left out of probability scores) | 8 | 6 |
| Matched decided games (all 8 sources) | **2,551** (170 weeks) | **1,642** (109 weeks) |
| Missing | 1 game without a moneyline | 2026 weeks 3-6: Deadeye's scores file ends at week 2, so its proxy has no forecast |

## 2. Probability quality (regular season, matched games)

| Model | Dev log loss | Dev Brier | Dev acc. | Holdout log loss | Holdout Brier | Holdout acc. |
|---|---|---|---|---|---|---|
| Market: de-vigged closing moneyline | 0.6105 | 0.2115 | 66.4% | 0.6082 | 0.2104 | 66.9% |
| Market: closing spread -> logistic | 0.6103 | 0.2114 | 66.3% | 0.6073 | 0.2101 | 66.9% |
| Deadeye curve on closing spread | 0.6102 | 0.2114 | 66.4% | 0.6077 | 0.2103 | 66.9% |
| Deadeye historical proxy | 0.6227 | 0.2170 | 64.8% | 0.6413 | 0.2247 | 63.8% |
| **Challenger (market-free stack)** | 0.6247 | 0.2178 | 64.8% | **0.6340** | 0.2217 | 64.0% |
| Challenger logistic | 0.6259 | 0.2184 | 64.7% | 0.6364 | 0.2228 | 64.0% |
| Challenger Elo | 0.6263 | 0.2187 | 64.6% | 0.6399 | 0.2243 | 63.3% |
| Challenger gradient boosting | 0.6303 | 0.2200 | 64.8% | 0.6333 | 0.2214 | 64.0% |

Paired log-loss differences (Challenger minus the other; negative = Challenger better;
week-clustered bootstrap, 4,000 resamples):

| vs | Development | Holdout |
|---|---|---|
| Deadeye proxy | +0.0020 [-0.0033, +0.0072] tie | **-0.0073 [-0.0131, -0.0015]** Challenger |
| Deadeye curve on closing spread | +0.0144 [+0.0067, +0.0217] Deadeye | +0.0263 [+0.0178, +0.0350] Deadeye |
| Closing moneyline | +0.0142 [+0.0071, +0.0209] market | +0.0258 [+0.0180, +0.0338] market |
| Elo | -0.0016 [-0.0058, +0.0025] tie | -0.0058 [-0.0122, +0.0011] tie |
| Logistic | -0.0013 [-0.0037, +0.0011] tie | -0.0024 [-0.0053, +0.0008] tie |
| Gradient boosting | **-0.0057 [-0.0103, -0.0012]** Challenger | +0.0008 [-0.0014, +0.0028] tie |

Holdout, Challenger minus Deadeye proxy by season (x1000): 2020 -14.4, 2021 -9.9, 2022 -0.4,
2023 +4.0, 2024 -12.3, 2025 -9.2, 2026 (weeks 1-2) -22.2. No single season's interval excludes zero
except 2020's, which touches it.

Multiple comparisons: about ten pairs are reported per split. The holdout proxy comparison
(bootstrap p about 0.015) was the brief's primary question, but it should still be read as moderate
evidence, not proof.

Calibration: all models are reasonably calibrated (expected calibration error 0.01-0.05); Challenger's
holdout ECE is 0.029, the proxy's 0.037, the moneyline's 0.024. Bucket tables are in the reports.

## 3. Variants (separate runs, never mixed into the tables above)

| Variant | Dev log loss | Holdout log loss | Holdout vs market-free Challenger | Holdout vs closing moneyline |
|---|---|---|---|---|
| `market_informed` (adds closing spread + moneyline) | 0.6158 | 0.6126 | -0.0215 [-0.0294, -0.0135] | +0.0044 [+0.0004, +0.0084] (market better) |
| `no_epa` (no play-by-play features) | 0.6257 | 0.6359 | +0.0018 [-0.0017, +0.0053] | - |

Adding Challenger's football features to the closing line made it slightly **worse** than the
closing line alone. Dropping every play-by-play feature cost nothing measurable on the holdout - the
football signal beyond Elo and points is small, and the retrospective-EPA concern does not drive the
result.

## 4. Playoffs (Deadeye's proxy does not price them)

Holdout, 78 games: closing moneyline 0.5962, Challenger 0.6093, Elo 0.6036. Development, 110 games:
logistic 0.6286, moneyline 0.6297, Challenger 0.6365. Too few games for conclusions.

## 5. ACQL pool

Actual rules: one point per credited pick, pool lines on favourites of 6.5+. Lines reconstructed
from the closing spread with the commissioner's measured habit (identical for every model);
opponents' picks not reconstructed.

| Card | Dev pts/week (170 wks) | Holdout pts/week (109 wks) | Holdout weekly SD | Challenger minus this, holdout |
|---|---|---|---|---|
| Challenger | 8.31 | 8.34 | 2.14 | - |
| Deadeye proxy | 8.35 | 8.17 | 2.10 | +0.17 [-0.18, +0.50] |
| Deadeye curve on closing spread | 8.59 | 8.76 | 2.06 | -0.42 [-0.81, -0.02] |
| Closing spread (normal margin) | 8.49 | 8.82 | 1.96 | -0.48 [-0.84, -0.09] |
| Always the home team | 7.58 | 7.69 | 1.86 | +0.65 [+0.14, +1.18] |

Rank agreement (mean within-week Spearman of home chances, holdout): Challenger-Deadeye proxy 0.93,
Challenger-closing moneyline 0.86, Deadeye proxy-moneyline 0.83.

A standard 1..N confidence pool (NOT ACQL's rules) ranks the same way: holdout totals Challenger
9,171, proxy 9,050, Deadeye curve on closing spread 9,639.

Real pick sheets (real lines, 35-39 real coaches; place 1 = tied for or holding first):

| Week | Pool avg | Best | Challenger (place) | Deadeye proxy (place) | Deadeye curve, closing (place) | Market card | Deadeye stored card |
|---|---|---|---|---|---|---|---|
| 2023 wk 8 | 7.7 | 11 | 7 (24) | 9 (4) | 9 (4) | 9 | - |
| 2023 wk 10 | 7.8 | 11 | 7 (20) | 7 (20) | 10 (2) | 9 | - |
| 2023 wk 11 | 7.8 | 10 | 8 (12) | 10 (1) | 10 (1) | 11 | - |
| 2023 wk 13 | 7.5 | 13 | 10 (3) | 8 (12) | 10 (3) | 9 | - |
| 2025 wk 3 | 8.9 | 12 | 9 (16) | 12 (1) | 10 (6) | 11 | - |
| 2025 wk 4 | 8.7 | 12 | 7 (30) | 9 (13) | 10 (5) | 11 | - |
| 2026 wk 1 | 9.7 | 13 | 12 (2) | 10 (12) | 13 (1) | 13 | 13 (1) |
| 2026 wk 2 | 8.7 | 12 | 9 (12) | 10 (4) | 13 (1) | 11 | 13 (1) |
| **Total** | 66.7 | | **69** | **75** | **85** | **84** | |

## 6. Prospective shadow: 2026 week 7 (not yet played)

Journaled 2026-10-21 16:54 UTC, before the first kickoff (2026-10-23 00:15 UTC), and pushed to
GitHub in commit `20e4939`. Challenger's home-win chances, Deadeye's (its live rule on
`nflpredictions week 7.csv`, captured separately) and the lines nflverse carried at the time:

| Game | Challenger | Deadeye live | Spread (home) | QBs Challenger assumed |
|---|---|---|---|---|
| NE @ CHI | 0.430 | 0.599 | -3.0 | Maye @ Williams |
| PIT @ NO | 0.369 | 0.376 | +3.5 | Rodgers @ Shough |
| CIN @ BAL | 0.489 | 0.603 | -2.5 | Burrow @ Huntley |
| CLE @ TEN | 0.502 | 0.439 | +1.5 | Watson @ Ward |
| IND @ MIN | 0.768 | 0.745 | -6.5 | Jones @ Murray |
| MIA @ NYJ | 0.541 | 0.696 | -4.5 | Willis @ Smith |
| NYG @ HOU | 0.720 | 0.815 | -10.0 | Winston @ Stroud |
| SF @ ATL | 0.277 | 0.372 | +3.0 | Purdy @ Penix |
| TB @ CAR | 0.692 | 0.642 | -3.5 | Daniels @ Young |
| DEN @ ARI | 0.300 | 0.327 | +4.5 | Nix @ Brissett |
| GB @ DET | 0.599 | 0.624 | -3.0 | Love @ Goff |
| LA @ LV | 0.299 | 0.361 | +4.5 | Stafford @ Cousins |
| KC @ SEA | 0.557 | 0.588 | -2.5 | Mahomes @ Darnold |
| DAL @ PHI | 0.458 | 0.337 | +4.5 | Prescott @ McKee |

(Spread shown as the home team's line, negative = home favoured.) Where the two disagree most
(NE@CHI, CIN@BAL, MIA@NYJ, DAL@PHI), Challenger is assuming the previous game's starter; where that
QB is a backup who will not start, Challenger is wrong for a reason the market already knows.
Score it after the games with `python -m challenger record-outcomes` and
`python -m challenger shadow-report`.
