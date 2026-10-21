# Data sources

Raw files are cached under `data/challenger/` (git-ignored; `python -m challenger fetch` rebuilds
it). Every download is fingerprinted in `data/challenger/manifest.json` (URL, UTC retrieval time,
bytes, SHA-256), and every stored backtest copies that manifest into its own `.manifest.json`.

## 1. nflverse schedule (`schedules/games.csv`)

| | |
|---|---|
| Source | https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv |
| Licence / access | Public release file from the open-source nflverse project; no key needed. Check nflverse's licence notes before redistributing - this repository does not commit the raw file. |
| Coverage | 1999-2026, 7,548 games (REG, WC, DIV, CON, SB). |
| Update frequency | Rebuilt by nflverse several times a week in season (results, lines, QBs). |
| Availability timestamps | None per row. Our retrieval time is recorded; the file itself is a current snapshot, not an archive. |
| Missingness | Kickoff time missing for all 259 games of 1999 (13:00 ET assumed, flagged `kickoff_assumed`; used only for Elo warm-up). Roof missing for 29 games, surface for 72. Stadium id never missing. Moneylines: none before 2006; 82% (2006), 100% (2007), 73% (2008), 95% (2009), then complete. |
| Used by Challenger | Teams, dates/times, venue (`stadium_id`), neutral site, roof, surface, divisional flag, final scores (only for games already finished at a forecast's deadline). |
| Not used by the market-free model | `spread_line`, moneylines, totals and their odds (market columns); `temp`/`wind` (observed, not forecast); `home_qb_id`/`away_qb_id` (the QB who actually started - known only near kickoff). |
| Known limitations | Lines are **closing** lines. Scores and QBs can be corrected retrospectively. Relocated franchises (STL->LA, SD->LAC, OAK->LV) are merged into one identity. |

## 2. nflverse play-by-play (`pbp/play_by_play_<season>.parquet`)

| | |
|---|---|
| Source | https://github.com/nflverse/nflverse-data/releases/download/pbp/ (nflfastR) |
| Licence / access | Public release files; raw files not committed here. |
| Coverage used | 2001-2026; every completed game since 2001 (6,851) has play-by-play. |
| Update frequency | Current season updated nightly in season; past seasons occasionally rebuilt. |
| Availability timestamps | None per play. A game's plays are treated as usable 4.5 hours after its kickoff. |
| Missingness | Red-zone rate missing for 2.6% of team-games (no drive reached the 20). Pressure proxy missing for 19.4% of team-games - every game before 2006, when QB hits were not charted. |
| Known limitations | **Retrospective model**: EPA, success and CPOE come from nflfastR's *current* models, fitted on many seasons - including seasons after the games being predicted. The as-of-then values cannot be recovered. The `no_epa` variant measures how much the EPA features contribute (on the holdout: not significantly). |

## 3. Data used only in the evaluation stage (`challenger/arena`)

| Data | Source | Role | Caveats |
|---|---|---|---|
| Closing spread, moneylines | nflverse schedule | Market baselines; pool-line reconstruction; `deadeye_core_closing` | Closing, i.e. after the ACQL deadline. |
| `acql/data/nfl_scores_2010_2026.csv` | Deadeye's own file | Deadeye's backtest proxy (`acql.model.backtest`) | Ends at 2026 week 2, so the proxy cannot price 2026 weeks 3+. |
| `nflpredictions week 3/4/5/7.csv` | Prediction Tracker weekly files kept by the dashboard | Deadeye's full live rule, via `acql.model.pricing` | First committed after week 3/4/5's first kickoffs (week 4's after its Sunday games); week 7's before kickoff. |
| `acql-picks.json` | The pool's pick sheets | Real lines and every coach's picks for 8 weeks | Coach names are never written to any output. |
| `acql/data/pool_weeks.json` | Deadeye's stored card results | Shown beside the real-sheet table | Deadeye's own replay "with the closing betting lines", per the file. |

## 4. Considered and excluded

| Data | Why excluded |
|---|---|
| Injury reports (nflverse `injuries`) | Only the final weekly status with a `date_modified` that can postdate the game; a Thursday-deadline status cannot be reconstructed. |
| Depth charts | Weekly snapshots without reliable as-of times for past seasons. |
| PFR pressure / FTN charting | Start in 2018 / 2022 - too short for training, and would break the feature definition mid-history. |
| Observed weather | Not knowable at the deadline; archived forecasts are not available. |
| Prediction Tracker archives | Not reachable from this environment (Cloudflare challenge); and they are model outputs, which Challenger would not use anyway. |
