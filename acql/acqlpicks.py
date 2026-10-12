"""The A.C.Q.L. card: what to play in all three contests, by the league's rules.

Three contests, kept apart because they are scored apart:

    main game     every game gets a pick. Most are straight up (pick the
                  winner); the commissioner makes some line games, where his
                  favourite must win by at least his line (a win by exactly a
                  whole-number line goes to the favourite, analytics.line_need).
    Big Loser     three teams a week to LOSE BY MORE THAN 14 (15 or more);
                  lines play no part; a point for each.
    suicide       one team a week to win, never the same team twice; a
                  commissioner line game is judged against his line.

Everything is priced the way the rest of the dashboard prices it (pricing,
briefing, survivor, bigloser), so this card can never disagree with Your card
about the same game. What this adds:

  * a game's pool-line status is never guessed. A spread on a game does not
    make it a line game; until the commissioner's lines are in (his sheet,
    the line games typed in, or the week confirmed by hand) every game
    without one is UNCONFIRMED, and says so;
  * the outright winner and its chance are kept apart from the side the
    pool would credit;
  * a week that has locked shows Deadeye's card as it was frozen at the lock
    (cards.py), never one re-made with hindsight;
  * a season-long log of the owner's official suicide picks, typed in by
    hand, which the advice never offers again and which warns on a repeat.

No Qt here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import analytics, cards, lines, oddslock, predictions, pricing, results, store, survivor
from .models import Game, Season

#: Weeks whose line games were confirmed by hand: "YEAR-WEEK" -> {"confirmed": True, "at": time}.
CONFIRM_KIND = "line-designation"
#: The owner's official suicide picks: "YEAR" -> {"WEEK": {"team": code, "status": ..., "at": time}}.
SUICIDE_KIND = "suicide-log"
#: What a logged suicide pick can be.
PENDING, SURVIVED, OUT = "pending", "survived", "out"
STATUSES = (PENDING, SURVIVED, OUT)

STRAIGHT, LINE, UNCONFIRMED = "Straight", "Line game", "Unconfirmed"
BIG_LOSS = analytics.BIG_LOSER_MARGIN + 1       # 15: loses by MORE than 14
BIG_LOSERS = 3
#: What every table says about a tied game: the league's rule for it is not recorded.
TIE_NOTE = "tie - how the league grades a tie is not recorded"
#: The market source names a model selector can show beside Deadeye.
MARKET, CONSENSUS = "Market line", "Model consensus"
MODEL_PREFIX = "model:"


def _year(season: Season) -> int:
    return results.season_year(season)


def _key(year: int, week: int) -> str:
    return f"{year}-{week}"


def _code(team: object) -> str:
    return predictions.team_code(team) or ""


# ---- line-game designation ------------------------------------------------------------
def confirmed_by_hand(year: int, week: int) -> bool:
    try:
        return bool((store.get(CONFIRM_KIND, _key(year, week)) or {}).get("confirmed"))
    except store.StoreError:
        return False


def confirm_lines(year: int, week: int, confirmed: bool = True) -> None:
    """Mark a week's line games as complete (every other game is straight up)."""
    try:
        if confirmed:
            store.put(CONFIRM_KIND, _key(year, week), {"confirmed": True, "at": time.time()})
        else:
            store.delete(CONFIRM_KIND, _key(year, week))
    except store.StoreError:
        pass


def lines_known(season: Season, week: int) -> tuple[bool, str]:
    """(whether the week's line games are known, how).

    Known from the commissioner's own pick sheet, from line games typed in for
    the week, from a line already on one of its games, or from a hand
    confirmation. A week the dashboard set up from the fixtures alone, or
    whose slate has no line on it yet, is not known.
    """
    year = _year(season)
    found = season.weeks.get(week)
    if week in (season.sheet_weeks or []):
        return True, "the commissioner's pick sheet"
    try:
        typed = lines.pool_lines(year, week)
    except Exception:  # noqa: BLE001 - a store problem leaves it unconfirmed
        typed = {}
    if typed:
        return True, "the line games typed in"
    if found is not None and any(g.line is not None for g in found.games):
        return True, "the lines on the slate"
    if confirmed_by_hand(year, week):
        return True, "confirmed by hand"
    return False, ""


def pick_type(game: Game, known: bool) -> str:
    if game.line is not None:
        return LINE
    return STRAIGHT if known else UNCONFIRMED


