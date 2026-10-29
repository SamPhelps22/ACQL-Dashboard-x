# Four features — 2026-10-28

Built in worktree `C:\Users\sam52\acql-four-features` (branch `four-features`, from main 49d69fc). Nothing is committed, pushed or published. The main folder publishes itself, so none of this is live until it is merged there.

## 1. Rulebook Explorer — Standings › Rules (`#rules`, `#rules?r=<id>`)
- `acql/pool/rulebook.py`: 22 rules in 9 categories. Each one has the rule, when it applies, how it's calculated, a hypothetical example, exceptions, links, and the code or export that enforces it.
- Numbers come from the scoring constants: `results.BLOWOUT` (15), `config.BIG_LOSER_PICKS` (3), the season buy-in, and the default deadline setting.
- Status labels: Verified 15, On record 3, **Not verified 4**:
  - whether a suicide team can be used twice
  - the suicide prize
  - the Big Loser prize
  - earlier seasons' rules (none are on file)
- The top-10 pool's rules and the late-card rule are also marked as not written down.
- Season selector: only 2026 is documented. "Earlier seasons" says so and doesn't apply the current rules to them.
- Search, category filters, a direct link per rule, and "copy link".
- Linked from Standings ("How ties in the table are broken") and from Side pools' suicide card.

## 2. Power Rankings — Explore › Power (`#power`)
- `acql/pool/powerrank.py`. Each week's score minus that week's pool average, then:
  - rating = 0.55 × recent (last 3 weeks) + 0.30 × earlier (the weeks before those, so no week counts twice) + 0.15 × steadiness (pool median spread minus the coach's own; needs 3 weeks)
  - The rating is in wins a week against the average coach. A missing part's weight is shared out over the rest.
- Missed weeks are left out. Ties share a place. Coaches with fewer than 3 weeks are marked. Each week's ranking uses only weeks up to that week.
- Snapshots: every week is reconstructed and labelled that way. When the site is built, the latest week's ranking is saved once in the store (`power_rankings`). A week whose saved ranking still matches is labelled "Recorded"; otherwise it stays "Reconstructed".
- The page shows: rank, movement, rating, official place (for past weeks, the official table as of that week with shared ties), gap, recent form, last weeks and swing. It lists the biggest differences between the two lists and explains the formula.
- It only reads the weekly scores. A test checks that it leaves the official places unchanged.

## 3. Coach Connection Map — Explore › Connections (`#connections`)
- `528-connection-map.js`. Each pair's numbers come from the Head-to-head page's own `compare(a, b, from, to)`.
- Four relationship types:
  - **Head-to-head closeness**: average weekly gap. Everyone meets everyone every week, so the map measures closeness, not how often they met.
  - **Shared picks** and **Different picks**: share of games compared. Splits are listed game by game with who was right.
  - **Similar seasons**: average gap between their scores relative to the pool.
- Week range filter. Season shows 2026 only, since no other season is archived.
- Links per coach (1/2/3/5), coach search, focus on one coach, map or list view, zoom (buttons and wheel) and pan.
- A detail panel for the selected coach or link, with links to the coach's page and the full head-to-head.
- Coaches are drawn in official order around a ring. Pairs are worked out once per week range; selecting, zooming or panning only redraws.
- Minimum sample before a link is drawn: 2 weeks, 16 games, 16 games, 3 weeks.
- Discoveries list the closest rivals, the most alike, the most opposed and the most similar. "Most frequent" and "changed across seasons" say why they don't apply yet.
- Players now carry `id` (the stable key) in the site data. The node key is still the display name, because every other page uses it and the loader already merges spelling variants through aliases.json.

## 4. Commissioner Import Workbench — local only
- `python -m acql.pool.importbench check FILE | approve ID --by NAME [--accept-serious] | apply ID | undo ID | history`
- **Detect**: uses the pipeline's `classify`. **Validate and preview**: parses the file with the pipeline's own `parse_stats` / `parse_workbook` and compares it with `load_season` (offline).
  - It flags new results, changed official scores, removals, missing, new or duplicated coaches, values out of range, a file older than the record, and money changes.
  - Each item is graded serious, check or harmless.
- **Approve**: the whole file at once, because the pipeline takes files whole. Approval needs a name. Serious items also need `--accept-serious`, and the accepted item numbers are recorded.
- **Apply**:
  - backs up every stats/workbook file to `backups/imports/<id>/`
  - copies the file into `data/` and never overwrites a file already there
  - reloads with `load_season` and checks the result against the file
- **Undo** restores the backed-up set.
- Duplicates (same SHA-256 already applied, or already in `data/`) are refused. A file edited after it was checked is refused.
- History is kept in `data/import-history.json`.
- Tried on real files in a scratch copy:
  - `stats week 7.xls` over a week-5 record: 0 serious, 72 to check (money moving with new weeks). Applied, verify PASSED, re-import refused as a duplicate, undo restored the folder.
  - An older export: 218 serious items, and approval was refused without `--accept-serious`.
- **Not built, and why:** a web version. The site is static GitHub Pages, so an online workbench would need a server with sign-in, write access to the data folder, and shared storage for the history. Nothing admin is in the public page; a test checks that.

## Tests
- `tests/test_four_features.py`, 29 tests, added to CI:
  - rules match the constants and the line / tie-breaker code
  - Power Rankings: arithmetic, missed weeks, ties, cutoff (later weeks changed → earlier ranking identical), the recorded/reconstructed label, official places untouched
  - the map's pair numbers equal `compare()`, and missing picks are left out
  - workbench: severities, gates, backup and undo, duplicates, changed file, not in the page
- Checked visually against the real season (35 coaches, weeks 1–7) at 1366 and 390 wide.

## Files
- New:
  - `acql/pool/rulebook.py`, `powerrank.py`, `importbench.py`
  - `acql/ui/pool_page/526-rulebook.js`, `527-power-rankings.js`, `528-connection-map.js`, `the `000-page-top.html` style block
  - `tests/test_four_features.py`, this report
- Changed:
  - `acql/ui/poolpage.py` (player `id`, `power`, `rulebook`, features CSS)
  - pool_page `100` (views and nav), `180` (routes), `530` (`#rules?r=`), `340` and `350` (rule links)
  - `.github/workflows/tests.yml`
