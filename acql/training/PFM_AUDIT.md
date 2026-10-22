# Pro Football Mania ratings against Deadeye (2026-10-18)

Sam pasted a brief asking whether Pro Football Mania's team ratings
(profootballmania.com) add predictive information to Deadeye beyond the
betting line and the current model, proved or rejected by leakage-safe,
chronological testing. This was a data integration and a shadow experiment. No pick, chance,
weight, model share or website output was changed.

Evidence: `python -m acql.training pfm` pulls a snapshot (unless `--no-pull`)
and writes `data/training/pfm/report.md`, `latest.json` and `shadow.jsonl`
(git-ignored). Tests: `python tests/test_pfm.py` (39, made-up pages and games).
No PFM rating is kept in this repository: the repo is public and the numbers
are PFM's. They live in `data/pfm/` on this computer only.

## 1. Deadeye's pipeline, as found

- **Margin.** `pricing.price` starts from the market's latest home margin
  (`pricing.market_margin`: the stored line, else the opener) and moves it a share
  of the way toward the trimmed consensus of the computer models
  (`predictions.Forecast.expected`, with a per-week fitted weight bounded by
  `MIN/MAX_WEIGHT_SHARE`). The share is `predictions.CONSENSUS_WEIGHT`, which has
  been **0.25 since 2026-10-12** (Sam's choice). The brief's "33%" is the old
  value. The moneyline and the over/under nudge the margin and its spread
  (`MONEYLINE_REACH`, the totals widening).
- **Chance.** `analytics.predict_margin` reads the chance that the pick is credited
  off the dashboard's two-bell, key-number margin curve
  (`analytics.margin_distribution`, narrow SD 8.7). It honours the pool's line and the
  favourite-needs-the-line rule (`analytics.line_need`). Disagreement among models
  widens the per-game SD (cosmetic, per the calibration audit).
- **Inputs already there:** odds with history and lock (`feeds/odds.py`,
  `feeds/oddslock.py`), injuries (`feeds/injuries.py`), weather
  (`feeds/weather.py`), nflverse schedule, rest and roof (`feeds/nflverse.py`), and the
  computer models (`model/computers.py`).
- **Record and evaluation:** the Model Lab (`model/modellab.py`, 150-game /
  0.010 rule), the written-down record (`model/ledger.py`, `forecastlog.py`),
  the frozen pre-deadline snapshots (`training/snapshots.py`), and the training
  ground's walk-forward (`training/walkforward.py`, `evaluate.py`,
  `featurevalue.py`).
- **Confidence points** belong to the separate `nfl_pickem` project
  (`nfl_pickem/nflpickem/confidence.py`). ACQL is straight pick'em with pool
  lines. Neither project's allocation was touched.
- **Cleanest integration point:** a feed (`acql/feeds/pfm.py`) for collection,
  the training ground (`acql/training/pfm.py`) for the experiment, and a
  read-only file reader (`acql/model/pfmcheck.py`) for the Model Lab. This is the
  same pattern as `challengers.py`. Nothing in pricing reads PFM (a test enforces
  it).

## 2. The source

| | |
|---|---|
| Ratings table | `/nfl-team-rankings/`: 32 teams, Team Score and 7 grades to 2-3 decimals, record, update date (`<time datetime>`) |
| Explosiveness | `/nfl-team-explosiveness-rankings/`: graded, not part of the score |
| History | team pages: Team Score after each week (BASELINE, W1..W5), 1 decimal, **no dates**; grades have **no history** |
| Update log | `/nfl-ranking-changes/`: before/after scores for the **newest two** updates only (2026-10-13, 2026-10-06) |
| Methodology | `/pfm-methodology/`: weights 25/20/15/15/10/10/5. Score introduced **2026-06-25**; version 2026-08-29 |
| Cadence | weekly, Tuesdays in season |
| Access | robots.txt allows all. No terms-of-use page, no API, a copyright notice on every page. Pulled politely (2 s apart, retries, one User-Agent). Sam approved a first pull and weekly pulls (2026-10-18) |

The published formula, applied to the published grades, reproduces every
team's published score to within 0.05. That check runs on every snapshot as a
derived value, kept apart from the source values. The site itself says the
score "is not a betting line, a game prediction".

**Limitation:** there is no PFM before June 2026, so no earlier season can be
tested. No past grade is recoverable. The weekly score history is source-reported,
was read on 2026-10-18, and its publication dates are mostly inferred.

## 3. Ingestion and storage

- One JSON snapshot per pull in `data/pfm/snapshots/` (self-ignoring), never
  overwritten. Each holds source URL, per-page SHA-256 and bytes, collected time,
  stated effective date, methodology version and weights, team code and name,
  values, and quality.