# ---- what the replay of past seasons found -----------------------------------------------
#: Written by the training ground's "contests" command (data/training); read
#: here as a plain file, so the dashboard never imports the training ground.
REPLAY_FILE = ("training", "contests.json")


def replay() -> dict | None:
    """The 2010-2025 replay of the three contests, if it has been run."""
    import json
    path = store.data_dir().joinpath(*REPLAY_FILE)
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and "main" in found else None


def replay_lines(found: dict | None = None) -> dict[str, str]:
    """One sentence per contest from the replay, or "" when there isn't one."""
    found = replay() if found is None else found
    if not found:
        return {"main": "", "losers": "", "suicide": ""}
    span = "{}-{}".format(*found.get("seasons", ("?", "?")))
    out = {}
    try:
        d, m = found["main"]["Deadeye"], found["main"]["Market line"]
        out["main"] = (f"Replayed {span}: Deadeye's straight picks {d['straight']['rate']:.1%} right, "
                       f"line games {d['line']['rate']:.1%} (past line games are the commissioner's habit, "
                       f"not his real lines); the line alone {m['straight']['rate']:.1%} and "
                       f"{m['line']['rate']:.1%}.")
        b = found["big_loser"]["Deadeye"]
        out["losers"] = (f"Replayed {span}: {b['per_week']:.2f} points a week; at least one hit in "
                         f"{b['at_least']['1']:.0%} of weeks, two in {b['at_least']['2']:.0%}, all three in "
                         f"{b['at_least']['3']:.0%}.")
        sv = found["suicide"]["Deadeye"]
        out["suicide"] = (f"Replayed {span}: the likeliest unused team survived {sv['rate']:.0%} of weeks; "
                          f"a season's run usually ended by week {sv['median_out']:g}.")
    except (KeyError, TypeError, ValueError):
        return {"main": "", "losers": "", "suicide": ""}
    return out


# ---- the main game ----------------------------------------------------------------------
@dataclass(frozen=True)
class MainRow:
    index: int
    away: str                       # team codes
    home: str
    matchup: str
    opening: float | None           # home margins
    current: float | None
    models: int
    consensus: float | None
    margin: float | None            # the margin the pick was priced on (Deadeye's)
    winner: str                     # predicted outright winner (code)
    win_chance: float | None
    kind: str                       # STRAIGHT / LINE / UNCONFIRMED
    pool_line: str
    pick: str                       # the recommended A.C.Q.L. pick (code)
    chance: float | None            # chance the pool credits that pick
    confidence: str
    frozen: bool                    # from the card kept at the lock
    if_lined: str = ""              # for an unconfirmed big favourite: the pick if a line comes
    selected: float | None = None   # the model selector's margin, home side
    selected_pick: str = ""
    mine: str = ""                  # the owner's submitted pick (code)
    outright: str = ""              # who actually won (code), "tie", or ""
    credited: str = ""              # who the pool credits (code), "tie", or ""
    right: bool | None = None       # the owner's pick, once decided
    deadeye_right: bool | None = None
    flags: tuple[str, ...] = ()


def strength(chance: float | None) -> str:
    if chance is None:
        return ""
    from .evidence import strength as named
    return named(chance)


def _home_win(margin: float, sd: float = analytics.SPREAD_SD) -> float:
    if margin >= 0:
        return analytics.cover_chance(margin, 1, sd)
    return 1 - analytics.cover_chance(-margin, 1, sd)


def _decided(game: Game) -> tuple[str, str]:
    """(outright winner code or "tie", credited side code or "tie"); "" when not played."""
    if game.home_points is None or game.away_points is None:
        if not game.played:
            return "", ""
        winner = _code(game.winner)
        return "", ("tie" if game.winner == results.TIE else winner)
    if game.home_points == game.away_points:
        outright = "tie"
    else:
        outright = _code(game.home) if game.home_points > game.away_points else _code(game.away)
    credited = results.credited(game, game.home_points, game.away_points)
    return outright, ("tie" if credited == results.TIE else _code(credited))


def _graded(pick: str, credited: str) -> bool | None:
    if not pick or not credited or credited == "tie":
        return None
    return pick == credited


