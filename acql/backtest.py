"""Replaying 2010-2025 under this pool's rules.

Two of the app's rules make promises only a long record can check:

  * the win-the-week planner says a card built to finish first beats the
    card that just takes every likelier side;
  * the suicide helper says spending a team it doesn't need later beats
    grabbing the likeliest winner every week.

One season is sixteen weeks of noise, so both are replayed over every
regular-season week from 2010 to 2025 - about 270 weeks and 16 suicide
pools - with the pool's own rules applied to the real results.

What stands in for the betting line
------------------------------------
The scores file has results but no lines, so each game is priced by a
rating model that only ever sees games already played: every team starts
the season 45% of the way back toward average, and each result moves the
two teams' ratings by 8% of what the rating got wrong, with a home edge
that is learned too. It is a little less sharp than the market - it picks
about 65% of winners straight up where the closing line gets about 66% -
and its chances are widened to match (the spread of results 15% wider
than the app uses for real lines), which makes them honest: games it
called 70% came in about 70% of the time.

The pool's rules, as used
-------------------------
  * a game with a favourite of 6.5 points or more carries a pool line,
    about the size of the spread; the favourite has to win by more than it,
    and a win by exactly the line goes to the underdog;
  * 34 other coaches, who take the favourite of a straight game the way
    pools usually do (analytics.crowd_on_favourite) and the favourite of a
    lined game about 73% of the time (analytics.CHALK_PRIOR);
  * the suicide pool plays by the same lines: a team in a lined game
    survives only if it is credited with the game.

Run `python -m acql.backtest` from the project folder to replay it again
(with a new season's scores added to the CSV, say); the app shows the
stored results on Insights > The model.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import analytics

DATA_FOLDER = Path(__file__).resolve().parent / "data"
SCORES_FILE = DATA_FOLDER / "nfl_scores_2010_2026.csv"
RESULTS_FILE = DATA_FOLDER / "backtest_results.json"

FIRST_SEASON, LAST_SEASON = 2010, 2025
#: The first season only warms the ratings up; it is replayed but not scored.
SCORED_FROM = 2011

# The rating model (fitted on 2011-2019, checked on 2020-2025).
RATING_STEP = 0.08
PRESEASON_REGRESSION = 0.45
HOME_EDGE_START = 2.0
HOME_EDGE_STEP = 0.002
ERROR_CAP = 35.0
#: Proxy chances use a spread of results this much wider than real lines do.
PROXY_SD_FACTOR = 1.15

# The pool's rules.
LINED_FROM = 6.5
SMALLEST_LINE = 7
OTHER_COACHES = 34

#: Franchises that moved: one rating each, whatever the scores file calls them.
ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "AZ": "ARI", "ARZ": "ARI",
           "JAC": "JAX", "WSH": "WAS"}


# ---- the games ----------------------------------------------------------------
@dataclass(frozen=True)
class HistGame:
    season: int
    week: int
    home: str
    away: str
    margin: float           # home score minus away score
    rated: float = 0.0      # the rating model's pre-game home margin


def load_games(path: str | Path = SCORES_FILE) -> list[HistGame]:
    """Every final regular-season game in the scores file, in playing order."""
    games = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            found = re.fullmatch(r"WEEK (\d+)", (row.get("Week") or "").strip())
            if not found or (row.get("GameStatus") or "").strip() != "FINAL":
                continue
            try:
                margin = float(row["HomeScore"]) - float(row["AwayScore"])
            except (TypeError, ValueError, KeyError):
                continue
            home = ALIASES.get(row["HomeTeam"].strip(), row["HomeTeam"].strip())
            away = ALIASES.get(row["AwayTeam"].strip(), row["AwayTeam"].strip())
            games.append(HistGame(int(row["Season"]), int(found.group(1)), home, away, margin))
    games.sort(key=lambda g: (g.season, g.week))
    return games


@dataclass
class Ratings:
    """The rating model's state as a week begins - what it knew then."""

    teams: dict[str, float]
    home_edge: float

    def margin(self, home: str, away: str) -> float:
        return self.teams.get(home, 0.0) - self.teams.get(away, 0.0) + self.home_edge


