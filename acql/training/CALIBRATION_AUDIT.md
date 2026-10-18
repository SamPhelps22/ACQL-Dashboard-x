# Deadeye probability calibration audit (2026-10-18)

Prompted by Will's thread of 2026-10-18 on ESPN's fantasy win chances, where
ESPN added standard deviations instead of variances and shrank the SD instead of
the variance as a matchup went on. The question here was whether Deadeye has
the same kind of error, and whether its chances are calibrated. This was an
audit and a shadow test only. No pick, chance, weight or website output was
changed.

Evidence: `python -m acql.training calibration` writes
`data/training/calibration/report.md` (git-ignored) with reliability diagrams.
Tests: `python tests/test_calibration.py`.

## 1. The path from a sportsbook line to a pick, in plain English

1. **Market lines.** `acql/feeds/odds.py` `parse` takes each book's home spread
   and moneyline and uses the **median across books**, so one stale book can't
   move it. The two moneyline prices are each turned into a chance and divided by
   their sum to remove the bookmaker's margin (`ours / (ours + theirs)`).
2. **The base margin.** `pricing.price` (`acql/model/pricing.py:333`) starts
   from a spread typed in by hand (unless the market has moved since it was
   typed), otherwise the market's latest home margin, otherwise the opening line.
   On a **straight-up** game, the moneyline's no-vig chance is turned back into
   a margin (`analytics.spread_for_win_chance`) and used instead, but only if it
   is within 2.5 points of the spread (`_anchor`, `MONEYLINE_REACH`). Lined games
   always keep the spread.
3. **The computer models.** `predictions.Forecast.expected`
   (`acql/model/predictions.py:400`) adds a share of the models' disagreement:
   `market + w_game × live_edge`. `live_edge` is the trimmed model mean (the
   wildest 20% at each end dropped) minus the market, minus the slate's median
   home lean, discounted when the line has since moved against the models.
   `w_game` is **25%** (`CONSENSUS_WEIGHT`, 33% until 2026-10-12), scaled by
   `2·typical² / (typical² + D²)`, where D is this game's model spread, and
   held between 0.35× and 1.6×. During a season the 25% is refitted on the
   earlier weeks (`pricing.week_weight`) and locked from the first kickoff.
4. **The width.** `sd = hypot(8.7, w_game × D) × total_factor`, where
   `total_factor` is (this game's over/under ÷ the slate's median)^0.25, held
   between 0.94 and 1.07.
5. **Margin to chance.** `analytics.predict_margin` → `cover_chance(margin,
   need, sd)` reads the chance off `margin_distribution`. **This is not a normal
   CDF.** It is a mixture of two bell curves with the same centre: a narrow one
   (8.7) carrying 66% and a wide one (8.7 × 2.26 = 19.7) carrying 34%. Each
   margin is then weighted by how often NFL games really end on it (3, 7, 10,
   14…), and the curve is shifted so its average is exactly the expected
   margin. A straight-up game needs a win by 1 or more. A lined game needs the
   pool's favourite to win by `ceil(line)` (a win by exactly the line counts).
6. **The card.** ACQL has **no confidence points**. Every game is worth one
   point, and `acql/pool/moneyplan.py` simulates thousands of weeks from these
   chances (and the pool's expected picks) to choose the card that makes the
   most money. That is where calibration matters: the chances decide when it
   pays to go against the pool's favourite. (The "1-to-N confidence" in the
   brief describes the separate `nfl_pickem` project.)

## 2. What the 8.7 is

**It is the width of the narrow bell only, not the SD of the final margin.**
Measured off the curve itself (`calibration.curve_sd`), the margin's true SD is
**13.05 points** at a pick'em and 13.1 at 7 points. That matches the published
SD of NFL results around the closing line (about 13 to 14). The two bells were
fitted by hand to two targets at once: the market's moneyline win chances (61%
at 3 points, 74% at 7, 82% at 10) and how far real scores land from the line
(2021-25). They were then checked on 2010-14 and 2015-20.

