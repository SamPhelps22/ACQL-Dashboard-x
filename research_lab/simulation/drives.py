"""Model B - drive-level Monte Carlo.

A game is a sequence of possessions. Everything below is estimated from the
snapshot's completed drives (last LOOKBACK seasons) - nothing from the game
being simulated:

    start field position   empirical, by what ended the previous drive
                           (kickoff after a score or at the half, punt, turnover,
                           turnover on downs, missed field goal, safety kick)
    drive outcome          TD / FG / turnover / safety / no score (punt, downs, missed FG,
                           end of half), by start-field bucket for the league, then
                           tilted for the offence and the defence on the field:
                           opponent-adjusted per-drive TD, score and turnover rates
                           (ridge-shrunk, home edge included) as multipliers
    fourth downs           inside the outcome rates: turnover on downs and missed
                           field goals are part of "no score" by field position
    possessions            total drives in a game drawn from the league's empirical
                           count, nudged by both teams' recent pace; drives alternate
    end of half / game     "end of half" drives are part of the outcome rates; a tie
                           after regulation plays alternating overtime drives (first
                           score wins, up to OT_DRIVES), else a tie
    conversions            touchdown = 6 + extra point at the league rate (2-pt tries
                           are not modelled separately)

Each game is simulated N_SIMS times with a seed fixed by its game_id, so a
rerun gives identical numbers. The simulated games are one forecast; they
are never used as training examples.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .. import config
from ..features import ratings
from ..models.base import Model

N_SIMS = 4000
LOOKBACK = 3
BUCKETS = np.array([0, 20, 40, 60, 75, 85, 100])          # yardline_100 edges
OUTCOMES = ["TD", "FG", "NONE", "TO", "SAFETY"]
PREV = ["KICKOFF", "PUNT", "TO", "DOWNS", "MISS", "SAFETY"]
XP_RATE = 0.95
OT_DRIVES = 4
DRIVE_STATS = {"td_drive": ("tds", "n_dr"), "score_drive": ("scores", "n_dr"), "to_drive": ("tos", "n_dr")}


def _bucket(y):
    return np.clip(np.searchsorted(BUCKETS, y, side="left") - 1, 0, len(BUCKETS) - 2)


def _prev_key(r):
    return {"TD": "KICKOFF", "FG": "KICKOFF", "KICKOFF_HALF": "KICKOFF", "END": "KICKOFF", "PUNT": "PUNT",
            "TO": "TO", "DOWNS": "DOWNS", "MISS": "MISS", "SAFETY": "SAFETY"}.get(r, "PUNT")


def _outcome(r):
    return {"TD": "TD", "FG": "FG", "TO": "TO", "SAFETY": "SAFETY"}.get(r, "NONE")


class League:
    """League-level drive tables from a snapshot."""

    def __init__(self, drives: pd.DataFrame, season: int, games: pd.DataFrame | None = None):
        d = drives[(drives["season"] >= season - LOOKBACK) & drives["start_yardline_100"].notna()]
        d = d.assign(b=_bucket(d["start_yardline_100"].values), o=d["result"].map(_outcome),
                     pk=d["prev_result"].map(_prev_key))
        self.starts = {k: np.clip(d.loc[d["pk"] == k, "start_yardline_100"].values, 1, 99) for k in PREV}
        for k in PREV:
            if len(self.starts[k]) < 30:
                self.starts[k] = np.clip(d["start_yardline_100"].values, 1, 99)
        tab = pd.crosstab(d["b"], d["o"]).reindex(index=range(len(BUCKETS) - 1), columns=OUTCOMES, fill_value=0)
        tab = tab + 1.0                                    # a pseudo-count per cell
        self.probs = (tab.T / tab.sum(axis=1)).T.values    # bucket x outcome
        per_game = d.groupby("game_id").size()
        self.n_drives = per_game.values if len(per_game) else np.array([23])
        none = d[d["o"] == "NONE"]["result"]
        self.share_downs = float((none == "DOWNS").mean()) if len(none) else 0.1
        self.share_miss = float((none == "MISS").mean()) if len(none) else 0.07
        # points no drive outcome explains (return and defensive TDs, 2-pt tries): per team per game
        self.extra_td = 0.0
        if games is not None and len(d):
            gp = games[games["game_id"].isin(d["game_id"].unique())]
            o = d["o"]
            drive_pts = (6 + XP_RATE) * (o == "TD").sum() + 3 * (o == "FG").sum() \
                + 2 * (o == "SAFETY").sum()
            gap = gp["total_points"].sum() - drive_pts
            self.extra_td = max(gap / 7.0 / (2 * max(len(gp), 1)), 0.0)
        self.rate = {"td": (d["o"] == "TD").mean(), "score": d["o"].isin(["TD", "FG"]).mean(),
                     "to": (d["o"] == "TO").mean()}


def team_drive_games(drives: pd.DataFrame) -> pd.DataFrame:
    """Per (game, offence): drives, TDs, scores, turnovers - shaped for ratings.unit_ratings."""
    o = drives["result"].map(_outcome)
    t = drives.assign(td=(o == "TD").astype(int), sc=o.isin(["TD", "FG"]).astype(int), to=(o == "TO").astype(int))
    g = t.groupby(["game_id", "posteam", "defteam"]).agg(season=("season", "first"), week=("week", "first"),
                                                         n_dr=("td", "size"), tds=("td", "sum"), scores=("sc", "sum"),
                                                         tos=("to", "sum")).reset_index()
    return g.rename(columns={"posteam": "team", "defteam": "opp"})


def _seed(game_id: str) -> int:
    return (int(hashlib.sha256(game_id.encode()).hexdigest()[:8], 16) + config.SEED) % (2 ** 32)


def drive_probs(league: League, td_mult: float, sc_mult: float, to_mult: float) -> np.ndarray:
    """Bucket x outcome probabilities for one offence-vs-defence pairing."""
    p = league.probs.copy()
    td = np.clip(p[:, 0] * td_mult, 1e-4, 0.95)
    fg = np.clip((p[:, 0] + p[:, 1]) * sc_mult - td, 1e-4, 0.95)
    to = np.clip(p[:, 3] * to_mult, 1e-4, 0.5)
    sf = p[:, 4]
    none = np.clip(1 - td - fg - to - sf, 0.01, 1)
    out = np.column_stack([td, fg, none, to, sf])
    return out / out.sum(axis=1, keepdims=True)


def simulate(league: League, probs_home: np.ndarray, probs_away: np.ndarray, n_drives_mean: float,
             n: int = N_SIMS, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Final (home, away) scores of `n` simulated games."""
    rng = np.random.default_rng(seed)
    base = rng.choice(league.n_drives, size=n)
    total = np.clip(np.round(base + (n_drives_mean - league.n_drives.mean())), 12, 36).astype(int)
    pts = np.zeros((n, 2))
    home_ball = rng.random(n) < 0.5
    prev = np.zeros(n, dtype=int)                       # index into PREV; 0 = KICKOFF
    after = np.array([0, 0, 1, 2, 5])                   # outcome -> what the next drive starts after
    rows = np.arange(n)

    def one_drive(active, home_ball, prev):
        start = np.empty(n)
        for k, name in enumerate(PREV):
            m = active & (prev == k)
            if m.any():
                start[m] = rng.choice(league.starts[name], size=m.sum())
        b = _bucket(np.where(active, start, 50))
        u = rng.random(n)
        P = np.where(home_ball[:, None], probs_home[b], probs_away[b])
        res = np.minimum((u[:, None] > np.cumsum(P, axis=1)).sum(axis=1), 4)
        off = np.where(home_ball, 0, 1)
        td, fg, sf = active & (res == 0), active & (res == 1), active & (res == 4)
        xp = rng.random(n) < XP_RATE
        pts[rows, off] += np.where(td, 6 + xp, 0) + np.where(fg, 3, 0)
        pts[rows, 1 - off] += np.where(sf, 2, 0)
        new_prev = after[res]
        alt = rng.random(n)
        none = res == 2
        new_prev = np.where(none & (alt < league.share_downs), 3, new_prev)
        new_prev = np.where(none & (alt >= league.share_downs) & (alt < league.share_downs + league.share_miss), 4,
                            new_prev)
        return np.where(active, new_prev, prev)

    for i in range(int(total.max())):
        active = i < total
        prev = one_drive(active, home_ball, prev)
        home_ball = np.where(active, ~home_ball, home_ball)
    # return / defensive touchdowns, at the league's rate, either side
    extra = rng.poisson(league.extra_td, size=(n, 2)) * 7
    pts += extra
    # overtime: alternate drives from a kickoff, first score wins
    tied = pts[:, 0] == pts[:, 1]
    prev = np.where(tied, 0, prev)
    home_ball = rng.random(n) < 0.5
    for _ in range(OT_DRIVES):
        active = tied & (pts[:, 0] == pts[:, 1])
        if not active.any():
            break
        prev = one_drive(active, home_ball, prev)
        home_ball = np.where(active, ~home_ball, home_ball)
    return pts[:, 0], pts[:, 1]


