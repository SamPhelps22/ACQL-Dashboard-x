"""The Lab's research assistant: Claude, answering from the app's own data.

Claude never sees a file, a shell or the model's code. It has a fixed set of
read-only tools, each one a function in data.py, and every number in an
answer has to come back from one of them. Each answer carries the list of
tool calls it made, with their inputs, so the page can show the evidence.

It uses the same sealed Anthropic key as the story writer (Ctrl+K > "Story
writer key..." in the dashboard); the key never leaves this computer's
server. With no key, `ask` says so plainly and the page offers the same
tools as buttons instead - nothing pretends to be an AI answer.

Costs a few cents a question. No Qt here.
"""

from __future__ import annotations

import json
from typing import Callable

from . import data

MODEL = "claude-opus-5-5"
MAX_TURNS = 8
MAX_RESULT_CHARS = 60_000

SYSTEM = """You are the research assistant inside Operation Sunday's private Lab, for an NFL pick'em pool's
forecasting model, Deadeye. Answer only from what the tools return. Rules:

- Every number you write must come from a tool result in this conversation. Do not calculate new statistics
  yourself beyond simple arithmetic on returned numbers; prefer the tools' own figures.
- Always give sample sizes, the season/weeks covered, and the model version when the tools give one.
- Label each claim as one of: Established (the data shows it, with enough games), Hypothesis (suggestive,
  needs testing or more games), or Unsupported (the data needed is not available - say which data).
- Only 'eligible' forecasts (proven made before the cutoff) are evidence. Forecasts marked 'postgame' were
  recorded after kickoff and must never be treated as predictions.
- A missed pick is not by itself evidence of a flawed model; compare wins with the chances given.
- Never claim an experiment was run unless a tool result shows its result. You cannot run experiments,
  change models or edit forecasts; if asked, say so and suggest what experiment would answer it.
- Information known only at kickoff (starting quarterbacks) was not available at the Thursday lock; say so.
- Be concise: a short answer, then the supporting games or figures as a brief list."""

