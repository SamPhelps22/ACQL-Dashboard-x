"""Point-in-time features: every game described as of its week's forecast deadline.

The walk
--------
Each (season, week) gets one deadline: `deadline_minutes_before_first_kickoff`
before its earliest kickoff (ACQL's cards are due about an hour before
Thursday's game). Every played game becomes a "finished" event at kickoff +
`game_duration_hours`. Walking the deadlines in time order, all events up to
a deadline are applied to the team, QB and Elo states, and only then is every
game of that week described from those states. So:

  * a game never sees its own result, nor any game that kicks off after the
    deadline - including the same week's Thursday game for a Sunday game;
  * nothing is a season total: every rating is a shrunk, exponentially
    weighted average of games already finished;
  * nothing global is fitted here (no scaling, no league-wide averages over
    the whole table) - league means are running averages too.

Ratings
-------
Team metrics (pbp.METRICS, offence and defence) are exponentially weighted
over games (long and short half-lives), pulled toward the running league mean
by `prior_games` pseudo-games, and lose most of their weight over the
offseason (`season_carry`). EPA, pass EPA, rush EPA and success rate are
opponent-adjusted: each game's number is corrected by how good the opponent's
unit was rated before that game.

Quarterbacks are rated per player across teams, weighted by dropbacks and
pulled toward a replacement level (`qb_replacement_shift` below league
average) - so an unknown backup is assumed below average until he shows
otherwise. The forecast assumes the QB who started the team's previous game
(`qb_source = "previous_start"`): the only starter known at a Thursday
deadline without timestamped injury reports.

Nothing here reads a betting line or anything from the dashboard.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Config
from .elo import EloState
from .pbp import METRICS
from .venues import distance_km, utc_offset_hours

ADJUSTED = ("epa", "pass_epa", "rush_epa", "success")
SIDES = ("off", "def")
LEAGUE_HALF_LIFE = 512.0   # team-games (about two seasons) for the running league means
QB_RUSH_DECAY = 0.5 ** (1 / 8)   # a QB's rushing EPA per start, half-life eight starts


class Ewma:
    """An exponentially weighted mean that can be shrunk toward a prior."""

    __slots__ = ("w", "wx")

    def __init__(self) -> None:
        self.w = 0.0
        self.wx = 0.0

    def add(self, x: float, decay: float, weight: float = 1.0) -> None:
        if x is None or not math.isfinite(x):
            return
        self.w = self.w * decay + weight
        self.wx = self.wx * decay + weight * x

    def carry(self, share: float) -> None:
        self.w *= share
        self.wx *= share

    def value(self, prior: float, k: float) -> float:
        if not math.isfinite(prior):
            return self.wx / self.w if self.w > 0 else float("nan")
        return (self.wx + k * prior) / (self.w + k)

    @property
    def raw(self) -> float:
        return self.wx / self.w if self.w > 0 else float("nan")


@dataclass
class TeamState:
    long: dict = field(default_factory=lambda: defaultdict(Ewma))
    short: dict = field(default_factory=lambda: defaultdict(Ewma))
    games: int = 0
    season_games: int = 0
    last_kickoff: pd.Timestamp | None = None
    last_starter: str | None = None
    last_starter_name: str | None = None
    starters: deque = field(default_factory=lambda: deque(maxlen=6))


@dataclass
class QbState:
    epa: Ewma = field(default_factory=Ewma)
    sack: Ewma = field(default_factory=Ewma)
    ints: Ewma = field(default_factory=Ewma)
    cpoe: Ewma = field(default_factory=Ewma)
    rush: Ewma = field(default_factory=Ewma)
    dropbacks: float = 0.0
    name: str = ""


class League:
    """Every state the features are read from, advanced one finished game at a time."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        r = cfg.ratings
        self.decay_long = 0.5 ** (1 / r.half_life_long)
        self.decay_short = 0.5 ** (1 / r.half_life_short)
        self.decay_league = 0.5 ** (1 / LEAGUE_HALF_LIFE)
        self.decay_qb = 0.5 ** (1 / r.qb_half_life)
        self.teams: dict[str, TeamState] = defaultdict(TeamState)
        self.qbs: dict[str, QbState] = defaultdict(QbState)
        self.mean: dict[str, Ewma] = defaultdict(Ewma)
        self.elo = EloState(cfg.elo)
        self.season: int | None = None
        self.last_event: pd.Timestamp | None = None
        self.events = 0

    # -- season boundary --------------------------------------------------------------
    def enter_season(self, season: int) -> None:
        if self.season is not None and season <= self.season:
            return
        if self.season is not None:
            r = self.cfg.ratings
            for t in self.teams.values():
                for e in list(t.long.values()) + list(t.short.values()):
                    e.carry(r.season_carry)
                t.season_games = 0
            for q in self.qbs.values():
                for e in (q.epa, q.sack, q.ints, q.cpoe, q.rush):
                    e.carry(r.qb_season_carry)
        self.elo.new_season(season)
        self.season = season

    # -- reading ----------------------------------------------------------------------
    def league_mean(self, key: str) -> float:
        return self.mean[key].raw

    def team_value(self, team: str, side: str, metric: str, short: bool = False) -> float:
        """A team's rating; `short` is its recent form, shrunk toward its own long-run level
        (not the league's - otherwise "recent minus long-run" would mostly measure quality)."""
        key = f"{side}_{metric}"
        long = self.teams[team].long[key].value(self.league_mean(key), self.cfg.ratings.prior_games)
        if not short:
            return long
        return self.teams[team].short[key].value(long, self.cfg.ratings.prior_games)

    def qb_value(self, qb: str | None, what: str) -> float:
        r = self.cfg.ratings
        k = r.qb_prior_dropbacks
        if what == "epa":
            prior = self.league_mean("qb_epa") + r.qb_replacement_shift
        else:
            prior = self.league_mean(f"qb_{what}")
        if qb is None or qb not in self.qbs:
            return prior
        return getattr(self.qbs[qb], what).value(prior, k)

    # -- writing ----------------------------------------------------------------------
    def apply(self, game, team_rows: dict, qb_rows: list) -> None:
        """A finished game: Elo, team ratings (opponent-adjusted) and QB ratings move."""
        self.enter_season(int(game.season))
        margin = float(game.home_score - game.away_score)
        self.elo.update(game.home, game.away, bool(game.neutral), margin)
        sides = {game.home: (game.away, game.home_score, game.away_score),
                 game.away: (game.home, game.away_score, game.home_score)}
        # opponent adjustments use the ratings from before this game, for both teams
        adjusted: dict[str, dict[str, float]] = {}
        for team, row in team_rows.items():
            opp = sides[team][0]
            vals = {}
            for m in METRICS:
                for side in SIDES:
                    x = row.get(f"{side}_{m}", float("nan"))
                    if m in ADJUSTED and x is not None and math.isfinite(x):
                        other = "def" if side == "off" else "off"
                        opp_rating = self.team_value(opp, other, m)
                        mu = self.league_mean(f"{other}_{m}")
                        if math.isfinite(opp_rating) and math.isfinite(mu):
                            x = x - (opp_rating - mu)
                    vals[f"{side}_{m}"] = x
            adjusted[team] = vals
        for team, (opp, pf, pa) in sides.items():
            vals = adjusted.get(team, {})
            vals["off_points"] = float(pf)
            vals["def_points"] = float(pa)
            t = self.teams[team]
            for key, x in vals.items():
                t.long[key].add(x, self.decay_long)
                t.short[key].add(x, self.decay_short)
            t.games += 1
            t.season_games += 1
        for team, row in team_rows.items():
            for m in METRICS:
                for side in SIDES:
                    self.mean[f"{side}_{m}"].add(row.get(f"{side}_{m}", float("nan")), self.decay_league)
        for pts in (game.home_score, game.away_score):
            self.mean["off_points"].add(float(pts), self.decay_league)
            self.mean["def_points"].add(float(pts), self.decay_league)
        # quarterbacks
        for q in qb_rows:
            st = self.qbs[q["qb_id"]]
            st.name = q.get("name") or st.name
            db = float(q["dropbacks"])
            if db <= 0:
                continue
            d = self.decay_qb ** db
            st.epa.add(q["epa_sum"] / db, d, db)
            st.sack.add(q["sacks"] / db, d, db)
            st.ints.add(q["ints"] / db, d, db)
            if q["cpoe_n"] > 0:
                st.cpoe.add(q["cpoe_sum"] / q["cpoe_n"], d, q["cpoe_n"])
            if q["starter"]:
                st.rush.add(q["rush_epa_sum"], QB_RUSH_DECAY, 1.0)
            st.dropbacks += db
            self.mean["qb_epa"].add(q["epa_sum"] / db, self.decay_league ** (db / 30), db)
            self.mean["qb_sack"].add(q["sacks"] / db, self.decay_league ** (db / 30), db)
            self.mean["qb_ints"].add(q["ints"] / db, self.decay_league ** (db / 30), db)
            if q["cpoe_n"] > 0:
                self.mean["qb_cpoe"].add(q["cpoe_sum"] / q["cpoe_n"], self.decay_league ** (db / 30), q["cpoe_n"])
            if q["starter"]:
                self.mean["qb_rush"].add(q["rush_epa_sum"], self.decay_league)
                t = self.teams[q["team"]]
                t.last_starter, t.last_starter_name = q["qb_id"], q.get("name")
                t.starters.append(q["qb_id"])
        self.events += 1