If you replace the curve with a single normal and ask which SD gives the same
win chances, the answer is 10.3 at 1 point, 10.6 at 7 and 11.6 at 14. No
single normal matches both. Real NFL margins are peaked and fat-tailed: most
games land close to the line, but blowouts happen more often than one bell
allows. A plain normal with the true SD (13) makes favourites look too weak,
and one that gets the win chances right (about 11) makes blowouts too rare.
The two-bell curve exists to do both.

## 3. The math, checked

| Concern | Finding | Evidence |
|---|---|---|
| Independent uncertainties combined as variances | **Correct.** The per-game widening is `hypot(8.7, extra)`, and inside the curve `extra²` is added to the variance of both bells (`analytics._shape`), never added as an SD. Measured on the whole curve: extra 2 → variance +3.8 (2² = 4); extra 4 → +15.1 (16). Adding them as SDs (8.7 + extra) would have added 38.8 and 85.6 to the narrow bell. | `Curve.test_widening_adds_in_variance`, `Pinned.test_priced_slate` |
| SD of a difference of independent variables | **Not applicable, and not done wrong.** Deadeye never builds a margin SD from two team-score SDs. It models the margin directly, at a width fitted to real margins. ESPN's first and third errors (adding SDs, then the /2) can't occur. | `Arithmetic.*`; no code path combines team SDs |
| A /2 or other normalisation | **None in the probability path.** The only factor of 2 is `2·typical²/(typical²+D²)` in `model_weight`: a weight that equals 1 when this game's disagreement is typical. It scales the models' share, not a variance. | `predictions.py:397` |
| Normal CDF gets the right margin and scale | **No normal CDF is used.** The curve gets the expected home margin and the narrow width, and the mean shift keeps its average equal to the margin. | `curve_sd(7) mean = 7.000` |
| Home/away orientation | **Symmetric.** `cover_chance(m, n)` equals `1 − cover_chance(−m, −n+1)` to 5×10⁻¹³ across margins ±14 and needs ±20. Every margin is from the home side, consistently. | `Curve.test_mirror`, `test_home_chance_symmetric_and_bounded` |
| Ties | **Counted once.** P(home ≥ 1) + P(away ≥ 1) + P(tie) = 1, and a tie is about 0.4%. A straight-up pick's chance counts a tie as a miss, so a pick'em reads 49.8%, not 50% (the audit's tie-free chance differs by at most 0.3 points). | `Curve.test_ties_counted_once`, `test_home_chance_matches_the_picks` |
| Bounds | Chances stay strictly inside (0, 1) and rise with the margin. `spread_for_win_chance` clamps to 3% to 97%. | `test_home_chance_symmetric_and_bounded` |
| Spread chance mistaken for moneyline chance | **Kept apart.** Moneyline chances are no-vig and only replace the spread on straight-up games within 2.5 points. A lined game never uses them. The file's own "probability home wins/covers" columns are deliberately ignored (they are the model average through fixed 14.4 and 19.9 curves). | `Curve.test_moneyline_and_spread_are_kept_apart`, `predictions.py:69-77` |
| Market counted twice | **No.** The market enters once as the base, and the models enter only as their difference from it, after the slate's shared lean is removed. One small inconsistency: on a straight-up game the base can be the moneyline's margin while the model edge is still measured against the spread. That is at most 2.5 points × 25% ≈ 0.6 points, and only when the two disagree. | `pricing._anchor`, `Forecast.edge` |
| ESPN's second error (SD shrinking with time left) | **Correct.** Live chances (`acql/pool/gameday.py:157` `outlook`) scale both bells by `sqrt(left)`, which is variance in proportion to the time left: exactly what ESPN got wrong. The pre-game edge is scaled linearly with time left (a mean, so that is right too). Only the code was checked here. Live chances weren't backtested (the archive has no in-game data). | `gameday.py:174-177`; `Arithmetic.test_remaining_sd_shrinks_by_root_of_time` |

One quirk worth knowing: the per-game widening is **tiny**. `extra = w_game × D`.
With w about 0.25 and the trimmed models usually 1 to 2 points apart, extra is
about 0.3 to 0.8, so `hypot` moves 8.7 to about 8.71 to 8.74.
`predict_margin` also rounds sd to 0.1, so most games are priced at exactly
8.7. The comment "believing a third of their disagreement means carrying a
third of the disagreement among themselves" is a heuristic. It is not the SD
of the model consensus (that would be about D / √n), but it is applied
correctly in variance.

## 4. Results from history

**Setup.** Data: The Prediction Tracker's per-game archive (every model's
margin plus the opening, midweek and last-updated lines), joined to nflverse
results. The question scored is the straight-up winner, with ties left out.
Every chance is built only from numbers known before kickoff. The two fitted
candidates (a normal width and a logistic recalibration) are refitted as each
season starts, using only the seasons before it. The first 3 seasons of each
timing are used only for fitting. **2024-26 is held out**: the "best
alternative width" was chosen on the earlier seasons and then scored, unchanged,
on 2024-26. Ranges are 95%, from redrawing whole weeks 1,000 times. Deadeye is
the picks' own code (`Forecast.expected` with its per-game width) at the 25% in
use.

