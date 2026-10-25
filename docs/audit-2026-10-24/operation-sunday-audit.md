# Operation Sunday: full system audit, 2026-10-24

Scope: the desktop dashboard (`acql/ui`), the website (`acql/ui/pool_page/`, `acql/site`), data loading (`acql/repository.py`, `acql/sources`), storage (`acql/store.py`), feeds (`acql/feeds`), Deadeye (`acql/model`, `acql/training`) and the scheduled jobs (`acql/headless.py`, `schedule.ps1`).

Labels used throughout: **Measured** means I ran it today. **Read** means I inspected the code but did not run it. **Estimate** means a judgement that has not been tested.

Protected and untouched: Deadeye maths, stored and locked forecasts, ACQL scoring, the Thursday deadline, historical results, and `stats.xls` / `ACQL Dashboard.xlsx`. Nothing was committed, pushed, published or emailed, and no odds requests were spent.

---

## 1. Architecture report

**Size.** 211 Python modules (about 74.7k lines) and 16 test files. The website is one generated page assembled from 56 ordered pieces in `acql/ui/pool_page/` (447 KB of HTML and JS), plus a service worker (`pool_sw.js`).

**Data flow.**

```
stats.xls snapshots ─┐
pick sheets (.xls)  ─┼─ sources.discover → repository.load_season ─→ Season (models.py)
ACQL Dashboard.xlsx ─┘   (merge: stats.xls wins;     │                    │
ESPN scoreboard ── feeds/results ──────────────────┘   conflicts kept)    │
Odds API / OddsPapi ── feeds/odds → store (SQLite)                           │
                                                                             ├─ desktop: ui/app.py → 25 pages (PySide6)
Deadeye: model/pricing, predictions → model/forecastlog (SQLite, locked) ─┤
                                                                             └─ website: ui/poolpage.py builds the JSON + page
                                                                                 → site/webpublish uploads to GitHub Pages
headless.py (Task Scheduler: daily 3am, game days, email Tue–Thu) runs the same loaders without the window.
```

