# Research summary

**Bottom line: no independent model, ensemble or information source tested here beats the closing betting
market.** Deadeye's base (the market line) remains the strongest forecast available, and nothing found here
justifies a change to production. The results are negative, and they are consistent between development and
the frozen holdout.

All numbers are walk-forward: every forecast was made from games completed before it, with settings, calibration
and ensemble weights fitted on earlier seasons only. Full tables: [`reports/RESULTS_DEV.md`](../reports/RESULTS_DEV.md),
[`reports/RESULTS_HOLDOUT.md`](../reports/RESULTS_HOLDOUT.md).

## 1. Head to head

| | Development 2012-2023 (3,107 games, 207 weeks) | Holdout 2024-2025 (543 games, 36 weeks) |
|---|---|---|
| Closing market (de-vigged moneyline) | log loss **0.6113**, ACQL **8.51** pts/wk | **0.5984**, **9.03** pts/wk |
| Deadeye line-only proxy (Deadeye's curve, closing spread) | 0.6106, 8.51 | 0.5974, 9.00 |
| Best market-informed ensemble | 0.6123 (weighted) | 0.5963 (stack; vs market -0.0021, 95% CI [-0.0057, +0.0018]) |
| Best pre-kickoff lab model (A, confirmed QB) | 0.6262, 8.41 | 0.6266, 8.25 |
| Best week-start lab model | 0.6299 (G_free_equal), 8.15 | 0.6245 (Challenger Elo), 8.47 |
| Challenger Elo | 0.6326, 8.31 | 0.6245, 8.47 |
| Gap, best market-free model vs market | +0.019 [+0.012, +0.026] | +0.026 [+0.008, +0.047] |

* Every market-free model is worse than the market with intervals that exclude zero, in both periods.
* In ACQL points the market card beat every lab card in both periods. The market-free cards lost
  0.25-0.5 points a week; most of those intervals exclude zero in development.
* The market-informed ensembles never reliably beat the market alone. In most seasons, forward selection
  picked the market by itself.

**Important caveat on timing.** The market benchmark is the **closing** line, which is retrospective. An ACQL
card is made earlier in the week, when lines are less sharp. The comparison therefore flatters the market
against week-start models. A fair test needs line snapshots taken at the card deadline. No accessible
source has them historically, so the shadow journal now records them going forward.

## 2. Against Challenger (Elo)

In development, the confirmed-starter QB model (A) was the only lab model to beat Challenger's Elo with an interval
excluding zero (-0.0064 [-0.0126, -0.0001]). It did not repeat in the holdout (+0.0021 [-0.015, +0.019]).
The Bayesian model (E), the ensembles and the QB week-start model were directionally better than Elo in
development and directionally worse in the holdout. **None is a reliable improvement on Challenger.**

## 3. Which signals carry information? (ablation lab)

| Family | Development | Holdout | Verdict |
|---|---|---|---|
| Confirmed starting QB (pre-kickoff) | adds to a football-only base: -0.0071 [-0.0117, -0.0022]; adds nothing to the market (+0.0011) | same direction on football base (-0.0086 [-0.020, +0.004]); nothing on market | **Real football information, already in the closing line.** Worth testing against the *card-time* line. |
| QB, last week's starter | -0.0027 on football base (CI crosses 0) | -0.0022 (crosses 0) | weak |
| Market detail (spread vs moneyline disagreement, prices, total) | nothing beyond the consensus price (+0.0000) | +0.0002 | the consensus price already holds it |
| Market movement, cross-book disagreement | **not run**: no historical opening lines, timestamps or per-book quotes accessible | — | untestable with current data |
| Rest / travel / time zones / altitude | +0.002 (no effect) | +0.003 | no value |
| Observed weather (upper bound) | **hurts**: +0.0016 [+0.0002, +0.0032] | 0.0000 | no value |
| Tactical matchup interactions | **hurts**: +0.0042 [+0.0019, +0.0065] | +0.0019 (crosses 0) | overfits; drop |
| Bayesian team strength on top of market | +0.0005 | +0.0002 | no value |
| Drive simulation on top of market | +0.0002 | -0.0002 | no value |
| Scheme (coverage, pressure, personnel; Model H, 2021+) | +0.0023 [-0.0011, +0.0058] | +0.0001 | no value |

The intervals resample whole weeks. Many comparisons were made (66 paired model comparisons per period
and 27 ablations), so a single interval excluding zero should be read with caution. The QB result holds up
best: it has the largest effect, is consistent across two bases and has the same sign in the holdout.

## 4. Model-specific findings

* **E — Bayesian uncertainty buys nothing.** The filter with posterior-predictive spreads and its fixed-spread
  twin are indistinguishable, including weeks 1-4 (dev -0.00005 [-0.0008, +0.0007]). The state variance is
  small next to game-to-game noise (two observations at a 9-point SD).
* **B — the drive simulator is competitive with Elo but mis-shaped.** It produces too few 3-point margins (8.1% simulated vs 14.9%
  real) and spreads totals a little too wide (15.1 vs 13.6). Its probabilities are under-confident
  (calibration helps: 0.6350 → 0.6329). 4,000 draws per game give a Monte Carlo SE ≤ 0.008.
* **F — interactions overfit.** Additive unit ratings beat the interaction version in development (0.6356 vs
  0.6368).
* **G — little to combine.** Component errors correlate at 0.97-1.00. Given the others, no component adds
  information reliably in either period, and the simplest ensembles did as well as stacking.
* **H — data feasible from 2018, signal absent.** See [`MODEL_H_FEASIBILITY.md`](MODEL_H_FEASIBILITY.md).

## 5. Deadeye

* Deadeye's **recorded** forecasts (the forecast log in `data/acql.db`) are not in the repository, so they
  could not be evaluated. The adapter reads them read-only if a copy is provided.
* Deadeye's distinguishing ingredient, the nudge toward the Prediction Tracker's computer models, cannot be
  tested historically from here: the tracker archive is behind Cloudflare (HTTP 403), and `data/tracker/` is
  not in the repository.
* **2026 weeks 1-5 (78 games)**: Deadeye was recomputed with its own code from the input files in the repo.
  Its log loss was 0.649, against 0.651 for the closing market and 0.627-0.647 for the lab models. Every
  interval includes zero, and this sample cannot separate anything. These lab forecasts are a
  retrospective reconstruction. Only the shadow journal is prospective.

## 6. What merits further investigation

1. **Card-time market vs late QB news.** This is the only place a real edge could plausibly exist: the
   confirmed-QB signal is real information, but the closing line already contains it. Whether the line at the
   ACQL deadline does is the open question. It needs timestamped line snapshots, which the shadow journal now collects.
2. **Deadeye's computer-model nudge.** Evaluate it with a local copy of the Prediction Tracker archive
   (`data/tracker/archive`) or the app's forecast log, through the existing adapter.
3. Stop investing in: tactical interactions, rest/travel, observed weather, Bayesian uncertainty widening,
   drive simulation as a market add-on, coverage/pressure scheme features, and large ensembles.

## 7. Limitations and things that could not run

* Closing lines and observed weather are retrospective. They are labelled `closing_retrospective`
  everywhere and never presented as pre-deadline forecasts.
* Pool lines before 2025 week 15 are reconstructed from the closing spread with the commissioner's measured habit.
  The repository records one ruleset, which is applied to every season (an assumption).
* Injury-report timestamps exist for 2010-2024 only, so `A_qb_injury` equals `A_qb_weekstart` in 2025-26.
* Model E's hyper-parameters were tuned on 2008-2011. The observation SD landed on the edge of its grid (9.0).
* The development run computed the inverse normal (used to turn probabilities into margins) before a refinement
  step was added (relative error 5e-6). The holdout, extensions and shadow runs used the refined version. The
  effect is far below reporting precision.
* `p_home_cal` for the ensembles applies a second Platt step on top of their own calibration, and it is slightly
  worse. Use their raw probabilities.
* The repository's existing suite (`tests/run_tests.py`) has 1 failure and 5 errors **before and after** this
  work: they are pre-existing and unrelated. `nfl_pickem` tests were not run because DuckDB is not installed here.
* The registry keeps two early smoke runs (2012-2013 only) alongside the real runs.
