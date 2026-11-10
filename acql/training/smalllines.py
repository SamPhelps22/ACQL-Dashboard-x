"""What a small betting line has really meant - the study behind analytics.meant_margin.

    python -m acql.training.smalllines

Reads nflverse's games file (data/nflverse/games.csv.gz: the closing line,
the moneylines and the final score of every game since 1999) and answers
three questions, in this order, so the second never sees what the third is
scored on:

    1. Line by line, how have favourites of each size done - by how much they
       won on average, how often they won, what the curve says at that line
       and what the moneylines beside it said?
    2. What reading of a small line makes the curve agree with the market's
       own moneylines? Two numbers (how much is taken off at a point or two,
       and by what size of line nothing is), fitted to moneylines only.
    3. Scored on results, each season read with the two numbers fitted on the
       moneylines of the seasons before it: is the curve better for it?

Nothing here is imported by the dashboard, and nothing is changed by running
it. The reading in use is two constants in analytics.py; this says where
they came from and prints what would be fitted today.
"""

from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import numpy as np

from .. import analytics

POWER = 4
SHADES = np.arange(0, 0.701, 0.025)
REACHES = np.arange(1.5, 5.001, 0.125)
#: Lines the reading is fitted on: beyond two touchdowns the way the bookmaker's
#: margin is taken out of a moneyline matters more than the line does.
FIT_WITHIN = 14.0
FIRST_SCORED = 2010


def _chance(p: str) -> float | None:
    try:
        v = float(p)
    except ValueError:
        return None
    if not v:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def load(path: Path) -> dict[str, np.ndarray]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle):
            if r["game_type"] != "REG" or not r["home_score"] or not r["spread_line"]:
                continue
            ours, theirs = _chance(r["home_moneyline"]), _chance(r["away_moneyline"])
            rows.append((int(r["season"]), int(r["week"]), float(r["spread_line"]),
                         float(r["home_score"]) - float(r["away_score"]),
                         ours / (ours + theirs) if ours and theirs else np.nan))
    a = np.array(rows, dtype=float)
    return {"season": a[:, 0].astype(int), "week": a[:, 1].astype(int), "line": a[:, 2], "margin": a[:, 3],
            "moneyline": a[:, 4]}


def _curve():
    """The curve in use, as two look-ups: margin -> the home side's chance (ties aside), and back."""
    grid = np.round(np.arange(-40, 40.05, 0.1), 1)

    def home(x: float) -> float:
        win, lose = analytics.cover_chance(float(x), 1), analytics.cover_chance(float(-x), 1)
        return win / (win + lose)

    table = np.array([home(x) for x in grid])
    return (lambda m: np.interp(np.clip(m, -40, 40), grid, table)), (lambda p: np.interp(p, table, grid))


def read(line, shade: float, reach: float):
    """analytics.meant_margin with the two numbers passed in."""
    return line * (1 - shade * np.exp(-(np.abs(line) / reach) ** POWER))


def fit(line, target) -> tuple[float, float]:
    """The (shade, reach) that puts the curve nearest the moneylines' own margins."""
    best = None
    for shade in SHADES:
        for reach in REACHES:
            miss = float(((read(line, shade, reach) - target) ** 2).mean())
            if best is None or miss < best[0]:
                best = (miss, float(shade), float(reach))
    return best[1], best[2]


def _range(gain, weeks, draws: int = 3000, seed: int = 3) -> tuple[float, float, float]:
    """The average gain a game and its 95% range, redrawing whole weeks."""
    rng = np.random.default_rng(seed)
    _, where = np.unique(weeks, return_inverse=True)
    sums, counts = np.bincount(where, weights=gain), np.bincount(where)
    drawn = [sums[k].sum() / counts[k].sum() for k in (rng.integers(0, len(sums), len(sums)) for _ in range(draws))]
    return float(gain.mean()), float(np.percentile(drawn, 2.5)), float(np.percentile(drawn, 97.5))


