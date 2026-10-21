# Feature definitions

Every feature is computed **as of the game's forecast deadline**: one hour before the earliest
kickoff of its (season, week). Only games that finished (kickoff + 4.5 h) before the deadline have
moved any state. So a Sunday game never sees that week's Thursday result, and no feature is a
season total. Code: `challenger/features.py`.

## Team ratings (per team, offence `off_` and defence `def_`)

From play-by-play scrimmage plays (`pass == 1 or rush == 1`, EPA present, kneels/spikes dropped),
aggregated per team-game in `challenger/pbp.py`:

| Metric | Definition |
|---|---|
| `epa` | EPA per play |
| `pass_epa` | EPA per dropback (sacks and scrambles included) |
| `rush_epa` | EPA per designed run |
| `success` | Share of plays with positive EPA |
| `explosive` | Passes of 20+ yards or runs of 10+ per play |
| `third` | Third-down conversion rate |
| `rz` | Touchdowns per drive that reached the opponent's 20 |
| `sack` | Sacks per dropback (for a defence: sacks made) |
| `pressure` | (Sacks + QB hits) per dropback - a proxy; missing before 2006 |
| `turnover` | Interceptions + fumbles lost per play (for a defence: takeaways) |
| `ypp` | Yards per play |
| `points` | Points scored / allowed per game (from the schedule) |

**Rating** = exponentially weighted mean over the team's games (half-life 8 games), shrunk toward
the running league mean by 4 pseudo-games; 45% of a team's evidence weight carries into a new
season. **Opponent adjustment** (epa, pass_epa, rush_epa, success): each game's value is corrected
by how good the opponent's unit was rated *before* that game.
**Form** (`*_form`) = the same EPA rating with a 3-game half-life, shrunk toward the team's own
long-run rating, minus that long-run rating.

## Quarterbacks

Per player across teams, weighted by dropbacks (half-life 400 dropbacks), shrunk toward a
replacement level (league EPA/dropback - 0.10) by 250 pseudo-dropbacks; 70% carried across
seasons. Ratings: `qb_epa` (EPA per dropback), `qb_sack`, `qb_ints`, `qb_cpoe`, `qb_rush` (designed-
run EPA per start), `qb_exp` (log career dropbacks), `qb_recent_starts` (of the team's last 6).
**Which QB**: the one who started the team's previous game (`qb_source = previous_start`) - the
only starter knowable at a Thursday deadline without timestamped injury reports. A backup who took
over mid-game last week is assumed to start; a starter returning from injury is not.

## Elo (`challenger/elo.py`)

K = 20, margin-of-victory multiplier, home advantage 55 Elo points (none at neutral sites), 60% of a
team's distance from 1505 kept over the offseason. Tuned on 2002-2009 only
(`results/elo_tuning_2002_2009.csv`). Features: `elo_diff` (home - away, without home edge),
`elo_prob`.

## Context

| Feature | Definition |
|---|---|
| `home_field` | 1 unless the game is at a neutral site |
| `h_rest`, `a_rest`, `d_rest` | Days since each team's previous scheduled game (capped at 21) |
| `*_short_week`, `*_off_bye` | Rest < 6 days; rest 13-20 days |
| `d_travel` | (away travel - home travel) / 1000 km, great-circle from each team's season home stadium to the venue |
| `*_tz_shift`, `d_tz` | Venue UTC offset minus home-base offset; difference of absolute shifts |
| `roof_indoor` | 1 dome, 0.5 retractable (open/closed decided on game day), 0 outdoors |
| `turf` | 1 for artificial surfaces |
| `div_game`, `playoff`, `week` | From the schedule |

## Differences and matchups (`add_differences`)

`d_off_m`, `d_def_m` = home minus away; `d_net_m` = net unit edge (offence produced minus defence
allowed, sign-flipped for sack/pressure/turnover so positive is always good for the home team).
Matchups: `mu_epa`, `mu_pass_epa`, `mu_rush_epa`, `mu_success` = (home offence + away defence
allowed) - (away offence + home defence allowed); `mu_pass_rush` (pass-vs-run tendency interaction);
`mu_protection` (each passer's exposure: own line's pressure allowed + the other side's pass rush);
`d_form`; `d_qb_*`.

## What each model sees

* **Logistic** (`LR_FEATURES`, chosen before any backtest): elo_diff, home_field, d_net_epa,
  d_net_success, d_net_points, d_qb_epa, mu_pass_epa, mu_rush_epa, d_net_turnover, d_form, d_rest,
  d_off_bye, d_short_week, d_travel, d_tz.
* **Gradient boosting**: every `d_*` and `mu_*` column plus elo_diff, elo_prob, home_field,
  div_game, playoff, week, roof_indoor, turf, season-games counts, QB experience, time-zone shifts,
  and both teams' offensive/defensive EPA levels (73 columns).
* **Stack (Challenger)**: logistic regression on the three models' calibrated logits.
* **Never seen** by the market-free models: any betting line, total or moneyline, any Deadeye
  number, observed weather, the actual starting QB, injury reports.
