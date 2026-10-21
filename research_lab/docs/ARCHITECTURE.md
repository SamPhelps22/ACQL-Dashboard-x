# Operation Sunday research lab — audit and architecture

Status: research / shadow only. Nothing in this package is imported by the
dashboard (`acql/`) or by `nfl_pickem/`, and nothing here writes to their data.

## 1. Repository audit (what exists before the lab)

| Area | Where | What it is | Used by the lab? |
|---|---|---|---|
| **Deadeye** (production) | `acql/model/pricing.py`, `acql/model/predictions.py` | Market line (typed > fetched > Prediction Tracker file > opening) plus a share (`CONSENSUS_WEIGHT` = 0.25, refitted in-season) of the computer models' disagreement with the line, slate home-lean removed. Normal margin→probability with SD 8.7 widened by model disagreement. | **Evaluation adapter only** (`research_lab/adapters/deadeye.py`). Never imported by a model. |
| Deadeye's training ground | `acql/training/` | Walk-forward recipes on the Prediction Tracker archive (line, Deadeye at shares, ridge, weighted crowd, trees). Needs `data/tracker/archive`, which is not in the repo and cannot be fetched from this environment (Cloudflare 403). | Read for design; not imported. |
| **Challenger** | `nfl_pickem/` | Standalone confidence-pool system: Elo (538-style, literature defaults), logistic, GBM, de-vigged market, 70/30 blend. Its own model card says the market was best 2012–2023. | Elo re-implemented as a baseline with **the same published parameters** (`research_lab/models/baselines.py`); `nfl_pickem` needs DuckDB, not installed. |
| Historical backtest | `acql/model/backtest.py` | Pool replay 2010–2025 on a *rating proxy* (no lines in `nfl_scores_2010_2026.csv`). | Pool **rules** (`pool_line`, `analytics.line_need`) are imported read-only by `research_lab/acql_eval.py`. |
| Scores | `acql/data/nfl_scores_2010_2026.csv` | Scores incl. preseason, no lines. | Cross-check only. |
| Deadeye recorded forecasts | `acql-forecasts.json` (2026 wk 1–3), `nflpredictions week {3,4,5,7}.csv` | Only 2026 weeks 1–3 recorded (weeks 1–2 typed lines, no models). App DB `data/acql.db` (the forecast log) is git-ignored and absent. | Adapter reads these; tiny sample, labelled. |
| Pool record | `acql/data/pool_weeks.json`, `acql-picks.json` | Real pool cards for 2025 wk 15–17 and 2026 wk 1–3. | Not used for model scoring (too few weeks); documented. |

### ACQL rules as implemented (the only ruleset the repo encodes)
* One point per correct pick, every game on the slate.
* A game whose favourite is **6.5 points or more** carries a pool line =
  `max(7, floor(spread)+1)` (commissioner's habit, `backtest.pool_line`);
  the favourite is credited only if it wins by at least `ceil(line)`
  (`analytics.line_need`); otherwise the underdog is credited.
* An unlined tie credits nobody.
* The habit was measured on 2025 wk 15 – 2026 wk 3 sheets only. For earlier
  seasons pool lines are **reconstructed** from the closing spread. No rule
  change is recorded in the repo, so one ruleset is applied throughout
  and that assumption is disclosed.

## 2. Data sources (see `DATA_INVENTORY.md` for measured coverage)
All public nflverse files, fetched by `python -m research_lab fetch` into
`data/research_lab/raw/` (git-ignored) with a manifest of URL, fetch time,
size and SHA-256.

| Source | Content | Timing honesty |
|---|---|---|
| `nfldata/games.csv` | schedule, scores, **closing** spread/total/moneylines, rest, roof, surface, temp, wind, starting QBs | Closing lines and observed weather are **retrospective**; starters are known ~90 min before kickoff |
| `pbp_<season>` | play-by-play with EPA, drives, QB ids | Used only for games completed before the forecast |
| `injuries_<season>` | weekly final injury report | Report date only (no intraday timestamp) |
| `ftn_charting` 2022+ | play-action, motion, blitz, box count | Model H feasibility |
| `pbp_participation` 2016+ | personnel, defenders in box, coverage (partial) | Model H feasibility |

Not available here: opening lines and line-movement history (nflverse carries
closing only; The Odds API needs a key and has no free history), cross-book
quotes, archived weather forecasts before 2022, Prediction Tracker archives.

## 3. Package layout

```
research_lab/
  config.py          seasons, holdout, paths, versions
  contract.py        the shared Forecast record + validation
  data/              fetch (with manifest), games, pbp-derived tables, inventory
  features/          point-in-time team, QB, situational, matchup, market features
  models/            A qb, C situational, D market, E bayes, F matchup, baselines
  simulation/        B drive-level Monte Carlo
  ensemble/          G out-of-fold stacking
  backtest/          walk-forward engine (season/week expanding window)
  metrics/           log loss, Brier, reliability, paired bootstrap
  experiments/       registry (append-only JSONL, incl. failures), ablation lab
  adapters/deadeye   the ONLY module allowed to import acql.model
  acql_eval.py       weekly ACQL cards under the repo's rules
  shadow/            prospective append-only journal + grading
  reports/           generated markdown
  tests/             unit, leakage, isolation tests
```

## 4. Timing model
Each forecast carries a `forecast_ts` and an `information_set`:

* `week_start` — Tuesday 09:00 ET of the game week. Only games completed
  before it are visible. All football-only models use this. **Prospective-equivalent.**
* `pre_kickoff` — 90 minutes before kickoff: adds confirmed starting QBs.
  Genuinely knowable before kickoff, but after the ACQL card deadline.
* `closing_retrospective` — the closing line / observed weather. Used only
  for benchmarks and clearly labelled; not claimable as a pre-deadline forecast.

## 5. Validation design
Walk-forward by week: for season *s*, week *w*, every model is fitted on
games with kickoff before the week's `forecast_ts`, then predicts the week.
Hyper-parameters are chosen on earlier seasons only. Calibration maps are
fitted on earlier out-of-fold predictions only. Ensemble weights are fitted
only on earlier out-of-fold component predictions.

* Development seasons: 2012–2023 (training history from 2006).
* **Frozen holdout: 2024–2025**, scored once after configs were frozen
  (`config.HOLDOUT_FROZEN_AT`).
* 2026 to date: prospective shadow period.

Leakage tests perturb future outcomes and assert earlier forecasts are
byte-identical (`tests/test_leakage.py`).
