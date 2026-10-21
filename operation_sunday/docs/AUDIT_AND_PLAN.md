# Operation Sunday — repository audit and implementation plan

Audit date: 2026-10-21 (branch `claude/operation-sunday-weekly-ml-7ssxr7`, from `main` at `7651e4b`, Release 2.18.2).
Working tree was clean before this work; no user changes needed preserving.

## 1. What already existed

| Area | Where | What it does | Used by Operation Sunday? |
|---|---|---|---|
| **Deadeye production pricing** | `acql/model/pricing.py`, `acql/model/predictions.py` | Market line + share of Prediction-Tracker model disagreement, fitted on the season's earlier weeks | **Not touched.** Never imported. |
| **ACQL scoring rules** (authoritative) | `acql/model/backtest.py` (`LINED_FROM = 6.5`, `pool_line`, `credited_winner`), `acql/analytics.py` (`line_need`, `cover_chance`, `win_chance`, `spread_for_win_chance`) | One point per credited pick; favourite of 6.5+ carries a pool line; win by exactly the line counts | **Read-only import** (`operation_sunday/acql_rules.py`) |
| **Thursday deadline** (authoritative) | `acql/feeds/oddslock.py` (`DEADLINE = (3, 18, 0)`), lock = min(deadline, first kickoff) | Thursday 18:00 on "this computer's clock", or the week's first kickoff | Same rule re-implemented with an **explicit configurable zone** (default `America/New_York`) |
| Deadeye's own walk-forward lab | `acql/training/` (walkforward, registry, calibration, verdict, featurevalue, snapshots, devig) | Training ground for Deadeye's blend weights and calibration; reports in `CALIBRATION_AUDIT.md`, `PFM_AUDIT.md`, `WEATHER_FINDINGS.md` | Read for prior findings; not modified |
| Forecast log | `acql/model/forecastlog.py` | Outside forecasts beside Deadeye's, eligibility by cutoff before kickoff | Not modified |
| Saved Deadeye cards | `acql/pool/cards.py` → dashboard store `cards` (`data/acql-cards.json` store name; gitignored, per computer) | The cards Deadeye actually made before kickoff; `rebuilt` flag marks after-the-fact cards | **Read-only adapter** `acql_rules.load_recorded_deadeye()`; none exist in this repository checkout |
| **Challenger / research lab** | `nfl_pickem/` (standalone, DuckDB, confidence pools) | Elo, logistic, GBM, market, blend; walk-forward 2012–2023, holdout 2024–2025; ablations; Deadeye comparison (`docs/MODEL_CARD.md`, `docs/DEADEYE_COMPARISON.md`) | Reviewed; its findings informed the design. Not imported (it needs DuckDB/sklearn/LightGBM and targets **1-to-N confidence pools**, which are **not** ACQL rules). Not modified. |
| Model review / limitations | `nfl_pickem/docs/MODEL_CARD.md` "Known biases and limitations"; `acql/training/*_AUDIT.md` | Closing-line proxy is optimistic for Thursday pools; QB starters not point-in-time; weather values are observations | Each limitation is handled explicitly below |
| Data | `acql/data/nfl_scores_2010_2026.csv` (scores only, no kickoff clocks, no lines); nflverse `games.csv` (fetched: kickoffs in ET, closing lines, QB names, weather) | | nflverse `games.csv` is the training source |
| Tests / CI | `tests/*.py` (unittest, run in `.github/workflows/tests.yml` on Windows + Linux) | | New suite `tests/test_operation_sunday.py` added to CI |

### Prior evidence carried forward
* `nfl_pickem` MODEL_CARD: over 2012–2023 the de-vigged **closing** market beat every football model and blend; learned blend weights converged to ~100% market. QB rating helped the ML models but used actual starters (not point-in-time).
* The closing line is not available on Thursday, so the market's backtest advantage is optimistic for this pool.

## 2. Gaps this work fills
1. No component computed a **per-week Thursday lock** with timezone/DST handling and late-run alerts outside the dashboard UI.
2. No **immutable, hash-verified** forecast journal with revision semantics.
3. No **promotion engine** with predefined criteria, paired week-block uncertainty, and retain/fallback rules.
4. No ensemble trained strictly on **chronological out-of-fold** predictions under ACQL rules.
5. No feature-family **ablation** under ACQL scoring with point-in-time status per family.

