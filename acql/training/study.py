"""One whole training run: every experiment, in order, on what is on disk.

    the comparison      every recipe walked forward over the season archives,
                        against each line the archive has (as last updated,
                        as it opened, midweek where kept)
    the curve           the margin-to-chance step in use against ones fitted
                        to results, season by season
    Big Losers          the chance of a 15-point beating, taught on the
                        seasons before, read off each recipe's margin
    this season         the same recipes on the dashboard's own records - the
                        only games whose lines carry a time
    sealed              the check that no result could have leaked backwards

Each part stands on its own: one that cannot run (no archives, no nflverse
files, a database that cannot be read) is left out and said, and the rest go
ahead. Nothing here writes anywhere but data/training, and the dashboard's
database is read from a copy.

No Qt here.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import analytics
from ..version import MODEL_NAME
from . import data, evaluate, features, probability, recipes, walkforward
from .data import Notes
from .walkforward import Result

log = logging.getLogger("acql.training")

#: Games with a crowd of models before a table is worth walking forward at all.
MIN_GAMES = 1500
#: The settings tried when the archives are there, the headline first.
WITH_MODELS = ("updated", "opening", "midweek")
LIVE = f"{MODEL_NAME} as it ran"


# ---- the dashboard's own books, read from a copy ------------------------------------------------
@contextmanager
def books():
    """Point the app's store at a copy of its database for as long as this
    lasts. Pricing a week notes things down; on a copy that is nobody's
    business but this run's, and the dashboard can be open the whole time."""
    from .. import store
    live = store.db_path()
    work = data.folder() / "work"
    copy = work / f"acql-{os.getpid()}.db"
    work.mkdir(parents=True, exist_ok=True)
    if not live.is_file():
        raise FileNotFoundError(f"{live} is not there")
    source = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(copy))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    store.use(copy)
    try:
        yield copy
    finally:
        store.use(None)
        shutil.rmtree(work, ignore_errors=True)


def load_books(notes: Notes, frozen: bool = True) -> pd.DataFrame:
    """This season as the dashboard kept it (data.this_season), or an empty
    table and a note saying why not. Games frozen before their deadline
    (snapshots.py) have their numbers put back as they stood then."""
    try:
        with books():
            from ..config import Settings
            from ..names import AliasTable
            from ..repository import load_season
            season = load_season(Settings.load(), AliasTable.load(), online=False)
            if season.is_empty:
                notes.note("books", "the dashboard has no season loaded - this season's own records were left out")
                return pd.DataFrame()
            rows = data.this_season(season, notes)
            if frozen and not rows.empty:
                from . import snapshots
                rows = snapshots.overlay(rows)
                held = int(rows["frozen_at"].notna().sum()) if "frozen_at" in rows.columns else 0
                if held:
                    notes.note("frozen", "games whose numbers were frozen before the pool's deadline are read "
                                         "from the snapshot, not from what the dashboard holds now", held)
            return data.check(rows, notes)
    except Exception as exc:  # noqa: BLE001 - the long record stands without this season's books
        log.exception("this season's books could not be read")
        notes.error("books", f"this season's own records could not be read ({type(exc).__name__}: {exc}) - left out")
        return pd.DataFrame()


# ---- one walk-forward, marked ---------------------------------------------------------------------
def chances_for(result: Result, layer: probability.Layer | None = None) -> dict[str, np.ndarray]:
    """Each recipe's chance the home side is credited, by the curve in use."""
    layer = layer or probability.Layer(probability.InUse())
    games = result.games
    line, favourite = games["pool_line"].to_numpy(dtype=float), games["pool_favourite"].tolist()
    return {name: layer.chance(margins, line, favourite) for name, margins in result.margins.items()}


