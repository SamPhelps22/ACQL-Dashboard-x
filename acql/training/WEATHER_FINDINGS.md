# Does weather beat the market? (2026-10-18)

**Verdict: no.** Once you know the closing spread, adding wind, temperature and
roof type makes win predictions slightly *worse*, not better. The one
narrow case that looks good (wind 20 mph or more) is too small and too
fragile to trust. Don't add weather to Deadeye on this evidence.

## What was tested
- **Data:** the nflverse games file already on disk (no download, no new key).
  It has roof type plus game-day temperature and wind from Pro Football
  Reference. 7,339 finished games from 1999 on: 5,236 outdoor with weather,
  1,835 indoor (dome or closed roof), and **268 marked missing** (outdoor with no
  reading or an impossible one, or no roof listed). Most of the missing ones are
  in 2022–23. Nothing was guessed.
- **Not tested: rain and snow.** That file has no precipitation. Adding it would
  mean a new source (e.g. a free historical weather archive). Sam needs to OK
  that first.
- **Models:** home win chance from (a) the closing spread alone, (b) spread +
  wind, cold, heat, outdoor, and how each one shrinks the favourite's edge,
  (c) spread + wind only. Each season from 2006 to 2025 was predicted using a
  model trained only on the seasons before it. That gives 5,179 games scored,
  all on the same games.

## Numbers (lower is better)
| model | log loss | Brier |
|---|---|---|
| market only | **0.6084** | **0.2106** |
| market + all weather | 0.6101 | 0.2113 |
| market + wind only | 0.6086 | 0.2107 |

Full weather costs 0.0017 log loss (90% interval −0.0028 to −0.0006,
resampling whole seasons). Wind alone also costs a little (−0.0002). Both are
reliably no better than the market.

By slice (log-loss change vs market; positive means weather helped):
- indoor −0.0019, outdoor calm −0.0016, wind ≥15 mph (463 games) −0.0016
- wind ≥20 mph (116 games): full model **+0.0092**, but the wind-only model
  is −0.0023 there. On ~6 games a year, that reads as noise.
- below 25°F (109 games): **−0.0265**. The cold term actively hurts.

## Sensitivity: how much would weather move a pick?
Fitted on all seasons, for an outdoor game:
- A 3-point home favourite: 61.6% when calm. At 20 mph wind, 58.5%; at 30 mph, 57.0%.
  At 0°F, 65.6%.
- A 7-point favourite: 74.7%. At 30 mph wind, 68.4%.

So the fitted effects are a few points, but they don't hold up when scored on
seasons the model hasn't seen. The market already prices the weather in
(lines move when the forecast does).

## Implication for the dashboard
Showing weather as context is fine, but it shouldn't move Deadeye's numbers.
The one open question is precipitation.

Reproduce: `python -m acql.training.weather` (code in `weather.py`).
