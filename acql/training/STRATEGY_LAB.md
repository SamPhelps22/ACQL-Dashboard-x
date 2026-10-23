# Strategy lab - findings (2026-10-23)

`python -m acql.training lab` · code: `strategylab.py`, `lablocks.py`, `labreport.py` · tests: `tests/test_strategy_lab.py`
Full run report: `data/training/lab/latest/report.md` (run 20261023-082015, 62 s).

**Verdict: nothing earned a nomination. Deadeye stays the champion and no production code was changed.**

## What was built (and what was not touched)

Everything is new files inside `acql/training`, the package the dashboard never imports (a test enforces it). Not
touched: `pricing.py`, `predictions.py`, the Model Lab, the card, the website, the locked records in `model/known.py`.

| Piece | What it does |
|---|---|
| Strategies | market; Deadeye (the picks' own code); Elo (4 settings); a points-for/against scoring model (3 half-lives); 7 logistic regressions on blocks of pregame inputs; LightGBM (2) and XGBoost (1); 2 plain averages; 3 meta-learners (stacks) - one with context (line size, model spread, early season) so it can learn *when* a strategy helps |
| Learned models start from the market | every logistic, tree and stack learns corrections to the market's log-odds, so its regularisation pulls toward "the line was right", not toward 50/50 |
| Point-in-time | walked a season at a time; Elo and the scoring model move a week at a time on earlier weeks' results only; totals and moneylines (closing-only) are never used at the deadline |
| Leak check | the whole lab is walked twice, once with every result from a cut onward scrambled; nothing priced before the cut may move (passed: 2,163 games) |
| Untouched test | development 2018-2022 chooses; 2023-2026 is scored only after the finalists are frozen to `freeze.json`; every opening is logged |
| Multiple testing | Holm correction over every candidate ever tried under the protocol (23 so far), across runs, so retrying ideas makes passing harder |
| Automatic proposals | a second round built only from development results: a stack of whatever beat the market, neighbours of the best tree setting, a logistic grown from blocks that helped alone |
| Registry | `data/training/lab/registry.jsonl`, append-only: every candidate, its spec, data fingerprint, code commit and status - failures included |
| Prediction archive | every strategy's chance for every game, beside the result, per run (`predictions-<timing>.csv.gz`, sha256 kept) |
| Probability vs pool | log loss, Brier, calibration error, sharpness - and separately ACQL picks credited a week; never added together |
| Promotion gates | written in `PROTOCOL` before any scoring: dev and test both beat Deadeye after correction, test beats the market, calibration no worse, pool picks not clearly worse, leak check, clean data. Passing only writes `nominee.json`; the switch is the owner's |
| Locked forecasts | `lab lock` writes `locked/<season>-w<week>.json` once, before the deadline, exclusive-create, read-only, hash-chained; `lab verify` catches edits, deletions and files outside the chain |

## Does the data support it?

Partly. The Thursday-deadline line itself exists only for about 60 games this season, so the headline uses the
archive's midweek line (2013 on, 3,448 games). With three warm-up seasons for learned models and two more for the
meta-learner, that leaves 1,305 development games and 863 test games. The smallest edge over Deadeye the development
games could reliably detect is about **0.0023 log loss a game**; the Model Lab's switching bar is 0.010. The archive's
computer-model numbers carry no time stamps, so any model-based edge at the midweek line is an upper bound.

## Results at the midweek line (nearest the deadline)

Log loss a game; positive = better than Deadeye; 95% range from week-clustered errors.

| Strategy | Development 2018-22 | Test 2023-26 |
|---|---|---|
| Market alone | +0.0014 (-0.0001 to +0.0030) | -0.0010 (-0.0028 to +0.0007) |
| Meta-learner: market, Deadeye, Elo, scoring (best on development) | +0.0021 (-0.0009 to +0.0052) | **-0.0043 (-0.0077 to -0.0009)** |
| Logistic, market only (recalibrated line) | +0.0013 (-0.0011 to +0.0038) | -0.0021 (-0.0045 to +0.0003) |
| Average of market and Deadeye | +0.0008 (+0.0000 to +0.0016) | -0.0004 (-0.0013 to +0.0005) |
| XGBoost, depth 1 | +0.0000 | -0.0012 |
| LightGBM, 3 leaves | -0.0014 | -0.0014 |
| Elo alone (best setting) | -0.0203, clearly worse | - |
| Scoring model alone (best setting) | -0.0163, clearly worse | -0.0362, clearly worse |

After Holm correction no candidate beat Deadeye on development (best corrected p = 0.45).

## What it means

1. **Nothing adds measurable value over Deadeye or the market at the deadline.** Deadeye and the market cannot be
   told apart: the market was slightly ahead in development and Deadeye slightly ahead in test, neither clear of zero.
2. **The most complex model was the clearest failure.** The meta-learner looked best in development and was the only
   finalist that was *clearly worse* than Deadeye on the untouched seasons. Without the frozen test, it would have
   looked like a discovery. The stack over every learned strategy was worse again (-0.0072 in development).
3. **Elo and the scoring model are redundant with the line.** On their own they are far worse than the line. On top
   of it, their weight is about zero (z near 0); they rediscover the sportsbook spread with more noise.
4. **Context did not help.** The context stack's penalty went to its maximum, which reduced it to the market. Splits
   by line size, model spread and early season all had ranges that included zero.
5. **The line keeps getting better toward kickoff** (on 3,440 shared games): opening 0.6736 → midweek 0.6689 → updated
   0.6660 → closing 0.6645. Deadeye beats the *opening* line (0.6727) but adds nothing from midweek on. That matches
   the earlier decay study: the market absorbs the models' information during the week.
6. **ACQL picks:** no market-based finalist changed picks a week by a range that excluded zero (all within about
   ±0.2 a week). The ones that clearly cost picks were the standalone ratings: the scoring model lost 0.58 a week
   on test (-1.09 to -0.09), and Elo and the all-learned stack lost about 0.4-0.5 a week on development. ACQL scores
   one point per credited pick with no confidence ranking, so the side is the only decision a probability drives.

## Honest caveats

- The test seasons were opened twice under this protocol. The first run crashed while writing its archive, *after*
  scoring. Nothing was changed between the two runs except the file-writing fix, and the results are deterministic.
- 2024-2026 had already been looked at by earlier studies for Deadeye against the line. They are untouched only for
  the new strategies.
- Learned strategies are retrained once a season, not each week. Elo and the scoring model update weekly.
- The lab recomputes Deadeye from the picks' own code on the archive. It does not use the app's recorded chances
  (`prereg.py` scores those).

## Protocol 2 (2026-10-23): the two objectives split

strategy-lab-1 scored one thing - the chance the home side was *credited* under the pool's line - so "probability
quality" and "ACQL picks" were the same number. `strategy-lab-2` (`PROTOCOL_2`, now the default for `lab run`) splits
them into two tracks, each taught, chosen and judged on its own answer, each with its own champion
(`data/training/lab/champions.json`; Deadeye holds both):

| Track | Question | Chances | Judged by |
|---|---|---|---|
| probability | did the home side win (ties out) | straight-up curve, every game | home-win log loss vs Deadeye and the market |
| acql | was the home side credited | pool-line curve | ACQL picks credited a week vs Deadeye's card |

- **Development (2018-2022) only chooses.** 2023-2026 were spent by protocol 1, so they are scored as "seen", for the
  record. **The test is the locked weeks only** (2026 week 8 on). Gates for each track were written into `PROTOCOL_2`
  before any locked week had a result; `lab score` judges them and updates champions.json.
- **Lab-1 is unchanged:** rebuilt from the edited code, its 24 first-round strategies give the same development chances
  as run 20261023-082015, to the sixth decimal on all 1,305 games.
- **Run 20261023-090013** (137 s, both leak checks passed). Probability track, midweek, development: market 0.6153 vs
  Deadeye 0.6166 home-win log loss (market +0.0014, -0.0002 to +0.0029); seen seasons: Deadeye 0.6111 vs market
  0.6122. ACQL track reproduces lab-1 exactly (picks 753 vs 749; seen 541 vs 537). On ACQL picks the market alone
  took +0.05 a week more than Deadeye in development and +0.07 in the seen seasons - neither clear of zero.
- **Finalists frozen per track** (6 each). Several are listed "not ahead of Deadeye on development": they are locked
  for the record but can never be nominated.
- Caveat: an earlier attempt (run 20261023-085721) crashed in the leak check after freezing; it left only
  `freeze.json` and one "seen-scored" registry line. Fixed (a meta-learner's members now join the leak check) and rerun.

## What happens next (nothing automatic changes a pick)

- **Each week:** the training task's Thursday run locks the finalists' forecasts for the coming week (12 hours or less
  before the deadline). `lab score` compares locked weeks with results as they come in. That is the only truly
  out-of-sample record, and it grows by about 14 games a week.
- **Rerun the lab** when a new idea is worth testing. Each rerun counts as another opening of the test seasons, and
  every new candidate makes the Holm correction stricter.
- A nomination, if one ever comes, is a case to put to the owner, never a switch.
