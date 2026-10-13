"""NFL Confidence Pick'em dashboard.

Run from the nfl_pickem/ directory:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nflpickem import db, pipeline  # noqa: E402
from nflpickem.backtest import latest_backtest  # noqa: E402
from nflpickem.cli import DEMO_OVERRIDES  # noqa: E402
from nflpickem.config import _deep_merge, load_config, resolve_path, save_local_overrides  # noqa: E402
from nflpickem.confidence import ScoringRules, allocate  # noqa: E402
from nflpickem.evaluation import MODEL_LABELS  # noqa: E402

st.set_page_config(page_title="NFL Confidence Pick'em", page_icon="🏈", layout="wide")

MODEL_COLORS = {"market": "#2f6db5", "elo": "#8a5cc2", "logistic": "#d4802a", "gbm": "#3a9c6a",
                "ml_only": "#9a9a9a", "blend": "#c23b4e"}


# ------------------------------------------------------------------ helpers
def base_config() -> dict:
    return load_config()


def db_path(source: str, cfg: dict) -> Path:
    return resolve_path(cfg["data"]["demo_db_path"] if source == "demo" else cfg["data"]["db_path"])


@contextmanager
def connection(write: bool = False):
    """Short-lived connections so the CLI and the dashboard can share the file."""
    path = st.session_state["db_path"]
    try:
        con = db.connect(path, read_only=not write and Path(path).exists())
    except db.duckdb.IOException as exc:
        st.error("The database is locked by another process (probably a CLI ingest/backtest that is still "
                 f"running). Wait for it to finish and reload.\n\n{exc}")
        st.stop()
    try:
        yield con
    finally:
        con.close()


def effective_cfg(con) -> dict:
    cfg = base_config()
    return _deep_merge(cfg, DEMO_OVERRIDES) if db.get_meta(con, "data_mode") == "synthetic" else cfg


def mode_banner(mode: str) -> None:
    if mode == "synthetic":
        st.warning("**SYNTHETIC DEMONSTRATION DATA.** Teams SYN01–SYN16 and seasons 2101+ are generated. "
                   "Nothing on this page is a real NFL forecast.", icon="⚠️")
    elif mode == "empty":
        st.info("The database is empty. Load data from **Settings** (or `python -m nflpickem ingest`), "
                "or switch the sidebar to the demo database.")


def pct(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.1%}"


def fmt_value(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return "—"
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (float, np.floating)):
        return f"{v:,.0f}" if abs(v) >= 100 else (f"{v:.0f}" if float(v).is_integer() else f"{v:+.3f}")
    return str(v)


def odds_badge(status: str) -> str:
    return {"current": "🟢 current", "stale": "🟠 stale", "closing_proxy": "🔵 closing line (historical)",
            "missing": "🔴 missing", "timestamped": "🟢 current"}.get(status, status)


# ------------------------------------------------------------------ sidebar
def sidebar() -> str:
    cfg = base_config()
    st.sidebar.title("🏈 Confidence Pick'em")
    real, demo = db_path("real", cfg), db_path("demo", cfg)
    options = []
    if real.exists():
        options.append("real")
    if demo.exists():
        options.append("demo")
    if not options:
        options = ["real"]
    labels = {"real": "Real NFL data (nflverse)", "demo": "Synthetic demo data"}
    src = st.sidebar.radio("Database", options, format_func=labels.get, key="source")
    st.session_state["db_path"] = str(db_path(src, cfg))
    with connection() as con:
        mode = db.get_meta(con, "data_mode", "empty") if Path(st.session_state["db_path"]).exists() else "empty"
        rep = db.validate_database(con) if mode != "empty" else {}
        last = db.get_meta(con, "last_update")
    st.session_state["mode"] = mode
    if mode == "synthetic":
        st.sidebar.error("SYNTHETIC DEMO DATA")
    elif mode == "real":
        st.sidebar.success("nflverse data")
    if rep:
        st.sidebar.caption(f"{rep['games']:,} games · seasons {rep['seasons'][0]}–{rep['seasons'][-1]} · "
                           f"{rep['odds_snapshots']:,} odds snapshots")
    if last:
        st.sidebar.caption(f"Last data update: {last[:16]} UTC")
    return mode


# --------------------------------------------------------------- page 1
def page_weekly() -> None:
    st.header("Weekly Picks")
    mode = st.session_state["mode"]
    mode_banner(mode)
    if mode == "empty":
        return
    with connection() as con:
        now = pipeline.effective_now(con)
        nxt = pipeline.next_slate(con, now)
        weeks = con.execute("SELECT DISTINCT season, week FROM games ORDER BY 1, 2").df()
    seasons = sorted(weeks.season.unique(), reverse=True)
    default_season = nxt[0] if nxt else seasons[0]
    c1, c2, c3 = st.columns([1, 1, 2])
    season = c1.selectbox("Season", seasons, index=seasons.index(default_season))
    wk_opts = sorted(weeks[weeks.season == season].week.unique())
    default_week = nxt[1] if nxt and nxt[0] == season else wk_opts[-1]
    week = c2.selectbox("Week", wk_opts, index=wk_opts.index(default_week))
    season, week = int(season), int(week)
    is_current = nxt == (season, week)
    c3.markdown(f"**As of:** {now:%Y-%m-%d %H:%M} UTC  \n"
                + ("🟢 Upcoming slate" if is_current else "🕘 Past or future week (predicted as of its own cutoff)"))

    with connection() as con:
        runs = pipeline.list_runs(con, season, week)
    b1, b2 = st.columns([1, 3])
    if b1.button("Generate new prediction run", type="primary"):
        with st.spinner("Building point-in-time features, training models, allocating points…"):
            with connection(write=True) as con:
                try:
                    rid, _ = pipeline.predict_week(con, effective_cfg(con), season, week)
                    st.session_state["run_id"] = rid
                    st.success(f"Created run {rid}")
                except Exception as exc:  # surface errors in the UI
                    st.error(str(exc))
            with connection() as con:
                runs = pipeline.list_runs(con, season, week)
    if runs.empty:
        b2.info("No prediction runs for this week yet. Click **Generate new prediction run**.")
        return
    labels = {r.run_id: f"{'🔒 SUBMITTED ' if r.frozen else ''}{r.run_id} · {str(r.generated_at)[:16]} · {r.model_version}"
              for r in runs.itertuples()}
    ids = list(labels)
    default = st.session_state.get("run_id") if st.session_state.get("run_id") in ids else ids[0]
    run_id = b2.selectbox("Prediction run", ids, index=ids.index(default), format_func=labels.get)
    st.session_state["run_id"] = run_id
    run = runs.set_index("run_id").loc[run_id]
    with connection() as con:
        picks = pipeline.get_run(con, run_id)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Games", len(picks))
    m2.metric("Expected points", f"{picks.expected_points.sum():.1f}", help="Sum of P(pick wins) × points")
    m3.metric("Max points", int(picks.confidence_points.sum()))
    m4.metric("Data cutoff (UTC)", pd.Timestamp(run.data_cutoff).strftime("%b %d %H:%M"))
    if run.frozen:
        st.success(f"🔒 This run was frozen (submitted) at {str(run.frozen_at)[:16]} UTC and cannot be changed.")

    view = pd.DataFrame({
        "Pts": picks.confidence_points,
        "Matchup": picks.away_team + " @ " + picks.home_team,
        "Kickoff (UTC)": pd.to_datetime(picks.kickoff_utc).dt.strftime("%a %m-%d %H:%M"),
        "Pick": picks.selected_team,
        "Win prob": picks.selected_team_probability,
        "Exp pts": picks.expected_points,
        "Blend (home)": picks.blended_home_probability,
        "Market (home)": picks.market_home_probability,
        "Model avg (home)": picks[["elo_home_probability", "logistic_home_probability",
                                   "gradient_boosting_home_probability"]].mean(axis=1),
        "Odds": picks.odds_status.map(odds_badge),
        "Odds time (UTC)": pd.to_datetime(picks.odds_captured_at).dt.strftime("%m-%d %H:%M").fillna("n/a (closing)"),
        "Injury data": picks.injury_status,
        "Flags": picks.data_flags,
    })
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "Win prob": st.column_config.ProgressColumn(format="percent", min_value=0.5, max_value=1.0),
        "Exp pts": st.column_config.NumberColumn(format="%.2f"),
        "Blend (home)": st.column_config.NumberColumn(format="%.3f"),
        "Market (home)": st.column_config.NumberColumn(format="%.3f"),
        "Model avg (home)": st.column_config.NumberColumn(format="%.3f"),
    })
    if (picks.odds_status == "missing").any():
        st.warning("Some games have no market odds; their blend uses the models only (lower data coverage).")
    if (picks.odds_status == "stale").any():
        st.warning("Some odds snapshots are older than the staleness threshold.")

    label = "SYNTHETIC DEMO - NOT REAL NFL" if mode == "synthetic" else "nflverse data"
    out = picks.reindex(columns=pipeline.EXPORT_COLUMNS).sort_values("confidence_points", ascending=False)
    out.insert(0, "data_label", label)
    c1, c2 = st.columns([1, 1])
    c1.download_button("⬇️ Export CSV", out.to_csv(index=False, float_format="%.4f"),
                       file_name=f"picks_{season}_wk{week:02d}_{run_id}.csv", mime="text/csv")
    if not run.frozen:
        if c2.button("🔒 Freeze as submitted picks"):
            with connection(write=True) as con:
                pipeline.freeze_run(con, run_id)
            st.rerun()


# --------------------------------------------------------------- page 2
@st.cache_data(show_spinner=False)
def recent_form(path: str, team: str, before: str) -> pd.DataFrame:
    con = db.connect(path, read_only=True)
    try:
        return con.execute("""
            SELECT g.kickoff_utc, g.week, g.season,
                   CASE WHEN g.home_team = ? THEN g.away_team ELSE g.home_team END AS opponent,
                   CASE WHEN g.home_team = ? THEN g.home_score - g.away_score ELSE g.away_score - g.home_score END AS margin,
                   s.off_epa_sum / NULLIF(s.plays, 0) AS off_epa, s.def_epa_sum / NULLIF(s.def_plays, 0) AS def_epa
            FROM games g JOIN team_game_stats s ON s.game_id = g.game_id AND s.team = ?
            WHERE g.game_status = 'final' AND (g.home_team = ? OR g.away_team = ?) AND g.kickoff_utc < ?
            ORDER BY g.kickoff_utc DESC LIMIT 8""", [team, team, team, team, team, before]).df()
    finally:
        con.close()


def page_matchup() -> None:
    st.header("Matchup Analysis")
    mode_banner(st.session_state["mode"])
    run_id = st.session_state.get("run_id")
    if not run_id:
        with connection() as con:
            latest = pipeline.list_runs(con)
        run_id = latest.run_id.iloc[0] if len(latest) else None
        if run_id:
            st.caption("Showing the most recent prediction run (choose another on Weekly Picks).")
    if not run_id:
        st.info("Select or generate a prediction run on **Weekly Picks** first.")
        return
    with connection() as con:
        picks = pipeline.get_run(con, run_id)
        tf = con.execute("SELECT * FROM team_features WHERE game_id IN (SELECT game_id FROM predictions WHERE run_id = ?)",
                         [run_id]).df() if "team_features" in {r[0] for r in con.execute("SHOW TABLES").fetchall()} else pd.DataFrame()
    if picks.empty:
        st.info("Run has no games.")
        return
    labels = {r.game_id: f"{r.away_team} @ {r.home_team} — pick {r.selected_team} ({r.confidence_points} pts)"
              for r in picks.itertuples()}
    gid = st.selectbox("Game", list(labels), format_func=labels.get)
    g = picks.set_index("game_id").loc[gid]
    st.caption(f"Run {run_id} · season {g.season} week {g.week} · kickoff {str(g.kickoff_utc)[:16]} UTC")

    probs = pd.DataFrame({
        "model": ["Market", "Elo", "Logistic", "Gradient boosting", "Blend"],
        "home": [g.market_home_probability, g.elo_home_probability, g.logistic_home_probability,
                 g.gradient_boosting_home_probability, g.blended_home_probability]})
    c1, c2 = st.columns([3, 2])
    fig = go.Figure()
    fig.add_bar(y=probs.model, x=probs.home, orientation="h", name=f"{g.home_team} (home)",
                marker_color="#2f6db5", text=[pct(x) for x in probs.home], textposition="inside")
    fig.add_bar(y=probs.model, x=1 - probs.home, orientation="h", name=f"{g.away_team} (away)",
                marker_color="#d4802a", text=[pct(1 - x) for x in probs.home], textposition="inside")
    fig.update_layout(barmode="stack", height=300, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis=dict(tickformat=".0%", range=[0, 1]), title="Win probability by model")
    fig.add_vline(x=0.5, line_dash="dot", line_color="gray")
    c1.plotly_chart(fig, width="stretch")
    gap = (g.blended_home_probability - g.market_home_probability) if pd.notna(g.market_home_probability) else np.nan
    c2.metric("Pick", g.selected_team, f"{g.selected_team_probability:.1%} win probability", delta_color="off")
    c2.metric("Confidence points", int(g.confidence_points), f"{g.expected_points:.2f} expected", delta_color="off")
    c2.metric("Blend − market (home)", "—" if np.isnan(gap) else f"{gap:+.1%}",
              help="How far the blend moved away from the de-vigged market probability")
    c2.caption(f"Odds: {odds_badge(g.odds_status)} · Injury data: {g.injury_status} · Flags: {g.data_flags}")

    from nflpickem.reports import load_reports
    with connection() as con:
        rep = load_reports(con, run_id).get(gid)
    if rep:
        st.subheader("Matchup report")
        r1, r2 = st.columns([3, 2])
        r1.markdown("**Evidence (measured, ranked by historical impact)**")
        if rep["factors"]:
            r1.dataframe(pd.DataFrame(rep["factors"])[["factor", "favours", "value", "strength_z", "impact_logodds",
                                                      "supports_pick"]], hide_index=True, width="stretch")
        else:
            r1.caption("No large measured edges between these teams.")
        r2.markdown("**Injuries / availability**")
        r2.write("\n".join(f"- {x}" for x in rep["injuries"]) or "None reported.")
        r2.markdown("**Uncertainties & missing information**")
        r2.write("\n".join(f"- {x}" for x in rep["uncertainties"]) or "None flagged.")
        qbs = rep.get("quarterbacks", {})
        st.caption(f"Starters assumed: {', '.join(f'{k}: {v}' for k, v in qbs.items())} · "
                   f"cutoff {rep['data']['prediction_cutoff'][:16]} UTC · football features as of "
                   f"{rep['data']['football_features_as_of'][:16]} · {rep['note']}")
    unit = unit_comparison(run_id, gid)
    if unit is not None:
        st.subheader("Unit & quarterback comparison (opponent-adjusted, point-in-time)")
        st.dataframe(unit, width="stretch")
        st.caption("EPA values are per play/dropback, adjusted for opponent strength and shrunk toward league "
                   "average for small samples. Defensive rows are 'allowed' (lower is better).")
    if not tf.empty:
        t = tf[tf.game_id == gid].set_index("team")
        if len(t) == 2:
            rows = {"Elo rating": "elo_rating", "Off EPA/play (season, shrunk)": "offensive_epa",
                    "Def EPA/play allowed (season, shrunk)": "defensive_epa",
                    "Net EPA last 4": "recent_epa", "Off EPA last 8": "off_epa_l8", "Def EPA last 8": "def_epa_l8",
                    "Success rate last 8": "success_l8", "Turnover rate last 8": "turnover_l8",
                    "Rest days": "rest_days", "Short week": "short_week", "Off bye": "off_bye",
                    "QB status": "quarterback_status", "QB changed vs last game": "quarterback_changed",
                    "QB prior starts": "quarterback_prior_starts", "Games played this season": "games_played_season",
                    "Feature timestamp (UTC)": "feature_timestamp"}
            comp = pd.DataFrame({team: [t.loc[team, c] for c in rows.values()] for team in (g.away_team, g.home_team)},
                                index=list(rows.keys()))
            st.subheader("Team context (point-in-time, before the cutoff)")
            st.dataframe(comp.map(fmt_value), width="stretch")

    st.subheader("Recent form (last 8 completed games before kickoff)")
    cols = st.columns(2)
    for col, team in zip(cols, (g.away_team, g.home_team)):
        rf = recent_form(st.session_state["db_path"], team, str(g.kickoff_utc))
        if rf.empty:
            col.caption(f"{team}: no completed games in the database")
            continue
        rf = rf.iloc[::-1]
        f2 = go.Figure()
        f2.add_scatter(x=rf.opponent + " (" + rf.season.astype(str) + " w" + rf.week.astype(str) + ")",
                       y=rf.off_epa, name="Off EPA/play", mode="lines+markers", line_color="#3a9c6a")
        f2.add_scatter(x=rf.opponent + " (" + rf.season.astype(str) + " w" + rf.week.astype(str) + ")",
                       y=rf.def_epa, name="Def EPA/play allowed", mode="lines+markers", line_color="#c23b4e")
        f2.update_layout(title=team, height=280, margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
        col.plotly_chart(f2, width="stretch")

    st.subheader("What moved the logistic model")
    contrib = logistic_factors(run_id, gid)
    if contrib is None or contrib.empty:
        st.caption("Factor breakdown unavailable (the model file for this run is not on disk).")
    else:
        top = contrib.head(10).iloc[::-1]
        f3 = px.bar(top, x="contribution", y="feature", orientation="h",
                    color=np.where(top.contribution > 0, f"toward {g.home_team}", f"toward {g.away_team}"),
                    color_discrete_sequence=["#2f6db5", "#d4802a"])
        f3.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), legend_title=None,
                         xaxis_title="log-odds contribution (standardised feature × coefficient)")
        st.plotly_chart(f3, width="stretch")
        st.caption("These are associations learned from historical data, describing what drove *this model's* "
                   "output. They are not evidence of causation.")


@st.cache_data(show_spinner=False)
def _run_features(path: str, run_id: str, game_id: str) -> pd.DataFrame | None:
    from nflpickem.backtest import features_from_db
    con = db.connect(path, read_only=True)
    try:
        run = con.execute("SELECT data_cutoff FROM prediction_runs WHERE run_id=?", [run_id]).fetchone()
        cfg = effective_cfg(con)
        return features_from_db(con, cfg, as_of=pd.Timestamp(run[0]), target_game_ids=[game_id])
    finally:
        con.close()


def unit_comparison(run_id: str, game_id: str) -> pd.DataFrame | None:
    f = _run_features(st.session_state["db_path"], run_id, game_id)
    if f is None or f.empty or "home_off_db_epa_adj" not in f:
        return None
    r = f.iloc[0]
    rows = {"QB rating (EPA/dropback, shrunk)": "qb_rating", "Pass offence EPA/dropback": "off_db_epa_adj",
            "Pass defence EPA/dropback allowed": "def_db_epa_adj", "Rush offence EPA/rush": "off_rush_epa_adj",
            "Rush defence EPA/rush allowed": "def_rush_epa_adj", "Sack rate allowed": "off_sack_rate_adj",
            "Sack rate generated": "def_sack_rate_adj", "Explosive pass rate": "off_xpass_rate",
            "Explosive passes allowed": "def_xpass_rate", "Third-down conversion": "off_third_rate",
            "Red-zone TD rate": "off_rz_td_rate", "Interception rate (thrown)": "off_int_rate",
            "CPOE": "off_cpoe"}
    data = {r.away_team: [r.get(f"away_{c}") for c in rows.values()],
            r.home_team: [r.get(f"home_{c}") for c in rows.values()]}
    return pd.DataFrame(data, index=list(rows)).map(fmt_value)


def logistic_factors(run_id: str, game_id: str) -> pd.DataFrame | None:
    import joblib

    from nflpickem.backtest import features_from_db
    from nflpickem.models.ml import logistic_contributions
    with connection() as con:
        run = con.execute("SELECT model_version, data_cutoff FROM prediction_runs WHERE run_id=?", [run_id]).fetchone()
        cfg = effective_cfg(con)
        path = resolve_path(cfg["data"]["model_dir"]) / f"{run[0]}.joblib"
        if not path.exists():
            return None
        feats = features_from_db(con, cfg, as_of=pd.Timestamp(run[1]), target_game_ids=[game_id])
    pm = joblib.load(path)
    c = logistic_contributions(pm.models, feats).iloc[0]
    return pd.DataFrame({"feature": c.index, "contribution": c.values}).sort_values(
        "contribution", key=np.abs, ascending=False)


# --------------------------------------------------------------- page 3
def page_backtest() -> None:
    st.header("Backtesting")
    mode_banner(st.session_state["mode"])
    with connection() as con:
        meta, preds = latest_backtest(con)
        cfg = effective_cfg(con)
    if meta is None:
        st.info("No backtest has been run on this database. Use **Settings → Run backtest** or "
                "`python -m nflpickem backtest`.")
        return
    s = meta["summary"]
    st.info(f"📊 **Historical walk-forward backtest** `{meta['backtest_id']}` · run {str(meta['created_at'])[:16]} UTC  \n"
            f"Seasons evaluated: **{meta['seasons']}** · games from {s['date_range'][0][:10]} to {s['date_range'][1][:10]} · "
            f"holdout included: **{meta['includes_holdout']}** · data: {meta['data_source']}  \n"
            "Each season was predicted by models trained only on earlier seasons. Historical lines are closing lines "
            "(a proxy for the line at pick time), which slightly flatters the market baseline.")
    metrics = pd.DataFrame(s["metrics"])
    pool = pd.DataFrame(s["pool"])
    metrics["Model"] = metrics.model.map(MODEL_LABELS)
    pool["Model"] = pool.model.map(MODEL_LABELS)
    c1, c2 = st.columns(2)
    c1.subheader("Probability quality")
    c1.dataframe(metrics[["Model", "games", "accuracy", "log_loss", "brier", "coverage"]].sort_values("log_loss"),
                 hide_index=True, width="stretch", column_config={
                     "accuracy": st.column_config.NumberColumn(format="%.3f"),
                     "log_loss": st.column_config.NumberColumn("log loss ↓", format="%.4f"),
                     "brier": st.column_config.NumberColumn("Brier ↓", format="%.4f")})
    c2.subheader("Confidence-pool simulation")
    c2.dataframe(pool[["Model", "weeks", "avg_weekly", "sd_weekly", "min_week", "max_week", "pct_of_max",
                       "weeks_best_or_tied"]], hide_index=True, width="stretch", column_config={
        "avg_weekly": st.column_config.NumberColumn("avg pts/week", format="%.2f"),
        "sd_weekly": st.column_config.NumberColumn("sd", format="%.2f"),
        "pct_of_max": st.column_config.NumberColumn("% of max", format="%.3f"),
        "weeks_best_or_tied": st.column_config.NumberColumn("weeks best/tied", format="%.2f")})
    paired = pd.DataFrame(s["paired"])
    st.caption("Blend minus baseline, mean weekly points with 95% CI: " + " · ".join(
        f"vs {MODEL_LABELS[r.b]}: {r.mean_diff:+.2f} [{r.ci_low:+.2f}, {r.ci_high:+.2f}]" for r in paired.itertuples()))

    if preds.empty:
        return
    preds["ml_only"] = preds[["elo", "logistic", "gbm"]].mean(axis=1) if "ml_only" not in preds or preds["ml_only"].isna().all() else preds["ml_only"]
    from nflpickem.evaluation import calibration_table, model_comparison, simulate_pool
    models = st.multiselect("Models", list(MODEL_LABELS), default=["market", "elo", "logistic", "gbm", "blend"],
                            format_func=MODEL_LABELS.get)
    t1, t2, t3, t4 = st.tabs(["Calibration", "By season", "Points over time", "Allocation example"])
    with t1:
        cal = pd.concat([calibration_table(preds, m) for m in models])
        f = px.line(cal, x="predicted", y="observed", color="model", markers=True,
                    color_discrete_map=MODEL_COLORS, hover_data=["games", "bucket"])
        f.add_shape(type="line", x0=0, y0=0, x1=1, y1=1, line=dict(dash="dot", color="gray"))
        f.update_layout(height=450, xaxis_title="Predicted home win probability",
                        yaxis_title="Observed home win rate", xaxis_tickformat=".0%", yaxis_tickformat=".0%")
        st.plotly_chart(f, width="stretch")
    with t2:
        bys = model_comparison(preds, models, by="season")
        metric = st.radio("Metric", ["log_loss", "brier", "accuracy"], horizontal=True)
        f = px.line(bys, x="season", y=metric, color="model", markers=True, color_discrete_map=MODEL_COLORS)
        f.update_layout(height=400)
        st.plotly_chart(f, width="stretch")
    rules = ScoringRules.from_config(cfg["pool"])
    with t3:
        weekly = pd.concat([simulate_pool(preds, m, rules) for m in models])
        weekly["label"] = weekly.season.astype(str) + "-w" + weekly.week.astype(str).str.zfill(2)
        weekly = weekly.sort_values(["season", "week"])
        weekly["cumulative"] = weekly.groupby("model")["points"].cumsum()
        base = weekly[weekly.model == "market"].set_index("label")["cumulative"] if "market" in models else None
        view = st.radio("Show", ["Cumulative points", "Cumulative vs market", "Weekly points"], horizontal=True)
        if view == "Weekly points":
            f = px.box(weekly, x="model", y="points", color="model", color_discrete_map=MODEL_COLORS)
        else:
            y = "cumulative"
            if view == "Cumulative vs market" and base is not None:
                weekly["vs_market"] = weekly["cumulative"] - weekly["label"].map(base)
                y = "vs_market"
            f = px.line(weekly, x="label", y=y, color="model", color_discrete_map=MODEL_COLORS)
        f.update_layout(height=420, xaxis_title=None)
        st.plotly_chart(f, width="stretch")
    with t4:
        weeks = preds[["season", "week"]].drop_duplicates().sort_values(["season", "week"])
        c1, c2 = st.columns(2)
        se = c1.selectbox("Season", sorted(weeks.season.unique(), reverse=True))
        wk = c2.selectbox("Week", sorted(weeks[weeks.season == se].week.unique()))
        d = preds[(preds.season == se) & (preds.week == wk)]
        a = allocate(d.rename(columns={"blend": "_p"}), rules, prob_col="_p")
        from nflpickem.confidence import grade_sheet
        gr = grade_sheet(a, d[["game_id", "home_score", "away_score", "game_status"]], rules)
        st.dataframe(gr[["confidence_points", "away_team", "home_team", "selected_team", "selected_team_probability",
                         "expected_points", "away_score", "home_score", "actual_result", "points_earned"]],
                     hide_index=True, width="stretch")
        st.caption(f"Blend allocation as it would have been submitted: {gr.points_earned.sum():.1f} points earned, "
                   f"{gr.expected_points.sum():.1f} expected, of {gr.confidence_points.sum()} possible.")
    from nflpickem.ablation import latest_ablation
    with connection() as con:
        abl = latest_ablation(con)
    if abl is not None:
        table, paired = abl
        with st.expander("Feature-group ablation (does football intelligence help out-of-sample?)", expanded=True):
            st.dataframe(table.pivot_table(index="variant", columns="model", values="log_loss").round(4),
                         width="stretch")
            st.caption("Log loss by feature-group variant (lower is better), same walk-forward protocol.")
            st.dataframe(paired[["variant", "model", "vs", "mean_diff", "ci_low", "ci_high", "weeks"]].round(2),
                         hide_index=True, width="stretch")
            st.caption("Mean weekly confidence-point difference with 95% CI. A group is enabled only if it "
                       "improved results in development seasons.")
    ratio = pd.DataFrame(s.get("blend_ratio_analysis", []))
    if len(ratio):
        with st.expander("Ex-post market/ML blend ratio analysis (not used for selection)"):
            st.dataframe(ratio, hide_index=True, width="stretch")
            st.caption("Choosing the best row here after seeing results would be in-sample; it is shown for "
                       "transparency only.")


# --------------------------------------------------------------- page 4
def page_tracker() -> None:
    st.header("Season Tracker")
    mode_banner(st.session_state["mode"])
    with connection() as con:
        cfg = effective_cfg(con)
        pool_id = cfg["pool"]["pool_id"]
        seasons = [r[0] for r in con.execute("SELECT DISTINCT season FROM pool_results UNION SELECT DISTINCT season "
                                             "FROM pool_scores ORDER BY 1 DESC").fetchall()]
    c1, c2 = st.columns([1, 3])
    if c1.button("Grade submitted weeks"):
        with connection(write=True) as con:
            n = pipeline.grade_all(con, cfg)
        st.success(f"Graded {n} submitted week(s).")
        st.rerun()
    if not seasons:
        st.info("Nothing graded yet. Freeze a prediction run on **Weekly Picks**, then grade it once games finish.")
    else:
        season = c2.selectbox("Season", seasons)
        with connection() as con:
            t = pipeline.season_tracker(con, pool_id, season)
            scores = con.execute("SELECT * FROM pool_scores WHERE pool_id=? AND season=?", [pool_id, season]).df()
        if len(t):
            m = st.columns(5)
            m[0].metric("Total points", f"{t.points.sum():.1f}")
            m[1].metric("Avg / week", f"{t.points.mean():.1f}")
            m[2].metric("Pick accuracy", pct(t.correct.sum() / max(t.decided.sum(), 1)))
            best, worst = t.loc[t.points.idxmax()], t.loc[t.points.idxmin()]
            m[3].metric("Best week", f"W{int(best.week)}: {best.points:.0f}")
            m[4].metric("Worst week", f"W{int(worst.week)}: {worst.points:.0f}")
            f = go.Figure()
            f.add_bar(x=t.week, y=t.points, name="Points", marker_color="#2f6db5")
            f.add_bar(x=t.week, y=t.max_points - t.points, name="Missed", marker_color="#d9dde3")
            f.add_scatter(x=t.week, y=t.cumulative_points, name="Cumulative", yaxis="y2", line_color="#c23b4e")
            f.update_layout(barmode="stack", height=380, yaxis2=dict(overlaying="y", side="right", rangemode="tozero"),
                            xaxis=dict(title="Week", type="category"), legend=dict(orientation="h"))
            st.plotly_chart(f, width="stretch")
            st.dataframe(t, hide_index=True, width="stretch")
        if len(scores):
            st.subheader("Leaderboard (imported pool scores)")
            lb = scores.groupby("participant").agg(total=("points", "sum"), weeks=("week", "nunique"),
                                                    avg=("points", "mean")).sort_values("total", ascending=False)
            wins = scores[scores.points == scores.groupby("week").points.transform("max")].groupby("participant").size()
            lb["weekly_wins_or_ties"] = wins.reindex(lb.index).fillna(0).astype(int)
            st.dataframe(lb, width="stretch")
    st.subheader("Weekly review (learning loop)")
    with connection() as con:
        wk_runs = con.execute("SELECT DISTINCT season, week FROM prediction_runs ORDER BY 1 DESC, 2 DESC").df()
    if len(wk_runs):
        c1, c2 = st.columns(2)
        rs = c1.selectbox("Review season", sorted(wk_runs.season.unique(), reverse=True), key="rv_s")
        rw = c2.selectbox("Review week", sorted(wk_runs[wk_runs.season == rs].week.unique(), reverse=True), key="rv_w")
        from nflpickem.review import review_week, systematic_check
        with connection() as con:
            rv = review_week(con, cfg, int(rs), int(rw))
            cal = systematic_check(con, cfg)
        if "games" in rv:
            m = st.columns(4)
            m[0].metric("Points", f"{rv['points']:.1f}", f"{rv['points'] - rv['market_sheet_points']:+.1f} vs market sheet")
            m[1].metric("Expected", f"{rv['expected_points']:.1f}")
            m[2].metric("Log loss (model / market)", f"{rv['model']['log_loss']:.3f} / {rv['market']['log_loss']:.3f}")
            m[3].metric("Misses", sum(rv["miss_causes"].values()))
            st.dataframe(pd.DataFrame(rv["games"]), hide_index=True, width="stretch")
            st.caption("Miss causes: data_issue, lineup_change, market_moved, model_deviation, coin_flip, variance. "
                       "A single upset is not evidence of a model flaw; only the calibration check below is.")
        else:
            st.caption(rv.get("status", ""))
        if len(cal):
            st.markdown("**Calibration of submitted picks (all graded weeks)**")
            st.dataframe(cal, hide_index=True, width="stretch")
    st.subheader("Prediction snapshots")
    with connection() as con:
        snaps = pipeline.list_runs(con)
    if len(snaps):
        st.dataframe(snaps[["run_id", "season", "week", "generated_at", "data_cutoff", "model_version", "frozen",
                            "frozen_at", "data_source"]], hide_index=True, width="stretch")
    st.subheader("Import or enter actual pool scores")
    st.caption("CSV columns: season, week, participant, points, is_me (optional). See samples/pool_scores_template.csv.")
    up = st.file_uploader("Pool scores CSV", type="csv")
    if up is not None and st.button("Import CSV"):
        with connection(write=True) as con:
            n = pipeline.import_pool_scores(con, pd.read_csv(up), pool_id)
        st.success(f"Imported {n} rows.")
    blank = pd.DataFrame({"season": pd.Series(dtype=int), "week": pd.Series(dtype=int),
                          "participant": pd.Series(dtype=str), "points": pd.Series(dtype=float),
                          "is_me": pd.Series(dtype=bool)})
    entered = st.data_editor(blank, num_rows="dynamic", width="stretch", key="score_editor")
    if st.button("Save entered scores") and len(entered.dropna(subset=["season", "week", "participant"])):
        with connection(write=True) as con:
            n = pipeline.import_pool_scores(con, entered.dropna(subset=["season", "week", "participant"]), pool_id)
        st.success(f"Saved {n} rows.")


# --------------------------------------------------------------- page 5
def page_settings() -> None:
    st.header("Settings")
    cfg = base_config()
    from nflpickem.ingest.providers import ODDS_PROVIDERS
    st.subheader("Data providers")
    rows = []
    for name, cls in ODDS_PROVIDERS.items():
        ok, why = cls().available()
        rows.append({"provider": name, "type": "odds", "available": "✅" if ok else "❌", "detail": why})
    rows.append({"provider": "nflverse", "type": "schedules / results / play-by-play / injuries",
                 "available": "✅", "detail": "free, no key; updated daily-ish in season"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("API keys are read from environment variables or nfl_pickem/.env (see .env.example). "
               "They are never stored by this page.")

    with st.form("settings"):
        c1, c2 = st.columns(2)
        odds_provider = c1.selectbox("Odds provider", list(ODDS_PROVIDERS),
                                     index=list(ODDS_PROVIDERS).index(cfg["data"]["odds_provider"]))
        stale = c2.number_input("Flag odds older than (hours)", 1, 240, int(cfg["data"]["stale_odds_hours"]))
        st.markdown("**Models**")
        c1, c2, c3 = st.columns(3)
        pick_models = ["blend", "market", "elo", "logistic", "gbm"]
        pick_model = c1.selectbox("Probabilities used for picks", pick_models,
                                  index=pick_models.index(cfg["models"].get("pick_model", "blend")),
                                  format_func=lambda m: MODEL_LABELS.get(m, m))
        cal_opts = ["auto", "none", "platt", "isotonic"]
        calibration = c2.selectbox("Probability calibration", cal_opts, index=cal_opts.index(cfg["models"]["calibration"]))
        gbm_opts = ["auto", "lightgbm", "xgboost", "sklearn"]
        gbm = c3.selectbox("Gradient boosting library", gbm_opts, index=gbm_opts.index(cfg["models"]["gbm_library"]))
        st.markdown("**Blend**")
        c1, c2, c3 = st.columns(3)
        bmode = c1.selectbox("Weights", ["fixed", "learned"], index=["fixed", "learned"].index(cfg["blend"]["mode"]),
                             help="learned = chosen only from earlier out-of-sample backtest predictions")
        mw = c2.slider("Market weight (fixed mode)", 0.0, 1.0, float(cfg["blend"]["market_weight"]), 0.05)
        space = c3.selectbox("Blend space", ["probability", "logit"],
                             index=["probability", "logit"].index(cfg["blend"]["space"]))
        mlw = cfg["blend"]["ml_weights"]
        c1, c2, c3 = st.columns(3)
        w_elo = c1.number_input("ML share: Elo", 0.0, 1.0, float(mlw["elo"]), 0.01)
        w_lr = c2.number_input("ML share: logistic", 0.0, 1.0, float(mlw["logistic"]), 0.01)
        w_gbm = c3.number_input("ML share: GBM", 0.0, 1.0, float(mlw["gbm"]), 0.01)
        st.markdown("**Pool scoring rules**")
        c1, c2, c3, c4 = st.columns(4)
        tie = c1.selectbox("Tie", ["zero", "half", "full"], index=["zero", "half", "full"].index(cfg["pool"]["tie_rule"]))
        post = c2.selectbox("Postponed after submission", ["void", "loss"],
                            index=["void", "loss"].index(cfg["pool"]["postponed_rule"]))
        pmode = c3.selectbox("Point values", ["1_to_n", "custom"],
                             index=["1_to_n", "custom"].index(cfg["pool"]["points_mode"]))
        incl_post = c4.checkbox("Include postseason", bool(cfg["pool"]["include_postseason"]))
        custom = st.text_input("Custom points (comma-separated, used when Point values = custom)",
                               ",".join(map(str, cfg["pool"]["custom_points"])))
        c1, c2, c3 = st.columns(3)
        pool_id = c1.text_input("Pool id", cfg["pool"]["pool_id"])
        cmode = c2.selectbox("Prediction cutoff", ["slate", "per_game"],
                             index=["slate", "per_game"].index(cfg["pool"]["cutoff_mode"]),
                             help="slate: picks lock before the first kickoff of the week")
        offset = c3.number_input("Cutoff hours before kickoff", 0.0, 72.0, float(cfg["pool"]["cutoff_offset_hours"]), 0.5)
        if st.form_submit_button("Save settings", type="primary"):
            try:
                pts = [int(x) for x in custom.split(",") if x.strip()]
                overrides = {
                    "data": {"odds_provider": odds_provider, "stale_odds_hours": int(stale)},
                    "models": {"pick_model": pick_model, "calibration": calibration, "gbm_library": gbm},
                    "blend": {"mode": bmode, "market_weight": mw, "space": space,
                              "ml_weights": {"elo": w_elo, "logistic": w_lr, "gbm": w_gbm}},
                    "pool": {"tie_rule": tie, "postponed_rule": post, "points_mode": pmode, "custom_points": pts,
                             "include_postseason": incl_post, "pool_id": pool_id, "cutoff_mode": cmode,
                             "cutoff_offset_hours": offset},
                }
                load_config(overrides=overrides)  # validate first
                save_local_overrides(overrides)
                st.success("Saved to settings.local.json. New prediction runs and backtests will use these settings.")
            except ValueError as exc:
                st.error(str(exc))

    st.subheader("Data refresh and retraining")
    mode = st.session_state["mode"]
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Refresh data now", disabled=mode == "synthetic", help="Download latest nflverse schedule, lines, "
                 "play-by-play and injuries (real database only)"):
        with st.spinner("Updating from nflverse…"), connection(write=True) as con:
            try:
                st.json(pipeline.update_data(con, base_config()))
            except Exception as exc:
                st.error(str(exc))
    if c2.button("Retrain production model"):
        with st.spinner("Training…"), connection(write=True) as con:
            pm = pipeline.train_production(con, effective_cfg(con), pipeline.effective_now(con))
        st.success(f"Trained {pm.model_version} — weights {pm.weights} ({pm.weights_source})")
    if c3.button("Run backtest"):
        from nflpickem.backtest import run_backtest
        with st.spinner("Walk-forward backtest (about a minute on real data)…"), connection(write=True) as con:
            res = run_backtest(con, effective_cfg(con))
        st.success(f"Backtest {res.backtest_id} complete. See the Backtesting page.")
    if c4.button("Build demo database"):
        from nflpickem.ingest import synthetic
        path = db_path("demo", cfg)
        if path.exists():
            path.unlink()
        con = db.connect(path)
        synthetic.load_into(con)
        con.close()
        st.success("Synthetic demo database rebuilt. Select it in the sidebar.")
    st.caption("Automate with cron / Task Scheduler: `python -m nflpickem weekly` (see README).")


PAGE_FUNCS = {"picks": page_weekly, "matchup": page_matchup, "backtest": page_backtest,
              "tracker": page_tracker, "settings": page_settings}


def main() -> None:
    sidebar()
    forced = st.session_state.get("force_page")  # used by automated UI tests
    if forced in PAGE_FUNCS:
        PAGE_FUNCS[forced]()
        return
    pages = [st.Page(page_weekly, title="Weekly Picks", icon="📋", url_path="picks", default=True),
             st.Page(page_matchup, title="Matchup Analysis", icon="🔍", url_path="matchup"),
             st.Page(page_backtest, title="Backtesting", icon="📊", url_path="backtest"),
             st.Page(page_tracker, title="Season Tracker", icon="🏆", url_path="tracker"),
             st.Page(page_settings, title="Settings", icon="⚙️", url_path="settings")]
    st.navigation(pages).run()


main()