# ---- the walk -----------------------------------------------------------------------------
def deadlines(games: pd.DataFrame, cfg: Config) -> pd.Series:
    """Each game's forecast deadline: before the earliest kickoff of its (season, week)."""
    first = games.groupby(["season", "week"])["kickoff_utc"].transform("min")
    return first - pd.Timedelta(minutes=cfg.deadline_minutes_before_first_kickoff)


def _home_bases(games: pd.DataFrame) -> dict[tuple[int, str], str]:
    """(season, team) -> the stadium it plays most non-neutral home games in that season."""
    home = games[games["neutral"] == 0]
    counts = home.groupby(["season", "home", "stadium_id"]).size().reset_index(name="n")
    counts = counts.sort_values(["season", "home", "n", "stadium_id"], ascending=[True, True, False, True])
    best = counts.drop_duplicates(["season", "home"])
    return {(int(r.season), r.home): r.stadium_id for r in best.itertuples()}


ROOF = {"dome": 1.0, "closed": 0.5, "open": 0.5, "outdoors": 0.0}
GRASS = {"grass", "grass ", "dessograss"}


def build(games: pd.DataFrame, team_games: pd.DataFrame, qb_games: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """One feature row per game in `games`, each as of its own week's deadline.

    `games` must come from data.load_games. Outcome columns are read only to
    apply finished games, and never copied into the result.
    """
    games = games.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)
    games = games.assign(deadline_utc=deadlines(games, cfg))
    finish = games["kickoff_utc"] + pd.Timedelta(hours=cfg.game_duration_hours)
    played = games[games["completed"]].assign(finish_utc=finish[games["completed"]])
    played = played.sort_values(["finish_utc", "game_id"])
    use_pbp = cfg.use_epa and not team_games.empty
    team_by_game: dict[str, dict] = defaultdict(dict)
    if use_pbp:
        cols = [f"{s}_{m}" for m in METRICS for s in SIDES]
        for r in team_games[["game_id", "team"] + cols].itertuples(index=False):
            team_by_game[r.game_id][r.team] = dict(zip(cols, r[2:]))
    qb_by_game: dict[str, list] = defaultdict(list)
    if not qb_games.empty:
        for r in qb_games.to_dict("records"):
            qb_by_game[r["game_id"]].append(r)
    bases = _home_bases(games)
    league = League(cfg)
    pending = deque(played.itertuples(index=False))
    rows = []
    schedule_last: dict[str, pd.Timestamp] = {}
    for (deadline, season, week), block in games.groupby(["deadline_utc", "season", "week"], sort=True):
        while pending and pending[0].finish_utc <= deadline:
            g = pending.popleft()
            league.apply(g, team_by_game.get(g.game_id, {}), qb_by_game.get(g.game_id, []))
            league.last_event = g.finish_utc
        league.enter_season(int(season))
        for g in block.itertuples(index=False):
            rows.append(_describe(g, league, bases, schedule_last, use_pbp))
        for g in block.itertuples(index=False):
            schedule_last[g.home] = g.kickoff_utc
            schedule_last[g.away] = g.kickoff_utc
    out = pd.DataFrame(rows)
    return out.sort_values(["kickoff_utc", "game_id"]).reset_index(drop=True)


