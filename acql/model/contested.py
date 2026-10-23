"""Contested games (idea #26): where the computer models sharply disagree with the line.

The models' middle and the betting line usually sit within a point or two.
When they don't, it's worth knowing - and the edge-decay study says what the
gap tends to mean: from the opening line the market has gone on to close a
large share of it, once the line has moved, almost none, and in recent
seasons the gap hasn't shown up in results at the later lines. So this is
information about the market, labelled as such - never a tip. No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import predictions

#: A gap this many points between the models' middle and the line is "contested".
GAP = 2.5


@dataclass(frozen=True)
class Contested:
    index: int
    matchup: str
    toward: str            # the side the models like more than the line does
    gap: float             # points
    models: int            # how many models priced it
    apart: float | None    # how far apart the models are among themselves
    at_opening: bool       # the line hasn't moved since it opened


def week(season, number: int) -> list[Contested]:
    from . import drift, pricing
    slate = season.weeks.get(number)
    if slate is None:
        return []
    games = sorted(slate.games, key=lambda g: g.index)
    ctx = pricing.context(season, number, games)
    out = []
    for g in games:
        f = ctx.forecasts.get(g.index)
        if f is None or g.played or f.edge is None:
            continue
        gap = predictions.home_margin(g, f, f.edge)
        if gap is None or abs(gap) < GAP:
            continue
        out.append(Contested(g.index, g.label, predictions.display_team(g.home if gap > 0 else g.away), abs(gap),
                             len(f.opinions or ()),
                             getattr(f, "disagreement", None), drift.at_opening(f)))
    return sorted(out, key=lambda c: -c.gap)
