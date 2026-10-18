"""The pool page: what everyone in the pool may see, as data for a web page.

The dashboard is for whoever runs it - it holds that coach's card, the
model's picks and a season of working-out. The rest of the pool wants four
things: where they stand, how the week went, the money, and who's still in
the side pools. This gathers exactly those, and nothing about anyone's card
for the week ahead or the model, into one small JSON file.

The file drives the pool page - a web page with a link to share. Whoever
owns the page drops the new file on it each week and the page updates
itself for everyone who has the link. Every number is worked out here by
the same code as the dashboard's own pages, so the two always agree.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path

from .. import analytics
from ..pool import patterns
from ..site import siteextras
from ..models import Season, same_team
from ..model.predictions import DISPLAY, display_team, team_code
from . import recap

SCHEMA = 1
#: What happened to the live week on the last snapshot - said when publishing.
LIVE_NOTE = [""]
FILE_PREFIX = "ACQL pool page"


def _money(value: float) -> float:
    return round(float(value or 0.0), 2)


def finished_weeks(season: Season) -> list[int]:
    """The weeks the page shows: the season's official weeks (none the
    dashboard holds out as in progress), each with every game's result in.
    The page never shows a week half-played."""
    out = []
    for number in season.final_weeks():
        week = season.weeks[number]
        if not week.lines:
            continue
        if not all(game.played for game in week.games):
            break
        out.append(number)
    return out


def left_off(season: Season) -> str:
    """Why a week that has scores is not on the page yet ("" when none is)."""
    shown = finished_weeks(season)
    latest = max(shown, default=0)
    for number in season.played_weeks():
        if number <= latest:
            continue
        week = season.weeks[number]
        to_play = sum(1 for game in week.games if not game.played)
        if to_play:
            return (f"Week {number} isn't on the page yet - it still has "
                    f"{to_play} game{'' if to_play == 1 else 's'} to play.")
        if number in season.provisional_weeks:
            return (f"Week {number} isn't on the page yet - the standings export "
                    f"only goes up to week {season.current_week}.")
    return ""


def _week_scores(season: Season, number: int) -> list[dict]:
    week = season.weeks[number]
    rows = []
    for key, line in week.lines.items():
        player = season.players.get(key)
        rows.append({
            "name": player.display if player else line.player,
            "total": int(line.total_wins or 0),
            "regular": int(line.regular_wins or 0),
            "big_loser": int(line.big_loser_wins or 0),
        })
    rows.sort(key=lambda r: (-r["total"], r["name"].casefold()))
    return rows


def _loser(game) -> str:
    """The side the pool did NOT credit with a played game ("" if unclear)."""
    if not game.played:
        return ""
    if same_team(game.winner, game.home):
        return display_team(game.away)
    if same_team(game.winner, game.away):
        return display_team(game.home)
    return ""


def _market(season: Season, number: int) -> dict[int, tuple[str, float]]:
    """Game index -> (the betting favourite as the pages name it, points),
    for the games of a week the dashboard has a betting line for: a spread
    typed in on Next Week first, else the forecasts file or fetched odds.
    Only ever asked of finished weeks, so it gives nothing away."""
    week = season.weeks[number]
    out: dict[int, tuple[str, float]] = {}
    try:
        from ..feeds import lines as lines_
        for index, spread in lines_.load_spreads(number, week.games).items():
            game = next((g for g in week.games if g.index == index), None)
            if game is not None and spread.points > 0:
                fav = game.home if spread.favourite == "home" else game.away
                out[index] = (display_team(fav), float(spread.points))
    except Exception:  # noqa: BLE001 - the page goes up without the favourites
        pass
    try:
        from ..model import predictions as predictions_
        forecasts, _ = predictions_.load(number)
        priced = {}
        for f in forecasts or []:
            value = f.market if f.market is not None else f.opening
            home, road = team_code(f.home), team_code(f.road)
            if value is not None and home and road:
                priced[frozenset((home, road))] = (home, float(value))
        for game in week.games:
            if game.index in out:
                continue
            hit = priced.get(frozenset((team_code(game.home), team_code(game.away))))
            if not hit or not hit[1]:
                continue
            home_code, margin = hit                  # the home side's expected margin
            home_favoured = (margin > 0) == (team_code(game.home) == home_code)
            out[game.index] = (display_team(game.home if home_favoured else game.away), abs(margin))
    except Exception:  # noqa: BLE001
        pass
    return out


def _week_games(season: Season, number: int) -> list[dict]:
    week = season.weeks[number]
    market = _market(season, number)
    out = []
    for game in sorted(week.games, key=lambda g: g.index):
        line = getattr(game, "line", None)
        fav = getattr(game, "line_favourite", "") or ""
        lined = line is not None and bool(fav)
        bet_fav, spread = market.get(game.index, ("", None))
        out.append({
            "matchup": game.label,
            "home": display_team(game.home),
            "away": display_team(game.away),
            "winner": display_team(game.winner) if game.played else "",
            "loser": _loser(game),
            "line": f"{display_team(fav)} by {line:g}" if lined else "",
            "pool_line": float(line) if lined else None,
            "pool_fav": display_team(fav) if lined else "",
            "fav": bet_fav,
            "spread": spread,
            "right": week.correct_count(game.index) if game.played else None,
        })
    return out


def _sides(season: Season, number: int) -> dict[str, str]:
    """Coach -> one character per game, in slate order: "1" had the side the
    pool credited, "0" had the other side, "-" not played. A graded sheet
    keeps only the right picks, so every played game is one or the other -
    which is all a head-to-head needs, and says nothing about next week."""
    week = season.weeks[number]
    games = sorted(week.games, key=lambda g: g.index)
    out = {}
    for key, line in week.lines.items():
        player = season.players.get(key)
        name = player.display if player else line.player
        out[name] = "".join(
            "-" if not g.played else "1" if same_team(line.correct_picks.get(g.index), g.winner) else "0"
            for g in games
        )
    return out


#: A coach needs this many to get a page-only award: one lucky call is the
#: lone wolf's story, not a pattern.
UPSET_CALLS_MIN = 2
AGAINST_CROWD_MIN = 3
HOT_STREAK_MIN = 3


def _more_awards(season: Season, number: int, sides: dict[str, str],
                 finished: list[int]) -> list[dict]:
    """The page's extra stories for a week, beside the recap's own."""
    out = []
    entrants = len(sides)
    if not entrants:
        return out
    width = max((len(s) for s in sides.values()), default=0)
    right = [sum(1 for s in sides.values() if j < len(s) and s[j] == "1") for j in range(width)]
    played = [j for j in range(width) if any(j < len(s) and s[j] != "-" for s in sides.values())]

    # right on games most of the pool got wrong
    calls = {n: sum(1 for j in played if s[j] == "1" and 2 * right[j] < entrants) for n, s in sides.items()}
    best = max(calls.values(), default=0)
    if best >= UPSET_CALLS_MIN:
        names = sorted((n for n, v in calls.items() if v == best), key=str.casefold)
        out.append({"title": "Best upset calls", "who": recap._list(names),
                    "detail": f"right on {best} games most of the pool got wrong"})

    # on the other side from most of the pool
    against, came_in = {}, {}
    for n, s in sides.items():
        mine = [j for j in played if 2 * right[j] != entrants and (s[j] == "1") != (2 * right[j] > entrants)]
        against[n] = len(mine)
        came_in[n] = sum(1 for j in mine if s[j] == "1")
    most = max(against.values(), default=0)
    if most >= AGAINST_CROWD_MIN:
        names = sorted((n for n, v in against.items() if v == most), key=lambda n: (-came_in[n], n.casefold()))
        top = [n for n in names if came_in[n] == came_in[names[0]]]
        out.append({"title": "Against the grain", "who": recap._list(top),
                    "detail": f"went against the crowd {most} times - {came_in[top[0]]} came in"})

    # weeks in a row above the pool's average, up to this one
    upto = [w for w in sorted(finished) if w <= number]
    averages = {}
    for w in upto:
        totals = [int(l.total_wins or 0) for l in season.weeks[w].lines.values()]
        averages[w] = sum(totals) / len(totals) if totals else 0.0
    streaks = {}
    for key, player in season.players.items():
        run = 0
        for w in reversed(upto):
            line = season.weeks[w].lines.get(key)
            if line is None or not int(line.total_wins or 0) > averages[w]:
                break
            run += 1
        streaks[player.display] = run
    hottest = max(streaks.values(), default=0)
    if hottest >= HOT_STREAK_MIN:
        names = sorted((n for n, v in streaks.items() if v == hottest), key=str.casefold)
        out.append({"title": "Hot hand", "who": recap._list(names),
                    "detail": f"{hottest} weeks in a row above the pool average"})
    return out


def _so_close(season: Season, number: int, sides: dict[str, str]) -> dict:
    """The games that would have changed who won the week, had the pool
    credited the other side. Pick'em points only - Big Loser points are
    left as they were."""
    week = season.weeks[number]
    games = sorted(week.games, key=lambda g: g.index)
    totals = {}
    for key, line in week.lines.items():
        player = season.players.get(key)
        totals[player.display if player else line.player] = int(line.total_wins or 0)
    if not totals:
        return {"margin": 0, "outcomes": []}
    ranked = sorted(totals.values(), reverse=True)
    top = ranked[0]
    winners = {n for n, v in totals.items() if v == top}
    runner_up = next((v for v in ranked if v < top), top)
    # one entry per different outcome, with every game that would have caused it
    found: dict[tuple, dict] = {}
    for j, game in enumerate(games):
        if not game.played or not _loser(game):
            continue
        flipped = {}
        for n, v in totals.items():
            bit = sides.get(n, "")[j:j + 1]
            flipped[n] = v - 1 if bit == "1" else v + 1 if bit == "0" else v
        best = max(flipped.values())
        now = sorted((n for n, v in flipped.items() if v == best), key=str.casefold)
        if not set(now) - winners:
            continue
        entry = found.setdefault((tuple(now), best), {
            "who": now,
            "new": sorted(set(now) - winners, key=str.casefold),
            "score": best,
            "games": [],
        })
        entry["games"].append({"matchup": game.label, "instead": _loser(game),
                               "was": display_team(game.winner)})
    # a new outright winner is the better story; then fewer sharing it
    ordered = sorted(found.values(), key=lambda f: (len(f["who"]) > 1, len(f["who"]), -len(f["games"])))
    return {"margin": top - runner_up if len(winners) == 1 else 0, "outcomes": ordered[:3]}


def _week(season: Season, number: int, *, money_known: bool = True,
          finished: list[int] | None = None) -> dict | None:
    made = recap.build(season, number)
    if made is None:
        return None
    sides = _sides(season, number)
    replay_info, beats = _replay(season, number)
    return {
        "replay": replay_info,
        "beats": beats,
        "week": number,
        "entrants": made.entrants,
        "games": made.games,
        # the most a card could score: every game plus every Big Loser pick the
        # official sheet allows; left out when the sheet does not say
        "most": made.games + int(season.max_big_loser_points)
        if made.games and season.max_big_loser_points else None,
        "average": round(made.average, 2),
        "winners": list(made.winners),
        "top": made.top_score,
        "payout_each": _money(made.payout_each) if money_known else None,
        "pool_average": round(made.pool_average, 2),
        "crowd": {"right": made.crowd_right, "games": made.crowd_games},
        "awards": [{"title": a.title, "who": a.who, "detail": a.detail} for a in made.awards]
        + _more_awards(season, number, sides, finished or [number]),
        "picks": sides,
        "so_close": _so_close(season, number, sides),
        "upsets": [
            {"matchup": u.matchup, "winner": u.winner, "right": u.right,
             "entrants": u.entrants, "line": u.line}
            for u in made.upsets
        ],
        "suicide": {
            "killer": made.killer, "killed": made.killed, "tied": list(made.killer_tied),
            "left": made.suicide_left, "picks": made.suicide_picks,
        },
        "scores": _week_scores(season, number),
        "results": _week_games(season, number),
    }


def _replay(season: Season, number: int) -> tuple[dict | None, list[dict]]:
    """The week replayed after every score, and its bad beats - when every
    game's scoring plays are kept and the replay ends on the pool's scores."""
    from ..site import replay
    try:
        made = replay.build(season, number)
    except Exception:  # noqa: BLE001 - the week goes up without it
        return None, []
    if made is None:
        return None, []
    data = made.data()
    info = {"v": replay.fingerprint(data), "data": data, **replay.summary(made)}
    try:
        stories = replay.beats(made)
    except Exception:  # noqa: BLE001
        stories = []
    return info, stories


def replay_file(number: int) -> str:
    return f"replay-{int(number)}.json"


def _patterns(season: Season, weeks: list[int]) -> tuple[dict, dict]:
    """Blind spots, the line move and each week's chaos rating (patterns.py),
    from the finished weeks only: (player key -> theirs, week -> its rating)."""
    if not weeks:
        return {}, {}
    made = patterns.report(season, weeks)

    def split(s: patterns.Split) -> dict:
        return {"label": s.label, "right": s.right, "picks": s.picks, "field": round(s.field_rate, 3)}

    coaches = {}
    for key, spots in made.spots.items():
        low, high = spots.team_extremes()
        entry = {
            "overall": split(spots.overall),
            "blind": [split(s) for s in spots.worst[:4]],
            "strong": [split(s) for s in spots.best[:4]],
            "weak_teams": [split(s) for s in low],
            "best_teams": [split(s) for s in high],
        }
        move = made.move_for(key)
        if move is not None:
            entry["move"] = {
                "with": move.with_move, "moved": move.moved, "came_in": move.came_in,
                "gained": round(move.gained, 2), "rank": made.moves.index(move) + 1,
                "of": len(made.moves),
            }
        adjusted = made.adjusted_for(key)
        if adjusted is not None:
            entry["adjusted"] = {
                "average": round(adjusted.average, 2), "adjusted": round(adjusted.adjusted, 2),
                "rank": adjusted.rank, "actual": adjusted.actual_rank, "of": len(made.adjusted),
                "wild": None if adjusted.wild is None else round(adjusted.wild, 2),
                "calm": None if adjusted.calm is None else round(adjusted.calm, 2),
            }
        coaches[key] = entry
    chaos = {
        c.week: {
            "rating": c.rating, "label": c.label, "upsets": c.upsets,
            "expected": round(c.expected, 1), "games": c.games, "biggest": c.biggest_text,
        }
        for c in made.chaos
    }
    return coaches, chaos


def _money_table(season: Season, weeks: list[int], *, official: bool = True,
                 ) -> tuple[dict[str, tuple[float, float, float]], str]:
    """(key -> (won, paid, net), where the numbers came from).

    Money is shown to the pool only when the pool's own files say it: the
    standings export's season totals, or the workbook's weekly winnings. A
    figure the dashboard worked out from the scores is left off the page -
    close is not good enough for other people's money.
    """
    people = list(season.players.values())
    # Season totals count only when a standings export gave them: without
    # one, the loader fills the same fields in from the scores.
    exported = official and not getattr(season, "computed_totals", False) and any(
        getattr(src, "kind", "") == "stats" and not getattr(src, "error", "")
        for src in getattr(season, "sources", []) or []
    )
    if exported and any(p.points_won or p.points_paid or p.net_points for p in people):
        out = {}
        for p in people:
            won, paid = _money(p.points_won), abs(_money(p.points_paid))
            net = _money(p.net_points) if p.net_points else _money(won - paid)
            out[p.key] = (won, paid, net)
        return out, "stats"
    worked_out = set(getattr(season, "computed_winnings", []) or [])
    from_files = [
        n for n in weeks
        if n not in worked_out and any(p.weekly_winnings.get(n) for p in people)
    ]
    if not from_files or len(from_files) < len(weeks):
        return {}, ""
    out = {}
    for p in people:
        won = sum(v for n in weeks for v in (p.weekly_winnings.get(n),) if v and v > 0)
        paid = sum(analytics.week_owed(season.weeks[n]).get(p.key, 0.0) for n in weeks)
        out[p.key] = (_money(won), _money(paid), _money(won - paid))
    return out, "workbook"


def _round_start(season: Season, weeks: list[int]) -> int:
    """The week the suicide round on the page began: 0 for the first, which
    is still the one shown until a week of the new round has been played."""
    start = getattr(season, "suicide_restart", 0) or 0
    return start if start and max(weeks, default=0) >= start else 0


def _suicide_status(season: Season, weeks: list[int], *, official: bool = True,
                    ) -> dict[str, tuple[bool, int | None]]:
    """key -> (still alive, week knocked out).

    Worked out week by week from each coach's pick and the result, with the
    pool's lines applied - the same rule as the recap, so the page and the
    recap always agree. The loader's own flags are only used for a coach
    whose picks don't settle it, and never name a week the page doesn't
    show: a DEAD marker on next week's sheet means out THIS week.
    """
    from ..model.predictions import team_code
    latest = max(weeks, default=0)
    # Once the page shows a week of a new round (the pool started again after
    # somebody won it), that round is the one it tells: everyone back in.
    start = _round_start(season, weeks)
    out: dict[str, tuple[bool, int | None]] = {}
    for key, person in season.players.items():
        entered, knocked = bool(start), None
        for number in (w for w in weeks if w >= start):
            line = season.weeks[number].lines.get(key)
            if line is None:
                continue
            text = (line.suicide_pick or "").strip()
            if line.suicide_out or text.casefold() in recap.DEAD_MARKERS:
                if entered and knocked is None:
                    knocked = number - 1
                break
            if not team_code(text):
                continue
            entered = True
            if recap._suicide_lost(season, number, key, text):
                knocked = number
                break
        if not entered and official and person.suicide_out_week:
            # no picks to go on: take the files' word, within the page's weeks
            knocked = min(person.suicide_out_week, latest) or None
            entered = knocked is not None
        out[key] = (entered and knocked is None, knocked)
    return out


def _live(season: Season, latest: int) -> dict | None:
    """The week being played: its games, the pool's lines and everyone's
    picks, so the page can follow the games live. From the commissioner's
    pick sheet, which goes out once picks are in; None until there is one."""
    from ..pool import picks as pick_sheets
    from ..model.predictions import team_code
    ahead = sorted(n for n in season.weeks if n > latest)
    number = ahead[0] if ahead else latest + 1
    week = season.weeks.get(number)
    slate = {frozenset((team_code(g.home), team_code(g.away))) for g in (week.games if week else [])}

    def fits(candidate, imported: float | None = None) -> bool:
        """A sheet from THIS season: most of its games are on this week's slate.
        (The app also keeps other seasons' sheets, and a week number alone
        can't tell last September's week 3 from this one.) With no slate to
        compare - the workbook hasn't got that far - only a sheet that
        arrived lately can be for the week coming up."""
        if candidate is None or not candidate.games:
            return False
        if not slate:
            return _recent_sheet(candidate, imported)
        theirs = {frozenset((team_code(g.home), team_code(g.away))) for g in candidate.games}
        return len(theirs & slate) >= 0.6 * max(1, len(theirs))

    sheet = pick_sheets.load(number)
    if not fits(sheet, pick_sheets.imported_at(number)):
        sheet = None
    problems = []
    if sheet is None:
        # Not stored (or only another season's): read it straight from the folder.
        for path in pick_sheets.find_files(getattr(season, "workbook_path", None)):
            try:
                found = pick_sheets.read_file(path)
            except Exception as exc:  # noqa: BLE001 - say why, try the next
                problems.append(f"{path.name}: {exc}")
                continue
            if found.week == number and fits(found):
                sheet = found
                break
    if sheet is None:
        LIVE_NOTE[0] = (f"no week {number} pick sheet for this season could be read"
                        + (" - " + "; ".join(problems[:2]) if problems else ""))
        return None
    slate = []
    if week is not None and week.games:
        for game in sorted(week.games, key=lambda g: g.index):
            line = getattr(game, "line", None)
            fav = getattr(game, "line_favourite", "") or ""
            slate.append((game.away, game.home, line if line is not None and fav else None, fav))
    else:
        for game in sheet.games:
            slate.append((game.away, game.home, None, ""))
    by_name = {p.display.casefold(): p.display for p in season.players.values()}

    def who(name: str) -> str:
        return by_name.get(" ".join(str(name).split()).casefold(), str(name).strip())

    games, columns = [], []
    for away, home, line, fav in slate:
        games.append({
            "a": display_team(away), "h": display_team(home),
            "ac": team_code(away), "hc": team_code(home),
            "line": line, "fav": team_code(fav) if fav else "",
        })
        columns.append(sheet.game_for(away, home))
    coaches = []
    for coach in sheet.coaches:
        coaches.append({
            "name": who(coach),
            "picks": [team_code(col.picks.get(coach, "")) if col else "" for col in columns],
            "bl": [team_code(t) for t in sheet.losers.get(coach, []) if team_code(t)],
            "sui": team_code(sheet.suicide.get(coach, "")),
        })
    coaches.sort(key=lambda c: c["name"].casefold())
    LIVE_NOTE[0] = f"week {number} live: {len(coaches)} coaches, {len(games)} games"
    return {"week": number, "games": games, "coaches": coaches}


TITLE_SIMS = 10_000


def _race(season: Season, players: list[dict], latest: int) -> dict:
    """Title chances and who can still catch the leader, filled into `players`.

    The rest of the season is played out TITLE_SIMS times with every coach
    scoring like a typical week from the pool - a score drawn at random from
    every week anyone has had. So the chances come from the standings alone,
    the same for everyone the page shows them to; the dashboard's own
    Projections tab also weighs each coach's past weeks, which after a few
    weeks mostly measures luck. "Out of reach" is plain arithmetic: even a
    perfect week every week left would not reach the leader's total.
    """
    from ..config import WEEKS_IN_SEASON
    left = max(0, WEEKS_IN_SEASON - latest)
    lead = max((p["wins"] for p in players), default=0)
    perfect = max([len(w.games) for w in season.weeks.values()] + [int(season.max_regular_points or 0)]) \
        + int(season.max_big_loser_points or 0)
    try:
        odds = _title_odds([p["wins"] for p in players],
                           [v for p in players for v in p["weekly"].values() if v is not None],
                           left, TITLE_SIMS)
    except Exception:  # noqa: BLE001 - the page goes up without the odds
        odds = [None] * len(players)
    for p, chance in zip(players, odds):
        p["title"] = chance
        p["out_of_reach"] = p["wins"] + left * perfect < lead
    return {"weeks_left": left, "season_weeks": WEEKS_IN_SEASON, "perfect_week": perfect}


def _title_odds(wins: list[float], pool: list[float], left: int, sims: int) -> list[float]:
    """Each coach's % chance of the title: the weeks left played out `sims`
    times, every coach scoring a week drawn at random from `pool`."""
    import numpy as np
    wins_ = np.array([float(w) for w in wins])
    pool_ = np.array([float(v) for v in pool])
    if left and pool_.size:
        rng = np.random.default_rng(analytics.SEED)
        finals = np.empty((len(wins_), sims))
        for i in range(len(wins_)):
            finals[i] = wins_[i] + pool_[rng.integers(pool_.size, size=(sims, left))].sum(axis=1)
    else:
        finals = wins_[:, None]
    title, _ = analytics._odds(finals)
    return [round(100 * float(v), 1) for v in title]


#: Past weeks' title odds need less precision than this week's: a line on a chart.
HISTORY_SIMS = 3_000


def _title_by_week(players: list[dict], weeks: list[int]) -> dict:
    """The title odds as they stood after each week shown, from the scores
    known by then - the same reckoning as this week's. The last week is this
    week's own figures, so the chart ends where the standings do."""
    from ..config import WEEKS_IN_SEASON
    out: dict[str, list[float | None]] = {p["name"]: [] for p in players}
    shown = []
    for number in weeks:
        if number == max(weeks):
            odds = [p.get("title") for p in players]
        else:
            done = [{w: v for w, v in p["weekly"].items() if int(w) <= number and v is not None}
                    for p in players]
            try:
                odds = _title_odds([sum(d.values()) for d in done], [v for d in done for v in d.values()],
                                   max(0, WEEKS_IN_SEASON - number), HISTORY_SIMS)
            except Exception:  # noqa: BLE001 - that week is left out
                continue
        shown.append(number)
        for p, chance in zip(players, odds):
            out[p["name"]].append(chance)
    return {"weeks": shown, "odds": out} if shown else {}


