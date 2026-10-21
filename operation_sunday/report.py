"""The weekly model-selection report (Markdown).

Three kinds of numbers are kept visibly apart:
  [PREGAME FORECAST]   this week's locked package - made before any kickoff;
  [RETROSPECTIVE]      walk-forward out-of-sample evaluation of past weeks;
  [COMPLETED RESULTS]  graded outcomes of earlier locked packages.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .acql_rules import load_recorded_deadeye, pool_points
from .backtest import matched, training_rows
from .features import UNAVAILABLE_FAMILIES
from .metrics import calibration, paired_week_bootstrap, per_game_logloss, summary
from .models import base_candidates
from .selection import segment_table


def _f(x, nd=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:.{nd}f}" if isinstance(x, (float, np.floating)) else str(x)


def _table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_none_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(_f(r[c]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def model_table(scored: pd.DataFrame, models: list[str], meta: dict) -> pd.DataFrame:
    m = matched(scored, models)
    rows = []
    for name in models:
        s = summary(m[m["model"] == name])
        rows.append({"model": name, "Thursday-eligible": "yes" if meta.get(name, {}).get("thursday_eligible") else "NO (benchmark)",
                     "games": s.get("games"), "log loss": s.get("log_loss"), "Brier": s.get("brier"),
                     "accuracy": s.get("accuracy"), "ECE": s.get("ece"), "cal slope": s.get("cal_slope"),
                     "margin MAE": s.get("margin_mae"), "margin RMSE": s.get("margin_rmse")})
    return pd.DataFrame(rows)


def weekly_report(settings, journal, registry, res, scored, feats, d) -> Path:
    from .pipeline import candidate_meta
    meta = candidate_meta(base_candidates())
    pkg, fc = journal.official(d.season, d.week, d.game_type)
    sel = res.decision or {}
    L = [f"# Operation Sunday — {d.season} week {d.week} ({d.game_type})", "",
         "_Research / shadow-production output. Deadeye's production card, ACQL scoring, the public site and "
         "the dashboard are not changed by anything here._", ""]

    L += ["## 1. Thursday deadline and lock status", "",
          f"- Nominal deadline (Thursday {settings.deadline_hour:02d}:{settings.deadline_minute:02d} {settings.timezone}): "
          f"`{d.nominal_utc.isoformat()}`",
          f"- First counted kickoff: `{d.first_kickoff_utc.isoformat() if d.first_kickoff_utc else '–'}`",
          f"- **Lock time: `{d.lock_utc.isoformat()}`** ({d.reason}); run due `{d.run_due_utc.isoformat()}`",
          f"- Package: `{pkg['package_id'] if pkg else '–'}` — status **{pkg['status'] if pkg else 'none'}**"
          + (f", locked `{pkg['locked_at']}`, mode **{pkg['mode']}**, on time: **"
             + ("REPLAY (not a live forecast)" if pkg['mode'] == 'replay' else ('yes' if pkg['on_time'] else 'NO')) + "**"
             if pkg and pkg['status'] == 'locked' else ""),
          f"- Content hash: `{pkg['content_hash'] if pkg else '–'}`", ""]
    for a in res.alerts:
        L.append(f"> ⚠️ {a}")
    L.append("")

    L += ["## 2. Selected model", "",
          f"- **{pkg['model_name'] if pkg else sel.get('model')}**, version `{pkg['model_version'] if pkg else '–'}`",
          f"- Decision: **{sel.get('action', '–')}** — {sel.get('reason', '')}",
          f"- Fallback: {pkg['fallback'] if pkg and pkg['fallback'] else 'none'}",
          f"- Promotion criteria digest `{sel.get('criteria_digest', '–')}`: {json.dumps(sel.get('criteria', {}), default=str)}",
          f"- Experiment record: `{res.experiment_id}`", ""]

    L += ["## 3. [PREGAME FORECAST] This week's locked forecasts", ""]
    if fc:
        df = pd.DataFrame([{"game": f"{f['away']} @ {f['home']}", "kickoff (UTC)": f["kickoff_utc"],
                            "P(home)": f["p_home"], "exp margin": f["exp_margin"], "exp total": f["exp_total"],
                            "ACQL pick": f["pick"], "P(pick credited)": f["p_pick_credited"],
                            "pool line": f["pool_line"], "flags": ", ".join(json.loads(f["missing_flags_json"]))}
                           for f in fc])
        L.append(_table(df))

    # disagreement on this slate among eligible base models
    target = feats[(feats["season"] == d.season) & (feats["week"] == d.week)]
    target = target[target["game_id"].isin([f["game_id"] for f in fc])]
    if len(target):
        train = training_rows(feats, d.lock_utc)
        cols = {}
        for m in base_candidates():
            if m.thursday_eligible and m.kind != "market":
                cols[m.name] = m.fit(train).predict(target)["p_home"].to_numpy()
        dis = pd.DataFrame(cols, index=[f"{a} @ {h}" for a, h in zip(target["away"], target["home"])])
        dis["spread (max-min)"] = dis.max(axis=1) - dis.min(axis=1)
        dis["sides differ"] = ((dis.drop(columns="spread (max-min)") > 0.5).nunique(axis=1) > 1).map({True: "YES", False: ""})
        dis = dis.sort_values("spread (max-min)", ascending=False).reset_index().rename(columns={"index": "game"})
        L += ["## 4. Games where models disagree [PREGAME]", "", _table(dis.head(8))]

    L += ["## 5. QB and injury uncertainty", "",
          "QB availability and injuries are **not modelled**: " + UNAVAILABLE_FAMILIES["qb"] + " "
          + UNAVAILABLE_FAMILIES["injuries"] + " Check late QB news manually; a change after the lock is recorded "
          "as a post-lock note and never alters the locked package.", ""]

    eligible = [n for n in ("home_rate", "elo", "bayes_strength", "logistic", "situational",
                            "ens_equal_football", "ens_stack_football", "ens_perf_football") if n in set(scored["model"])]
    bench = [n for n in ("market_close", "deadeye_line_proxy") if n in set(scored["model"])]
    L += ["## 6. [RETROSPECTIVE] Candidates and benchmarks on identical games", "",
          "Walk-forward, out-of-sample, matched games only. `market_close` and `deadeye_line_proxy` use the "
          "**closing line** (not available on Thursday) and are benchmarks, never inputs. `deadeye_line_proxy` "
          "is a **reconstructed line-only proxy**, not Deadeye's recorded forecasts.", "",
          _table(model_table(scored, eligible + bench, {**meta, **{c["model"]: c for c in sel.get("candidates", [])}}))]
    _, deadeye_note = load_recorded_deadeye()
    L += [f"Recorded Deadeye forecasts: {deadeye_note}", ""]

    rows = []
    for c in sel.get("candidates", []):
        for other, comp in c.get("comparisons", {}).items():
            if comp.get("games"):
                ld = comp["logloss_diff"]
                rows.append({"candidate": c["model"], "vs": other, "games": comp["games"], "weeks": comp["weeks"],
                             "Δ log loss": ld["mean"], "95% CI lo": ld["lo"], "95% CI hi": ld["hi"],
                             "passes all rules": "YES" if c["passes"] else "no",
                             "failed checks": ", ".join(k for k, v in c["checks"].items() if not v) or "–"})
    L += ["### Paired comparisons (week-block bootstrap; negative = candidate better)", "", _table(pd.DataFrame(rows))]

    chosen = (pkg["model_name"] if pkg else sel.get("model")) or settings.designated_baseline
    if chosen in set(scored["model"]):
        by_season = []
        for s_, g in scored[scored["model"].isin([chosen, settings.designated_baseline, "market_close"])].groupby(["season", "model"]):
            sm = summary(g)
            by_season.append({"season": s_[0], "model": s_[1], "games": sm.get("games"), "log loss": sm.get("log_loss"),
                              "accuracy": sm.get("accuracy")})
        L += ["## 7. [RETROSPECTIVE] Out-of-sample performance by season", "", _table(pd.DataFrame(by_season))]

        recent_keys = list(dict.fromkeys(scored.sort_values("cutoff_utc")["week_key"]))[-8:]
        rec = scored[scored["week_key"].isin(recent_keys)]
        rows = []
        for name in dict.fromkeys([chosen, settings.designated_baseline]):
            g = rec[(rec["model"] == name) & rec["home_win"].isin([0.0, 1.0])]
            if g.empty:
                continue
            bs = paired_week_bootstrap(pd.Series(per_game_logloss(g["p_home"], g["home_win"])), g["week_key"],
                                       1000, 0.95, settings.seed)
            rows.append({"model": name, "weeks": bs["weeks"], "games": len(g), "log loss": bs["mean"],
                         "95% CI lo": bs["lo"], "95% CI hi": bs["hi"]})
        L += ["### Recent 8 evaluated weeks, with uncertainty", "", _table(pd.DataFrame(rows)),
              "_Eight weeks is ~120 games: intervals this wide cannot separate models._", ""]

        g = scored[(scored["model"] == chosen) & scored["home_win"].isin([0.0, 1.0])]
        cal = calibration(g["p_home"], g["home_win"])
        L += ["## 8. [RETROSPECTIVE] Probability calibration of the selected model", "",
              f"ECE {cal['ece']:.4f}, recalibration slope {cal['slope']:.3f}", "", _table(pd.DataFrame(cal["table"]))]

        segs = []
        for col, title in (("slice_favourite", "favourite/underdog"), ("slice_prob_bucket", "probability bucket"),
                           ("slice_qb", "QB continuity (retrospective slice)"), ("slice_spread", "market spread range"),
                           ("slice_complete", "data completeness")):
            t = segment_table(scored, list(dict.fromkeys([chosen, settings.designated_baseline, "market_close"])), col)
            if len(t):
                L += [f"### By {title}", "", _table(t)]

    pts = pool_points(matched(scored, eligible + bench))
    if len(pts):
        agg = pts.groupby("model").agg(games=("points", "count"), realised=("points", "sum"),
                                        expected=("exp_points", "sum"), weeks=("week_key", "nunique")).reset_index()
        agg["realised / week"] = agg["realised"] / agg["weeks"]
        agg["expected / week"] = agg["expected"] / agg["weeks"]
        L += ["## 9. [RETROSPECTIVE] ACQL scoring comparison", "",
              "One point per credited pick; favourites of 6.5+ carry a pool line reconstructed from the closing "
              "spread with the commissioner's measured habit (acql.model.backtest.pool_line). Same slate, rules "
              "and eligibility for every model.", "",
              _table(agg[["model", "weeks", "games", "realised / week", "expected / week"]])]

    L += ["## 10. [COMPLETED RESULTS] Earlier locked packages", ""]
    graded = []
    for p in journal.packages():
        if p["status"] != "locked" or (p["season"], p["week"]) == (d.season, d.week):
            continue
        fcs = journal.forecasts(p["package_id"])
        res_rows = {r["game_id"]: r for r in journal.conn.execute("SELECT * FROM results")}
        done = [(f, res_rows[f["game_id"]]) for f in fcs if f["game_id"] in res_rows]
        if not done:
            continue
        y = np.array([1.0 if r["home_score"] > r["away_score"] else 0.0 if r["home_score"] < r["away_score"] else np.nan for _, r in done])
        p_ = np.array([f["p_home"] for f, _ in done])
        ok = ~np.isnan(y)
        graded.append({"package": p["package_id"], "revision": p["revision"], "mode": p["mode"], "on time": ("replay" if p["mode"] == "replay" else "yes" if p["on_time"] else "NO"),
                       "model": p["model_name"], "graded games": int(ok.sum()),
                       "log loss": float(per_game_logloss(p_[ok], y[ok]).mean()) if ok.any() else None,
                       "accuracy": float(((p_[ok] > 0.5) == (y[ok] == 1)).mean()) if ok.any() else None})
    L.append(_table(pd.DataFrame(graded)))

    hist = registry.history()
    L += ["## 11. Changes since the previous approved version", ""]
    L += [f"- {h.get('approved_at') or h.get('at')}: **{h['event']}** → {h.get('model')} ({h.get('reason')})" for h in hist[-5:]] or ["- no approved model yet"]
    L += ["", "## 12. Features and components", ""]
    exp = next((e for e in registry.experiments() if e.get("experiment_id") == res.experiment_id), None)
    if exp:
        for name, w in (exp.get("ensemble_weights") or {}).items():
            L.append(f"- `{name}` ({w['method']}, {w['oof_games']} out-of-fold games): "
                     + ", ".join(f"{c}={x:.3f}" for c, x in zip(w["components"], w["weights"])))
    L += ["- Not testable this release (excluded from every model): "
          + "; ".join(f"**{k}** — {v}" for k, v in UNAVAILABLE_FAMILIES.items()), "",
          "Feature-family ablations: `python -m operation_sunday ablation` (see docs/EVIDENCE_REPORT.md).", ""]

    L += ["## 13. Data freshness and warnings", ""] + [f"- {w}" for w in res.warnings] + (["- none"] if not res.warnings else [])
    L += ["", "## 14. Decision", "", f"**{sel.get('action', '–').upper()}** — {sel.get('reason', '')}", ""]

    out = settings.state_path / "reports" / f"{d.season}-{d.game_type}-w{d.week:02d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out