- Same numbers as the newest snapshot: the import is logged as "unchanged" and no
  file is written (idempotent). A failed check is logged as "refused" and kept in
  `data/pfm/refused/` for a look; the last good snapshot stands, and
  `pfm.freshness` gives its age. Stale (over 9 days since PFM's update) is always
  labelled as stale.
- Validation covers the 32 known codes, duplicates, ranges, missing fields, the
  formula, the team page's newest score against the table's, the changes page's
  "before" score against the history, and the methodology weights.
- `pfm.as_of(t)` is the only way a prediction sees a snapshot: read no later than
  `t`, stating no later update, status ok or partial.
- `pfm.revisions()` flags any past weekly score PFM rewrites between snapshots.
- Weekly: the "ACQL Training" task (Tue/Wed/Thu 12:30, registered) now pulls PFM
  when the newest snapshot is 20+ hours old. It reads the 32 team pages only when
  PFM's update date has moved, and then runs the study.

## 4. Features (home less road) and overlap

`score_diff`, `score_move` (change at PFM's latest update), and the eight grade
differences. There are also three attack-against-defence terms, which are sums of
two grade differences and are tried alone, never in E. Grades are never combined
with the Team Score, which is built from seven of them. Narrative text and badges
are not used.

The overlap is large. Over 105 games, the PFM score gap correlates **0.83** with the
line and 0.83 with Deadeye's margin. About **31%** of its variance is left once the
line is taken out. On the 12 games with grades so far, roster strength (0.94) and
franchise direction (0.84) track the line most. QB stability, offense and recent
performance track it least (0.13-0.20). That is far too few games to rely on.

## 5. Backtest (2026, weeks 1-6; graded 2026-10-18)

Walk-forward by week. For each game, the variant's own chance is a fixed offset,
and one coefficient is fitted per fact, with no intercept and fixed shrinkage
(4.0, set in advance). It is taught only on earlier weeks' graded games, and
nothing is taught before 40 training games. The PFM score for week n+1 is PFM's
score after week n, used only if it was published before that week's deadline
(stated date where PFM gives one, else the Tuesday before, flagged). The seal
holds: scrambling every result from week w on leaves week w's chances unchanged,
for weeks 2-6.

Same 41 games (weeks 4-6; 40 training games are first reached at week 4):

| Variant | Log loss | Brier | Against A (95% range, weeks resampled) |
|---|---|---|---|
| A Deadeye (production) | 0.6836 | 0.2454 | - |
| B Line alone | 0.6874 | 0.2473 | +0.0038 (-0.0069 to +0.0191) |
| C Deadeye + PFM score | 0.6799 | 0.2434 | -0.0037 (-0.0225 to +0.0245) |
| C2 Line + PFM score | 0.6833 | 0.2451 | -0.0003 (-0.0297 to +0.0175) |
| C3 Deadeye + PFM movement | 0.7032 | 0.2528 | +0.0196 (-0.1304 to +0.2390) |
| D, E (grades) | - | - | not taught: grades exist only from the first snapshot (after week 6's deadline) |
| F (earned facts) | = A | = A | no fact has earned a place (needs 150 earlier test games, range below zero) |

Closing line on the 30 of those games where nflverse has a true close: 0.6740
(Deadeye 0.6680 on the same games). That is a yardstick only.

The taught PFM weight was **negative every week** (about -0.2 logit per SD of
the gap). On these games, the side PFM rated above the line did slightly worse
than the line said. Descriptively, over 90 graded games, the PFM gap against
Deadeye's margin miss has a correlation of -0.07 (weeks resampled: -0.25 to +0.11).
By group (week, home favourite or underdog, line size) the groups hold 11-23
games each, and none says anything.

Missing or stale PFM: none of the graded games lacked a score. A game without
one keeps its base chance (tested). Weeks 3-4 were priced from lines taken after
the deadline. Every variant shares that line, so the comparison is fair, but
none of them is the card that could actually have been made then.

## 6. Verdict: **inconclusive**

There are 41 out-of-sample games, a range that takes in zero on both sides, and a
direction (fade PFM) that is the opposite of "PFM helps". The grades cannot be
tested at all yet. The data cannot show an improvement, and it shows no
significant harm either.

## 9. Limitations and next steps

- Evidence will come only prospectively: about 14 games a week. At least 150
  taught games (about 10 more weeks) are needed before the F rule can admit
  anything. A full season will still be one season.
- The grades become testable from week 7 on (snapshot of 2026-10-18).
- The history's publication dates are inferred for most points. The weekly
  pulls now record real collection times and will catch rewrites.
- PFM's own pre-game "PFM Call" picks are on the team pages (locked at kickoff,
  graded). They are not collected. They are picks, not probabilities, and could be
  added as an independent baseline if wanted.

## 10. Production

Unchanged. `CONSENSUS_WEIGHT` is still 0.25. Pricing, predictions, the
ledger, the cards and the website have no PFM in them (tested). Shadow chances
go only to `data/training/pfm/shadow.jsonl`, marked `"official": false`. Rollback
means deleting the three new modules, the Model Lab cards and the `pfm` command.
No production behaviour depends on them.
