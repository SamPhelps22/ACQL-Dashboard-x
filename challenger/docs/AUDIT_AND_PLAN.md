# Repository audit and implementation plan

Written at the start of Project Challenger (2026-10-21), before any model was built, and updated
only to record what was actually done.

## 1. What the repository already holds

| Part | What it is | Relevance to Challenger |
|---|---|---|
| `acql/` | The ACQL Dashboard (PySide6 desktop app, website, emails, scheduled jobs). | Must keep working unchanged. |
| `acql/model/` | **Deadeye**: how the dashboard prices a game, its ledger, backtest, Model Lab. | The opponent. Read-only. |
| `acql/training/` | Deadeye's "training ground": recipes tested walk-forward against the line, fed by Prediction Tracker season archives. | Shows how Deadeye could be replayed historically - but needs archives not in the repo. |
| `acql/data/nfl_scores_2010_2026.csv` | Scores feeding Deadeye's own backtest proxy. | Deadeye's data, used only to capture Deadeye. |
| `acql/data/backtest_results.json`, `pool_weeks.json` | Deadeye's stored backtest and stored card results. | Reported beside, never used as inputs. |
| `acql-forecasts.json`, `nflpredictions week N.csv` | Deadeye's weekly inputs (Prediction Tracker files): 2026 weeks 3, 4, 5, 7. | Let Deadeye's full live rule be reconstructed for those weeks only. |
| `acql-picks.json` | Eight real pick sheets (2023 wk 8/10/11/13, 2025 wk 3/4, 2026 wk 1/2): every coach's pick and the commissioner's pool lines. | Real-field ACQL comparison. |
| `nfl_pickem/` | A separate, earlier pick'em system (market-blended). | Not Deadeye; not reused (Challenger was built from scratch). |

### How Deadeye prices a game (from `acql/model/pricing.py`, `predictions.py`, `analytics.py`)

1. **Base**: the market's latest home spread (or a hand-typed spread, or the moneyline-implied margin
   on straight-up games).
2. **Nudge**: plus a share (default 25%, refitted in-season from the app's own database) of the
   Prediction Tracker computer-model consensus's disagreement with the market, after removing the
   slate's shared home lean and discounting disagreement the line has moved against.
3. **Width**: SD 8.7 for the narrow bell, widened by model disagreement and the game's total.
4. **Chance**: a two-bell margin distribution weighted toward key numbers (`analytics.cover_chance`).

So Deadeye-as-deployed is **market-anchored**. Its historical backtest (`acql/model/backtest.py`)
cannot replay that, because no historical lines are in its scores file; it uses a **rating-model
proxy** instead (constants fitted 2011-2019, checked 2020-2025).

### ACQL's actual rules

One point per credited pick, every game on the NFL week's slate; a favourite of 6.5+ carries a pool
line and must win by at least it (a win by exactly a whole-number line goes to the favourite); a tied
straight-up game credits nobody. **There are no confidence points** - the brief's "1..N" describes a
different kind of pool (the dashboard's own CALIBRATION_AUDIT says the same). Both are evaluated, and
kept separate.

## 2. What could and could not be obtained

| Need | Status |
|---|---|
| Historical play-by-play, results, schedule, venues | nflverse release files - reachable, downloaded (2001-2026). |
| Historical closing lines and moneylines | In the nflverse schedule (spread from 1999, moneylines from 2006, near-complete from 2010). Closing only - no deadline-time lines. |
| Prediction Tracker season archives (to replay Deadeye's live rule before 2026) | **Not obtainable here**: thepredictiontracker.com sits behind a Cloudflare browser challenge (HTTP 403 to scripted requests). |
| Deadeye forecasts recorded at the time | **None in the repository** for any season: the ledger lives in the app's own `acql.db`, which is git-ignored. |
| Timestamped injury reports | nflverse injury files exist but carry only the final weekly status with `date_modified`; not reconstructable as of a Thursday deadline. **Excluded.** |
| Forecast weather at the deadline | Only observed game-day weather exists. **Excluded.** |
| Pressure charting | True pressure only from 2018 (PFR); QB hits in pbp from 2006. A sacks+hits proxy is used from 2006, missing before. |

## 3. Plan (as carried out)

1. **Isolated package** `challenger/`: data -> pbp aggregation -> point-in-time features -> Elo /
   logistic / LightGBM / stack -> walk-forward backtest -> write-once forecast files. The model
   modules never import `acql`, `nfl_pickem` or `challenger.arena`, and never mention Deadeye's files
   (checked by `tests/test_challenger.py::Independence`).
2. **Evaluation stage** `challenger/arena/`: the only code that touches Deadeye, and only through
   Deadeye's own functions, read-only, to capture its forecasts into a separate frame.
3. **Pre-registered split**: development seasons 2010-2019 (design may react to them), untouched
   holdout 2020-2026 (run once, after the code and config were committed at `f19b7b5`).
4. **Leakage controls**: features as of each week's deadline; models refitted once a season on
   earlier seasons only; tuning, calibration and stacking on inner folds of earlier seasons;
   forecasts written before any result is joined; automated perturbation tests.
5. **Head-to-head** on one matched set, log loss and Brier primary, week-clustered bootstrap CIs.
6. **ACQL** layer kept separate from the probability models.
7. **Prospective shadow** journal, hash-chained and append-only; first used for 2026 week 7.

## 4. What changed during development (researcher degrees of freedom, disclosed)

- The "recent form" feature was first defined in a way that measured team quality backwards (form
  correlated -0.20 with the margin); it was redefined (form shrunk toward the team's own long-run
  level). This was found from correlations on 2006-2026 data during development - a look at data
  that includes the holdout seasons, though at a feature-sanity level, not a model score.
- QB hits are absent before 2006; the pressure proxy was set to missing there rather than mixing
  definitions.
- Elo constants were tuned on 2002-2009 only; online home-advantage drift did not help there and is off.
- Nothing about the models was changed after the development scores were seen, except reporting
  fixes (no interval verdicts below ten weeks; extra columns on the real-sheet table).
- The holdout was evaluated once. Its numbers are reported as they came out.