@dataclass
class Trial:
    """A walk-forward with every recipe's chances worked out."""

    result: Result
    chances: dict[str, np.ndarray]
    prepared: pd.DataFrame
    _emerged: dict = field(default_factory=dict, repr=False)

    @property
    def names(self) -> list[str]:
        """Recipes that priced anything, in line-up order."""
        return [r.name for r in self.result.recipes if not np.isnan(self.result.margins[r.name]).all()]

    @property
    def together(self) -> list[str]:
        """The recipes compared on one set of games - all but those grown late (trees)."""
        return [r.name for r in self.result.recipes if r.name in self.names and r.refit == "week"]

    @property
    def keep(self) -> np.ndarray:
        return self.result.common(self.together)

    def within(self, seasons) -> np.ndarray:
        return self.keep & np.isin(self.result.games["season"].to_numpy(), list(seasons))

    def marks(self, keep: np.ndarray | None = None, names=None) -> dict[str, evaluate.Score]:
        return evaluate.marks(self.result, self.chances, list(names or self.together),
                              self.keep if keep is None else keep)

    def against(self, name: str, other: str = recipes.LINE, keep: np.ndarray | None = None) -> evaluate.Duel:
        return evaluate.against(self.result, self.chances, name, other, self.keep if keep is None else keep)

    def emerged(self, seasons=None) -> str | None:
        """The challenger that has earned a second look: the one furthest
        ahead of the line on these seasons among those whose whole range is
        above zero. None when no lead is clear of zero - which is a finding,
        not a failure."""
        key = tuple(sorted(seasons)) if seasons else ()
        if key not in self._emerged:
            keep = self.within(seasons) if seasons else self.keep
            leads = {}
            for name in self.together:
                if name != recipes.LINE:
                    found = self.against(name, recipes.LINE, keep)
                    if found.games and found.low > 0:
                        leads[name] = found.edge
            self._emerged[key] = max(leads, key=leads.get) if leads else None
        return self._emerged[key]


def _screen(prepared: pd.DataFrame, setting: features.Setting, notes: Notes) -> None:
    """Say so, loudly, if an input looks as though it has seen the result."""
    for column, r in features.suspects(prepared):
        notes.error("leak", f"{setting.title}: {column} goes with the line's error at {r:+.2f} - no forecast does. "
                            "It has seen the result; nothing built on it here can be believed.")


def trial(table: pd.DataFrame, key: str, notes: Notes, *, trees: bool = True, progress=None) -> Trial | None:
    setting = features.SETTINGS[key]
    prepared = features.prepare(table, setting, notes)
    if prepared.empty:
        return None
    crowded = int((prepared["n_models"] >= features.ENOUGH_MODELS).sum())
    if crowded < MIN_GAMES:
        notes.note("too few", f"{setting.title}: {crowded} games with a crowd of models - under the {MIN_GAMES:,} "
                              "a walk-forward needs, so it was not run")
        return None
    log.info("%s: %d games, %d with a crowd of models", setting.title, len(prepared), crowded)
    _screen(prepared, setting, notes)
    result = walkforward.run(prepared, setting, recipes.with_models(trees=trees), progress=progress)
    return Trial(result, chances_for(result), prepared)


# ---- the curve ------------------------------------------------------------------------------------
@dataclass
class Curves:
    games: pd.DataFrame
    chances: dict[str, np.ndarray]
    about: dict[str, str]
    states: dict[str, dict]
    setting: features.Setting

    def keep(self, which: str = "all") -> np.ndarray:
        out = np.array(self.games["credited"].notna(), dtype=bool)
        for said in self.chances.values():
            out &= ~np.isnan(said)
        lined = np.array(self.games["pool_line"].notna(), dtype=bool)
        return out & lined if which == "lined" else out & ~lined if which == "straight" else out

    def score(self, name: str, which: str = "all") -> evaluate.Score:
        keep = self.keep(which)
        return evaluate.score(self.chances[name][keep], self.games["credited"].to_numpy(dtype=float)[keep])

    def against(self, name: str, which: str = "all", other: str = "In use") -> evaluate.Duel:
        keep = self.keep(which)
        return evaluate.duel(self.chances[name][keep], self.chances[other][keep],
                             self.games["credited"].to_numpy(dtype=float)[keep],
                             self.games["order"].to_numpy()[keep])