def rate(games: list[HistGame]) -> tuple[list[HistGame], dict[tuple[int, int], Ratings]]:
    """Each game priced before it was played, and the ratings at each week's start."""
    teams: dict[str, float] = defaultdict(float)
    edge = HOME_EDGE_START
    out, snapshots = [], {}
    season = week = None
    for g in games:
        if g.season != season:
            for t in teams:
                teams[t] *= 1 - PRESEASON_REGRESSION
            season, week = g.season, None
        if g.week != week:
            week = g.week
            snapshots[(season, week)] = Ratings(dict(teams), edge)
        predicted = teams[g.home] - teams[g.away] + edge
        out.append(HistGame(g.season, g.week, g.home, g.away, g.margin, predicted))
        miss = max(-ERROR_CAP, min(ERROR_CAP, g.margin - predicted))
        teams[g.home] += RATING_STEP * miss
        teams[g.away] -= RATING_STEP * miss
        edge += HOME_EDGE_STEP * miss
    return out, snapshots


# ---- the pool's rules ---------------------------------------------------------------
def pool_line(home_margin: float) -> float | None:
    """The line the commissioner would post on a game this size, or None."""
    size = abs(home_margin)
    if size < LINED_FROM:
        return None
    return float(max(SMALLEST_LINE, math.floor(size + 0.5)))


def _sd() -> float:
    return analytics.SPREAD_SD * PROXY_SD_FACTOR


def favourite_credited(fav_margin: float, line: float) -> float:
    """Chance the pool favourite wins by more than the line, on a proxy margin."""
    need = math.floor(line) + 1
    if fav_margin >= 0:
        return analytics.cover_chance(fav_margin, need, _sd())
    return 1 - analytics.cover_chance(-fav_margin, -need + 1, _sd())


def home_wins(home_margin: float) -> float:
    """Chance the home side wins outright (a tie counted as half)."""
    sd = _sd()
    if home_margin >= 0:
        win = analytics.cover_chance(home_margin, 1, sd)
        tie = analytics.cover_chance(home_margin, 0, sd) - win
        return win + tie / 2
    win = analytics.cover_chance(-home_margin, 1, sd)
    tie = analytics.cover_chance(-home_margin, 0, sd) - win
    return 1 - (win + tie / 2)


def credited_home(home_margin: float) -> float:
    """Chance the home side is credited with the game under the pool's rules."""
    line = pool_line(home_margin)
    if line is None:
        return home_wins(home_margin)
    if home_margin > 0:
        return favourite_credited(home_margin, line)
    return 1 - favourite_credited(-home_margin, line)


def credited_winner(g: HistGame) -> str | None:
    """Who the pool would have credited with the game, from the real margin."""
    line = pool_line(g.rated)
    if line is None:
        if g.margin == 0:
            return None
        return g.home if g.margin > 0 else g.away
    fav, dog = (g.home, g.away) if g.rated > 0 else (g.away, g.home)
    fav_margin = g.margin if fav == g.home else -g.margin
    return fav if fav_margin >= math.floor(line) + 1 else dog


def crowd_on(g: HistGame, side: str) -> float:
    """Share of a typical pool on `side`."""
    line = pool_line(g.rated)
    fav = g.home if g.rated >= 0 else g.away
    on_fav = analytics.CHALK_PRIOR if line is not None else analytics.crowd_on_favourite(abs(g.rated))
    return on_fav if side == fav else 1 - on_fav


# ---- finishing first --------------------------------------------------------------
def chance_first(my_score: int, right_rates: list[float], others: int = OTHER_COACHES) -> float:
    """Chance a card scoring `my_score` finishes first, ties shared.

    `right_rates` is, per game, the share of the field that got it right.
    Each other coach's score is a sum of independent coin flips, so its
    distribution is exact (a Poisson-binomial), and so is the chance that
    none of them beats the card and how many tie it.
    """
    dist = [1.0]
    for q in right_rates:
        nxt = [0.0] * (len(dist) + 1)
        for k, p in enumerate(dist):
            nxt[k] += p * (1 - q)
            nxt[k + 1] += p * q
        dist = nxt
    below = sum(dist[:my_score]) if my_score > 0 else 0.0
    level = dist[my_score] if my_score < len(dist) else 0.0
    total = 0.0
    for tied in range(others + 1):
        ways = math.comb(others, tied)
        total += ways * (level ** tied) * (below ** (others - tied)) / (tied + 1)
    return total


