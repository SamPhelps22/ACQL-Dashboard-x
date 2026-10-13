# NFL Confidence Pick'em Predictor

A standalone system for weekly NFL **confidence-point pools**. It is independent of the ACQL
Dashboard in the parent folder and shares no code with it.

It does the following:

1. Ingests free nflverse data into DuckDB: schedules, results, closing and current lines,
   play-by-play EPA, and injury reports.
2. Builds **point-in-time** features (Elo, rolling EPA, rest, QB changes, market).
3. Predicts the home win probability with five models: **Elo**, **logistic regression**,
   **gradient boosting** (LightGBM, falling back to XGBoost or scikit-learn), the
   **de-vigged betting market**, and a **blend** (default 70% market / 30% ML).
4. Assigns confidence points N…1 to maximise expected points.
5. Backtests everything walk-forward and reports accuracy, log loss, Brier score, calibration
   and simulated pool scores.
6. Freezes the picks you submit, exports CSV, grades results and tracks your season.
7. Ships a Streamlit dashboard with five pages.

> **What the backtest says:** over 2012–2023, the de-vigged market alone was the best
> probability source. The 70/30 blend was statistically tied with it, and the ML models alone
> trailed by 2.5–3.4 points per week. The system does **not** claim to beat the market. See
> [docs/MODEL_CARD.md](docs/MODEL_CARD.md).

---

## Install

Requires Python 3.11+ (developed on 3.13; 3.12 recommended).

```bash
cd nfl_pickem
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add ODDS_API_KEY for live bookmaker odds
```

## Quick start with real data

```bash
python -m nflpickem ingest          # ~1 min: games 2006→today + play-by-play EPA + injuries
python -m nflpickem backtest --report data/exports/backtest   # ~1.5 min walk-forward 2012–2023
python -m nflpickem predict         # next week's picks + CSV in data/exports/
streamlit run app/streamlit_app.py  # dashboard at http://localhost:8501
```

## Offline demo (synthetic data, no network)

```bash
python -m nflpickem demo                 # writes data/demo.duckdb  (SYNTHETIC - not real NFL)
python -m nflpickem --demo backtest
python -m nflpickem --demo predict
streamlit run app/streamlit_app.py       # pick "Synthetic demo data" in the sidebar
```

Synthetic teams are `SYN01…SYN16` and its seasons are 2101+. Every page shows a synthetic
warning banner, and every export carries `data_label = SYNTHETIC DEMO - NOT REAL NFL`.

---

## Loading historical NFL data

```bash
python -m nflpickem ingest                       # schedule + all play-by-play seasons since config first_season
python -m nflpickem ingest --first-season 2010   # different start season
python -m nflpickem ingest --seasons 2025 2026   # only (re)load play-by-play for these seasons
python -m nflpickem ingest --force               # re-download seasons already complete
python -m nflpickem status                       # integrity report
```

Ingestion is idempotent:

* Games are upserted by the stable nflverse `game_id`, so a rescheduled game keeps its id and
  gets the new kickoff.
* Duplicate rows keep the last copy.
* Play-by-play is skipped for seasons that are already complete.
* A game more than 7 days past kickoff with no score is marked `canceled` and excluded.

Sources and caveats are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Generating weekly picks

```bash
python -m nflpickem update                 # refresh schedule, lines, results, pbp, injuries
python -m nflpickem predict                # next upcoming slate; creates a new run
python -m nflpickem predict --freeze       # ...and lock it as your submitted picks
python -m nflpickem predict --season 2026 --week 6 --export my_picks.csv
python -m nflpickem freeze <run_id>        # freeze an earlier run
python -m nflpickem grade                  # grade all frozen weeks -> season tracker
python -m nflpickem import-scores samples/pool_scores_template.csv   # competitor scores for the leaderboard
```

Every run records a `run_id`, `generated_at`, the **data cutoff** used for its features, the
model version, and its config. Runs are insert-only. A **frozen** run (your submission) can't
be modified or deleted, and new runs never replace it. If you re-predict a past week, the
models are retrained as of that week's cutoff, so later results can't leak in.

The default allocation gives N points to the highest-probability pick down to 1. Ties are
broken by earlier kickoff, then by `game_id`. Expected points = P(pick wins) × points.

## Matchup reports and the weekly review

```bash
python -m nflpickem report                         # markdown reports for the latest run
python -m nflpickem report --out week6_reports.md  # or a specific run with --run-id
python -m nflpickem review --season 2026 --week 6  # results vs predictions, vs market sheet, miss causes
```

**What a report contains (one per game):**

* winner and both teams' probabilities
* de-vigged market probabilities and the model − market gap
* up to 5 measured matchup factors, ranked by historical impact
* QB and offensive-line injury designations
* uncertainties and missing data
* data timestamps and sources
* the suggested confidence rank

**What the review does:**

