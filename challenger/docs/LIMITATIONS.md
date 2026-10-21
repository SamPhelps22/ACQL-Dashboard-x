# Limitations, missing data and next steps

## The comparison with Deadeye

1. **No Deadeye forecast recorded at the time exists for any backtest season.** Deadeye's ledger is
   in the app's own database (`data/acql.db`), which is not in the repository. Everything labelled
   Deadeye here is a reconstruction through Deadeye's own code.
2. **Deadeye's live rule cannot be replayed before 2026.** It needs the Prediction Tracker's
   computer-model margins, and thepredictiontracker.com refuses scripted downloads from this
   environment (Cloudflare challenge). Only the four weekly files in the repository exist (2026
   weeks 3, 4, 5, 7). With those archives, `acql.training` could replay Deadeye's full rule for
   1999-2025 and this comparison should be rerun against it.
3. **The Deadeye proxy is in-sample for 2011-2019.** Its constants were fitted on those seasons, so
   the development tie flatters it. The holdout (2020+) is out of sample for both models.
4. **The Deadeye proxy stops at 2026 week 2**, because Deadeye's scores file does. 2026 weeks 3-6
   are therefore missing from the main holdout matched set.
5. **`deadeye_core_closing` uses closing lines**, which carry information from after the ACQL
   deadline, and leaves out Deadeye's moneyline anchoring on straight-up games and its in-season
   refit of the model share. It is a stand-in for Deadeye's starting point, not Deadeye.
6. **The 2026 weeks 3-5 Deadeye-live inputs** were first committed after each week's first kickoff
   (week 4's after its Sunday games). The files hold no scores, but their line column may be later
   than the deadline. Only week 7's file is provably pregame.

## Challenger's own inputs

7. **Retrospective play-by-play models.** EPA, success rate and CPOE come from nflfastR's current
   models, fitted on many seasons, including later ones. The `no_epa` ablation shows this is not
   what drives Challenger's results (no measurable difference on the holdout).
8. **Retrospective data corrections.** The schedule and play-by-play are today's versions; stat
   corrections made after a game are baked in. Kickoff times and scores are rarely corrected; QB
   identities and play details occasionally are.
9. **Quarterback availability** is the previous game's starter. Injuries announced during the week,
   returns from injury and planned rest are invisible to Challenger. This is the largest known gap:
   timestamped injury reports would fix it, and the historical ones in nflverse are not timestamped
   reliably enough to backtest.
10. **No weather forecasts**, no officiating, no coaching changes, no in-season trades.
11. **Pressure** is a sacks-plus-QB-hits proxy, missing before 2006.
12. **Models are refitted once per season.** Mid-season retraining would use more information
   (legitimately); it was not tried.

## The evaluation

13. **Retrospective backtest, not a prospective test.** The prospective record starts with 2026
   week 7 (journaled before kickoff, commit `20e4939`); it will take seasons, not weeks, to mean
   anything.
14. **Development-time look at holdout data.** While fixing the "form" feature, correlations were
   computed on 2006-2026 data - a sanity check of a feature, not a model score, but disclosed.
15. **Multiple comparisons.** About ten pairs are reported per split; a single 95% interval that
   just excludes zero is moderate evidence.
16. **ACQL pool lines** in the long replay are reconstructed from closing spreads with the
   commissioner's measured habit. The cards take the likelier side in every game; Deadeye's
   win-the-week planner and money logic are not evaluated. Opponents' picks are real only on the
   eight sheets on file; finishing position elsewhere cannot be reconstructed.
17. **Challenger's cover chances** on lined games come from a normal margin (SD 13.5) around the
    margin implied by its win chance - a simple conversion, not a separately validated margin model.
18. **Provenance flag.** The six stored backtest manifests say `git_commit: f19b7b5...+dirty`. The
    code was the clean commit `f19b7b5`; the flag came from the run's own output files being
    untracked at the time. The check now ignores output folders. The manifests were left as written.

## Next steps (none taken without review)

1. Obtain the Prediction Tracker season archives (download them in a browser into
   `data/tracker/archive/`) and rerun the head-to-head against Deadeye's full live rule for
   1999-2025 via `acql.training`.
2. Start archiving, every week, the Prediction Tracker file and Deadeye's ledger next to Challenger's
   journal, so the prospective comparison grows: after each week, `python -m challenger
   record-outcomes` then `python -m challenger shadow-report`; before each week,
   `python -m challenger shadow --week N` and `python -m challenger capture-deadeye --week N`.
3. Build a timestamped quarterback-availability input (e.g. archive each week's injury report and
   depth chart as it is published) - the most promising football improvement.
4. If anything from Challenger is ever used, the evidence points to a narrow role: a small,
   validated nudge on top of the market (as Deadeye already does with outside models), not a
   replacement for it. The `market_informed` variant did not beat the closing line, so even that is
   unproven.