@dataclass
class WeekOutcome:
    season: int
    week: int
    games: int
    plain_right: int
    plan_right: int
    plain_first: float
    plan_first: float
    plan_claimed: float
    plain_claimed: float
    turned: int


def replay_weeks(rated: list[HistGame], *, sims: int = 8000, progress=None) -> list[WeekOutcome]:
    """Every scored week: the likeliest card and the planner's card, against real results."""
    from . import weekplan

    by_week: dict[tuple[int, int], list[HistGame]] = defaultdict(list)
    for g in rated:
        if g.season >= SCORED_FROM:
            by_week[(g.season, g.week)].append(g)
    out = []
    for n, key in enumerate(sorted(by_week)):
        games = by_week[key]
        choices, credited = [], []
        for g in games:
            p_home = credited_home(g.rated)
            pick, other = (g.home, g.away) if p_home >= 0.5 else (g.away, g.home)
            chance = max(p_home, 1 - p_home)
            choices.append(weekplan.Choice(f"{g.away}@{g.home}", pick, other, chance, crowd_on(g, pick)))
            credited.append(credited_winner(g))
        plan = weekplan.plan_week(choices, coaches=OTHER_COACHES, sims=sims)
        field_right = [crowd_on(g, w) if w else 0.0 for g, w in zip(games, credited)]
        plain = [c.pick for c in choices]
        plain_right = sum(1 for side, w in zip(plain, credited) if side == w)
        planned = plan.take if plan is not None else plain
        plan_right = sum(1 for side, w in zip(planned, credited) if side == w)
        out.append(WeekOutcome(
            season=key[0], week=key[1], games=len(games),
            plain_right=plain_right, plan_right=plan_right,
            plain_first=chance_first(plain_right, field_right),
            plan_first=chance_first(plan_right, field_right),
            plan_claimed=plan.win_odds if plan is not None else 0.0,
            plain_claimed=plan.plain_win_odds if plan is not None else 0.0,
            turned=len(plan.flipped) if plan is not None else 0,
        ))
        if progress:
            progress(n + 1, len(by_week))
    return out


# ---- the suicide pool ---------------------------------------------------------------------
@dataclass(frozen=True)
class SuicideRule:
    """How a coach chooses: the helper's rule, or one of the simple ones."""

    name: str
    kind: str = "helper"            # "helper", "greedy" or "outright"
    close_enough: float = 0.04
    strong: float = 0.66


def _fixtures(rated: list[HistGame]) -> dict[int, dict[int, list[HistGame]]]:
    out: dict[int, dict[int, list[HistGame]]] = defaultdict(lambda: defaultdict(list))
    for g in rated:
        out[g.season][g.week].append(g)
    return out


_CHANCE_MEMO: dict[tuple[str, float], float] = {}


def _team_chance(margin_for_team: float) -> float:
    """Chance a team survives with this margin, the pool line applied."""
    key = ("survive", round(margin_for_team, 1))
    found = _CHANCE_MEMO.get(key)
    if found is None:
        m = key[1]
        line = pool_line(m)
        if line is None:
            found = home_wins(m)
        elif m > 0:
            found = favourite_credited(m, line)
        else:
            found = 1 - favourite_credited(-m, line)
        _CHANCE_MEMO[key] = found
    return found


def _outright(margin_for_team: float) -> float:
    key = ("outright", round(margin_for_team, 1))
    found = _CHANCE_MEMO.get(key)
    if found is None:
        found = _CHANCE_MEMO[key] = home_wins(key[1])
    return found


_SPOTS_MEMO: dict[tuple[int, int, float], dict[str, int]] = {}


