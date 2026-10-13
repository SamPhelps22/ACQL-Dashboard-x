"""Head-to-head: the new pick'em model vs the ACQL Dashboard's Deadeye, under ACQL rules.

Reads the dashboard's data read-only (acql-picks.json, data/acql-cards.json, the acql package's
rules) and this project's DuckDB. Nothing in the dashboard is modified.

ACQL rules, applied identically to every card through Deadeye's own code (acql.analytics,
acql.backtest, acql.weekplan):
  * one point per credited pick;
  * a favourite of 6.5+ carries a pool line; it must win by at least the line
    (a win by exactly the line counts) or the underdog is credited;
  * the card is judged against the field (finishing first).
Big Loser and the suicide pool are side games and are not compared here.

Part 1 - the real weeks on file (2023 weeks 8/10/11/13, 2025 weeks 3-4, 2026 weeks 1-2): real slates, the
commissioner's real pool lines and every coach's real picks. Deadeye's live saved cards
exist for 2026 weeks 1-2 (its week-3 card is for 2026, the week-3 sheet is 2025).

Part 2 - 2012-2025 replay of every regular-season week. Pool lines follow the commissioner's
measured habit (acql.backtest.pool_line) applied to the real closing spread; the field is
Deadeye's crowd model. Each pricing feeds the same line math and the same planner.
Deadeye's *live* engine (market line + Prediction Tracker model consensus) cannot be
replayed historically because the Prediction Tracker files are not archived here, so
Part 2 compares the pricing sources that can be: Deadeye's own backtest proxy, the
market line Deadeye's live engine starts from, and the new model.

Usage (from the repository root):  python nfl_pickem/scripts/compare_deadeye.py [--sims 3000]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "nfl_pickem"))

from acql import analytics, weekplan  # noqa: E402
from acql import backtest as dbt  # noqa: E402
from acql.lines import TEAMS, line_from_note  # noqa: E402

from nflpickem.backtest import latest_backtest  # noqa: E402

DB = REPO / "nfl_pickem" / "data" / "nflpickem.duckdb"
OUT = REPO / "nfl_pickem" / "samples"
CODE = {"lar": "LA", "jac": "JAX", "wsh": "WAS"}
SD = analytics.SPREAD_SD


# ------------------------------------------------------------------ pricing helpers
def home_win_prob(margin: float) -> float:
    """Deadeye's real-line distribution: P(home wins), ties counted half."""
    m = abs(margin)
    win = analytics.cover_chance(m, 1, SD)
    tie = analytics.cover_chance(m, 0, SD) - win
    p = win + tie / 2
    return p if margin >= 0 else 1 - p


_GRID = np.round(np.arange(-30, 30.01, 0.5), 1)
_GRID_P = np.array([home_win_prob(m) for m in _GRID])


def margin_from_prob(p: float) -> float:
    """Invert home_win_prob (monotone) so a probability model can use the line math."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return float("nan")
    return float(np.interp(p, _GRID_P, _GRID))


def credited_home_prob(home_margin: float, line: tuple[str, float] | None) -> float:
    """P(home credited) given a priced home margin and the pool line (favourite side, points)."""
    if line is None:
        return home_win_prob(home_margin)
    fav_side, pts = line
    need = analytics.line_need(pts)
    fav_margin = home_margin if fav_side == "home" else -home_margin
    if fav_margin >= 0:
        p_fav = analytics.cover_chance(round(fav_margin, 1), need, SD)
    else:
        p_fav = 1 - analytics.cover_chance(round(-fav_margin, 1), -need + 1, SD)
    return p_fav if fav_side == "home" else 1 - p_fav


def credited(home_score, away_score, line) -> str | None:
    m = float(home_score) - float(away_score)
    if line is None:
        return None if m == 0 else ("home" if m > 0 else "away")
    fav, pts = line
    fav_m = m if fav == "home" else -m
    ok = fav_m >= analytics.line_need(pts)
    return fav if ok else ("away" if fav == "home" else "home")


def card_for(probs: list[float], crowd: list[float], labels: list[str], sims: int) -> tuple[list[str], list[str]]:
    """(plain card, planner card) as 'home'/'away' sides, via Deadeye's planner."""
    plain = ["home" if p >= 0.5 else "away" for p in probs]
    choices = [weekplan.Choice(lab, s, "away" if s == "home" else "home", max(p, 1 - p),
                               c if s == "home" else 1 - c)
               for lab, s, p, c in zip(labels, plain, probs, crowd)]
    plan = weekplan.plan_week(choices, coaches=dbt.OTHER_COACHES, sims=sims)
    take = list(plan.take) if plan is not None else plain
    return plain, take


