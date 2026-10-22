"""What a training run found, written down where it can be read.

One folder a run under data/training/runs, and the newest copied to
data/training/latest:

    report.md               the whole of it, in the order a decision needs:
                            what there was to learn from, the comparison, the
                            seasons one by one, the test of the 33%, the
                            curve, the games that changed sides, how sure any
                            of it is, the Model Lab's rule, and what would
                            have to happen before a switch
    predictions-<line>.csv  every game asked about, with every recipe's margin
                            and chance beside the result
    changed-sides.csv       every game the best challenger took the other
                            side of from the line
    fits.json               what each recipe had settled on as each season
                            began - the weights it would have had that day
    summary.json            the headline numbers, for anything that reads them
    verdict.json            the one-line answer the Model Lab shows (verdict.py)
    issues.json             everything left out or doubted, and why

The report says what the numbers can bear and no more: a gap is given with
the range it could lie in, and "cannot be told apart" is a finding.

No Qt here.
"""

from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .. import analytics
from ..model import modellab, predictions
from ..version import MODEL_NAME, VERSION as APP_VERSION
from . import VERSION, data, evaluate, features, recipes, registry
from .study import LIVE, Study, Trial

DEADEYE = f"{MODEL_NAME} at {predictions.CONSENSUS_WEIGHT:.0%}"
RIDGE = "Ridge on the line's error"
CHOSEN = f"{MODEL_NAME}, share chosen on the past"
RECENT_FLIPS = 12


# ---- small things ---------------------------------------------------------------------------------
def _table(headers: list[str], rows: list[list]) -> list[str]:
    if not rows:
        return ["_Nothing to show._", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out += ["| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |" for row in rows]
    return out + [""]


def _pct(value: float | None, digits: int = 1) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}%}"


def _num(value: float | None, digits: int = 3) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.{digits}f}"


def _signed(value: float | None, digits: int = 4) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:+.{digits}f}"


def _range(low: float, high: float, digits: int = 4) -> str:
    return "" if math.isnan(low) or math.isnan(high) else f"{low:+.{digits}f} to {high:+.{digits}f}"


def _seasons(seasons) -> str:
    seasons = sorted(set(int(s) for s in seasons))
    if not seasons:
        return "none"
    return str(seasons[0]) if len(seasons) == 1 else f"{seasons[0]}-{seasons[-1]}"


def _record(score: evaluate.Score) -> str:
    return f"{score.right} of {score.games} ({score.rate:.1%})" if score.games else "-"


def _luck(duel: evaluate.Duel) -> str:
    if duel.luck is None:
        return f"{duel.only_first} to {duel.only_second} on the games they split - too few to test"
    return f"{duel.only_first} to {duel.only_second} on the games they split ({duel.luck:.0%} by chance)"


# ---- the sections ---------------------------------------------------------------------------------
def _coverage(study: Study) -> list[str]:
    out = ["## 1. What there was to learn from", ""]
    history, now = study.history, study.now
    archived = history[history["source"] == "archive"] if "source" in history.columns else history.iloc[0:0]
    plain = history[history["source"] == "nflverse"] if "source" in history.columns else history.iloc[0:0]
    rows = []
    if len(archived):
        crowd = int((archived[data.model_columns(archived)].notna().sum(axis=1) >= features.ENOUGH_MODELS).sum())
        rows.append(["The Prediction Tracker's season archives", f"{len(archived):,}", _seasons(archived["season"]),
                     f"{crowd:,} with five or more computer models; opening and updated lines; final scores"])
    if len(plain):
        rows.append(["nflverse", f"{len(plain):,}", _seasons(plain["season"]),
                     "closing line, over/under, moneylines (2006 on), final scores - no computer models"])
    elif len(archived) and "line_closing" in archived.columns:
        rows.append(["nflverse (joined to the archives)", f"{int(archived['line_closing'].notna().sum()):,}",
                     _seasons(archived.loc[archived['line_closing'].notna(), 'season']),
                     "closing line, over/under, moneylines; used to check every archived score and side"])
    if len(now):
        graded = now[now["credited_home"].notna()]
        timed = int(graded["line_deadline"].notna().sum())
        crowd = int((graded[data.model_columns(graded)].notna().sum(axis=1) >= features.ENOUGH_MODELS).sum())
        rows.append([f"This season, on the dashboard's own records", f"{len(graded)} graded",
                     _seasons(now["season"]),
                     f"{timed} with a line known to have been taken by the pool's deadline; {crowd} with the "
                     "computer models; the commissioner's real lines"])
    out += _table(["Source", "Games", "Seasons", "What it carries"], rows)

    if not len(archived):
        wanted = data.archive_wanted()
        out += [
            "> **The main experiment is blocked on data, not on code.** Whether the computer models know anything "
            "the betting line does not can only be measured where each model's number is kept game by game, and "
            f"on disk that is this season's {len(now[now['credited_home'].notna()]) if len(now) else 0} games. "
            "The Prediction Tracker publishes exactly that for every season since 1999 - one file a season, "
            f"`{wanted[0][1]}` to `{wanted[-1][1]}`, about 2 MB in all - at "
            "`https://www.thepredictiontracker.com/nflarchive.html`. Nothing was fetched: put them in "
            "`data/tracker/archive/` (or say the word and `python -m acql.training fetch` will) and run this "
            "again. Everything below that needs the models says so.",
            "",
        ]
    else:
        by = data.models_by_season(archived)
        out += ["Season by season, the archives hold:", ""]
        out += _table(["Season", "Games", "With 5+ models", "Models a game", "Opening line", "Midweek line",
                       "Updated line", "Closing line (nflverse)"],
                      [[r.season, r.games, r.with_models, f"{r.models_a_game:.0f}", r.opening, r.midweek, r.updated,
                        r.closing] for r in by.itertuples()])
    out += _lines_apart(archived)
    for key, found in study.trials.items():
        cover = features.coverage(found.prepared, features.CORE + features.EXTRAS)
        out += [f"Inputs, {found.result.setting.title.lower()} ({len(found.prepared):,} games):", ""]
        out += _table(["Input", "What it is", "Games with it", "Share", "Seasons"],
                      [[r.column, features.ABOUT.get(r.column, ""), f"{r.games:,}", _pct(r.share), r.seasons]
                       for r in cover.itertuples()])
    if not study.trials and study.lines_only is not None:
        cover = features.coverage(study.lines_only.prepared, ("market",) + features.EXTRAS + features.CORE[:5])
        out += [f"Inputs, {study.lines_only.result.setting.title.lower()} ({len(study.lines_only.prepared):,} games):", ""]
        out += _table(["Input", "What it is", "Games with it", "Share", "Seasons"],
                      [[r.column, features.ABOUT.get(r.column, ""), f"{r.games:,}", _pct(r.share), r.seasons]
                       for r in cover.itertuples()])
    out += ["Not kept anywhere for past seasons, so not an input: **when** each line and each model's number was "
            "taken. The archives hold a week as it stood when the site last updated it; only the dashboard's own "
            "records carry times, and only from this season. See section 7.", ""]
    return out


