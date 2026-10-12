# CLAUDE.md — Deadeye / Operation Sunday

Sam's private NFL pool-prediction project. This repo is the **ACQL Dashboard**,
a PySide6 desktop app (version in `acql/version.py`). **Deadeye** is the app's
pick model (`MODEL_NAME` in `acql/version.py`). "Operation Sunday" is the
project's name and does not appear in the code.

The **ACQL Pool website** is a separate public application. Its generator still
lives in this repo, and it publishes to a different GitHub Pages repo (see
"Public website" below). Do not change it while working on Deadeye unless
explicitly told to.

User-facing behaviour is described in `README.md` and `START HERE.txt`. The
README's "Project layout" section was written before most of the prediction
modules existed, so trust the code over it.

## Architecture (verified 2026-10-12)

| Step | Where | What |
|---|---|---|
| Forecast inputs | `acql/predictions.py` (`read_csv`, `parse_summary_text`) | The Prediction Tracker's weekly CSV (`nflpredictions week N.csv`) or its pasted summary table: market `line`/`lineopen` plus one column per computer model |
| Live lines | `acql/odds.py` (`overlay`, `lines_at`) | Lines from The Odds API, with each update's timestamp kept |
| Typed spreads, pool lines | `acql/lines.py` | Spreads entered by hand, and the commissioner's lines read from the workbook |
| The nudge | `predictions.Forecast.expected` / `live_edge` / `model_weight` | The market line, moved toward the trimmed model consensus by a weight. The slate's shared home lean is removed first, adverse line movement is discounted, and the weight is scaled by how much the models disagree |
| Weight fit | `predictions.fit_from`, `pricing.model_weight(before=week)` | Walk-forward: each week's weight is fitted only on earlier graded weeks and shrunk toward `CONSENSUS_WEIGHT` |
| Pricing | `acql/pricing.py` (`price`, `context`, `week_weight`) | The single pricing path. Every page goes through it |
| Credit probability | `acql/analytics.py` (`margin_distribution`, `line_need`, `cover_chance`, `predict_margin`) | Turns a margin into P(credited) under the pool's rules. A win by exactly a whole-number pool line goes to the favourite |
| Lock | `acql/oddslock.py`, store kind `weights` | A week's lines, weight and card freeze at its first kickoff |
| Grading | `acql/cards.py`, `acql/reportcard.py` | Deadeye's card from before kickoff is kept, then graded |
| Long-run replay | `acql/backtest.py` | Replays 2010–2025 under the pool's rules (see the data limits below) |

**Storage.** `acql/store.py` keeps one SQLite file, `data/acql.db`, with
documents grouped by kind (`forecasts`, `odds`, `spreads`, `picks`, `cards`,
`weights`, `settings`, …). **That file is tracked in git.**

**Public website.**
- `acql/ui/poolpage.py`: its `snapshot()` is the whitelist of public data.
- `acql/ui/pool_page.html` and `acql/ui/pool_sw.js`: the page template and its service worker.
- `acql/webpublish.py`: uploads through the GitHub Contents API to Pages.
- `acql/ui/webpage.py`: the publish button and `AutoPublisher`.
- `acql/siteextras.py`: the site's extra content.
- `acql/mailer.py`: the recap email.

**Model Lab** is `lab/`, which production never imports. `lab/history/` builds
the as-of-cutoff backtest dataset into `lab/data/history.db` (gitignored).
What each source can vouch for is in `lab/reports/data-audit.md`, and the
coverage is in `lab/reports/coverage.md`.

## Commands

```bash
python run.py                    # launch; the first run builds .venv from requirements.txt
python run.py --check            # report dependency status; installs nothing
QT_QPA_PLATFORM=offscreen python tests/run_tests.py   # whole test suite (unittest, no pytest)
python -m acql.backtest          # replays history AND overwrites the tracked acql/data/backtest_results.json
python -m lab.history.build      # fetch pinned inputs, build lab/data/history.db, verify, write coverage report
python -m lab.walkforward        # phase 2 backtests from that dataset -> lab/reports/walkforward.md
python packaging/build.py        # PyInstaller build into dist/
```

CI (`.github/workflows/build.yml`) runs only when a `v*` tag is pushed or the
workflow is started by hand. It tests, builds, and attaches the binaries to a
GitHub Release, so pushing a `v*` tag is a release.

## Known state and traps (as of 2026-10-12)

- **Test baseline.** 73 tests run: 39 app tests, plus 34 lab tests from
  `tests/test_lab_history.py` and `tests/test_lab_walkforward.py`. 2 app
  tests already fail with no changes made
  (`test_big_loser_slots_round_trip`, `test_wins_include_big_loser_points`),
  and 1 is skipped. Compare results against this baseline; don't assume a
  green suite.
- **Untested modules.** No tests cover `predictions.py`, `pricing.py`, the
  probability functions in `analytics.py`, `backtest.py`, `oddslock.py`, or
  what `poolpage.snapshot()` publishes.