def study(path: Path) -> str:
    d = load(path)
    season, line, margin, money = d["season"], d["line"], d["margin"], d["moneyline"]
    chance, margin_for = _curve()
    out = [f"Games: {len(line):,} regular-season games with a closing line, {season.min()}-{season.max()} "
           f"({int(np.isfinite(money).sum()):,} with moneylines, from {season[np.isfinite(money)].min()}).", ""]

    # 1. favourites of each size
    fav, side = np.abs(line), np.where(line > 0, 1.0, -1.0)
    out += ["## 1. Favourites of each size", "",
            "| Line | Games | Won by, on average | Won | Curve at the line | Moneylines said |", "|---:|---:|---:|---:|---:|---:|"]
    for size in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 6.0, 7.0, 10.0):
        at = (fav == size) & (margin != 0)
        with_money = at & np.isfinite(money)
        said = np.where(side > 0, money, 1 - money)[with_money].mean() if with_money.any() else float("nan")
        out.append(f"| {size:g} | {int(at.sum()):,} | {(side * margin)[fav == size].mean():+.1f} | "
                   f"{(side * margin > 0)[at].mean():.1%} | {float(chance(size)):.1%} | {said:.1%} |")

    # 2. the reading that agrees with the moneylines
    has = np.isfinite(money) & (fav <= FIT_WITHIN)
    target = np.where(has, margin_for(np.nan_to_num(money, nan=0.5)), np.nan)
    shade, reach = fit(line[has], target[has])
    out += ["", "## 2. The reading that agrees with the moneylines", "",
            f"Fitted today on {int(has.sum()):,} games: shade {shade:.3f}, reach {reach:.3f} "
            f"(in use: {analytics.SMALL_LINE_SHADE}, {analytics.SMALL_LINE_REACH}).", "",
            "| Line | Read as | Favourite's chance before | after |", "|---:|---:|---:|---:|"]
    for size in (0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 7):
        now = float(read(size, shade, reach))
        out.append(f"| {size:g} | {now:.2f} | {float(chance(size)):.1%} | {float(chance(now)):.1%} |")

    # 3. scored on results, walked forward
    decided = margin != 0
    won = (margin > 0).astype(float)

    def loss(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return -(won * np.log(p) + (1 - won) * np.log(1 - p))

    before = loss(chance(line))
    after = np.full(len(line), np.nan)
    for year in range(FIRST_SCORED, int(season.max()) + 1):
        earlier = has & (season < year)
        s, r = fit(line[earlier], target[earlier])
        after[season == year] = loss(chance(read(line, s, r)))[season == year]
    weeks = season * 100 + d["week"]
    out += ["", "## 3. Scored on results (log loss a game; + is better with the reading)", "",
            "Each season read with numbers fitted on earlier seasons' moneylines only.", "",
            "| Games | Count | Gain | 95% range |", "|---|---:|---:|---|"]
    scored = decided & (season >= FIRST_SCORED)
    half = (FIRST_SCORED + int(season.max())) // 2
    for label, mask in ((f"{FIRST_SCORED}-{season.max()}", scored),
                        ("lines of 3 and under", scored & (fav <= 3)),
                        ("lines over 3", scored & (fav > 3)),
                        (f"{FIRST_SCORED}-{half}", scored & (season <= half)),
                        (f"{half + 1}-{season.max()}", scored & (season > half))):
        mean, low, high = _range((before - after)[mask], weeks[mask])
        out.append(f"| {label} | {int(mask.sum()):,} | {mean:+.5f} | {low:+.5f} to {high:+.5f} |")
    early = decided & (season < FIRST_SCORED) & ~np.isfinite(money)
    if early.any():
        fixed = loss(chance(read(line, shade, reach)))
        mean, low, high = _range((before - fixed)[early], weeks[early])
        out.append(f"| {season[early].min()}-{season[early].max()}, no moneylines to fit to (today's numbers) | "
                   f"{int(early.sum()):,} | {mean:+.5f} | {low:+.5f} to {high:+.5f} |")
    both = decided & np.isfinite(money)
    out += ["", f"Where there is a moneyline ({int(both.sum()):,} games): the curve at the line "
                f"{before[both].mean():.5f}, the curve with the reading "
                f"{loss(chance(read(line, shade, reach)))[both].mean():.5f}, the moneyline itself "
                f"{loss(np.nan_to_num(money, nan=0.5))[both].mean():.5f}."]
    return "\n".join(out)


def main() -> int:
    from ..feeds import nflverse
    path = nflverse.FOLDER / nflverse.GAMES_FILE
    if not path.is_file():
        print(f"No games file at {path}. `python -m acql.model.seasonsim --fetch` gets it (goes online).",
              file=sys.stderr)
        return 1
    print(study(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