def curves(table: pd.DataFrame, key: str, notes: Notes, *, warm_up: int = walkforward.WARM_UP,
           progress=None) -> Curves | None:
    """Each way of turning a margin into a chance, taught on the seasons
    before and marked on the market's own margin - so only the curve differs."""
    setting = features.SETTINGS[key]
    prepared = features.prepare(table, setting, Notes())
    if prepared.empty or prepared["season"].nunique() <= warm_up:
        notes.note("curve", f"the curve could not be tested {setting.title.lower()}: too few seasons")
        return None
    games = prepared.sort_values(["order", "game"], kind="stable").reset_index(drop=True)
    made = probability.layers()
    said = {layer.name: np.full(len(games), np.nan) for layer in made}
    season_of = games["season"].to_numpy()
    seasons = sorted(set(season_of.tolist()))[warm_up:]
    for count, season in enumerate(seasons):
        before, now = games[season_of < season], np.flatnonzero(season_of == season)
        asked = games.iloc[now]
        for layer in made:
            layer.fit(before["market"].to_numpy(dtype=float), before["actual"].to_numpy(dtype=float),
                      before["pool_line"].to_numpy(dtype=float), before["pool_favourite"].tolist())
            said[layer.name][now] = layer.chance(asked["market"].to_numpy(dtype=float),
                                                 asked["pool_line"].to_numpy(dtype=float),
                                                 asked["pool_favourite"].tolist())
        if progress:
            progress(count + 1, len(seasons))
    return Curves(games, said, {layer.name: layer.about for layer in made},
                  {layer.name: layer.state() for layer in made}, setting)


# ---- Big Losers -----------------------------------------------------------------------------------
BAR = analytics.BIG_LOSER_MARGIN + 1
PICKS = 3


@dataclass
class Routs:
    rows: list[dict] = field(default_factory=list)      # one a source: its record at calling 15-point beatings
    games: int = 0
    weeks: int = 0
    setting: str = ""