LINE_NAMES = {"line_opening": "the opening line", "line_midweek": "the midweek line",
              "line_updated": "the line as last updated", "line_closing": "the closing line (nflverse)"}


def _lines_apart(archived: pd.DataFrame) -> list[str]:
    """How much the line moves between one of the archive's numbers and the
    next - which is how much later than a Thursday card each one is."""
    rows = []
    for first, second in (("line_opening", "line_midweek"), ("line_opening", "line_updated"),
                          ("line_midweek", "line_updated"), ("line_updated", "line_closing")):
        if first not in archived.columns or second not in archived.columns:
            continue
        both = archived[[first, second, "actual"]].dropna()
        if len(both) < 100:
            continue
        apart = (both[first] - both[second]).abs()
        rows.append([f"{LINE_NAMES[first]} to {LINE_NAMES[second]}", f"{len(both):,}", _num(float(apart.mean()), 2),
                     _pct(float((apart >= 0.5).mean()), 0),
                     _num(float((both[first] - both["actual"]).abs().mean()), 2),
                     _num(float((both[second] - both["actual"]).abs().mean()), 2)])
    if not rows:
        return []
    return ["How far the line moves from one of these numbers to the next, and how far each lands from the result "
            "(the pool's Thursday deadline falls about where the midweek line does):", ""] + _table(
        ["From - to", "Games with both", "Points apart, on average", "Moved half a point or more",
         "Avg miss, the earlier", "Avg miss, the later"], rows)


def _compare(trial: Trial, names: list[str], keep: np.ndarray, title: str) -> list[str]:
    found = trial.marks(keep, names)
    if not found or not next(iter(found.values())).games:
        return [f"**{title}** - no games.", ""]
    rows = []
    for name in names:
        s = found[name]
        row = [name, s.games, _record(s), _num(s.expected, 1), _num(s.logloss, 4), _num(s.brier, 4), _pct(s.off),
               _num(s.miss, 2), _num(s.rms, 2), _signed(s.lean, 2)]
        if name == recipes.LINE:
            row += ["-", "-", "the bar"]
        else:
            d = trial.against(name, recipes.LINE, keep)
            row += [_signed(d.edge), _range(d.low, d.high), d.reading]
        rows.append(row)
    return [f"**{title}** - {next(iter(found.values())).games:,} games every recipe priced", ""] + _table(
        ["Recipe", "Games", "Credited picks right", "Expected right", "Log loss", "Brier", "Chances off by",
         "Avg miss", "RMS miss", "Lean to home", "Log loss better than the line", "Could lie in", "Reading"], rows)


def _headline_names(trial: Trial, extra: str | None = None) -> list[str]:
    names = [n for n in recipes.HEADLINE if n in trial.together]
    if extra and extra not in names and extra in trial.together:
        names.append(extra)
    return names


def _split(trial: Trial) -> tuple[list[int], list[int]]:
    """(the seasons recipes were judged and chosen on, the seasons held back)."""
    held = trial.result.held_back()
    return [s for s in trial.result.seasons if s not in held], held


def _hybrid(trial: Trial) -> tuple[str | None, list[int], list[int]]:
    """(the hybrid that emerged on the seasons recipes were judged on, those seasons, the seasons held back)."""
    judged, held = _split(trial)
    return trial.emerged(judged or None), judged, held


def _comparison(study: Study) -> list[str]:
    out = ["## 2. The comparison - every recipe on the same games", ""]
    if not study.trials:
        out += ["Not run: it needs the computer models game by game (section 1).", ""]
        if study.lines_only is not None:
            only = study.lines_only
            out += ["What could be run without them - the closing line, and a ridge regression on the line's own "
                    "numbers (the moneyline, the over/under, rest, division) - is here as a check that the "
                    "pipeline does not find edges that are not there:", ""]
            out += _compare(only, only.together, only.keep, f"{only.result.setting.title}, {_seasons(only.result.seasons)}")
        return out
    out += ["Each recipe was tuned on the seasons before each season, taught again as each week began on every "
            "earlier game, and asked about that week's games without their results. Chances come from the "
            "dashboard's own curve for all of them, so only the margins differ. Pool lines for past seasons are "
            "the commissioner's habit applied to each game's earliest line (`backtest.pool_line`), not lines he "
            "posted.", ""]
    for key, trial in study.trials.items():
        setting = trial.result.setting
        hybrid, judged, held = _hybrid(trial)
        names = _headline_names(trial, hybrid)
        out += [f"### {setting.title}", "", setting.about, ""]
        out += _compare(trial, names, trial.keep, f"Every season asked about ({_seasons(trial.result.seasons)})")
        if held:
            if hybrid:
                lead = trial.against(hybrid, recipes.LINE, trial.within(judged))
                out += [f"**The best validated hybrid: {hybrid}.** Over {_seasons(judged)}, the seasons used to judge "
                        f"the challengers, it was the one furthest ahead of the line whose whole range was above zero "
                        f"({_signed(lead.edge)} a game, {_range(lead.low, lead.high)}). The seasons after were held "
                        "back - nothing about any recipe was chosen by looking at them:", ""]
            else:
                out += [f"**No hybrid emerged.** Over {_seasons(judged)}, the seasons used to judge the challengers, "
                        "not one of them was ahead of the line by more than the games could vouch for - there is "
                        "nothing to carry forward. The seasons after were held back all the same, and nothing about "
                        "any recipe was chosen by looking at them:", ""]
            out += _compare(trial, names, trial.within(held), f"Held back ({_seasons(held)})")
        late = [n for n in trial.names if n not in trial.together]
        for name in late:
            keep = trial.result.common([name, recipes.LINE, DEADEYE] if DEADEYE in trial.names else [name, recipes.LINE])
            d = trial.against(name, recipes.LINE, keep)
            out += [f"{name} could only be grown once there were {recipes.MIN_TREES:,} games to teach it on, so it "
                    f"is marked on its own {d.games:,} games ({_seasons(trial.result.games.loc[keep, 'season'])}): "
                    f"log loss {_signed(d.edge)} a game against the line (could lie in {_range(d.low, d.high)}) - "
                    f"{d.reading}.", ""]
    head = study.headline
    out += ["<details><summary>Every recipe tried, " + head.result.setting.title.lower() + "</summary>", ""]
    out += _compare(head, head.together, head.keep, f"Every season asked about ({_seasons(head.result.seasons)})")
    out += ["</details>", ""]
    return out


