# Feature definitions

Every feature is computed for a game **as of its prediction cutoff**.

* **`slate` mode (default):** the cutoff is the first kickoff of that season-week minus
  `pool.cutoff_offset_hours`. All of a week's picks lock together, as in a typical pool.
* **`per_game` mode:** the cutoff is each game's own kickoff minus the offset.
* **Live predictions:** the cutoff is also capped at "now".

A team's performance state after a game becomes available at kickoff + 4 hours. Features are
joined using the latest state available **strictly before** the cutoff (`merge_asof`, direction
`backward`, exact matches excluded). `features.validate_point_in_time` asserts all of the
following and raises `LeakageError` otherwise:

* team-state timestamp < cutoff
* odds capture time ≤ cutoff
* cutoff ≤ kickoff

`tests/test_features.py::test_no_future_leakage...` checks this directly. It rewrites every
result and EPA value after a pivot date, then verifies that no feature before the pivot changes.

All "diff" features are **home minus away**.

## Team-strength features

| Feature | Definition |
|---|---|
| `elo_diff` | Home pre-game Elo − away pre-game Elo (see Elo model). The home-field advantage is *not* included. |
| `home_field` | 1 for a true home game, 0 for a neutral site (`location == "Neutral"`, e.g. London or Super Bowl). |
| `off_epa_l4_diff`, `off_epa_l8_diff` | Mean offensive EPA/play over each team's last 4 / last 8 completed games, across season boundaries. While a team has fewer than k games available, `shrinkage_games × (k − n)/k` pseudo-games at the prior league mean are added. |
| `def_epa_l4_diff`, `def_epa_l8_diff` | The same for EPA/play **allowed**. Lower is better defence. |
| `off_epa_season_diff`, `def_epa_season_diff` | Season-to-date mean shrunk toward a prior: `(Σx + m·prior)/(n + m)` with `m = shrinkage_games`. The prior is the previous season's league mean plus `prior_season_weight × (the team's previous-season mean − league mean)`. In week 1 this equals the prior. |
| `success_l8_diff`, `def_success_l8_diff` | Success rate (nflverse `success`, i.e. EPA > 0) on offence / allowed, last 8, shrunk as above. |
| `explosive_l8_diff`, `def_explosive_l8_diff` | Share of plays that are explosive (rush ≥ 10 yards or pass ≥ 20 yards), last 8. |
| `turnover_l8_diff` | Giveaways per offensive play (interceptions + lost fumbles), last 8. |
| `takeaway_l8_diff` | Takeaways per defensive play, last 8. |

Plays counted for EPA are `play_type` pass or run with a non-missing EPA, excluding kneels,
spikes and two-point attempts. The league-mean prior for a season is the previous season's
league average, so it is always available before the season starts.

## Schedule and situation features

The published schedule is known in advance, so these features carry no leakage.

| Feature | Definition |
|---|---|
| `rest_diff` | Home rest days − away rest days. Rest is the days since the team's previous game in the same season, capped at 14. A team's first game of the season counts as 14. |
| `home_short_week`, `away_short_week` | Rest ≤ `short_rest_days` (default 5), e.g. Thursday after Sunday. |
| `home_off_bye`, `away_off_bye` | Rest ≥ `bye_rest_days` (default 13) within the same season. |
| `early_season` | Regular-season week ≤ `early_season_weeks` (default 4). Signals higher uncertainty. |
| `week` | Season week number (postseason weeks continue the numbering). |
| `is_postseason` | 1 for WC/DIV/CON/SB games. |
| `div_game` | Divisional game indicator from the schedule. |
| `dome` | Roof is `dome` or `closed`. |

## Quarterback features (`features.use_qb_features`, default on)

| Feature | Definition |
|---|---|
| `home_qb_changed`, `away_qb_changed` | 1 if the starter listed for this game differs from the team's starter in its last game available before the cutoff. |
| `qb_exp_diff` | log(1 + prior starts) for the home starter − the same for the away starter. Prior starts are counted across all teams in the database, before the cutoff. |

**Timing caveat:** for completed games, nflverse lists the *actual* starter. That is confirmed
roughly 90 minutes before kickoff, so for a pool that locks on Thursday it may not have been
known at pick time. For upcoming games the listed starter is nflverse's *projected* starter.
`quarterback_status` records `confirmed_starter`, `projected_starter` or `unknown`. Injury
designations are shown in the dashboard but are not used as model inputs (see the limitations
in the model card).

## Market features

| Feature | Definition |
|---|---|
| `market_home_prob` | De-vigged home win probability from the latest snapshot at or before the cutoff. When several bookmakers are available, their de-vigged probabilities are averaged. If there is no moneyline, it falls back to the spread via Φ(−spread/13.45). |
| `market_home_spread` | Home spread in sportsbook notation (negative means the home team is favoured). |

By default these feed the **market model** and the **blend**, not the ML models
(`ml_include_market_features = false`). That keeps the ML models independent of the market,
so the blend combines two different sources of information. Set the option to true to give the
ML models the market inputs as well.

## Weather (`features.use_weather`, default off)

`wind` and `temp` come from nflverse. For dome or closed roofs they are set to 0 mph and 70°F.
They are off by default because historical values are *observed* conditions, not forecasts,
and they are blank for upcoming games.

## Labels

`home_result` is 1 for a home win, 0 for an away win, 0.5 for a tie, and NaN for an unplayed
game. Ties are excluded from classifier training and from accuracy, log-loss and Brier
calculations. In pool scoring they follow `pool.tie_rule`.