def crowd_home(market_margin: float, line) -> float:
    """Deadeye's crowd model: share of the field on the home side."""
    fav_home = market_margin >= 0
    on_fav = analytics.CHALK_PRIOR if line is not None else analytics.crowd_on_favourite(abs(market_margin))
    return on_fav if fav_home else 1 - on_fav


def paired(a: pd.Series, b: pd.Series) -> str:
    d = (a - b).dropna()
    se = d.std(ddof=1) / math.sqrt(len(d)) if len(d) > 1 else float("nan")
    return f"{d.mean():+.3f} [{d.mean() - 1.96 * se:+.3f}, {d.mean() + 1.96 * se:+.3f}] over {len(d)} weeks"


# ------------------------------------------------------------------ data
def load(con):
    games = con.execute("""SELECT game_id, season, week, kickoff_utc, home_team, away_team, home_score,
                                  away_score, game_status FROM games WHERE game_type='REG'""").df()
    close = con.execute("""SELECT game_id, avg(home_spread) AS home_spread FROM odds_snapshots
                           WHERE is_closing GROUP BY 1""").df()
    games = games.merge(close, on="game_id", how="left")
    games["market_margin"] = -games["home_spread"]
    _, preds = latest_backtest(con)
    return games, preds


def code_of(name: str) -> str:
    n = " ".join(str(name).lower().split())
    best = None
    for abbr, names in TEAMS.items():
        if any(n == x or n.startswith(x) or x.startswith(n) for x in names):
            if best is None or len(max(names, key=len)) > 0:
                best = abbr
                if n in names:
                    break
    if best is None:
        raise KeyError(name)
    return CODE.get(best, best.upper())


