"""Every week priced by recipes that had only seen the weeks before it.

Games are never shuffled. The clock is the week: a card for week 9 of 2019
is made with what was known going into it, so every recipe is

    tuned    as each season begins, on the seasons before it (how hard to
             pull a regression toward the line, which share of the models to
             believe)
    taught   as each week begins, on every game of every earlier week
    asked    about that week's games, shown without their results

and what it says is written down against the game. The first few seasons are
only ever taught from - nothing is asked about a season until there is
enough before it to learn on.

Two guards against a recipe seeing what it should not. The games it is asked
about are handed over with the answers taken out (features.question). And
`sealed` runs the whole thing twice - once as it is, once with every result
from some week on scrambled - and checks that nothing said before that week
changed: if a result could leak backwards, it would show.

No Qt here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import features
from .features import Setting
from .recipes import Recipe

#: Seasons that are only taught from, never asked about.
WARM_UP = 3
#: Seasons at the end of the record kept apart: nothing about the recipes was
#: chosen by looking at them, and they are reported on their own.
HELD_BACK = 3


@dataclass
class Result:
    setting: Setting
    games: pd.DataFrame                     # every game of the table, in order, answers and all
    margins: dict[str, np.ndarray]          # recipe -> the home margin it gave each game (nan: not asked, or could not say)
    recipes: list[Recipe] = field(default_factory=list)
    #: what each recipe had settled on as each season began - the settings and
    #: weights that would have been known on that date
    fits: list[dict] = field(default_factory=list)

    def recipe(self, name: str) -> Recipe | None:
        return next((r for r in self.recipes if r.name == name), None)

    @property
    def asked(self) -> np.ndarray:
        """Games any recipe was asked about."""
        out = np.zeros(len(self.games), dtype=bool)
        for margins in self.margins.values():
            out |= ~np.isnan(margins)
        return out

    def common(self, names=None) -> np.ndarray:
        """Games every one of these recipes priced and the pool credited to someone."""
        names = list(names) if names is not None else list(self.margins)
        out = np.array(self.games["credited"].notna(), dtype=bool)
        for name in names:
            out &= ~np.isnan(self.margins[name])
        return out

    @property
    def seasons(self) -> list[int]:
        return sorted(set(self.games.loc[self.asked, "season"].tolist()))

    def held_back(self, count: int = HELD_BACK) -> list[int]:
        """The last few seasons asked about, when there are enough before them to stand apart from."""
        seasons = self.seasons
        return seasons[-count:] if len(seasons) >= 2 * count else []


def run(prepared: pd.DataFrame, setting: Setting, recipes: list[Recipe], *, warm_up: int = WARM_UP,
        weekly: bool = True, until: int | None = None, progress=None) -> Result:
    """Walk the table forward, a week at a time. `until` stops after that
    week of that season (as season * 100 + week), for a check that needs no more."""
    games = prepared.sort_values(["order", "game"], kind="stable").reset_index(drop=True)
    margins = {recipe.name: np.full(len(games), np.nan) for recipe in recipes}
    result = Result(setting, games, margins, list(recipes))
    if games.empty:
        return result
    order = games["order"].to_numpy()
    season_of = games["season"].to_numpy()
    seasons = sorted(set(season_of.tolist()))
    asked_seasons = seasons[warm_up:]
    steps = [int(o) for o in sorted(set(order.tolist())) if o // 100 in set(asked_seasons)]
    if until is not None:
        steps = [o for o in steps if o <= until]
    done = 0
    for season in asked_seasons:
        mine = [o for o in steps if o // 100 == season]
        if not mine:
            continue
        before = games[season_of < season]
        for recipe in recipes:
            recipe.tune(before)
        for count, step in enumerate(mine):
            taught = games[order < step] if weekly else before
            where = np.flatnonzero(order == step)
            asked = features.question(games.iloc[where])
            for recipe in recipes:
                if count == 0 or (weekly and recipe.refit == "week"):
                    recipe.fit(taught)
                margins[recipe.name][where] = recipe.predict(asked)
            if count == 0:
                result.fits += [{"season": int(season), "recipe": recipe.name, **recipe.state()} for recipe in recipes]
            done += 1
            if progress:
                progress(done, len(steps))
    return result


def sealed(prepared: pd.DataFrame, setting: Setting, make_recipes, cut: int, *, warm_up: int = WARM_UP,
           seed: int = 7) -> tuple[bool, str]:
    """Whether anything said up to week `cut` (season * 100 + week) could have
    come from a result at or after it. (sealed, what was found).

    The table is walked to `cut` twice: as it is, and with the results of
    every game from `cut` on shuffled among themselves and every later game's
    inputs scrambled too. A recipe that only looks backwards says exactly the
    same thing both times.
    """
    draw = np.random.default_rng(seed)
    spoiled = prepared.copy()
    later = spoiled["order"].to_numpy() >= cut
    after = spoiled["order"].to_numpy() > cut
    if later.sum() < 2:
        return True, "nothing after that week to scramble"
    for column in features.ANSWERS:
        if column in spoiled.columns:
            values = spoiled.loc[later, column].to_numpy()
            spoiled.loc[later, column] = draw.permutation(values)
    numeric = [c for c in spoiled.columns if c not in features.ANSWERS + ("season", "week", "order")
               and pd.api.types.is_float_dtype(spoiled[c])]
    for column in numeric:
        values = spoiled.loc[after, column].to_numpy()
        spoiled.loc[after, column] = draw.permutation(values)
    clean = run(prepared, setting, make_recipes(), warm_up=warm_up, until=cut)
    dirty = run(spoiled, setting, make_recipes(), warm_up=warm_up, until=cut)
    keep = clean.games["order"].to_numpy() <= cut
    for name, said in clean.margins.items():
        a = said[keep]
        b = dirty.margins[name][dirty.games["order"].to_numpy() <= cut]
        if len(a) != len(b) or not np.allclose(a, b, equal_nan=True, atol=1e-9):
            moved = int((~np.isclose(a, b, equal_nan=True, atol=1e-9)).sum()) if len(a) == len(b) else -1
            return False, f"{name}: {moved} of its margins up to {cut} changed when later results were scrambled"
    asked = int(clean.asked.sum())
    return True, f"{asked} games asked about up to {cut}; none moved when everything after was scrambled"
