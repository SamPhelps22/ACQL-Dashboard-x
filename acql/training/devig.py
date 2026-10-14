"""Taking the bookmaker's margin out of a pair of moneylines - four ways, and which is right.

A book's two prices on a game imply chances that add up to more than 100%:
-150 and +130 are 60.0% and 43.5%, 103.5% between them. The extra 3.5% is the
book's margin, and how it is taken back out decides the "fair" chance. The
dashboard has always used the first way below (odds.parse, data.fair_win):

    Proportional   each side's chance scaled down by the same factor -
                   60.0 / 103.5 = 58.0%
    Additive       the same number of points off each side
    Power          each chance raised to the one power that makes them add
                   to 100% - takes more off the longshot
    Shin           Shin's (1993) model of a book guarding against bettors who
                   know more than it does - also leans on the longshot

The longshot methods only part company with the proportional one where a game
is lopsided, which is also where the top confidence points go. Whether they
are better is a question about results, and nflverse has the closing
moneylines and the final score of every game since 1999.

This only measures. It changes no pick, and the dashboard does not import it.
The moneylines are the closing ones: that is fine for choosing a *method* -
how to read a pair of prices - but says nothing about what was known on a
Thursday.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import data

METHODS = ("Proportional", "Additive", "Power", "Shin")
#: The method in use, the one the others are measured against.
IN_USE = "Proportional"
#: Resamples (whole seasons at a time) for the ranges on each difference.
RESAMPLES = 2000
#: A favourite this sure (fair, by the method in use) counts as a big one.
BIG_FAVOURITE = 0.75


# ---- the odds themselves ------------------------------------------------------------------------
def american_to_decimal(price: float) -> float:
    """-150 pays 1.667 a unit back; +130 pays 2.30."""
    if not price or -100 < price < 100:
        raise ValueError(f"not an American price: {price}")
    return 1 + (100 / -price if price < 0 else price / 100)


def decimal_to_american(decimal: float) -> float:
    """2.30 is +130; 1.667 is -150 (rounded as books round them)."""
    if decimal <= 1:
        raise ValueError(f"not a decimal price: {decimal}")
    return round((decimal - 1) * 100, 1) if decimal >= 2 else round(-100 / (decimal - 1), 1)


def implied(price: float) -> float:
    """The chance an American price implies, margin and all: -150 is 60%."""
    return 1 / american_to_decimal(price)


# ---- the four ways back to 100% -----------------------------------------------------------------
def _solve(f, low: float, high: float) -> float:
    """The root of an increasing-or-decreasing f between low and high, by halving."""
    f_low = f(low)
    for _ in range(100):
        mid = (low + high) / 2
        f_mid = f(mid)
        if (f_mid > 0) == (f_low > 0):
            low, f_low = mid, f_mid
        else:
            high = mid
    return (low + high) / 2


def fair(home: float, away: float, method: str = IN_USE) -> float:
    """The home side's fair chance from the two sides' implied chances."""
    total = home + away
    if home <= 0 or away <= 0:
        raise ValueError("both chances must be above zero")
    if method == "Proportional":
        return home / total
    if method == "Additive":
        return min(1.0, max(0.0, home - (total - 1) / 2))
    if method == "Power":
        if abs(total - 1) < 1e-12:
            return home
        k = _solve(lambda k: home ** k + away ** k - 1, 1e-6, 50.0)
        return home ** k
    if method == "Shin":
        if total <= 1:
            return home / total

        def side(q: float, z: float) -> float:
            return (math.sqrt(z * z + 4 * (1 - z) * q * q / total) - z) / (2 * (1 - z))

        z = _solve(lambda z: side(home, z) + side(away, z) - 1, 0.0, 0.999)
        return side(home, z)
    raise ValueError(f"no such method: {method}")


# ---- measured on every game nflverse has ------------------------------------------------------------
def games(path=None) -> pd.DataFrame:
    """Every finished, untied game with both closing moneylines: season,
    week, the two prices, and whether the home side won."""
    import csv
    import gzip
    from ..feeds.nflverse import FOLDER, GAMES_FILE
    rows = []
    try:
        with gzip.open(path or FOLDER / GAMES_FILE, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                hp, ap = data._number(row.get("home_moneyline")), data._number(row.get("away_moneyline"))
                hs, as_ = data._number(row.get("home_score")), data._number(row.get("away_score"))
                if None in (hp, ap, hs, as_) or hs == as_ or abs(hp) < 100 or abs(ap) < 100:
                    continue
                rows.append({"season": int(row["season"]), "week": int(row["week"]),
                             "kind": row.get("game_type", ""), "home_price": hp, "away_price": ap,
                             "home_won": float(hs > as_)})
    except OSError:
        return pd.DataFrame()
    return pd.DataFrame(rows)


@dataclass
class Score:
    method: str
    games: int
    log_loss: float
    brier: float
    right: int
    big_games: int
    big_log_loss: float
    #: Against the method in use: mean log loss a game (negative is better)
    #: and the range whole-season resamples put on it.
    vs_in_use: float = 0.0
    low: float = 0.0
    high: float = 0.0
    first_season: int = 0
    last_season: int = 0


def _loss(p: np.ndarray, won: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(won * np.log(p) + (1 - won) * np.log(1 - p))


def study(frame: pd.DataFrame | None = None, seed: int = 2026) -> tuple[list[Score], pd.DataFrame]:
    """Each method's score, and a table of how sure each was against how often favourites won."""
    frame = games() if frame is None else frame
    if frame.empty:
        return [], pd.DataFrame()
    q_home = frame["home_price"].map(implied).to_numpy()
    q_away = frame["away_price"].map(implied).to_numpy()
    won = frame["home_won"].to_numpy()
    seasons = frame["season"].to_numpy()
    chances = {m: np.array([fair(h, a, m) for h, a in zip(q_home, q_away)]) for m in METHODS}
    base = chances[IN_USE]
    big = np.maximum(base, 1 - base) >= BIG_FAVOURITE
    losses = {m: _loss(p, won) for m, p in chances.items()}
    rng = np.random.default_rng(seed)
    years = np.unique(seasons)
    picks = [rng.choice(years, len(years)) for _ in range(RESAMPLES)]
    by_year = {y: seasons == y for y in years}
    out = []
    for m, p in chances.items():
        diff = losses[m] - losses[IN_USE]
        sums = {y: (diff[by_year[y]].sum(), by_year[y].sum()) for y in years}
        means = [sum(sums[y][0] for y in pick) / sum(sums[y][1] for y in pick) for pick in picks]
        out.append(Score(
            m, len(p), float(losses[m].mean()), float(((p - won) ** 2).mean()),
            int(((p > 0.5) == (won == 1)).sum()), int(big.sum()), float(losses[m][big].mean()),
            float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)),
            int(years.min()), int(years.max()),
        ))
    fav = np.maximum(base, 1 - base)
    fav_won = np.where(base >= 0.5, won, 1 - won)
    bands = pd.cut(fav, [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], include_lowest=True)
    table = pd.DataFrame({"band": bands, "won": fav_won,
                          **{m: np.maximum(chances[m], 1 - chances[m]) for m in METHODS}})
    calibration = table.groupby("band", observed=True).agg(
        games=("won", "size"), favourites_won=("won", "mean"), **{m: (m, "mean") for m in METHODS})
    return out, calibration


