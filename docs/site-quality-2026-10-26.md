# Website consistency, freshness, dates, speed and layout — 26 Oct 2026

Branch `site-quality` (worktree `C:\Users\sam52\acql-site-quality`, made from main `c6a29a4`). Nothing is committed, pushed or published. This folder is separate from the one that publishes the site by itself.

## 1. What was wrong

- **Rankings.** The same rule (1 + the number of coaches scoring more) was written out separately in 13 places across Home, Live, Cinema, one-week pages, the coach page, the share picture and the standings feed. Season places after a given week were worked out twice (`placesAfter` on the coach page, `lmRank` in the modes). They all gave the same answers, but each copy could drift on its own.
- **Feed status words.** The website used two vocabularies:
  - The game-day strip said "Scores unreachable · retrying".
  - Cinema and Broadcast said "Cached" and "Delayed".
  - "Delayed" came from its own fixed 90-second rule. With no game on, Cinema called 2-minute-old scores "Delayed" while the rest of the site said "Updated 2 minutes ago".
  - The coach page and Live called the score feed "Market feed".
  - Desktop RedZone and Cinema had the same "CACHED"/"DELAYED" split.
- **Addresses.** A week chosen on Past weeks or Factions was lost on refresh or when shared. A Time Machine or Numbers Room link to a season the archive doesn't have silently showed a different season.
- **Speed.** Profiling the slowest redraws found:
  - The time-zone formatter was rebuilt for every kickoff time shown.
  - The stylesheet was asked for the same freshness thresholds on every check.
  - Each team badge's colour contrast was recomputed every time.
  - Factions recomputed every pair of coaches' distance thousands of times.
  - With Cinema open, every score update also redrew the whole page hidden underneath it.
- **Layout.**
  - Above about 1,400 px the site was a 1,180 px column with no larger text (on a 4K TV, about a third of the screen).
  - Cinema on a tablet was a single column of very wide cards.
  - Desktop RedZone:
    - The scores ribbon cut off each chip's second team line, at every size.
    - On a 1366×768 laptop at 125% (1,093 points wide), the window was wider than the screen: 1,165 points even before this work, because the "MY PICKS · …" heading couldn't shorten.
- **Charts.** In the Numbers Room, the histogram and bar charts showed their values only on mouse hover, with no keyboard or touch access, and used their own wording for empty states.

## 2. One calculation for each figure

| Figure | The one place it is worked out | Now used by |
|---|---|---|
| Place among coaches (ties share, next skipped: 1, 2, 2, 4) | `rankAll` in `pool_page/020-small-helpers.js` | everything below, and the modes' `lmRank` |
| A coach's place in a finished week | `weekPlace(w, name)`, remembered per week (never written into the data) | recap "Your week", one-week page, coach page, share picture |
| Place in the week being played | `livePlace(t, name)`, remembered per score update | Home on game day and after games, Live table, Cinema board and "You:" line, standings change feed, side-pool board, share picture |
| Season place after week n | `placesAfter` (coach page), now on `rankAll` and remembered per week | the coach page's Season column; agrees with the Time Machine for every week |
| Head-to-head | `compare()`, from the last cleanup | unchanged |

Checked in the page itself:
- 454 places agree with the old code: every coach in every week, every live row, and every earlier week against the Time Machine. The latest week matches the official table.
- These all agree across the site and the modes, with no differences:
  - weekly scores (35 coaches × 6 weeks);
  - season totals;
  - Big Loser totals;
  - weeks won;
  - each week's pool average.