def _by_season(study: Study) -> list[str]:
    out = ["## 3. Season by season, and week by week", ""]
    head = study.headline
    if head is None:
        out += ["Not run without the computer models.", ""]
        return out
    hybrid, judged, held = _hybrid(head)
    names = [n for n in dict.fromkeys((recipes.LINE, DEADEYE, RIDGE, hybrid)) if n and n in head.together]
    table = evaluate.by_group(head.result, head.chances, names, head.keep, "season")
    rows, ahead = [], {n: 0 for n in names if n != recipes.LINE}
    seasons = sorted(set(table["season"].tolist()))
    for season in seasons:
        mine = table[table["season"] == season].set_index("recipe")
        base = mine.loc[recipes.LINE]
        row = [f"{season}{' (held back)' if season in held else ''}", int(base["games"]),
               f"{int(base['right'])} ({base['rate']:.1%})"]
        for name in names[1:]:
            edge = base["logloss"] - mine.loc[name, "logloss"]
            ahead[name] += edge > 0
            row += [f"{int(mine.loc[name, 'right'])} ({mine.loc[name, 'rate']:.1%})", _signed(edge)]
        rows.append(row)
    headers = ["Season", "Games", "The line: right"]
    for name in names[1:]:
        headers += [f"{name}: right", "Log loss better than the line"]
    out += [f"{head.result.setting.title}. A recipe that is really better is better in most seasons, not in one "
            "good stretch.", ""]
    out += _table(headers, rows)
    out += ["Seasons ahead of the line on log loss: "
            + "; ".join(f"**{name}** {count} of {len(seasons)}" for name, count in ahead.items()) + ".", ""]
    for key, trial in study.trials.items():
        if trial is head or DEADEYE not in trial.together:
            continue
        other = evaluate.by_group(trial.result, trial.chances, [recipes.LINE, DEADEYE], trial.keep, "season")
        count = total = 0
        for season in sorted(set(other["season"].tolist())):
            mine = other[other["season"] == season].set_index("recipe")
            count += mine.loc[recipes.LINE, "logloss"] > mine.loc[DEADEYE, "logloss"]
            total += 1
        out += [f"{trial.result.setting.title}: {DEADEYE} was ahead of the line on log loss in {count} of {total} "
                "seasons.", ""]
    weekly = evaluate.by_group(head.result, head.chances, names, head.keep, "week")
    rows = []
    for week in sorted(set(weekly["week"].tolist())):
        mine = weekly[weekly["week"] == week].set_index("recipe")
        base = mine.loc[recipes.LINE]
        row = [week, int(base["games"]), _pct(base["rate"])]
        for name in names[1:]:
            row += [_pct(mine.loc[name, "rate"]), _signed(base["logloss"] - mine.loc[name, "logloss"])]
        rows.append(row)
    headers = ["Week of the season", "Games", "The line: right"]
    for name in names[1:]:
        headers += [f"{name}: right", "Log loss better than the line"]
    out += ["The same by week of the season, every season together:", ""] + _table(headers, rows)
    return out


def _nudge_table(trial: Trial, keep: np.ndarray, title: str) -> list[str]:
    names = [n for n in recipes.NUDGE_TEST if n in trial.together]
    found = trial.marks(keep, names)
    rows = []
    for name in names:
        s = found[name]
        if name == recipes.LINE:
            rows.append(["No nudge (the line)", _record(s), _num(s.logloss, 4), "-", "-", _num(s.miss, 3), "-", "the bar"])
            continue
        d = trial.against(name, recipes.LINE, keep)
        rows.append([name, _record(s), _num(s.logloss, 4), _signed(d.edge), _range(d.low, d.high),
                     _num(s.miss, 3), _signed(d.closer, 3), d.reading])
    return [f"**{title}**", ""] + _table(
        ["Share of the models believed", "Credited picks right", "Log loss", "Better than the line", "Could lie in",
         "Avg miss", "Points closer than the line", "Reading"], rows)