def write_up(scores: list[Score], calibration: pd.DataFrame) -> str:
    if not scores:
        return "# Taking out the margin\n\nnflverse's games file is not in data/nflverse - nothing to measure.\n"
    first = scores[0]
    lines = [
        "# Taking out the margin: four methods against the results",
        "",
        f"{first.games:,} finished, untied games with both closing moneylines (nflverse), "
        f"seasons {first.first_season}-{first.last_season}. Lower log loss and Brier are better. "
        f"The range on each difference comes from {RESAMPLES:,} resamples of whole seasons; "
        "a range that takes in zero cannot be told apart from the method in use.",
        "",
        "| Method | Games | Log loss | Brier | Favourites right | Log loss, big favourites "
        f"({first.big_games:,} games) | Against {IN_USE.lower()}, a game | Range |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        same = s.method == IN_USE
        lines.append(
            f"| {s.method}{' (in use)' if same else ''} | {s.games:,} | {s.log_loss:.5f} | {s.brier:.5f} | "
            f"{s.right:,} ({s.right / s.games:.1%}) | {s.big_log_loss:.5f} | "
            f"{'-' if same else f'{s.vs_in_use:+.5f}'} | {'-' if same else f'{s.low:+.5f} to {s.high:+.5f}'} |")
    lines += ["", "How sure each method was of the favourite, against how often favourites won:", "",
              "| Favourite's chance | Games | Won | " + " | ".join(METHODS) + " |",
              "| --- | --- | --- | " + " | ".join("---" for _ in METHODS) + " |"]
    for band, row in calibration.iterrows():
        lines.append(f"| {band} | {int(row['games']):,} | {row['favourites_won']:.1%} | "
                     + " | ".join(f"{row[m]:.1%}" for m in METHODS) + " |")
    best = min(scores, key=lambda s: s.vs_in_use)
    if best.method == IN_USE or best.high >= 0:
        verdict = (f"Nothing beats {IN_USE.lower()} by more than the games can vouch for: keep it.")
    else:
        verdict = (f"{best.method} is better by {-best.vs_in_use:.5f} a game, and the range "
                   f"({best.low:+.5f} to {best.high:+.5f}) stays below zero. Worth proposing - it only "
                   "touches straight-up games, where the moneyline is used (pricing._anchor).")
    lines += ["", f"**Verdict:** {verdict}", "",
              "Every method picks the same favourite (pick'ems aside), so the number right barely moves: "
              "they differ only in how sure they are.", ""]
    return "\n".join(lines)


def run() -> tuple[str, object]:
    scores, calibration = study()
    text = write_up(scores, calibration)
    where = data.folder() / "patterns"
    where.mkdir(parents=True, exist_ok=True)
    path = where / "margin-removal.md"
    path.write_text(text, encoding="utf-8")
    return text, path