class DriveSim(Model):
    name = "B_drive_sim"
    version = "1"
    provenance = "nflverse play-by-play drives; Monte Carlo"

    def __init__(self, n_sims: int = N_SIMS, keep: bool = False):
        self.n_sims, self.keep = n_sims, keep
        self.dist: dict = {}

    def predict(self, snap, week):
        s, w = int(week["season"].iloc[0]), int(week["week"].iloc[0])
        league = League(snap.drives, s, snap.games)
        tdg = team_drive_games(snap.drives[snap.drives["season"] >= s - 2])
        rt = ratings.unit_ratings(tdg, snap.games, s, w, stats=DRIVE_STATS)
        r = rt.set_index("team") if len(rt) else pd.DataFrame()
        home_adj = rt.attrs.get("home", {}) if len(rt) else {}
        pace = tdg.groupby("team")["n_dr"].mean() if len(tdg) else pd.Series(dtype=float)
        lg_pace = tdg["n_dr"].mean() if len(tdg) else 11.5
        rows = []
        for g in week.itertuples():
            def mult(off, de, home):
                out = []
                for stat, key in (("td_drive", "td"), ("score_drive", "score"), ("to_drive", "to")):
                    base = league.rate[key]
                    o = r[f"off_{stat}"].get(off, 0.0) if len(r) else 0.0
                    d = r[f"def_{stat}"].get(de, 0.0) if len(r) else 0.0
                    h = (home_adj.get(stat, 0.0) / 2) * (1 if home else -1) * (0 if g.neutral else 1)
                    out.append(max(base + o + d + h, 0.2 * base) / base)
                return out
            ph = drive_probs(league, *mult(g.home_team, g.away_team, True))
            pa = drive_probs(league, *mult(g.away_team, g.home_team, False))
            nd = (pace.get(g.home_team, lg_pace) + pace.get(g.away_team, lg_pace)) * 0.5 + lg_pace
            nd_mean = league.n_drives.mean() + 0.5 * (nd - 2 * lg_pace)
            hs, as_ = simulate(league, ph, pa, nd_mean, self.n_sims, _seed(g.game_id))
            m = hs - as_
            p = np.mean(m > 0) + 0.5 * np.mean(m == 0)
            if self.keep:
                self.dist[g.game_id] = (hs.astype(np.int16), as_.astype(np.int16))
            rows.append({"game_id": g.game_id, "p_home": float(np.clip(p, 1e-3, 1 - 1e-3)), "exp_margin": float(m.mean()),
                         "exp_total": float((hs + as_).mean()), "margin_sd": float(m.std()),
                         "missing": {"p_tie": float(np.mean(m == 0)), "mc_se": float(np.sqrt(p * (1 - p) / self.n_sims))}})
        return pd.DataFrame(rows)
