# Operation Sunday: overnight sprint, 2026-10-25

**Run:** 00:50–02:30 Sunday morning (game day), in the shared working folder, alongside Sam's open dashboard, the 2 am scheduled job and another Claude session working on the website (`data/site-preview/ui-audit/parts-r2`).

**Labels used below:** **Done** means changed, tested and checked here. **Proposed** means written up but not built. **Measured** means I ran it. **Read** means I looked at the code without running it.

Nothing was committed, pushed, published, emailed or downloaded. No odds requests were spent by this work. The `odds` lines in the log at 02:00 are the scheduled 2 am job.

---

## 1. Executive summary

- **Live feeds no longer fail a whole week over one bad game.** I fed deliberately broken data to the score reader, using the 201 ESPN scoreboards saved on this PC, and found **12 places** where one malformed field raised an error. The week's update then failed and the round stopped. ESPN scores, the Odds API, OddsPapi (backup lines), the injury report and the weather now skip an unreadable item on its own and write it to the log once. The fuzz now finds **0** crash sites. Every saved real payload reads **byte-identically** before and after.
- **Unreadable is never shown as quiet or fresh.** If ESPN sends games but none can be read, that is now a failure, not an empty week. The same goes for the injury report, which would otherwise read as "nobody hurt". The Readiness "Scores" row now dates scores from the last answer that actually had games. Before, it used the last time ESPN was *asked*, so repeated empty replies made old scores look fresh.
- **The predictions download lands whole.** The scheduled job wrote it straight into the folder the dashboard watches, so the dashboard could read half a file, and a crash mid-write could leave a truncated one. It now writes to a temp file and swaps it in, byte for byte.
- **Readiness page: 1.2 s → 0.04 s on repeat refreshes (measured).** It ran Task Scheduler and three `git` commands on the window's thread at every redraw. Each answer is now reused for 60 s. All 29 checks come out identical.
- **The log tells checks apart from real use.** The smoke test, the self-check and hidden test windows now write `slow (check run):` instead of `slow:`.
- **New analytic: how much a head-to-head record can be read into.** The decision journal on the Report card now says how many results would have to flip to reverse "you vs Deadeye", plus an exact sign test. With Sam's numbers (5 vs 12 over 17 decided games), 4 flips would reverse it, and a coin does that well about 1 time in 7, so it is still within luck. I checked this on the real rendered page.
- **Tests: 309 → 338 in the main suite (+29), all passing.** All 15 standalone files (302 tests), 8 self-checks and the smoke test also pass.
- **No changes to Deadeye, pricing, scoring, locked forecasts, the deadline or source files.**

## 2. Architecture findings (this sprint)

The 2026-10-24 audit's map still holds (`docs/audit-2026-10-24/operation-sunday-audit.md`). New findings:

- **One root cause across five feed readers:** each loop over a source's list trusted every item's shape, so one odd item raised out of the whole loop. Fixed with one shared helper, `feeds.keep_readable(items, read, where)`. Per-item reading is now a function (`results._event`, `odds._quote`, `odds._book_numbers`, and inner functions in `injuries.parse` and `oddspapi.parse`).
- **Timestamps:** `results.fetched_at` (last answer with games) already existed for exactly this purpose, and the live-game cards (`pool/livestate.py`) use it. Readiness was the one screen still using `checked_at`.
- **Blocking work on the window thread:** subprocesses (`schtasks`, `git`) were the largest cost on the Readiness page. Other slow first opens are Deadeye's own pricing work (Recipe, Model Lab, Deadeye Picks), which is protected.
- **Already sound, verified tonight:** overlapping refreshes are guarded (`app.py`: the loader, results and timeline workers each check `isRunning()`). Corrupt, truncated or empty `stats.xls`, pick sheets and workbook each become a named warning while the season still loads (tested on copies, see §6). The Thursday deadline and fallback kickoff are correct across next Sunday's clock change (week 8: Thu Oct 29 6:30 pm CDT; week 9: Thu Nov 5 6:30 pm CST). SQLite writes are transactional, and settings and aliases already used atomic writes.

