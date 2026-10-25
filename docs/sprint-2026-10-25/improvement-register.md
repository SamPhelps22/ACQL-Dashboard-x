# Operation Sunday: improvement opportunity register (2026-10-25)

Classes: **1** verified bug · **2** verified performance issue · **3** reliability/security risk · **4** usability · **5** architecture · **6** new feature proposal · **7** unverified hypothesis.
Effort and risk are S (small), M (medium) or L (large).

Completed fixes (§1–2) are kept apart from proposals (§3 onward).

---

## 1. Verified issues found and fixed this sprint

| ID | Class | Description | Evidence | Root cause | Effort / risk | Status |
|---|---|---|---|---|---|---|
| S-1 | 1 | One malformed ESPN game failed the whole week's score update | Fuzz: 12 crash sites over 2,134 field paths of a real saved scoreboard | Per-item shape trusted inside a whole-list loop | S / low | **Fixed**, 7 tests, identical output on 2,822 real games |
| S-2 | 1 | Same in the Odds API, OddsPapi, injury and weather readers | Read, plus tests that fail on the old code | Same root cause as S-1 | S / low | **Fixed** |
| S-3 | 1 | Readiness "Scores" could show old scores as fresh | Test: an empty reply 3 h later read "just now" | Used `checked_at`, not `fetched_at` | XS / low | **Fixed** |
| S-4 | 3 | An unreadable ESPN or injury reply would read as an empty week or "nobody hurt" | Found while reviewing S-1's design | Skipping items needs a "none readable" floor | XS / low | **Fixed** |
| S-5 | 3 | Predictions download written in place into a watched folder | Read: `headless._download_predictions` | `write_bytes`, not atomic | XS / low | **Fixed**, 3 tests |
| S-6 | 2 | Readiness blocked the window about 1.2 s per refresh | Measured: schtasks 0.78 s plus git 3 × 0.17 s | Subprocesses on the window thread at every redraw | XS / low | **Fixed**: 0.04 s |
| S-7 | 4 | Check runs wrote `slow:` lines that look like real slowness | Seen in the log at 01:56 and 00:52 | `write_log` doesn't know about checks | XS / none | **Fixed** (labelled) |

## 2. Things checked that were already handled (no change)