def _team_block(league: League, team: str, prefix: str, use_pbp: bool) -> dict:
    out = {}
    metrics = METRICS if use_pbp else ()
    for side in SIDES:
        for m in metrics:
            out[f"{prefix}_{side}_{m}"] = league.team_value(team, side, m)
        out[f"{prefix}_{side}_points"] = league.team_value(team, side, "points")
    if use_pbp:
        for side in SIDES:
            out[f"{prefix}_{side}_form"] = (league.team_value(team, side, "epa", short=True)
                                            - league.team_value(team, side, "epa"))
    t = league.teams[team]
    out[f"{prefix}_games_rated"] = t.games
    out[f"{prefix}_season_games"] = t.season_games
    qb = t.last_starter
    out[f"{prefix}_qb_id"] = qb
    out[f"{prefix}_qb_name"] = league.qbs[qb].name if qb in league.qbs else t.last_starter_name
    for what in ("epa", "sack", "ints", "cpoe", "rush"):
        out[f"{prefix}_qb_{what}"] = league.qb_value(qb, what)
    out[f"{prefix}_qb_exp"] = math.log1p(league.qbs[qb].dropbacks) if qb in league.qbs else 0.0
    out[f"{prefix}_qb_recent_starts"] = sum(1 for s in t.starters if s == qb) if qb else 0
    return out