## 3. Data available and its point-in-time status

| Field (nflverse games.csv) | Known when | Use |
|---|---|---|
| teams, gameday + gametime (ET), site, div_game, stadium roof *type* | schedule release | features |
| home/away score | after the game (+`result_delay_hours`, default 4 h) | labels; team-state updates only after publication |
| spread_line, total_line, moneylines | **closing** (kickoff) | **benchmark only** (`market_close`, `deadeye_line_proxy`) |
| home/away QB name | kickoff (actual starter) | **retrospective report slicing only** |
| temp, wind, roof closed/open | game day | **never used** |
| injuries | not stored with timestamps | not used |
| Market at Thursday | only if supplied as a timestamped snapshot (`--market`) | `market_snapshot`, `ens_market_informed`; snapshots stored in each locked package are reused later so the market accrues evidence |

## 4. Design (implemented)

```
                 ┌───────────────────────── weekly job (pipeline.run_week) ─────────────────────────┐
nflverse         │                                                                                   │
games.csv ──1──► ingest ──2──► validate ──► as_of(now) ──3──► features (point-in-time per week lock) │
 (cache on       │  (fail → cached copy     │ duplicates, bad     │ Elo, Kalman strength, rest,        │
  failure)       │   + STALE alert)         │ kickoffs, future    │ travel, site, market snapshot≤cut  │
                 │                          │ scores, canceled    │                                    │
market snapshot ─┼──────────────────────────┴─────────────────────┘                                    │
 CSV (optional)  │                                                                                     │
                 │ 4 train / 5 validate: walk-forward over dev seasons + live weeks (holdout refused)  │
                 │      base models ──► out-of-fold preds ──► ensembles (weights from earlier OOF only)│
                 │ 6 select: predefined criteria vs incumbent + baseline ──► promote / retain / fallback│
                 │      └─► experiments/<id>.json, approved.json (history, rollback)                   │
                 │ 7 forecast: fit chosen model at cutoff ──► artifact (versioned) ──► draft package   │
                 │      └─► ACQL pick (separate step; never feeds back)                                │
                 │ 8 verify ──► 9 lock (hash, on_time / LATE alert; DB triggers forbid edits)          │
                 │ 10 record results (insert-only) ──► next cycle learns from them                     │
                 └─────────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   └─► reports/<season>-REG-wNN.md   (journal.sqlite, all under data/operation_sunday/)
```

Isolation: a new top-level package `operation_sunday/`; the only imports from `acql` are the read-only rule
functions (`acql.analytics`, `acql.model.backtest`) and, optionally, reading the dashboard store for recorded
cards. All state lives in `data/operation_sunday/` (gitignored). No dashboard page, site code, or Deadeye
calculation was changed.

## 5. Plan → status
| Step | Status |
|---|---|
| Audit, plan, data flow | done (this file) |
| Weekly calendar + Thursday lock, DST, early kickoffs, postponements, late alerts | done (`schedule.py`, `tz.py`) |
| Strict cutoff fields on every forecast | done (`journal.py` schema) |
| Point-in-time features; leakage-sensitive families excluded with reasons | done (`features.py`) |
| Candidates incl. market baseline, Deadeye line-only adapter, logistic, Elo, Bayesian strength, situational, ensembles | done (`models.py`, `ensemble.py`) |
| QB model, injury model, drive simulation, tactical model | **not built** — no point-in-time data; documented (see EVIDENCE_REPORT §6) |
| Walk-forward, holdout guard, leakage tests | done (`backtest.py`, tests) |
| Selection engine with CIs, segments, ACQL points | done (`selection.py`, `metrics.py`, `acql_rules.py`) |
| Ablations | done (`ablation.py`) |
| Journal, revisions, results | done (`journal.py`) |
| Registry, artifacts, rollback | done (`registry.py`) |
| Weekly report | done (`report.py`) |
| Docs and evidence | done (`OPERATIONS.md`, `EVIDENCE_REPORT.md`) |
