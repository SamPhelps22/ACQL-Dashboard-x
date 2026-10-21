"""Markdown reports from saved outputs. Nothing here computes a forecast."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config
from . import md

LEGEND = """**Information sets.** `week_start` = Tuesday 09:00 ET, completed games only (prospective-equivalent).
`pre_kickoff` = adds confirmed starters / timestamped final injury report (~90 min before kickoff; after the ACQL card
deadline). `closing_retrospective` = closing lines and/or observed weather: a benchmark, not a forecast anyone could
have made at the card deadline. Deadeye's line-only proxy is Deadeye's own margin->chance curve applied to the
nflverse **closing** spread; it is not Deadeye's recorded forecast."""

KEY = ["market_ml_close", "deadeye_line_only_proxy", "D_market_full", "G_market_stack", "G_free_stack",
       "G_free_equal", "A_qb_confirmed", "A_qb_weekstart", "E_bayes", "C_situational", "B_drive_sim",
       "challenger_elo", "F_matchup_interaction"]


def _load(name):
    p = config.OUTPUTS / name
    if not p.exists():
        return None
    return json.loads(p.read_text()) if name.endswith(".json") else pd.read_csv(p)


def _results(ev: dict, title: str) -> list[str]:
    L = [f"# {title}", "", f"Period: **{ev['period']}**. Regular-season games: {ev['games_total']}; scored on the "
         f"matched set every model priced: **{ev['games_matched']}** (ties excluded from probability scores).", "",
         LEGEND, "", "## Probability scores (matched games)", ""]
    s = pd.DataFrame(ev["summary"])
    cols = ["model", "info_set", "uses_market", "n", "log_loss", "log_loss_cal", "brier", "accuracy", "ece",
            "margin_mae", "total_mae"]
    L += [md.table(s[[c for c in cols if c in s]]), "",
          "`log_loss_cal` = after Platt scaling fitted on the same model's earlier seasons only (first two scored "
          "seasons uncalibrated are excluded from that column's average, so it covers fewer games).", ""]
    p = pd.DataFrame(ev["paired"])
    for bench in ("market_ml_close", "deadeye_line_only_proxy", "challenger_elo"):
        q = p[p["b"] == bench].sort_values("diff")
        if not len(q):
            continue
        q = q.assign(verdict=np.where(q["hi"] < 0, "better (CI < 0)", np.where(q["lo"] > 0, "worse (CI > 0)", "no clear difference")))
        L += [f"## Paired log-loss difference vs `{bench}`", "",
              "Model minus benchmark, per game; 95% interval from resampling whole weeks (2000 draws). Negative = model better.", "",
              md.table(q[["a", "n", "weeks", "diff", "lo", "hi", "p_a_better", "verdict"]].rename(columns={"a": "model"}), 4), ""]
    L += [f"**Multiple comparisons.** {ev['n_comparisons']} paired log-loss comparisons are reported here (plus Brier "
          "versions). At 95% about one in twenty intervals excludes zero by chance alone, so an isolated 'better' "
          "or 'worse' among many should not be read as a finding without replication on the holdout.", ""]
    bs = pd.DataFrame(ev["by_season"])
    keys = [k for k in KEY if k in set(bs["model"])]
    piv = bs[bs["model"].isin(keys)].pivot_table(index="season", columns="model", values="log_loss")[keys]
    L += ["## Log loss by season", "", md.table(piv.reset_index(), 4), ""]
    ph = pd.DataFrame(ev["by_phase"])
    piv = ph[ph["model"].isin(keys)].pivot_table(index="phase", columns="model", values="log_loss")[keys]
    piv = piv.reindex(["weeks 1-4", "weeks 5-9", "weeks 10-18"])
    L += ["## Early vs late season (log loss)", "", md.table(piv.reset_index(), 4), ""]
    if "bayes_uncertainty" in ev:
        bu = pd.DataFrame([dict(v, phase=k) for k, v in ev["bayes_uncertainty"].items()])
        L += ["## Does explicit uncertainty help? (E_bayes vs E_bayes_plugin)", "",
              "Same filter, same means; E_bayes widens each forecast by its posterior state variance, the plug-in "
              "uses a fixed spread. Negative = uncertainty helps.", "",
              md.table(bu[["phase", "n", "diff", "lo", "hi", "p_a_better"]], 5), ""]
    side = pd.DataFrame(ev["by_side"])
    L += ["## Favourite / underdog picks (straight-up accuracy)", "",
          "How often each model's pick is the closing-market favourite, and how often it is right when it is and isn't.", "",
          md.table(side[side["model"].isin(keys)], 3), ""]
    L += ["## Reliability (said vs came, by probability band)", ""]
    for m in ("market_ml_close", "E_bayes", "G_free_stack", "B_drive_sim"):
        if m in ev["reliability"]:
            L += [f"**{m}**", "", md.table(pd.DataFrame(ev["reliability"][m]), 3), ""]
    a = pd.DataFrame(ev["acql"])
    rows = []
    for r in ev["acql"]:
        row = {"model": r["model"], "weeks": r["weeks"], "total": r["total"], "per_week": r["per_week"],
               "sd_week": r["sd_week"]}
        for b in ("market_ml_close", "deadeye_line_only_proxy"):
            v = r.get(f"vs_{b}")
            if v:
                row[f"vs {b} /wk"] = v["diff_per_week"]
                row[f"95% CI ({b})"] = f"[{v['lo']:+.2f}, {v['hi']:+.2f}]"
        rows.append(row)
    L += ["## ACQL cards under the repository's rules", "",
          "One point per correct pick; favourites of 6.5+ carry a pool line `max(7, floor(spread)+1)` and must win by "
          "`ceil(line)` (acql.model.backtest.pool_line, acql.analytics.line_need). Pool lines are **reconstructed from "
          "the closing spread** for every season; the repository records one ruleset, applied throughout. "
          "Intervals resample whole weeks.", "", md.table(pd.DataFrame(rows), 3), ""]
    bys = pd.DataFrame(ev["acql_by_season"])
    piv = bys[bys["model"].isin(keys)].pivot_table(index="season", columns="model", values="points")
    L += ["### ACQL points by season", "", md.table(piv.reset_index(), 0), ""]
    return L