def model_choices(week: int) -> list[tuple[str, str]]:
    """(label, key) for the model selector: the market, the consensus, and
    every model kept by name for this week (computers.py)."""
    out = [(MARKET, MARKET), (CONSENSUS, CONSENSUS)]
    try:
        entry = store.get("computers", str(week)) or {}
    except store.StoreError:
        entry = {}
    seen = sorted({name for g in entry.get("games") or [] for name in (g.get("named") or {})})
    from .computers import label
    return out + [(label(n), MODEL_PREFIX + n) for n in seen]


def _named(week: int, games: list[Game], code: str) -> dict[int, float]:
    """game index -> this model's home margin, from the models kept by name."""
    try:
        entry = store.get("computers", str(week)) or {}
    except store.StoreError:
        return {}
    by_pair = {}
    for g in entry.get("games") or []:
        value = (g.get("named") or {}).get(code)
        road, home = _code(g.get("road")), _code(g.get("home"))
        if value is not None and road and home:
            by_pair[frozenset((road, home))] = (home, float(value))
    out = {}
    for game in games:
        found = by_pair.get(frozenset((_code(game.away), _code(game.home))))
        if found is not None:
            home, value = found
            out[game.index] = value if home == _code(game.home) else -value
    return out


def main_game(season: Season, week: int, *, model: str = MARKET, me: str = "") -> list[MainRow]:
    """Every game of the week, with the pick to play."""
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return []
    known, _ = lines_known(season, week)
    ctx = pricing.context(season, week, games)
    prices = {p.game.index: p for p in pricing.price_week(season, week, games, ctx)}
    locked = oddslock.locked_for(season, week)
    kept = cards.model(week) if locked else None
    if kept is not None:
        kept = cards.aligned(kept, [(g.index, g.away, g.home) for g in games])
    unkept = locked and kept is None
    picks_of_me: dict[int, str] = {}
    if me:
        from . import everyone
        card = everyone.build(season, week).coach(me)
        picks_of_me = dict(card.picks) if card is not None else {}
    selected: dict[int, float] = {}
    if model.startswith(MODEL_PREFIX):
        selected = _named(week, games, model[len(MODEL_PREFIX):])

    rows = []
    for game in games:
        flags: list[str] = []
        price = prices.get(game.index)
        forecast = ctx.forecasts.get(game.index)

        def home_side(value):
            return predictions.home_margin(game, forecast, value) if forecast is not None else None

        opening = home_side(forecast.opening) if forecast is not None else None
        current = pricing.market_margin(game, forecast) if forecast is not None else None
        consensus = home_side(forecast.consensus) if forecast is not None else None
        n_models = forecast.models if forecast is not None else 0
        if forecast is None:
            flags.append("no forecasts file for this game")
        elif not n_models:
            flags.append("no computer models for this game")
        margin = price.margin if price is not None else None
        sd = price.sd if price is not None else analytics.SPREAD_SD
        kind = pick_type(game, known)

        pick, chance, frozen = "", None, False
        if kept is not None and (kept.plain or kept.take).get(game.index):
            pick = _code((kept.plain or kept.take)[game.index])
            if _code(kept.take.get(game.index)) == pick:
                chance = kept.chance.get(game.index)
            frozen = True
            if kept.margin.get(game.index) is not None:
                margin = kept.margin[game.index]
        elif price is not None and price.prediction() is not None:
            guess = price.prediction()
            pick, chance = _code(guess.pick), guess.chance
        if margin is None:
            flags.append("no line or forecast: nothing to price it on")
        elif unkept:
            flags.append("no card was kept at the lock - priced again from the stored lines")

        winner = win = None
        if margin is not None:
            if abs(margin) < analytics.PICK_EM:
                winner, win = "", 0.5
                flags.append("pick 'em")
            else:
                winner = _code(game.home) if margin > 0 else _code(game.away)
                win = _home_win(abs(margin), sd)

        if_lined = ""
        if kind == UNCONFIRMED and margin is not None:
            guess_line = survivor.assumed_line(margin)
            if guess_line is not None:
                fav = game.home if margin > 0 else game.away
                trial = Game(game.index, game.home, game.away, line=guess_line, line_favourite=fav)
                lined = analytics.predict_margin(trial, margin, sd=sd)
                if lined is not None:
                    if_lined = (f"if lined {predictions.display_team(fav)} by {guess_line:g}: "
                                f"{predictions.display_team(lined.pick)} ({lined.chance:.0%})")
                flags.append("a favourite this big usually gets a line - confirm the line games")

        sel_margin = {MARKET: current, CONSENSUS: consensus}.get(model, selected.get(game.index))
        sel_pick = ""
        if sel_margin is not None:
            guess = analytics.predict_margin(game, sel_margin, sd=analytics.SPREAD_SD)
            sel_pick = _code(guess.pick) if guess is not None else ""

        outright, credited = _decided(game)
        mine = _code(picks_of_me.get(game.index))
        if credited == "tie":
            flags.append(TIE_NOTE)
        rows.append(MainRow(
            index=game.index, away=_code(game.away), home=_code(game.home), matchup=game.label,
            opening=opening, current=current, models=n_models, consensus=consensus, margin=margin,
            winner=winner or "", win_chance=win, kind=kind, pool_line=_line_text(game),
            pick=pick, chance=chance, confidence=strength(chance), frozen=frozen, if_lined=if_lined,
            selected=sel_margin, selected_pick=sel_pick, mine=mine, outright=outright,
            credited=credited, right=_graded(mine, credited), deadeye_right=_graded(pick, credited),
            flags=tuple(flags)))
    return rows


