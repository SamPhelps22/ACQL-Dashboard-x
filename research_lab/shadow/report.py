"""Weekly shadow comparison report: what each model said before kickoff, and - once graded - how it did.

Only prospective journal entries appear here; retrospective reconstructions live in reports/.
"""

from __future__ import annotations

import pandas as pd

from .. import config
from ..reports import md
from . import journal


def build(season: int, week: int) -> str:
    entries = [e for e in journal.read() if e.get("season") == season and e.get("week") == week]
    grades = [g for g in journal.read(journal.GRADES) if g.get("season") == season and g.get("week") == week]
    L = [f"# Shadow forecasts — {season} week {week}", "",
         "Prospective: every row was written to `shadow/journal.jsonl` before its game's kickoff and is never "
         "edited (corrections would appear as new revisions). Lab models use only games completed before the "
         "forecast time. Nothing here is used by the dashboard or Deadeye.", ""]
    if not entries:
        return "\n".join(L + ["No forecasts recorded for this week."])
    df = pd.DataFrame(entries)
    stamp = df[df["kind"] == "lab_model"]["forecast_ts"].min() if "kind" in df else ""
    L += [f"Forecast time (lab models): `{stamp}`.", ""]
    probs = df[df["p_home_raw"].notna()]
    piv = probs.pivot_table(index=["game_id"], columns="model", values="p_home_raw", aggfunc="first")
    meta = df.drop_duplicates("game_id").set_index("game_id")[["away_team", "home_team", "kickoff"]]
    piv = meta.join(piv, how="right").sort_values("kickoff").reset_index()
    piv["kickoff"] = pd.to_datetime(piv["kickoff"]).dt.strftime("%a %H:%M UTC")
    cols = ["game_id", "away_team", "home_team", "kickoff"] + [c for c in (
        "market_snapshot", "deadeye_recomputed", "G_free_stack", "G_free_equal", "E_bayes", "A_qb_weekstart",
        "A_qb_confirmed", "B_drive_sim", "C_situational", "F_matchup_interaction", "challenger_elo") if c in piv]
    L += ["## Home win probability by model", "", md.table(piv[cols], 3), ""]
    mk = df[df["kind"] == "market_snapshot"]
    if len(mk):
        L += ["## Market snapshot used", "", f"Source: {mk['provenance'].iloc[0]}", "",
              md.table(mk[["game_id", "spread_line", "total_line", "home_moneyline", "away_moneyline"]], 1), ""]
    dd = df[df["kind"].isin(["deadeye", "deadeye_unavailable"])]
    if len(dd):
        L += ["## Deadeye", "", str(dd.get("provenance", dd.get("note")).iloc[0]), ""]
    if grades:
        g = pd.DataFrame(grades)
        g = g[g["log_loss"].notna()]
        s = g.groupby("model").agg(games=("game_id", "size"), log_loss=("log_loss", "mean"), brier=("brier", "mean"),
                                   right=("p_home", lambda p: 0)).reset_index()
        hits = g.assign(hit=((g["p_home"] > 0.5) == (g["home_win"] == 1)).astype(int)).groupby("model")["hit"].sum()
        s["right"] = s["model"].map(hits)
        L += ["## Graded", "", md.table(s.sort_values("log_loss"), 4), "",
              "One week is far too small a sample to judge a model; the season-long table is what matters.", ""]
    else:
        L += ["## Graded", "", "Not yet: games not final.", ""]
    return "\n".join(L)


def write(season: int, week: int) -> str:
    path = config.ROOT / "research_lab" / "shadow" / f"week_{season}_{week:02d}.md"
    path.write_text(build(season, week))
    return str(path)
