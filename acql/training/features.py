"""What a recipe may look at, worked out the same way for every game.

A game is priced "as of" a moment - the opening line, the pool's deadline,
the last update, the close (data.TIMINGS). `prepare` takes the table and one
such setting and lays out, for every game, the market's number at that moment
and everything known by then: what the computer models made of it, how far
they sat from the line, how far the line had moved to get there. A number
taken later than the setting allows is refused, not used - a closing
moneyline says nothing a card handed in on Thursday could have known.

The models are boiled down exactly as the picks boil them down
(predictions.trimmed, home_lean, typical_disagreement), so "the gap" here is
the same gap Deadeye nudges by.

Nothing here looks at a result except to write down the answer (`target`,
`credited`), and the walk-forward takes those two columns away from a recipe
before it is asked to price a game.

No Qt here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import analytics, predictions
from . import data
from .data import MODEL, NAMELESS, Notes, TIMINGS

#: What a recipe must never be handed when it prices a game: the answers.
ANSWERS = ("actual", "target", "credited", "credited_home", "home_points", "away_points")
#: Fewest models before their middle counts as a crowd (predictions.MIN_KEPT).
ENOUGH_MODELS = predictions.MIN_KEPT
#: A slate needs this many games with a gap before it has a shared lean (predictions.home_lean).
LEAN_GAMES = 6


@dataclass(frozen=True)
class Setting:
    """One way of asking the question: which line, taken when."""

    key: str
    title: str
    market: str             # the column holding the market's home margin
    as_of: str              # data.TIMINGS: nothing taken later may be used
    about: str = ""

    def allows(self, timing: str) -> bool:
        return TIMINGS.index(timing) <= TIMINGS.index(self.as_of)


SETTINGS = {s.key: s for s in (
    Setting("updated", "Against the line as last updated", "line_updated", "updated",
            "The archive's own betting line: the last one the site took down before the game, usually late in the "
            "week. The hardest line to beat, and later than a Thursday card could have seen."),
    Setting("opening", "Against the opening line", "line_opening", "opening",
            "Where the line opened, early in the week. Always known before the pool's deadline, but softer than "
            "the line a Thursday card is really priced from."),
    Setting("midweek", "Against the midweek line", "line_midweek", "midweek",
            "The line in the middle of the week - the nearest thing the archive has to the pool's Thursday "
            "deadline, kept for some seasons only."),
    Setting("closing", "Against the closing line", "line_closing", "closing",
            "nflverse's closing line. No computer models go with it; it is what the probability curve and the Big "
            "Loser chances are checked against."),
    Setting("deadline", "At the pool's deadline", "line_deadline", "deadline",
            "This season, on the dashboard's own records: the newest line taken at or before the pool's deadline."),
    Setting("used", "On the line the app priced from", "line_used", "updated",
            "This season, on the line the Model Lab replays each game with - for some weeks one taken after the "
            "deadline."),
)}

#: What each input is, for the report.
ABOUT = {
    "market": "the betting line itself (does the market misprice big favourites, or home teams?)",
    "gap": "the models' middle less the betting line",
    "gap_net": "the same, with the slate's shared home lean taken out",
    "week_lean": "the slate's shared lean: the middle of every game's gap that week",
    "gap_agree": "the net gap, scaled down when the models are strung out and up when they agree (Deadeye's own scaling)",
    "gap_mean": "the plain average of the models less the line",
    "gap_median": "the middle model less the line",
    "apart": "how far apart the models that count are (the spread of the trimmed middle)",
    "spread_all": "how far apart all the models are, wild ones included",
    "n_models": "how many models priced the game",
    "move": "how far the line has moved since it opened",
    "ml_gap": "the margin the moneyline implies, less the spread",
    "total": "the over/under",
    "total_rel": "the over/under less the slate's middle one",
    "rest": "the home side's days of rest less the road side's",
    "division": "a division game",
    "neutral": "a neutral site",
    "week": "the week of the season",
}
#: The inputs a regression on the market's error is given when the models are to hand...
CORE = ("gap_net", "week_lean", "gap_agree", "apart", "n_models", "move", "market")
#: ...and the ones that only a line taken with its moneyline and total can add.
EXTRAS = ("ml_gap", "total_rel", "rest", "division")


def _stats(values: np.ndarray) -> tuple[float, float, float, float, float, int]:
    """(the picks' middle, plain average, median, spread of the middle, spread of all, how many)."""
    present = values[~np.isnan(values)]
    count = len(present)
    if not count:
        return (np.nan,) * 5 + (0,)
    middle = predictions.trimmed(present.tolist())
    return (statistics.fmean(middle), float(present.mean()), float(np.median(present)),
            statistics.pstdev(middle) if len(middle) > 1 else np.nan,
            float(present.std()) if count > 1 else np.nan, count)


def prepare(frame: pd.DataFrame, setting: Setting, notes: Notes | None = None) -> pd.DataFrame:
    """The table as one setting sees it: only games that had that line, with
    every allowed input worked out and every later one left out."""
    notes = notes if notes is not None else Notes()
    if frame.empty or setting.market not in frame.columns:
        notes.note("setting", f"{setting.title}: the table has no {setting.market} column")
        return pd.DataFrame()
    out = frame[frame[setting.market].notna()].copy().reset_index(drop=True)
    if out.empty:
        return out
    out["market"] = out[setting.market].astype(float)
    out["order"] = out["season"].astype(int) * 100 + out["week"].astype(int)

    # the line it opened at, and how far it has come: only when the opening is earlier than the line in use
    opening = out["line_opening"].astype(float) if "line_opening" in out.columns else pd.Series(np.nan, index=out.index)
    out["opening"] = opening if setting.market != "line_opening" else np.nan
    out["move"] = out["market"] - out["opening"]

    # the models, boiled down as the picks boil them down
    columns = data.model_columns(out)
    table = out[columns].to_numpy(dtype=float) if columns else np.empty((len(out), 0))
    stats = np.array([_stats(row) for row in table], dtype=float) if len(table) else np.empty((0, 6))
    for i, name in enumerate(("middle", "mean", "median", "apart", "spread_all", "n_models")):
        out[name] = stats[:, i] if len(stats) else np.nan
    out["gap"] = out["middle"] - out["market"]
    out["gap_mean"] = out["mean"] - out["market"]
    out["gap_median"] = out["median"] - out["market"]

    # the slate's shared lean and its usual disagreement - both from before the games
    lean = np.zeros(len(out))
    typical = np.zeros(len(out))
    total_mid = np.full(len(out), np.nan)
    total_column = next((c for c, t in (("total_deadline", "deadline"), ("total_closing", "closing"))
                         if c in out.columns and setting.allows(t) and out[c].notna().any()), None)
    win_column = next((c for c, t in (("win_deadline", "deadline"), ("win_closing", "closing"))
                       if c in out.columns and setting.allows(t) and out[c].notna().any()), None)
    for _, rows in out.groupby("order"):
        where = rows.index.to_numpy()
        gaps = rows["gap"].dropna()
        lean[where] = float(gaps.median()) if len(gaps) >= LEAN_GAMES else 0.0 if len(gaps) else np.nan
        spreads = rows["apart"][rows["apart"] > 0]
        typical[where] = float(spreads.median()) if len(spreads) else 0.0
        if total_column is not None and rows[total_column].notna().any():
            total_mid[where] = float(rows[total_column].median())
    out["week_lean"], out["typical"] = lean, typical
    out["gap_net"] = out["gap"] - out["week_lean"]
    scale = np.where((out["typical"] > 0) & (out["apart"] > 0),
                     2 * out["typical"] ** 2 / (out["typical"] ** 2 + out["apart"] ** 2), 1.0)
    out["gap_agree"] = out["gap_net"] * scale

    # the moneyline and the total, when they were taken no later than the line
    out["total"] = out[total_column].astype(float) if total_column is not None else np.nan
    out["total_rel"] = out["total"] - total_mid
    if win_column is not None:
        implied = [analytics.spread_for_win_chance(p) if not np.isnan(p) else np.nan
                   for p in out[win_column].to_numpy(dtype=float)]
        out["ml_gap"] = np.array(implied) - out["market"]
    else:
        out["ml_gap"] = np.nan
    refused = [c for c, t in (("total_closing", "closing"), ("win_closing", "closing"), ("line_closing", "closing"),
                              ("line_updated", "updated"))
               if c in frame.columns and frame[c].notna().any() and not setting.allows(t) and c != setting.market]
    if refused:
        notes.note("refused", f"{setting.title}: left out as taken later than this line - " + ", ".join(refused))
    for column in ("rest", "division", "neutral"):
        out[column] = out[column].astype(float) if column in out.columns else np.nan

    # the answers - written down here, and never handed to a recipe pricing the game
    if "actual" in out.columns:
        out["actual"] = out["actual"].astype(float)
        out["target"] = out["actual"] - out["market"]
    else:
        out["actual"] = out["target"] = np.nan
    from .probability import credited_home
    ruled = credited_home(out["actual"].to_numpy(dtype=float), out["pool_line"].to_numpy(dtype=float),
                          out["pool_favourite"].tolist())
    if "credited_home" in out.columns:                    # the pool's own grading, where there is one
        graded = out["credited_home"].to_numpy(dtype=float)
        out["credited"] = np.where(np.isnan(graded), ruled, graded)
    else:
        out["credited"] = ruled
    return out


#: An input that goes with the line's error this closely was not made before
#: the game. Nothing known going in gets near it: the models' gap, the best of
#: them, goes with the line's error at well under 0.1.
TOO_GOOD = 0.4


def suspects(prepared: pd.DataFrame, inputs=None) -> list[tuple[str, float]]:
    """Inputs that track what the line got wrong too closely to be forecasts:
    (input, how closely). A column that has seen the result - a score, a
    closing number filed under an earlier name - shows up here."""
    if prepared.empty or "target" not in prepared.columns:
        return []
    inputs = list(inputs) if inputs is not None else list(CORE + EXTRAS) + named_models(prepared)
    target = prepared["target"].to_numpy(dtype=float)
    out = []
    for column in inputs:
        if column not in prepared.columns:
            continue
        values = prepared[column].to_numpy(dtype=float)
        both = ~np.isnan(values) & ~np.isnan(target)
        if both.sum() < 50 or values[both].std() < 1e-9 or target[both].std() < 1e-9:
            continue
        # a model's own number goes with the result because the line does: it is its view of the line that is checked
        if column.startswith(MODEL):
            values = values - prepared["market"].to_numpy(dtype=float)
        r = float(np.corrcoef(values[both], target[both])[0, 1])
        if abs(r) >= TOO_GOOD:
            out.append((column, r))
    return out


def question(rows: pd.DataFrame) -> pd.DataFrame:
    """The same games with the answers taken away: what a recipe is handed to price."""
    return rows.drop(columns=[c for c in ANSWERS if c in rows.columns])


def named_models(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith(MODEL) and not c.startswith(NAMELESS)]


def coverage(prepared: pd.DataFrame, features: tuple[str, ...] | list[str]) -> pd.DataFrame:
    """Each input: how many games have it, the share, and over which seasons."""
    return data.coverage(prepared, list(features))