TOOLS = [
    {"name": "calibration", "description": "Calibration of one model's eligible win-probability forecasts on "
     "finished games: probability bins with predicted vs observed win rate, counts, 95% Wilson intervals, Brier "
     "score, log loss, and winner accuracy. Filters are optional.",
     "input_schema": {"type": "object", "properties": {
         "model": {"type": "string", "description": "Model id from list_models; default 'deadeye'."},
         "season": {"type": "integer"}, "team": {"type": "string", "description": "Team code, e.g. 'buf'."},
         "width": {"type": "number", "description": "Bin width, 0.05 or 0.1 (default 0.1)."}},
         "additionalProperties": False}},
    {"name": "list_models", "description": "Every model in the forecast log with its count of eligible forecasts.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "postmortems", "description": "Every Deadeye forecast on a finished game: locked probability, when "
     "it was made, model version, eligibility status, the market's eligible moneyline chance, result, Brier and "
     "surprise, margin error, stored line moves, starting quarterbacks (known at kickoff only), data-quality "
     "flags, plus a research summary. Use filters to keep it short.",
     "input_schema": {"type": "object", "properties": {
         "season": {"type": "integer"}, "weeks": {"type": "array", "items": {"type": "integer"}},
         "team": {"type": "string"}, "only_misses": {"type": "boolean"},
         "only_eligible": {"type": "boolean", "description": "Default true."},
         "sort": {"type": "string", "enum": ["brier", "surprise", "disagreement", "week"]},
         "limit": {"type": "integer"}}, "additionalProperties": False}},
    {"name": "team", "description": "One team's identity, record, every stored game with its line and "
     "Deadeye's forecast, and Deadeye's record on its games.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"],
                      "additionalProperties": False}},
    {"name": "strength", "description": "Weekly team ratings for chosen teams: Deadeye's own results-only rating, "
     "the market's line-implied rating, and scoring form, with the method notes.",
     "input_schema": {"type": "object", "properties": {"teams": {"type": "array", "items": {"type": "string"}}},
                      "required": ["teams"], "additionalProperties": False}},
    {"name": "odds", "description": "Every bookmaker's moneyline, spread and total for one game (or all) from the "
     "latest archived Odds API answer, with consensus and best prices.",
     "input_schema": {"type": "object", "properties": {"team": {"type": "string"}}, "additionalProperties": False}},
    {"name": "team_stats", "description": "nflverse team-game statistics for one team (points, yards a play, EPA a "
     "play, turnovers, and the opponent's), with definitions and what is missing.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}, "season": {"type": "integer"}},
                      "required": ["code"], "additionalProperties": False}},
    {"name": "experiments", "description": "The forecast log's scorecard for every model and the hypothesis "
     "bench's recorded plans. Shows only what was recorded.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def run_tool(name: str, args: dict, conn) -> object:
    """One tool call. Only these names exist; anything else is an error."""
    args = args if isinstance(args, dict) else {}
    if name == "calibration":
        width = args.get("width") if args.get("width") in (0.05, 0.1) else 0.1
        made = data.calibration(conn, args.get("model") or data.DEADEYE, season=args.get("season"),
                                team=args.get("team"), width=width)
        for b in made["bins"]:
            b.pop("games", None)
        return made
    if name == "list_models":
        return data.model_list(conn)
    if name == "postmortems":
        made = data.postmortems(conn, args.get("season"))
        games = made["games"]
        if args.get("only_eligible", True):
            games = [g for g in games if g["status"] == "eligible"]
        if args.get("weeks"):
            games = [g for g in games if g["week"] in args["weeks"]]
        if args.get("team"):
            games = [g for g in games if args["team"] in (g["home"], g["away"])]
        if args.get("only_misses"):
            games = [g for g in games if g["right"] is False]
        key = args.get("sort") or "week"
        if key == "week":
            games.sort(key=lambda g: (g["week"], g["game"]))
        else:
            games.sort(key=lambda g: -abs(g.get(key) or 0))
        for g in games:
            g["line_moves"] = g["line_moves"][-3:]
        return {"games": games[: int(args.get("limit") or 25)], "matching": len(games),
                "summary": made["summary"], "missing": made["missing"]}
    if name == "team":
        code = data.code(args.get("code"))
        row = next((t for t in data.teams(conn) if t["code"] == code), None)
        if not row:
            return {"error": f"No team with code {code!r}."}
        return {**row, "deadeye_record": data.team_record(conn, code)}
    if name == "strength":
        made = data.strength()
        wanted = [data.code(t) for t in args.get("teams") or []][:6]
        return {"weeks": made["weeks"], "method": made["method"],
                "teams": {t: {"own": made["own"].get(t), "market": made["market"].get(t), "form": made["form"].get(t)}
                          for t in wanted if t in made["own"]}}
    if name == "odds":
        made = data.books()
        if args.get("team"):
            t = data.code(args["team"])
            made["games"] = [g for g in made["games"] if t in (g["home"], g["away"])]
        made.pop("snapshots", None)
        return made
    if name == "team_stats":
        made = data.stats(args.get("season"))
        code = data.code(args.get("code"))
        made["rows"] = [r for r in made["rows"] if r["team"] == code]
        return made
    if name == "experiments":
        return data.experiments(conn)
    return {"error": f"Unknown tool {name!r}."}


def available() -> tuple[bool, str]:
    from ..site import storyteller
    if not storyteller.has_key():
        return False, ("No Anthropic API key is set. Add one in the dashboard (Ctrl+K > \"Story writer key...\"); "
                       "until then use the data buttons, which answer from the same tools without AI.")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The anthropic package isn't installed in the dashboard's Python."
    return True, ""


def _client():
    from ..site import storyteller
    import anthropic
    return anthropic.Anthropic(api_key=storyteller._key())


def ask(question: str, conn, *, client=None, context: dict | None = None,
        log: Callable[[dict], None] | None = None) -> dict:
    """Answer one question. Returns {"answer", "calls", "stop"} or {"error"}."""
    question = " ".join(str(question or "").split())[:2000]
    if not question:
        return {"error": "Ask a question first."}
    if client is None:
        ok, why = available()
        if not ok:
            return {"error": why, "unavailable": True}
        client = _client()
    text = question if not context else f"{question}\n\n(Page context: {json.dumps(context, default=str)[:2000]})"
    messages = [{"role": "user", "content": text}]
    calls: list[dict] = []
    for _ in range(MAX_TURNS):
        try:
            response = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except Exception as exc:  # noqa: BLE001 - said on the page, never a crash
            return {"error": f"Claude couldn't be reached: {exc}", "calls": calls}
        stop = getattr(response, "stop_reason", "")
        if stop == "refusal":
            return {"error": "Claude declined to answer this one.", "calls": calls}
        if stop == "max_tokens":
            return {"error": "The answer ran too long and was cut off; try a narrower question.", "calls": calls}
        messages.append({"role": "assistant", "content": response.content})
        if stop != "tool_use":
            answer = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
            return {"answer": answer, "calls": calls, "stop": stop}
        results = []
        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            try:
                out = run_tool(block.name, block.input, conn)
                body, is_error = json.dumps(out, default=str), isinstance(out, dict) and "error" in out
            except Exception as exc:  # noqa: BLE001 - the model is told, and can try again
                body, is_error = json.dumps({"error": str(exc)}), True
            if len(body) > MAX_RESULT_CHARS:
                body = body[:MAX_RESULT_CHARS] + ' ... [cut: narrow the filters]'
            call = {"tool": block.name, "input": block.input, "error": is_error, "chars": len(body)}
            calls.append(call)
            if log:
                log(call)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": body, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return {"error": "Stopped after too many tool rounds without an answer.", "calls": calls}