**Sources of truth** (verified against `repository.py`'s own policy):

| Data | Authority | Notes |
|---|---|---|
| Standings, W/L, money, Big Loser / Suicide | newest `stats.xls` | Disagreements are kept as `Conflict`s and not discarded. `pool/standings.py` works the export out itself for weeks `stats.xls` does not yet cover. |
| Slates, pool lines, coaches' picks | commissioner pick sheets | `picks.fill_short_grids` fills short grids up to the official counts. |
| Final scores | graded sheet, else ESPN (`feeds/results`) | |
| Rulings | `pool/rulings.py` | Weeks 3–4 follow stats.xls (Sam's ruling, 2026-10-22). |
| `ACQL Dashboard.xlsx` | optional | Each week it covers is kept as typed; the sheets only check it. |
| Odds, cards, forecasts, caches | `data/acql.db` (SQLite) | Journal mode is DELETE with a busy timeout. Writes are transactional. |
| Locked forecasts | `model/forecastlog.py` tables in SQLite | |

**What should stay as it is:** the merge policy, SQLite as the one store, page-by-page refresh, the website being static and published as a file, and the habit of keeping conflicts visible. All of these are sound.

**Shared logic between the desktop and the website.** The website recomputes some of the pool maths in the browser (for example `blownChance` for Big Loser, and the live "who can still win" in `060-who-can-still-win-the.js`). That means two implementations of the same rules. This is the main duplication risk in the project (see C-3).

---

## 2. Code audit

| # | Finding | Where | Status |
|---|---|---|---|
| C-1 | **Tests wrote fake lines into the real log** (for example `autopsy brief sent: "s"`, `catch-up … started it`, `x left to GitHub`). Today's run added several at 10:19–10:23. This made `data/acql-log.txt` and `digest.py` untrustworthy for diagnosis. | `tests/run_tests.py`, `tests/test_snapshot.py` | **Fixed today** (see §9) |
| C-2 | `nfl lines.csv: 168 games` is rejected on every run. A season-wide file sits where weekly files go, so it fills the log with noise. | `data/` / predictions intake | Open. Sam decides: move or rename the file. |
| C-3 | Pool rules exist twice, in Python and in the browser JS. A dashboard fix does not reach the site (this already happened with Big Loser recalibration). | `acql/pool/bigloser.py` ↔ `pool_page/0x0–350*.js` | Open. Recommended fix: ship precomputed numbers in the site JSON (R-6). |
| C-4 | 363 `except Exception` handlers. Most log or annotate (`# noqa: BLE001` with a reason), and only one bare `except:` was found (`pool/chaos.py`). Silent failures are rarer than the count suggests, but they are not centralised. | across `acql/` | Low. `logbook.trouble` is the right pattern; use it more widely. |
| C-5 | CSV exports in `forecastlog.py` (lines 690, 705, 717, 1066) write in place with `open(..., "w")`. A crash mid-write leaves a truncated export. The store itself is safe (SQLite). | `acql/model/forecastlog.py` | Low. Exports can be regenerated. `config.write_atomic` already exists for this. |
| C-6 | Some pages refresh slowly, per the app's own "slow:" log: Deadeye Picks 7.2 s, Computer models 4.4 s, Model Lab 1.2 s. These figures come partly from hidden test windows on cold first opens, so they overstate everyday use. | `ui/pages/model.py`, `computers.py`, `modellab.py` | Needs a warm-vs-cold profile before any change (P-2). |
| C-7 | `Sunday brief` task Last Result 1 (2026-10-18) with no log line. Earlier this was hard to look into because of C-1. | `headless.py` | Still unexplained. Recheck after Oct 25. |
| C-8 | Several modules exist only on unmerged branches (`lockedextras`, `survivorfield`, `pushalerts`… per the 2026-10-18 note). Some are now on main (`site/lockedextras.py`, `site/pushalerts.py`, `pool/survivorfield.py` are present). | branches | Check each before relying on the branch copies. |

**Security (read, not pen-tested):**
- No hard-coded keys or passwords were found (grep for long literal `api_key/token/password` values: none).
- Secrets are sealed with DPAPI, and the private page uses AES-GCM.
- The repo is public, and older commits still contain `data/acql.db` and the log (known; scrubbing history was never asked for).
- External data is parsed with `xlrd`/`openpyxl` (no macros run) and `json`. No `pickle` or `eval` on outside data was seen.
- `pip-audit` is not installed, so dependency vulnerabilities were **not checked**.

---

## 3. Performance report (measured 2026-10-24, this PC)

| Measure | Result |
|---|---|
| `import acql.ui.app` (cold) | 5.0 s total. numpy 2.1 s, `acql.analytics` 2.4 s cumulative (it pulls in numpy), charts/matplotlib 1.2 s |
| Offline `load_season` (no ESPN) | 1.28 s |
| `acql.checks.run_all()` | 0.17 s, 8 checks |
| Smoke test (load + render 25 pages) | passes; 35 coaches |
| Main test suite | 309 tests, 42–58 s |
| Website payload | 447 KB uncompressed, one page; four `setInterval` loops plus a 60 ms tick (countdown/animation) |
| Live refresh overlap | already guarded (`live.busy` in `050-…js`) |

**Bottlenecks, in order of evidence:**
1. **Startup imports: investigated and dropped (2026-10-24).** The 5.0 s figure above was a cold first run. Warm, `import acql.ui.app` takes 1.57–1.65 s over three runs, of which matplotlib is about 0.7 s and numpy about 0.2 s. Deferring matplotlib would not make the first useful screen appear sooner. The window opens on Phelpy's page (`pages/player.py`, which builds three charts when it is created), and the alternative landing page, `overview.py`, builds two. The cost would only move from import to the first page. `Chart` also subclasses `FigureCanvasQTAgg`, so deferring would mean restructuring 15 pages for no net gain. If a cold start ever matters, the useful version is to show the window frame first and build the landing page a moment later. That is a separate, visible behaviour change.
2. **Deadeye Picks and Computer models: profiled and fixed (2026-10-24).** Measured in a hidden real window with a scratch copy of the database.
   - On a quiet PC, Deadeye Picks took **9.2–9.5 s** on first open and 0.4 s after that.
   - Computer models took 0.7–0.9 s first and 0.5 s after. The 4.4 s in the log was a one-off, so nothing was changed there.
   - The cause was `pool/moneyplan.py` `Weeks.value()`, at 5.3 of 9.1 s. With the real pick sheet known, it rebuilt every other coach's score in every simulated week on each of its 71 calls, although those scores never depend on the card being valued.
   - The fix computes them once per batch in `Weeks.__init__`. The arrays and the arithmetic are the same.
   - **Proof:** the original and new code give identical `value()` results on 720 random cards and identical `plan()` results on 12 random weeks. The planner alone ran 21.3 s → 2.8 s. The page fingerprint (every label and table cell, 1,740 items) is unchanged.
   - **Page timing,** back to back under the same (busy) machine load: first open 38–49 s → 18.4–18.6 s, about 2–2.6× faster. The absolute seconds were inflated by other load at the time. On a quiet machine the estimate is ~9 s → ~4 s, which has not been re-measured.
   - The remaining first-open cost is spread out: cover-chance sums ~1.1 s, flips ~0.8 s, leverage ~0.7 s.
3. **Website 60 ms tick (read).** If it runs while the tab is hidden, it wastes phone battery. Gate it with `document.hidden` / `requestAnimationFrame`. Small, safe win; verify in Chrome.
4. **Website size (measured).** 447 KB is acceptable when gzipped by GitHub Pages (estimate ~90–110 KB). It is not urgent.

---

## 4. Desktop dashboard redesign plan

The current app has 25 pages. The brand (graphite, gold, blue for live, drawn icons, plain tab names) already matches what you asked for. The problem is how many pages there are to get through, not the look.

**Proposed structure:** five groups instead of a flat list.
1. **Sunday**: This Week, Game Day, Cinema, Leverage.
2. **Pool**: Standings, Everyone, Side Pools, Winnings, Teams.
3. **Deadeye**: Picks, Report card, Calibration, Computers, Lab.
4. **History**: Weekly, Hits & Misses, Insights, Charts.
5. **System**: Readiness, Data & Update, the new Health view (F-2).

It always opens on Phelpy, as now.

**Components:**
- One `SlateCard` used by This Week, Game Day and Cinema: kickoff, status pill (Scheduled / Live / Final / Delayed / Postponed), score, pick and confidence.
- One `FreshnessBadge` ("updated 3 min ago", or amber/red when stale).
- One "week strip" header: games scheduled / live / final, the next real kickoff with a countdown, Phelpy's week score, and freshness warnings. All counts come from `Season` and ESPN state, never typed in.

**Technical changes:**
- Lazy imports (P-1).
- Skip-unchanged rendering on the two slow pages.
- Move the remaining sums off the window thread through `workers.py`, which already exists.
- Keyboard shortcuts: 1–5 for groups; Ctrl+K already exists.

---

## 5. Website redesign plan

- **Keep:** the static, one-page build (no framework migration; it has no measurable benefit here), the service worker, the busy guard on live refresh, and keeping the last good scores when a refresh fails.
- **Freshness everywhere:** every live number shows its age. Past a set threshold (suggest 3× the refresh interval) it turns amber with "scores may be behind", and on error it reads "ESPN unreachable, showing 10:42". Part of this exists; make it consistent.
- **States:** one status vocabulary shared with the desktop (Scheduled, Live, Halftime, Delayed, Postponed, Final, Stale, Error).
- **Smallest update:** change only the cells whose score changed and flash them for 1.5 s. Check whether `080-after-new-scores-swings-and.js` already does this before writing new code.
- **Phone:** keep the width checks from the dev notes (342–430 px, `--hide-scrollbars`) as a scripted test (T-4).
- **Battery:** pause timers while the tab is hidden (P-3).
- **Single rule source:** ship Big Loser and "can still win" numbers precomputed in the page's JSON, with the browser recomputing only live deltas (R-6).

---

## 6. Feature proposal

| ID | Feature | Data it needs | Notes |
|---|---|---|---|
| F-1 | Week strip (desktop + site) | Season + ESPN | Quick win once `SlateCard` exists. |
| F-2 | **Health view**: each source's last success, age, last error; odds requests left; each scheduled task's last result; forecast lock status per week; rejected files (e.g. C-2) | log, store, Task Scheduler, forecastlog | Builds on `readiness.py`, `sourcehealth.py` and `digest.py`. Needs C-1 fixed first (done). |
| F-3 | Analytics, kept separate: (a) pool results, (b) pick accuracy, (c) probability calibration, (d) Deadeye vs market | `training/record.py`, `calibration.py` | Each metric shows its definition, source, n and a confidence interval. Only weeks 5+ count as saved-before-deadline; earlier weeks are labelled "rebuilt". No combined score. |
| F-4 | Confidence-tier report: points won by tier, against what the tier was expected to win | picks, results | Descriptive only. |
| F-5 | Weekly export: PDF/PNG report of the week (standings move, Phelpy vs field, Deadeye vs line) | existing recap code | `ui/recap.py` already makes pictures. |
| F-6 | Release gate: `packaging/release.py` refuses to build unless all 16 test files, `checks` and the smoke test pass | tests | CI already runs these; this adds the same gate locally. |
| F-7 | Provider interface: one `fetch() -> (data, fetched_at, error)` shape for ESPN, Odds API, OddsPapi and PFM | feeds | Makes F-2 straightforward. Refactor only, no change to outputs. |

There is no internal API or service layer. The desktop app and the website already share Python (the site is built by the same process), so a server would add moving parts without solving a real problem.

---

## 7. Prioritised roadmap

**Priority 1: correctness and integrity**

| Item | Effort | Risk | Validation |
|---|---|---|---|
| ✅ C-1 Tests isolated from the real log (done) | S | none | log byte count unchanged across every test file |
| C-2 Deal with `nfl lines.csv` (Sam: move it) | XS | none | rejection line stops |
| C-7 Sunday-brief failure: read the log after Oct 25, now that it's clean | S | none | a clear cause, or a clean run |
| C-5 Atomic CSV exports (`config.write_atomic`) | S | low | byte-identical exports before and after |
| Install and run `pip-audit` (a download, needs your OK) | XS | none | report |

**Priority 2: performance and reliability**

| Item | Effort | Depends on | Validation |
|---|---|---|---|
| P-1 Lazy-import matplotlib/analytics | S–M | – | import time before and after; smoke test; output fingerprints identical |
| P-2 Profile, then fix, Deadeye Picks and Computer models | M | – | warm refresh under 1 s; fingerprints identical |
| P-3 Pause website timers while the tab is hidden | XS | – | headless Chrome check |
| F-7 Common feed interface | M | – | all feed tests; same stored data |

**Priority 3: product overhaul**

| Item | Effort | Depends on |
|---|---|---|
| Shared tokens file (colours, spacing, status names) read by `theme.py` and the site build | M | – |
| `SlateCard` + `FreshnessBadge` + week strip (desktop, then site) | M–L | tokens |
| Five-group navigation | M | – |
| F-2 Health view | M | C-1 ✅, F-7 |
| R-6 Precomputed pool numbers in the site JSON | M | tests comparing JS and Python numbers |

**Priority 4: advanced**

F-3 analytics suite, F-4 confidence tiers, F-5 exports, F-6 release gate, and configurable landing cards.

**Quick wins:** C-2, P-3, C-5, F-6.
**Architectural work:** tokens, R-6, F-7, navigation.

**Sequence:** P1 items → P-1/P-3 → F-7 → tokens → SlateCard/week strip → Health view → R-6 → analytics. Foundations land before the features that rely on them.

---

## 8. Testing report

| Suite | Tests | Result |
|---|---|---|
| `tests/run_tests.py` | 309 | OK (twice: before and after the change) |
| 15 standalone `tests/test_*.py` | 282 | all OK |
| `acql.checks.run_all()` | 8 | ran, 0.17 s |
| `python -m acql.ui.app --smoke-test` | 25 pages | OK |

Total: 591 tests passing. CI (`.github/workflows/tests.yml`) runs the same set.

**Missing coverage:**
- Nothing checks that the JS pool maths matches the Python (C-3).
- No scripted website width/phone test (the dev notes describe a manual method).
- No test that a failed live refresh keeps the last scores and shows their age.
- No timing regression test for page refreshes.
- No test that a locked forecast cannot be rewritten by a re-run (the check may already exist; verify in `test_record.py` / `forecastlog`).

**Not done:** browser testing of the live site, `pip-audit`, and profiling of individual pages.

---

## 9. Implementation summary

| File | Change | Validation |
|---|---|---|
| `tests/run_tests.py` | Points `ui.pages.base.log_path` at a temp file for the run | 309 OK; real log unchanged in size (132,389 bytes before and after) |
| `tests/test_snapshot.py` | Same, for the one standalone file that wrote to the log | 5 OK; real log delta 0 |

There are no app code changes. Both edits are uncommitted. Line endings are kept (CRLF).

Note: before the fix, today's test runs had already left fake lines in the log at 10:19:42–10:19:46 and 10:23:17. They were left in place, not deleted.

---

## 10. Next steps

1. **Move or rename `nfl lines.csv`** (your call): it is the one recurring rejection in the log.
2. **P-1 lazy imports.** This is the biggest measured startup cost, it is a contained change, and it can be proven with output fingerprints.
3. **Profile Deadeye Picks** warm vs cold before redesigning the page.
4. **Shared design tokens + SlateCard.** This unlocks the unified look on both screens.
5. **Health view.** Now possible because the log is trustworthy.