## 3. Bugs and risks discovered

| # | Kind | Finding | Status |
|---|---|---|---|
| B-1 | Verified bug | One malformed game in ESPN's scoreboard failed the whole week's update and stopped the refresh round (12 crash sites found by fuzzing). | **Done** |
| B-2 | Verified bug | Same pattern in the Odds API reader (after the 3 paid requests are spent), OddsPapi, the injury report and the weather. | **Done** |
| B-3 | Verified bug | Readiness dated scores by when ESPN was *asked*, so old scores could show as fresh. | **Done** |
| B-4 | Regression risk from B-1 (caught before it shipped) | A total ESPN format change would have read as an empty week, and an unreadable injury report as "nobody hurt". | **Done**: both are now failures |
| B-5 | Reliability | The predictions download was written in place into a watched folder. | **Done** (atomic) |
| B-6 | Verified performance | Readiness blocked the window for about 1.2 s per refresh. | **Done** |
| B-7 | Diagnostics | Check runs wrote `slow:` lines that look like real slowness. | **Done** (labelled) |
| B-8 | Correction | Last audit's P-3 (website "60 ms tick wastes battery") is not a problem. The 60 ms timer is the boot animation and stops within 1.7 s, and browsers throttle hidden-tab timers. | Closed, no change |
| B-9 | Note | A week-7 game, NYG @ HOU, is on ESPN's week 7 for today at noon, so the journal's "1 still to play" is correct. | No action |

## 4. Exact files changed (all uncommitted)

| File | Change |
|---|---|
| `acql/feeds/__init__.py` | `SHAPE_ERRORS`, `keep_readable()` |
| `acql/feeds/results.py` | `parse` reads each game alone (`_event`). `fetch` fails when games were sent but none could be read. |
| `acql/feeds/odds.py` | `parse` reads each game (`_quote`) and each book (`_book_numbers`) alone. A NaN, Infinity or `true` point is not a line (`_finite`). |
| `acql/feeds/oddspapi.py` | `parse` reads each fixture alone. |
| `acql/feeds/injuries.py` | Each team and each player read alone. A team whose list is unreadable is left out (unknown), never shown as healthy. `fetch` fails when nothing could be read. |
| `acql/feeds/weather.py` | One game's bad forecast is skipped; the week's others are kept. |
| `acql/config.py` | `write_atomic_bytes()`. `write_atomic` shares its body and its output bytes are unchanged (tested). |
| `acql/headless.py` | The predictions download is written atomically. |
| `acql/readiness.py` | Scores dated by `fetched_at`. Task Scheduler and git answers reused for 60 s (`_remembered`). |
| `acql/ui/pages/base.py` | `CHECK_RUN` flag. Slow lines say `(check run)` when it is set. |
| `acql/ui/app.py` | Hidden windows, the smoke test and the self-check set `CHECK_RUN`. |
| `acql/pool/journal.py` | `Fragility` (games to flip, exact sign test, plain words). |
| `acql/ui/pages/reportcard.py` | One sentence from `Fragility` under the journal's tally. |
| `tests/run_tests.py` | 10 new test classes plus 2 tests in the OddsPapi class, 29 tests (listed in §6). |
| `docs/sprint-2026-10-25/*` | This report and the opportunity register. |

Left exactly as found: the 9 website files from yesterday's applied UI fixes (`acql/ui/pool_page/*`, uncommitted). I made no website changes, because the folder publishes itself on game day and another session is working on the site.

`data/acql-log.txt` (git-ignored) had housekeeping of my own lines only. 14 fake "unexpected shape" lines from my first fuzz run, before I redirected its log, were removed. So were 2 "slow: Report card" lines from a hidden screenshot window. 23 lines from my 01:56 smoke test were relabelled `slow (check run):`. A backup taken before the first removal is in the session scratchpad. No other log lines were touched.

## 5. Improvements and why

