"""Feature value: does one football fact, added to the betting line, say anything the line did not?

Each candidate is tried on its own. For every line timing the archive keeps
(opening, midweek, updated, closing) the question is the same: a home win's
chance read from the line alone, against the same reading with one fact
added. Both are logistic fits on the de-vigged line - the moneyline's fair
chance where the closing line has one, otherwise the spread turned into a
chance on the dashboard's own curve (analytics.win_chance) - taught in the
usual walk-forward: as each week begins, on every earlier week's games, and
never on a season before walkforward.WARM_UP seasons have gone. The games are
handed over without their results (features.question).

What is reported is the change in log loss a game (negative: the fact helped)
on the games that had the fact, with a 95% range from resampling whole
seasons. Ties are left out.

Only facts with a time on them are counted as usable:

    rest, division, roof   on the schedule long before the game
    ml_gap, total_rel      the moneyline and total, only when taken no later
                           than the line (features.prepare refuses later ones)

and these are flagged, not used, because nothing says when they were known:

    qb_change              nflverse's starting quarterbacks are filled in
                           after the game - who started, not who was named
    wind, cold             nflverse's weather is what it was at kickoff, not
                           the forecast a card was made from
    injuries               the only reports with a time on them are the
                           weekly snapshots, which begin this season

The flagged ones are still measured, in their own table, as a hindsight
ceiling: if even knowing them for certain adds nothing, a forecast of them
will not. They never count toward a verdict.

This only measures. It changes no pick, and the dashboard does not import it.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import data, features, walkforward

#: Line timings, in the order the week takes them, and the setting each is read through.
TIMINGS = ("opening", "midweek", "updated", "closing")
#: Facts with a time on them.
USABLE = ("rest", "division", "roof", "ml_gap", "total_rel")
#: Facts without one: measured as a ceiling, never a verdict.
UNTIMED = ("qb_change", "wind", "cold")
ABOUT = {
    "rest": "home days of rest less the road side's (schedule)",
    "division": "a division game (schedule)",
    "roof": "played under a fixed roof (stadium; retractable roofs count as open air)",
    "ml_gap": "the margin the moneyline implies, less the spread (same timing or earlier; on top of the spread alone)",
    "total_rel": "the over/under less the slate's middle one (same timing or earlier)",
    "qb_change": "a side starting a different quarterback from its last game, home less road (filled in after the game)",
    "wind": "wind at kickoff, mph, open air only (observed, not forecast)",
    "cold": "kickoff at or below freezing, open air only (observed, not forecast)",
}
#: Fewest games with the fact, across the seasons asked about, before it is scored at all.
FEWEST = 300
RESAMPLES = 2000
#: Kept a little away from 0 and 1 before logs are taken.
EDGE = 1e-6


# ---- the facts nflverse has that data.history does not carry -------------------------------------
def schedule_facts(path=None) -> pd.DataFrame:
    """game key -> roof, wind, cold, qb_change from nflverse's schedule file.
    qb_change compares each side's starter with its own previous game
    (postseason included, across seasons). Empty when the file is not there."""
    from ..feeds.nflverse import FOLDER, GAMES_FILE
    try:
        with gzip.open(path or FOLDER / GAMES_FILE, "rt", encoding="utf-8", newline="") as handle:
            raw = list(csv.DictReader(handle))
    except OSError:
        return pd.DataFrame()
    raw.sort(key=lambda r: (int(r["season"]), r.get("gameday", ""), r.get("gametime", "")))
    last_qb: dict[str, str] = {}
    rows = []
    for row in raw:
        home, away = data._verse_team(row.get("home_team", "")), data._verse_team(row.get("away_team", ""))
        if not home or not away:
            continue
        changed = {}
        for side, team in (("home", home), ("away", away)):
            qb = (row.get(f"{side}_qb_id") or "").strip()
            before = last_qb.get(team)
            changed[side] = np.nan if not qb or before is None else float(qb != before)
            if qb:
                last_qb[team] = qb
        roof = (row.get("roof") or "").strip().casefold()
        open_air = roof in ("outdoors", "open", "closed") if roof else None
        temp, wind = data._number(row.get("temp")), data._number(row.get("wind"))
        rows.append({
            "game": data.game_key(int(row["season"]), int(row["week"]), away, home),
            "roof": np.nan if not roof else float(roof == "dome"),
            "wind": wind if open_air and wind is not None else (0.0 if roof == "dome" else np.nan),
            "cold": (float(temp <= 32) if open_air and temp is not None else (0.0 if roof == "dome" else np.nan)),
            "qb_change": changed["home"] - changed["away"],
        })
    return pd.DataFrame(rows).drop_duplicates("game", keep="last")


def injury_seasons(folder=None) -> list[int]:
    """Seasons with an injury report frozen before the deadline in a weekly snapshot."""
    folder = folder or data.folder() / "snapshots"
    found = set()
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(isinstance(g, dict) and g.get("injuries") for g in body.get("games", [])):
            found.add(int(body.get("season", 0)))
    return sorted(found)


# ---- the fit -----------------------------------------------------------------------------------
def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EDGE, 1 - EDGE)
    return np.log(p / (1 - p))


def fit_logistic(x: np.ndarray, y: np.ndarray, ridge: float = 1e-3, steps: int = 25) -> np.ndarray:
    """Weights (intercept first) of a logistic fit of y on the columns of x, by Newton's method."""
    design = np.column_stack([np.ones(len(x)), x])
    w = np.zeros(design.shape[1])
    hold = ridge * np.eye(len(w))
    hold[0, 0] = 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-np.clip(design @ w, -30, 30)))
        grad = design.T @ (p - y) + hold @ w
        hess = (design * (p * (1 - p))[:, None]).T @ design + hold + 1e-9 * np.eye(len(w))
        move = np.linalg.solve(hess, grad)
        w -= move
        if np.abs(move).max() < 1e-8:
            break
    return w