def _nudge(study: Study) -> list[str]:
    out = ["## 4. The 33% nudge, tested", ""]
    if not study.trials:
        out += ["Not run without the computer models. On this season's own games every share is scored in the last "
                "section, on far too few games to choose between them.", ""]
        return out
    out += ["The picks' own rule, run by the picks' own code, at each share of the models' disagreement with the "
            "line - and at the share the results before each season would have chosen. A fixed share's row is that "
            "share used throughout, whatever the results said; no share was chosen on the games it is scored on.", ""]
    for key, trial in study.trials.items():
        title = trial.result.setting.title
        out += [f"### {title}", ""]
        out += _nudge_table(trial, trial.keep, f"Every season asked about ({_seasons(trial.result.seasons)})")
        _, held = _split(trial)
        if held and trial is study.headline:
            out += _nudge_table(trial, trial.within(held), f"Held back ({_seasons(held)})")
        chosen = [f for f in trial.result.fits if f["recipe"] == CHOSEN]
        trained = [f for f in trial.result.fits if f["recipe"] == "Trained nudge" and f.get("per unit")]
        if chosen:
            shares = [f["share"] for f in chosen]
            counts = {s: shares.count(s) for s in sorted(set(shares))}
            out += ["**What the results before each season would have chosen.** Going into each of "
                    f"{len(chosen)} seasons, the smallest share the best-scoring one did not clearly beat was: "
                    + ", ".join(f"{share:.0%} ({n} season{'s' if n != 1 else ''})" for share, n in counts.items())
                    + f". Going into {chosen[-1]['season']}: **{chosen[-1]['share']:.0%}**.", ""]
        if trained:
            slopes = [f["per unit"].get("gap", 0.0) for f in trained]
            out += ["**The trained nudge** - the share a regression on every earlier game arrives at, after its "
                    f"pull toward none - ran from {min(slopes):.0%} to {max(slopes):.0%} across the seasons and "
                    f"stands at **{slopes[-1]:.0%}** going into {trained[-1]['season']}.", ""]
        straight = [f for f in trial.result.fits if f["recipe"] == "Straight-line fit" and f.get("per unit")]
        if straight:
            last = straight[-1]
            out += [f"With no pull at all, a straight line through every game before {last['season']} puts the share "
                    f"at **{last['per unit'].get('gap', 0.0):.0%}** ({last['taught']:,} games).", ""]
    return out


def _curve(study: Study) -> list[str]:
    out = ["## 5. The curve - from a margin to a chance", ""]
    found = study.curves
    if found is None:
        out += ["Not run.", ""]
        return out
    keep = found.keep()
    seasons = _seasons(found.games.loc[keep, "season"])
    out += [f"Marked on the market's own margin ({found.setting.title.lower()}, {seasons}), so the only thing that "
            "differs is the step from margin to chance. Each alternative was taught on the seasons before the one "
            "it was marked on. The curve in use was not: its constants were set by hand on results from 2010 to "
            "2025, most of the seasons it is marked on here, which flatters it - an alternative has to beat a "
            "curve that has already seen the answers.", ""]
    for which, title in (("all", "Every game"), ("lined", "Games with a pool line"), ("straight", "Straight-up games")):
        rows = []
        for name in found.chances:
            s = found.score(name, which)
            if not s.games:
                continue
            row = [name, s.games, _record(s), _num(s.expected, 1), _num(s.logloss, 4), _num(s.brier, 4), _pct(s.off)]
            if name == "In use":
                row += ["-", "-", "the bar"]
            else:
                d = found.against(name, which)
                row += [_signed(d.edge), _range(d.low, d.high), d.reading]
            rows.append(row)
        out += [f"**{title}**", ""] + _table(
            ["Curve", "Games", "Credited picks right", "Expected right", "Log loss", "Brier", "Chances off by",
             "Log loss better than in use", "Could lie in", "Reading"], rows)
    out += ["What each is: " + " ".join(f"**{name}** - {about}" for name, about in found.about.items()), ""]
    refit = found.states.get("Refitted", {})
    recal = found.states.get("Recalibrated", {})
    if refit:
        out += [f"Taught on everything to the last season, the refitted curve's widths come out at "
                f"{refit.get('narrow')} points for the ordinary game (in use: {analytics.SPREAD_SD:g}), a wide bell "
                f"{refit.get('ratio')} times wider (in use: {analytics.TAIL_RATIO:g}) carrying "
                f"{refit.get('share'):.0%} of games (in use: {analytics.TAIL_SHARE:.0%})."
                + (f" The recalibration stretches the chances in use by {recal.get('stretch', 1):.2f} "
                   f"(1.00 is no change; under 1 means they were too sure)." if recal else ""), ""]
    rows = []
    bands = {name: evaluate.reliability(found.chances[name][keep], found.games["credited"].to_numpy(dtype=float)[keep])
             for name in found.chances}
    for i, band in enumerate(bands["In use"]):
        row = [band["band"]]
        for name in found.chances:
            b = bands[name][i]
            row += [b["picks"], _pct(b["said"]), _pct(b["came"])]
        rows.append(row)
    headers = ["How sure of its side"]
    for name in found.chances:
        headers += [f"{name}: picks", "said", "came in"]
    out += ["Reliability - the picks by how sure each curve was, against how often they came in:", ""]
    out += _table(headers, rows)
    return out


def _flips(study: Study, folder: Path | None) -> list[str]:
    out = ["## 6. Games where the side changed", ""]
    head = study.headline
    if head is None:
        out += ["Not run without the computer models.", ""]
        return out
    hybrid, judged, held = _hybrid(head)
    pairs = [(DEADEYE, recipes.LINE, "what the nudge changes"), (RIDGE, recipes.LINE, "what the regression changes"),
             (RIDGE, DEADEYE, "what the challenger would change on the card")]
    if hybrid and hybrid not in (DEADEYE, RIDGE):
        pairs.append((hybrid, recipes.LINE, "what the hybrid changes"))
    out += [f"{head.result.setting.title}, {int(head.keep.sum()):,} games. A recipe only matters to the pool in the "
            "games where it takes the other side.", ""]
    rows, listed = [], None
    for name, other, what in pairs:
        if name not in head.together or other not in head.together:
            continue
        table = evaluate.changed_sides(head.result, head.chances, name, other, head.keep)
        helped = int(table["helped"].sum()) if len(table) else 0
        luck = modellab.Pair(games=len(table), first=helped, second=len(table) - helped).luck if len(table) else None
        late = table[table["season"].isin(held)] if len(table) and held else table.iloc[0:0]
        rows.append([f"{name} v {other}", what, len(table), helped, len(table) - helped,
                     "too few to test" if luck is None else f"{luck:.0%}",
                     f"{int(late['helped'].sum())} of {len(late)}" if held else ""])
        if folder is not None and len(table):
            slug = "-".join("".join(c if c.isalnum() else " " for c in f"{name} v {other}".casefold()).split())
            table.to_csv(folder / f"changed-sides-{slug}.csv", index=False)
        if (name, other) == (RIDGE, DEADEYE):
            listed = table
    out += _table(["Pair", "", "Games on different sides", "The change was right", "Wrong",
                   "A split that lopsided by luck alone", f"Right, held back ({_seasons(held)})" if held else ""], rows)
    out += ["Every one of these games is in the run's folder (`changed-sides-*.csv`), with both margins, the side "
            "taken and how it came out.", ""]
    if listed is not None and len(listed):
        recent = listed.tail(RECENT_FLIPS)
        out += [f"The latest {len(recent)} where {RIDGE} would have changed {DEADEYE}'s side:", ""]
        out += _table(["Season", "Week", "Game", "Line (home)", "Pool line", f"{DEADEYE} made it", f"{RIDGE} made it",
                       "It took", "Chance", "Final (home)", "Credited", "Helped"],
                      [[r["season"], r["week"], r["game"], f"{r['line']:+g}", r["pool line"],
                        f"{r[f'{DEADEYE} margin']:+.1f}", f"{r[f'{RIDGE} margin']:+.1f}", r[f"{RIDGE} took"],
                        _pct(r[f"{RIDGE} chance"]),
                        "" if r["final margin (home)"] is None else f"{r['final margin (home)']:+g}",
                        r["credited"], "yes" if r["helped"] else "no"] for _, r in recent.iterrows()])
    return out