def _money_weeks(season: Season, weeks: list[int], money: dict, money_from: str) -> dict[str, list[float]]:
    """Each coach's money after each week, for the chart: week by week by the
    pool's rule (the week's best card collects a dollar a game from everyone
    behind it). Only when the pool's files give money at all - and, with the
    standings export, only when the weeks add up to its totals."""
    if not money_from:
        return {}
    out = {}
    for key, person in season.players.items():
        running, series = 0.0, []
        for number in weeks:
            week = season.weeks[number]
            if key not in week.lines:
                series.append(round(running, 2))
                continue
            owed = analytics.week_owed(week).get(key, 0.0)
            if money_from == "workbook":
                won = person.weekly_winnings.get(number) or 0.0
                won = won if won > 0 else 0.0
            else:
                won = analytics.week_payouts(week).get(key, 0.0)
            running += won - owed
            series.append(round(running, 2))
        out[key] = series
    if money_from == "stats":
        for key, series in out.items():
            official = money.get(key, (None, None, None))[2]
            if official is None or not series or abs(series[-1] - official) > 1.0:
                return {}
    return {season.players[key].display: series for key, series in out.items()}


def _team_ranks(latest: int) -> dict[str, int]:
    """Team code -> 1 (best) .. 32, from this season's betting lines as the
    dashboard stored them; {} when too few games are priced to say."""
    try:
        from ..pool import survivor
        rating = survivor.ratings(survivor._lines_so_far(latest + 1))
    except Exception:  # noqa: BLE001 - the board shows without it
        return {}
    if len(rating) < 28:
        return {}
    order = sorted(rating, key=lambda c: (-rating[c], c))
    return {c: i + 1 for i, c in enumerate(order)}


