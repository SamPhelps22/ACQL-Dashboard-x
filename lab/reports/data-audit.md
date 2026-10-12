# Data audit: historical dataset for Deadeye's walk-forward backtest

Written 2026-10-12, before any dataset code. Production code (`acql/`) is not
changed by this work. Every finding below was checked against the files or
the live source; nothing is estimated.

## 1. Sources

| Source | What it gives | Time information | Status |
|---|---|---|---|
| nflverse `nfldata` `data/games.csv`, pinned to commit `76dcc8587f94` (sha256 `54024613…bd93`) | Every game since 1999: game id, season, week, game type, teams, neutral site, kickoff date + time (Eastern), final scores; `spread_line`, `total_line`, home/away moneylines | Kickoff times: yes. **When each line was taken: not stated anywhere in the repo's docs.** | Reachable; used |
| `acql/data/nfl_scores_2010_2026.csv` (in repo) | Final scores 2010–2026, team abbreviations | Dates without kickoff times | Used only to cross-check scores |
| `data/acql.db` kind `odds` (The Odds API, fetched by the app) | Spreads (median over books), home side positive | **Each update timestamped** when the app fetched it | 2026 weeks 3–5 only; spreads only (no moneylines, no totals) |
| `data/acql.db` kind `forecasts` + repo `nflpredictions week N.csv` | Prediction Tracker files: market `line`/`lineopen` and one column per computer model | The app recorded when it imported each file (`imported`). **No publication time in the file.** | Model columns for 2026 weeks 3–5 only. Weeks 1–2 are typed market lines with no time (`imported` = 0) |
| `data/acql.db` kind `spreads` | Spreads typed in by hand | **None** | 2026 weeks 1–5 |
| `data/acql.db` kind `picks` | The pool's own pick sheets, including the commissioner's line notes ("(gb by 7)") | When the app imported the sheet (always after the week). **No posting time for the lines.** | Store key is the week only. Slate matching puts them in 2023 weeks 8, 10, 11, 13; 2025 weeks 15–17; 2026 weeks 1–5 |
| `ACQL Dashboard.xlsx` row 8 | The same line notes for 2026 weeks 1–5 | None | Note counts match the pick sheets week for week (3, 7, 6, 4, 4); not imported separately |
| The Prediction Tracker website | Past seasons' forecasts | — | **HTTP 403 from this environment.** Not checked whether archives exist |
| Pro-Football-Reference | Closing lines | — | **HTTP 403** |
| The Odds API historical endpoint | Timestamped historical odds | — | Needs a paid key. The app's stored key is not used |
| Covers, TeamRankings | Closing lines / summary tables | — | Not used (terms restrict automated access; TeamRankings has no per-game rows) |

Checks run:
- The three repo Prediction Tracker CSVs are identical to what the app
  stored (same games, market, opening and model values, in order). So their
  model names can be paired with the app's recorded import times. Imports:
  - week 3: 2026-09-24 21:58 UTC;
  - week 4: 2026-09-30 21:25 UTC;
  - week 5: 2026-10-07 22:19 UTC.
  Each import is before that week's first kickoff.
- nflverse kickoff times (Eastern, converted with the app's own DST rule,
  `oddslock._eastern_hours`) equal the app's ESPN-recorded kickoffs for all
  16 games of 2026 week 3.
- nflverse documents `spread_line` as positive when the home team is
  favoured, which is Deadeye's convention. No sign conversion is needed.

## 2. What this means for each requirement

| Requirement | Can it be met? |
|---|---|
| Game identity and outcomes | Yes, 1999–2026, from nflverse; scores cross-checked against the repo's CSV |
| Spreads/moneylines/totals, latest snapshot at or before the cutoff | **Verified only for 2026 weeks 1–5 spreads.** The undated nflverse lines are kept, but quarantined in separate `*_unverified` fields and flagged; they never fill a verified field |
| Individual model forecasts with source, publication time and retrieval time | 2026 weeks 3–5 only. Publication time: not available in any source (stored as NULL, flagged). Retrieval: the app's import time, stated as an upper bound |
| Pool line and scoring rules as known at the cutoff | Lines: 2023 weeks 8–13, 2025 weeks 15–17, 2026 weeks 1–5, all flagged because no posting time exists. Rules: see §3 |
| Flags, coverage report, leakage tests | Yes |

Consequence: until historical Prediction Tracker files and timestamped odds
exist, **no season before 2026 can support a verified Deadeye-vs-market
comparison.** The dataset makes that explicit per record instead of filling
the gap.

## 3. Pool rules

Recorded only where the repo has evidence:

- **Pool line.** The favourite must win by at least the line; a win by
  exactly a whole-number line goes to the favourite (`analytics.line_need`).
  The cited evidence is the graded 2025 week 15 sheet, "(sf by 13)", 49ers
  37–24. Records before that week are flagged "rules not verified for this
  period".
- **Straight-up games.** The winner is credited. How a tie is graded is not
  documented anywhere in the repo, so it is recorded as unknown.
- **Unknown field.** `acql/data/pool_weeks.json` has a field `old_rule`
  (for example, 2025 week 15: model 7, old_rule 5). No code reads it and
  nothing documents it, so the earlier rule it implies is **unknown and not
  encoded**. Sam should say what it was.
- **Pool's real pick deadline.** Not recorded anywhere. The dataset builds two
  cutoffs:
  - `week_lock`: the week's first kickoff, which is production's
    `oddslock.py` rule;
  - `kickoff`: each game's own kickoff.

## 4. Traps found while auditing

- **Store migration.** Never open `data/acql.db` through `acql.store` or
  `predictions.load()`: in a fresh checkout that re-imports the legacy JSON
  and rewrites the database (see CLAUDE.md). The dataset reads it with a
  read-only SQLite URI and copies out only the kinds it needs.
- **API key in the store.** The `odds` kind also holds the API key (`odds`/`key`), and
  `settings` holds sealed tokens. The extract excludes both.
- **No season in store keys.** Store keys for `forecasts`, `odds`, `spreads`
  and `picks` are week numbers without a season. The season is inferred by
  matching each slate against the schedule, and a record is flagged when
  the match is partial.
- **No license file in nflverse.** `nfldata` has no LICENSE file, so its raw
  data is not committed. The lock file pins the commit URL and sha256, so
  identical bytes can be re-downloaded and verified.

## 5. Build plan

1. `lab/history/`: a separate package that production never imports. It
   reuses `acql.predictions.read_csv` / `team_code`, `acql.lines.line_from_note`
   and `acql.oddslock._eastern_hours`, all read-only.
2. Raw inputs go in `lab/data/raw/` (gitignored), with sha256 values pinned in
   `lab/history/sources.lock.json`.
3. The SQLite output is `lab/data/history.db`, with these tables: `sources`,
   `games`, `outcomes`, `odds_snapshots`, `model_forecasts`, `pool_lines`,
   `pool_rules`, `prediction_records`.
4. Each prediction record is one game at one cutoff. It holds no outcome
   columns. Its fields come from the latest row whose availability time is at
   or before the cutoff. Rows with no availability time never fill a verified
   field.
5. `verify` rebuilds every record from the tables and checks it is
   identical, which proves each record is reproducible.
6. Leakage tests run on a synthetic database, with no network.
7. A coverage report goes in `lab/reports/coverage.md`.
