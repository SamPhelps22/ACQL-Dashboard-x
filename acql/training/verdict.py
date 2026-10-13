"""The week's answer in one place: is any challenger clearly better than the rule in use?

A run finds a great deal; the report says all of it. This says one thing,
as plain data the Model Lab can show without knowing anything about this
package (it reads the file, it never imports from here):

    the archive     every challenger against the rule in use over the walked-
                    forward seasons, and over the seasons held back to the end
    this season     the same, on the dashboard's own records as they stood at
                    each deadline - and how many of the weeks it came out ahead
    the call        one sentence. A challenger "has a case" only when the whole
                    range of its lead over the archive is above zero and it
                    is not behind on the held-back seasons. A case is a reason
                    to look, never a switch: nothing here changes a pick, and
                    the Model Lab's own rule for a switch is untouched.

No Qt here.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from ..model import modellab, predictions
from ..version import MODEL_NAME
from . import VERSION, data, evaluate, recipes
from .study import Season, Study, Trial

FILE = "verdict.json"
IN_USE = f"{MODEL_NAME} at {predictions.CONSENSUS_WEIGHT:.0%}"
#: The challengers worth a line of their own, in the order they are shown.
SHOWN = (recipes.LINE, "Ridge on the line's error", "Ridge, model by model", "Weighted crowd", "Trained nudge",
         f"{MODEL_NAME}, share chosen on the past")


def _number(value) -> float | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def _duel(found: evaluate.Duel) -> dict:
    return {"games": found.games, "edge": _number(found.edge), "low": _number(found.low),
            "high": _number(found.high), "right": found.first_right, "in_use_right": found.second_right,
            "reading": found.reading}


def _weeks(season: Season, name: str) -> dict:
    """Week by week this season: how many weeks the challenger's chances were
    the better ones, and how many of the latest in a row."""
    keep = season.keep
    came = season.games["credited"].to_numpy(dtype=float)[keep]
    weeks = season.games["order"].to_numpy()[keep]
    gain = evaluate.losses(season.chances[IN_USE][keep], came) - evaluate.losses(season.chances[name][keep], came)
    by_week = [float(gain[weeks == week].sum()) for week in sorted(set(weeks.tolist()))]
    ahead = [g > 1e-12 for g in by_week]
    run = 0
    for won in reversed(ahead):
        if not won:
            break
        run += 1
    return {"weeks": len(by_week), "ahead": int(sum(ahead)), "level": int(sum(abs(g) <= 1e-12 for g in by_week)),
            "latest_in_a_row": run}


def _archive(head: Trial) -> tuple[dict, dict]:
    seasons = head.result.seasons
    held = list(head.result.held_back())
    about = {"setting": head.result.setting.title, "games": int(head.keep.sum()),
             "seasons": [int(seasons[0]), int(seasons[-1])] if seasons else [], "held_back": [int(s) for s in held]}
    rows = {}
    for name in SHOWN:
        if name not in head.together or name == IN_USE:
            continue
        rows[name] = {"all": _duel(head.against(name, IN_USE))}
        if held:
            rows[name]["held_back"] = _duel(head.against(name, IN_USE, head.within(held)))
    return about, rows


def _this_season(study: Study) -> tuple[dict, dict]:
    season = next((s for s in study.seasons if IN_USE in s.margins), None)
    if season is None or not season.keep.any():
        return {}, {}
    about = {"setting": season.title, "games": int(season.keep.sum()),
             "season": int(season.games["season"].max())}
    rows = {}
    for name in season.margins:
        if name == IN_USE or (name not in SHOWN and not name.startswith(MODEL_NAME)):
            continue
        if np.isnan(season.margins[name][season.keep]).any():
            continue
        rows[name] = {**_duel(season.against(name, IN_USE)), **_weeks(season, name)}
    return about, rows


def has_a_case(row: dict) -> bool:
    whole, late = row.get("all", {}), row.get("held_back")
    clear = whole.get("low") is not None and whole["low"] > 0
    return bool(clear and (late is None or (late.get("edge") or 0.0) >= 0))


def _call(archive: dict, now: dict, now_about: dict) -> tuple[str, str | None]:
    if not archive:
        return ("The season archives are not on disk, so no challenger could be tested against "
                f"{MODEL_NAME}'s rule."), None
    cases = [name for name, row in archive.items() if has_a_case(row)]
    if not cases:
        behind = [name for name, row in archive.items()
                  if row["all"].get("high") is not None and row["all"]["high"] < 0]
        tail = (f" {len(behind)} of the {len(archive)} tried are clearly worse." if behind else
                " None is clearly worse either: they cannot be told apart.")
        return f"No challenger is clearly better than {MODEL_NAME}'s rule. Nothing to change." + tail, None
    best = max(cases, key=lambda name: archive[name]["all"]["edge"] or 0.0)
    whole = archive[best]["all"]
    said = (f"{best} has been better than {MODEL_NAME}'s rule over {whole['games']:,} archived games, and the "
            "whole range of its lead is above zero.")
    mine = now.get(best)
    if mine and mine["games"]:
        lean = "ahead" if (mine["edge"] or 0) > 0 else "behind" if (mine["edge"] or 0) < 0 else "level"
        said += (f" This season it is {lean} on {mine['games']} games, ahead in {mine['ahead']} of "
                 f"{mine['weeks']} weeks.")
    said += (f" That is a reason to look, not a switch: the Model Lab's rule ({modellab.ENOUGH_GAMES} games "
             "priced live) still stands, and the choice is yours.")
    return said, best


def reach(study: Study, now: float | None = None) -> dict:
    """What a run says about the challengers, as plain data."""
    head = study.headline
    about, archive = _archive(head) if head is not None and IN_USE in head.together else ({}, {})
    now_about, this = _this_season(study)
    call, best = _call(archive, this, now_about)
    return {"training": VERSION, "made": time.time() if now is None else now, "took": study.took,
            "in_use": IN_USE, "call": call, "best": best,
            "problems": len(study.notes.of("error")),
            "sealed": all(ok for _, _, ok, _ in study.seals) if study.seals else None,
            "archive": {**about, "challengers": archive},
            "this_season": {**now_about, "challengers": this}}


def write(study: Study, folder: Path) -> Path:
    path = Path(folder) / FILE
    path.write_text(json.dumps(reach(study), indent=1), encoding="utf-8")
    return path


def latest() -> dict | None:
    """The newest verdict on disk, or None."""
    try:
        found = json.loads((data.folder() / "latest" / FILE).read_text(encoding="utf-8"))
        return found if isinstance(found, dict) and "call" in found else None
    except (OSError, ValueError):
        return None
