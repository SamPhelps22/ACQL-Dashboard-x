"""The recipes on trial: each a way of turning what was known into a margin.

Every one starts from the market's number and adds a correction to it, so
"the betting line only" is the recipe whose correction is nothing and every
other has to earn whatever it adds:

    Betting line only     the bar
    Deadeye               the picks' own rule, run by the picks' own code
                          (predictions.Forecast.expected) at a share of 33% -
                          and at other shares, to test the 33
    Plain nudge           the line moved a flat share toward the models' middle
    Trained nudge         one number - how much of the gap to believe - fitted
                          to the games before, pulled toward none
    Ridge                 a regression on what the line got wrong, from the
                          gap, the slate's lean, how far apart the models are,
                          how far the line has moved and the line itself
    Ridge, model by model the same with every model's own view added
    Weighted crowd        the models weighted by how each has done against
                          the line over its last few seasons
    Straight-line fit     the plainest regression there is: the gap, a
                          constant, no pull toward anything
    Trees                 gradient boosting (contenders.boost) - only run when
                          there are enough games to teach it on

A recipe is `tune`d as a season begins (settings chosen on the seasons before
it), `fit` as each week begins (on every game before it) and then asked to
`predict` games it is shown without their results. Whatever it needs to know
about a column - its middle, its spread, what to do when it is missing - it
learns in `fit`, from the games it is taught on and no others.

No Qt here; numpy only, as contenders.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import contenders, predictions
from ..version import MODEL_NAME
from . import features
from .data import MODEL

MARKET, HYBRID = "Market", "Hybrid"
LINE = "Betting line only"
#: Games a recipe must have been taught on before it says anything.
MIN_TAUGHT = 400
#: The shares of the models' view tried, by the picks' rule and as a flat nudge.
SHARES = (0.10, 0.20, 0.33, 0.50, 0.75, 1.00)
#: How hard a regression is pulled toward "the line was right": this many times the games taught on.
PULLS = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
#: The pull used until there are seasons enough to choose one.
DEFAULT_PULL = 3.0
#: Seasons a setting is tried on (each taught on the ones before it) before one is chosen.
TRY_SEASONS = 5
#: An input needs to be there for this share of the games taught on, or it is left out.
MIN_COVER = 0.5
#: A model needs this share of the games taught on before its own view is an input...
MODEL_COVER = 0.4
#: ...and this many games over its last few seasons before its record sets its weight.
FORM_GAMES = 100
FORM_SEASONS = 3
#: How sharply the weighted crowd leans on its better models (0 is everyone alike).
POWERS = (0.0, 2.0, 8.0, 32.0)
#: Trees are only grown on this many games or more.
MIN_TREES = 2000


class Recipe:
    name = ""
    about = ""
    kind = HYBRID
    #: "week": taught again as each week begins; "season": once, as the season begins.
    refit = "week"
    #: Whether a game needs a crowd of models before this recipe will price it.
    wants_models = True

    def tune(self, taught: pd.DataFrame) -> None:
        """Choose settings, on games before the season about to be priced."""

    def fit(self, taught: pd.DataFrame) -> None:
        """Learn from games already played."""

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """The expected home margin of each game (nan where it cannot say)."""
        raise NotImplementedError

    def state(self) -> dict:
        """What it has settled on, for the record of what was known when."""
        return {}

    def _crowd(self, rows: pd.DataFrame) -> np.ndarray:
        return rows["n_models"].to_numpy(dtype=float) >= features.ENOUGH_MODELS


class Line(Recipe):
    name, kind, wants_models = LINE, MARKET, False
    about = "The sportsbooks' number and nothing else. The bar every other recipe has to clear."

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        return rows["market"].to_numpy(dtype=float)


class Slates:
    """Each slate as the picks' own code sees it (predictions.Forecast), made
    once however many shares are asked of it: one walk-forward's line-up
    shares one of these."""

    KEEP = 64

    def __init__(self) -> None:
        self._kept: dict[tuple, list] = {}

    def of(self, rows: pd.DataFrame) -> list[tuple[list[int], list, float, float]]:
        """(where each game is in `rows`, its forecasts, the slate's lean, its usual disagreement) a slate."""
        key = tuple(rows["game"])
        found = self._kept.get(key)
        if found is None:
            if len(self._kept) >= self.KEEP:
                self._kept.clear()
            found = self._kept[key] = _slates(rows)
        return found


def _slates(rows: pd.DataFrame) -> list[tuple[list[int], list, float, float]]:
    columns = [c for c in rows.columns if c.startswith(MODEL)]
    place = {index: i for i, index in enumerate(rows.index)}
    out = []
    for _, slate in rows.groupby("order"):
        made = []
        for record, opinions in zip(slate[["home", "away", "market", "opening"]].to_dict("records"),
                                    slate[columns].to_numpy(dtype=float)):
            opening = record["opening"]
            made.append(predictions.Forecast(
                road=record["away"], home=record["home"], market=float(record["market"]),
                opening=None if opening is None or np.isnan(opening) else float(opening),
                opinions=tuple(float(v) for v in opinions[~np.isnan(opinions)]),
            ))
        out.append(([place[index] for index in slate.index], made, predictions.home_lean(made),
                    predictions.typical_disagreement(made)))
    return out


def deadeye_margins(rows: pd.DataFrame, weight: float, slates: Slates | None = None) -> np.ndarray:
    """The margin the picks' own rule makes of each game, at a given share.

    The picks' code itself does the work (predictions.Forecast): the wildest
    fifth of the models dropped at each end, the slate's shared lean taken
    out, a gap the line has moved against discounted, and the share scaled
    by how far apart the models are against the slate's usual.
    """
    out = np.full(len(rows), np.nan)
    for where, made, lean, typical in (slates.of(rows) if slates is not None else _slates(rows)):
        for i, forecast in zip(where, made):
            out[i] = forecast.expected(weight, lean, typical)
    return out


class Deadeye(Recipe):
    def __init__(self, weight: float = predictions.CONSENSUS_WEIGHT, name: str | None = None,
                 slates: Slates | None = None) -> None:
        self.weight, self.slates = weight, slates
        self.name = name or f"{MODEL_NAME} at {weight:.0%}"
        self.about = (f"The picks' own rule, run by the picks' own code, believing {weight:.0%} of the models' "
                      "disagreement with the line.")

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        out = deadeye_margins(rows, self.weight, self.slates)
        out[~self._crowd(rows)] = np.nan
        return out

    def state(self) -> dict:
        return {"share": self.weight}


def _closest(losses: dict[float, np.ndarray], order: list[float]) -> float:
    """The setting to use: the first in `order` (most cautious first) that
    the best-scoring one does not beat by more than chance.

    `losses` is each setting's squared miss, game by game, on the same games.
    The best one's lead over another is the average of their differences,
    and how sure that lead is its standard error; a setting inside one
    standard error of the best is as good as the games can tell, and the
    most cautious such setting is the one taken.
    """
    means = {k: float(v.mean()) for k, v in losses.items()}
    best = min(means, key=means.get)
    for key in order:
        if key == best:
            return key
        lead = losses[key] - losses[best]
        if lead.mean() <= lead.std() / np.sqrt(len(lead)):
            return key
    return best


def _seasons_to_try(taught: pd.DataFrame) -> list[int]:
    """The last few seasons taught on that have enough before them to be asked about."""
    seasons = sorted(set(taught["season"].tolist()))
    return [s for s in seasons[-TRY_SEASONS:] if int((taught["season"] < s).sum()) >= MIN_TAUGHT]


class DeadeyeChosen(Recipe):
    """The picks' rule at whatever share the seasons before would have chosen."""

    def __init__(self, slates: Slates | None = None) -> None:
        self.slates = slates
        self.name = f"{MODEL_NAME}, share chosen on the past"
        self.about = ("The picks' own rule, at the share - none, or one of "
                      + ", ".join(f"{s:.0%}" for s in SHARES)
                      + " - that came closest to the results of every game before the season. The smallest share "
                        "that the best one does not clearly beat is taken.")
        self.weight = predictions.CONSENSUS_WEIGHT
        #: season -> each share's squared miss on that season's games. A
        #: season already played does not change, so it is worked out once.
        self._misses: dict[int, dict[float, np.ndarray]] = {}

    def tune(self, taught: pd.DataFrame) -> None:
        rows = taught[(taught["n_models"] >= features.ENOUGH_MODELS) & taught["target"].notna()]
        if len(rows) < MIN_TAUGHT:
            self.weight = predictions.CONSENSUS_WEIGHT
            return
        for season, mine in rows.groupby("season"):
            if int(season) not in self._misses:
                actual = mine["actual"].to_numpy(dtype=float)
                made = {0.0: (mine["market"].to_numpy(dtype=float) - actual) ** 2}
                for share in SHARES:
                    made[share] = (deadeye_margins(mine, share, self.slates) - actual) ** 2
                self._misses[int(season)] = made
        seasons = sorted(set(rows["season"].tolist()))
        losses = {share: np.concatenate([self._misses[s][share] for s in seasons]) for share in (0.0, *SHARES)}
        self.weight = _closest(losses, [0.0, *SHARES])

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        out = (deadeye_margins(rows, self.weight, self.slates) if self.weight
               else rows["market"].to_numpy(dtype=float).copy())
        out[~self._crowd(rows)] = np.nan
        return out

    def state(self) -> dict:
        return {"share": self.weight}


class Nudge(Recipe):
    def __init__(self, share: float) -> None:
        self.share = share
        self.name = f"Plain nudge, {share:.0%}"
        self.about = (f"The line moved {share:.0%} of the way to the models' middle and nothing else - no lean "
                      "taken out, no allowance for disagreement.")

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        out = np.array(rows["market"] + self.share * rows["gap"], dtype=float)
        out[~self._crowd(rows)] = np.nan
        return out

    def state(self) -> dict:
        return {"share": self.share}


# ---- regressions on what the line got wrong ------------------------------------------------------
class Linear(Recipe):
    """The line, plus a regression's guess at how wrong it is.

    The target is the result less the line. Each input is put on one scale
    using the games taught on; an input missing for a game is given the
    middle value of the games taught on, and how often that happened is
    counted (`filled`). The weights are pulled toward nothing - toward "the
    line was right" - by `pull` times the games taught on, and `pull` is the
    most cautious one the seasons before cannot tell from the best.
    """

    def __init__(self, name: str, about: str, inputs: tuple[str, ...], *, constant: bool = True,
                 pulls: tuple[float, ...] = PULLS, by_model: bool = False) -> None:
        self.name, self.about = name, about
        self.inputs, self.constant, self.pulls, self.by_model = tuple(inputs), constant, tuple(pulls), by_model
        self.pull = DEFAULT_PULL if len(self.pulls) > 1 else self.pulls[0]
        self.used: list[str] = []
        self.middle = self.spread = self.weights = None
        self.base, self.taught, self.filled = 0.0, 0, {}

    # -- the inputs, as a table
    def _columns(self, taught: pd.DataFrame) -> list[str]:
        used = []
        for column in self.inputs:
            if column in taught.columns:
                values = taught[column].to_numpy(dtype=float)
                there = ~np.isnan(values)
                if there.mean() >= MIN_COVER and values[there].std() > 1e-9:
                    used.append(column)
        named = features.named_models(taught) if self.by_model else []
        if named:
            cover = taught[named].notna().to_numpy().mean(axis=0)
            used += [column for column, share in zip(named, cover) if share >= MODEL_COVER]
        return used

    def _table(self, rows: pd.DataFrame, used: list[str]) -> np.ndarray:
        """One row a game. A model's column is its own view less the crowd's
        middle, so a model that did not price a game adds nothing (nan here,
        then the middle of the games taught on, which is close to none)."""
        cells = []
        for column in used:
            values = (rows[column].to_numpy(dtype=float) if column in rows.columns
                      else np.full(len(rows), np.nan))
            if column.startswith(MODEL):
                values = values - rows["middle"].to_numpy(dtype=float)
            cells.append(values)
        return np.column_stack(cells) if cells else np.empty((len(rows), 0))

    def _usable(self, taught: pd.DataFrame) -> pd.DataFrame:
        keep = taught["target"].notna()
        if self.wants_models:
            keep &= taught["n_models"] >= features.ENOUGH_MODELS
        return taught[keep]

    def _solve(self, taught: pd.DataFrame, pull: float):
        used = self._columns(taught)
        table = self._table(taught, used)
        target = taught["target"].to_numpy(dtype=float)
        middle = np.nanmedian(table, axis=0) if table.size else np.empty(0)
        table = np.where(np.isnan(table), middle, table)
        mean, spread = table.mean(axis=0), table.std(axis=0)
        spread[spread < 1e-9] = 1.0
        scaled = (table - mean) / spread
        base = float(target.mean()) if self.constant else 0.0
        if not self.constant:
            scaled = table / spread                 # through the origin: no gap, no correction
            mean = np.zeros_like(mean)
        weights = np.linalg.solve(scaled.T @ scaled + pull * len(target) * np.eye(scaled.shape[1]),
                                  scaled.T @ (target - base)) if scaled.shape[1] else np.empty(0)
        return used, middle, mean, spread, weights, base

    def _apply(self, rows: pd.DataFrame, solved, count: bool = False) -> np.ndarray:
        used, middle, mean, spread, weights, base = solved
        table = self._table(rows, used)
        missing = np.isnan(table)
        if count:
            for column, gaps in zip(used, missing.sum(axis=0)):
                if gaps:
                    self.filled[column] = self.filled.get(column, 0) + int(gaps)
        table = np.where(missing, middle, table)
        return base + ((table - mean) / spread) @ weights if len(used) else np.full(len(rows), base)

    # -- chosen on the past, taught on the past
    def tune(self, taught: pd.DataFrame) -> None:
        rows = self._usable(taught)
        if len(self.pulls) < 2:
            return
        tried = _seasons_to_try(rows)
        if not tried:
            self.pull = DEFAULT_PULL
            return
        losses = {pull: [] for pull in self.pulls}
        for season in tried:
            before, asked = rows[rows["season"] < season], rows[rows["season"] == season]
            answers = asked["target"].to_numpy(dtype=float)
            for pull in self.pulls:
                losses[pull].append((self._apply(asked, self._solve(before, pull)) - answers) ** 2)
        self.pull = _closest({pull: np.concatenate(parts) for pull, parts in losses.items()},
                             sorted(self.pulls, reverse=True))

    def fit(self, taught: pd.DataFrame) -> None:
        rows = self._usable(taught)
        self.taught = len(rows)
        if self.taught < MIN_TAUGHT:
            self.weights = None
            return
        self._solved = self._solve(rows, self.pull)
        self.used, self.middle, _, self.spread, self.weights, self.base = self._solved

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        if self.weights is None:
            return np.full(len(rows), np.nan)
        out = rows["market"].to_numpy(dtype=float) + self._apply(rows, self._solved, count=True)
        if self.wants_models:
            out[~self._crowd(rows)] = np.nan
        return out

    def state(self) -> dict:
        if self.weights is None:
            return {"taught": self.taught}
        # each weight as points of correction for one point (or one unit) of its input
        per_unit = {c: float(w / s) for c, w, s in zip(self.used, self.weights, self.spread)}
        return {"taught": self.taught, "pull": self.pull, "constant": self.base, "per unit": per_unit}

    def saved(self) -> dict:
        """Everything needed to price a game again, as plain numbers (registry.py)."""
        if self.weights is None:
            return {}
        used, middle, mean, spread, weights, base = self._solved
        return {"inputs": list(used), "middle": middle.tolist(), "mean": mean.tolist(), "spread": spread.tolist(),
                "weights": weights.tolist(), "constant": base, "pull": self.pull, "taught": self.taught,
                "wants_models": self.wants_models}


def ridge(by_model: bool = False) -> Linear:
    if by_model:
        return Linear("Ridge, model by model",
                      "The ridge regression below, given each computer model's own view as well - how far that "
                      "model sits from the crowd's middle - so it can learn to listen to some more than others.",
                      features.CORE, by_model=True)
    return Linear("Ridge on the line's error",
                  "A regression on what the line got wrong: from the models' net gap, the slate's lean, how far "
                  "apart the models are, how many there are, how far the line has moved and the line itself. Its "
                  "weights are pulled toward nothing, by as much as the seasons before cannot tell from the best.",
                  features.CORE)


def trained_nudge() -> Linear:
    return Linear("Trained nudge",
                  "One number: how much of the models' gap to believe, fitted to every game before and pulled "
                  "toward none. What the 33% would be if the results had set it.",
                  ("gap",), constant=False)


def straight_line() -> Linear:
    return Linear("Straight-line fit",
                  "The plainest regression: the line's error against the models' gap and a constant, with no pull "
                  "toward anything.",
                  ("gap",), pulls=(0.0,))


def market_extras() -> Linear:
    made = Linear("Ridge on the line's own numbers",
                  "No computer models: what the moneyline, the over/under, rest and the line itself say about the "
                  "line's error. A check on whether the closing numbers leave anything on the table.",
                  ("market",) + features.EXTRAS)
    made.wants_models, made.kind = False, MARKET
    return made


# ---- the models weighted by their own records -----------------------------------------------------
class Weighted(Recipe):
    """The line, moved toward a crowd in which the better models count for more.

    A model's weight going into a season is set by its record over its last
    few seasons - its squared miss against the line's on the very games it
    priced - and by nothing from that season on, so every game's weighted
    middle is one that could have been worked out before it was played. How
    sharply to lean on the better models, and how much of the weighted gap
    to believe, are both chosen on the games before.
    """

    name = "Weighted crowd"
    about = ("The line moved toward the models' average, each model weighted by how it has done against the line "
             "over its last three seasons. How hard to lean on the better ones, and how far to move, are fitted "
             "to the games before.")

    def __init__(self) -> None:
        self.power = 0.0
        # how much of the weighted gap to believe: one number, chosen and pulled as the trained nudge's is
        self.share = Linear("", "", ("weighted_gap",), constant=False)
        self._forms: dict[int, dict[str, float]] = {}
        self._all, self._stamp = pd.DataFrame(), None

    def _form(self, everything: pd.DataFrame, season: int) -> dict[str, float]:
        """Each model's squared miss over the line's, on its own games in the
        few seasons before `season` (under 1 is better than the line)."""
        if season not in self._forms:
            before = everything[(everything["season"] < season) & (everything["season"] >= season - FORM_SEASONS)
                                & everything["target"].notna()]
            form = {}
            if len(before):
                actual, market = before["actual"].to_numpy(dtype=float), before["market"].to_numpy(dtype=float)
                for column in features.named_models(before):
                    said = before[column].to_numpy(dtype=float)
                    mine = ~np.isnan(said)
                    if mine.sum() >= FORM_GAMES:
                        line_miss = float(((market[mine] - actual[mine]) ** 2).mean())
                        form[column] = float(((said[mine] - actual[mine]) ** 2).mean()) / max(line_miss, 1e-9)
            self._forms[season] = form
        return self._forms[season]

    def _gaps(self, rows: pd.DataFrame, power: float) -> np.ndarray:
        """Each game's weighted middle less the line. `self._all` holds every
        game seen so far, and each game is weighted by the seasons before its own."""
        out = np.full(len(rows), np.nan)
        columns = features.named_models(rows)
        if not columns:
            return out
        place = {index: i for i, index in enumerate(rows.index)}
        for season, mine in rows.groupby("season"):
            form = self._form(self._all, int(season))
            weights = np.array([form.get(c, 1.0) ** -power for c in columns])
            said = mine[columns].to_numpy(dtype=float)
            there = ~np.isnan(said)
            total = (there * weights).sum(axis=1)
            middle = np.where(total > 0, (np.where(there, said, 0.0) * weights).sum(axis=1) / np.maximum(total, 1e-12),
                              np.nan)
            out[[place[i] for i in mine.index]] = middle - mine["market"].to_numpy(dtype=float)
        return out

    def _remember(self, taught: pd.DataFrame) -> pd.DataFrame:
        stamp = (len(taught), int(taught["order"].max()) if len(taught) else 0)
        if stamp != self._stamp:
            self._all, self._stamp = taught, stamp
        return taught[taught["target"].notna() & (taught["n_models"] >= features.ENOUGH_MODELS)]

    def _with_gap(self, rows: pd.DataFrame) -> pd.DataFrame:
        return rows.assign(weighted_gap=self._gaps(rows, self.power))

    def tune(self, taught: pd.DataFrame) -> None:
        rows = self._remember(taught)
        if len(rows) < MIN_TAUGHT:
            self.power = 0.0
            return
        target = rows["target"].to_numpy(dtype=float)
        losses = {}
        for power in POWERS:
            gap = self._gaps(rows, power)
            ok = ~np.isnan(gap)
            slope = float((gap[ok] * target[ok]).sum() / max((gap[ok] ** 2).sum(), 1e-9))
            losses[power] = np.where(ok, (target - slope * np.nan_to_num(gap)) ** 2, target ** 2)
        self.power = _closest(losses, list(POWERS))
        self.share.tune(self._with_gap(rows))

    def fit(self, taught: pd.DataFrame) -> None:
        self.share.fit(self._with_gap(self._remember(taught)))

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        return self.share.predict(self._with_gap(rows))

    def state(self) -> dict:
        form = self._forms.get(max(self._forms, default=0), {})
        ranked = sorted(form, key=form.get)
        return {**self.share.state(), "power": self.power, "models with a record": len(form),
                "closest to the results": [c[len(MODEL):] for c in ranked[:5]]}


# ---- trees, when there are games enough ----------------------------------------------------------
class Trees(Recipe):
    name = "Trees on the line's error"
    about = ("Gradient-boosted trees (the Machine's own, contenders.boost) on the same inputs as the ridge. Taught "
             f"once a season, and only with {MIN_TREES:,} games or more to learn from.")
    refit = "season"

    def __init__(self, inputs: tuple[str, ...] = features.CORE) -> None:
        self.inputs, self.made, self.taught = tuple(inputs), None, 0

    def fit(self, taught: pd.DataFrame) -> None:
        rows = taught[taught["target"].notna() & (taught["n_models"] >= features.ENOUGH_MODELS)]
        self.taught = len(rows)
        if self.taught < MIN_TREES:
            self.made = None
            return
        used = [c for c in self.inputs if rows[c].notna().mean() >= MIN_COVER]
        table = rows[used].to_numpy(dtype=float)
        middle = np.nanmedian(table, axis=0)
        table = np.where(np.isnan(table), middle, table)
        start, trees = contenders.boost(table, rows["target"].to_numpy(dtype=float))
        self.made = (used, middle, start, trees)

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        if self.made is None:
            return np.full(len(rows), np.nan)
        used, middle, start, trees = self.made
        table = rows[used].to_numpy(dtype=float)
        table = np.where(np.isnan(table), middle, table)
        out = rows["market"].to_numpy(dtype=float) + start
        if len(table):
            out = out + contenders.LEARNING_RATE * sum(contenders._leaves(tree, table) for tree in trees)
        out[~self._crowd(rows)] = np.nan
        return out

    def state(self) -> dict:
        return {"taught": self.taught, "grown": self.made is not None}


# ---- the line-ups ---------------------------------------------------------------------------------
def with_models(*, trees: bool = True) -> list[Recipe]:
    """Every recipe for a table that has the computer models game by game."""
    slates = Slates()
    made: list[Recipe] = [Line(), Deadeye(slates=slates)]
    made += [Deadeye(share, slates=slates) for share in SHARES if abs(share - predictions.CONSENSUS_WEIGHT) > 1e-9]
    made += [DeadeyeChosen(slates), trained_nudge(), ridge(), ridge(by_model=True), Weighted(), straight_line()]
    made += [Nudge(share) for share in SHARES]
    if trees:
        made.append(Trees())
    return made


def without_models() -> list[Recipe]:
    """What can be asked of a table with lines and results and no models."""
    return [Line(), market_extras()]


#: The five the comparison is headed by, in the order they are shown.
HEADLINE = (LINE, f"{MODEL_NAME} at {predictions.CONSENSUS_WEIGHT:.0%}", "Ridge on the line's error",
            "Weighted crowd", "Trained nudge", "Straight-line fit")
#: The ones that make up the test of the 33%.
NUDGE_TEST = (LINE, *(f"{MODEL_NAME} at {s:.0%}" for s in SHARES), f"{MODEL_NAME}, share chosen on the past",
              "Trained nudge")