- `pool_average` in the data is the season-to-date average total (49.31 = the mean of everyone's wins), not a weekly figure. It is used only for that purpose.

No official result, standing, pick or money figure was changed.

## 3. Charts

All the site's line charts (about 15) already share `lineChart`. That gives:
- an accessible label;
- a hover line that also moves with the arrow keys;
- the viewer in gold, the leaders highlighted and everyone else grey;
- a "Show the numbers" table under each chart on the Charts page.

The two Numbers Room charts that didn't fit that pattern now do:
- **Bars:** histogram and bar-chart bars can be reached with the keyboard and by touch, read their value aloud, and show a gold outline when focused.
- **Empty states:** those charts use the site's standard empty-state message, which says why there's nothing to show.

## 4. Data status and freshness

- **One rule:** `freshness()`. A game on wants scores within 90 seconds; with none on, 15 minutes will do. These thresholds come from the dashboard's `tokens.FRESHNESS`.
- **One word for each state:** `feedLabel()` on the website and `liveplus.data_label()` on the desktop.
  - **Loading:** nothing yet.
  - **Unavailable:** never reached.
  - **Refresh failed:** the last good scores are kept and their time is shown.
  - **Stale:** older than the limit.
  - **Live:** fresh, with a game being played.
  - **Up to date:** fresh, with no game being played.
- **Game status stays separate.** A game's own status (upcoming, live, final, postponed) is kept apart from the feed's health, and a final result never shows a data warning.
- **Unchanged and checked:**
  - A failed refresh keeps the last scores and shows when they're from.
  - A score only counts as "new" when it changed between two good checks.

The tests cover each state, stale with and without a game on, a failed refresh, and recovering from it.

## 5. Seasons, weeks and dates

- **Weeks in the address.**
  - Past weeks keeps the chosen week in the address (`#weeks?w=4`).
  - Factions keeps its week or the whole season (`#factions?w=season`).
  - A week the season doesn't have is ignored rather than guessed.
- **The week travels with you.** A week chosen on the site comes along when you open the Time Machine or Numbers Room, and comes back when you close it (this season only).
- **Missing seasons are named.** A link to a season the archive doesn't have shows "The 2019 season isn't in the archive — showing 2026 instead". Nothing is filled in for a missing season.
- **Mode addresses are left alone.** The site never rewrites a mode's address. This was a bug introduced during this work and caught before it shipped.
- **Kickoff times** show in the viewer's own time zone, with the zone named. One shared formatter still names each date's own zone, so CST and CDT are each correct around the clock change.
- **Not changed:** postseason weeks, and season rules for past years. There is still only one season (2026) archived.

## 6. Speed: measured before and after

Method: the same made-up live scoreboard, headless Chrome, 1366×768, three runs of each build alternating, median shown. Timings on this PC swung by up to 3× between runs, so only differences that held in every run are reported.

| | Before (main) | After |
|---|---|---|
| Page size | 864 KB (717 KB script, 146 KB CSS) | 870 KB (+5.6 KB) |
| Load | about 0.3 s | about 0.3 s |
| Redraw, all 12 pages together | 650 ms | 344 ms (47% less) |
| Home / Live / Picks | 30 / 77 / 63 ms | 15 / 38 / 31 ms |
| Factions / Standings / coach page | 98 / 46 / 59 ms | 35 / 18 / 31 ms |
| Side pools | 97 ms | 83 ms |
| Score update with Cinema open | 71–198 ms | 13–47 ms |
| Live minute: scoreboard requests / redraws | 2 / 2 | 2 / 2 |
| Memory after a live minute | 3.3 MB | 3.3 MB |

**Not changed, on purpose.** Each 30-second score check still redraws the open page, at about 40–90 ms per check, which is under 0.5% of the time. Skipping those redraws would mean rewriting how the page updates, and the measurements don't justify that.

## 7. Layouts checked

Every page and mode was opened in headless Chrome at seven sizes, from 360×740 phone to 3840×2160 TV, in the before-kickoff and live previews. The results:
- **Errors and clipping:** no script errors, sideways overflow, clipped elements or squeezed sections at any size.
- **Big screens:** pages now scale up 1.25× from 1,900 px, 1.6× from 2,500 px and 2× from 3,400 px, unless you've chosen a text size of your own. The top bar and ticker stay lined up at every size.
- **Cinema:** checked at seven widths. Tablets now get two columns of game cards, phones one, and nothing clips.
- **RedZone (desktop):** rendered at 1,093×614, 1,366×768, 1,920×1,080 and 2,560×1,440.
  - It now fits 1,093 points wide.
  - The ribbon shows both teams on each chip.
  - The queue buttons are never cut.
  - At 4K with Windows scaling at 100%, its text is small. Windows normally scales 4K screens to 150–200%, where it looks like the 1,920–2,560 renders.

## 8. Tests

| Check | Result |
|---|---|
| `tests/run_tests.py` on the worktree | 354 OK (1 skipped: the worktree has no `data/nflverse`, as before) |
| `tests/test_site_quality.py` (new, in CI) | 13 OK: ranking ties, week and live places, freshness states and recovery, the shared words (website and desktop), kickoff zones, addresses, RedZone fit |
| `test_site_layout.py`, `test_league_modes.py`, `test_guard.py`, `test_live_modes.py` (updated for the new words), `test_gameday_live.py` | all OK |
| `packaging/guard.py` | nothing wrong found |
| Mode walk (74 steps, desktop and phone) | 0 errors, 0 overflow |
| Page sweep: 19 pages, phone and desktop, before kickoff and live | 0 errors, 0 overflow |

## 9. Still open

- **Previews only.** The previews open from a file, so ESPN and the history file can't be reached. Live behaviour was tested with a made-up scoreboard, and the published site wasn't measured.
- **Short sessions only.** Live sessions ran for 60–120 seconds. An hours-long session wasn't measured.
- **Side pools** is still the slowest page to redraw (about 80 ms).
- **RedZone's drive line** ("1st & Goal · 4 to go") can still be cut short on the smallest laptops.
- **The modes' standings** for earlier weeks (`lmCheckpoints`) still compute their own totals. They agree with the site everywhere, but sharing one season-totals function would remove that last copy.
