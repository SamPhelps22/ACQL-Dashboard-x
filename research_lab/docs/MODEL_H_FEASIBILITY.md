# Model H — film-derived and tactical data: feasibility and decision

## What exists and can be used

| Source | Seasons | Fields | Coverage (measured) | Terms |
|---|---|---|---|---|
| nflverse `pbp_participation` | 2016–2025 | offensive / defensive personnel, formation, defenders in box, pass rushers, `was_pressure`, time to throw, route, **man/zone** and **coverage shell** | personnel ~75% of plays 2016–22, 100% 2023+; man/zone & shell **0% before 2018**, ~38–50% 2018+; pressure ~39% 2016–22, 100% 2023+ | Redistributed by nflverse; derived from NFL Next Gen Stats. Research use; raw files are not re-published here. |
| FTN charting via nflverse | 2022–2026 | play action, motion, RPO, screen, blitzers, pass rushers, QB out of pocket, box count, drops, catchable ball | ~285 games a season, every play | CC-BY-SA 4.0 (FTN Data, via nflverse) |
| 2026 participation | — | — | **not published** (HTTP 404 on 2026-10-21) | — |

## What does not exist here

* PFF grades, coverage charting before 2018, alignment / route-tree film charting at scale — licensed products, not accessible.
* NGS player tracking — not public beyond the aggregates above.
* Anything before 2016.

## Decision

A **functional baseline** was built, because coverage, pressure and personnel exist for enough seasons to score it
honestly — but only from 2021 (two prior seasons of coverage labels are needed to teach it):

* `research_lab/data/scheme.py` — per team-game: dropbacks and EPA against man and against zone, pressured dropbacks,
  11-personnel and shotgun snaps (participation joined to play-by-play EPA).
* `research_lab/models/scheme.py` — `H_base` (team strength only, same 2019+ training window) and `H_scheme`
  (+ coverage-weighted expected pass EPA, pressure allowed × generated, personnel and formation tendencies).
* Evaluated on 2021–2023 (development) and 2024–2025 (holdout) by `python -m research_lab extensions`;
  results in `reports/RESULTS_HOLDOUT.md` (Model H section) and `outputs/model_h.json`.

FTN charting (play action, motion, blitz) is **not** used in the baseline: four completed seasons, one of which is the
first training season, leaves too few scored games to tell a real effect from noise. It is the natural next input.

No shadow forecasts are made for H in 2026 because the participation file for 2026 is not published.

## Extension interface

A new tactical data source plugs in the same way as `scheme.py`:

1. a per-(game, offence) table with numerator / denominator columns, joined to `games` by `game_id`
   (the Store attaches `completed_at`, so `Store.snapshot` hides unfinished games automatically);
2. a stats dict `{name: (numerator, denominator)}` passed to `features.ratings.unit_ratings`, which returns
   opponent-adjusted, recency-weighted, shrunk offence and defence ratings;
3. a `columns()` function turning those into matchup features, on a `RidgeMarginModel` subclass with
   `train_from` set to the first season with a full prior season of the data.

Required of any new source before it is used: per-play or per-game timestamps or game ids that tie each row to a
completed game, documented coverage by season, and terms that allow research use.
