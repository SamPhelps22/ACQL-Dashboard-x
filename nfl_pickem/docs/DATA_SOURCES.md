# Data sources

| Data | Source | Credentials | Update frequency | Used for |
|---|---|---|---|---|
| Schedules, scores, game type, location, rest, roof, weather, starting QBs, **closing/current moneylines and spreads** | nflverse `games.csv` — `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv` | none | Several times a week in season | `games`, `odds_snapshots` (provider `nflverse`) |
| Play-by-play (EPA, success, yards, turnovers) | nflverse release `pbp/play_by_play_{season}.parquet` | none | Nightly in season | Aggregated to `team_game_stats` |
| Injury reports | nflverse release `injuries/injuries_{season}.csv` | none | Weekly in season (reports appear Wed–Fri) | `injuries`; QB designations shown in the dashboard |
| Live odds snapshots (optional) | The Odds API v4 `/sports/americanfootball_nfl/odds` (`markets=h2h,spreads`, American odds) | `ODDS_API_KEY` (free tier available) | Every time you run `update`; each run adds timestamped snapshots per bookmaker | `odds_snapshots` (provider `the_odds_api:<book>`) |
| Synthetic demo league | `nflpickem/ingest/synthetic.py` | none | Generated on demand | Offline demo and tests only. Clearly labelled; teams `SYN01…`, seasons 2101+ |

## Coverage observed when this project was built (October 2026)

| Data | Coverage |
|---|---|
| Spreads | Every game 1999–present |
| Moneylines | About 82% of 2006 games, partial for 2007–2009, ~100% from 2010 |
| Play-by-play | 1999–present (this project ingests 2006 onward by default) |
| Injury reports | Current season available |
| Upcoming games | Lines appear in `games.csv` once nflverse records them. For Week 6 2026, 2 of 15 games had no line yet; those are flagged `NO_ODDS` |

## Limitations

* **Historical lines are closing lines with no timestamp.** They are stored with
  `captured_at = NULL` and `is_closing = TRUE`. With `data.closing_line_proxy = true` (the
  default) they stand in for the line at pick time and are flagged `closing_proxy`. A closing
  line contains slightly more information than a Thursday line, so backtested market
  performance is mildly optimistic for a pool that locks before the first game of the week.
  Set `closing_line_proxy = false` to refuse untimestamped lines; historical games then have
  no market input.
* **Current lines from `games.csv`** are stamped with the time *we downloaded them*, which is
  truthful but later than when nflverse captured them. They are a consensus line, not a
  specific bookmaker's.
* **Upcoming starting QBs** in `games.csv` are projections and can be wrong.
* **Weather** is observed game-day weather for past games, and blank for upcoming games.
* **The Odds API** quota depends on your plan. Historical odds are a paid endpoint and are
  not used here.
* Team relocations are normalised to current codes: OAK→LV, SD→LAC, STL→LA.

## Adding a provider

Subclass `OddsProvider` in `nflpickem/ingest/providers.py`, implement `available()` and
`fetch(games)`, and return rows in the `odds_snapshots` layout. Register the class in
`ODDS_PROVIDERS` and select it with `data.odds_provider`. If the provider is unconfigured or
unreachable, `update` logs the error and falls back to nflverse lines. Predictions still run,
with games flagged `NO_ODDS` where no line exists.