def ensemble_section(tag: str) -> list[str]:
    ch = _load(f"ensemble_choices_{tag}.json")
    fc = _load(f"forecasts_all_{tag}.csv.gz")
    if ch is None or fc is None:
        return []
    if tag == "holdout":           # incremental-value stacks are taught on the earlier (development) seasons
        dev = _load("forecasts_dev.csv.gz")
        if dev is not None:
            fc = pd.concat([dev, fc]).drop_duplicates(["game_id", "model"], keep="last")
    from ..data import games
    from ..ensemble import stack
    from ..metrics.scoring import block_bootstrap
    from .. import pipeline
    L = ["## Ensemble (Model G): what was chosen", "",
         "Components were selected each season by forward selection on earlier seasons' out-of-fold forecasts "
         f"(walk-forward validation on the last {stack.VAL_SEASONS} training seasons; a component joins only if it "
         f"lowers validation log loss by {stack.MIN_GAIN}).", ""]
    df = pd.DataFrame(ch)
    df["chosen"] = df["chosen"].map(lambda c: ", ".join(c))
    L += [md.table(df[["season", "ensemble", "chosen"]]), ""]
    g = games.load()[["game_id", "home_win", "season"]]
    scored = fc["season"].unique()
    seasons = [s for s in sorted(scored) if s >= (config.DEV_FROM if tag == "dev" else config.HOLDOUT[0])]
    for label, comps in (("market-free", pipeline.FREE), ("market-informed", pipeline.INFORMED)):
        sub = fc[fc["season"].isin(seasons)]
        seasons = [s for s in seasons if s in set(sub["season"])]
        cor = stack.error_correlation(sub, g, comps)
        L += [f"### Error correlation ({label} components)", "",
              "Correlation of (forecast - outcome) across games. Outcome noise is shared by every model, so these "
              "sit near 1 for any set of decent forecasts; the incremental-value table below is the sharper test.", "",
              md.table(cor.reset_index().rename(columns={"model": "component"}), 2), ""]
        inc = stack.incremental(fc, g, comps, seasons)
        rows = []
        for c, grp in inc.groupby("component"):
            mean, lo, hi, draws = block_bootstrap(grp["diff"].values, (grp["season"].astype(str) + "-" + grp["week"].astype(str)).values)
            rows.append({"component": c, "n": len(grp), "with_minus_without": mean, "lo": lo, "hi": hi,
                         "p_adds": float(np.mean(draws < 0))})
        L += [f"### Incremental value given all other {label} components", "",
              "Walk-forward logistic stack with vs without the component (negative = it adds information).", "",
              md.table(pd.DataFrame(rows).sort_values("with_minus_without"), 5), ""]
    return L


