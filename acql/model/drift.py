"""Lines likely to move before the deadline (idea #21).

The training ground's edge-decay study (training/decay.py) measured how
much of the computer models' gap from the line the market goes on to close.
In the latest era it is a large share from the opening line and close to
nothing once the line has moved off it. That study leaves its figures in
data/training/latest/drift.json; this reads them (never the training
package) and, for each game still on its opening line, gives the move to
expect by kickoff - and whether that is enough to turn the pick.

The expectation is an average over thousands of games, not a forecast for
this one: it says which way and roughly how far, with the sample shown.
Nothing here changes a pick. No Qt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..store import data_dir
from . import predictions

WHERE = ("training", "latest", "drift.json")
#: Below this many points of expected move a game isn't listed.
SHOWN = 0.5


@dataclass(frozen=True)
class Drift:
    index: int
    matchup: str
    toward: str                # the side the line is expected to move toward
    points: float              # the expected move, points
    share: float               # the share of the gap the market has closed from this line
    games: int                 # how many games that share was measured on
    pick: str = ""
    turns: bool = False        # the expected move reaches the line where the pick changes


def read(path=None) -> dict | None:
    try:
        found = json.loads((path or data_dir().joinpath(*WHERE)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and isinstance(found.get("from"), dict) else None


def at_opening(forecast) -> bool:
    """The line hasn't moved since it opened (or only the opener is known)."""
    return forecast.opening is None or forecast.market is None or abs(forecast.market - forecast.opening) < 0.25


def outlook(season, week: int, found: dict | None = None, flipped=None) -> list[Drift]:
    """Games still on their opening line, with the move the study says to expect."""
    from . import flips as flipmod, pricing
    found = read() if found is None else found
    if not found:
        return []
    share = (found["from"].get("opening") or {})
    if not share.get("move"):
        return []
    slate = season.weeks.get(week)
    if slate is None:
        return []
    games = sorted(slate.games, key=lambda g: g.index)
    ctx = pricing.context(season, week, games)
    turns = {f.index: f for f in (flipmod.week_flips(season, week) if flipped is None else flipped)}
    out = []
    for g in games:
        f = ctx.forecasts.get(g.index)
        if f is None or g.played or not at_opening(f) or f.edge is None:
            continue
        move = predictions.home_margin(g, f, share["move"] * f.edge)
        if move is None or abs(move) < SHOWN:
            continue
        flip = turns.get(g.index)
        reaches = False
        if flip is not None and flip.market is not None and flip.flip_market is not None:
            after = flip.market + move
            reaches = (flip.market - flip.flip_market) * (after - flip.flip_market) <= 0
        out.append(Drift(g.index, g.label, g.home if move > 0 else g.away, abs(move), float(share["move"]),
                         int(share.get("games", 0)), flip.pick if flip else "", reaches))
    return sorted(out, key=lambda d: (-d.turns, -d.points))
