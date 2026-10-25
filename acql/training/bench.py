"""The hypothesis bench (idea #34 of the upgrade book): new tests proposed by Claude,
registered only on your say, and judged only on games nobody had seen.

prereg.py holds the two tests written by hand on 2026-10-20. This adds a way to
keep the research moving without writing code: Claude is shown what has been
tested already and the small set of rules a test may use, and proposes one.
A proposal is only words until you approve it. Approving writes it down with
the date and a fingerprint, and it is scored - by prereg.score, the same sums as
the hand-written tests - only on frozen weeks from the week after approval.

The rules a test may use are deliberately few: move Deadeye's expected margin
by a fixed number of points toward or away from the favourite and/or the home
side, in one group of games. Nothing freer, so a proposal can't smuggle in a
look at results, and every test is a shadow: nothing here touches a pick.

    python -m acql.training bench propose      ask Claude for one (needs the story writer's key)
    python -m acql.training bench list         every test on the bench
    python -m acql.training bench approve ID   register it from next week
    python -m acql.training bench reject ID
    python -m acql.training bench score        score the registered ones on the frozen weeks
"""

from __future__ import annotations

import json
import re
import time

from . import prereg

#: The groups a test may apply to. Each is a test on one of prereg.games' rows.
APPLIES = {
    "every game": lambda row: True,
    "small favourites": lambda row: row["market"] is not None and row["market"] < 3,
    "middling favourites": lambda row: row["market"] is not None and 3 <= row["market"] < 7,
    "big favourites": lambda row: row["market"] is not None and row["market"] >= 7,
    "home favourites": lambda row: row["favourite_home"],
    "road favourites": lambda row: not row["favourite_home"],
}
#: The biggest move a test may make, points.
MOST_SHIFT = 3.0
STATUSES = ("proposed", "registered", "rejected")
FILE = "bench.json"


class BenchError(Exception):
    pass


def _path():
    from . import data
    return data.folder() / FILE


def load() -> list[dict]:
    try:
        found = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in found.get("plans", []) if isinstance(p, dict)] if isinstance(found, dict) else []


def save(plans: list[dict]) -> None:
    _path().write_text(json.dumps({"plans": plans}, indent=1), encoding="utf-8")


def check(plan: object) -> list[str]:
    """Why a proposed plan can't go on the bench, or []."""
    if not isinstance(plan, dict):
        return ["not a plan"]
    out = []
    pid = str(plan.get("id") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,40}", pid):
        out.append("id must be 3-41 lower-case letters, digits and dashes")
    if plan.get("applies") not in APPLIES:
        out.append(f"applies must be one of: {', '.join(APPLIES)}")
    for name in ("shift_favourite", "shift_home"):
        value = plan.get(name)
        if not isinstance(value, (int, float)) or abs(float(value)) > MOST_SHIFT:
            out.append(f"{name} must be a number of points between -{MOST_SHIFT:g} and {MOST_SHIFT:g}")
    if not out and plan["shift_favourite"] == 0 and plan["shift_home"] == 0:
        out.append("a test must move something")
    if not str(plan.get("rule") or "").strip():
        out.append("rule must say in words what changes")
    taken = {p["id"] for p in prereg.PLANS} | {p.get("id") for p in load()}
    if pid in taken:
        out.append(f"{pid} is already on the bench")
    return out


def _facts() -> dict:
    done = [{"id": p["id"], "rule": p["rule"]} for p in list(prereg.PLANS) + load()]
    return {
        "already_tested_or_proposed": done,
        "allowed_groups": list(APPLIES),
        "most_shift_points": MOST_SHIFT,
        "known_findings": [
            "Deadeye is level with the betting line over 6,128 games; no challenger beat it.",
            "Weather, injuries, travel, rest, surface and tracking stats added nothing over the line.",
            "The curve may overrate favourites giving under 3 points by 2-3 points of win chance.",
            "Home sides may be overrated by about 1 point.",
        ],
    }