def _limits(study: Study) -> list[str]:
    out = ["## 7. How sure any of this is, and what it cannot say", ""]
    points = [
        "**A record is not a rate.** A recipe that is truly 1% better at picking credited sides gets about one "
        "extra game right in a hundred; over this season's games that is under one game. Every gap above is given "
        "with the range it could plausibly lie in (whole weeks drawn again 2,000 times), and a range that takes in "
        "zero means the games cannot tell the two apart.",
        "**The archives have no clock.** Each archived game holds the models' numbers and the line as the site "
        "last updated them that week. A Thursday card could have seen the opening line for certain; the updated "
        "line may be from the weekend. So the comparison is run against each line the archive has, and the truth "
        "for a Thursday deadline lies between the opening line and the updated one: against the opening line the "
        "models look better than a Thursday card would find them (part of their 'edge' is news the market had "
        "priced by Thursday), and against the updated line they look worse (the line has had days more to learn). "
        "The midweek line, kept since 2013, is the fairest of the three.",
        "**Pool lines for past seasons are a rule, not a record.** They are the commissioner's measured habit "
        "applied to each game's earliest line. Straight-up games need no such stand-in, and the curve is scored on "
        "the two kinds separately.",
        "**The constants in use have seen these seasons.** The margin curve and the Big Loser weights were set on "
        "results through 2025. Marked on those same seasons they are flattered, which only makes an alternative's "
        "job harder.",
        "**Many recipes were tried.** The best of a dozen looks better than it is. That is why the seasons at the "
        "end were held back and why the Model Lab's rule asks for games a recipe had not seen.",
    ]
    if study.drift:
        d = study.drift
        text = (f"**How late is the archive? Measured on this season:** {d['games']} games are in both the "
                "dashboard's records and the archive (as the site left the week).")
        if d.get("forecasts"):
            text += (f" Across {d['forecasts']:,} model forecasts the dashboard read in before a deadline, "
                     f"{_pct(d.get('unchanged'))} are the same number in the archive (average difference "
                     f"{d.get('model_gap', 0):.2f} points): the models do not move late in the week, so the archive's "
                     "models are the ones a Thursday card saw.")
        if d.get("line_games"):
            text += (f" The line does move: between the pool's deadline and the archive's last update it differed by "
                     f"half a point or more in {d['line_moved']} of {d['line_games']} games (average "
                     f"{d['line_gap']:.2f} points).")
        if d.get("midweek_games"):
            text += (f" The archive's midweek line sat {d['midweek_gap']:.2f} points from the dashboard's deadline "
                     f"line on average ({d['midweek_moved']} of {d['midweek_games']} games half a point or more "
                     "apart) - it is the nearest thing in the archive to the line a Thursday card is priced from.")
        points.append(text)
    for title, cut, ok, what in study.seals:
        points.append(f"**Nothing leaked backwards** ({title.lower()}, cut at week {cut % 100} of {cut // 100}): "
                      + ("" if ok else "FAILED - ") + what + ".")
    out += [f"- {p}" for p in points] + [""]
    return out


def _promotion(study: Study) -> list[str]:
    out = ["## 8. The Model Lab's rule for a switch", "",
           f"Unchanged: a challenger replaces {MODEL_NAME} only with **{modellab.ENOUGH_GAMES} games** both priced "
           f"going in, a log loss at least **{modellab.CLEARLY_BETTER:.3f}** a game lower on them, and no fewer "
           "credited picks right. Those are games priced live, before they were played - and no challenger here has "
           "priced one. So under the rule as it stands the answer for every recipe is **0 of "
           f"{modellab.ENOUGH_GAMES} games: not eligible**.", ""]
    head = study.headline
    if head is None or DEADEYE not in head.together:
        return out
    hybrid, judged, held = _hybrid(head)
    wanted = dict.fromkeys((recipes.LINE, RIDGE, "Ridge, model by model", "Weighted crowd", "Trained nudge",
                            "Straight-line fit", CHOSEN, hybrid))
    rows = []
    for name in wanted:
        if not name or name == DEADEYE or name not in head.together:
            continue
        whole = evaluate.standing(head.against(name, DEADEYE))
        late = evaluate.standing(head.against(name, DEADEYE, head.within(held))) if held else None
        rows.append([name, whole.games, _signed(whole.edge), f"{whole.right} v {whole.service_right}", whole.verdict]
                    + ([late.games, _signed(late.edge), f"{late.right} v {late.service_right}", late.verdict]
                       if late else []))
    headers = ["Challenger", "Games", f"Log loss better than {DEADEYE}", "Right, it v it", "By the rule's numbers"]
    if held:
        headers += [f"Held back ({_seasons(held)}): games", "Log loss better", "Right", "By the rule's numbers"]
    out += ["For scale only, here is how each would read if the walk-forward's games were allowed to count - "
            f"against {DEADEYE}, the same rule and the same thresholds ({head.result.setting.title.lower()}):", ""]
    out += _table(headers, rows)
    out += ["A backtest clearing the bar would be a reason to start the clock on a challenger, not to end it. None "
            "clears it." if not any(r[4] == "has earned the switch" for r in rows) else
            "A backtest clearing the bar is a reason to start the clock on a challenger, not to end it.", ""]
    return out


