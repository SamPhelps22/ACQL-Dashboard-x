"""The rest of the locked page: more of the model than the card, for its owner.

The locked page (lockedpage.py) carries the week's card. These are the other
rooms behind the same door - the model's season record, how each signal has
done, the market's power ranks and the training ground's latest answer - each
made from what is stored, nothing fetched. Every room is optional: one that
fails or has nothing to say is left out, never the cause of a failed upload.
Everything here ends up encrypted; nothing here is uploaded as it stands.
Nothing here knows about Qt.
"""

from __future__ import annotations

from html import escape


def _table(heads: list[str], rows: list[list], right: set[int] = frozenset()) -> str:
    th = "".join(f"<th{' class=n' if i in right else ''}>{escape(h)}</th>" for i, h in enumerate(heads))
    body = "".join(
        "<tr>" + "".join(f"<td{' class=n' if i in right else ''}>{escape(str(v))}</td>" for i, v in enumerate(row))
        + "</tr>" for row in rows)
    return f"<div class=scroll><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


def _tiles(pairs: list[tuple[str, str]]) -> str:
    return "<div class=tiles>" + "".join(
        f"<div class=tile><b>{escape(v)}</b><span>{escape(k)}</span></div>" for k, v in pairs) + "</div>"


def _money(value: float) -> str:
    return f"{'+' if value > 0 else '-' if value < 0 else ''}${abs(value):,.0f}"


def record(season) -> str | None:
    from ..model import ghost
    found = ghost.season_record(season)
    if found is None or not found.weeks:
        return None
    tiles = _tiles([("Record", f"{found.wins}-{found.losses}"), ("Hit rate", f"{found.pct:.1%}"),
                    ("Net", _money(found.net)), ("Best week", str(found.best_week)),
                    ("Last 3 weeks", str(found.last(3)))])
    rows = [[w.week, w.regular, w.losers, w.total, f"{w.place} of {w.entrants}", w.best, _money(w.money)]
            for w in sorted(found.weeks, key=lambda w: w.week, reverse=True)]
    return (tiles + "<h3>Week by week</h3>"
            + _table(["Week", "Picks", "Big L", "Total", "Place", "Best", "Money"], rows, {0, 1, 2, 3, 5, 6})
            + "<p class=note>Its card played against the pool each week, scored the way a coach's is.</p>")


def signals(season) -> str | None:
    from ..model import evidence
    board = [r for r in evidence.scoreboard(season) if r.games]
    if not board:
        return None
    rows = [[r.name, f"{r.right}-{r.games - r.right}", f"{r.rate:.0%}",
             f"{r.split_right} of {r.split}" if r.split else "-"] for r in board]
    return (_table(["Signal", "Right-wrong", "Rate", "Against the line"], rows, {1, 2, 3})
            + "<p class=note>Every graded game this season. “Against the line” is the part worth "
              "knowing: the games a signal disagreed with the betting line, and how often it was right.</p>")


def ranks(season) -> str | None:
    from ..model import power
    found = power.rankings(season)
    if not found.teams:
        return None
    rows = [[t.rank, t.team, f"{t.rating:+.1f}", t.record, f"{t.margin:+.1f}",
             f"{t.gap:+d}" if t.gap else "-", t.next or "-"] for t in found.teams]
    return (_table(["#", "Team", "Rating", "Record", "Margin", "vs results", "Next"], rows, {0, 2, 4, 5})
            + f"<p class=note>Solved from {found.games} betting lines. Rating: points better than an average "
              "team. “vs results”: places the market has a team above (+) or below what it has done.</p>")


def lab(season=None) -> str | None:
    from ..model import challengers
    found = challengers.read()
    if found is None:
        return None
    head = f"<p class=call>{escape(found.call)}</p>"
    if found.stale():
        head += "<p class=note>This answer is more than a week old - the weekly training run has not been.</p>"
    return (head + _table(challengers.HEADERS, found.rows)
            + f"<p class=note>{found.games:,} past games walked forward; {found.now_games} from this season. "
              "Nothing here changes a pick.</p>")


#: The rooms after the card, in order: (id, tab name, maker).
ROOMS = (("record", "Record", record), ("signals", "Signals", signals),
         ("ranks", "Ranks", ranks), ("lab", "Lab", lab))


def rooms(season) -> list[dict]:
    """Each room that has something to show, as {"id", "name", "html"}."""
    out = []
    for key, name, make in ROOMS:
        try:
            inside = make(season)
        except Exception:  # noqa: BLE001 - one room missing never stops the page
            inside = None
        if inside:
            out.append({"id": key, "name": name, "html": inside})
    return out