| Scenario (from the brief's adversarial list) | Result |
|---|---|
| Two refreshes overlap | Guarded: each worker checks `isRunning()` (app.py ~920–1050). The website has `live.busy`. |
| Spreadsheet missing, corrupt or truncated | Tested on copies: each becomes a named warning and the season loads (35 coaches, 8 weeks). |
| API unavailable or late | Every network call has a timeout. ESPN failures are recorded (`results.last_failure`) and shown with their age. |
| A game is delayed or its kickoff changes | Each look re-reads the kickoff; the lock follows ESPN's first kickoff. |
| A final score is later corrected | `feeds/recheck.py` re-checks finals and keeps corrections. |
| A final goes back to "in progress" in a later reply | `results.save` never downgrades a kept final. |
| Clock and time zones | The deadline uses local `mktime(isdst=-1)` and kickoffs are UTC. Correct either side of the Nov 1 clock change (checked). |
| App closes mid-write | SQLite transactions; settings and aliases atomic; now the predictions download too. |
| Restart with stale cache | Freshness comes from stored times, never from "just loaded" (`livestate.freshness`). |
| Website battery (last audit's P-3) | Not an issue: the 60 ms timer stops within 1.7 s, and the game-day strip already checks `document.hidden`. |

## 3. Root causes that show up in more than one place

1. **Shape trust in readers of outside data.** Five feed readers had it (fixed). `timeline.parse` and the PFM page parsers are the rest (O-1).
2. **Two timestamps, "asked" and "answered".** They exist for scores, but only some screens used the right one (fixed for Readiness). Any new freshness display should take `fetched_at` / `livestate.Freshness`, never `checked_at`.
3. **Blocking work on the window thread.** The subprocesses are fixed. Pricing-heavy first opens remain (O-2, O-3).
4. **Pool rules written twice, in Python and JS** (from 10-24, still open, R-6).

## 4. New ideas generated beyond the brief

| ID | Class | Idea | Problem solved | How | Data exists? | Effort / risk |
|---|---|---|---|---|---|---|
| O-1 | 3 | Fuzz every outside-data reader in CI (**done for ESPN, Odds API, injuries and OddsPapi**: `TestReadersSurviveAnyShape` and `TestOddsPapiBackup.test_any_shape_of_fixture_is_survived`; timeline and PFM still to add) | Shape trust comes back with each new reader | A test that mutates a fixture of each reader (the harness from this sprint, `fuzz_espn.py`) and asserts no exception | Yes (fixtures in tests) | S / none |
| O-2 | 2 | Readiness built on a worker thread | 2.2 s first open still blocks | `workers.py` pattern: build in a QThread, draw on finish | Yes | S–M / low |
| O-3 | 2 | Pre-warm Deadeye Picks and Model Lab after load (**done 10-25 morning**: 5.3 s → 2.6 s and 3.4 s → 1.9 s, fingerprints identical; handoff §14) | 2.8–5.5 s cold first open | Extend `workers.warm_this_week` (already used for This Week); same cache, same numbers | Yes | M / low |
| O-4 | 6 | Fragility everywhere a record is compared | "Deadeye 16 vs line 17" and "card vs coach" leads have no sense of scale | Reuse `journal.Fragility` on the Report card lead and the Model Lab's saved-before-deadline record | Yes | S / none |
| O-5 | 6 | "Skipped items" counter on Readiness | A reader skipping items is logged, but not shown | Count skips per source in `sourcehealth.record` notes; show "1 game unreadable" on the Scores row | Yes | S / low |
| O-6 | 3 | Keep a live game's last score when one reply leaves it out | One odd reply blanks that game until the next look | In `results.save`, keep a non-final game missing from a non-empty reply if its kickoff is within the week | Yes | S / **medium**: needs a rule for games that really moved weeks |
| O-7 | 4 | Website and desktop share freshness limits | The two screens can call the same data fresh and stale at different ages | Export `tokens.FRESHNESS` into the site JSON | Yes | S / low (website: show Sam first) |
| O-8 | 5 | One `fetch() -> (data, at, error)` shape for feeds | Each feed has its own error and freshness bookkeeping | Was F-7 on 10-24; S-1–S-4 make it easier | Yes | M / low |
| O-9 | 6 | "Weeks you'd have won with Deadeye's card" | Answers "how much did the overrides cost in the pool, not just in picks" | `ghost.py` already scores Deadeye's card as a coach; compare places week by week | Yes | S / none |
| O-10 | 6 | Calibration by data freshness | "Do stale feeds correlate with worse forecasts?" (from the brief) | `known.py` snapshots plus source-health history per week | Partly: only weeks 5+ are clean | M / none; small sample, label it |

## 5. Strongest unimplemented ideas, ranked by expected value

1. ~~O-3 Pre-warm the slow Deadeye pages.~~ Done (handoff §14).
2. **R-6 Site pool numbers precomputed in Python.** Removes the duplicated rules (risk to the public site).
3. **O-1 Reader fuzz in CI.** Partly done; add timeline and PFM.
4. **O-6 Keep the last live score through one odd reply.** Matters only on game day, but that's when it matters.
5. **O-4 Fragility on every record comparison.** Makes every "who's better" claim honest.
6. **O-2 Readiness on a thread.**
7. **O-9 Weeks won with Deadeye's card.**
8. **O-5 Skipped-item counts on Readiness.**
9. **O-7 Shared freshness limits.**
10. **O-8 Common feed interface.**

## 6. Architectural improvements worth considering

- **Feed interface (O-8)** before adding more sources. Five readers now share `keep_readable`; the bookkeeping (when asked, when answered, last failure) is next.
- **Site numbers from Python (R-6).** It removes the second implementation of Big Loser and "can still win".
- **Window-thread budget.** A test that fails when any page's refresh calls `subprocess` (monkeypatch `subprocess.run` to raise inside `Page.refresh_now`) would stop S-6 coming back.

No rewrite is recommended. The architecture (one SQLite store, one generated static site, page-by-page refresh) is sound.

## 7. Tests or investigations needed for uncertain hypotheses

- **C-7 (Sunday brief Last Result 1):** read today's log after the brief's run.
- **O-6:** check how often ESPN's in-week reply omits a live game. `rawarchive` keeps every reply, so count games that disappear and come back within a week across the 201 saved scoreboards.
- **O-10:** only weeks 5+ are saved before the deadline, so any freshness-vs-accuracy chart will have n < 100 games this season. Label it "too few to judge" until week 12 or so.

## 8. Ideas rejected or deferred, with reasons

| Idea | Why |
|---|---|
| Confidence-tier charts | ACQL has no confidence points (it is pick'em against pool lines); that belongs to `nfl_pickem`. |
| Lazy-import matplotlib | Measured on 10-24: the landing page draws charts at once, so it saves nothing. |
| Speeding up `pricing.price` | Protected Deadeye code; the gain is a second on first open. Pre-warming (O-3) gets it without touching the maths. |
| Website battery timer gating | Not a real cost (§2). |
| Any website edit tonight | Auto-publishing on game day; another session is mid-round on the site. |
| New charting library | The desktop has a consistent in-house chart family (below); no demonstrated gain. |
| pip-audit | Needs a download: Sam's call. |

## 8b. Done in round three (10-25 morning)

O-1 (all readers), O-2, O-4, O-5 and the window-thread subprocess guard test are done; see the handoff §15. A new bug was found and fixed on the way: a chart deleted while its draw was queued raised in `Chart._draw_idle`.

**Still open, in order:** O-6 (keep a live score through one odd reply; needs a rule for games that really moved weeks, so your call), R-6 (site numbers from Python; website, mock-up first), O-9 (weeks you'd have won with Deadeye's card), O-7 (shared freshness limits, website), O-8 (feed interface), and C-2 (`nfl lines.csv`, your call).

## 9. The next ten highest-value tasks

1. ~~O-3 pre-warm Deadeye Picks and Model Lab~~ done; next: O-2 Readiness off-thread (S–M, low)
2. O-1 extend the reader fuzz test to timeline and PFM (S, none)
3. R-6 site numbers from Python (M, medium; website needs Sam's yes)
4. O-6 keep the last live score through one odd reply (S, medium; decide the rule first)
5. O-4 fragility on the Report card lead and the Model Lab record (S, none)
6. O-2 Readiness on a worker thread (S–M, low)
7. Window-thread subprocess guard test (S, none)
8. O-9 weeks won with Deadeye's card (S, none)
9. O-5 skipped-item counts on Readiness (S, low)
10. C-2 move `nfl lines.csv` (Sam, XS)

## 10. The single most valuable next project

*(Done the same morning; see the handoff §14. The next pick is R-6: site numbers from Python, once Sam has seen a mock-up.)*


**O-3: pre-warm the Deadeye pages after each load.** Deadeye Picks is the page Sam opens before every deadline, and its first open is 5.5 s cold (measured at 01:56). The warm-up pattern already exists (`workers.warm_this_week`, used for This Week), the numbers are cached by the pricing code, and nothing about the picks changes. That makes it a measurable, reversible speed-up on the most-used screen, with an output fingerprint to prove it (the 10-24 Deadeye Picks fix used the same proof).

---

## 11. UI and chart inventory

### Desktop (PySide6, 26 page classes)

Overview, Player (the landing page, opens on Phelpy), Standings, Projections, Charts, Briefing / Next week, Everyone's picks, Weekly (Results), Game Day (plus Cinema), Pools (Side Pools), Winnings, Teams, Leverage, Insights, Model (Deadeye Picks), Report card, Model charts, Model Lab, Recipe, Computers, Radar, Hits & misses, Forecast log, Data & Update, Readiness.

**Chart family** (`acql/ui/charts.py`, `modelcharts.py`, `funcharts.py`, `seasoncharts.py`): BarChart (ranked magnitude), DivergingBarChart (signed, such as money), LineChart (time), RankChart (rank 1 on top), HistogramChart (distribution), HeatmapChart (sequential or diverging), ScatterChart (quadrants), TrajectoryChart (games above a coin flip), **CalibrationChart** (said vs happened, by band), ScopeChart (expected vs actual margin), RollingChart (recent form against a luck band), ThinBars (with a benchmark tick), MatrixChart (rates by kind of game), FlightChart (line movement small multiples), FormChart (recent vs season), RaceChart (places by week), LandedChart (one week's scores as dots), FunnelChart (suicide pool), CrowdChart (how much of the pool had the credited side).

**Assessment:** the families match the questions they answer. Calibration, uncertainty bands and luck bands already exist; the charts draw only when visible and share a tooltip and theme. **Retain all.** No chart was found that duplicates another's question. The gaps are uncertainty *words* next to record comparisons (O-4) and pre-warming (O-3), not new chart types.

### Website (one generated page, 56 pieces in `acql/ui/pool_page/`)

Sections: Home; This week (Live, Picks, Past weeks); Standings (Table, Charts, Head-to-head, History); Pools & money (Side pools, Money); Me. Charts are in `460-charts.js` (`lineChart`, `drawCharts`) and `480-the-charts-page.js`. Live state: on-air bar, scoreboard ribbon, game-day strip, cinema mode, a deadline countdown (`170`, from real `DATA` times), and a boot sequence that shows feed status ("connected", "saved scores", "offline").

**Assessment (read only tonight):** yesterday's audit shot every page at 390 px and 1366 px, light and dark, and its 10 fixes are applied. Round 2 is in progress in another session. Proposals only: O-7 (shared freshness limits), R-6 (precomputed numbers).

### Recommended layouts

- **Desktop:** keep the five-group navigation proposed on 10-24 (Sunday / Pool / Deadeye / History / System), with Readiness and Data & Update under System. Nothing new tonight.
- **Website:** keep the four sections plus Me (Sam-approved 10-12). Any change goes through a mock-up first.

### Next 15 UI, charting and analytics improvements (value · data · effort · risk · priority)

1. O-3 pre-warm Deadeye pages · speed on the key screen · existing · M · low · **P1**
2. O-4 fragility sentence on the Report card lead · honest comparisons · existing · S · none · **P1**
3. O-5 skipped-item counts on Readiness · visible feed trouble · existing · S · low · P1
4. O-2 Readiness built off-thread · no freeze on first open · existing · S–M · low · P2
5. O-9 "weeks you'd have won with Deadeye's card" panel · the pool cost of overrides · `ghost.py` · S · none · P2
6. O-7 one freshness scale for the site and desktop · consistency · `tokens.FRESHNESS` · S · low (site) · P2
7. Fragility in the Model Lab's saved-before-deadline record (Deadeye vs line, n=29) · stops over-reading 16 vs 17 · `training/record.py` · S · none · P2
8. A "too few to judge" badge style shared by every chart with n < 30 · consistent uncertainty language · existing · S · none · P2
9. Journal: reasons ranked by sign-test p with n shown · which reasons hold up · existing · S · none · P3
10. Calibration by data freshness (O-10) · the brief's stale-feed question · `known.py` + source health · M · none · P3, label small n
11. Desktop SlateCard / week strip (10-24 plan) · scannable slate · existing · M–L · low · P3
12. R-6 site Big Loser and "can still win" from Python · one rule source · existing · M · medium · P3 (needs Sam's yes)
13. Export of the journal and fragility as CSV · Sam's own analysis · existing · S · none · P4
14. Readiness "last 7 days" source strip as a sparkline per source · see flaky sources at a glance · `sourcehealth` · S · none · P4
15. Window-thread subprocess guard test · keeps S-6 fixed · n/a · S · none · P4
