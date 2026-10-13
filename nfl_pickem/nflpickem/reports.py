"""Structured weekly matchup reports.

Each report separates *measured evidence* (numbers computed from the database,
with their point-in-time timestamps) from *interpretation*. Factor strength is
expressed as a z-score against the historical distribution of that feature, so
"strong" means unusual relative to past NFL matchups, not that it caused anything.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

# (feature column, label, positive means good for home?, how to read the number)
FACTORS = [
    ("elo_diff", "Overall team strength (Elo)", True, "{v:+.0f} Elo points"),
    ("qb_rating_diff", "Quarterback play (EPA/dropback rating)", True, "{v:+.3f} EPA per dropback"),
    ("pass_matchup", "Passing offence vs opposing pass defence", True, "{v:+.3f} EPA/dropback edge"),
    ("rush_matchup", "Rushing offence vs opposing run defence", True, "{v:+.3f} EPA/rush edge"),
    ("protection_matchup", "Pass protection vs pass rush (sack rates)", True, "{v:+.3f} sack-rate edge"),
    ("explosive_pass_matchup", "Explosive passing vs explosive passes allowed", True, "{v:+.3f} rate edge"),
    ("off_neutral_epa_adj_diff", "Offensive efficiency in neutral game states", True, "{v:+.3f} EPA/play"),
    ("def_neutral_epa_adj_diff", "Defensive efficiency in neutral game states", False, "{v:+.3f} EPA/play allowed"),
    ("off_third_rate_diff", "Third-down conversion rate", True, "{v:+.1%}"),
    ("rest_diff", "Rest advantage", True, "{v:+.0f} days"),
]
SOURCES = {
    "schedule/results/lines": "nflverse games.csv (github.com/nflverse/nfldata)",
    "play-by-play": "nflverse play_by_play_{season}.parquet",
    "injuries": "nflverse injuries_{season}.csv",
}


def _z(value: float, ref: pd.Series) -> float:
    sd = ref.std()
    if value is None or (isinstance(value, float) and math.isnan(value)) or not sd or math.isnan(sd):
        return float("nan")
    return float((value - ref.mean()) / sd)


def _fmt(x, f="{:.1%}"):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f.format(x)


def factor_weights(reference: pd.DataFrame) -> dict[str, float]:
    """Historical log-odds change per 1 SD of each factor (univariate logistic fit on
    completed games before the cutoff). Used only to rank evidence by measured impact."""
    from sklearn.linear_model import LogisticRegression
    d = reference[reference["home_result"].isin([0.0, 1.0])]
    out = {}
    for col, *_ in FACTORS:
        if col not in d:
            continue
        x = d[col].astype(float)
        ok = x.notna()
        if ok.sum() < 200 or x[ok].std() == 0:
            continue
        z = ((x[ok] - x[ok].mean()) / x[ok].std()).to_numpy().reshape(-1, 1)
        out[col] = float(LogisticRegression().fit(z, d.loc[ok, "home_result"].astype(int)).coef_[0, 0])
    return out


def build_report(feat: pd.Series, pick: pd.Series, reference: pd.DataFrame, injuries: pd.DataFrame,
                 n_games: int, weights: dict[str, float] | None = None) -> dict:
    weights = weights if weights is not None else factor_weights(reference)
    home, away = feat["home_team"], feat["away_team"]
    p_home = float(pick["blended_home_probability"])
    m_home = pick.get("market_home_probability")
    m_home = None if m_home is None or pd.isna(m_home) else float(m_home)
    winner = pick["selected_team"]
    factors = []
    for col, label, home_good, fmt in FACTORS:
        if col not in feat or col not in reference:
            continue
        v = feat[col]
        if pd.isna(v):
            continue
        z = _z(float(v), reference[col].dropna())
        if math.isnan(z):
            continue
        favours = home if (v > 0) == home_good else away
        impact = abs(z * weights.get(col, 0.0))  # historical log-odds per this many SDs
        if impact < 0.03:
            continue
        factors.append({"factor": label, "favours": favours, "value": fmt.format(v=float(v)),
                        "strength_z": round(abs(z), 2), "impact_logodds": round(impact, 3),
                        "supports_pick": favours == winner, "kind": "measured"})
    if feat.get("home_short_week") == 1 or feat.get("away_short_week") == 1:
        team = home if feat.get("home_short_week") == 1 else away
        factors.append({"factor": "Short week", "favours": away if team == home else home,
                        "value": f"{team} on <= 5 days rest", "strength_z": 0.5, "impact_logodds": 0.05,
                        "supports_pick": (away if team == home else home) == winner, "kind": "measured"})
    if feat.get("home_field") == 1:
        factors.append({"factor": "Home field", "favours": home, "value": "true home game",
                        "strength_z": 0.3, "impact_logodds": 0.08, "supports_pick": home == winner, "kind": "measured"})
    factors.sort(key=lambda f: f["impact_logodds"], reverse=True)
    factors = factors[:5]

    inj = injuries[(injuries["team"].isin([home, away]))
                   & injuries["position"].isin(["QB", "T", "G", "C", "OT", "OG", "OL"])
                   & injuries["report_status"].notna()] if len(injuries) else pd.DataFrame()
    inj_list = [f"{r.team} {r.position} {r.player_name}: {r.report_status}" for r in inj.itertuples()]

    unc = []
    if m_home is None:
        unc.append("No market odds available: probability relies on models that trailed the market in backtests.")
    elif pick.get("odds_status") == "stale":
        unc.append("Odds snapshot is stale.")
    for side, team in (("home", home), ("away", away)):
        st = feat.get(f"{side}_quarterback_status")
        if st == "projected_starter":
            unc.append(f"{team} starter is a projection ({feat.get(f'{side}_qb_name') or 'unnamed'}); confirm before lock.")
        elif st == "unknown":
            unc.append(f"{team} starting QB unknown.")
        w = feat.get(f"{side}_qb_dropbacks_weighted")
        if w is not None and not pd.isna(w) and w < 150:
            unc.append(f"{team} QB rating rests on limited recent dropbacks (shrunk toward replacement level).")
    if feat.get("early_season") == 1:
        unc.append("Early season: team ratings lean heavily on last season and priors.")
    if m_home is not None and abs(p_home - m_home) >= 0.06:
        unc.append(f"Model differs from market by {abs(p_home - m_home):.1%}; historically the market has been "
                   "the more accurate source, so treat the gap as a hypothesis.")
    if not inj_list:
        unc.append("No QB/OL injury designations found (or injury report not yet published).")

    ml_vals = [pick.get(c) for c in ("elo_home_probability", "logistic_home_probability",
                                      "gradient_boosting_home_probability")]
    ml_vals = [float(x) for x in ml_vals if x is not None and not pd.isna(x)]
    ml_home = float(np.mean(ml_vals)) if ml_vals else None
    football_view = None
    if ml_home is not None and m_home is not None:
        gap = ml_home - m_home
        football_view = {"ml_home_probability": round(ml_home, 4), "ml_minus_market_home": round(gap, 4),
                         "leans": home if gap > 0 else away}
        if abs(gap) >= 0.08:
            unc.append(f"Football models lean {football_view['leans']} by {abs(gap):.1%} versus the market. "
                       "This is an unvalidated hypothesis: in 2012-2025 backtests, deviating from the market "
                       "toward the models lowered pool points, so it does not change the pick.")
    p_pick = p_home if winner == home else 1 - p_home
    return {
        "game_id": feat["game_id"], "matchup": f"{away} @ {home}",
        "kickoff_utc": str(feat["kickoff_utc"]),
        "predicted_winner": winner,
        "win_probability": {home: round(p_home, 4), away: round(1 - p_home, 4)},
        "market_probability": None if m_home is None else {home: round(m_home, 4), away: round(1 - m_home, 4)},
        "model_minus_market_home": None if m_home is None else round(p_home - m_home, 4),
        "football_model_view": football_view,
        "confidence_points": int(pick["confidence_points"]),
        "confidence_rank": f"{n_games - int(pick['confidence_points']) + 1} of {n_games}",
        "pick_probability": round(p_pick, 4),
        "factors": factors,
        "injuries": inj_list,
        "uncertainties": unc,
        "quarterbacks": {home: feat.get("home_qb_name"), away: feat.get("away_qb_name")},
        "qb_ids": {home: feat.get("home_qb_id"), away: feat.get("away_qb_id")},
        "data": {
            "odds_status": pick.get("odds_status"),
            "odds_captured_at": None if pd.isna(pick.get("odds_captured_at")) else str(pick.get("odds_captured_at")),
            "team_features_as_of": str(max([t for t in (feat.get("home_feature_ts"), feat.get("away_feature_ts"))
                                            if not pd.isna(t)], default="none")),
            "football_features_as_of": str(feat.get("football_feature_ts")),
            "prediction_cutoff": str(feat["cutoff"]),
            "sources": SOURCES,
        },
        "note": "Factors are measured differences between the teams (z = size relative to past NFL matchups), "
                "ranked by their historical univariate association with winning. They overlap with each "
                "other and with the market, and are not proof of causation.",
    }


def to_markdown(r: dict) -> str:
    teams = list(r["win_probability"])
    lines = [f"### {r['matchup']} — pick **{r['predicted_winner']}** ({r['confidence_points']} pts, "
             f"rank {r['confidence_rank']})",
             f"Kickoff {r['kickoff_utc'][:16]} UTC",
             "",
             f"- Model: {teams[0]} {_fmt(r['win_probability'][teams[0]])} / {teams[1]} {_fmt(r['win_probability'][teams[1]])}"]
    if r["market_probability"]:
        lines.append(f"- Market (de-vigged): {teams[0]} {_fmt(r['market_probability'][teams[0]])} / "
                     f"{teams[1]} {_fmt(r['market_probability'][teams[1]])} "
                     f"(model − market, home: {r['model_minus_market_home']:+.1%})")
    else:
        lines.append("- Market: **no odds available**")
    fv = r.get("football_model_view")
    if fv:
        lines.append(f"- Football-model view (unvalidated vs market): home {_fmt(fv['ml_home_probability'])}, "
                     f"{fv['ml_minus_market_home']:+.1%} vs market (leans {fv['leans']})")
    lines.append("- Evidence (measured):")
    for f in r["factors"] or [{"factor": "No large measured edges", "favours": "-", "value": "", "strength_z": 0}]:
        lines.append(f"  - {f['factor']}: favours {f['favours']} ({f['value']}, z={f['strength_z']}, "
                     f"historical impact ~{f.get('impact_logodds', 0):.2f} log-odds)")
    lines.append("- Injuries/availability: " + ("; ".join(r["injuries"]) if r["injuries"] else "none reported"))
    lines.append("- Uncertainties: " + (" ".join(r["uncertainties"]) if r["uncertainties"] else "none flagged"))
    d = r["data"]
    lines.append(f"- Data: odds {d['odds_status']} @ {d['odds_captured_at'] or 'n/a'}; features as of "
                 f"{d['team_features_as_of'][:16]}; cutoff {d['prediction_cutoff'][:16]}")
    return "\n".join(lines)


def build_reports(slate: pd.DataFrame, picks: pd.DataFrame, reference: pd.DataFrame,
                  injuries: pd.DataFrame) -> list[dict]:
    p = picks.set_index("game_id")
    eligible = int((picks["confidence_points"] > 0).sum())
    w = factor_weights(reference)
    return [build_report(f, p.loc[f["game_id"]], reference, injuries, eligible, w)
            for _, f in slate.iterrows() if f["game_id"] in p.index]


def save_reports(con, run_id: str, reports: list[dict]) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS matchup_reports (run_id VARCHAR, game_id VARCHAR, report_json VARCHAR, "
                "PRIMARY KEY (run_id, game_id))")
    for r in reports:
        con.execute("INSERT OR REPLACE INTO matchup_reports VALUES (?, ?, ?)",
                    [run_id, r["game_id"], json.dumps(r, default=_default)])


def load_reports(con, run_id: str) -> dict[str, dict]:
    try:
        rows = con.execute("SELECT game_id, report_json FROM matchup_reports WHERE run_id = ?", [run_id]).fetchall()
    except Exception:
        return {}
    return {g: json.loads(j) for g, j in rows}


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)
