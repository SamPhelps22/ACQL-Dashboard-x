"""The training ground's weekly answer, read off disk for the Model Lab.

The training ground is a package apart: it teaches challengers on past
seasons, walks them forward, and once a week writes down one plain answer -
is any of them clearly better than the rule in use? The dashboard never
imports it and never runs it. All this does is read the file it leaves
(data/training/latest/verdict.json) and lay it out as rows.

A missing, damaged or half-written file is no answer, never an error.
Nothing here changes a pick. No Qt here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from ..store import data_dir

WHERE = ("training", "latest", "verdict.json")
#: Older than this, the answer is shown as stale: the weekly job has not run.
STALE_S = 9 * 86400
HEADERS = ["Challenger", "Past seasons", "Could be from", "Newest seasons", "This season", "Weeks ahead",
           "Reading"]


@dataclass
class Answer:
    call: str = ""
    in_use: str = ""
    best: str | None = None
    made: float = 0.0
    games: int = 0
    seasons: tuple[int, ...] = ()
    held_back: tuple[int, ...] = ()
    now_games: int = 0
    problems: int = 0
    sealed: bool | None = None
    rows: list[list] = field(default_factory=list)
    cases: set[int] = field(default_factory=set)        # rows whose challenger has a case
    behind: set[int] = field(default_factory=set)       # rows clearly worse than the rule in use

    def stale(self, now: float | None = None) -> bool:
        return (time.time() if now is None else now) - self.made > STALE_S


def _signed(value, none: str = "-") -> str:
    return none if value is None else f"{value:+.4f}"


def read(path=None) -> Answer | None:
    """The newest answer on disk, or None."""
    try:
        found = json.loads((path or data_dir().joinpath(*WHERE)).read_text(encoding="utf-8"))
        archive, now = found["archive"], found["this_season"]
        out = Answer(call=str(found["call"]), in_use=str(found.get("in_use", "")), best=found.get("best"),
                     made=float(found.get("made", 0.0)), games=int(archive.get("games", 0)),
                     seasons=tuple(archive.get("seasons", ())), held_back=tuple(archive.get("held_back", ())),
                     now_games=int(now.get("games", 0)), problems=int(found.get("problems", 0)),
                     sealed=found.get("sealed"))
        mine = now.get("challengers", {})
        for name, row in archive.get("challengers", {}).items():
            whole, late, this = row["all"], row.get("held_back"), mine.get(name)
            clear = whole.get("low") is not None and whole["low"] > 0
            if clear and (late is None or (late.get("edge") or 0.0) >= 0):
                out.cases.add(len(out.rows))
                reading = "has a case - worth a look"
            elif whole.get("high") is not None and whole["high"] < 0:
                out.behind.add(len(out.rows))
                reading = "clearly worse"
            elif clear:
                reading = "ahead, but not on the seasons held back"
            else:
                reading = "cannot be told apart"
            out.rows.append([
                name, _signed(whole.get("edge")),
                "-" if whole.get("low") is None else f"{whole['low']:+.4f} to {whole['high']:+.4f}",
                "-" if not late or not late.get("games") else f"{_signed(late.get('edge'))} on {late['games']}",
                "-" if not this or not this.get("games") else f"{_signed(this.get('edge'))} on {this['games']}",
                "-" if not this or not this.get("weeks") else f"{this['ahead']} of {this['weeks']}",
                reading])
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
