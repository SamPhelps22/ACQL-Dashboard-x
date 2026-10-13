"""Who the dashboard belongs to.

The dashboard is one person's, and every page that asks "which coach are
you?" starts on that coach: the report card's comparison, Game Day's
rooting guide, the suicide pool helper, the highlighted line on the charts.
The pickers are still there for a look at somebody else's season - they
just never have to be set, and a new session always starts back here.

The pool's website has nothing to do with this: there every coach picks
their own name, on their own phone.
"""

from __future__ import annotations

#: The owner's name, as the pool's sheets spell it.
NAME = "Phelpy"


def _plain(text: object) -> str:
    return " ".join(str(text or "").split()).casefold()


def key(season) -> str:
    """The owner's key in this season's data, or "" if they are not in it."""
    wanted = _plain(NAME)
    for found, player in (getattr(season, "players", None) or {}).items():
        if _plain(getattr(player, "display", "")) == wanted or _plain(found) == wanted:
            return found
    return ""


def display(season) -> str:
    """The owner's name as this season shows it, or "" if they are not in it."""
    found = key(season)
    return season.players[found].display if found else ""
