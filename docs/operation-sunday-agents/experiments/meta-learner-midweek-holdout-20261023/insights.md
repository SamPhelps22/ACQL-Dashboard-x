# Analytics interpretation: meta-learner holdout

## Evidence

This is an interpretation of the archived research and independent validation records, not a new experiment. The source report is [the October 26 strategy-lab findings](../../../lab-2026-10-26.md). The candidate's development and held-out metrics are preserved in [record.json](./record.json); the validation decision and parity checks are in [validation.json](./validation.json).

## Supported conclusion

- The candidate's development estimate favored it by 0.0021 log-loss points per game, but the interval included zero.
- On the reported held-out seasons it was worse than Deadeye by 0.0043 points per game, with the reported interval fully below zero. This supports rejecting this candidate for this protocol; it does not prove that every ensemble is harmful.
- Complexity is not evidence of predictive value. Selecting a stack because it ranked first on development would have been a misleading success narrative.

## Descriptive observations and limitations

- The report also describes market-only performance as slightly better than Deadeye on development and slightly worse on the held-out block; both reported uncertainty intervals include zero. Those data do not establish a general winner between the market and Deadeye.
- The held-out seasons had prior exposure under the older lab protocol. Historical archive model values do not all have publication timestamps, and the line is midweek rather than the exact Thursday cutoff. Do not call this prospective, cutoff-clean validation.
- ACQL's real weekly pool payouts cannot be inferred from probability log loss. Pool pick performance, dollar results, and proxy simulations must remain separate.

## Next useful analysis

Prioritize a prospective report that accumulates immutable Thursday locks over enough distinct weeks, with candidate, Deadeye, and market baselines on identical games and the real credited-pick rules. Show season/week counts and week-clustered uncertainty. Do not create a team, quarterback, or injury narrative from this small live sample.

## Suggested visual

A paired log-loss difference plot by season with a zero reference, displaying game and week counts and a week-clustered interval. Label development and previously viewed holdout seasons separately; place the candidate's negative held-out result beside the neutral market-versus-Deadeye interval. Avoid a smooth trend line or causal caption.