def _team_power(latest: int) -> dict[str, int]:
    """Team code -> points better than an average team, to the whole point,
    from this season's betting lines (the same ratings as _team_ranks);
    {} when too few games are priced. Whole points so a line moving by a
    hair doesn't put the site up again."""
    try:
        from ..pool import survivor
        rating = survivor.ratings(survivor._lines_so_far(latest + 1))
    except Exception:  # noqa: BLE001 - the power map hides without it
        return {}
    if len(rating) < 28:
        return {}
    return {c: int(round(r)) for c, r in rating.items()}


#: How old a pick sheet can be and still be for the week coming up, when
#: the workbook has no slate for that week to check it against.
RECENT_SHEET_DAYS = 21


def _recent_sheet(sheet, imported: float | None = None, now: float | None = None) -> bool:
    """Whether a pick sheet arrived lately: its file was saved in the last
    three weeks (or, with no file to look at, it was read in then). Last
    season's sheet for the same week is a year old."""
    now = time.time() if now is None else now
    when = None
    source = str(getattr(sheet, "source", "") or "")
    if source:
        try:
            path = Path(source)
            if path.is_file():
                when = path.stat().st_mtime
        except (OSError, ValueError):
            when = None
    if when is None:
        when = imported
    return when is not None and now - when <= RECENT_SHEET_DAYS * 86400


