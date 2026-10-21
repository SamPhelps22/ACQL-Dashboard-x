# Project Challenger

An independent NFL win-probability engine, built from scratch to compete with Deadeye in a
leakage-safe historical backtest and in prospective weekly forecasts. It shares no code with Deadeye
and never reads a Deadeye output; Deadeye is only captured, through its own code and read-only, in
the evaluation stage (`challenger/arena/`). Nothing in the dashboard or Deadeye was changed.

**Result in one line:** Challenger beat Deadeye's historical proxy on the untouched 2020-2026
holdout (log loss 0.6340 vs 0.6413, 95% CI of the difference -0.0131 to -0.0015), but lost clearly to
the betting market and to Deadeye's market-based starting point - so it is not an improvement over
Deadeye as deployed. Details: [docs/RESULTS.md](docs/RESULTS.md).

## Documents

| | |
|---|---|
| [docs/AUDIT_AND_PLAN.md](docs/AUDIT_AND_PLAN.md) | Repository audit, how Deadeye works, the plan and what changed during development |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Every dataset: source, coverage, missingness, timestamps, limitations |
| [docs/FEATURES.md](docs/FEATURES.md) | Feature definitions and what each model sees |
| [docs/RESULTS.md](docs/RESULTS.md) | Head-to-head, market benchmark, ACQL evaluation, week-7 shadow forecasts |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Limitations, missing data, next steps |
| `results/dev/REPORT.md`, `results/holdout/REPORT.md` | Generated reports with every table |

## Commands (from the project root)

```bash
python -m pip install -r challenger/requirements.txt
python -m challenger fetch                                   # nflverse schedule + pbp 2001-now (~450 MB, git-ignored)
python -m challenger backtest --split dev                    # walk-forward 2010-2019, write-once forecasts
python -m challenger backtest --split holdout                # 2020-2026 (pre-registered holdout)
python -m challenger backtest --split holdout --variant market_informed   # or no_epa
python -m challenger evaluate --split holdout                # vs Deadeye, market, ACQL -> results/holdout/
python -m challenger shadow --season 2026 --week 8           # journal next week's forecasts before kickoff
python -m challenger capture-deadeye --season 2026 --week 8  # journal Deadeye's, separately (needs that week's file)
python -m challenger record-outcomes                         # after the games
python -m challenger shadow-report                           # score the prospective journal
python -m challenger verify                                  # every stored file and journal vs its hash
python tests/test_challenger.py                              # 26 tests, ~10 s, no network
```

## Layout

```
challenger/
  config.py        every setting; its hash names the model version
  data.py          nflverse downloads, manifest with SHA-256, schedule loading
  pbp.py           play-by-play -> team-game and QB-game tables
  venues.py        stadium coordinates and time zones (own table)
  elo.py           Elo, read as of each week's deadline
  features.py      point-in-time ratings, QB ratings, context, matchups
  models.py        logistic, LightGBM, stacker
  calibration.py   Platt scaling
  backtest.py      expanding-window, season-by-season walk-forward
  predictions.py   write-once forecast files + manifests
  runs.py          one backtest end to end
  journal.py       append-only, hash-chained prospective journal
  shadow.py        prospective forecasts for an upcoming week
  synthetic.py     made-up league for the tests
  metrics.py       log loss, Brier, calibration, week-clustered bootstrap
  arena/           evaluation only: Deadeye capture, market baselines, head-to-head, ACQL, reports
  results/         stored forecasts (backtests/), generated reports (dev/, holdout/, shadow/)
  journal/         the prospective journal
  artifacts/       the fitted model behind each prospective forecast
  docs/
```

Not promoted to production. Any use of Challenger in the dashboard needs a separate, explicit review.