SYSTEM = ("You propose one new pre-registered test for an NFL prediction model's research bench. A test "
          "moves the model's expected margin by a fixed number of points in one group of games. Reply with a "
          "single JSON object and nothing else, with keys: id (lower-case words joined by dashes, ending in -1), "
          "rule (one plain sentence saying what changes), applies (one of the allowed groups), shift_favourite "
          "(points toward the favourite, negative toward the underdog), shift_home (points toward the home side, "
          "negative toward the road side), why (one sentence on why it might matter). Do not repeat anything "
          "already tested or proposed. Prefer tests with a football reason over data-mined ones.")


def _client():
    from ..site import storyteller
    key = storyteller._key()
    if not key:
        raise BenchError("No Anthropic API key yet - add one with 'Story writer key…' (Ctrl+K).")
    try:
        import anthropic
    except ImportError as exc:
        raise BenchError("The anthropic package isn't installed in the dashboard's Python.") from exc
    return anthropic.Anthropic(api_key=key)


def _json_in(text: str) -> object:
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        return None
    try:
        return json.loads(found.group(0))
    except ValueError:
        return None


def propose(*, client=None, now: float | None = None) -> dict:
    """Ask Claude for one test and put it on the bench as 'proposed'. Raises BenchError."""
    from ..site import storyteller
    client = client or _client()
    prompt = "Facts, as JSON:\n" + json.dumps(_facts(), sort_keys=True)
    last: list[str] = []
    for _attempt in range(2):
        try:
            response = client.messages.create(
                model=storyteller.MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt + (f"\n\nYour last proposal was refused: "
                                                                f"{'; '.join(last)}." if last else "")}])
        except Exception as exc:  # noqa: BLE001
            raise BenchError(f"Claude couldn't be reached: {exc}") from exc
        if getattr(response, "stop_reason", "") == "refusal":
            raise BenchError("Claude declined to propose one.")
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        plan = _json_in(text)
        last = check(plan)
        if not last:
            kept = {"id": plan["id"], "rule": str(plan["rule"]).strip(), "applies": plan["applies"],
                    "shift_favourite": float(plan["shift_favourite"]), "shift_home": float(plan["shift_home"]),
                    "why": str(plan.get("why") or "").strip(), "status": "proposed",
                    "proposed": time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))}
            plans = load()
            plans.append(kept)
            save(plans)
            return kept
    raise BenchError("The proposal didn't pass the bench's rules (" + "; ".join(last) + "), so it wasn't kept.")


def _find(plans: list[dict], pid: str) -> dict:
    for p in plans:
        if p.get("id") == pid:
            return p
    raise BenchError(f"No test called {pid} on the bench.")


def approve(pid: str, first_week: int, season: int, *, now: float | None = None) -> dict:
    """Register a proposal: dated, fingerprinted, judged from `first_week` on."""
    plans = load()
    plan = _find(plans, pid)
    if plan.get("status") != "proposed":
        raise BenchError(f"{pid} is {plan.get('status')}, not waiting for a yes.")
    plan.update(status="registered", first_week=int(first_week), season=int(season),
                registered=time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now)))
    frozen = {k: plan[k] for k in ("id", "rule", "applies", "shift_favourite", "shift_home",
                                   "first_week", "season", "registered")}
    plan["fingerprint"] = prereg.fingerprint(frozen)
    save(plans)
    return plan


def reject(pid: str) -> dict:
    plans = load()
    plan = _find(plans, pid)
    if plan.get("status") == "registered":
        raise BenchError(f"{pid} is registered; a registered test stays on the record.")
    plan["status"] = "rejected"
    save(plans)
    return plan


def score_plan(plan: dict, rows: list[dict]) -> dict:
    """prereg.score for a bench plan: the same sums, with the bench's groups."""
    test = APPLIES[plan["applies"]]
    picked = [r for r in rows if test(r)]
    as_every = dict(plan, applies="every game")      # prereg.score's own filter is then a no-op
    found = prereg.score(as_every, picked)
    found["applies"] = plan["applies"]
    found["fingerprint"] = plan.get("fingerprint", found["fingerprint"])
    return found


def score() -> list[dict]:
    """Every registered bench test, on the frozen weeks since it was registered (a copy of the database)."""
    from . import study
    out = []
    with study.books():
        for plan in load():
            if plan.get("status") != "registered":
                continue
            out.append(score_plan(plan, prereg.games(plan["season"], plan["first_week"])))
    return out
