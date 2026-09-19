# ACQL Dashboard

A desktop dashboard for the ACQL NFL pick'em pool. It reads the pool's existing
spreadsheets — the weekly `stats.xls` standings export and the
`ACQL Dashboard.xlsx` workbook — and turns them into a browsable interface with
standings, weekly results, per-player histories, the money, and both side pools.

It runs from source with one command, and ships as a standalone executable for
people who do not have Python.

---

## Running it

```bash
python run.py
```

That is the whole setup. On first launch the script creates a local `.venv`,
installs anything missing from `requirements.txt` into it, and starts the app.
Nothing is installed system-wide. Later launches skip straight to the app
(~0.05s), because the launcher records which dependency set the environment was
built against.

| Flag | Effect |
|---|---|
| `--system` | Install into the current interpreter instead of a `.venv` |
| `--reinstall` | Force every dependency to be reinstalled |
| `--no-install` | Never install; fail if something is missing |
| `--check` | Report dependency status and exit without opening the window |

Requires Python 3.9 or newer. On Linux, Qt also needs a few system libraries:

```bash
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libdbus-1-3 libxcb-cursor0
```

## Feeding it data

Drop each week's files into the `data/` folder and press **Refresh** (or `F5`):

```
data/
├── stats.xls              # this week's standings export
├── stats (3).xls          # older exports are fine to leave in place
└── ACQL Dashboard.xlsx    # the workbook
```

Filenames do not matter. Every file is identified by reading what is inside it
— `stats.xls` states its own week in a header cell — so `stats (1).xls` and
`stats.xls` are told apart correctly, and two files with identical content are
collapsed into one. The project root is watched as well as `data/`, and you can
add more folders from the **Data & Update** page.

Because each weekly export is identified by its own week number, **leaving old
exports in the folder rebuilds the season's history**: drop week 4's file in
next to weeks 1–3 and the whole season assembles itself.

### How the two files are combined

`stats.xls` is authoritative. It is the official export, and it is the only
source for the Big Loser and Suicide pools, so its positions, W/L, PCT, games
behind and net points are the ones shown.

The workbook supplies what the export does not carry: the game slates,
individual picks, and the Winnings sheet.

Where the two disagree about the same number, the export wins and the
disagreement is **listed on the Data & Update page** rather than quietly
dropped. (Your current files disagree about two players' week-1 totals, which
is exactly the kind of data-entry slip this is meant to surface.)

A week that the workbook has started but the export does not yet cover is shown
as *in progress* and held out of season averages, so a half-entered week cannot
drag everyone's numbers down.

### Player names

Names are matched case-, space- and punctuation-insensitively, so `SaleeNmd `
and `SaleeNmd` are one player. For genuine nickname differences, add a mapping
to `aliases.json` in the project root:

```json
{
  "aliases": {
    "Zach N": "Zachary Nelson",
    "tb": "TB"
  }
}
```

If a player appears in only one of the two files, the app says so on launch
rather than letting them silently vanish from the standings.

## The pages

| Page | What it shows |
|---|---|
| **Overview** | Leader, current week, pot, pool average, the top 12, how bunched the field is, and the season superlatives |
| **Standings** | Every player with W/L, PCT, GB, net money, recent form and rank movement, plus a wins-by-week grid |
| **Weekly** | One week's slate, who won it, the full scoreboard, and which games were traps |
| **Player** | One coach: form against the pool average, rank trajectory, and a week-by-week record |
| **Winnings** | Buy-ins, payouts, and every player's net position |
| **Side Pools** | Big Loser standings and who is still alive in the suicide pool |
| **Data & Update** | Which files loaded, what disagrees, and the weekly result entry form |

`Ctrl+1`–`Ctrl+7` switch pages, `F5` refreshes, `Ctrl+T` toggles light/dark.

## Entering results (write-back)

The **Data & Update** page writes back into `ACQL Dashboard.xlsx`. It covers
every cell the workbook actually treats as an input, across two tabs:

| Tab | What you can edit |
|---|---|
| **Slate & results** | Each game's home and away team, and its winner. The winner list follows whatever the two team cells say, so fixing a team name updates it. Plus the week's game count on the Season sheet. |
| **Picks** | One player at a time: their pick for each game, their three big-loser slots, and their suicide pick. |

