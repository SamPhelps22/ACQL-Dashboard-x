# New model vs Deadeye under ACQL rules

Generated 2026-10-13 by `python nfl_pickem/scripts/compare_deadeye.py`. The script reads the
dashboard's data read-only; nothing in the dashboard was changed.

**ACQL rules, applied to every card through Deadeye's own code** (`acql.analytics`,
`acql.backtest`, `acql.weekplan`):

* one point per credited pick;
* a favourite of 6.5 or more carries a pool line, and must win by at least the line;
* the field is 34–38 coaches.

Big Loser and the suicide pool are not compared. Both models feed the same pool-line math (key
numbers), the same crowd model and the same planner. Only the probabilities differ.

## Part 1: the real weeks on file

These use real slates, the commissioner's pool lines and every coach's actual picks.

| Week | Pool avg | Best coach | Deadeye live card | New model (plain) | Market line (plain) | New ML-only (plain) |
|---|---|---|---|---|---|---|
| 2023 wk 8* | 7.7 | 11 | – | 11 (1st) | 9 (4th) | 8 |
| 2023 wk 10 | 7.8 | 10 | – | 11 (1st) | 11 (1st) | 11 (1st) |
| 2023 wk 11 | 7.8 | 10 | – | 9 (7th) | 10 (1st) | 8 |
| 2023 wk 13 | 7.4 | 13 | – | 10 (3rd) | 10 (3rd) | 9 |
| 2025 wk 3 | 8.9 | 12 | – | 11 (2nd) | 10 (6th) | 9 |
| 2025 wk 4 | 8.7 | 12 | – | 11 (2nd) | 10 (5th) | 7 |
| 2026 wk 1 | 9.7 | 13 | **13 (1st)** | **13 (1st)** | 13 (1st) | 11 |
| 2026 wk 2 | 8.7 | 12 | **13 (1st)** | **13 (1st)** | 13 (1st) | 9 |

\* One sheet game (LAC@DET) isn't on that NFL week, so it was skipped (15 games).

* **Deadeye vs the new model:** the only weeks where both have a card are 2026 weeks 1–2. There
  they tied: 13 and 13, first both weeks.
* **The new model over all eight weeks:** 89 of 123 correct (8.4 more than the pool's average
  coach over the 8 weeks). It never finished worse than 7th.
* **Caveat:** the new model's market input is the *closing* line, which was not available when
  the coaches (or Deadeye) made their picks. That flatters it slightly. Eight weeks is noise.

## Part 2: 2012–2025 replay, 243 regular-season weeks

Pool lines follow the commissioner's measured habit (`acql.backtest.pool_line`), applied to the
real closing spread. The field is Deadeye's crowd model. "Firsts" is the expected number of
weeks finishing first, ties shared. A fair share in a 35-card field is about 6.9.

| Pricing | Card | Right / week | % right | Expected firsts (243 wks) |
|---|---|---|---|---|
| Market line (Deadeye's live starting point) | plain | **8.63** | 57.2% | 14.7 |
| New model (learned blend) | plain | 8.61 | 57.1% | 15.4 |
| New model, ML only (football models) | plain | 8.40 | 55.7% | 14.2 |
| Deadeye backtest proxy (rating model) | plain | 8.24 | 54.7% | 13.0 |
| Market line | planner | 8.38 | 55.6% | 15.4 |
| New model | planner | 8.31 | 55.1% | 15.0 |
| New ML only | planner | 8.08 | 53.6% | 18.2 |
| Deadeye proxy | planner | 8.00 | 53.1% | 16.7 |

Paired weekly differences against the market line (95% CI):

* **New model:** −0.03 right per week [−0.15, +0.10]. Tied.
* **New ML only:** −0.23 [−0.44, −0.01]. Worse.
* **Deadeye proxy:** −0.39 [−0.62, −0.15]. Worse.
* **Chance of finishing first:** no pricing differs significantly. Every CI includes 0.
* **Deadeye's planner vs the plain card** (market line): −0.25 right per week
  [−0.41, −0.08], and +0.003 chance of first per week [−0.018, +0.023]. The planner gives up
  correct picks without a measurable gain in first-place finishes. This agrees with Deadeye's
  own stored backtest, where `plan_first` 0.052 < `plain_first` 0.065.

## What could not be compared

Deadeye's *live* engine nudges the market line with about a third of the Prediction Tracker
model consensus. It cannot be replayed historically, because those weekly files aren't
archived here (only 2026 weeks 3–5 are in the repo). Its live record is the only evidence:
2025 weeks 15–17 and 2026 weeks 1–2, 49 of 80 correct against a pool average of 41.9.

## Bottom line

Under ACQL rules, the new model ties the market line, which is Deadeye's live starting point.
Over 14 seasons it beats the stand-in model Deadeye's own backtest uses by about 0.4 picks per
week. In the two real weeks where both made cards, they tied. Whether Deadeye's consensus
nudge adds or subtracts value is still unmeasured. Archiving Prediction Tracker files each
week would make that testable.