def _switch(study: Study) -> list[str]:
    out = ["## 9. Before a switch would be justified", ""]
    steps = []
    if not study.has_models:
        steps.append("Get the season archives on disk and run this again. Until then there is no challenger to "
                     "speak of - only this season's games, which cannot separate anything.")
    steps += [
        "Freeze each week's inputs at the pool's deadline (`python -m acql.training snapshot`, run before "
        "Thursday 6 pm, or added to the scheduled job), so that from now on every game has the line, the "
        "moneyline, the over/under and every model's number as they stood then, with the time on them.",
        "Put the chosen challenger in the Model Lab as one more recipe, priced live each week from its saved "
        "weights (`data/training/models`) and never used for the card, until it has the "
        f"{modellab.ENOUGH_GAMES} games the rule asks for.",
        "Require the same thing of it there that the rule already requires - and that its lead over the line shows "
        "in more than one season, not one hot month.",
        f"Only then change the card, and keep {MODEL_NAME} as it is now running beside it as the fallback: the live "
        "model must go on working if a taught one cannot be loaded.",
    ]
    out += [f"{i}. {step}" for i, step in enumerate(steps, start=1)] + [""]
    return out


def _routs(study: Study) -> list[str]:
    out = ["## Big Losers (a separate experiment)", ""]
    found = study.routs
    if found is None:
        out += ["Not run.", ""]
        return out
    out += [f"Both teams of {found.games:,} games over {found.weeks} weeks ({found.setting.lower()}). The chance of "
            "losing by 15 or more is read off the dashboard's own Big Loser curve from each recipe's margin, the "
            "curve's weights taught again each season on the seasons before. Three picks a week, the likeliest "
            "first.", ""]
    out += _table(["Margin from", "Log loss", "Brier", "Said, on average", "Happened", "Points a week from 3 picks",
                   "Its chances expected", "Log loss better than the line", "Could lie in"],
                  [[r["source"], _num(r["logloss"], 4), _num(r["brier"], 4), _pct(r["said"]), _pct(r["came"]),
                    _num(r["points"], 3), _num(r["expected"], 3),
                    "-" if i == 0 else _signed(r["edge"]), "-" if i == 0 else _range(r["low"], r["high"])]
                   for i, r in enumerate(found.rows)])
    out += ["\"Weights as in use\" are the dashboard's own, which were taught on every season to 2025 and so have "
            "seen these games.", ""]
    return out


def _this_season(study: Study) -> list[str]:
    out = [f"## This season, on the dashboard's own records", ""]
    if not study.seasons:
        out += ["Not available - the dashboard's records for this season could not be read, or hold no graded games.", ""]
        return out
    out += ["Far too few games to tell any two recipes apart - shown because they are the only games whose lines "
            "carry a time, and because this is the table the dashboard's own record is read from.", ""]
    for found in study.seasons:
        marks = found.marks()
        games = int(found.keep.sum())
        weeks = sorted(set(found.games.loc[found.keep, "week"].tolist()))
        rows = []
        for name, s in marks.items():
            row = [name, _record(s), _num(s.expected, 1), _num(s.logloss, 4), _num(s.brier, 4), _num(s.miss, 2)]
            if name == recipes.LINE:
                row += ["-", "-", "-"]
            else:
                d = found.against(name)
                row += [_signed(d.edge), _range(d.low, d.high), d.sides]
            rows.append(row)
        out += [f"**{found.title}** - {games} graded games, weeks {', '.join(str(w) for w in weeks)}. {found.about}", ""]
        out += _table(["Recipe", "Credited picks right", "Expected right", "Log loss", "Brier", "Avg miss",
                       "Log loss better than the line", "Could lie in", "Games on the other side from the line"], rows)
    if study.taught:
        out += ["The taught recipes above learned from every archived season before this one and were then asked "
                "about this season's games on the line as it stood at the pool's deadline - the nearest thing "
                "there is yet to a live test, and far short of one.", ""]
    return out


