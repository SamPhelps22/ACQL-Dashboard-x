"""The evaluation stage: where Challenger meets Deadeye and the market.

This is the only part of the `challenger` package allowed to import the
dashboard (`acql`) - and only to capture Deadeye's forecasts through
Deadeye's own, unmodified code, and to apply the pool's own rules. Nothing in
here is ever read by the Challenger model pipeline (tests/test_challenger.py
checks that no model module imports `challenger.arena` or `acql`).

Every forecast source is captured on its own into a frame with the same
columns (model, game_id, p_home, ...) before any result is joined.
"""
