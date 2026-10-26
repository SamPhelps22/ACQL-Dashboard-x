# Independent validation decision

**Outcome: REJECTED as a production improvement.**

## Same-population results

The archived walk-forward compared the candidate with Deadeye and a market-only line on the same historical midweek population. The candidate's development edge over Deadeye was +0.0021 log-loss points/game (95% interval -0.0009 to +0.0052). The reported holdout edge was -0.0043 (-0.0077 to -0.0009): the candidate was worse on the held-out block.

The holdout result, not the development rank, controls the rejection. The reported holdout seasons were previously viewed under the older strategy-lab protocol, so the result is informative but not a pristine prospective test.

## Gates and limitations

| Gate | Result | Evidence |
|---|---|---|
| Common games and baselines | Pass for the archived comparison | Strategy-lab reports compare candidate, Deadeye, and market on common rows. |
| Chronological split and leak check | Pass for the archived protocol | The repository report records a passed scramble-based leak check. |
| Preregistered development/holdout separation | Pass with reuse caveat | Candidate selection precedes the report's holdout evaluation; prior protocol exposure is documented. |
| Exact ACQL Thursday deadline parity | Fail | The archived market timing is midweek, not the exact local Thursday cutoff/earlier kickoff lock. |
| Historical feature publication times | Incomplete | Archive model values do not all have point-in-time publication timestamps. |
| Prospective locked weeks | Not available | No two-track prospective locked week had been scored in the current report. |

The historical evidence is sufficient to reject this particular candidate on its reported test result. It is insufficient to claim a new production candidate has passed the current prospective deadline protocol. This decision does not authorize code changes, forecast replacement, deployment, or a model switch.

## Reproduction checks in this setup audit

- `python tests/test_strategy_lab.py`: 26 passed, including same-game scoring, leak checks, lock protections, and small-sample/no-edge rejection.
- `python tests/test_model_lab.py`: 38 passed, including cutoff timestamp eligibility and rejection of missing timestamps.
- The source report is `docs/lab-2026-10-26.md`; the full original run artifacts are local under ignored `data/training/lab/runs/`.
