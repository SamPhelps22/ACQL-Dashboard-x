"""The devil's advocate (idea #37 of the upgrade book): the best case against the card's
shakiest picks, written by Claude from stored facts only.

Before the deadline the card's three most fragile picks - the ones the market
need move least to turn, then the closest calls - are handed to Claude as a fact
sheet: the chances, the pool's lean, how far the line has moved, what the
computer models and the radar say, quarterback news and the weather. Claude
argues against each pick and then says, in a line, what still holds it up.
Every number in the brief is checked against the fact sheet, as the
storyteller's are; a brief that fails the check is refused, never shown.

It changes nothing. It is a second look on the desktop only; nothing here is
published or sent. Needs the story writer's key; costs a few cents. No Qt.
"""

from __future__ import annotations

import json

from ..models import Season
from ..model import screener

#: How many picks it argues against.
PICKS = 3


class AdvocateError(Exception):
    pass


def fragile(screen: screener.Screen, n: int = PICKS) -> list[screener.Row]:
    """The card's shakiest picks: nearest to flipping first, then the closest calls."""
    return sorted(screen.rows, key=lambda r: (r.flip if r.flip is not None else 99.0, r.chance))[:n]


def facts(season: Season, week: int | None = None, screen: screener.Screen | None = None) -> dict:
    screen = screen or screener.build(season, week)
    try:
        from ..feeds import odds
        moves = {m[0]: (m[1], m[2]) for m in odds.movements(screen.week)}
    except Exception:  # noqa: BLE001
        moves = {}
    games = []
    for r in fragile(screen):
        moved = moves.get(r.matchup)
        games.append({
            "game": r.matchup, "card_takes": r.pick, "card_chance_pct": round(r.chance * 100),
            "market_chance_pct": None if r.market is None else round(r.market * 100),
            "pool_share_on_pick_pct": None if r.crowd is None else round(r.crowd * 100),
            "pool_share_counted": r.counted, "pool_line": r.pool_line or None,
            "points_market_must_move_to_flip": None if r.flip is None else round(r.flip, 1),
            "line_home_side_first_seen_then_now": list(moved) if moved else None,
            "hard_to_call_0_100": round(r.hard),
            "radar_notes": list(r.flags), "quarterback_news": r.injuries or None, "weather": r.weather or None,
        })
    return {"week": screen.week, "picks": games}


SYSTEM = ("You are a devil's advocate for an NFL pick'em player. For each pick in the facts, write a short "
          "paragraph making the strongest honest case against it, then one sentence on what still supports it. "
          "Use only the facts given: every number you write must appear in them, and do not invent injuries, "
          "trends, records or quotes. If the facts give little against a pick, say so plainly. Plain text, one "
          "paragraph per pick starting with the game, no headings or lists, about 70 words a pick.")


def write(season: Season, week: int | None = None, *, client=None, sheet: dict | None = None) -> tuple[str, dict]:
    """(the brief, the facts it was written from). Raises AdvocateError."""
    from ..site import storyteller
    sheet = sheet or facts(season, week)
    if not sheet["picks"]:
        raise AdvocateError("No priced games to argue about yet.")
    if client is None:
        key = storyteller._key()
        if not key:
            raise AdvocateError("No Anthropic API key yet - add one with 'Story writer key…' (Ctrl+K).")
        try:
            import anthropic
        except ImportError as exc:
            raise AdvocateError("The anthropic package isn't installed in the dashboard's Python.") from exc
        client = anthropic.Anthropic(api_key=key)
    prompt = "Facts, as JSON:\n" + json.dumps(sheet, sort_keys=True, ensure_ascii=False)
    last: list[str] = []
    for _attempt in range(2):
        try:
            response = client.messages.create(
                model=storyteller.MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt + (f"\n\nYour last draft had {last[0]}; leave those out."
                                                                if last else "")}])
        except Exception as exc:  # noqa: BLE001
            raise AdvocateError(f"Claude couldn't be reached: {exc}") from exc
        if getattr(response, "stop_reason", "") == "refusal":
            raise AdvocateError("Claude declined to write this one.")
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        last = [p for p in storyteller.problems(text, sheet) if p.startswith("numbers")]
        if text and not last:
            return text, sheet
    raise AdvocateError("The brief didn't pass the fact check (" + "; ".join(last) + "), so it wasn't shown.")
