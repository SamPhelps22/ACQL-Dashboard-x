# Explain This

Tap (or click, or Tab to and press Enter on) an important number on the pool website and a panel opens with:

1. **The value and its definition**
2. **Source records**: the rows it was built from (weekly scores, the coach's line for the week, picks, Big Loser points) and the official file they came from
3. **How it's worked out**: the method and the pool rules that apply (line rule, ties, Big Loser, ranking)
4. **When and which week**: season, week, when the page was built, when the official file was saved, when ESPN's scores were kept
5. **Validation**: whether a second count agrees, and what kind of count it was
6. **Also used in**: the other parts of the site that read the same number
7. **Gaps and issues**: missing data, unreadable picks, games ESPN disagrees on, conflicting files, provisional weeks

Nothing changes on the page until someone asks: tagged numbers look the same as before and only get a gold dotted underline on hover or keyboard focus (a faint one on touch screens). Esc, the × button or a tap outside closes the panel.

## What can be explained (first release)

| Metric | Where it's tagged | Validation |
|---|---|---|
| Weekly score | Standings (Every week, Last week), One week scoreboard, Head-to-head week table | **Independent recount**: every pick re-graded against ESPN's kept final scores with the line rule (`pool.reconcile.check`), Big Loser picks checked against ESPN final margins |
| Season wins | Standings leaderboard, Every week table, podium | Cross-check: official total vs the weekly scores added up |
| Place (coach ranking) | Standings | Cross-check: ranking of the weekly scores added up |
| Rank movement | Standings | Cross-check: place before minus place now, both ranked from weekly scores |
| Head-to-head record | Head-to-head tale of the tape | Built in the browser from weekly scores; the badge is about its inputs (both coaches' weekly scores) |
| Big Loser points | Standings, Side pools | Independent recount from ESPN final margins when every week can be checked; otherwise a cross-check against weekly points |
| Suicide pool status | Standings (the dot) | Cross-check: worked out again from each pick and result with lines applied, and against the files' own elimination flag |

## The status words

| Badge | Meaning |
|---|---|
| **Verified** | A recount from a *different input* (ESPN final scores, pick sheet) agrees |
| **Cross-checked** | Agrees with a second figure in the official files. Explicitly *not* called independent |
| **Doesn't match** | A recount gives a different number. The official figure is shown unchanged; the commissioner decides |
| **Partly checked** | Only part could be recounted (e.g. ESPN has a final for 13 of 14 games) |
| **Not checked** | Nothing could be recounted (no ESPN scores kept, picks unreadable, recount failed) |

The code never writes "verified" for anything that wasn't independently recounted, and never shows a made-up recount: a missing one is `null` and says why. `tests/test_explain.py` holds those rules.

## How it's built

- **`acql/site/explain.py`**: the one registry (`METRICS`: label, definition, method, rules, and the data fields each metric is read from) plus `build()`, which gathers the evidence for a snapshot. It reuses the existing calculations: `reconcile.check` (re-grading), `recap._through` / `recap._places` (totals and ranking), `poolpage._suicide_status`, `results.load` / `fetched_at` (kept ESPN scores, never fetched), `picks.load` (pick sheets). Read-only, no Qt.
- **"Also used in"** is not typed by hand: `shown_in()` scans the website's own code for each metric's data fields, so it follows the code.
- **`poolpage.snapshot()`** adds `explain` to the page data (about 40 KB for a 35-coach, 7-week season). If anything in it fails, the page still goes up and the panel says no evidence was published.
- **`acql/ui/pool_explain/`**: `535-explain-this.js` (the panel, inside the page script) and `explain.css`, joined in like the league modes. **`poolpage.EXPLAIN`** is the switch; off, the page is exactly what it was, and the tags do nothing.
- **Tagging a number** is one call in a view: `xa(node, metric, coach, week, otherCoach)` (in `020-small-helpers.js`). It only sets `data-x` attributes.

### Adding another metric

1. Add an entry to `METRICS` in `acql/site/explain.py` (and its evidence in `build()` if it has its own source or recount).
2. Add its case to `xpExplain()` in `535-explain-this.js`.
3. Tag the number in its view with `xa(...)`.

The registry tests fail if a tag names an unknown metric or the panel doesn't handle one.

## What it found on the real season (built 2026-10-28, through week 7)

Nothing was changed. These are what the panels show:

- **242 of 244 weekly scores independently verified.** The other two are **Not checked** because the picks couldn't be read: Regltr5 week 3, SaleeNmd week 4.
- **Ryan S: season total 51 in the standings export, but his weekly scores add up to 47.** That's a 4-win gap, and he has no week-7 score on file. His place (31st shown, 33rd by recount) and his movement (▼6 shown, ▼8 by recount) are the only places/moves that don't match. It is shown as **Doesn't match** and needs the commissioner's call.
- **Tied places (changed 2026-10-28 at Sam's request):** the site no longer uses the standings export's tie order. Coaches on the same wins share a place, shown as **T-9th** (three coaches on 60 are all T-9th, and the next coach is 12th). This is used across the site: Standings, podium, Head-to-head, coach page, Recap, search and Share my week. Movement arrows compare with last week ranked the same way, so a tie never shows as a move. A coach with no score this week is ranked on their weekly scores up to last week. Done in `poolpage._share_places`, with a `tied` flag per coach and `placeText()` in the page.
- Conflicting files are listed per coach, e.g. MiMi week 3: stats.xls says 9 and was used, the workbook says 8.
- All 35 Big Loser totals independently verified; all 35 suicide statuses cross-check.

## Checking it

```bash
python tests/test_explain.py
```

It is also in CI (`.github/workflows/tests.yml`). Full suite: `tests/run_tests.py` (354 OK), `acql.checks` (8/8), the smoke test, and the website tests (`test_site_quality`, `test_league_modes`, `test_site_layout`, `test_live_modes`, `test_snapshot`) all pass. `test_league_modes`' "modes off" comparison now switches Explain off too.

Screenshots: `data/site-preview/explain/` (git-ignored).

## Not done / caveats

- Built in the worktree `C:\Users\sam52\acql-explain` (branch `explain-engine`). **Not committed, merged, pushed or published.** If merged into the main folder, it goes live at the next automatic publish.
- Coach pages, Recap, Numbers Room, Time Machine and Broadcast read the same numbers (they appear under "Also used in") but their numbers aren't tagged yet.
- Money figures are not explained yet.
- Another session is building an Integrity Engine (`acql/integrity/`, uncommitted, in the main folder). It isn't wired in here. Its results could later feed the Validation section.