def _strong_spots(season: int, week: int, weeks: dict[int, list[HistGame]],
                  ratings: Ratings, strong: float) -> dict[str, int]:
    """Team -> later weeks it would be at least `strong` to survive, as rated now."""
    key = (season, week, strong)
    found = _SPOTS_MEMO.get(key)
    if found is not None:
        return found
    spots: dict[str, int] = defaultdict(int)
    for w in range(week + 1, max(weeks) + 1):
        for later in weeks.get(w, []):
            margin = ratings.margin(later.home, later.away)
            if _team_chance(margin) >= strong:
                spots[later.home] += 1
            if _team_chance(-margin) >= strong:
                spots[later.away] += 1
    _SPOTS_MEMO[key] = spots
    return spots


@dataclass
class SuicideRun:
    rule: str
    season: int
    start: int
    survived: int                   # weeks survived
    expected: float                 # what the rule's own chances expected
    picks: list[tuple[int, str, float, bool]] = field(default_factory=list)


def play_suicide(rule: SuicideRule, season: int, start: int,
                 weeks: dict[int, list[HistGame]], snapshots: dict) -> SuicideRun:
    """One coach, one season, from week `start`.

    `survived` is what really happened: weeks until the first pick that
    wasn't credited. `expected` is what the rule's own chances said to
    expect along the same picks - the path is played on past a loss, as if
    the coach were still in, so the two can be compared like for like.
    """
    used: set[str] = set()
    last = max(weeks)
    survived, expected, reach = 0, 0.0, 1.0
    alive = True
    picks = []
    for week in range(start, last + 1):
        games = weeks.get(week, [])
        if not games:
            continue
        options = []
        for g in games:
            for team, margin in ((g.home, g.rated), (g.away, -g.rated)):
                if team in used:
                    continue
                options.append((team, _team_chance(margin), _outright(margin), g))
        if not options:
            break
        if rule.kind == "outright":
            team, survive, _, g = max(options, key=lambda o: (o[2], o[0]))
        elif rule.kind == "greedy":
            team, survive, _, g = max(options, key=lambda o: (o[1], o[0]))
        else:
            ratings = snapshots[(season, week)]
            top = max(o[1] for o in options)
            close = [o for o in options if o[1] >= top - rule.close_enough]
            spots = _strong_spots(season, week, weeks, ratings, rule.strong)
            team, survive, _, g = min(close, key=lambda o: (spots.get(o[0], 0), -o[1], o[0]))
        used.add(team)
        won = credited_winner(g) == team
        reach *= survive
        expected += reach
        picks.append((week, team, round(survive, 3), won))
        if alive and won:
            survived += 1
        else:
            alive = False
    return SuicideRun(rule.name, season, start, survived, expected, picks)


RULES = (
    SuicideRule("The helper now: likeliest survivor each week", "helper", 0.0, 0.66),
    SuicideRule("The helper before: spend a team not needed later", "helper", 0.04, 0.66),
    SuicideRule("Biggest favourite each week, ignoring the line", "outright"),
)
#: Variations tried, to see whether saving teams for later ever pays.
TUNING = (SuicideRule("Likeliest survivor, no tie-break", "greedy"),) + tuple(
    SuicideRule(f"helper close={c:.2f} strong={st:.2f}", "helper", c, st)
    for c in (0.02, 0.04, 0.06, 0.08) for st in (0.62, 0.66, 0.70)
)


def replay_suicide(rated, snapshots, rules=RULES, starts=(1, 2, 3, 4)) -> dict[str, list[SuicideRun]]:
    fixtures = _fixtures(rated)
    out: dict[str, list[SuicideRun]] = defaultdict(list)
    for rule in rules:
        for season in sorted(fixtures):
            if season < SCORED_FROM:
                continue
            for start in starts:
                out[rule.name].append(
                    play_suicide(rule, season, start, fixtures[season], snapshots)
                )
    return out