- **Store migration overwrites the database.** Opening the store in a fresh
  checkout (tests or app) re-imports the legacy root `acql-*.json` files into
  `data/acql.db`. That overwrites stored forecasts, picks, odds and cards, and
  creates `data/backups/`. After any run, check `git status`, and restore with
  `git checkout -- data/acql.db` unless the change was intended.
- **Historical data is thin.**
  - Market lines and Prediction Tracker forecasts exist only for weeks the app
    has stored this season: 2026 weeks 1–5, with model columns for weeks 3–5
    only.
  - `acql/data/nfl_scores_2010_2026.csv` has final scores but **no historical
    lines or forecasts**.
  - `backtest.py` prices history with an Elo-style rating proxy, not the
    market and not Deadeye.

## Project rules

### Prediction logic
- The betting market is the primary baseline. Deadeye nudges it toward The
  Prediction Tracker's published computer-model forecasts.
- Margins use one convention: **positive means the home team is favoured,
  negative means the visitor is favoured.**
  - `lines.Spread` and `analytics.predict` carry a favourite plus unsigned
    points instead. Convert at the boundary.
  - When a sheet has home and away swapped (`Match.flipped`), use
    `predictions.home_margin`.
- Deadeye converts predicted margins into probabilities of receiving credit
  under the commissioner's pool rules (`analytics.predict_margin`, `line_need`).
- **Do not change the current production nudge or algorithm without explicit
  approval.** That covers:
  - the tuning constants in `predictions.py`: `CONSENSUS_WEIGHT`,
    `ADVERSE_MOVE`, `*_WEIGHT_SHARE`, `TRIM_SHARE`, `MIN_KEPT`, and the `FIT_*`
    and `MIN_FIT_GAMES` values;
  - `home_lean` and `typical_disagreement`;
  - the margin-distribution constants in `analytics.py`: `SPREAD_SD`, `TAIL_*`,
    `MARGIN_FREQUENCY`, `KEY_*`;
  - `line_need`, `pricing.price`, and the odds lock.
- Never rewrite locked history. The `weights` and `cards` store kinds record
  what each week was priced and picked with.
- Keep Model Lab experiments separate from production until they are validated
  and approved:
  - they live in their own module(s), and production code never imports them;
  - they read production data read-only;
  - they never write `data/acql.db` or `acql/data/backtest_results.json`.

### Accuracy and data integrity
- Never fabricate historical odds, forecasts, timestamps, results, or backtest
  metrics. If the data does not exist, say so.
- Use only information available at each historical prediction deadline.
  In production, Deadeye's card freezes at the week's first kickoff
  (`oddslock.py`), and `odds.lines_at(week, when)` gives stored lines as of a
  given moment.
- Prevent look-ahead bias and other data leakage. Follow the
  `pricing.model_weight(before=week)` pattern: never fit on the week being
  priced.
- Evaluate candidates against the market-only and current-Deadeye baselines on
  identical games.
- Use chronological walk-forward backtesting.
- Report sample sizes, missing-data coverage, uncertainty, and season-by-season
  results.
- Treat small differences in accuracy as potentially random, and don't claim
  an improvement unless the experiment supports it.
- Never present `backtest.py` proxy results as market or Deadeye performance.

### Development
- Inspect the relevant existing code before editing. Reuse the current
  architecture and dependencies (`requirements.txt`; stdlib `unittest` for
  tests).
- Make the smallest reasonable change for each task.
- Add regression tests in `tests/` for bugs and new behaviour.
- Run the suite and report the actual counts against the baseline above. Never
  delete or weaken tests to make a change pass.
- Never change production settings, deploy, push to GitHub, or commit without
  Sam's approval. In this repo that includes:
  - publishing the pool page (`webpublish.publish`, `AutoPublisher`);
  - sending the recap email;
  - pushing a `v*` tag;
  - publishing to the update channel (`acql/autoupdate.py`);
  - running `python -m acql.backtest`;
  - committing changes to `data/acql.db`.
- Keep a rollback path for changes to prediction logic or model configuration.
  Leave the previous production values recoverable, and say how to revert.
- Never expose private prediction formulas or internal data on the public
  website. `poolpage.snapshot()` is a whitelist: never add Deadeye cards,
  chances, nudged margins, model weights, or backtest data to it. Today its
  only market-derived numbers are finished-week spreads and a team ranking
  built from market lines alone.

### Working style
- For substantial tasks: inspect first, write a concise plan, then implement.
- Identify the important unknowns before making assumptions.
- Work through implementation, testing, and verification before declaring a
  task complete.
- Use parallel agents only for genuinely independent tasks. Agents running
  tests or the app share and rewrite `data/acql.db`, so give each one its own
  worktree.
- Before finishing, report the files changed, tests run, results, remaining
  issues, and the next recommended step.
- For lengthy tasks, keep a concise `PROGRESS.md` at the repo root (goal,
  decisions, done, next step, open questions) so a fresh session can resume
  without repeating the investigation.
- Keep this file concise. Link to existing docs rather than copying them in.