- **One bad item no longer takes down a feed.** On game day the scores are the product. A single odd event in ESPN's reply used to blank every live score update for that round.
- **Fail loudly when nothing is readable.** Skipping items must not turn a format change into silence.
- **Honest freshness.** "Never report stale data as fresh."
- **Atomic intake.** The dashboard reloads on file changes, so a half-written CSV could be read mid-write.
- **Readiness speed.** It is the page you open when something looks wrong, so it shouldn't freeze the window.
- **Fragility sentence.** The journal said "you 5, Deadeye 12" with no sense of how much that means. The sign test answers it without claiming more than the sample supports.
- **Log labels.** The log is the main diagnosis tool, and check runs were polluting it.

## 6. Tests executed and actual results

| What | Before | After |
|---|---|---|
| `tests/run_tests.py` | 309 OK (72 s) | **338 OK** (80 s) |
| 15 standalone `tests/test_*.py` | 302 OK | 302 OK |
| `acql.checks.run_all()` | 8 of 8 | 8 of 8 |
| `python -m acql.ui.app --smoke-test` | OK, 35 coaches, 25 pages | OK |
| Feed fuzz (2,134 field paths × 11 junk values on a real scoreboard) | 12 distinct crash sites | **0** |
| Feed fingerprints over every saved real payload (201 ESPN scoreboards / 2,822 games, odds, injuries) | `50de2416…`, `c73cded2…`, `22f078c1…` | **identical** |
| Same, re-proved after the 2 am job added payloads: committed (HEAD) parsers, run from a `git archive` copy, against tonight's, on all 203 scoreboards / 2,850 games, 2 odds replies, 3 injury reports | `7ea7000c…`, `303c6c3b…`, `151863fe…` | **identical** |
| Readiness checks fingerprint (29 checks) | `626a50ae337760a5` | **identical** |
| Corrupt-spreadsheet loads on copies (truncated, garbage and empty `stats.xls`, truncated pick sheet, broken workbook) | all load with a named warning | unchanged (nothing to fix) |

New test classes: `TestFeedsSkipWhatTheyCantRead` (7), `TestWholeFileWrites` (3), `TestPredictionsDownloadLandsWhole` (3), `TestUnreadableIsNeverQuietOrFresh` (3), `TestWeatherOneGameAtATime` (1), `TestOddsPapiBackup.test_an_odd_fixture_leaves_the_rest_of_the_board` and `test_any_shape_of_fixture_is_survived` (2), `TestJournalFragility` (2), `TestCheckRunsAreLabelledInTheLog` (2), `TestReadinessReusesSlowAnswers` (2), `TestReadersSurviveAnyShape` (3: every field of the ESPN, Odds API and injury samples swapped for 11 kinds of junk; this is O-1, done). One test failed on its first run and changed the design. A team with an unreadable injury list came out as "no injuries", so the reader now leaves that team out instead.

The final verification run's actual output is pasted in §13.

## 7. Before and after performance (measured, this PC, game-day night)

| Measure | Before | After |
|---|---|---|
| `readiness.build` as the page calls it, 2nd and 3rd refresh | 1.25 s, 1.20 s | **0.04 s, 0.04 s** |
| `readiness.build`, first open | 2.13 s | 2.25 s (same work; noise) |
| of which: Task Scheduler query / 3 × git | 0.78 s / 0.52 s | asked once a minute at most |
| Recipe week scan (`recipe.simulate` × 8 weeks) | 1.30 s cold, 0.21 s warm | unchanged: it is Deadeye pricing, protected |
| Cold first opens from the smoke test (01:56) | Deadeye Picks 5.5 s, Model Lab 2.8 s, Recipe 2.3 s, Readiness 2.0 s, Leverage 1.6 s, Computer models 1.2 s, Standings 1.1 s | not changed tonight except Readiness |

## 8. Prediction and scoring integrity checks

- No file under `acql/model/`, nor `acql/pool/{standings,picks,bigloser,survivor,moneyplan}.py`, nor `oddslock.py` was changed.
- `TestGoldenWeek` (the pricing fingerprint) and the self-checks "Pricing a game", "The pool's line rule" and "Finishing first, ties shared" pass.
- The odds reader gives identical quotes on the real saved reply. The only values it now drops are non-numbers (NaN, Infinity, `true`), which no real book sends.
- No locked forecast, snapshot, pick sheet, `stats.xls` or `ACQL Dashboard.xlsx` was opened for writing. The corrupt-file tests used copies in a temp folder, and profiling used a copy of `acql.db`.
- The fragility sentence is descriptive only. It reads the journal's existing tallies and changes no pick or verdict.

