"""The week as a story, written by Claude from the week's facts only (idea #94).

The recap is built from templates. This hands Claude a fact sheet - the
recap's own numbers, names, upsets and awards, nothing else - and asks for a
short, readable story for the group chat. Then every number in the story is
checked against the fact sheet, and the story is refused if it holds one the
facts don't, or mentions the model or the dashboard by name (they stay off
anything the pool sees). Nothing is sent anywhere: the dashboard shows the
story and you copy it if you like it.

Needs the `anthropic` package and an API key you enter yourself (sealed on
this computer like the odds key). Costs a few cents a story. No Qt.
"""

from __future__ import annotations

import json
import re

from .. import store

MODEL = "claude-opus-5-5"
KEY_KIND, KEY_NAME = "settings", "anthropic_key"
PRIVATE = ("Deadeye", "Operation Sunday")


class StoryError(Exception):
    pass


def has_key() -> bool:
    return bool(store.get(KEY_KIND, KEY_NAME, ""))


def set_key(key: str) -> None:
    from . import mailer
    key = "".join(key.split())
    store.put(KEY_KIND, KEY_NAME, mailer.seal(key) if key else "")


def _key() -> str:
    from . import mailer
    sealed = store.get(KEY_KIND, KEY_NAME, "") or ""
    try:
        return mailer.unseal(sealed) if sealed else ""
    except Exception:  # noqa: BLE001 - sealed on another computer
        return ""


def facts(recap) -> dict:
    """The week's fact sheet: everything the story may say, and nothing else."""
    return {
        "season": recap.season_title, "week": recap.week, "coaches": recap.entrants, "games": recap.games,
        "average_score": round(recap.average, 1), "winners": recap.winners, "top_score": recap.top_score,
        "payout_each": round(recap.payout_each, 2),
        "standings_top5": [{"place": s.place, "name": s.name, "wins": s.wins, "moved": s.move, "won_week": s.won_week}
                           for s in recap.standings[:5]],
        "awards": [vars(a) if hasattr(a, "__dict__") else str(a) for a in recap.awards],
        "upsets": [vars(u) if hasattr(u, "__dict__") else str(u) for u in recap.upsets],
        "crowd_right": recap.crowd_right, "crowd_games": recap.crowd_games,
        "suicide_knocked_out_by": recap.killer, "suicide_knocked_out": recap.killed,
        "suicide_left": recap.suicide_left,
    }


def _numbers(text: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", text)}


def problems(story: str, sheet: dict) -> list[str]:
    """Why a story can't be used, or []."""
    allowed = _numbers(json.dumps(sheet, default=str))
    stray = sorted(_numbers(story) - allowed, key=lambda n: float(n))
    out = []
    if stray:
        out.append(f"numbers not in the facts: {', '.join(stray)}")
    private = [w for w in PRIVATE if w.casefold() in story.casefold()]
    if private:
        out.append(f"mentions {', '.join(private)}")
    return out


SYSTEM = ("You write a short, lively weekly recap for a friendly NFL pick'em pool's group chat. Use only the facts "
          "given: every name and number you write must appear in them. Do not invent plays, quotes, scores or "
          "streaks. Do not write any number that isn't in the facts - say 'a handful' rather than guess. About 120 "
          "words, plain text, no headings or lists.")


def write(recap, *, client=None) -> str:
    """The story, checked. Raises StoryError when it can't be written or fails the check."""
    sheet = facts(recap)
    if client is None:
        key = _key()
        if not key:
            raise StoryError("No Anthropic API key yet - add one with 'Story writer key…' (Ctrl+K).")
        try:
            import anthropic
        except ImportError as exc:
            raise StoryError("The anthropic package isn't installed in the dashboard's Python.") from exc
        client = anthropic.Anthropic(api_key=key)
    prompt = "Facts for the week, as JSON:\n" + json.dumps(sheet, default=str, sort_keys=True)
    last = []
    for _attempt in range(2):
        try:
            response = client.messages.create(
                model=MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt + (f"\n\nYour last draft had {last[0]}; leave those out."
                                                                if last else "")}])
        except Exception as exc:  # noqa: BLE001 - shown to you, never a crash
            raise StoryError(f"Claude couldn't be reached: {exc}") from exc
        if getattr(response, "stop_reason", "") == "refusal":
            raise StoryError("Claude declined to write this one.")
        story = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        last = problems(story, sheet)
        if story and not last:
            return story
    raise StoryError("The story didn't pass the fact check (" + "; ".join(last) + "), so it wasn't used.")