# ------------------------------------------------------------------ part 2
def long_replay(games: pd.DataFrame, preds: pd.DataFrame, sims: int) -> pd.DataFrame:
    hist = [dbt.HistGame(int(r.season), int(r.week), dbt.ALIASES.get(r.home_team, r.home_team),
                         dbt.ALIASES.get(r.away_team, r.away_team), float(r.home_score - r.away_score))
            for r in games[(games.game_status == "final") & games.season.between(2010, 2025)]
            .sort_values("kickoff_utc").itertuples()]
    rated, _ = dbt.rate(hist)
    proxy = {(g.season, g.week, g.home, g.away): g.rated for g in rated}
    d = games[(games.game_status == "final") & games.season.between(2012, 2025) & games.market_margin.notna()]
    d = d.merge(preds[["game_id", "blend", "ml_only"]], on="game_id", how="left")
    rows = []
    for (season, week), wk in d.groupby(["season", "week"]):
        wk = wk.reset_index(drop=True)
        lines, cred, crowd, labels = [], [], [], []
        for r in wk.itertuples():
            pl = dbt.pool_line(r.market_margin)
            line = None if pl is None else (("home" if r.market_margin > 0 else "away"), pl)
            lines.append(line)
            cred.append(credited(r.home_score, r.away_score, line))
            crowd.append(crowd_home(r.market_margin, line))
            labels.append(r.game_id)
        field_right = [(c if w == "home" else 1 - c) if w else 0.0 for c, w in zip(crowd, cred)]
        pricings = {
            "market_line": list(wk.market_margin),
            "deadeye_proxy": [proxy.get((r.season, r.week, dbt.ALIASES.get(r.home_team, r.home_team),
                                         dbt.ALIASES.get(r.away_team, r.away_team)), np.nan) for r in wk.itertuples()],
            "new_blend": [margin_from_prob(p) for p in wk.blend],
            "new_ml_only": [margin_from_prob(p) for p in wk.ml_only],
        }
        for name, margins in pricings.items():
            margins = [m if not (isinstance(m, float) and math.isnan(m)) else mm
                       for m, mm in zip(margins, wk.market_margin)]
            probs = [credited_home_prob(m, ln) for m, ln in zip(margins, lines)]
            plain, take = card_for(probs, crowd, labels, sims)
            for kind, card in (("plain", plain), ("planner", take)):
                right = sum(1 for s, w in zip(card, cred) if s == w)
                rows.append({"season": season, "week": week, "pricing": name, "card": kind, "games": len(wk),
                             "right": right, "p_first": dbt.chance_first(right, field_right)})
        print(f"\r  replayed {season} week {week}", end="", flush=True)
    print()
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ part 1
def real_weeks(games: pd.DataFrame, preds: pd.DataFrame, sims: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    picks = json.loads((REPO / "acql-picks.json").read_text())
    cards = json.loads((REPO / "data" / "acql-cards.json").read_text())["weeks"]
    season_of = {"1": 2026, "2": 2026, "3": 2025, "4": 2025, "8": 2023, "10": 2023, "11": 2023, "13": 2023}
    live = live_predictions(games, [(2026, w) for w in (1, 2)])
    summary, detail = [], []
    for wk_key, sheet in sorted(picks.items(), key=lambda kv: (season_of[kv[0]], int(kv[0]))):
        season, week = season_of[wk_key], int(wk_key)
        g = games[(games.season == season) & (games.week == week)].set_index(["home_team", "away_team"])
        rows = []
        for i, gm in enumerate(sheet["games"], start=1):
            h, a = code_of(gm["home"]), code_of(gm["away"])
            if (h, a) not in g.index:
                print(f"  WARNING {season} wk{week}: sheet game {a}@{h} is not on that NFL week - skipped")
                continue
            r = g.loc[(h, a)]
            parsed, problem = line_from_note(gm.get("note"), gm["away"], gm["home"])
            line = None if not parsed else (("home" if parsed[0] == gm["home"] else "away"), parsed[1])
            rows.append({"n": i, "game_id": r.game_id, "home": h, "away": a, "home_name": gm["home"],
                         "away_name": gm["away"], "line": line, "credited": credited(r.home_score, r.away_score, line),
                         "market_margin": r.market_margin, "picks": gm["picks"]})
        df = pd.DataFrame(rows)
        coaches = list(df.picks.iloc[0].keys())
        score = {c: sum(1 for r in df.itertuples() if r.credited and
                        " ".join(str(r.picks.get(c, "")).lower().split()) ==
                        " ".join(str(r.home_name if r.credited == "home" else r.away_name).lower().split()))
                 for c in coaches}
        crowd = [crowd_home(m, ln) for m, ln in zip(df.market_margin, df.line)]
        entrants = {}
        src = preds.set_index("game_id")
        for name, col in (("new_blend", "blend"), ("new_ml_only", "ml_only")):
            if season == 2026:
                probs_home = [live.get(gid, {}).get(col, np.nan) for gid in df.game_id]
            else:
                probs_home = [src.loc[gid, col] if gid in src.index else np.nan for gid in df.game_id]
            margins = [margin_from_prob(p) for p in probs_home]
            cp = [credited_home_prob(m, ln) for m, ln in zip(margins, df.line)]
            plain, take = card_for(cp, crowd, list(df.game_id), sims)
            entrants[f"{name} (plain)"] = plain
            entrants[f"{name} (planner)"] = take
        mk = [credited_home_prob(m, ln) for m, ln in zip(df.market_margin, df.line)]
        mplain, mtake = card_for(mk, crowd, list(df.game_id), sims)
        entrants["market line (plain)"] = mplain
        entrants["market line (planner)"] = mtake
        card = cards.get(wk_key, {}).get("model") if season == 2026 else None
        if card:
            for kind, key in (("Deadeye live (submitted card)", "take"), ("Deadeye live (plain)", "plain")):
                sides = []
                for r in df.itertuples():
                    t = " ".join(str(card[key].get(str(r.n), "")).lower().split())
                    sides.append("home" if code_of(t) == r.home else "away")
                entrants[kind] = sides
        field = sorted(score.values(), reverse=True)
        for name, sides in entrants.items():
            right = sum(1 for s, w in zip(sides, df.credited) if s == w)
            place = 1 + sum(1 for v in field if v > right)
            summary.append({"season": season, "week": week, "entrant": name, "right": right,
                            "games": len(df), "place": place, "coaches": len(coaches),
                            "best_coach": field[0], "pool_average": round(float(np.mean(field)), 2)})
        for r, *sides in zip(df.itertuples(), *entrants.values()):
            detail.append({"season": season, "week": week, "game": f"{r.away}@{r.home}",
                           "pool_line": "" if r.line is None else f"{r.home if r.line[0]=='home' else r.away} by {r.line[1]:g}",
                           "credited": "" if r.credited is None else (r.home if r.credited == "home" else r.away),
                           **{k: (r.home if s == "home" else r.away) for k, s in zip(entrants, sides)}})
    return pd.DataFrame(summary), pd.DataFrame(detail)


def live_predictions(games: pd.DataFrame, weeks: list[tuple[int, int]]) -> dict:
    """New model as-of each 2026 week's cutoff (retrained as of then; nothing saved)."""
    from nflpickem import db, pipeline
    from nflpickem.config import load_config
    cfg = load_config()
    con = db.connect(DB)
    out = {}
    try:
        for s, w in weeks:
            _, picks = pipeline.predict_week(con, cfg, s, w, save=False)
            ml = picks[["elo_home_probability", "logistic_home_probability",
                        "gradient_boosting_home_probability"]].mean(axis=1)
            for gid, b, m in zip(picks.game_id, picks.blended_home_probability, ml):
                out[gid] = {"blend": b, "ml_only": m}
            print(f"  new model predicted {s} week {w} as of its cutoff")
    finally:
        con.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--skip-long", action="store_true")
    args = ap.parse_args()
    con = duckdb.connect(str(DB), read_only=True)
    games, preds = load(con)
    con.close()
    pd.set_option("display.width", 220)

    print("PART 1 - real ACQL weeks (real slates, pool lines and coaches)")
    summ, detail = real_weeks(games, preds, args.sims)
    summ.to_csv(OUT / "deadeye_vs_new_real_weeks.csv", index=False)
    detail.to_csv(OUT / "deadeye_vs_new_real_weeks_picks.csv", index=False)
    print(summ.pivot_table(index=["season", "week"], columns="entrant", values="right").to_string())
    print(summ.pivot_table(index=["season", "week"], columns="entrant", values="place").to_string())
    print(summ.groupby(["season", "week"])[["pool_average", "best_coach", "coaches"]].first().to_string())

    if args.skip_long:
        return
    print("\nPART 2 - 2012-2025 replay under ACQL rules")
    long = long_replay(games, preds, args.sims)
    long.to_csv(OUT / "deadeye_vs_new_replay_2012_2025.csv", index=False)
    s = long.groupby(["pricing", "card"]).agg(weeks=("right", "size"), right_per_week=("right", "mean"),
                                               pct_right=("right", lambda x: x.sum()),
                                               weekly_wins=("p_first", "sum")).reset_index()
    games_total = long.groupby(["pricing", "card"])["games"].sum().to_numpy()
    s["pct_right"] = s["pct_right"] / games_total
    print(s.round(3).to_string(index=False))
    pv = long.pivot_table(index=["season", "week"], columns=["pricing", "card"], values="right")
    pf = long.pivot_table(index=["season", "week"], columns=["pricing", "card"], values="p_first")
    for card in ("plain", "planner"):
        for other in ("deadeye_proxy", "new_ml_only", "new_blend"):
            print(f"  {card}: {other} - market_line  right/week {paired(pv[(other, card)], pv[('market_line', card)])};"
                  f"  P(first)/week {paired(pf[(other, card)], pf[('market_line', card)])}")
    print("  planner - plain (market_line): right/week",
          paired(pv[("market_line", "planner")], pv[("market_line", "plain")]),
          "; P(first)/week", paired(pf[("market_line", "planner")], pf[("market_line", "plain")]))


if __name__ == "__main__":
    main()