**Which line counts as "before the deadline".** The archive has no timestamps.
The **midweek** line (2013 onward) is the nearest it has to the Thursday 6 pm
deadline, so it is the headline. The **opening** line is always earlier than
the deadline, but softer than what a Thursday card sees. The **last update**
may come after the deadline, so treat it as an upper bound, not a
pre-deadline test. The closing line is never used as an input.

### Headline: midweek line, 2,084 development games (2016-23), 591 held out (2024-26)

| Candidate | Log loss (dev) | Slope (dev, 95%) | vs market, dev (95%) | Log loss (held out) | Slope (held out) | vs market, held out (95%) |
|---|---:|---:|---:|---:|---:|---:|
| **Market line, curve in use** | 0.6149 | 0.95 (0.84-1.10) | bar | 0.6048 | 1.07 | bar |
| **Deadeye as priced** | 0.6162 | 0.95 (0.83-1.09) | −0.0013 (−0.0025 to −0.0001) | 0.6031 | 1.08 | +0.0017 (−0.0005 to +0.0038) |
| Curve 10% wider (chosen on dev) | 0.6146 | 1.04 | +0.0002 (−0.0012 to +0.0016) | 0.6060 | 1.17 | −0.0012 (−0.0038 to +0.0015) |
| Curve 10% narrower | 0.6166 | 0.86 | −0.0018 | 0.6047 | 0.97 | +0.0001 |
| Normal, SD fitted on earlier seasons (10.5-12.1) | 0.6148 | 1.01 | +0.0001 | 0.6057 | 1.15 | −0.0009 |
| Market recalibrated on earlier seasons | 0.6149 | 1.00 | −0.0001 | 0.6057 | 1.13 | −0.0008 |
| Deadeye recalibrated on earlier seasons | 0.6162 | 1.00 | −0.0013 | 0.6041 | 1.14 | +0.0007 (−0.0025 to +0.0038) |
| Normal SD 13.0 (true SD, plain bell) | 0.6156 | 1.16 (1.02-1.34) | −0.0007 | 0.6085 | 1.32 (1.06-1.63) | −0.0037 |
| Normal SD 9.2 (**ESPN /2 error**) | 0.6186 | 0.80 (0.70-0.93) | −0.0038 (−0.0071 to −0.0003) | 0.6052 | 0.92 | −0.0004 |
| Normal SD 18.5 (**ESPN SD-sum error**) | 0.6251 | 1.65 (1.45-1.92) | −0.0102 (−0.0176 to −0.0034) | 0.6214 | 1.88 (1.51-2.33) | −0.0166 (−0.0294 to −0.0036) |

Brier scores rank the candidates in the same order. Accuracy barely moves
(65.9-66.3% dev, 68.4-68.5% held out) and wasn't used to judge anything.

