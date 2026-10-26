# Website cleanup — 26 Oct 2026

Branch `site-cleanup` (worktree `C:\Users\sam52\acql-site-cleanup`). Nothing is committed, pushed or published. This folder is separate from the one that publishes the site by itself, so none of this goes live until it is merged into `main`.

## What changed, in one line each

- **Navigation.** A fifth section, **Explore**, now holds Charts, Head-to-head, Factions, Teams and the three league modes. Standings drops from 7 tabs to 3: Table, Awards, History.
- **Home.** Before kickoff, Home now shows who's leading (top six plus you). In all three week phases (picks in, games on, all over), the full suicide-pool and Big Loser cards are replaced by one short side-pools card. The big "League modes" block becomes a slim "Go deeper" row at the foot of the page.
- **Live.** The two full side-pool cards are replaced by the same short card. The full cards stay at the top of Side pools.
- **Coach page.** "Points against the max" becomes an "Of max" column in the "Every week" table, which now links on to the Time Machine and the Numbers Room.
- **Standings.** The title race no longer repeats the Wins and Back columns from the table above it.
- **Charts.** "Every week's scores" was the same chart as each coach page's "Week by week", so it's removed. The Money chart now appears only on the Money page, which picked up its note and data table.
- **Numbers Room.** The rail is grouped into Overview, Coaches, Picks, League and Tools.
  - Head-to-head keeps the side-by-side stats and the season-gap chart, and drops its copies of the places chart and the week-by-week table.
  - Rank movement drops its places chart and links to the Time Machine's title race instead.
- **Time Machine.** Compare drops "Two coaches", which repeated Numbers Room's head-to-head, and links there instead.
- **One calculation per number.**
  - The modes' head-to-head (`lmVs`) now uses the site's own `compare()`, which can take a range of weeks. Before the switch, all 595 coach pairs agreed exactly.
  - The suicide-pool and Big Loser figures are worked out once (`weekSuicideTally`, `weekLosersTally`), and both the full cards and the short card read them.
- **Fixed.** The week's suicide card said "19 still in" while the rest of the site said 20: it skipped a coach with no card this week. It now counts everyone still in and names anyone without a card.

## Duplicates removed or consolidated

| What was repeated | Where | Kept as the main version | The other places now |
|---|---|---|---|
| Week suicide-pool card | Home, Live, Side pools | Side pools | Short card on Home and Live, same numbers, linked |
| Week Big Loser card | Home, Live, Side pools | Side pools | Same as above |
| Season standings | Home (after results only), Standings, Time Machine, Numbers Room | Standings (official) | Home now always shows the top six; the modes are the historical and analysis views |
| Pool spread per week + one coach's score | Charts "Every week's scores", coach "Week by week" (same function) | Coach page | Removed from Charts; pool-wide spread lives in the Numbers Room's Score spread |
| Money over the season | Charts, Money page, coach page (small) | Money page | Removed from Charts (note and table moved to Money) |
| Weekly % of the max | Coach "Points against the max" module and the "Every week" table beside it | "Every week" table | Module removed, now a column |
| Wins and Back for the contenders | Standings table and the title race | Standings table | Title race shows only Per week and Title |
| Places by week (line chart) | Time Machine race and coach tabs, Numbers Room rank movement and head-to-head, Broadcast spotlight | Time Machine title race | Removed from Numbers Room (both tabs); the Time Machine coach tab and the Broadcast spotlight keep one focused line each |
| Coach-vs-coach | Head-to-head page, Numbers Room head-to-head, Time Machine compare | Head-to-head page for picks, Numbers Room for stats | Time Machine "Two coaches" removed; the Numbers Room week table removed |
| Head-to-head calculation | `compare()` and `lmVs` (separate code) | `compare()` | `lmVs` calls it |
| League modes launcher | Big Home block, separate menu group | Explore tabs and its menu group | Slim "Go deeper" row on Home |

## The structure now

- **Home** answers what's happening, who's leading, what changed and where to go next. It shows the week's main card for the phase, the top of the table, the side pools in short, last week's story and links onward.
- **This week:**
  - **Live** is the slate as it happens.
  - **Picks** is everyone's picks and how the pool picked.
  - **Past weeks** is recaps and replays.