def _describe(g, league: League, bases: dict, schedule_last: dict, use_pbp: bool) -> dict:
    season = int(g.season)
    row = {
        "game_id": g.game_id, "season": season, "week": int(g.week), "game_type": g.game_type,
        "playoff": int(g.playoff), "kickoff_utc": g.kickoff_utc, "deadline_utc": g.deadline_utc,
        "data_cutoff_utc": league.last_event, "home": g.home, "away": g.away, "neutral": int(g.neutral),
        "div_game": float(g.div_game) if pd.notna(g.div_game) else np.nan,
    }
    rh, ra, hfa, p = league.elo.pregame(g.home, g.away, bool(g.neutral))
    row.update(elo_home=rh, elo_away=ra, elo_hfa=hfa, elo_prob=p, elo_diff=rh - ra)
    row.update(_team_block(league, g.home, "h", use_pbp))
    row.update(_team_block(league, g.away, "a", use_pbp))
    # rest (scheduled games are known in advance), capped: a bye or an offseason reads as long rest
    for prefix, team in (("h", g.home), ("a", g.away)):
        last = schedule_last.get(team)
        days = (g.kickoff_utc - last).total_seconds() / 86400 if last is not None else np.nan
        days = min(days, 21.0) if np.isfinite(days) else 21.0
        row[f"{prefix}_rest"] = days
        row[f"{prefix}_short_week"] = float(days < 6)
        row[f"{prefix}_off_bye"] = float(13 <= days < 21)
        base = bases.get((season, team))
        row[f"{prefix}_travel_km"] = distance_km(base, g.stadium_id)
        tz_venue = utc_offset_hours(g.stadium_id, g.kickoff_utc)
        tz_base = utc_offset_hours(base, g.kickoff_utc)
        row[f"{prefix}_tz_shift"] = tz_venue - tz_base
    row["roof_indoor"] = ROOF.get(str(g.roof).strip().lower(), np.nan)
    surf = str(g.surface).strip().lower() if pd.notna(g.surface) else ""
    row["turf"] = np.nan if not surf else float(surf not in GRASS)
    return row