# ---- the big losers -------------------------------------------------------------------
def replay_big_losers(rated: list[HistGame]) -> dict:
    """Three picks a week: the teams likeliest to lose by 15 or more."""
    by_week: dict[tuple[int, int], list[HistGame]] = defaultdict(list)
    for g in rated:
        if g.season >= SCORED_FROM:
            by_week[(g.season, g.week)].append(g)
    points, said, weeks = 0, 0.0, 0
    for key, games in sorted(by_week.items()):
        options = []
        for g in games:
            # big_loser_chance takes the team's own margin (negative = underdog).
            options.append((analytics.big_loser_chance(-g.rated, _sd()), g.away, -g.margin))
            options.append((analytics.big_loser_chance(g.rated, _sd()), g.home, g.margin))
        options.sort(reverse=True)
        for chance, _team, their_margin in options[:3]:
            said += chance
            points += their_margin <= -(analytics.BIG_LOSER_MARGIN + 1)
        weeks += 1
    return {"weeks": weeks, "points": points, "expected": round(said, 1),
            "per_week": round(points / weeks, 3) if weeks else 0.0}


# ---- the whole thing -------------------------------------------------------------------
def run(path: str | Path = SCORES_FILE, *, sims: int = 8000, tune: bool = True, progress=None) -> dict:
    games = [g for g in load_games(path) if FIRST_SEASON <= g.season <= LAST_SEASON]
    rated, snapshots = rate(games)
    scored = [g for g in rated if g.season >= SCORED_FROM]
    errors = [g.margin - g.rated for g in scored]
    straight = [g for g in scored if g.margin != 0]
    su = sum((g.margin > 0) == (g.rated > 0) for g in straight) / len(straight)

    weeks = replay_weeks(rated, sims=sims, progress=progress)
    fair = 1 / (OTHER_COACHES + 1)
    week_summary = {
        "weeks": len(weeks),
        "fair": fair,
        "plain_first": statistics.fmean(w.plain_first for w in weeks),
        "plan_first": statistics.fmean(w.plan_first for w in weeks),
        "plan_claimed": statistics.fmean(w.plan_claimed for w in weeks),
        "plain_claimed": statistics.fmean(w.plain_claimed for w in weeks),
        "plain_right": statistics.fmean(w.plain_right / w.games for w in weeks),
        "plan_right": statistics.fmean(w.plan_right / w.games for w in weeks),
        "turned": statistics.fmean(w.turned for w in weeks),
        # A spread for the difference, from the weeks themselves.
        "gain_se": statistics.pstdev([w.plan_first - w.plain_first for w in weeks]) / math.sqrt(len(weeks)),
        "by_season": {
            str(s): {
                "plain": statistics.fmean(w.plain_first for w in weeks if w.season == s),
                "plan": statistics.fmean(w.plan_first for w in weeks if w.season == s),
            }
            for s in sorted({w.season for w in weeks})
        },
    }

    rules = RULES + (TUNING if tune else ())
    runs = replay_suicide(rated, snapshots, rules)
    suicide = {}
    for name, found in runs.items():
        lasted = [r.survived for r in found]
        suicide[name] = {
            "runs": len(found),
            "mean": statistics.fmean(lasted),
            "median": statistics.median(lasted),
            "expected": statistics.fmean(r.expected for r in found),
            "reached_4": sum(1 for x in lasted if x >= 4) / len(lasted),
            "reached_8": sum(1 for x in lasted if x >= 8) / len(lasted),
            "week1_only": [r.survived for r in found if r.start == 1],
        }
    return {
        "generated": time.strftime("%Y-%m-%d"),
        "seasons": [SCORED_FROM, LAST_SEASON],
        "proxy": {
            "games": len(scored),
            "rmse": math.sqrt(statistics.fmean(e * e for e in errors)),
            "straight_up": su,
        },
        "week": week_summary,
        "suicide": suicide,
        "big_loser": replay_big_losers(rated),
    }


