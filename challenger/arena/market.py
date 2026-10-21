"""Sportsbook baselines - evaluation only, never a Challenger input.

    market_moneyline   de-vigged closing moneylines: each side's implied
                       chance divided by their sum (the bookmaker's margin
                       removed proportionally)
    market_spread      the closing spread turned into a win chance by a
                       logistic curve fitted, walk-forward, on decided games
                       of earlier seasons only

Both use CLOSING numbers (nflverse records no opening or deadline-time line),
which carry information from after the ACQL deadline. That makes them a
stronger bar than any forecast made at the deadline could face.
"""

from __future__ import annotations

import pandas as pd


from ..data import implied_chance as implied


def moneyline(games: pd.DataFrame) -> pd.DataFrame:
    g = games[games["home_moneyline"].notna() & games["away_moneyline"].notna()]
    h, a = implied(g["home_moneyline"]), implied(g["away_moneyline"])
    return pd.DataFrame({"model": "market_moneyline", "game_id": g["game_id"].to_numpy(),
                         "p_home": h / (h + a), "overround": h + a - 1})


def spread(games: pd.DataFrame, seasons, first_fit_season: int = 2003) -> pd.DataFrame:
    """Closing spread -> chance, with the curve for season S fitted on seasons [first_fit_season, S-1]."""
    from sklearn.linear_model import LogisticRegression

    g = games[games["spread_line"].notna()]
    out = []
    for season in seasons:
        train = g[(g["season"] < season) & (g["season"] >= first_fit_season) & g["home_win"].notna()]
        test = g[g["season"] == season]
        if train.empty or test.empty:
            continue
        model = LogisticRegression(C=100.0).fit(train[["spread_line"]].to_numpy(), train["home_win"].to_numpy())
        out.append(pd.DataFrame({"model": "market_spread", "game_id": test["game_id"].to_numpy(),
                                 "p_home": model.predict_proba(test[["spread_line"]].to_numpy())[:, 1],
                                 "spread_slope": float(model.coef_[0][0])}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["model", "game_id", "p_home"])
