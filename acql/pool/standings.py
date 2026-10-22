"""The standings export, worked out here so stats.xls never has to be uploaded.

Every number on the commissioner's stats.xls follows from each coach's weekly
scores. These rules were checked cell by cell against the real exports for
weeks 1, 2, 3 and 5:

    W        regular + big-loser wins, all season
    L        the most anyone could have won, minus W
    PCT, GB  W over that most; the leader's W minus yours
    -PTS     minus the buy-in, plus each week's (your score - the top score)
    +PTS     each week's pot, split between the coaches on the top score,
             plus Pie Splits (the side-pool money, entered by hand)
    pot      what everyone fell short of the top score by, added up
    NET      -PTS + +PTS
    Flux     this week's (score - top), or this week's pot share for a winner
    Pos      most wins; a tie goes to whoever was higher the week before
    3 wk     wins over the last three weeks
    BL pool  big-loser wins, all season
    line %   share of the pool's line games picked right

The newest stats.xls is still read and believed for every week it covers.
This only rolls the standings forward over weeks it doesn't cover yet, so
nothing changes the day the export arrives, and nothing waits for it.
"""

from __future__ import annotations

from ..feeds import results
from ..model.predictions import team_code
from ..models import Season

def _decided(game) -> bool:
    return bool(str(game.winner or "").strip())


def regrade(season: Season) -> list[int]:
    """Grade the workbook's weeks against the results.

    The workbook scores a row by counting the picks left on it (COUNTA),
    which is right once the commissioner has deleted the wrong picks and
    wrong before: an ungraded week scored every pick as a win, 16 each for
    everyone. Each pick is checked against its game's winner instead - the
    same answer on a graded row, the right one on an ungraded row. Returns
    the weeks whose scores changed.
    """
    from .picks import _loser_slots

    changed: list[int] = []
    year = season.results_year or results.season_year(season)
    for number, week in season.weeks.items():
        if week.source is None:
            continue  # built from a pick sheet: graded already
        # The final scores, for the Big Losers (a winner typed in stays).
        if any(g.home_points is None for g in week.games):
            kept = results.load(year, number)
            for game in week.games:
                if game.home_points is None:
                    results.apply(game, kept)
        decided = {g.index: g for g in week.games if _decided(g)}
        if not decided:
            continue
        listed = {team_code(t) for t in season.big_losers_by_week.get(number, []) if team_code(t)}
        moved = False
        for line in week.lines.values():
            for index, pick in list(line.correct_picks.items()):
                game = decided.get(index)
                if game is not None and team_code(pick) != team_code(game.winner):
                    del line.correct_picks[index]
            regular = sum(1 for i in line.correct_picks if i in decided)
            cells, teams, hits, _ = _loser_slots(week, line.big_loser_raw, None, listed, set())
            total = regular + hits
            if (regular, total) != (line.regular_wins, line.total_wins):
                moved = True
            line.big_loser_raw, line.big_loser_picks, line.big_loser_wins = cells, teams, hits
            line.regular_wins, line.total_wins = regular, total
        if moved:
            changed.append(number)
    return sorted(changed)


def complete_weeks(season: Season) -> list[int]:
    """Weeks with every game decided and coaches' picks in them."""
    return sorted(
        n for n, w in season.weeks.items()
        if w.games and w.lines and all(_decided(g) for g in w.games)
    )


def big_losers(week) -> list[str]:
    """The week's teams beaten by the pool's big-loser margin."""
    out = []
    for g in week.games:
        for team in (g.away, g.home):
            by = results.lost_by(g, team)
            if by is not None and by >= results.BLOWOUT:
                out.append(team)
    return out


