"""Does the weather tell us anything the betting market has not already priced?

A study, not a recipe: nothing here feeds the live model.

Weather comes from the nflverse games file already on disk (data/nflverse):
its roof, temp (degrees F) and wind (mph) are the game-day conditions as
Pro Football Reference recorded them. No precipitation is in that file, so
rain and snow are not studied here. Nothing is filled in:

    indoor      roof "dome" or "closed": the weather is known - there is none.
    outdoor     roof "outdoors" or "open" with a temp and wind in range.
    missing     an outdoor game with no temp or wind, a reading out of range,
                or no roof at all. Left out of every comparison.

The market is the closing spread. Both models are a logistic regression on the
home side winning, fitted on every earlier season and scored on the next one
(2006 to the last full season), on the same games, by log loss and Brier score.

    python -m acql.training.weather
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..feeds.nflverse import FOLDER, GAMES_FILE

FIRST_TEST = 2006
#: Readings outside these are taken for errors, not weather.
TEMP_RANGE = (-20, 115)
WIND_RANGE = (0, 45)
HIGH_WIND = 15


def profiles(path=None) -> pd.DataFrame:
    """One row a finished regular- or post-season game with its weather profile."""
    g = pd.read_csv(path or FOLDER / GAMES_FILE)
    g = g[g.result.notna() & (g.result != 0) & g.spread_line.notna()].copy()
    indoor = g.roof.isin(["dome", "closed"])
    outdoor = g.roof.isin(["outdoors", "open"])
    sane = g.temp.between(*TEMP_RANGE) & g.wind.between(*WIND_RANGE)
    g["weather"] = np.select([indoor, outdoor & sane], ["indoor", "outdoor"], "missing")
    g["home_win"] = (g.result > 0).astype(float)
    out = g.weather == "outdoor"
    g["wind_x"] = np.where(out, g.wind, 0.0)
    g["cold_x"] = np.where(out, np.clip(40 - g.temp, 0, None), 0.0)  # degrees below 40F
    g["hot_x"] = np.where(out, np.clip(g.temp - 85, 0, None), 0.0)
    g["outdoor_x"] = out.astype(float)
    g["windy"] = out & (g.wind >= HIGH_WIND)
    return g


def _fit(X, y, ridge=1e-3, steps=50):
    w = np.zeros(X.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-X @ w))
        H = X.T @ (X * (p * (1 - p))[:, None]) + ridge * np.eye(len(w))
        w -= np.linalg.solve(H, X.T @ (p - y) + ridge * w)
    return w


def _design(d, weather):
    s = d.spread_line.to_numpy() / 7  # home favoured by s*7 points
    cols = [np.ones(len(d)), s]
    if weather:
        for c in (("wind_x",) if weather == "wind" else ("wind_x", "cold_x", "hot_x", "outdoor_x")):
            v = d[c].to_numpy()
            cols += [v / 10, s * v / 10]  # a level shift and a squeeze of the favourite
    return np.column_stack(cols)


def walk_forward(g: pd.DataFrame) -> pd.DataFrame:
    g = g[g.weather != "missing"]
    rows = []
    for season in range(FIRST_TEST, int(g.season.max()) + 1):
        train, test = g[g.season < season], g[g.season == season]
        if len(test) < 100:
            continue  # a season still being played
        t = test.copy()
        for name, weather in (("p_market", False), ("p_weather", True), ("p_wind", "wind")):
            w = _fit(_design(train, weather), train.home_win.to_numpy())
            t[name] = 1 / (1 + np.exp(-_design(test, weather) @ w))
        rows.append(t)
    return pd.concat(rows)


def scores(t: pd.DataFrame) -> dict:
    y = t.home_win.to_numpy()
    out = {"games": len(t)}
    for m in ("p_market", "p_weather", "p_wind"):
        p = np.clip(t[m].to_numpy(), 1e-6, 1 - 1e-6)
        out[m + "_logloss"] = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        out[m + "_brier"] = float(np.mean((p - y) ** 2))
    return out


def bootstrap_gain(t: pd.DataFrame, col="p_weather", n=2000, seed=0):
    """Log-loss gain of weather over market, with a 90% interval resampling whole seasons."""
    y = t.home_win.to_numpy()
    ll = lambda p: -(y * np.log(p) + (1 - y) * np.log(1 - p))
    gain = pd.Series(ll(t.p_market.to_numpy()) - ll(t[col].to_numpy()), index=t.index)
    by = gain.groupby(t.season.to_numpy()).agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(by), (n, len(by)))
    boot = by["sum"].to_numpy()[pick].sum(1) / by["count"].to_numpy()[pick].sum(1)
    return gain.mean(), np.percentile(boot, [5, 95])


def sensitivity(g: pd.DataFrame) -> pd.DataFrame:
    """How a weather-aware fit on every season moves a game's chance as conditions change."""
    g = g[g.weather != "missing"]
    w = _fit(_design(g, True), g.home_win.to_numpy())
    rows = []
    for spread in (3, 7):
        for wind, temp in ((0, 60), (10, 60), (20, 60), (30, 60), (5, 20), (5, 0)):
            d = pd.DataFrame({"spread_line": [spread], "wind_x": [wind], "cold_x": [max(40 - temp, 0)],
                              "hot_x": [0.0], "outdoor_x": [1.0]})
            base = d.assign(wind_x=0.0, cold_x=0.0)
            p = lambda x: float(1 / (1 + np.exp(-_design(x, True) @ w))[0])
            rows.append({"home favoured by": spread, "wind mph": wind, "temp F": temp,
                         "home win %": round(100 * p(d), 1), "vs calm 60F": round(100 * (p(d) - p(base)), 1)})
    return pd.DataFrame(rows)


def main():
    g = profiles()
    print("weather profiles:", g.weather.value_counts().to_dict())
    t = walk_forward(g)
    print("all games", scores(t))
    for col in ("p_weather", "p_wind"):
        gain, ci = bootstrap_gain(t, col)
        print(f"{col} log-loss gain {gain:+.5f} (90% {ci[0]:+.5f} to {ci[1]:+.5f})")
    for label, mask in (("indoor", t.weather == "indoor"), ("outdoor calm", (t.weather == "outdoor") & ~t.windy),
                        (f"wind >= {HIGH_WIND}", t.windy), ("wind >= 20", t.wind_x >= 20),
                        ("below 25F", (t.weather == "outdoor") & (t.temp < 25))):
        s = t[mask]
        print(label, scores(s), "gains %+.5f %+.5f" % (bootstrap_gain(s)[0], bootstrap_gain(s, "p_wind")[0]))
    print(sensitivity(g).to_string(index=False))


if __name__ == "__main__":
    main()