def _short(study: Study) -> list[str]:
    out = ["## The short of it", ""]
    points = []
    if study.has_models:
        head = study.headline
        hybrid, judged, held = _hybrid(head)
        points.append(f"**Data:** {len(study.history):,} finished games from {_seasons(study.history['season'])} with "
                      "every computer model's number beside the line and the result. The first three seasons are only "
                      "taught from; every later game was priced by recipes that had seen only the games before it.")
        for key, trial in study.trials.items():
            if DEADEYE not in trial.together:
                continue
            marks = trial.marks(None, [recipes.LINE, DEADEYE])
            d = trial.against(DEADEYE)
            points.append(f"**{trial.result.setting.title}** ({d.games:,} games, {_seasons(trial.result.seasons)}): "
                          f"the line alone {_record(marks[recipes.LINE])}, {DEADEYE} {_record(marks[DEADEYE])}. "
                          f"Log loss {_signed(d.edge)} a game against the line (could lie in {_range(d.low, d.high)}): "
                          f"{d.reading}.")
        if held and DEADEYE in head.together:
            keep = head.within(held)
            marks = head.marks(keep, [recipes.LINE, DEADEYE])
            d = head.against(DEADEYE, recipes.LINE, keep)
            points.append(f"**The seasons held back ({_seasons(held)}), {head.result.setting.title.lower()}:** the "
                          f"line {_record(marks[recipes.LINE])}, {DEADEYE} {_record(marks[DEADEYE])}; log loss "
                          f"{_signed(d.edge)} (could lie in {_range(d.low, d.high)}): {d.reading}.")
        chosen = [f["share"] for f in head.result.fits if f["recipe"] == CHOSEN]
        if chosen:
            none = sum(1 for share in chosen if share == 0)
            points.append(f"**The 33%:** going into each of {len(chosen)} seasons, the share of the models' view that "
                          f"the results so far could justify was none at all in {none} of them, and it is "
                          f"**{chosen[-1]:.0%}** going into this one. Shares of 50% and up are worse than the line "
                          "outright (section 4).")
        found = [(t.result.setting.title.lower(), _hybrid(t)[0]) for t in study.trials.values()]
        if any(name for _, name in found):
            points.append("**A hybrid:** " + "; ".join(
                f"{title}, {name} was ahead of the line by more than chance on the seasons used to judge it"
                if name else f"{title}, none emerged" for title, name in found) + " (section 2).")
        else:
            points.append("**A hybrid:** none emerged. On the seasons used to judge them, no challenger - ridge, "
                          "weighted crowd, trained nudge, trees - was ahead of any of the three lines by more than "
                          "the games could vouch for. (Against the opening line alone a small share of the models "
                          "does edge ahead once every season is counted - section 4 - but a Thursday card is not "
                          "priced from the opening line.)")
    else:
        points.append("**The main experiment could not be run.** The computer models are kept game by game for "
                      "this season only; the season archives that hold them back to 1999 are not on disk "
                      "(section 1 says exactly what to fetch). The pipeline is built and was run on everything "
                      "that is here.")
        if study.lines_only is not None:
            only = study.lines_only
            name = next((n for n in only.together if n != recipes.LINE), None)
            if name:
                d = only.against(name)
                points.append(f"**A check that it does not find edges that are not there:** a ridge regression on "
                              f"the closing line's own numbers, over {d.games:,} games from "
                              f"{_seasons(only.result.seasons)}, came out {_signed(d.edge)} a game against the line "
                              f"(could lie in {_range(d.low, d.high)}: {d.reading}).")
    if study.curves is not None:
        found = study.curves
        rivals = [n for n in found.chances if n != "In use"]
        best_curve = min(rivals, key=lambda n: found.score(n).logloss)
        d = found.against(best_curve)
        in_use = found.score("In use")
        points.append(f"**The curve:** the best alternative, {best_curve.lower()}, scored {_signed(d.edge)} a game "
                      f"against the curve in use over {d.games:,} games (could lie in {_range(d.low, d.high)}: "
                      f"{d.reading}). The curve in use expected {in_use.expected:,.0f} credited picks right and "
                      f"{in_use.right:,} were: a shade too sure, not enough to matter.")
    if study.routs is not None and len(study.routs.rows) > 1:
        rows = {r["source"]: r for r in study.routs.rows}
        if DEADEYE in rows:
            r = rows[DEADEYE]
            points.append(f"**Big Losers:** reading the 15-point chance off {DEADEYE}'s margin rather than the "
                          f"line's scored {_signed(r['edge'])} a team (could lie in {_range(r['low'], r['high'])}) - "
                          "no better than the line alone.")
    for found in study.seasons:
        if LIVE in found.margins:
            marks = found.marks()
            d = found.against(LIVE)
            points.append(f"**This season:** {MODEL_NAME} {_record(marks[LIVE])}, the line {_record(marks[recipes.LINE])} "
                          f"- they took different sides in {d.sides} games, {_luck(d)}.")
    points.append(f"**The rule:** nothing has earned a switch. {MODEL_NAME} is unchanged, and nothing here can "
                  "change it.")
    errors = study.notes.of("error")
    if errors:
        points.append(f"**Left out:** {sum(i.rows for i in errors):,} rows across {len(errors)} problems - listed "
                      "at the end.")
    out += [f"- {p}" for p in points] + [""]
    return out


def _issues(study: Study) -> list[str]:
    out = ["## Everything left out or doubted", ""]
    if not study.notes.items:
        return out + ["Nothing.", ""]
    out += _table(["", "What", "Rows", "Detail"],
                  [[i.level, i.code, i.rows or "", i.detail] for i in study.notes.items])
    return out


def _again(folder: Path | None) -> list[str]:
    return ["## Running it again", "",
            "From the project folder (in VS Code: Terminal > Run Task, or Run and Debug > *Deadeye training*):", "",
            "```", ".venv\\Scripts\\python.exe -m acql.training run        the whole thing (this report)",
            ".venv\\Scripts\\python.exe -m acql.training audit      what data there is, and nothing else",
            ".venv\\Scripts\\python.exe -m acql.training snapshot   freeze this week's inputs at the deadline",
            ".venv\\Scripts\\python.exe -m acql.training check      the no-leak check on its own",
            ".venv\\Scripts\\python.exe tests\\test_training.py      the tests", "```", ""]


# ---- the picture ----------------------------------------------------------------------------------
CHART = "calibration.png"