**The other two timings say the same about the curve.** The curve in use has
a slope of 0.95 on development seasons at every timing and 1.02-1.07 held out,
and no alternative width beats it on held-out games. The SD-sum error is
clearly worse everywhere: −0.010 to −0.017 a game, slopes 1.65-1.88. In this
setup the /2 error is worse on the larger development samples (−0.0035 to
−0.0038, ranges clear of zero).

**Deadeye against the market depends on how early the line is**:

| Line | Development | Held out 2024-26 |
|---|---|---|
| Opening (dev 2005-23, 4,756 games) | +0.0002 (−0.0011 to +0.0013) | **+0.0047 (+0.0013 to +0.0081)** |
| Midweek (headline) | −0.0013 (−0.0025 to −0.0001) | +0.0017 (−0.0005 to +0.0038) |
| Last update (dev 2002-23, 5,531 games) | −0.0006 (−0.0016 to +0.0003) | +0.0021 (−0.0003 to +0.0046) |

Against the opening line, the models know things the line hasn't priced yet.
By midweek the market has mostly caught up. This matches the training
ground's decay study.

**Reliability (midweek, all scored seasons).** Every bucket from 20% to 90%
with 200+ games lands inside its 95% range. The two tails are thin: 0-10%
has 5 games and 90-100% has 26.

**Two small, consistent patterns** that are below the bar for acting on but
worth watching:
- *Narrow favourites (lines under 3) are a little overrated.* The market curve
  said 56.0-56.7% and they won 52.8-54.6% (612 games midweek, about 1,230 at
  the other timings, mostly the same games). Their slope is 0.49-0.60. Each
  gap is about the size of its own 95% range (±2.8 points), and the three
  timings aren't independent samples.
- *Home sides win slightly less than priced.* The calibration intercept is
  −0.02 to −0.055 in log-odds, about 0.5 to 1.3 percentage points, in every
  timing. Most narrow favourites are home teams, so these may be one effect.

**The per-game widening changes nothing measurable.** "Deadeye as priced" and
"Deadeye fixed width" are identical to four decimals in every table, because
the extra width is about 0.3 to 0.8 points and the chance step rounds the
width to 0.1.

## 5. Recommendation

**Keep the curve and the 8.7 as they are.** Deadeye doesn't have ESPN's bug,
and its margin-to-chance step is calibrated. Its slope is consistent with 1
on every development set, no alternative width or recalibration beats it on
held-out seasons, and the two ESPN-style errors measurably make chances worse
when tried on the same games. Nothing here supports a production change. None
was made.

Worth investigating later (proposals, not changes):
1. **The narrow-favourite / home overrating.** A walk-forward check of a home
   or small-line adjustment, scored on held-out seasons, before anything moves.
2. **Deadeye's share.** At the line nearest the deadline, the models add
   nothing that can be told apart from zero (midweek development is slightly
   negative, held out slightly positive). That is the same reading as the
   Model Lab's. The 25% is Sam's call, and was chosen on 2010-26 replays that
   overlap these held-out seasons.
3. **The per-game widening is cosmetic.** It could be removed, or made
   meaningful, but that is a design choice with no measured gain either way.

## 6. Limits

- The archive has no timestamps. Midweek is a stand-in for the deadline, and
  2026 has only 48 graded archive games.
- The held-out set is 591 games, so a difference under about 0.004 a game
  can't be resolved there.
- The question scored is the straight-up winner. The pool's lined games (cover
  the commissioner's line) use the same curve at a different threshold, but
  the archive has too few pool lines to score them separately.
- The archive has no over/under, so the total's widening (×0.94-1.07) wasn't
  tested. In-season weight refitting (`pricing.week_weight`) wasn't replayed:
  Deadeye was scored at a fixed 25%.
- Accuracy differences are reported but never counted as improvement.

## Files

- `acql/training/calibration.py`: the shadow audit (never imported by the dashboard; a test enforces this).
- `acql/training/__main__.py`: the `calibration [midweek|opening|updated|join]` command.
- `tests/test_calibration.py`: 25 tests (arithmetic, curve symmetry/ties/bounds/variance, scoring, look-back-only fits, pinned production outputs).
- `.github/workflows/tests.yml`: runs the new suite in CI.
- This file.