def _from_sheets(season: Season) -> Season:
    """The season as the pick sheets and the files have it: without the
    weeks the dashboard set up itself from the NFL's fixtures, which have
    nobody's picks in them. The page goes on showing what it always has."""
    extra = set(getattr(season, "fixture_weeks", ()) or ())
    if not extra:
        return season
    view = copy.copy(season)
    view.weeks = {n: w for n, w in season.weeks.items() if n not in extra}
    return view


def _alerts_link() -> str:
    """Where coaches subscribe to the pool's phone alerts, when they're on."""
    try:
        from ..site import pushalerts
        return pushalerts.subscribe_link()
    except Exception:  # noqa: BLE001
        return ""


#: Where coaches send their number to get the text alerts.
TEXT_SIGNUP = "Sam522p@gmail.com"


def _texts_on() -> str:
    """Where to sign up for the text alerts, when they're on."""
    try:
        from ..site import pushalerts
        return TEXT_SIGNUP if pushalerts.text_number() else ""
    except Exception:  # noqa: BLE001
        return ""


def snapshot(season: Season, *, generated: str | None = None, strict: bool = False) -> dict:
    """Everything the pool page shows, worked out from the season. `strict`
    (publishing) lets a store that can't be read stop the build rather than
    put the site up without its announcement and past seasons."""
    season = _from_sheets(season)
    weeks = finished_weeks(season)
    latest = max(weeks, default=0)
    # The standings the files give (places, wins, Big Loser points) are as
    # of the season's current week. When the page stops short of it - that
    # week isn't finished - everything is worked out from the weeks shown.
    official = bool(latest) and latest == (season.current_week or latest)
    totals = recap._through(season, latest) if latest else {}
    before = recap._through(season, latest - 1) if latest > 1 else {}
    place_now = recap._places(totals) if totals else {}
    place_before = recap._places(before) if before else {}
    money, money_from = _money_table(season, weeks, official=official)
    suicide = _suicide_status(season, weeks, official=official)
    round_start = _round_start(season, weeks)
    try:
        found, chaos = _patterns(season, weeks)
    except Exception:  # noqa: BLE001 - the page goes up without them
        found, chaos = {}, {}

    players = []
    for key, player in season.players.items():
        if official:
            wins = int(player.wins or totals.get(key, 0))
            place = player.pos or place_now.get(key)
        else:
            wins = int(totals.get(key, 0))
            place = place_now.get(key)
        if official and player.pos is not None and player.prev_pos is not None:
            move = player.prev_pos - player.pos
        elif key in place_now and key in place_before:
            move = place_before[key] - place_now[key]
        else:
            move = None
        weekly = {}
        for n in weeks:
            line = season.weeks[n].lines.get(key)
            if line is not None:
                weekly[str(n)] = int(line.total_wins or 0)
        won, paid, net = money.get(key, (None, None, None))
        alive, knocked = suicide.get(key, (False, None))
        big_loser = (player.big_loser_points if official else 0) or sum(
            int(season.weeks[n].lines[key].big_loser_wins or 0)
            for n in weeks if key in season.weeks[n].lines
        )
        players.append({
            "name": player.display,
            "place": place,
            "move": move,
            "wins": wins,
            "weekly": weekly,
            "won": won,
            "paid": paid,
            "net": net,
            "big_loser": float(big_loser or 0),
            "suicide": {
                "alive": alive,
                "out": knocked,
                # Played weeks only: a pick for a week still to come is
                # nobody else's business until the games are over.
                "picks": {str(w): display_team(t) for w, t in sorted(player.suicide_picks.items())
                          if w in weeks and w >= round_start},
                # the same teams as codes, for the board's "teams left"
                "used": [team_code(t) for w, t in sorted(player.suicide_picks.items())
                         if w in weeks and w >= round_start and team_code(t)],
            },
            "patterns": found.get(key),
        })
    players.sort(key=lambda r: (r["place"] if r["place"] is not None else 999, -r["wins"],
                                r["name"].casefold()))
    race = _race(season, players, latest)
    try:
        title_by_week = _title_by_week(players, weeks) if weeks else {}
    except Exception:  # noqa: BLE001 - the chart is left off, the page goes up
        title_by_week = {}
    try:
        money_by_week = _money_weeks(season, weeks, money, money_from)
    except Exception:  # noqa: BLE001
        money_by_week = {}

    LIVE_NOTE[0] = ""
    try:
        live = _live(season, latest) if latest else None
    except Exception as exc:  # noqa: BLE001 - the finished weeks go up regardless
        live = None
        LIVE_NOTE[0] = f"the live week couldn't be built ({exc!r})"
    stamp = generated or time.strftime("%Y-%m-%d %H:%M")
    try:
        extras = siteextras.Extras.load()
        note = extras.page_note()
        history = siteextras.page_history(siteextras.season_year(stamp), extras)
    except Exception as exc:  # noqa: BLE001 - no store (a test, a broken backup): no extras
        if strict:
            raise RuntimeError(f"the announcement and past seasons couldn't be read ({exc})") from exc
        note, history = None, {"champions": [], "seasons": []}
    return {
        "live": live,
        "schema": SCHEMA,
        "title": getattr(season, "title", "") or "ACQL",
        "generated": stamp,
        "through_week": latest,
        "buy_in": _money(season.buy_in),
        "entrants": len(season.players),
        "money": money_from,               # "" when the files don't give it
        "players": players,
        "race": race,
        "title_by_week": title_by_week,
        "money_by_week": money_by_week,
        "note": note,
        "alerts": _alerts_link(),
        "texts": _texts_on(),
        "history": history,
        "teams": {code: display_team(code) for code in sorted(DISPLAY)},
        "team_rank": _team_ranks(latest),
        "team_power": _team_power(latest),
        "weeks": [
            {**w, "chaos": chaos.get(w["week"])} for w in (
                _week(season, n, money_known=n not in set(getattr(season, "computed_winnings", []) or []),
                      finished=weeks)
                for n in weeks
            )
            if w is not None
        ],
    }