## 9. Issues that remain unresolved

- **C-2 (from 10-24):** `nfl lines.csv` is still turned away on every run. Sam to move or rename it.
- **C-7:** the Sunday brief task "Last Result 1" on 2026-10-18 is unexplained. Today's run (Sunday) is the first chance to see it with a clean log.
- **Cold first opens** of Deadeye Picks, Model Lab and Recipe (2–5 s) are Deadeye pricing work. Making them faster means touching protected code or moving the work to a thread. That is a proposal (O-3), not done.
- **The website still re-implements pool maths in JS** (C-3 / R-6 from 10-24). Not touched.
- **C-5:** `forecastlog.py` CSV exports still write in place. They are user-triggered exports that can be regenerated, and the module sits beside the locked-forecast code, so it was left alone.

## 10. Considered and intentionally not done

- **Any website change.** The folder auto-publishes on game day, and another session is mid-way through a website round (`parts-r2`). Website ideas are in the register as proposals.
- **Speeding up Recipe, Model Lab or Deadeye Picks.** The cost is in pricing (`pricing.price`, `analytics.cover_chance`), which is protected.
- **Keeping a skipped live game's last score.** When ESPN leaves out a game that isn't final (or it can't be read), `results.save` drops its in-progress score until the next good look. Keeping it would change how a game that genuinely moved weeks is handled, so this is a proposal (O-6).
- **pip-audit:** it would need a download, so it is Sam's call.
- **Confidence-point analytics** (the brief's "confidence tier" charts). ACQL has no confidence points, as it is pick'em against pool lines. That idea belongs to `nfl_pickem`.
- **A new design-token system.** `acql/ui/tokens.py` already exists and `livestate` uses its freshness limits. A shared token file for the website is in the register.

## 11. Prioritised recommendations for the next sprint

See `improvement-register.md` §9–10. In short:

1. **O-1 (mostly done tonight: ESPN, Odds API, injuries, OddsPapi).** Extend the fuzz test to `timeline.parse` and the `pfm.parse_*` page readers.
2. **O-2 Readiness on a worker thread**, so the first open (2.2 s) doesn't block either.
3. **O-3 Cold-open warm-up** for Deadeye Picks and Model Lab: extend `workers.warm_this_week` (the pattern already exists) so the first click is warm. No maths change.
4. **R-6 (from 10-24) site numbers precomputed in Python.**

**When the changes take effect:** the scheduled jobs (`headless.py`) run from this folder, so today's game-day runs already use the hardened feed readers. The dashboard you have open runs the code it started with, so the Readiness speed-up, the journal sentence and the log labels appear after it is restarted.

## 12. Launching and verifying

```bash
.venv\Scripts\python.exe tests\run_tests.py
```
```bash
.venv\Scripts\python.exe -m acql.ui.app --smoke-test
```
```bash
.venv\Scripts\python.exe -c "from acql import checks; print([(c.name, c.ok) for c in checks.run_all()])"
```

- Open the dashboard as usual (`ACQL Dashboard.bat`).
- **Report card → "Your calls against it"** shows the new sentence after the tally.
- **Readiness:** open it, switch away, and come back within a minute; it should come back at once.
- To see the feed hardening, run the main suite. The `TestFeedsSkipWhatTheyCantRead`, `TestUnreadableIsNeverQuietOrFresh` and `TestWeatherOneGameAtATime` classes cover it.

Review the changes:

```bash
git diff --stat -- acql tests
```

Commit only the files in §4 and §14. The `acql/ui/pool_page/*` files are the website fixes (round 1 from 10-24, plus round 2 applied by another session on 10-25) and belong to that change.

## 13. Final verification run (pasted output)

Run at about 02:15, after every code change except the OddsPapi fuzz test (which was then added, and the main suite re-run: **338 OK, 80 s**):

```
Ran 334 tests in 75.867s
OK
tests/test_calibration.py: Ran 25 tests  OK      tests/test_pushalerts.py: Ran 8 tests  OK
tests/test_chaos.py: Ran 8 tests  OK             tests/test_record.py: Ran 7 tests  OK
tests/test_gameday_live.py: Ran 31 tests  OK     tests/test_research_lab.py: Ran 14 tests  OK
tests/test_guard.py: Ran 8 tests  OK             tests/test_snapshot.py: Ran 5 tests  OK
tests/test_leverage.py: Ran 8 tests  OK          tests/test_strategy_lab.py: Ran 26 tests  OK
tests/test_mail_retry.py: Ran 8 tests  OK        tests/test_sunday.py: Ran 6 tests  OK
tests/test_model_lab.py: Ran 38 tests  OK        tests/test_training.py: Ran 51 tests  OK
tests/test_pfm.py: Ran 39 tests  OK
checks 8 of 8 ok
Smoke test OK: 35 player(s) loaded, 25 pages rendered, icon found.
[2026-10-25 02:14:47] slow (check run): Readiness took 2183 ms to refresh   <- the smoke test, now labelled
```


## 14. Follow-up the same morning: O-3, pre-warming Deadeye Picks and Model Lab (done)

Sam asked for O-3 "with an output fingerprint to prove nothing changes".

**What the measurement found first:** the "5.5 s" Deadeye Picks figure came from the smoke test, which turns the warm-up off. With the warm-up on, as in real use, the first open was still **5.3 s**, because 2.8 s of it was the "Turns at" column (`flips.week_flips`), which the warm-up never computed. The Model Lab (3.4 s) had no warm-up at all.

**Changes:**

| File | Change |
|---|---|
| `acql/ui/workers.py` | `warm_this_week` gains a last step, `turns`, which computes the flips once. Its answers live in the chance maths' existing process-wide caches (`analytics.margin_distribution`, `_at_least`), so no new cache is involved. It runs last, so other steps can't push those answers out first. New `warm_model_lab` works out `modellab.run` and `livecheck.study` and hands them over. `Warmer` takes `this_week=False` for reloads. |
| `acql/ui/handoff.py` (new) | A one-time hand-off: a page takes a warmed answer **once**, and only if it was worked out from the very season object it is showing. Otherwise it computes, exactly as before. A newer load can never be shown an older answer. |
| `acql/ui/pages/modellab.py` | The two sums go through `handoff.take(...)`. |
| `acql/ui/app.py` | After a reload (whose loader already warmed This Week before handing over), the Model Lab warm-up starts on the window's existing low-priority thread, so fresh scores never wait for it. |
| `tests/run_tests.py` | `TestWarmUpHandOff` (3): once-only, same-season-only, the warm-up hands over both sums, and a failed warm-up leaves the page to do it. |

**Proof (hidden real window at 1366 × 900, on a copy of the database, log to a scratch file):** a fingerprint of every visible label and table cell on each page.

| Run | Deadeye Picks first open | Model Lab first open | Fingerprints (1,376 / 568 items) |
|---|---|---|---|
| Before, warm-up off | 10.65 s | 3.61 s | `7388f497…` / `903c64f1…` |
| Before, warm-up on (real use) | 5.28 s | 3.40 s | same |
| After, first load (3 runs) | 2.86, 2.56, 2.77 s | 1.90, 1.95, 1.98 s | **identical** |
| After, following a reload | 2.55 s | 2.11 s | **identical** |
| After, warm-up off (the pages' own path) | 7.16 s | 2.29 s | **identical** |

Timings move ±0.5 s with machine load (another session was running), so these are the run values, not averages. What remains of Deadeye Picks' first open (about 2.5 s) is drawing widgets (`_update_why`, tables, suicide path), which has to happen on the window's thread. The flips there are now 0.08 s.

**Cost:** the warm-up takes about 1.5 s longer, off the window's thread and at low priority. A page opened while it runs waits for at most one step (`WORKING` lock), as before.

**Tests:** main suite **341 OK**; `test_model_lab.py` and `test_leverage.py` OK; smoke test OK; no "warm-up: … not done ahead of time" lines in the log.


## 15. Round three the same morning ("go"): the rest of the safe list (done)

| Item | Change | Evidence |
|---|---|---|
| **O-1 finished** | `feeds.items()` (a list sent as anything else is no items). Used in `timeline._plays` and `pfm.parse_changes`. The fuzz test now covers every outside-data reader: ESPN scores, play-by-play, Odds API, OddsPapi, injuries, PFM changes. | Fuzz: timeline 3 → 0 crash sites, PFM 2 → 0. Identical output on valid input (`items(x) == x` for any list). |
| **O-2 Readiness off the window's thread** | `pages/readiness.py` builds on a daemon thread, under the shared `WORKING` lock. It keeps the last answer on screen meanwhile, asks once more if asked mid-check, and shows a failure in the page's usual "couldn't finish drawing" view. Check runs (smoke test, self-check) still build on the spot, so their pictures are complete. A theme change redraws the last answer without working it out again. | Hidden real window, first open, two runs each: **window held 2.06 / 1.98 s → 0.83 / 0.67 s**; page complete at 1.35–1.46 s. The drawn page is identical to the on-the-spot path (108 labels, same fingerprint). |
| **O-4 fragility on the Report card** | The "own calls" line (for any coach) ends with the same sentence as the journal. `Fragility.words(coach)` names both sides ("that split Phelpy and Deadeye"). | Real data: "...came in 5 times: -7 wins. 4 of the 17 results that split Phelpy and Deadeye going the other way would put Phelpy ahead; ... about 1 time in 7 - so it is still within what luck alone does." A test proves the headline and tone are unchanged. |
| **O-5 unreadable items on Readiness** | `keep_readable` keeps a note per source when it leaves something out (`feeds.note_skipped`, store kind `feed-skips`, parts of one answer added up). Readiness shows an "Unreadable items" note row for 48 hours, and no row otherwise. | 3 tests. No such note exists in the real database (checked). |
| **Window-thread guard test** | `TestNoSubprocessOnTheWindowThread`: opening Readiness in everyday use runs no subprocess (Task Scheduler, git) on the window's thread. | It would fail on the old page; passes now. |
| **New bug found and fixed** | `Chart._draw_idle` asked a deleted chart for `visibleRegion()` when matplotlib's queued 0 ms draw fired after a page had cleared it ("Internal C++ object already deleted"). It now returns when the chart is gone. | Reproduced in a 10-line script, then fixed. A regression test calls the queued draw on a deleted chart. |

Also: the website round committed by another session (`d5587e6`, Sam, 09:17) contains only the 14 `pool_page` files. Every uncommitted change left in the folder is from this sprint.

**Verification after round three:**
- Main suite **354 OK** (`TestReadinessOffTheWindowThread` 4, `TestReportCardSaysHowMuchTheCallsMean` 2, `TestUnreadableItemsShowOnReadiness` 3, `TestChartDeletedBeforeItsDraw` 1, `TestNoSubprocessOnTheWindowThread` 1, plus 2 fuzz tests for play-by-play and PFM).
- All 15 standalone files OK; self-checks 8 of 8; smoke test OK.
- **Feed readers vs committed code:** identical on every saved payload, now 312 ESPN scoreboards / 4,376 games, 2 odds replies, 4 injury reports (the archive grew during today's games).
- **O-3 re-proved on a frozen copy of this afternoon's database:** Deadeye Picks (1,372 items) and Model Lab (568 items) give identical fingerprints with the warm-up off, with it on, and after a reload. The first-open figures were 4.71 s off → 1.94 s on → 1.06–1.22 s after a reload (Deadeye Picks), and 1.88 s off → 1.35 s on → 0.91 s after a reload (Model Lab). After the reload, both Model Lab sums were confirmed ready and matched to the new season before the page was opened. (This morning's fingerprints differ only because today's games have since been played.)