def _chance(w: np.ndarray, x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(w[0] + x @ w[1:], -30, 30)))


def line_chance(prepared: pd.DataFrame, moneyline: bool = True) -> np.ndarray:
    """The home side's chance from the line alone: the de-vigged moneyline when
    the setting allowed it (features.prepare refuses a later one), else the
    spread on the dashboard's curve."""
    from .. import analytics
    spread = np.array([analytics.win_chance(m) if not np.isnan(m) else np.nan
                       for m in prepared["market"].to_numpy(dtype=float)])
    if moneyline and "ml_gap" in prepared.columns:
        # ml_gap is only filled when the moneyline was allowed; its chance is the one to use
        ml_margin = prepared["market"].to_numpy(dtype=float) + prepared["ml_gap"].to_numpy(dtype=float)
        ml = np.array([analytics.win_chance(m) if not np.isnan(m) else np.nan for m in ml_margin])
        return np.where(np.isnan(ml), spread, ml)
    return spread


def walk(prepared: pd.DataFrame, fact: str, warm_up: int = walkforward.WARM_UP,
         until: int | None = None) -> pd.DataFrame:
    """Every game asked about that has the fact: season, order, and the chance
    each way (line alone, line + fact), each taught only on earlier weeks."""
    use = prepared[prepared[fact].notna() & prepared["actual"].notna() & (prepared["actual"] != 0)].copy()
    use = use.sort_values(["order", "game"], kind="stable").reset_index(drop=True)
    if use.empty:
        return pd.DataFrame(columns=["season", "order", "won", "line", "with"])
    # the moneyline's own gap is measured against the spread: on top of the moneyline it would be counted twice
    use["base"] = _logit(line_chance(use, moneyline=fact != "ml_gap"))
    use = use[np.isfinite(use["base"])].reset_index(drop=True)
    won = (use["actual"].to_numpy(dtype=float) > 0).astype(float)
    order = use["order"].to_numpy()
    seasons = sorted(set(use["season"].tolist()))
    asked = set(seasons[warm_up:])
    out = []
    for step in sorted(set(order.tolist())):
        if step // 100 not in asked or (until is not None and step > until):
            continue
        before = order < step
        if before.sum() < 50:
            continue
        here = np.flatnonzero(order == step)
        question = features.question(use.iloc[here])     # the results go nowhere near the fit's inputs
        taught = use[before]
        x0 = taught[["base"]].to_numpy(dtype=float)
        x1 = taught[["base", fact]].to_numpy(dtype=float)
        y = won[before]
        if np.nanstd(x1[:, 1]) < 1e-9:
            continue
        w0, w1 = fit_logistic(x0, y), fit_logistic(x1, y)
        out.append(pd.DataFrame({
            "season": question["season"].to_numpy(), "order": step, "won": won[here],
            "line": _chance(w0, question[["base"]].to_numpy(dtype=float)),
            "with": _chance(w1, question[["base", fact]].to_numpy(dtype=float)),
        }))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["season", "order", "won", "line", "with"])


def _loss(p: np.ndarray, won: np.ndarray) -> np.ndarray:
    p = np.clip(p, EDGE, 1 - EDGE)
    return -(won * np.log(p) + (1 - won) * np.log(1 - p))


@dataclass
class Value:
    fact: str
    timing: str
    usable: bool
    games: int
    seasons: int
    change: float = np.nan        # log loss a game, line + fact less line alone (negative: it helped)
    low: float = np.nan
    high: float = np.nan
    why: str = ""

    @property
    def helps(self) -> bool:
        return self.usable and self.games >= FEWEST and self.high < 0


