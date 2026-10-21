"""Project Challenger: an independent NFL win-probability engine.

Challenger is built to compete with Deadeye, not to improve it. Its model
pipeline (data, pbp, venues, elo, features, models, calibration, backtest,
predictions, shadow) never imports the dashboard (`acql`) or the separate
`nfl_pickem` package, never reads a Deadeye output, and never looks at a
betting line in its primary, market-free form. `tests/test_challenger.py`
checks that statically.

Deadeye only appears in `challenger.arena`, the evaluation stage, where each
model's forecasts are captured on their own and then scored on the same games.

Run `python -m challenger --help` from the project root.
"""

VERSION = "1.0.0"