# ---- model inputs -------------------------------------------------------------------------
def add_differences(f: pd.DataFrame, use_pbp: bool = True) -> pd.DataFrame:
    """Home-minus-away differences and offence-versus-defence matchups."""
    f = f.copy()
    metrics = list(METRICS) + ["points"] if use_pbp else ["points"]
    for m in metrics:
        # net unit strength: offence produced minus defence allowed (opponent-adjusted where possible)
        sign = -1.0 if m in ("sack", "pressure", "turnover") else 1.0   # for these, high offence numbers are bad
        f[f"d_off_{m}"] = f[f"h_off_{m}"] - f[f"a_off_{m}"]
        f[f"d_def_{m}"] = f[f"h_def_{m}"] - f[f"a_def_{m}"]
        f[f"d_net_{m}"] = sign * (f[f"d_off_{m}"] - f[f"d_def_{m}"])
    if use_pbp:
        for m in ("epa", "pass_epa", "rush_epa", "success"):
            # home offence against away defence, minus away offence against home defence
            f[f"mu_{m}"] = (f[f"h_off_{m}"] + f[f"a_def_{m}"]) - (f[f"a_off_{m}"] + f[f"h_def_{m}"])
        f["mu_pass_rush"] = (f["h_off_pass_epa"] - f["h_off_rush_epa"]) * (f["a_def_pass_epa"] - f["a_def_rush_epa"]) \
            - (f["a_off_pass_epa"] - f["a_off_rush_epa"]) * (f["h_def_pass_epa"] - f["h_def_rush_epa"])
        # how exposed each passer is: his line's pressure allowed plus the other side's pass rush
        f["mu_protection"] = (f["a_off_pressure"] + f["h_def_pressure"]) - (f["h_off_pressure"] + f["a_def_pressure"])
        f["d_form"] = (f["h_off_form"] - f["h_def_form"]) - (f["a_off_form"] - f["a_def_form"])
    for what in ("epa", "sack", "ints", "cpoe", "rush", "exp", "recent_starts"):
        f[f"d_qb_{what}"] = f[f"h_qb_{what}"] - f[f"a_qb_{what}"]
    f["d_rest"] = f["h_rest"] - f["a_rest"]
    f["d_short_week"] = f["h_short_week"] - f["a_short_week"]
    f["d_off_bye"] = f["h_off_bye"] - f["a_off_bye"]
    f["d_travel"] = (f["a_travel_km"] - f["h_travel_km"]) / 1000.0
    f["d_tz"] = f["a_tz_shift"].abs() - f["h_tz_shift"].abs()
    f["home_field"] = 1 - f["neutral"]
    return f


#: The logistic model's inputs: few, interpretable, chosen before any backtest.
LR_FEATURES = (
    "elo_diff", "home_field", "d_net_epa", "d_net_success", "d_net_points", "d_qb_epa",
    "mu_pass_epa", "mu_rush_epa", "d_net_turnover", "d_form", "d_rest", "d_off_bye",
    "d_short_week", "d_travel", "d_tz",
)
LR_FEATURES_NO_EPA = ("elo_diff", "home_field", "d_net_points", "d_rest", "d_off_bye", "d_short_week",
                      "d_travel", "d_tz")


def gbm_features(f: pd.DataFrame, use_pbp: bool = True) -> list[str]:
    """The gradient-boosting model's inputs: every difference and matchup, plus context."""
    cols = [c for c in f.columns if c.startswith(("d_", "mu_"))]
    cols += ["elo_diff", "elo_prob", "home_field", "div_game", "playoff", "week", "roof_indoor", "turf",
             "h_season_games", "a_season_games", "h_qb_exp", "a_qb_exp", "h_tz_shift", "a_tz_shift"]
    if use_pbp:
        cols += ["h_off_epa", "h_def_epa", "a_off_epa", "a_def_epa"]
    return sorted(dict.fromkeys(cols))