- **Standings** is the official results:
  - **Table** has the podium, full table, every-week view and title race.
  - **Awards.**
  - **History** is champions and records.
- **Explore** is where to dig in:
  - **Charts:** the season race, title odds and the power map.
  - **Head-to-head:** pick by pick.
  - **Factions.**
  - **Teams.**
  - **Broadcast:** stories.
  - **Time Machine:** the authority for any past week.
  - **Numbers Room:** detailed analysis in five groups.
- **Pools & money:** Side pools (suicide and Big Loser) and Money.
- **Me / coach pages:**
  - The coach's own week, rooting guide, trend, picking profile, blind spots, trophies, twins, rivals, side pools, money and every week.
  - Links on to the Time Machine and the Numbers Room.
- **Cinema** was checked and left alone. Its game cards are already short (score, state, pool line, the pool's split) with no charts in them.
- **RedZone** is a desktop dashboard feature. The website only links to it (shown to Phelpy only), so it was not changed.

All old addresses still work: `#charts`, `#h2h`, `#vs=…`, `#coach=…`, `#timemachine…`, `#numbers…` and `#broadcast…`. An old link to Numbers Room's head-to-head or rank tab still opens it. An old link to the Time Machine's "Two coaches" compare now opens "Two weeks".

## Checks run

| Check | Result |
|---|---|
| `python tests/run_tests.py`, main folder before the changes | 354 OK |
| `python tests/run_tests.py`, cleanup worktree | 354 OK, 1 skipped (`data/nflverse` is not in the worktree; not a website test) |
| `python tests/test_league_modes.py` | 18 OK (the engine test now loads the shared `compare()`) |
| `python tests/test_site_layout.py` (new, added to CI) | 11 OK |
| `tests/test_guard.py`, `test_live_modes.py`, `test_gameday_live.py` | 8, 15, 33 OK |
| `python packaging/guard.py` (joined page parses in Chrome) | nothing wrong found |
| Headless Chrome, every page, desktop and phone, before kickoff and with made-up live scores | 0 script errors, 0 sideways overflow |
| League modes walk (`modes-check/drive.py`), 74 steps desktop and phone | 0 errors, 0 overflow |
| Phone bottom bar with 6 buttons at 320, 342, 360 and 390 px | fits, no clipped labels |
| Desktop nav at 1100 to 1280 px with live scores | nothing hidden or overflowing |
| Same numbers before and after | "Of max" equals the old module for all 6 weeks; the "Every week" table is unchanged; the title race's per-week pace and chances are unchanged; head-to-head is identical |

Page lengths at desktop width (px):
- Home before kickoff: 3,132 → 1,891.
- Home with games on: 3,205 → 2,117.
- Live: 5,875 → 4,854.
- Coach page: 4,610 → 4,283.
- Charts: 2,540 → 2,115.

Not checked: empty, loading and failed-refresh states beyond what the previews show. The previews are opened from a file, so ESPN and the history file can't be reached. Those pages showed their existing "unavailable" messages correctly, but the stale-data state wasn't produced on purpose.

## Left as it was, and why

- **Rooting guide** appears on Home (game day), Live and the coach page. Each is personal and fits its context.
- **"How the pool picked"** is on Home before kickoff and on Picks. Before kickoff it is the main story.
- **"Out on a limb"** is now on Live only.
- **Numbers Room's Side pools and Record book** overlap Side pools and History. They analyse a chosen run of weeks and the archive, and already link to the site's pages.
- **Standings "Every week" grid** overlaps the modes' data tables. It is the official grid.

## Worth doing later

- Time Machine and Numbers Room still work out standings for themselves (`lmCheckpoints`). For the latest week they defer to the official table, but a shared standings function for the site and the modes would remove the last copy of that calculation.
- The Live page is still long on game day (nine sections). Folding "What each coach needs" and the finished games would shorten it.
- History's records and the Numbers Room's record book could become one view when past seasons are added.