def roll_forward(season: Season, stats_week: int) -> int:
    """Bring the standings up to the last finished week. Returns that week,
    or 0 when stats.xls already covers everything that has been played."""
    from ..config import BIG_LOSER_PICKS

    done = complete_weeks(season)
    last = done[-1] if done else 0
    if last <= stats_week:
        return 0
    people = season.players
    if not people:
        return 0

    # Weekly scores: the export's for weeks it covers, the graded week's after.
    for number in done:
        if number <= stats_week:
            continue
        week = season.weeks[number]
        for key, person in people.items():
            line = week.lines.get(key)
            regular = line.regular_wins if line else 0
            loser = line.big_loser_wins if line else 0
            person.weekly_regular[number] = regular
            person.weekly_big_loser[number] = loser
            person.weekly_wins[number] = regular + loser
            person.provisional_wins.pop(number, None)
        if number not in season.big_losers_by_week:
            season.big_losers_by_week[number] = big_losers(week)

    weeks = sorted({w for p in people.values() for w in p.weekly_wins if w <= last})

    def most(number: int) -> int:
        week = season.weeks.get(number)
        games = len(week.games) if week and week.games else season.max_regular_points
        if week and not any(g.home_points is not None for g in week.games):
            # No final scores kept: the best anyone did is all that is known.
            best = max((l.big_loser_wins for l in week.lines.values()), default=0)
            return games + best
        listed = season.big_losers_by_week.get(number)
        losers = len(listed) if listed else len(big_losers(week)) if week else 0
        return games + min(BIG_LOSER_PICKS, losers)

    possible = sum(most(w) for w in weeks)
    buy_in = season.buy_in or 0.0
    # Line games per week, and who got each one right.
    line_games = {w: [g.index for g in season.weeks[w].games if g.line is not None]
                  for w in weeks if w in season.weeks}
    lined = sum(len(v) for v in line_games.values())

    pos: dict[str, int] = {}
    prev: dict[str, int] = {}
    for upto, number in enumerate(weeks):
        through = weeks[: upto + 1]
        scores = {k: p.weekly_wins.get(number, 0) for k, p in people.items()}
        top = max(scores.values(), default=0)
        pot = sum(top - s for s in scores.values())
        winners = [k for k, s in scores.items() if s == top]
        share = pot / len(winners) if winners else 0.0
        prev = dict(pos)
        totals = {k: sum(p.weekly_wins.get(w, 0) for w in through) for k, p in people.items()}
        order = sorted(people, key=lambda k: (-totals[k], prev.get(k, 999), people[k].display.casefold()))
        pos = {k: i for i, k in enumerate(order, start=1)}
        if number == last:
            leader = max(totals.values(), default=0)
            for k, person in people.items():
                person.wins = totals[k]
                person.losses = possible - totals[k]
                person.pct = totals[k] / possible if possible else 0.0
                person.games_behind = float(leader - totals[k])
                person.current_week_wins = scores[k]
                person.pos = pos[k]
                person.prev_pos = prev.get(k)

    tops = {w: max(p.weekly_wins.get(w, 0) for p in people.values()) for w in weeks}
    pots = {w: sum(tops[w] - p.weekly_wins.get(w, 0) for p in people.values()) for w in weeks}
    for k, person in people.items():
        short = sum(person.weekly_wins.get(w, 0) - tops[w] for w in weeks)
        won = 0.0
        for w in weeks:
            level = [q for q in people.values() if q.weekly_wins.get(w, 0) == tops[w]]
            if person.weekly_wins.get(w, 0) == tops[w]:
                won += pots[w] / len(level)
        person.points_paid = -buy_in + short
        person.points_won = round(won + person.pie_splits, 2)
        person.net_points = round(person.points_paid + person.points_won, 2)
        person.three_week_wins = sum(person.weekly_wins.get(w, 0) for w in weeks[-3:])
        person.big_loser_points = float(sum(person.weekly_big_loser.get(w, 0) for w in weeks))
        # The export's share stands for the weeks it covers (the
        # commissioner's grading of them); later weeks are added on.
        early = sum(len(v) for w, v in line_games.items() if w <= stats_week)
        right = person.line_game_pct * early if stats_week else 0.0
        right += sum(1 for w, idx in line_games.items() if w > stats_week or not stats_week
                     for i in idx if i in season.weeks[w].lines.get(k, _NoLine).correct_picks)
        if lined:
            person.line_game_pct = right / lined

    season.current_week = last
    return last


class _NoLine:
    correct_picks: dict = {}


def replay_suicide(season: Season, stats_week: int) -> bool:
    """Who is still alive in the suicide pool, week by week from the export.

    Starts from the newest export's survivors (or everyone), then takes each
    later week in turn: a coach survives a week only by picking a team that
    was credited with its game; no pick is out. When one coach is left the
    pool is won and starts again the next week with everyone in. Stops at the
    first week with no suicide picks in it at all. True if it moved on.
    """
    people = season.players
    alive = {k for k, p in people.items() if p.suicide_alive} if stats_week else set(people)
    if len(alive) <= 1:
        # The export's round is already won (or none is running): a new one
        # starts the week after, with everyone in.
        if stats_week and alive and not season.suicide_restart:
            season.suicide_winners = [people[k].display for k in alive]
            season.suicide_restart = stats_week + 1
        alive = set(people)
    moved = False
    for number in complete_weeks(season):
        if number <= stats_week:
            continue
        week = season.weeks[number]
        if not any(l.suicide_pick or l.suicide_out for l in week.lines.values()):
            break
        left = set()
        for k in alive:
            line = week.lines.get(k)
            code = team_code(line.suicide_pick) if line and not line.suicide_out else ""
            game = next((g for g in week.games if code and code in (team_code(g.home), team_code(g.away))), None)
            if game is not None and team_code(game.winner) == code:
                left.add(k)
            else:
                people[k].suicide_out_week = number
        moved = True
        if len(left) <= 1:
            # Won (or everyone fell together, and they share it): start again.
            season.suicide_winners = [people[k].display for k in (left or alive)]
            season.suicide_restart = number + 1
            alive = set(people)
            for p in people.values():
                p.suicide_out_week = None
        else:
            alive = left
    if moved:
        for k, p in people.items():
            p.suicide_alive = k in alive
    return moved