* grades the submitted (frozen) run against results
* compares it with a market-only sheet for the same slate
* labels each miss: `data_issue`, `lineup_change`, `market_moved`, `model_deviation`,
  `coin_flip` or `variance`
* prints a calibration table across all graded weeks

Only a calibration bucket flagged `investigate` is evidence of a systematic problem.

## Feature ablation

```bash
python -m nflpickem ablation --report data/exports/abl   # ~10 min on real data
```

This runs the same walk-forward backtest with each football feature group added (units, QB
rating, matchups, all). It reports log loss and paired weekly point differences against the
base features and against the market. Groups are enabled in `config.toml` only if they help.

## Running backtests

```bash
python -m nflpickem backtest                          # dev seasons 2012–2023, fixed 70/30 blend
python -m nflpickem backtest --blend-mode learned     # weights learned from earlier OOS seasons only
python -m nflpickem backtest --seasons 2018 2019      # subset
python -m nflpickem backtest --seasons 2024 2025 --include-holdout   # untouched final test period
python -m nflpickem backtest --report data/exports/bt # also write CSV tables
```

Results go into DuckDB (`backtest_runs`, `backtest_predictions`) and appear on the
dashboard's Backtesting page.

## Dashboard

`streamlit run app/streamlit_app.py`

| Page | What it shows |
|---|---|
| **Weekly Picks** | Week selector; generate a run; per-game pick, win probability, confidence points, expected points; model, market and blend probabilities; odds timestamp and status (current, stale, closing proxy, missing); injury data status; flags; freeze; CSV export. |
| **Matchup Analysis** | Probabilities by model, market vs. model, Elo, offensive and defensive EPA, recent form chart, rest and QB context, and the logistic model's feature contributions (labelled as associations, not causes). |
| **Backtesting** | Evaluated seasons and dates, model comparison, calibration curves, season-by-season metrics, cumulative pool points, an allocation example, and the ex-post blend-ratio table. |
| **Season Tracker** | Weekly and cumulative points, accuracy, best and worst week, CSV import or manual entry of pool scores, and a leaderboard. |
| **Settings** | Provider status, which model makes the picks, blend weights and mode, calibration, scoring rules, cutoff, and refresh, retrain, backtest and demo buttons. |

Settings are saved to `settings.local.json`, which overrides `config.toml`. Delete that file
to reset.

## Automation

```bash
python -m nflpickem weekly            # update -> grade frozen weeks -> predict next slate -> export CSV
python -m nflpickem weekly --freeze   # also freeze, unless a submission already exists for that week
```

**cron (Linux/macOS)**, daily at 14:00 UTC in season:

```
0 14 * * * /path/to/nfl_pickem/scripts/weekly_job.sh >> /path/to/nfl_pickem/data/weekly.log 2>&1
```

**Windows Task Scheduler:** run `powershell -File C:\path\to\nfl_pickem\scripts\weekly_job.ps1`.

Each run is idempotent: it adds new odds snapshots, upserts games and results, and creates a
new draft run. Submitted picks are never changed. Avoid running the CLI while the dashboard is
writing; DuckDB allows a single writer.

## Tests

```bash
python -m pytest              # 91 tests, about a minute; no network or API keys needed
```

The suite covers:

* odds conversion and de-vigging
* blending and missing components
* confidence-point uniqueness, ordering and tie-breaking
* team selection, ties and void games
* feature timestamp validation and future-data leakage
* chronological train/validation/test separation
* holdout protection
* backtest reproducibility
* frozen-snapshot immutability
* nflverse parsing and idempotent ingestion, including reschedules
* Odds API parsing
* a synthetic end-to-end pipeline
* a smoke test of every dashboard page

## Project layout

```
nfl_pickem/
  config.toml            configuration (overridden by settings.local.json)
  nflpickem/
    db.py                DuckDB schema, upserts, validation
    ingest/nflverse.py   schedules, lines, play-by-play aggregation, injuries
    ingest/providers.py  odds provider interface + The Odds API adapter
    ingest/synthetic.py  labelled synthetic demo league
    features.py          point-in-time features + leakage validation
    models/elo.py        Model A
    models/ml.py         Models B and C, calibration
    models/market.py     Model D (American odds, de-vig, snapshot selection)
    models/ensemble.py   Model E (fixed/learned blend)
    confidence.py        allocation, scoring rules, grading, strategy interface
    evaluation.py        metrics, calibration, pool simulation
    backtest.py          walk-forward backtest
    pipeline.py          weekly workflow, frozen runs, export, grading, tracker
    cli.py               command line
  app/streamlit_app.py   dashboard
  scripts/               cron / Task Scheduler wrappers
  samples/               CSV schema, sample exports, pool-score template
  docs/                  FEATURES.md, DATA_SOURCES.md, MODEL_CARD.md
  tests/
```