def score(walked: pd.DataFrame, fact: str, timing: str, usable: bool, seed: int = 2026) -> Value:
    if len(walked) < FEWEST:
        return Value(fact, timing, usable, len(walked), walked["season"].nunique() if len(walked) else 0,
                     why=f"fewer than {FEWEST} games had it")
    won = walked["won"].to_numpy(dtype=float)
    diff = _loss(walked["with"].to_numpy(dtype=float), won) - _loss(walked["line"].to_numpy(dtype=float), won)
    seasons = walked["season"].to_numpy()
    years = np.unique(seasons)
    sums = {y: (diff[seasons == y].sum(), (seasons == y).sum()) for y in years}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(RESAMPLES):
        pick = rng.choice(years, len(years))
        means.append(sum(sums[y][0] for y in pick) / sum(sums[y][1] for y in pick))
    return Value(fact, timing, usable, len(walked), len(years), float(diff.mean()),
                 float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


# ---- the whole study -----------------------------------------------------------------------------
def study(history: pd.DataFrame | None = None, facts: pd.DataFrame | None = None,
          notes: data.Notes | None = None, timings=TIMINGS) -> list[Value]:
    notes = notes if notes is not None else data.Notes()
    history = data.check(data.history(notes=notes), notes) if history is None else history
    facts = schedule_facts() if facts is None else facts
    if len(facts):
        history = history.drop(columns=[c for c in facts.columns if c != "game" and c in history.columns])
        history = history.merge(facts, on="game", how="left")
    out = []
    for timing in timings:
        setting = features.SETTINGS[timing]
        prepared = features.prepare(history, setting, notes)
        for fact in USABLE + UNTIMED:
            usable = fact in USABLE
            if prepared.empty or fact not in prepared.columns or prepared[fact].notna().sum() == 0:
                out.append(Value(fact, timing, usable, 0, 0,
                                 why="not known at this line" if fact in ("ml_gap", "total_rel") else "no data"))
                continue
            out.append(score(walk(prepared, fact), fact, timing, usable))
    return out


def write_up(values: list[Value], injuries: list[int]) -> str:
    lines = [
        "# Feature value: one fact at a time, on top of the line",
        "",
        "Each fact is added on its own to the de-vigged line in a week-by-week walk-forward (taught only on "
        "earlier weeks, nothing asked about until "
        f"{walkforward.WARM_UP} seasons have gone). The number is the change in log loss a game when the fact "
        "is added - negative means it helped - on the games that had it, with a 95% range from "
        f"{RESAMPLES:,} resamples of whole seasons. A range that takes in zero is no evidence either way.",
        "",
    ]

    def table(rows: list[Value]) -> list[str]:
        body = ["| Fact | Line | Games | Seasons | Change a game | Range |", "| --- | --- | --- | --- | --- | --- |"]
        for v in rows:
            if np.isnan(v.change):
                body.append(f"| {v.fact} | {v.timing} | {v.games:,} | {v.seasons} | - | {v.why} |")
            else:
                body.append(f"| {v.fact} | {v.timing} | {v.games:,} | {v.seasons} | {v.change:+.5f} | "
                            f"{v.low:+.5f} to {v.high:+.5f}{' (helps)' if v.helps else ''} |")
        return body

    usable = [v for v in values if v.usable]
    untimed = [v for v in values if not v.usable]
    lines += ["## Facts known before the game", ""] + table(usable)
    lines += ["", "## Facts with no time on them - a hindsight ceiling, not usable", "",
              "Measured as if known for certain. They are not counted in the verdict: nothing says they were "
              "known before kickoff.", ""] + table(untimed)
    lines += ["", "**Injuries:** " + (
        f"point-in-time reports exist only for {', '.join(map(str, injuries))} (the weekly snapshots) - "
        "too few seasons for a walk-forward. Not measured." if injuries else
        "no injury report with a time on it has been frozen yet (the weekly snapshots carry none). "
        "Not measured."), ""]
    lines += ["What each fact is:", ""] + [f"- **{k}**: {v}" for k, v in ABOUT.items()]
    helps = [v for v in usable if v.helps]
    verdict = ("; ".join(f"{v.fact} at the {v.timing} line ({v.change:+.5f}, {v.low:+.5f} to {v.high:+.5f})"
                         for v in helps) + " - worth a closer look as a proposal to Sam, nothing more."
               if helps else "No fact known before the game adds anything the line had not priced, by more than "
                             "the games can vouch for.")
    lines += ["", f"**Verdict:** {verdict}", "",
              "This only measures; no pick changes and the dashboard does not import it.", ""]
    return "\n".join(lines)


def run() -> tuple[str, object]:
    values = study()
    text = write_up(values, injury_seasons())
    where = data.folder() / "patterns"
    where.mkdir(parents=True, exist_ok=True)
    path = where / "feature-value.md"
    path.write_text(text, encoding="utf-8")
    return text, path
