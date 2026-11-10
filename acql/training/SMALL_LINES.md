# What a small betting line has really meant (2026-11-10)

**Verdict: a line of a field goal or less is read down before Deadeye prices it.** A small, one-directional
gain in how honest the chances are. It is not an edge over the market and it was not sold as one.

Reproduce: `python -m acql.training.smalllines` (needs `data/nflverse/games.csv.gz`;
`python -m acql.model.seasonsim --fetch` gets it). Code: `smalllines.py` here, `analytics.meant_margin` in use.
Tests: `python tests/test_seasonsim.py`.

## Where it came from

The calibration audit (CALIBRATION_AUDIT.md, 2026-10-18) left one thing to look into: narrow favourites won
less often than the curve said, at every timing. This follows that up on nflverse's closing lines - 7,103
regular-season games, 1999 to week 9 of 2026, 5,201 of them with moneylines (2006 on).

| Line | Games | Won by, on average | Won | Curve at the line | Moneylines said |
|---:|---:|---:|---:|---:|---:|
| 1 | 536 | +0.2 | 51.5% | 53.9% | 52.5% |
| 1.5 | 208 | +0.2 | 53.8% | 55.8% | 53.2% |
| 2 | 159 | +2.9 | 58.5% | 57.7% | 54.3% |
| 2.5 | 516 | +1.0 | 53.7% | 59.6% | 56.4% |
| 3 | 1,139 | +2.8 | 58.6% | 61.4% | 59.6% |
| 3.5 | 674 | +4.3 | 63.2% | 63.2% | 63.0% |
| 4 | 324 | +4.2 | 66.0% | 65.0% | 65.1% |
| 4.5 | 265 | +5.1 | 66.8% | 66.7% | 66.6% |
| 7 | 475 | +8.8 | 76.2% | 74.5% | 73.5% |
| 10 | 204 | +10.5 | 81.4% | 82.0% | 80.0% |

Two different witnesses say the same thing below 3.5. The **moneylines** - the market's own answer to "who
wins", with thousands of games behind each row and no luck in them - sit two to three points of chance under
the curve at 1 to 3. And the **results** agree with the moneylines, not the curve (the 2-point row, 159 games,
is the one exception and the thinnest row there). From 3.5 up the curve and the moneylines are level.

The reason is the number 3. Books are slow to move a line onto or off it and move the price beside it
instead, so a team laying 2.5 has won by a point on average, not two and a half; a team laying 3.5 by four.
The line is not the expected margin there. The curve's shape was never the problem - what it was handed was.

## What was changed

`analytics.meant_margin(line) = line × (1 − 0.5 × exp(−(|line| / 2.875)⁴))`, applied to the market's number
in `pricing.reading` before the moneyline or the models are added, and in `Forecast.expected` (the share's
fit and the training ground's copy of the recipe). The two numbers were fitted to **moneylines only** (the
margin at which the curve gives each game's no-vig chance; 5,104 games on lines of 14 or less), never to
results.

| Line | Read as | Favourite's chance before | after |
|---:|---:|---:|---:|
| 1 | 0.51 | 53.9% | 52.0% |
| 2 | 1.21 | 57.7% | 54.7% |
| 2.5 | 1.79 | 59.6% | 56.9% |
| 3 | 2.54 | 61.4% | 59.7% |
| 3.5 | 3.31 | 63.2% | 62.5% |
| 4 | 3.95 | 65.0% | 64.8% |
| 5 and up | unchanged | | |

## Scored on results

Each season read with numbers fitted on the moneylines of earlier seasons only. Log loss a game; + is better
with the reading; 95% range from redrawing whole weeks.

| Games | Count | Gain | 95% range |
|---|---:|---:|---|
| 2010-2026 | 4,297 | +0.00058 | −0.00015 to +0.00133 |
| lines of 3 and under | 1,610 | +0.00158 | −0.00034 to +0.00350 |
| lines over 3 | 2,687 | −0.00002 | −0.00022 to +0.00019 |
| 2010-2018 | 2,297 | +0.00067 | −0.00019 to +0.00155 |
| 2019-2026 | 2,000 | +0.00048 | −0.00066 to +0.00163 |
| 1999-2009, games with no moneyline to fit to | 1,900 | +0.00030 | −0.00095 to +0.00154 |

Where there is a moneyline (5,186 games): the curve at the line 0.60874, the curve with the reading 0.60802,
the moneyline itself 0.60900.

## How to read that

- **The gain is small and its range touches zero.** It is nowhere near the Model Lab's 0.010 bar for switching
  recipes, and this is not a recipe switch: it corrects a reading that two independent sources say was off.
  It is the same sign in every split, including seasons the fit never saw, and costs nothing above 3.
- **It does not beat the market.** It makes the curve agree with the market's moneylines where the two
  differed. With fetched moneylines a straight-up game was already priced off them (`pricing._anchor`); this
  matters most when only a spread is to hand - a predictions file, a typed spread, an early week.
- **It never changes the side the line itself favours.** It does make a near pick 'em nearer one, so the
  computer models' say tips it sooner. In the 2026 replay (docs/deadeye-season-sim-2026.md) that turned two
  more picks, both right - which is two games, not evidence.
- Tried beside it and **not** adopted: a flat home-side shade, fitted on results walk-forward over
  2006-2026 (+0.0002, −0.0002 to +0.0006; the amount the earlier seasons chose wandered between 0 and 0.4
  points). A one-off check, not kept in the script. Closing lines, not Thursday's: the archive of
  deadline lines is too short to fit anything to.

`SMALL_LINE_SHADE = 0` in `analytics.py` undoes it.