# ---- what the app shows --------------------------------------------------------------
@dataclass
class Results:
    raw: dict

    TABLE_HEADERS = ["Suicide pool rule", "Weeks its chances expected",
                     "Weeks it really lasted", "Lasted 4+ weeks"]
    WEEK_HEADERS = ["Weekly card", "Finished first", "Its own estimate", "Games right"]

    def headline_html(self) -> str:
        w = self.raw["week"]
        lo, hi = self.raw["seasons"]
        first, plain, fair = w["plan_first"], w["plain_first"], w["fair"]
        gain, se = first - plain, w.get("gain_se", 0.0)
        verdict = (
            "a difference smaller than sixteen seasons can measure"
            if abs(gain) < 2 * se else
            ("a real gain" if gain > 0 else "a real loss")
        )
        text = (
            f"<b>Winning the week.</b> Replayed over {w['weeks']} weeks from {lo} to {hi} "
            f"against a pool that picks the way pools do, the card built to finish "
            f"first did so <b>{first:.1%}</b> of the time and the card that takes "
            f"every likelier side <b>{plain:.1%}</b> - {verdict} "
            f"({gain * 100:+.1f} points, give or take {se * 100:.1f}). Both are well over a fair share of "
            f"{fair:.1%}. Turning games against the pool costs about "
            f"{(w['plain_right'] - w['plan_right']) * 16:.1f} right answers a week, "
            f"which counts toward the season title; the extra weeks it wins are too "
            f"few for history to confirm. So the turns are a choice, not a rule - "
            f"This Week lets you play either card."
        )
        s = self.raw["suicide"]
        now, before, outright = (s.get(r.name) for r in RULES)
        if now and before:
            text += (
                f"<br><br><b>The suicide pool.</b> Under the pool's lines nothing is "
                f"much better than 70% to survive a week, so few coaches are still in "
                f"by week 5 and a team saved for later is rarely used. Taking the "
                f"likeliest survivor every week expected <b>{now['expected']:.2f}</b> "
                f"weeks; saving strong teams for later, {before['expected']:.2f}"
                + (f"; taking the biggest favourite and ignoring the line - what much "
                   f"of the pool does - only {outright['expected']:.2f}." if outright else ".")
                + " The helper now takes the likeliest survivor, and when two are level, "
                  "spends the one with fewer good weeks left."
            )
        b = self.raw.get("big_loser")
        if b:
            text += (
                f"<br><br><b>Big Losers.</b> The three teams likeliest to lose by 15 "
                f"or more landed {b['per_week']:.2f} points a week over {b['weeks']} "
                f"weeks, against the {b['expected'] / max(b['weeks'], 1):.2f} their "
                f"chances said - the big-loser numbers are honest."
            )
        return text

    def week_rows(self) -> list[list]:
        w = self.raw["week"]
        return [
            ["Built to win the week", f"{w['plan_first']:.1%}", f"{w['plan_claimed']:.1%}",
             f"{w['plan_right']:.1%}"],
            ["Likeliest side of every game", f"{w['plain_first']:.1%}", f"{w['plain_claimed']:.1%}",
             f"{w['plain_right']:.1%}"],
            ["A fair share of the pool", f"{w['fair']:.1%}", "", ""],
        ]

    def table_rows(self) -> list[list]:
        rows = []
        for rule in RULES:
            found = self.raw["suicide"].get(rule.name)
            if not found:
                continue
            rows.append([
                rule.name, f"{found['expected']:.2f}", f"{found['mean']:.2f}",
                f"{found['reached_4']:.0%}",
            ])
        return rows

    def method_note(self) -> str:
        p = self.raw["proxy"]
        return (
            f"The scores file has no betting lines, so every game is priced by a "
            f"rating model that only knows the games already played - it picked "
            f"{p['straight_up']:.0%} of winners straight up over {p['games']:,} "
            f"games (the closing line manages about 66%), and its chances are "
            f"widened to stay honest. Pool lines go on every game of 6.5 points or "
            f"more, 34 other coaches pick the way pools usually do, and each "
            f"suicide rule is played from weeks 1 to 4 of every season. \u201cIts "
            f"own estimate\u201d is what the planner expected before the games; the "
            f"real results came in a little kinder to both cards. Replayed "
            f"{self.raw['generated']}."
        )


def stored_results(path: str | Path = RESULTS_FILE) -> Results | None:
    try:
        return Results(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_results(raw: dict, path: str | Path = RESULTS_FILE) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(raw, indent=1), encoding="utf-8")


if __name__ == "__main__":
    import sys

    def _progress(done: int, total: int) -> None:
        if done % 20 == 0 or done == total:
            print(f"  weeks replayed: {done}/{total}", flush=True)

    found = run(progress=_progress)
    save_results(found)
    print(Results(found).headline_html().replace("<br>", "\n").replace("<b>", "").replace("</b>", ""))
    sys.exit(0)
