"""Prospective side of the arena: capture Deadeye on its own, and score the shadow journal.

    python -m challenger capture-deadeye --season 2026 --week 7 [--file "nflpredictions week 7.csv"]
    python -m challenger shadow-report

Deadeye's forecast is computed through its own pricing code from the weekly
Prediction Tracker file the dashboard uses, and appended to
challenger/journal/deadeye.jsonl - only for games not yet kicked off. The
journal records the input file's SHA-256 and first-commit time. Challenger's
forecasts are never read here until scoring.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from .. import data, journal, metrics
from ..config import RESULTS, ROOT
from . import deadeye
from .headtohead import to_markdown


def capture_deadeye(season: int, week: int, file: str | None = None) -> dict:
    name = file or deadeye.LIVE_FILES.get(week) or f"nflpredictions week {week}.csv"
    path = ROOT / name
    if not path.exists():
        raise FileNotFoundError(path)
    games = data.load_games()
    frame, notes = deadeye.live(games, season, {week: name})
    now = journal.now_utc()
    kick = games.set_index("game_id")["kickoff_utc"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    from acql.model import predictions as dp

    recs = []
    for r in frame.itertuples(index=False):
        if kick[r.game_id] <= now:
            continue
        recs.append({"game_id": r.game_id, "season": season, "week": week, "kickoff_utc": kick[r.game_id].isoformat(),
                     "deadline_utc": (games[(games["season"] == season) & (games["week"] == week)]["kickoff_utc"].min()
                                      - pd.Timedelta(minutes=60)).isoformat(),
                     "model": "deadeye_live", "model_version": f"deadeye-pricing-weight{dp.CONSENSUS_WEIGHT}",
                     "p_home": round(float(r.p_home), 6), "p_away": round(1 - float(r.p_home), 6),
                     "deadeye_margin": round(float(r.deadeye_margin), 4), "deadeye_sd": round(float(r.deadeye_sd), 4),
                     "source_file": name, "source_sha256": digest,
                     "source_first_committed_utc": str(r.file_first_committed_utc),
                     "note": "Deadeye's live rule at the default consensus share; the app's in-season refit of the share needs its database, which is not in the repository"})
    written = journal.append_forecasts("deadeye", recs, now=now) if recs else []
    return {"captured": len(written), "file": name, "notes": notes}


def shadow_report() -> dict:
    ch = journal.scored_forecasts("challenger")
    de = journal.scored_forecasts("deadeye")
    outs = pd.DataFrame(journal.read("outcomes"))
    out_dir = RESULTS / "shadow"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Prospective shadow competition", "",
             "Forecasts journaled before kickoff (challenger/journal/). Scored only after games finish. "
             "Small samples: no conclusion should be drawn from a few weeks.", ""]
    checks = {k: journal.verify(k) for k in journal.KINDS}
    lines.append("Journal integrity: " + ", ".join(f"{k} {'ok' if v[0] else 'BROKEN: ' + v[1]}" for k, v in checks.items()))
    lines.append("")
    if ch.empty:
        lines.append("No Challenger forecasts journaled yet.")
    else:
        lines.append(f"Forecasts journaled: Challenger {ch['game_id'].nunique()} games; "
                     f"Deadeye {de['game_id'].nunique() if not de.empty else 0} games.")
    summary = {"integrity": {k: v[0] for k, v in checks.items()}}
    if not ch.empty and not outs.empty:
        outs = outs.sort_values("recorded_at_utc").drop_duplicates("game_id", keep="last")
        res = outs.set_index("game_id")
        rows = []
        both = pd.concat([ch, de], ignore_index=True) if not de.empty else ch
        for (model, version), grp in both.groupby(["model", "model_version"]):
            grp = grp[grp["game_id"].isin(res.index)]
            margin = grp["game_id"].map(res["home_score"] - res["away_score"])
            grp = grp[margin != 0]
            if grp.empty:
                continue
            y = (grp["game_id"].map(res["home_score"] - res["away_score"]) > 0).astype(float)
            rows.append({"model": model, "version": version, **metrics.summary(grp["p_home"].astype(float), y)})
        if rows:
            table = pd.DataFrame(rows).sort_values("log_loss")
            lines += ["", "## Scored so far (decided games only)", "", to_markdown(table), ""]
            summary["scores"] = rows
    (out_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    return summary
