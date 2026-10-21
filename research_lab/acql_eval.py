"""ACQL weekly cards under the rules the repository implements.

Rules come from the dashboard's own code, imported read-only (these are pool
rules, not Deadeye's prediction functions):

    acql.model.backtest.pool_line(spread)   a favourite of 6.5+ carries a pool line,
                                            max(7, floor(spread) + 1)
    acql.analytics.line_need(line)          the favourite must win by at least ceil(line)

One point per correct pick; an unlined tie scores nobody.

The pool line is RECONSTRUCTED from the nflverse closing spread for every
season (the commissioner's habit was measured on 2025 wk 15 - 2026 wk 3). The
repository records no rule change, so one ruleset is applied throughout -
an assumption, disclosed in every report.

A card picks, for each game, the side the model gives the better chance of
being credited: on an unlined game the likelier winner; on a lined game the
favourite if P(favourite margin >= need) > 1/2. That chance comes from the
model's expected margin and spread when it has them, else from its win
probability turned into a margin on a normal curve (MARGIN_SD).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .models.base import norm_cdf, p_to_margin


def _rules():
    import sys
    if str(config.ROOT) not in sys.path:
        sys.path.insert(0, str(config.ROOT))
    from acql import analytics
    from acql.model.backtest import pool_line
    return pool_line, analytics.line_need


def credited(spread: float, margin: float):
    """'home', 'away' or None (a tie on an unlined game)."""
    pool_line, line_need = _rules()
    line = pool_line(spread)
    if line is None:
        return None if margin == 0 else ("home" if margin > 0 else "away")
    need = line_need(line)
    if spread > 0:
        return "home" if margin >= need else "away"
    return "away" if -margin >= need else "home"


def pick(spread: float, p_home: float, exp_margin: float | None, sd: float | None) -> str:
    pool_line, line_need = _rules()
    line = pool_line(spread)
    if line is None:
        return "home" if p_home >= 0.5 else "away"
    need = line_need(line)
    m = exp_margin if exp_margin is not None and not np.isnan(exp_margin) else float(p_to_margin(p_home))
    s = sd if sd is not None and not np.isnan(sd) and sd > 0 else config.MARGIN_SD
    if spread > 0:     # home favourite: P(home margin >= need), continuity-corrected
        p_fav = float(norm_cdf((m - (need - 0.5)) / s))
        return "home" if p_fav > 0.5 else "away"
    p_fav = float(norm_cdf((-m - (need - 0.5)) / s))
    return "away" if p_fav > 0.5 else "home"


def cards(forecasts: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Per (model, game): the pick, the credited side, the point."""
    r = results[results["spread_line"].notna() & results["margin"].notna()][
        ["game_id", "season", "week", "spread_line", "margin"]]
    f = forecasts.merge(r, on=["game_id"], how="inner", suffixes=("", "_r"))
    rows = []
    for x in f.itertuples():
        side = pick(x.spread_line, float(x.p_home_raw),
                    None if pd.isna(x.exp_margin) else float(x.exp_margin),
                    None if pd.isna(x.margin_sd) else float(x.margin_sd))
        cred = credited(x.spread_line, x.margin)
        rows.append({"model": x.model, "game_id": x.game_id, "season": x.season, "week": x.week, "pick": side,
                     "credited": cred, "point": int(cred is not None and side == cred)})
    return pd.DataFrame(rows)


def weekly(card_rows: pd.DataFrame) -> pd.DataFrame:
    return card_rows.groupby(["model", "season", "week"])["point"].agg(points="sum", games="size").reset_index()
