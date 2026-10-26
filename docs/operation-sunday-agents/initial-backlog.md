# Initial research backlog

Priorities are based on the audited data and existing experiment history, not on expected wins. Every item starts as a hypothesis; none is a production change.

| Priority | Research question | Why now | Experiment / stop condition |
|---|---|---|---|
| P0 | Can any frozen candidate beat both Deadeye and the market on actual Thursday-locked games? | The current prospective locked sample has no scored two-track weeks; midweek archive lines are only proxies. | Keep candidates, Deadeye, and market in the existing hash-chained lock; require identical games and the preregistered number of distinct weeks before judging. Until then report inconclusive. |
| P1 | Do quarterback availability or injury signals improve the deadline forecast beyond the line? | The repo has historical injury files and NFL features, but injury publication-time snapshots are not kept consistently per forecast. | First audit source publication timestamps and coverage. Only proceed on time-valid snapshots; otherwise stop as unavailable rather than backfill from final reports. Compare to same-game market and Deadeye baselines. |
| P1 | Are any market-relative signals stable by line movement timing? | Historical openings, midweek and updated lines are broad, but archive model snapshots lack full availability timestamps and previous reports show the market absorbs much of the early signal. | Pre-register a single timing-specific hypothesis; walk seasons chronologically; require a strictly common population and never call closing-line results Thursday evidence. |
| P2 | Are calibration errors meaningfully different by favorite strength or straight-up versus pool-lined games? | Existing calibration reports show possible small-line deviations, while bin/subgroup samples can be small. | Use fixed bins, season/week counts, week-clustered intervals, and multiplicity control. Pool-line and straight-up targets remain separate. Collapse or suppress sparse groups. |
| P2 | Do team-strength or contextual features add incremental value to the market? | Team-week stats and some player/NGS files exist. Earlier Elo/scoring/context stacks were weak or redundant with market. | Require a specific source and point-in-time feature definition before coding; compare with market-only and production Deadeye; stop if the feature merely duplicates a baseline or timestamp cannot be verified. |
| P3 | Does a forecast change actual ACQL weekly wins or payouts, not just log loss? | Historical backtests use assumptions for pool composition/lines; actual pool records are narrower. | Join only real historical pick sheets and payout rules on common weeks. Report actual result and uncertainty separately from simulated field performance. Do not claim a dollar gain from probability metrics alone. |
| P3 | Which model-error summaries belong in the dashboard? | The Lab already has calibration, distribution, teams, strength, stats, and postmortem views; more charts can overstate sparse evidence. | Analytics may propose a chart only when the source, denominator, benchmark, uncertainty, and available-at-deadline status can be shown. No prediction changes in this work. |

## Deprioritized until new evidence exists

- Re-running an unconstrained ensemble or another broad feature sweep without a new, falsifiable mechanism. The historical complex meta-learner was worse on its reported held-out seasons.
- Selecting a subgroup after inspecting its best-performing slice.
- Adding features from current injuries, closing odds, final team statistics, or other post-deadline information to a Thursday historical forecast.
- Any experiment whose result can only be measured by a single favorable week.