def _line_text(game: Game) -> str:
    if game.line is None or not game.line_favourite:
        return ""
    return f"{predictions.display_team(game.line_favourite)} by {game.line:g}"


# ---- Big Loser --------------------------------------------------------------------------
@dataclass(frozen=True)
class LoserRow:
    rank: int                       # 1-3 for the picks, then the rest
    team: str                       # code
    opponent: str
    opponent_margin: float          # how much the opponent is expected to win by
    home: bool                      # the team plays at home
    chance: float                   # chance of losing by 15 or more (analytics.big_loser_chance)
    pick: bool                      # one of the three
    frozen: bool
    lost_by: int | None = None      # once played
    hit: bool | None = None


@dataclass(frozen=True)
class LoserBoard:
    rows: list[LoserRow]
    picks: list[LoserRow]
    points: int | None              # the three picks' points once all are decided
    mine: tuple[str, ...] = ()
    my_points: int | None = None


def big_losers(season: Season, week: int, *, shown: int = 8, me: str = "") -> LoserBoard:
    """The likeliest teams to lose by more than 14, the top three picked."""
    found = season.weeks.get(week)
    games = sorted(found.games, key=lambda g: g.index) if found else []
    if not games:
        return LoserBoard([], [], None)
    by_team = {}
    for g in games:
        by_team[_code(g.home)] = g
        by_team[_code(g.away)] = g
    prices = pricing.price_week(season, week, games)
    candidates = pricing.big_loser_candidates(prices, include_played=True)
    locked = oddslock.locked_for(season, week)
    kept = cards.model(week) if locked else None
    frozen_three = [c for c in (kept.losers if kept is not None else []) if c]
    if frozen_three:
        chosen = [_code(c) for c in frozen_three][:BIG_LOSERS]
    else:
        chosen = [_code(c.team) for c in candidates[:BIG_LOSERS]]

    def result(code: str) -> tuple[int | None, bool | None]:
        game = by_team.get(code)
        if game is None:
            return None, None
        by = results.lost_by(game, code)
        return by, (None if by is None else by >= BIG_LOSS)

    rows, rank = [], 0
    ordered = sorted(candidates, key=lambda c: (_code(c.team) not in chosen, -c.chance))
    for c in ordered[:max(shown, BIG_LOSERS)]:
        code = _code(c.team)
        is_pick = code in chosen
        rank += 1
        by, hit = result(code)
        chance = c.chance
        if frozen_three and code in (kept.loser_chance or {}):
            chance = kept.loser_chance[code]
        game = by_team.get(code)
        rows.append(LoserRow(rank=rank, team=code, opponent=_code(c.opponent),
                             opponent_margin=-c.margin,
                             home=game is not None and _code(game.home) == code,
                             chance=chance, pick=is_pick,
                             frozen=bool(frozen_three) and is_pick, lost_by=by, hit=hit))
    picks = [r for r in rows if r.pick]
    points = sum(1 for r in picks if r.hit) if picks and all(r.hit is not None for r in picks) else None
    mine: tuple[str, ...] = ()
    my_points = None
    if me:
        from . import everyone
        card = everyone.build(season, week).coach(me)
        mine = tuple(_code(t) for t in (card.losers if card is not None else ()) if _code(t))
        outcomes = [result(t)[1] for t in mine]
        if mine and all(o is not None for o in outcomes):
            my_points = sum(1 for o in outcomes if o)
    return LoserBoard(rows, picks, points, mine, my_points)