def _clean(value):
    """NaN and infinity have no JSON spelling; a stray one would stop the page."""
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def to_json(data: dict) -> str:
    """JSON safe to put inside a <script> block (no "</" can end it early)."""
    return json.dumps(_clean(data), ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).replace("</", "<\\/")


TEMPLATE = Path(__file__).with_name("pool_page.html")
SITE = "__SITE__"               # the website's address, filled in on upload
PREVIEW = "preview.png"         # the link-preview picture, next to the page
MANIFEST = "manifest.webmanifest"
ICONS = {512: "icon-512.png", 192: "icon-192.png", 180: "apple-touch-icon.png"}
THEME = "#0a0c0b"               # the on-air black of the site's top bar - the logo's own


def app_files() -> dict[str, bytes]:
    """What a phone needs to save the site to its home screen like an app:
    the icons and the little file that names them. Uploaded beside the page."""
    from . import brand, previewcard
    # The league's logo when it is there (brand.py); the drawn crest otherwise.
    files = {name: brand.icon(size) or previewcard.icon(size) for size, name in ICONS.items()}
    manifest = {
        "name": "ACQL - Arm Chair Quarterback League",
        "short_name": "ACQL",
        "description": "Standings, live scores, side pools, charts and history for the Arm Chair Quarterback League.",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#0a0d0b",
        "theme_color": THEME,
        "icons": [
            {"src": ICONS[192], "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": ICONS[512], "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    files[MANIFEST] = json.dumps(manifest, indent=1).encode("utf-8")
    return files


HISTORY_FILE = "history.json"   # past seasons and champions, fetched when History opens
SERVICE_WORKER = "sw.js"         # keeps the site opening with no signal
SW_TEMPLATE = Path(__file__).with_name("pool_sw.js")


def service_worker(version: str) -> str:
    return SW_TEMPLATE.read_text(encoding="utf-8").replace("__VERSION__", version)


def site(season: Season, *, generated: str | None = None) -> tuple[str, dict[str, bytes], dict]:
    """(index.html, the files that go beside it, the snapshot it shows) for
    the pool's own website. The season's own figures are in the page itself,
    so the page and its numbers always arrive together; the archive of past
    seasons, which only grows, is its own file and is only fetched when
    someone opens History."""
    data = snapshot(season, generated=generated, strict=True)
    if not data["weeks"]:
        raise ValueError("no finished week to put on the page yet")
    history = data.pop("history", None) or {"champions": [], "seasons": []}
    data["history_url"] = HISTORY_FILE
    # Each week's replay is its own file, fetched when that week is opened:
    # a season of them would make the page itself slow to open.
    replays = {}
    for week in data["weeks"]:
        info = week.get("replay")
        if info and "data" in info:
            name = replay_file(week["week"])
            replays[name] = to_json(info.pop("data")).encode("utf-8")
            info["file"] = name
    page = _hosted_page(data)
    stamp = "".join(ch for ch in data["generated"] if ch.isdigit())
    files = {
        **replays,
        HISTORY_FILE: to_json(history).encode("utf-8"),
        SERVICE_WORKER: service_worker(stamp).encode("utf-8"),
    }
    data["history"] = history
    return page, files, data


#: The suicide board marks a coach's teams left among the ten best
#: (TOP_TEAMS in the page's 50-pages.js) - all it shows of the ratings.
TOP_TEAMS = 10


def _as_shown(data: dict) -> dict:
    """The snapshot as far as the page shows it. The ratings' full order and
    the betting spreads of finished games shift whenever a line is stored;
    the page shows only the top ten and never the spreads, so those alone
    shouldn't put the site up again."""
    out = dict(data)
    rank = data.get("team_rank") or {}
    out["team_rank"] = sorted(c for c, r in rank.items() if r <= TOP_TEAMS) if len(rank) >= 28 else []
    out["weeks"] = [
        dict(w, results=[{k: v for k, v in g.items() if k != "spread"} for g in w.get("results") or []])
        for w in data.get("weeks") or []
    ]
    return out


def site_fingerprint(data: dict) -> str:
    """Changes whenever the website would: new results, a new pick sheet, the
    announcement or champions, or a dashboard update that changes the page."""
    from ..version import VERSION
    # the tokens and shared icons count as part of the page: a change to either republishes it
    template = hashlib.sha256(_with_design(TEMPLATE.read_text(encoding="utf-8")).encode("utf-8")).hexdigest()
    return siteextras.fingerprint(_as_shown(data), [VERSION, template])


def page_html(season: Season, *, generated: str | None = None) -> str:
    """The whole pool page as one web page, for the pool's own website.

    The same page as the Claude one, marked as hosted so it offers no
    "update this page" controls - the dashboard publishes it instead.
    """
    return site(season, generated=generated)[0]


_TOKENS = re.compile(r"(/\* tokens:begin.*?\*/\n).*?(\n/\* tokens:end \*/)", re.S)


def _with_design(page: str) -> str:
    """The page with the dashboard's own design tokens and shared icon drawings
    written in, so the site and the window never drift apart (tokens.py)."""
    from . import iconset, tokens
    page = _TOKENS.sub(lambda m: m.group(1) + tokens.css() + m.group(2), page, count=1)
    shared = json.dumps(json.dumps(iconset.web_icons())).replace("</", "<\\/")
    return page.replace('"__POOL_ICONS__"', shared)


def _hosted_page(data: dict) -> str:
    import html as _html
    data["hosted"] = "web"
    from . import brand
    fragment = (_with_design(TEMPLATE.read_text(encoding="utf-8"))
                .replace("__POOL_LOGO__", brand.data_uri())
                .replace("__POOL_DATA__", to_json(data)))
    head, body = fragment.split('<div id="app"', 1)
    year = siteextras.season_year(data["generated"])      # January is still last autumn's season
    version = f"{data['through_week']}-" + "".join(ch for ch in data["generated"] if ch.isdigit())
    blurb = (f"Arm Chair Quarterback League: standings, live scores and side pools after week "
             f"{data['through_week']} - {data['entrants']} coaches.")
    meta = (
        f'<meta name="description" content="{_html.escape(blurb, quote=True)}">'
        f'<meta property="og:title" content="ACQL {year} - after week {data["through_week"]}">'
        f'<meta property="og:description" content="{_html.escape(blurb, quote=True)}">'
        '<meta property="og:type" content="website">'
        # The link preview: SITE is filled in with the website's address as
        # it is uploaded (webpublish.publish), and the version makes chat
        # apps fetch the new picture each week instead of last week's.
        f'<meta property="og:url" content="{SITE}">'
        f'<meta property="og:image" content="{SITE}{PREVIEW}?v={version}">'
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
        '<meta name="twitter:card" content="summary_large_image">'
        # Add to Home Screen: the icon and name a phone gives the saved page
        f'<link rel="manifest" href="{MANIFEST}">'
        f'<link rel="icon" type="image/png" sizes="192x192" href="{ICONS[192]}">'
        f'<link rel="apple-touch-icon" href="{ICONS[180]}">'
        '<meta name="apple-mobile-web-app-title" content="ACQL">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
        f'<meta name="theme-color" content="{THEME}">'
    )
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
            + meta + head.strip() + "</head><body>\n<div id=\"app\"" + body + "</body></html>\n")


def export(season: Season, folder: str | Path | None = None) -> Path:
    """Write this week's pool-page file - to Downloads unless told otherwise."""
    data = snapshot(season)
    if not data["weeks"]:
        raise ValueError("no finished week to put on the page yet")
    folder = Path(folder) if folder else Path.home() / "Downloads"
    if not folder.is_dir():
        from .. import store
        folder = store.data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{FILE_PREFIX} - week {data['through_week']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
