# Operation Sunday — operating guide

## Commands

```bash
python -m operation_sunday calendar --season 2026          # every week's lock and run-due time
python -m operation_sunday run                              # the weekly job for the next week (fetches data)
python -m operation_sunday run --market snapshots.csv       # ...with a Thursday market snapshot
python -m operation_sunday run --no-fetch --games games.csv # offline, from a local file
python -m operation_sunday run --no-lock                    # draft only (can be regenerated)
python -m operation_sunday status --season 2026 --week 8    # packages, hashes, alerts
python -m operation_sunday check-deadline                   # exit code 2 if a deadline was missed or late
python -m operation_sunday backtest [--seasons ...]         # walk-forward evaluation (holdout refused)
python -m operation_sunday ablation                         # feature-family ablations
python -m operation_sunday rollback --reason "..."          # back to the previous approved model
```

State lives in `data/operation_sunday/` (override with `OPERATION_SUNDAY_STATE`):
`journal.sqlite`, `approved.json`, `experiments/`, `artifacts/`, `reports/`, `cache/games.csv`,
`holdout_access.jsonl`.

## Scheduling

* **Deadline** = Thursday `deadline_hour:deadline_minute` in `timezone` (default 18:00 America/New_York — the
  dashboard's `oddslock.DEADLINE`), or the week's earliest non-canceled kickoff minus `kickoff_margin_minutes`
  if that is sooner. Computed per week from that week's fixtures and that date's UTC offset, so Wednesday
  openers, Thanksgiving, Christmas, international games and postponements are handled. Check with
  `calendar`.
* **Run due / lock window** = lock − 3 h (`run_lead_hours`, `lock_window_minutes`). With the default
  `run` (lock = auto), runs before the window only refresh the draft (one package, replaced in place); the
  first run inside the window locks it. `--lock-now` locks immediately; `--no-lock` never locks.
* **Scheduled on Windows by `schedule.ps1`** (task "ACQL Operation Sunday"): daily, every 2 hours from
  9 AM to 9 PM, waking the PC, with `--log` (output and tracebacks go to `data/operation_sunday/run.log`).
  Every scheduled run also performs the missed/late-deadline check. Re-run
  `powershell -ExecutionPolicy Bypass -File schedule.ps1` once to register it; `-Remove` removes it with
  the others. Other systems: `operation_sunday/scripts/weekly.sh` from cron every 2 hours, 9-21 local.
* **Market snapshot**: read automatically from the dashboard's stored Odds API fetches (the noon
  "ACQL Deadeye email" task fetches Tue/Wed/Thu; "Update lines" fetches on demand). The last fetch before
  the cutoff is used, with its fetch time as `taken_at`; no extra requests are spent. Commissioner pool
  lines typed into the dashboard are used for ACQL picks ahead of the habit rule. A week with no
  pre-cutoff line raises a `NO MARKET SNAPSHOT` alert. `--market file.csv` adds or overrides snapshots.
* A run that starts after `run_due` is labelled `late_start`; after the lock, `LATE RUN` — the package is
  stored with `on_time = 0`, the real lock time, and an alert. Games that already kicked off get no forecast.
  Nothing is backdated.

## Settings (`operation_sunday/settings.json`, optional)

```json
{"timezone": "America/New_York", "deadline_weekday": 3, "deadline_hour": 18, "deadline_minute": 0,
 "kickoff_margin_minutes": 0, "run_lead_hours": 12, "designated_baseline": "elo",
 "dev_eval_seasons": [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
 "holdout_seasons": [2025],
 "promotion": {"min_games": 500, "min_weeks": 30, "min_logloss_gain": 0.002, "max_ece": 0.035}}
```
Changing `promotion` changes its digest, which every experiment records.

On Windows without time-zone tables, the mainland US zones use the built-in DST rule; other zones need
`pip install tzdata`.

## Data requirements

* **Games** (required): nflverse `games.csv` columns `game_id, season, game_type, week, gameday, gametime,
  away_team, home_team, away_score, home_score, location, div_game, roof, stadium_id`; optional
  `spread_line, total_line, *_moneyline` (benchmarks only) and `*_qb_name` (report slicing only).
* **Market snapshot** (optional, recommended): CSV `game_id, taken_at, home_prob, home_spread, source`.
  `taken_at` must carry a time zone; rows after the cutoff are ignored and flagged. `home_spread` > 0 means
  the home team is favoured; it also gives the ACQL pool line (6.5+ rule). Without it, picks are made
  straight-up and flagged `pool_line_unknown_no_spread_at_cutoff`.

## Recovery

| Situation | What happens / what to do |
|---|---|
| Download fails | Cached copy used with a STALE/INGEST alert; no cache → run stops before forecasting. Re-run. |
| Run interrupted mid-way | Next run marks stale stages `interrupted`, regenerates the draft in place (one package, no duplicates). |
| Chosen model fails at forecast time | Designated baseline used; package `fallback` field and an alert say so. |
| Missed run | `check-deadline` exits 2. Run immediately: package is locked late and labelled late. |
| Wrong forecast discovered after lock | Never edit. Create a revision with a reason (`Journal.create_revision`); the original stays official and is evaluated separately. |
| Bad promotion | `rollback --reason ...` restores the previous approved model; history keeps both events. |
| New information after lock | `Journal.note(...)` for monitoring; the locked package does not change. |
| Replaying a past Thursday | `run --now <ISO>`: stored as `mode = replay` (simulated time + real `recorded_at`), never counted as live. |

## Promotion rules (predefined)
A candidate replaces the approved model only if it is Thursday-eligible, has ≥ `min_games` games and
≥ `min_weeks` weeks of matched out-of-sample predictions, beats the incumbent **and** the designated baseline
by ≥ `min_logloss_gain` log loss with the 95% paired week-block bootstrap interval entirely below zero, and is
calibrated (ECE within `max_ece` plus a small-sample allowance; recalibration slope in range). Otherwise the
incumbent stays; with no incumbent, the designated baseline is used and disclosed as a fallback.