def score_big_losers(margins_lost: list[int]) -> int:
    """Points for a week's three: one for each that lost by more than 14."""
    return sum(1 for by in margins_lost if by >= BIG_LOSS)


# ---- the suicide pool ---------------------------------------------------------------------
@dataclass(frozen=True)
class Logged:
    week: int
    team: str                       # code
    status: str


def suicide_log(year: int) -> list[Logged]:
    try:
        raw = store.get(SUICIDE_KIND, str(year)) or {}
    except store.StoreError:
        raw = {}
    out = []
    for week, entry in raw.items():
        try:
            team = _code(entry.get("team"))
            status = entry.get("status") if entry.get("status") in STATUSES else PENDING
            if team:
                out.append(Logged(int(week), team, status))
        except (AttributeError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda e: e.week)


def used_teams(season: Season, me: str) -> dict[str, int]:
    """Team code -> the week it was spent, from the sheets and the log together."""
    used = {code: week for week, code in survivor.used_teams(season, me)} if me else {}
    for entry in suicide_log(_year(season)):
        used.setdefault(entry.team, entry.week)
    return used


def record_suicide(season: Season, week: int, team: str, status: str = PENDING,
                   me: str = "") -> list[str]:
    """Log the owner's official pick for a week. Returns warnings (a team
    already used in another week is saved all the same - it is the official
    record - and said loudly). An empty team clears the week."""
    year = _year(season)
    code = _code(team)
    warnings = []
    try:
        raw = dict(store.get(SUICIDE_KIND, str(year)) or {})
    except store.StoreError:
        raw = {}
    if not code:
        raw.pop(str(week), None)
    else:
        if status not in STATUSES:
            status = PENDING
        earlier = {w: c for c, w in used_teams(season, me).items()}
        for w, c in sorted(earlier.items()):
            if c == code and w != week:
                warnings.append(f"{predictions.display_team(code)} was already used in week {w} - "
                                f"a team can only be picked once a season.")
        raw[str(week)] = {"team": code, "status": status, "at": time.time()}
    try:
        if raw:
            store.put(SUICIDE_KIND, str(year), raw)
        else:
            store.delete(SUICIDE_KIND, str(year))
    except store.StoreError as exc:
        warnings.append(f"Could not save: {exc}")
    return warnings


@dataclass(frozen=True)
class SuicideView:
    advice: survivor.Advice | None
    pick: survivor.Option | None
    used: dict[str, int]
    logged: Logged | None
    alive: bool
    warnings: tuple[str, ...]


def suicide(season: Season, week: int, me: str) -> SuicideView:
    """The one eligible team to take this week, and the season's record."""
    used = used_teams(season, me)
    log = suicide_log(_year(season))
    logged = next((e for e in log if e.week == week), None)
    out_before = any(e.status == OUT and e.week < week for e in log)
    advice = survivor.advise(season, me, week, also_used=set(used)) if me else None
    alive = bool(advice is not None and advice.alive) and not out_before
    warnings = []
    if out_before:
        warnings.append("Your log has you out of the suicide pool already.")
    if logged is not None and used.get(logged.team, week) != week:
        warnings.append(f"Your official pick, {predictions.display_team(logged.team)}, was already "
                        f"used in week {used[logged.team]}.")
    pick = advice.pick if advice is not None and alive else None
    if pick is not None and pick.code in used:
        pick = None                                          # never offer a spent team
    return SuicideView(advice, pick, used, logged, alive, tuple(warnings))


@dataclass
class Card:
    """All three contests for one week."""

    week: int
    lines_known: bool
    lines_from: str
    main: list[MainRow] = field(default_factory=list)
    losers: LoserBoard | None = None
    suicide: SuicideView | None = None


def build(season: Season, week: int, *, model: str = MARKET, me: str = "") -> Card:
    known, how = lines_known(season, week)
    return Card(week=week, lines_known=known, lines_from=how,
                main=main_game(season, week, model=model, me=me),
                losers=big_losers(season, week, me=me),
                suicide=suicide(season, week, me) if me else None)
