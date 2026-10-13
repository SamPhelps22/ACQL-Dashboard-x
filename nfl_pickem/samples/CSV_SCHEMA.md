# CSV schemas

## Picks export (`predict`, `weekly`, Weekly Picks → Export CSV)

One row per game, sorted by `confidence_points` descending.

| Column | Type | Meaning |
|---|---|---|
| `data_label` | text | `nflverse data` or `SYNTHETIC DEMO - NOT REAL NFL` |
| `season`, `week` | int | NFL season and week (postseason weeks continue the numbering) |
| `game_id` | text | Stable nflverse id `SEASON_WEEK_AWAY_HOME` |
| `kickoff_utc` | timestamp | Kickoff in UTC |
| `away_team`, `home_team` | text | Current franchise codes |
| `selected_team` | text | Your pick |
| `confidence_points` | int | Unique value, N…1. 0 means excluded or canceled |
| `selected_team_probability` | float | Win probability of the pick, from the model used for picks |
| `expected_points` | float | `selected_team_probability × confidence_points` |
| `blended_home_probability` | float | Blend (Model E) home win probability |
| `market_home_probability` | float | De-vigged market probability. Blank means no odds |
| `elo_home_probability`, `logistic_home_probability`, `gradient_boosting_home_probability` | float | Individual model probabilities |
| `odds_status` | text | `current`, `stale`, `closing_proxy` or `missing` |
| `odds_captured_at` | timestamp | When the odds snapshot was observed. Blank means a closing line with no timestamp |
| `injury_status` | text | QB injury designations from the injury report, `no QB designations`, or `no injury data` |
| `data_flags` | text | `NO_ODDS`, `STALE_ODDS`, `CLOSING_LINE_PROXY`, `QB_UNKNOWN`, `EARLY_SEASON`, `NO_TEAM_HISTORY`, `QB_INJURY_REPORTED`, or `ok` |
| `model_version` | text | `v<package>-<trained-through date>-<hash>` |
| `generated_at` | timestamp | When the run was produced (UTC) |
| `run_id` | text | Prediction run id. Freeze it to mark it as your submission |

## Example files

| File | Contents |
|---|---|
| `sample_export_real_2026_wk06.csv` | A real export for 2026 Week 6, generated 2026-10-13 from nflverse data |
| `sample_export_SYNTHETIC.csv` | An export from the synthetic demo league |

## Pool scores import (`import-scores`, Season Tracker page)

| Column | Required | Meaning |
|---|---|---|
| `season` | yes | Season |
| `week` | yes | Week |
| `participant` | yes | Name in your pool |
| `points` | yes | That participant's points for the week |
| `is_me` | no | `true` for your own row |

`pool_scores_template.csv` is a filled example for the synthetic 2108 season.
