"""Edge decay: how much of the computer models' disagreement with the line is
still worth anything as the week goes on.

Deadeye's nudge is the published models' view minus the line. If that gap
says something the market has not yet priced, two things should follow: the
line should move toward the models between the open and the close, and the
gap should still say something about the result at whichever line it is
measured against. If the market soaks the information up, the gap measured
against a later line should be worth less - the edge decays.

For every game in the season archives this takes the models' consensus (the
same trimmed mean the picks use: the wildest fifth at each end dropped) and
measures, at each line the archive keeps (opening, midweek, updated, closing):

    move     slope of (closing line - this line) on the gap: the share of the
             gap the market went on to close. 0 = the market ignored it.
    result   slope of (result - this line) on the gap: the share of the gap
             that turned up in the score. 0 = no edge left at this line.
    ATS      how often the models' side covered this line when the gap was at
             least GAP points (pushes left out), against the 52.4% -110 needs.

Ranges are 90%, from resampling whole seasons. A caveat no number here can fix:
the archive has no clock on the models' numbers - a model may have posted after
the opening line, even after the midweek one. So "the gap at the open" may know
things the opening line did not, which flatters the early columns. This counts;
it teaches nothing and changes no pick, and the dashboard does not import it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data

#: Lines in the order the week takes them.
ORDER = ("opening", "midweek", "updated", "closing")
#: The wildest share of models dropped at each end, as the picks do.
TRIM = 0.2
#: A gap this many points is "a disagreement" for the cover count.
GAP = 2.0
BREAK_EVEN = 110 / 210
RESAMPLES = 1000
#: Eras, so a slope that held once and then vanished shows as that.
ERAS = ((1999, 2009), (2010, 2017), (2018, 2100))


def consensus(frame: pd.DataFrame) -> pd.Series:
    """Trimmed mean of every model column, per game (NaN with fewer than three models)."""
    cols = [c for c in frame.columns if c.startswith(data.MODEL)]
    values = frame[cols].to_numpy(dtype=float)
    out = np.full(len(frame), np.nan)
    for i, row in enumerate(values):
        row = np.sort(row[~np.isnan(row)])
        if len(row) < 3:
            continue
        cut = int(len(row) * TRIM)
        out[i] = row[cut:len(row) - cut].mean()
    return pd.Series(out, index=frame.index)


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.var(x) == 0:
        return float("nan")
    return float(np.cov(x, y, bias=True)[0, 1] / np.var(x))


def _ats(gap: np.ndarray, beat: np.ndarray) -> tuple[int, int]:
    """(wins, decisions) for the models' side where |gap| >= GAP. `beat` is result - line."""
    keep = (np.abs(gap) >= GAP) & (beat != 0)
    return int((np.sign(gap[keep]) == np.sign(beat[keep])).sum()), int(keep.sum())


def measure(frame: pd.DataFrame, timing: str) -> dict:
    """The three numbers for one line, on the games that have it and the close."""
    line = frame[f"line_{timing}"]
    ok = line.notna() & frame["line_closing"].notna() & frame["consensus"].notna() & frame["actual"].notna()
    part = frame[ok]
    gap = (part["consensus"] - part[f"line_{timing}"]).to_numpy()
    move = (part["line_closing"] - part[f"line_{timing}"]).to_numpy()
    beat = (part["actual"] - part[f"line_{timing}"]).to_numpy()
    wins, decided = _ats(gap, beat)
    return {"games": len(part), "move": _slope(gap, move), "result": _slope(gap, beat),
            "wins": wins, "decided": decided, "seasons": part["season"].to_numpy(),
            "gap": gap, "moved": move, "beat": beat}


def _ranges(m: dict, seed: int) -> dict:
    """90% ranges for the slopes and the cover rate, resampling whole seasons."""
    rng = np.random.default_rng(seed)
    seasons = np.unique(m["seasons"])
    rows = {s: np.flatnonzero(m["seasons"] == s) for s in seasons}
    moves, results, rates = [], [], []
    for _ in range(RESAMPLES):
        idx = np.concatenate([rows[s] for s in rng.choice(seasons, len(seasons))])
        g = m["gap"][idx]
        moves.append(_slope(g, m["moved"][idx]))
        results.append(_slope(g, m["beat"][idx]))
        w, d = _ats(g, m["beat"][idx])
        rates.append(w / d if d else np.nan)
    q = lambda v: tuple(np.nanpercentile(v, [5, 95])) if np.isfinite(v).any() else (np.nan, np.nan)
    return {"move_range": q(np.array(moves)), "result_range": q(np.array(results)), "rate_range": q(np.array(rates))}


def study(history: pd.DataFrame | None = None, seed: int = 2026) -> dict[str, dict[str, dict]]:
    """{span: {timing: numbers}} - every season, then each era."""
    if history is None:
        history = data.check(data.history(notes=data.Notes()), data.Notes())
    frame = history.copy()
    frame["consensus"] = consensus(frame)
    for timing in ORDER:
        if f"line_{timing}" not in frame:
            frame[f"line_{timing}"] = np.nan
    spans = {f"Every season {int(frame['season'].min())}-{int(frame['season'].max())}": frame}
    for low, high in ERAS:
        part = frame[(frame["season"] >= low) & (frame["season"] <= high)]
        if len(part):
            spans[f"{low}-{min(high, int(frame['season'].max()))}"] = part
    out = {}
    for span, part in spans.items():
        out[span] = {}
        for timing in ORDER:
            m = measure(part, timing)
            if m["games"] >= 30:
                m.update(_ranges(m, seed))
            out[span][timing] = m
    return out


def _r(v: tuple) -> str:
    return "-" if not np.all(np.isfinite(v)) else f"{v[0]:+.2f} to {v[1]:+.2f}"


def write_up(found: dict[str, dict[str, dict]]) -> str:
    lines = ["# Edge decay: the models' gap from the line, open to close", "",
             f"Consensus = trimmed mean of the archive's models ({TRIM:.0%} off each end). Slopes are the share of "
             "the gap that showed up; ranges are 90%, resampling whole seasons. ATS counts games with a gap of "
             f"{GAP:g}+ points, pushes out; -110 needs {BREAK_EVEN:.1%}.", "",
             "**Caveat:** the archive does not say when each model posted, so the opening and midweek columns may "
             "use numbers posted after those lines - read them as an upper bound. Every span here is exploratory: "
             "nothing was fitted, but nothing was held back either.", ""]
    for span, by in found.items():
        lines += [f"## {span}", "",
                  "| Line | Games | Market closed the gap | Gap showed in the result | Models' side ATS |",
                  "|---|---|---|---|---|"]
        for timing in ORDER:
            m = by[timing]
            if m["games"] < 30:
                lines.append(f"| {timing} | {m['games']} | too few | | |")
                continue
            ats = f"{m['wins']}/{m['decided']} = {m['wins'] / m['decided']:.1%} ({_r(m['rate_range']).replace('+', '')})" \
                if m["decided"] else "-"
            move = "0 by definition" if timing == "closing" else f"{m['move']:+.2f} ({_r(m['move_range'])})"
            lines.append(f"| {timing} | {m['games']} | {move} | {m['result']:+.2f} ({_r(m['result_range'])}) | {ats} |")
        lines.append("")
    return "\n".join(lines)


def run() -> tuple[str, object]:
    text = write_up(study())
    where = data.folder() / "decay"
    where.mkdir(parents=True, exist_ok=True)
    path = where / "edge-decay.md"
    path.write_text(text, encoding="utf-8")
    return text, path
