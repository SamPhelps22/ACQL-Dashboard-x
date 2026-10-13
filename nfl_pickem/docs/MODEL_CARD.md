# Model card: NFL Confidence Pick'em Predictor v1.1

## v1.1 upgrade: what changed and what it measurably did

All results come from the same walk-forward protocol: 2012–2023 development seasons,
207 regular-season weeks, 3,247 decided games. Paired weekly point differences are shown with
95% confidence intervals.

| Change | Measured impact | Decision |
|---|---|---|
| Play-by-play detail tables (dropback/rush/early-down/neutral-state EPA, sacks, CPOE, third-down, red zone, per-QB stats) | Data only | Kept |
| **QB rating group** (starter's own shrunk EPA/dropback, backup indicator) | Logistic: log loss 0.6309→0.6285, **+0.40 pts/wk [+0.06, +0.74]**. GBM: 0.6320→0.6274, **+0.83 pts/wk [+0.22, +1.45]**. 70/30 blend: +0.12 [−0.01, +0.25] | **Enabled** |
| Opponent-adjusted unit ratings (passing, rushing, neutral, early-down, sack, third-down, red-zone, interceptions) | Logistic +0.04 [−0.40, +0.48], GBM −0.13 [−0.90, +0.65]; log loss slightly worse | Not enabled |
| Matchup interactions (pass, rush, protection, explosive pass) | Logistic −0.07, GBM −0.34 (n.s.); log loss worse | Not enabled |
| Market-residual model (market logit + ridge-penalised football adjustments) | Log loss 0.6120 vs market 0.6111; −0.12 pts/wk vs market [−0.57, +0.32] | Reported, not used for picks |
| Blend weights learned from prior out-of-sample seasons (replaces fixed 70/30) | Weights converge to 90–100% market (100% from 2023). Dev: −0.16 pts/wk vs market [−0.41, +0.10]; holdout: identical to market | **Enabled** (`blend.mode = learned`) |
| Explicit no-odds fallback (equal-weight Elo/logistic/GBM) | ML-only trails the market by ~2.5 pts/wk when odds exist, but is the best available signal when they don't | Enabled |
| Leakage fix: the first data season's league prior no longer uses future seasons | Affected 2006 training rows only; caught by a new test | Fixed |

**Bottom line.** No football feature, model or blend beat the de-vigged market out of sample.
The validated system therefore *uses the market whenever odds exist*. The football-intelligence
work improves the fallback models: the QB rating is a genuine, statistically significant gain
for the ML models. It also powers the matchup reports. Each report shows the football models'
gap to the market as an explicitly **unvalidated** hypothesis that never changes the pick.

### Holdout 2024–2025, final configuration

This is one continuous walk-forward from 2012, so the 2024–2025 blend weights were learned
only from earlier seasons.

| Model | Accuracy | Log loss | Avg pts/wk |
|---|---|---|---|
| Market | 0.684 | 0.5981 | 90.61 |
| Blend (learned → 100% market) | 0.684 | 0.5981 | 90.61 |
| Market residual | 0.682 | 0.5986 | 90.61 |
| ML ensemble (with QB rating) | 0.666 | 0.6143 | 86.94 |
| Logistic / GBM / Elo | 0.652 / 0.652 / 0.659 | 0.6152 / 0.6149 / 0.6232 | 86.9 / 86.9 / 85.8 |

**Disclosure:** the 2024–2025 holdout was first evaluated with v1.0. Every v1.1 decision above
was made from development seasons only, but this is the holdout's second viewing.

---

# Original v1.0 card (kept for reference)

## Purpose

The model estimates P(home team wins) for each NFL game and allocates confidence points
(N…1) to maximise **expected points** in a weekly confidence pool.

It is not a betting tool and makes no claim of betting profitability.

## Models

| Id | Model | Details |
|---|---|---|
| A | Elo | K=20, home-field advantage = 48 Elo points (0 at neutral sites), a FiveThirtyEight-style margin-of-victory multiplier, and 1/3 regression to 1505 between seasons. These are literature defaults; they were **not tuned** on the evaluation data. |
| B | Logistic regression | Median imputation with missing-value indicators, standardisation and L2 regularisation. C is chosen on the previous season. The whole pipeline is fitted on training rows only. |
| C | Gradient boosting | LightGBM with 4–8 leaves, 150–300 trees, learning rate 0.03, row and column subsampling. Hyper-parameters are chosen on the previous season. |
| D | Market | American odds → implied probability → multiplicative de-vig; bookmakers are averaged; falls back to Φ(−spread/13.45). |
| E | Blend | Default 0.70 market + 0.10 each for Elo, logistic and GBM, combined linearly in probability space. Missing components are dropped and the remaining weights renormalised. A `learned` mode grid-searches weights on earlier out-of-sample predictions only. |

**Calibration** (`auto`): Platt or isotonic calibration is kept only if, fitted on the first
half of the earlier out-of-sample predictions, it lowers log loss on the second half. In
practice it was rarely selected: GBM got Platt calibration only in the 2025 holdout season.

**Inputs:** see [FEATURES.md](FEATURES.md). By default the ML models do *not* see market
inputs.

## Validation protocol

The backtest is walk-forward. For each test season S:

* train on seasons 2006…S−2 and tune on S−1;
* refit on 2006…S−1;
* predict S using features computed at each week's slate cutoff (first kickoff minus 1 hour);
* store the predictions, then score them;
* allocate weekly points exactly as a real slate would be.

Development seasons were **2012–2023** (3,247 decided games, 207 regular-season weeks).
**2024–2025** was kept as an untouched holdout and evaluated once, after development was
finished. Ties (about 0.2% of games) are excluded from the probability metrics. Pool scoring
uses half points for ties and regular-season weeks only.

## Measured results (nflverse data, run 2026-10-13)

### Development, 2012–2023, fixed 70/30 blend

| Model | Accuracy | Log loss | Brier | Avg pool pts/week | SD |
|---|---|---|---|---|---|
| Market only | **0.661** | **0.6111** | **0.2118** | **87.11** | 20.4 |
| Market + ML blend (70/30) | 0.659 | 0.6129 | 0.2125 | 86.91 | 20.1 |
| ML ensemble (no market) | 0.645 | 0.6278 | 0.2191 | 84.39 | 19.3 |
| Logistic regression | 0.649 | 0.6309 | 0.2205 | 83.80 | 19.6 |
| Gradient boosting | 0.645 | 0.6320 | 0.2209 | 83.57 | 19.6 |
| Elo | 0.644 | 0.6322 | 0.2210 | 84.01 | 19.0 |

Mean weekly point differences, with 95% confidence intervals:

* Blend − market: **−0.21 [−0.57, +0.16]**, no significant difference.
* Blend − ML-only: +2.52 [+1.59, +3.44].
* Blend − Elo: +2.90 [+1.75, +4.05].

### Learned blend weights (development)

* **Log loss:** 0.6118, still worse than the market alone at 0.6111.
* **Pool points:** 86.94 per week (−0.17 vs. market, 95% CI [−0.43, +0.09]).
* **Weights:** the learned weights converged to 90–100% market by 2021–2023.

### Holdout, 2024–2025, evaluated once

| Model | Accuracy | Log loss | Brier | Avg pool pts/week |
|---|---|---|---|---|
| Market only | 0.684 | 0.5981 | 0.2059 | 90.61 |
| Blend (70/30) | 0.680 | 0.6003 | 0.2068 | 90.07 |
| ML ensemble | 0.657 | 0.6159 | 0.2138 | 86.96 |
| Logistic | 0.663 | 0.6174 | 0.2146 | 86.69 |
| GBM | 0.663 | 0.6170 | 0.2138 | 87.29 |
| Elo | 0.659 | 0.6232 | 0.2169 | 85.82 |

Blend − market: −0.54 points per week, 95% CI [−1.35, +0.26].

## Interpretation

* **The ML models do not improve on the market.** That holds in development and in the
  holdout, on every probability metric and on pool points. Adding 30% ML costs a small,
  statistically insignificant amount.
* The ML and Elo models still have value **when odds are missing**: they score about 3 points
  per week below the market, far better than a coin flip. The blend falls back to them
  automatically, and those games are flagged `NO_ODDS`.
* **Practical recommendation:** set *Probabilities used for picks* to **market**, or set the
  market weight to 0.9–1.0, whenever current odds are available. The 70/30 default is kept
  because it was the requested baseline hypothesis.
* Pool scores vary a lot from week to week (SD ≈ 20 points on a ~110-point week). Single-week
  results say little about model quality.

## Known biases and limitations

1. **Closing-line proxy.** Historical lines are closing lines, which are sharper than the line
   available at a Thursday pick deadline. The market baseline's backtest is therefore slightly
   optimistic for a slate-cutoff pool.
2. **QB starters.** Historical features use the actual starter, which may not have been known
   at the cutoff. Upcoming games use nflverse projections. Injury designations are displayed
   but not modelled; replacement-level effects are not estimated.
3. **No in-season refits.** The ML models refit once per season. Elo and rolling features
   update weekly.
4. **Elo parameters** are untuned literature defaults.
5. **Weather** features are off, because historical values are observations, not forecasts.
6. **Opponent-aware strategy** (maximising the chance of winning the pool, rather than
   expected points) is not implemented. It needs opponent picks or a credible model of how
   opponents pick. `OpponentAwareStrategy` refuses to run, and
   `simulate_pool_win_probability` can evaluate a sheet against known opponent sheets.
7. Data comes from community-maintained nflverse sources and may contain occasional errors or
   update delays.

## Reproducibility

The random seed is fixed (42) and LightGBM runs in deterministic single-thread mode. Re-running
a backtest on the same data and config gives identical predictions
(`tests/test_backtest.py::test_backtest_reproducible`).