def chart(study: Study, folder: Path) -> bool:
    """Said against came in, drawn: the curves on the left, the recipes on the
    right. A line on the diagonal means its chances were honest. Whether it
    was drawn - a report stands without its picture."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return False
    panels = []
    if study.curves is not None:
        found = study.curves
        keep = found.keep()
        came = found.games["credited"].to_numpy(dtype=float)[keep]
        panels.append((f"The curve - {found.setting.title.lower()}",
                       {name: evaluate.reliability(said[keep], came, evaluate.ECE_BANDS)
                        for name, said in found.chances.items()}))
    head = study.headline
    if head is not None:
        hybrid, _, _ = _hybrid(head)
        names = [n for n in (recipes.LINE, DEADEYE, RIDGE, hybrid) if n and n in head.together]
        came = head.result.games["credited"].to_numpy(dtype=float)[head.keep]
        panels.append((f"The recipes - {head.result.setting.title.lower()}",
                       {name: evaluate.reliability(head.chances[name][head.keep], came, evaluate.ECE_BANDS)
                        for name in dict.fromkeys(names)}))
    if not panels:
        return False
    try:
        figure, axes = plt.subplots(1, len(panels), figsize=(6.4 * len(panels), 5.6), squeeze=False)
        for axis, (title, lines) in zip(axes[0], panels):
            axis.plot([0.5, 0.95], [0.5, 0.95], color="#888888", linewidth=1, linestyle="--", label="honest")
            for name, bands in lines.items():
                shown = [b for b in bands if b["picks"] >= 25]
                axis.plot([b["said"] for b in shown], [b["came"] for b in shown], marker="o", linewidth=1.6,
                          markersize=5, label=name)
            axis.set_title(title, fontsize=11)
            axis.set_xlabel("How sure it said it was of its side")
            axis.set_ylabel("How often that side was credited")
            axis.set_xlim(0.49, 0.9)
            axis.set_ylim(0.44, 0.9)
            axis.grid(True, alpha=0.25)
            axis.legend(fontsize=8, loc="upper left")
        figure.tight_layout()
        figure.savefig(folder / CHART, dpi=120)
        plt.close(figure)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- the whole report ------------------------------------------------------------------------------
def render(study: Study, folder: Path | None = None) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(study.started or time.time()))
    out = [f"# {MODEL_NAME} training report", "",
           f"Run {stamp} - training {VERSION}, dashboard {APP_VERSION} - took {study.took:.0f} seconds. Every margin "
           "is points for the home team. Nothing in this report changes a pick.", ""]
    for section in (_short, _coverage, _comparison, _by_season, _nudge, _curve):
        out += section(study)
    if folder is not None and chart(study, folder):
        out += [f"![Said against came in]({CHART})", "",
                "_Each point is a band of picks (25 or more): how sure the chances said they were, against how often "
                "the side was credited. On the dashed line the chances were honest; below it they were too sure._", ""]
    out += _flips(study, folder)
    for section in (_limits, _promotion, _switch, _routs, _this_season, _issues):
        out += section(study)
    out += _again(folder)
    return "\n".join(out)


def _predictions(trial: Trial) -> pd.DataFrame:
    games = trial.result.games
    keep = trial.result.asked
    table = games.loc[keep, ["season", "week", "game", "home", "away", "market", "opening", "pool_line",
                             "pool_favourite", "n_models", "actual", "credited"]].copy()
    for name in trial.names:
        table[f"margin: {name}"] = np.round(trial.result.margins[name][keep], 3)
        table[f"chance: {name}"] = np.round(trial.chances[name][keep], 4)
    return table


def summary(study: Study) -> dict:
    """The headline numbers as plain data."""
    out: dict = {"version": VERSION, "dashboard": APP_VERSION, "started": study.started, "took": study.took,
                 "has_models": study.has_models, "games": int(len(study.history)),
                 "issues": {level: len(study.notes.of(level)) for level in ("error", "warning", "note")},
                 "sealed": [{"setting": t, "cut": c, "ok": ok, "what": w} for t, c, ok, w in study.seals],
                 "settings": {}}
    for key, trial in list(study.trials.items()) + ([("closing", study.lines_only)] if study.lines_only else []):
        judged, held = _split(trial)
        marks = trial.marks()
        out["settings"][key] = {
            "games": int(trial.keep.sum()), "seasons": trial.result.seasons, "held_back": held,
            "recipes": {name: {"right": s.right, "games": s.games, "logloss": s.logloss, "brier": s.brier,
                               "miss": s.miss,
                               **({} if name == recipes.LINE else
                                  {"edge": (d := trial.against(name)).edge, "low": d.low, "high": d.high})}
                        for name, s in marks.items()},
        }
    return out


KEPT_WHOLE = "latest-study.pickle"
#: Run folders kept; older ones are cleared away as new ones are written.
KEEP_RUNS = 6


def _whole_path() -> Path:
    """Where the newest run is kept whole: the computer's temp folder. It is
    every table of every walk-forward - well over a hundred megabytes - and
    the project folder is synced, so it does not belong there."""
    import tempfile
    return Path(tempfile.gettempdir()) / "acql-training" / KEPT_WHOLE


def keep_whole(study: Study) -> None:
    """The newest run, whole - so `python -m acql.training report` can write
    its report again without walking it all forward again."""
    import pickle
    try:
        _whole_path().parent.mkdir(parents=True, exist_ok=True)
        with open(_whole_path(), "wb") as handle:
            pickle.dump(study, handle, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - a run not kept whole is run again next time, that is all
        pass


def kept_whole() -> Study | None:
    import pickle
    try:
        with open(_whole_path(), "rb") as handle:
            found = pickle.load(handle)
        return found if isinstance(found, Study) else None
    except Exception:  # noqa: BLE001
        return None


def write(study: Study) -> Path:
    """Everything a run found, in its own folder; the newest is copied to data/training/latest."""
    root = data.folder()
    folder = root / "runs" / time.strftime("%Y%m%d-%H%M%S", time.localtime(study.started or time.time()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.md").write_text(render(study, folder), encoding="utf-8")
    for key, trial in study.trials.items():
        _predictions(trial).to_csv(folder / f"predictions-{key}.csv", index=False)
    if study.lines_only is not None:
        _predictions(study.lines_only).to_csv(folder / "predictions-closing.csv", index=False)
    fits = {key: trial.result.fits for key, trial in study.trials.items()}
    (folder / "fits.json").write_text(json.dumps(fits, indent=1, default=float), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps(summary(study), indent=1, default=float), encoding="utf-8")
    (folder / "issues.json").write_text(json.dumps(study.notes.as_rows(), indent=1), encoding="utf-8")
    try:
        from . import verdict
        verdict.write(study, folder)
    except Exception:  # noqa: BLE001 - the report stands without its one-line answer
        import logging
        logging.getLogger("acql.training").exception("the verdict could not be written")
    try:
        from . import journal, scorecards, verdict as said
        scorecards.write(study, folder, said.IN_USE)
        cards = json.loads((folder / scorecards.FILE).read_text(encoding="utf-8"))
        head = study.headline
        journal.record(cards, head.result.games[head.keep] if head is not None else None, folder, root)
    except Exception:  # noqa: BLE001 - the report stands without its scorecards
        import logging
        logging.getLogger("acql.training").exception("the scorecards could not be written")
    for recipe in study.taught:
        registry.save(recipe, setting=study.taught_key, before=study.taught_before)
    latest = root / "latest"
    shutil.rmtree(latest, ignore_errors=True)
    shutil.copytree(folder, latest)
    for old in sorted(p for p in (root / "runs").iterdir() if p.is_dir())[:-KEEP_RUNS]:
        shutil.rmtree(old, ignore_errors=True)
    return folder
