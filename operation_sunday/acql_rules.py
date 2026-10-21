"""ACQL pool rules, read from the dashboard's own code (read-only).

Authoritative implementation: acql/model/backtest.py (pool_line, LINED_FROM =
6.5) and acql/analytics.py (line_need, cover_chance, spread_for_win_chance).
  * one point per credited pick, no confidence points;
  * a favourite of 6.5+ carries a pool line; it must win by at least
    line_need(line) (a win by exactly the line counts) or the underdog is
    credited; a tie with no line credits nobody.

Probability forecasting and pick selection are kept apart: this module turns a
finished forecast into a pick and never feeds anything back into a model.

Pool lines: the real commissioner's line when the slate gives one; otherwise
the commissioner's measured habit (acql.model.backtest.pool_line) applied to a
spread - in retrospective evaluation that spread is the closing line, which
is labelled as a reconstruction.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from acql import analytics
from acql.model import backtest as acql_bt

LINED_FROM = acql_bt.LINED_FROM


def pool_line_for(home_spread: float | None) -> float | None:
    if home_spread is None or np.isnan(home_spread):
        return None
    return acql_bt.pool_line(float(home_spread))


def credited_home_prob(p_home: float, home_spread_for_line: float | None, line: float | None = None) -> float:
    """P(home credited) given a probability forecast and the game's pool line.

    The forecast's probability is turned into a margin with Deadeye's own
    distribution (spread_for_win_chance), and the line applied with
    cover_chance - the same math the dashboard uses."""
    if line is None:
        line = pool_line_for(home_spread_for_line)
    if line is None:
        return float(p_home)
    fav_home = home_spread_for_line is not None and home_spread_for_line > 0
    p_fav = p_home if fav_home else 1 - p_home
    fav_margin = analytics.spread_for_win_chance(p_fav)
    need = analytics.line_need(line)
    if fav_margin >= 0:
        p_fav_credit = analytics.cover_chance(fav_margin, need)
    else:
        p_fav_credit = 1 - analytics.cover_chance(-fav_margin, -need + 1)
    return float(p_fav_credit if fav_home else 1 - p_fav_credit)


def credited_side(margin: float, home_spread_for_line: float | None, line: float | None = None) -> str | None:
    """'home', 'away' or None from the real margin, under the pool's rules."""
    if line is None:
        line = pool_line_for(home_spread_for_line)
    if line is None:
        return None if margin == 0 else ("home" if margin > 0 else "away")
    fav_home = home_spread_for_line > 0
    fav_margin = margin if fav_home else -margin
    fav_ok = fav_margin >= analytics.line_need(line)
    return ("home" if fav_home else "away") if fav_ok else ("away" if fav_home else "home")


def pool_points(scored: pd.DataFrame, line_col: str = "close_spread") -> pd.DataFrame:
    """Per-game expected and realised ACQL points for each model's picks.

    `line_col` names the spread the pool line is reconstructed from. The same
    slate, rules and eligibility are used for every model."""
    s = scored[scored["p_home"].notna()].copy()
    cred = [credited_home_prob(p, sp) for p, sp in zip(s["p_home"], s[line_col])]
    s["p_home_credited"] = cred
    s["pick"] = np.where(s["p_home_credited"] >= 0.5, "home", "away")
    s["exp_points"] = np.maximum(s["p_home_credited"], 1 - s["p_home_credited"])
    actual = [credited_side(m, sp) if not np.isnan(m) else "pending" for m, sp in zip(s["margin"], s[line_col])]
    s["credited"] = actual
    s["points"] = np.where(s["credited"] == "pending", np.nan, (s["pick"] == s["credited"]).astype(float))
    s["lined"] = [pool_line_for(sp) is not None for sp in s[line_col]]
    return s


def load_recorded_deadeye() -> tuple[pd.DataFrame, str]:
    """Deadeye cards the dashboard actually kept before kickoff (its store,
    "cards"). Snapshots marked `rebuilt` were made after the fact and are
    kept apart - they are reconstructions, not recorded forecasts. Read-only;
    empty when this computer has no dashboard database."""
    try:
        from acql import store
        raw = store.items("cards")
    except Exception as exc:  # noqa: BLE001 - no database here
        return pd.DataFrame(), f"No recorded Deadeye cards available here ({type(exc).__name__})."
    rows = []

    def walk(obj, path):
        if isinstance(obj, dict) and "take" in obj and "chance" in obj:
            for idx, side in (obj.get("take") or {}).items():
                rows.append({"key": "/".join(path), "index": idx, "side": side,
                             "chance": (obj.get("chance") or {}).get(idx),
                             "label": (obj.get("label") or {}).get(idx), "at": obj.get("at"),
                             "kind": "reconstructed" if obj.get("rebuilt") else "recorded"})
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, path + [str(k)])
    walk(raw, [])
    df = pd.DataFrame(rows)
    if df.empty:
        return df, "No recorded Deadeye cards in the dashboard store."
    n_rec = int((df["kind"] == "recorded").sum())
    return df, f"{n_rec} recorded Deadeye picks, {len(df) - n_rec} reconstructed (kept apart)."