Edits from both tabs are collected and applied as one change set, so a week's
entry is a single backup and a single save. Edits accumulate **across
players** — change one coach's picks, move to the next, and the first one's
edits are still pending (the counter says how many players they span, and
returning to a player shows their pending values rather than the file's). A
running count sits next to the buttons, **Preview changes** lists the exact
cells and values before anything is written, and **Discard changes** reloads
everything from the file.

That is the whole input surface, because the workbook is almost entirely
derived. **Every win total, rank, payout, the Season grid, the Winnings grid
and the whole Dashboard sheet are Excel formulas fed by those cells.** So the
app writes the inputs and lets Excel recompute the rest, which is both safer
and more correct than writing computed values.

Two details the editor preserves rather than flattens:

- A big-loser slot holds either the team picked **or** a `1` once that pick
  came in. All three slots are shown and written back by position, and a `1` is
  stored as a number, because Excel's tallies do not count a text `"1"`.
- The sheet is inconsistent about capitalisation — some home picks are stored
  shouted (`CINCINNATI`), others are not. Existing spellings are kept exactly
  as they are; only a pick you actually change is rewritten, using the spelling
  shown on that game's row.

Three guarantees on every save:

1. **Formula cells are never overwritten.** Each target is checked first, and a
   change set that touches a formula is refused whole rather than applied in
   part.
2. **A timestamped backup** is written to `backups/` before anything changes
   (the last 25 are kept).
3. **The save is verified** by reopening the file and reading the values back.

This has been verified end to end against the real workbook — including
through the UI, not just the API: 5,381 formulas, 1,348 array formulas, 7
tables, 66 conditional-formatting rules, 33 validation rules and 27 merged
ranges all survive a write unchanged. Excel recalculates cached values when it
next opens the file.

Close the workbook in Excel before saving, then reopen it so Excel recalculates,
save it there, and press **Refresh**.

## Building the standalone executable

```bash
python packaging/build.py
```

The result lands in `dist/`:

| Platform | Output |
|---|---|
| Windows | `ACQL Dashboard.exe` |
| macOS | `ACQL Dashboard.app` |
| Linux | `ACQL Dashboard` |

It bundles Python and every dependency; the recipient needs nothing installed.
They put their spreadsheets in a `data/` folder next to the executable and
double-click.

PyInstaller cannot cross-compile, so a build only produces a binary for the
machine it runs on. To get all three, push a `v*` tag (or run the workflow
manually) and **`.github/workflows/build.yml`** builds each on its own runner,
smoke-tests that the frozen app actually starts, and attaches the zips to the
release.

macOS will warn that the app is from an unidentified developer, since signing
needs an Apple Developer certificate. Right-click → Open once to get past it.

## Project layout

```
run.py                  launcher: bootstraps dependencies, then starts the app
requirements.txt        runtime dependencies
aliases.json            optional player-name mappings
data/                   drop the weekly spreadsheets here
backups/                automatic backups taken before each write
acql/
├── config.py           paths and persisted settings
├── names.py            name normalisation and aliases
├── models.py           the domain model
├── repository.py       merges the sources into one Season
├── awards.py           season superlatives
├── writeback.py        guarded Excel writing
├── sources/
│   ├── discovery.py    identifies files by content, not filename
│   ├── stats_xls.py    the standings export parser
│   └── workbook.py     the dashboard workbook parser
└── ui/
    ├── app.py          window, navigation, background loading
    ├── theme.py        light and dark palettes
    ├── charts.py       matplotlib charts embedded in Qt
    ├── widgets.py      cards, stat tiles, sortable tables
    ├── editor.py       the weekly input editor
    └── pages/          one module per page
packaging/
├── acql.spec           PyInstaller build definition
├── entrypoint.py       frozen-build entry point
├── build.py            one-command build
├── acql.ico / .icns    Windows and macOS app icons
└── icon.png            window icon, bundled with the build
tests/                  parser, merge, editor and write-back tests
```

## Tests

```bash
python tests/run_tests.py
```

39 tests covering name matching, file identification, both parsers, the merge
rules, the awards, and the write-back guards — including that a formula cell is
refused, that a change set containing an unsafe edit is abandoned whole, that
big-loser win markers survive editing a neighbouring slot, and that the
workbook's structure is unchanged by a save.