def ablation_section(tag: str) -> list[str]:
    ab = _load(f"ablation_{tag}.csv")
    if ab is None:
        return []
    ok = ab[ab["comparison"] != "not run"].copy()
    ok["verdict"] = np.where(ok["hi"] < 0, "adds (CI < 0)", np.where(ok["lo"] > 0, "hurts (CI > 0)", "no clear effect"))
    nr = ab[ab["comparison"] == "not run"]
    return ["## Signal discovery: feature-family ablations", "",
            "Each row compares two walk-forward logistic regressions on identical games (penalty fixed in advance). "
            "`diff` = log loss with the family minus without; negative = the family adds information. "
            "Every run is in `research_lab/experiments/registry.jsonl`, including failures.", "",
            md.table(ok.assign(n=ok["n"].astype(int))[["family", "comparison", "n", "ll_with", "ll_without", "diff", "lo", "hi", "p_improves", "verdict"]], 4), "",
            "### Not run (no usable historical data)", "", md.table(nr[["family", "note"]]), ""]


def sim_section() -> list[str]:
    v = _load("sim_validation.json")
    if v is None:
        return []
    k = v["key_numbers"]
    return ["## Model B validation (drive simulation)", "",
            f"Seasons {v['seasons'][0]}-{v['seasons'][1]}, {v['games']} games, {4000} simulations each.", "",
            "PIT deciles (count of real outcomes falling in each tenth of their own simulated distribution; "
            f"uniform would be about {v['games'] / 10:.0f} each):", "",
            md.table(pd.DataFrame({"decile": range(1, 11), "margin": v["pit_margin_deciles"], "total": v["pit_total_deciles"]}), 0), "",
            "Share of games ending on key margins:", "",
            md.table(pd.DataFrame({"abs margin": k["margins"], "simulated": k["simulated"], "real": k["real"]}), 4), "",
            f"Totals: simulated mean {v['totals']['sim_mean']:.1f} vs real {v['totals']['real_mean']:.1f}; "
            f"simulated spread within a game {v['totals']['sim_sd_within_game']:.1f} vs real spread around the "
            f"simulated mean {v['totals']['real_sd_around_sim_mean']:.1f}.", "",
            "Convergence (home win chance for the same six games as draws increase):", "",
            md.table(pd.DataFrame([{"n": c["n"], **{f"g{i + 1}": p for i, p in enumerate(c["p_home"])}} for c in v["convergence"]]), 4), "",
            f"Monte Carlo standard error at N=4000 is at most {v['mc_se_at_4000']:.4f}. The simulated games are a single "
            "forecast each; they are never used as training rows.", ""]


def extension_section() -> list[str]:
    h = _load("model_h.json")
    d = _load("deadeye_2026.json")
    L = []
    if h is not None:
        L += ["## Model H (scheme matchups) extension", "", h.get("note", ""), "", md.table(pd.DataFrame(h["rows"]), 4), ""]
    if d is not None:
        L += ["## Deadeye's 2026 inputs, recomputed, against the lab (2026 to date)", "", d.get("note", ""), "",
              md.table(pd.DataFrame(d["rows"]), 4), ""]
    return L


def all_reports() -> list[str]:
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    written = []
    for tag, title in (("dev", "Development results (walk-forward, 2012-2023)"),
                       ("holdout", "Frozen holdout results (2024-2025)")):
        ev = _load(f"eval_{tag}.json")
        if ev is None:
            continue
        L = _results(ev, title) + ensemble_section(tag) + ablation_section(tag)
        if tag == "dev":
            L += sim_section()
        L += extension_section() if tag == "holdout" else []
        path = config.REPORTS / f"RESULTS_{tag.upper()}.md"
        path.write_text("\n".join(L))
        written.append(str(path))
    return written