def routs(games: pd.DataFrame, margins: dict[str, np.ndarray], keep: np.ndarray, setting: str, *,
          warm_up: int = walkforward.WARM_UP) -> Routs | None:
    """How well each margin calls a 15-point beating, both teams of every game.

    The chance is read off the dashboard's own Big Loser curve
    (analytics.rout_chance), but with its weights taught again as each season
    begins, on the seasons before it and the market's margins - so the
    curve never saw the games it is marked on. The weights the dashboard
    carries were taught on every season to 2025, which makes "as in use"
    flattered on those seasons; it is shown beside the others for scale.
    """
    actual = games["actual"].to_numpy(dtype=float)
    market = games["market"].to_numpy(dtype=float)
    season_of, order = games["season"].to_numpy(), games["order"].to_numpy()
    known = ~np.isnan(actual) & ~np.isnan(market)
    seasons = sorted(set(season_of[keep & known].tolist()))
    first = sorted(set(season_of[known].tolist()))[warm_up:][:1]
    seasons = [s for s in seasons if first and s >= first[0]]
    if not seasons:
        return None
    said: dict[str, list] = {name: [] for name in list(margins) + ["The line, weights as in use"]}
    lost, week_of, team_game = [], [], []
    for season in seasons:
        before = known & (season_of < season)
        weights = analytics.rout_fit(np.concatenate([market[before], -market[before]]),
                                     np.concatenate([actual[before] <= -BAR, actual[before] >= BAR]))
        now = np.flatnonzero(keep & known & (season_of == season))
        if not len(now):
            continue
        lost.append(np.concatenate([actual[now] <= -BAR, actual[now] >= BAR]))
        week_of.append(np.concatenate([order[now], order[now]]))
        team_game.append(np.concatenate([now, now]))
        for name, mine in margins.items():
            said[name].append(probability.rout_chances(np.concatenate([mine[now], -mine[now]]), weights))
        said["The line, weights as in use"].append(
            probability.rout_chances(np.concatenate([market[now], -market[now]])))
    if not lost:
        return None
    lost, week_of = np.concatenate(lost).astype(float), np.concatenate(week_of)
    out = Routs(games=len(lost) // 2, weeks=len(set(week_of.tolist())), setting=setting)
    base = None
    for name, parts in said.items():
        chance = np.clip(np.concatenate(parts), 1e-4, 1 - 1e-4)
        loss = -(lost * np.log(chance) + (1 - lost) * np.log(1 - chance))
        points = expected = 0.0
        for week in set(week_of.tolist()):
            inside = np.flatnonzero(week_of == week)
            top = inside[np.argsort(-chance[inside], kind="stable")[:PICKS]]
            points += lost[top].sum()
            expected += chance[top].sum()
        if base is None:
            base = loss
        low, high = evaluate.interval(base - loss, week_of)
        out.rows.append({"source": name, "logloss": float(loss.mean()), "brier": float(((chance - lost) ** 2).mean()),
                         "said": float(chance.mean()), "came": float(lost.mean()),
                         "points": points / out.weeks, "expected": expected / out.weeks,
                         "edge": float((base - loss).mean()), "low": low, "high": high})
    return out


# ---- this season, on the dashboard's own records --------------------------------------------------
@dataclass
class Season:
    title: str
    about: str
    games: pd.DataFrame
    margins: dict[str, np.ndarray]
    chances: dict[str, np.ndarray]
    keep: np.ndarray

    def marks(self) -> dict[str, evaluate.Score]:
        came = self.games["credited"].to_numpy(dtype=float)[self.keep]
        actual = self.games["actual"].to_numpy(dtype=float)[self.keep]
        return {name: evaluate.score(self.chances[name][self.keep], came, self.margins[name][self.keep], actual)
                for name in self.margins}

    def against(self, name: str, other: str = recipes.LINE) -> evaluate.Duel:
        k = self.keep
        return evaluate.duel(self.chances[name][k], self.chances[other][k],
                             self.games["credited"].to_numpy(dtype=float)[k], self.games["order"].to_numpy()[k],
                             self.margins[name][k], self.margins[other][k],
                             self.games["actual"].to_numpy(dtype=float)[k])


def this_season(now: pd.DataFrame, key: str, notes: Notes, taught: list[recipes.Recipe] | None = None) -> Season | None:
    """The recipes that need no teaching, and any taught on earlier seasons,
    over this season's games as the dashboard kept them."""
    setting = features.SETTINGS[key]
    prepared = features.prepare(now, setting, Notes())
    if prepared.empty:
        return None
    games = prepared.sort_values(["order", "game"], kind="stable").reset_index(drop=True)
    asked = features.question(games)
    made: list[recipes.Recipe] = [recipes.Line()] + [recipes.Deadeye(share) for share in recipes.SHARES]
    margins = {recipe.name: recipe.predict(asked) for recipe in made}
    for recipe in taught or []:
        try:
            margins[recipe.name] = recipe.predict(asked)
        except Exception as exc:  # noqa: BLE001 - one recipe that cannot price this season does not stop the rest
            notes.warning("this season", f"{recipe.name} could not price this season's games: {exc}")
    if key == "used" and "deadeye_live" in games.columns:
        margins[LIVE] = games["deadeye_live"].to_numpy(dtype=float)
    layer = probability.Layer(probability.InUse())
    line, favourite = games["pool_line"].to_numpy(dtype=float), games["pool_favourite"].tolist()
    chances = {name: layer.chance(mine, line, favourite) for name, mine in margins.items()}
    # the games every recipe with models priced; the line and the live card are held to the same games
    keep = np.array(games["credited"].notna(), dtype=bool)
    with_models = [n for n in margins if n not in (recipes.LINE, LIVE)]
    wide = keep.copy()
    for name in with_models:
        keep &= ~np.isnan(margins[name])
    if key == "used":                       # the Model Lab's own table: every graded game, the line and the live card
        margins = {n: m for n, m in margins.items() if n in (recipes.LINE, LIVE)}
        chances = {n: chances[n] for n in margins}
        keep = wide & ~np.isnan(margins.get(LIVE, np.full(len(games), np.nan)))
    return Season(setting.title, setting.about, games, margins, chances, keep)


def taught_on(table: pd.DataFrame, key: str, before: int) -> list[recipes.Recipe]:
    """The recipes that learn, taught on every archived season before `before`
    - what would be put to this season's games."""
    prepared = features.prepare(table, features.SETTINGS[key], Notes())
    if prepared.empty:
        return []
    past = prepared[prepared["season"] < before]
    made = [recipes.trained_nudge(), recipes.ridge(), recipes.ridge(by_model=True), recipes.Weighted(),
            recipes.DeadeyeChosen()]
    out = []
    for recipe in made:
        recipe.tune(past)
        recipe.fit(past)
        if not np.isnan(recipe.predict(features.question(past.tail(50)))).all():
            out.append(recipe)
    return out


# ---- how late is the archive? ---------------------------------------------------------------------
def drift(now: pd.DataFrame, history: pd.DataFrame) -> dict | None:
    """This season's games in both places: the dashboard's file as it was read
    in before the deadline, and the archive's row for the same game as it was
    left at the end of the week. How far apart they are is how much later
    than a Thursday card the archive's numbers are."""
    if now.empty or history.empty or "source" not in history.columns:
        return None
    theirs = history[history["source"] == "archive"]
    both = now.merge(theirs, on=["season", "week", "home", "away"], suffixes=("", "_archive"))
    if both.empty:
        return None
    out: dict = {"games": len(both)}
    shared = [c for c in features.named_models(now) if f"{c}_archive" in both.columns]
    gaps, same, count = [], 0, 0
    for column in shared:
        pair = both[[column, f"{column}_archive"]].dropna()
        if len(pair):
            apart = (pair[column] - pair[f"{column}_archive"]).abs()
            gaps.append(float(apart.mean()))
            same += int((apart < 0.05).sum())
            count += len(pair)
    out["models"] = len(shared)
    out["forecasts"] = count
    out["unchanged"] = same / count if count else None
    out["model_gap"] = float(np.mean(gaps)) if gaps else None
    for mine, other, name in (("line_deadline", "line_updated", "line"), ("line_deadline", "line_midweek", "midweek"),
                              ("line_opening", "line_opening_archive", "opening")):
        if mine in both.columns and other in both.columns:
            pair = both[[mine, other]].dropna()
            if len(pair):
                out[f"{name}_games"] = len(pair)
                out[f"{name}_gap"] = float((pair[mine] - pair[other]).abs().mean())
                out[f"{name}_moved"] = int(((pair[mine] - pair[other]).abs() >= 0.5).sum())
    return out


# ---- the whole run --------------------------------------------------------------------------------
@dataclass
class Study:
    notes: Notes
    history: pd.DataFrame
    now: pd.DataFrame
    trials: dict[str, Trial] = field(default_factory=dict)
    lines_only: Trial | None = None             # the closing line and its own numbers - no models
    curves: Curves | None = None
    routs: Routs | None = None
    seasons: list[Season] = field(default_factory=list)
    taught: list[recipes.Recipe] = field(default_factory=list)
    taught_key: str = ""                        # the line the taught recipes learned against...
    taught_before: int = 0                      # ...and the season they had not seen
    drift: dict | None = None
    seals: list[tuple[str, int, bool, str]] = field(default_factory=list)
    started: float = 0.0
    took: float = 0.0

    @property
    def has_models(self) -> bool:
        return bool(self.trials)

    @property
    def headline(self) -> Trial | None:
        return next((self.trials[k] for k in WITH_MODELS if k in self.trials), None)


def run(*, trees: bool = True, seal: bool = True, books_too: bool = True, progress=None) -> Study:
    """Everything, on what is on disk. `progress(what, done, of)` is told how far along it is."""
    started = time.time()
    notes = Notes()

    def tell(what: str):
        return (lambda done, of: progress(what, done, of)) if progress else None

    history = data.check(data.history(notes=notes), notes)
    now = load_books(notes) if books_too else pd.DataFrame()
    study = Study(notes, history, now, started=started)
    if history.empty:
        notes.error("nothing", "no season archives and no nflverse files: there is nothing to learn from. "
                               "See the report for what to fetch.")
    archived = history[history["source"] == "archive"] if "source" in history.columns else history.iloc[0:0]

    # the comparison, against each line the archives have
    for key in WITH_MODELS:
        if archived.empty:
            break
        try:
            found = trial(archived, key, notes, trees=trees, progress=tell(features.SETTINGS[key].title))
        except Exception as exc:  # noqa: BLE001 - one setting failing leaves the others
            log.exception("walk-forward failed: %s", key)
            notes.error("failed", f"{features.SETTINGS[key].title}: the walk-forward failed ({type(exc).__name__}: {exc})")
            continue
        if found is not None:
            study.trials[key] = found

    # the closing line: its own numbers, the curve, the Big Losers
    closing = "closing" if "line_closing" in history.columns and history["line_closing"].notna().any() else None
    if closing:
        try:
            prepared = features.prepare(history, features.SETTINGS[closing], notes)
            _screen(prepared, features.SETTINGS[closing], notes)
            result = walkforward.run(prepared, features.SETTINGS[closing], recipes.without_models(),
                                     progress=tell("The closing line's own numbers"))
            study.lines_only = Trial(result, chances_for(result), prepared)
        except Exception as exc:  # noqa: BLE001
            log.exception("closing-line walk-forward failed")
            notes.error("failed", f"the closing line's own numbers could not be tested ({type(exc).__name__}: {exc})")
    curve_key = closing or next(iter(study.trials), None)
    if curve_key:
        try:
            study.curves = curves(history, curve_key, notes, progress=tell("The curve"))
        except Exception as exc:  # noqa: BLE001
            log.exception("curve study failed")
            notes.error("failed", f"the curve could not be tested ({type(exc).__name__}: {exc})")
    try:
        head = study.headline
        if head is not None:
            names = [n for n in (recipes.LINE, *recipes.HEADLINE[1:]) if n in head.together]
            study.routs = routs(head.result.games, {n: head.result.margins[n] for n in names}, head.keep,
                                head.result.setting.title)
        elif study.lines_only is not None:
            only = study.lines_only
            study.routs = routs(only.result.games, {recipes.LINE: only.result.margins[recipes.LINE]}, only.keep,
                                only.result.setting.title)
    except Exception as exc:  # noqa: BLE001
        log.exception("Big Loser study failed")
        notes.error("failed", f"the Big Loser chances could not be tested ({type(exc).__name__}: {exc})")

    # this season, on the dashboard's own records
    if not now.empty:
        try:
            year = int(now["season"].max())
            head_key = next((k for k in WITH_MODELS if k in study.trials), None)
            study.taught = taught_on(archived, head_key, year) if head_key else []
            study.taught_key, study.taught_before = head_key or "", year
            for key in ("used", "deadline"):
                found = this_season(now, key, notes, study.taught if key == "deadline" else None)
                if found is not None and found.keep.any():
                    study.seasons.append(found)
            study.drift = drift(now, history)
        except Exception as exc:  # noqa: BLE001
            log.exception("this season's study failed")
            notes.error("failed", f"this season's own records could not be scored ({type(exc).__name__}: {exc})")

    # nothing leaked backwards?
    if seal:
        for key, found in list(study.trials.items())[:1] or ([("closing", study.lines_only)] if study.lines_only else []):
            seasons = found.result.seasons
            for season in (seasons[len(seasons) // 3], seasons[-2]) if len(seasons) >= 3 else ():
                cut = season * 100 + 6
                make = (lambda: recipes.with_models(trees=False)) if key != "closing" else recipes.without_models
                try:
                    ok, what = walkforward.sealed(found.prepared, found.result.setting, make, cut)
                except Exception as exc:  # noqa: BLE001
                    ok, what = False, f"the check itself failed ({type(exc).__name__}: {exc})"
                study.seals.append((found.result.setting.title, cut, ok, what))
                if not ok:
                    notes.error("leak", f"{found.result.setting.title}: {what}")
    study.took = time.time() - started
    return study
