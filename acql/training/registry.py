"""Taught challengers, kept apart from the live model.

A recipe taught on the season archives is written to data/training/models as
a plain JSON file: its inputs, the scale each was put on, its weights, how
hard it was pulled toward the line, the last season it was taught on, and
the version of this package that made it. Plain numbers, so it can be read,
compared with the one before, and loaded without running anything.

Nothing in the dashboard reads this folder. `load` is for the day a
challenger is put in the Model Lab to be priced beside Deadeye: it gives back
a recipe that can price games, or None - for a file that is missing, damaged,
made by other rules, or wrong in any way at all. It never raises, so a
challenger that cannot be loaded costs the card nothing.

No Qt here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path

import numpy as np

from ..version import VERSION as APP_VERSION
from . import VERSION, data
from .recipes import Linear, Recipe

log = logging.getLogger("acql.training")

FOLDER_NAME = "models"
STATUS = "experimental - taught and tested, not used for any pick"
NEEDED = ("inputs", "middle", "mean", "spread", "weights", "constant")


def folder() -> Path:
    where = data.folder() / FOLDER_NAME
    where.mkdir(parents=True, exist_ok=True)
    return where


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def path_for(name: str, before: int) -> Path:
    return folder() / f"{_slug(name)}-to-{int(before) - 1}.json"


def save(recipe: Recipe, *, setting: str, before: int, where: Path | None = None) -> Path | None:
    """Keep a taught recipe. Only regressions can be kept (they are plain
    numbers); anything else is passed over, and None comes back."""
    kept = recipe.saved() if isinstance(recipe, Linear) else {}
    if not kept:
        return None
    body = {
        "name": recipe.name, "about": recipe.about, "kind": "linear", "status": STATUS,
        "training": VERSION, "dashboard": APP_VERSION, "made": time.strftime("%Y-%m-%d %H:%M:%S"),
        "setting": setting, "taught_through": int(before) - 1, **kept,
    }
    body["mark"] = hashlib.sha1(json.dumps({k: body[k] for k in NEEDED}, sort_keys=True).encode()).hexdigest()
    target = where or path_for(recipe.name, before)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("could not keep %s: %s", recipe.name, exc)
        return None
    return target


def load(path: str | Path) -> Linear | None:
    """A kept recipe, ready to price games - or None, whatever went wrong."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        if body.get("kind") != "linear" or body.get("training") != VERSION:
            log.warning("%s was made by other rules (%s) - not loaded", path, body.get("training"))
            return None
        mark = hashlib.sha1(json.dumps({k: body[k] for k in NEEDED}, sort_keys=True).encode()).hexdigest()
        if mark != body.get("mark"):
            log.warning("%s has been changed since it was made - not loaded", path)
            return None
        inputs = [str(c) for c in body["inputs"]]
        numbers = [np.array(body[k], dtype=float) for k in ("middle", "mean", "spread", "weights")]
        if any(len(n) != len(inputs) or not np.isfinite(n).all() for n in numbers):
            log.warning("%s does not add up - not loaded", path)
            return None
        made = Linear(str(body["name"]), str(body.get("about", "")), tuple(inputs))
        made.wants_models = bool(body.get("wants_models", True))
        made.pull, made.taught = float(body.get("pull", 0.0)), int(body.get("taught", 0))
        made._solved = (inputs, *numbers, float(body["constant"]))
        made.used, made.middle, _, made.spread, made.weights, made.base = made._solved
        return made
    except Exception as exc:  # noqa: BLE001 - a challenger that cannot be loaded is no challenger, never an error
        log.warning("%s could not be loaded: %s", path, exc)
        return None


def kept() -> list[Path]:
    """Every challenger on disk, newest first."""
    try:
        return sorted(folder().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
