# Operation Sunday research lab

An independent, shadow-only NFL forecasting lab. It builds eight genuinely different forecasting approaches,
scores them walk-forward against the market, Deadeye and Challenger on identical games, tests which information
sources add anything, and keeps a prospective, append-only forecast journal.

**Deadeye is not modified, imported by any model, or used as a training label.** Nothing in `acql/` or
`nfl_pickem/` changed. Deadeye enters only through `adapters/deadeye.py` (evaluation) and the ACQL pool *rules*
through `acql_eval.py`. A test enforces both.

* Audit and architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
* Data sources and measured coverage: [`docs/DATA_INVENTORY.md`](docs/DATA_INVENTORY.md)
* Model H decision: [`docs/MODEL_H_FEASIBILITY.md`](docs/MODEL_H_FEASIBILITY.md)
* Results: [`reports/RESULTS_DEV.md`](reports/RESULTS_DEV.md) (2012-2023), [`reports/RESULTS_HOLDOUT.md`](reports/RESULTS_HOLDOUT.md) (2024-2025, frozen)
* Research summary: [`docs/RESEARCH_SUMMARY.md`](docs/RESEARCH_SUMMARY.md)
* Experiment registry (every run, including failures and not-run tests): `experiments/registry.jsonl`
* Shadow journal: `shadow/journal.jsonl`, grades in `shadow/grades.jsonl`

## Running it

Python 3.11+, numpy and pandas only (no scipy / scikit-learn).

```bash
python -m research_lab fetch        # nflverse files -> data/research_lab/raw (git-ignored), with SHA-256 manifest
python -m research_lab build        # play-by-play -> team-game, QB-game, drive tables
python -c "from research_lab.data import scheme; scheme.build()"   # Model H participation table
python -m research_lab inventory    # docs/DATA_INVENTORY.md
python -m research_lab dev          # walk-forward 2009-2023, ensembles, evaluation 2012-2023, ablation (~35 min)
python -m research_lab freeze "..." # record the frozen configuration
python -m research_lab holdout      # score 2024-2025 once (refuses without a freeze record)
python -m research_lab extensions   # Model H 2021-2025; 2026-to-date vs Deadeye's recomputed forecasts
python -m research_lab shadow       # forecasts for the next unplayed week -> shadow/journal.jsonl
python -m research_lab grade        # grade journal entries whose games are final
python -m unittest discover -s research_lab/tests -t .     # tests (leakage tests need the fetched data)
```

## The models

| | Model | Module | Information set |
|---|---|---|---|
| A | Quarterback: opponent-adjusted, shrunk EPA/dropback of the expected starter, kept apart from the team's pass offence; sacks, INTs, CPOE, EPA when hit, rushing, experience, starter change, pressure matchup. Three timing variants: last game's starter (`A_qb_weekstart`), + timestamped final injury report (`A_qb_injury`), confirmed starter (`A_qb_confirmed`) | `models/qb.py`, `features/qb.py` | week start / pre-kickoff |
| B | Drive-level Monte Carlo: start field position by previous drive result, outcome rates by field bucket tilted by opponent-adjusted offence/defence drive ratings, pace, overtime, return/defensive TDs; 4,000 seeded simulations a game | `simulation/drives.py` | week start |
| C | Situational: team-strength base + rest, byes, short weeks, travel, time zones, early west-coast kickoffs, altitude, roof, surface, division; weather variant uses observed weather (retrospective) | `models/situational.py`, `features/situational.py` | week start / closing (weather) |
| D | Market: de-vigged moneyline, spread, spread-vs-moneyline disagreement, spread prices, total interaction | `models/market.py` | closing (retrospective) |
| E | Bayesian dynamic team strength: Kalman filter on offence/defence/home edge with offseason regression and variance inflation, QB-change uncertainty, posterior-predictive probabilities; plug-in twin for the uncertainty test | `models/bayes.py` | week start |
| F | Tactical matchups: opponent-adjusted unit ratings (pass/run EPA, pressure, explosives, third down, red zone, turnovers), additive vs interaction versions | `models/matchup.py`, `features/ratings.py` | week start |
| G | Ensembles of out-of-fold component forecasts: equal, regularised weighted, logistic stacking; forward selection on earlier seasons; market-free and market-informed | `ensemble/stack.py` | as its latest component |
| H | Scheme matchups from charted coverage (man/zone) and pressure, 2018+ | `models/scheme.py`, `data/scheme.py` | week start |

Benchmarks: closing de-vigged moneyline and closing spread (`market_*_close`), Challenger's Elo (nfl_pickem's
formula and parameters, cross-checked in tests), a plain logistic on point differential, and Deadeye's line-only
proxy (Deadeye's own curve on the closing spread).

## Leakage controls

* `Store.snapshot(as_of)` is the only way a model sees history: games completed by `as_of` and their pbp rows.
* The games being predicted are passed through `games.blind(info_set)`: no outcomes ever; no closing lines,
  starters or observed weather unless the model's information set allows them.
* Point-in-time feature tables are built week by week, each from its own week's snapshot (`features/bank.py`).
* Hyper-parameters: chosen on earlier seasons only (ridge penalties per season; Model E's on 2008-2011).
* Calibration and ensemble weights: fitted on earlier seasons' out-of-fold forecasts only.
* Tests (`tests/test_leakage.py`) rewrite every later game's scores, lines and play-by-play at random and
  assert that eleven models' earlier forecasts are byte-identical; likewise for ensembles and calibration.
* The holdout was scored once, after `freeze` (see `experiments/freeze.json`).
