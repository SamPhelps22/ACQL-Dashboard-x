"""The week, replayed: the pool's scores after every kickoff, score and final
whistle of a finished week, in the order they happened - and the stories
that only the order tells (the bad beats).

Built from each game's scoring plays (timeline.py), the pool's lines and
every coach's card for the week, by the same rule as the live page: a game
counts for the side the pool would credit if it ended there and then, a Big
Loser once its team is behind by 15 or more. A finished game counts for the
side the pool actually credited, so the replay ends exactly where the week's
scores did - and a week whose replay wouldn't (a card the dashboard doesn't
have) is left without one rather than shown wrong.

Only finished weeks, and only what the website already shows of them: the
side each coach took, and - now the games are over - their Big Losers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..pool import picks as pick_sheets
from ..feeds import results, timeline
from ..analytics import line_need
from ..models import Game, Season
from ..model.predictions import display_team, team_code
from ..wording import ordinal as _ordinal

BLOWOUT = results.BLOWOUT
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
#: Coaches whose replayed total may differ from the pool's own (a card the
#: dashboard only partly has) before the week's replay is left off.
MAX_MISMATCH = 2
#: "Late": the last five minutes of the fourth quarter, or overtime.
LATE_S = 5 * 60
#: When ESPN gives no time of day for a play: a game second takes about
#: this many real ones, plus a halftime.
REAL_PER_GAME_S, HALFTIME_S = 3.1, 13 * 60
#: A front-runner's story needs this long in front alone.
FRONT_RUNNER_S = 30 * 60
#: A swing that cost fewer coaches than this isn't a story.
SWING_MIN = 3
MAX_BEATS = 5
QUARTERS = {1: "first quarter", 2: "second quarter", 3: "third quarter", 4: "fourth quarter"}


def encode(totals: list[int]) -> str:
    """A frame's scores, one character a coach (0-9, then a-z)."""
    return "".join(DIGITS[min(max(int(v), 0), len(DIGITS) - 1)] for v in totals)


def decode(text: str) -> list[int]:
    return [DIGITS.index(ch) for ch in text]


def _clock_s(text: str) -> int | None:
    try:
        minutes, seconds = str(text).split(":")
        return int(minutes) * 60 + int(seconds)
    except (TypeError, ValueError):
        return None


def _estimate(kickoff: float, period: int, clock: str) -> float:
    left = _clock_s(clock)
    elapsed = (max(period, 1) - 1) * 900 + (900 - (left if left is not None else 450))
    return kickoff + elapsed * REAL_PER_GAME_S + (HALFTIME_S if period >= 3 else 0)


def _plain(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


@dataclass
class _Game:
    index: int
    game: Game
    ac: str                     # the slate's away and home, as codes
    hc: str
    fav: str                    # the pool's favourite, "" for a straight-up game
    winner: str                 # the side the pool credited, "" for a tie
    kickoff: float
    end: float
    moments: list[tuple] = field(default_factory=list)     # (at, away pts, home pts, period, clock, text)
    final: tuple[int, int] | None = None

    def label(self) -> str:
        return f"{display_team(self.game.away)} at {display_team(self.game.home)}"


def _games(season: Season, number: int) -> list[_Game] | None:
    week = season.weeks[number]
    year = results.season_year(season)
    scores = results.load(year, number)
    out = []
    for game in sorted(week.games, key=lambda g: g.index):
        if not game.played:
            return None
        if getattr(game, "called_off", False):
            continue
        score, _ = results.find(scores, game.away, game.home)
        if score is None or not score.final or score.kickoff is None:
            return None
        kept = timeline.load(year, number, score.away, score.home)
        if kept is None:
            return None
        flipped = score.home != team_code(game.home)
        moments = []
        for m in kept.moments:
            at = m.at if m.at is not None else _estimate(score.kickoff, m.period, m.clock)
            a, h = (m.home, m.away) if flipped else (m.away, m.home)
            moments.append((max(at, score.kickoff + 1), a, h, m.period, m.clock, m.text))
        moments.sort(key=lambda m: m[0])
        last = moments[-1][0] if moments else score.kickoff
        end = max(kept.end or 0, last + 60) if kept.end else last + 600
        winner = team_code(game.winner) if str(game.winner or "").strip() and game.winner != results.TIE else ""
        final = None
        if game.home_points is not None and game.away_points is not None:
            final = (int(game.away_points), int(game.home_points))
        fav = team_code(game.line_favourite) if game.line is not None and game.line_favourite else ""
        out.append(_Game(game.index, game, team_code(game.away), team_code(game.home), fav, winner,
                         float(score.kickoff), float(end), moments, final))
    return out or None


@dataclass
class _Card:
    key: str
    name: str
    picks: list[str]            # a code per replayed game, "" unknown
    losers: list[str]
    official: int
    unknown: int = 0            # right Big Losers the sheet only marks "1"


def _cards(season: Season, number: int, games: list[_Game]) -> list[_Card]:
    week = season.weeks[number]
    sheet = pick_sheets.load(number)
    sheet_names = {_plain(n): n for n in (sheet.coaches if sheet else [])}
    out = []
    for key, line in week.lines.items():
        player = season.players.get(key)
        name = player.display if player else line.player
        on_sheet = sheet_names.get(_plain(name)) or sheet_names.get(_plain(line.player))
        picks = []
        for g in games:
            right = team_code(line.correct_picks.get(g.index) or "")
            mine = ""
            if right:
                mine = right
            elif sheet is not None and on_sheet:
                row = sheet.game_for(g.game.away, g.game.home)
                took = team_code(row.picks.get(on_sheet, "")) if row else ""
                mine = took if took in (g.ac, g.hc) and took != g.winner else ""
            if not mine and g.winner:
                mine = g.hc if g.winner == g.ac else g.ac        # a miss: the other side
            picks.append(mine)
        raw = list(sheet.losers.get(on_sheet, [])) if sheet is not None and on_sheet else []
        if not any(team_code(t) for t in raw) and not any(str(t).strip() == "1" for t in raw):
            raw = list(line.big_loser_raw or line.big_loser_picks)
        losers = [team_code(t) for t in raw if team_code(t)]
        card = _Card(key, name, picks, losers, int(line.total_wins or 0))
        card.unknown = sum(1 for t in raw if str(t).strip() == "1")
        out.append(card)
    # A graded sheet keeps a right Big Loser as "1": it was one of the teams
    # that lost by 15 or more - the one most of the pool had, when it could be several.
    blown = []
    for g in games:
        if g.final is None:
            continue
        a, h = g.final
        if a - h >= BLOWOUT:
            blown.append(g.hc)
        elif h - a >= BLOWOUT:
            blown.append(g.ac)
    liked = {}
    for c in out:
        for t in c.losers:
            liked[t] = liked.get(t, 0) + 1
    for c in out:
        if c.unknown:
            spare = sorted((t for t in blown if t not in c.losers), key=lambda t: (-liked.get(t, 0), t))
            c.losers = c.losers + spare[:c.unknown]
    out.sort(key=lambda c: (-c.official, c.name.casefold()))
    return out


@dataclass
class Replay:
    week: int
    games: list[_Game]
    cards: list[_Card]
    frames: list[list]          # [at, game, kind, away pts, home pts, period, clock, text, totals]
    adjusted: list[str]         # coaches the pool's own scores were put in for at the end

    def data(self) -> dict:
        """What the website gets."""
        return {
            "week": self.week,
            "coaches": [c.name for c in self.cards],
            "games": [{"a": display_team(g.game.away), "h": display_team(g.game.home), "ac": g.ac, "hc": g.hc,
                       "line": float(g.game.line) if g.fav else None, "fav": g.fav, "w": g.winner,
                       "k": int(g.kickoff), "e": int(g.end)} for g in self.games],
            "frames": [f[:8] + [encode(f[8])] for f in self.frames],
            "adjusted": self.adjusted,
        }


def build(season: Season, number: int) -> Replay | None:
    """The week's replay; None when it can't be told faithfully."""
    week = season.weeks.get(number)
    if week is None or not week.lines or not week.games:
        return None
    games = _games(season, number)
    if games is None:
        return None
    cards = _cards(season, number, games)
    n = len(games)
    events = []
    for gi, g in enumerate(games):
        events.append((g.kickoff, 0, gi, "k", None))
        for m in g.moments:
            events.append((min(m[0], g.end - 1), 1, gi, "s", m))
        events.append((g.end, 2, gi, "f", None))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    phase = ["pre"] * n
    score = [(0, 0)] * n
    where = {}
    for gi, g in enumerate(games):
        where[g.ac] = where[g.hc] = gi

    def credit(gi: int) -> str:
        g = games[gi]
        if phase[gi] == "pre":
            return ""
        if phase[gi] == "final":
            return g.winner
        a, h = score[gi]
        side = results.credited(g.game, h, a)
        return "" if side == results.TIE else team_code(side)

    def totals() -> list[int]:
        credited = [credit(gi) for gi in range(n)]
        out = []
        for c in cards:
            v = sum(1 for gi, pick in enumerate(c.picks) if pick and pick == credited[gi])
            for team in c.losers:
                gi = where.get(team)
                if gi is None or phase[gi] == "pre":
                    continue
                a, h = score[gi]
                behind = (a - h) if team == games[gi].hc else (h - a)
                v += behind >= BLOWOUT
            out.append(v)
        return out

    frames = []
    for at, _, gi, kind, m in events:
        g = games[gi]
        if kind == "k":
            phase[gi] = "in"
            text, period, clock = "Kickoff", 1, "15:00"
        elif kind == "s":
            score[gi] = (m[1], m[2])
            text, period, clock = m[5], m[3], m[4]
        else:
            phase[gi] = "final"
            if g.final is not None:
                score[gi] = g.final
            ot = any(mm[3] >= 5 for mm in g.moments)
            text, period, clock = "Final" + ("/OT" if ot else ""), 0, ""
        a, h = score[gi]
        frames.append([int(at), gi, kind, a, h, period, clock, text, totals()])
    official = [c.official for c in cards]
    off = [c.name for c, v, want in zip(cards, frames[-1][8], official) if v != want]
    if len(off) > MAX_MISMATCH:
        # a week the commissioner has ruled on is told, ending on the ruled scores (pool/rulings.py)
        from ..pool import rulings
        ruled = rulings.get(results.season_year(season), number)
        if ruled is None:
            return None
        if ruled["ruling"] == "recount":
            return Replay(number, games, cards, frames, off)
    if off:
        last = frames[-1]
        frames.append([last[0] + 1, last[1], "o", last[3], last[4], 0, "", "The pool's own scores", official])
    return Replay(number, games, cards, frames, off)


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ---- the all-time bad-beat museum (#50) ---------------------------------------------------
MUSEUM = 10


def museum(season: Season, most: int = MUSEUM) -> list[dict]:
    """The latest swings that cost someone the week, across every week that can be
    replayed: each week's bad beat and late swing, latest in the week first."""
    out = []
    for number in sorted(season.weeks):
        try:
            rep = build(season, number)
        except Exception:  # noqa: BLE001 - one week that can't be told leaves the rest
            rep = None
        if rep is None or len(rep.frames) < 3:
            continue
        for beat in beats(rep):
            if beat.get("kind") not in ("bad-beat", "swing"):
                continue
            out.append({"week": number, "kind": beat["kind"], "title": beat["title"], "who": beat["who"],
                        "detail": beat["detail"], "late": round(beat["frame"] / (len(rep.frames) - 1), 4)})
    out.sort(key=lambda b: (-b["late"], b["week"]))
    return out[:most]


# ---- the bad beats -------------------------------------------------------------------
def _names(names: list[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= 3:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return f"{len(names)} coaches"


def _coaches(n: int) -> str:
    return f"{n} coach{'' if n == 1 else 'es'}"


def _when(period: int, clock: str) -> str:
    if period >= 5:
        return f"with {clock} left in overtime" if clock else "in overtime"
    quarter = QUARTERS.get(period, "")
    return f"with {clock} left in the {quarter}" if clock and quarter else (f"in the {quarter}" if quarter else "")


def describe(rep: Replay, i: int) -> str:
    """A frame as words: "Tampa Bay's touchdown with 2:01 left in the fourth quarter"."""
    at, gi, kind, a, h, period, clock, text, _ = rep.frames[i]
    g = rep.games[gi]
    if kind == "k":
        return f"the kickoff of {g.label()}"
    if kind in ("f", "o"):
        return f"the final whistle of {g.label()}"
    before = next(((f[3], f[4]) for f in reversed(rep.frames[:i]) if f[1] == gi), (0, 0))
    scored_away = a - before[0] > h - before[1]
    gain = (a - before[0]) if scored_away else (h - before[1])
    team = display_team(g.game.away if scored_away else g.game.home)
    other = display_team(g.game.home if scored_away else g.game.away)
    what = {1: "extra point", 2: "safety", 3: "field goal"}.get(gain, "touchdown" if gain >= 6 else "score")
    return f"{_owner(team)} {what} against {other} {_when(period, clock)}".strip()


def _owner(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def _leaders(totals: list[int]) -> set[int]:
    top = max(totals) if totals else 0
    return {i for i, v in enumerate(totals) if v == top}


def _places(cards: list[_Card]) -> list[int]:
    return [1 + sum(1 for o in cards if o.official > c.official) for c in cards]


def beats(rep: Replay) -> list[dict]:
    """The week's bad beats and turning points, most telling first. Each
    carries the replay frame it happened at, so the page can jump there."""
    frames, cards, games = rep.frames, rep.cards, rep.games
    if len(frames) < 3:
        return []
    names = [c.name for c in cards]
    places = _places(cards)
    top = max(c.official for c in cards)
    winners = {i for i, c in enumerate(cards) if c.official == top}
    out: list[dict] = []
    started = next((i for i, f in enumerate(frames) if f[2] == "s"), 0)
    leads = [_leaders(f[8]) for f in frames]

    # the moment that settled it: after it, the winners were always in front
    decider = None
    for i in range(len(frames) - 1, -1, -1):
        if leads[i] != winners:
            decider = i + 1
            break
    decided_at = decider if decider is not None and decider < len(frames) and frames[decider][2] != "o" else None

    # a bad beat: the coach who was in front alone latest, and lost it
    best = None
    for c in range(len(cards)):
        if c in winners:
            continue
        alone = [i for i in range(started, len(frames) - 1) if leads[i] == {c}]
        if alone and (best is None or alone[-1] > best[1]):
            best = (c, alone[-1])
    if best is not None and best[1] >= len(frames) // 2:
        c, i = best
        lost = i + 1
        out.append({"kind": "bad-beat", "title": "Bad beat", "who": names[c],
                    "detail": f"In front alone until {describe(rep, lost)} – finished {_ordinal(places[c])}.",
                    "frame": lost})

    winner_names = _names([names[i] for i in sorted(winners, key=lambda i: names[i].casefold())])
    if decided_at is not None and decided_at > started and not (out and out[0]["frame"] == decided_at):
        joint = len(winners) > 1
        out.append({"kind": "decider", "title": "The deciding moment", "who": winner_names,
                    "detail": f"{'Level at the top' if joint else 'In front'} for good from {describe(rep, decided_at)}.",
                    "frame": decided_at})
    elif decided_at is not None and decided_at <= started:
        out.append({"kind": "wire", "title": "Wire to wire", "who": winner_names,
                    "detail": "In front from the first score to the last.", "frame": started})

    # a late swing: a score in the last five minutes that moved the pool's credit
    swing = None
    for i, f in enumerate(frames):
        if f[2] != "s":
            continue
        period, left = f[5], _clock_s(f[6])
        if not (period >= 5 or (period == 4 and left is not None and left <= LATE_S)):
            continue
        gi = f[1]
        g = games[gi]
        prev = next((p for p in reversed(frames[:i]) if p[1] == gi), None)
        if prev is None:
            continue
        side_before = _side(g, prev[3], prev[4])
        side_after = _side(g, f[3], f[4])
        if not side_before or side_before == side_after or side_after != g.winner:
            continue            # only a swing that stuck: the side it went to was credited
        hurt = sum(1 for c in cards if c.picks[gi] == side_before)
        if hurt >= SWING_MIN and (swing is None or hurt >= swing[1]):
            swing = (i, hurt, side_before)
    if swing is not None:
        i, hurt, lost_side = swing
        g = games[rep.frames[i][1]]
        before_name = display_team(g.game.home if lost_side == g.hc else g.game.away)
        said = describe(rep, i)
        out.append({"kind": "swing", "title": "Late swing", "who": g.label(),
                    "detail": f"{said[0].upper()}{said[1:]} turned it – {_coaches(hurt)} "
                              f"with {before_name} lost a point.", "frame": i})

    # a Big Loser that got away: 15 or more behind in the fourth, and not at the end
    got_away = None
    for gi, g in enumerate(games):
        if g.final is None:
            continue
        for team in (g.ac, g.hc):
            holders = sum(1 for c in cards if team in c.losers)
            if not holders:
                continue
            final_behind = (g.final[0] - g.final[1]) if team == g.hc else (g.final[1] - g.final[0])
            if final_behind >= BLOWOUT:
                continue
            worst, at = 0, None
            for i, f in enumerate(frames):
                if f[1] != gi or f[2] != "s" or f[5] < 4:
                    continue
                behind = (f[3] - f[4]) if team == g.hc else (f[4] - f[3])
                if behind > worst:
                    worst, at = behind, i
            if worst >= BLOWOUT and (got_away is None or holders > got_away[1]):
                got_away = (team, holders, worst, final_behind, at, g)
    if got_away is not None:
        team, holders, worst, final_behind, at, g = got_away
        name = display_team(g.game.home if team == g.hc else g.game.away)
        ending = f"lost by {final_behind}" if final_behind > 0 else ("tied" if final_behind == 0 else f"won by {-final_behind}")
        out.append({"kind": "got-away", "title": "The one that got away", "who": name,
                    "detail": f"Down {worst} in the fourth quarter, {ending} – a Big Loser point gone for "
                              f"{_coaches(holders)}.", "frame": at})

    # a point short: a Big Loser beaten by 14, or a favourite one short of the line
    short = []
    for gi, g in enumerate(games):
        if g.final is None:
            continue
        for team in (g.ac, g.hc):
            behind = (g.final[0] - g.final[1]) if team == g.hc else (g.final[1] - g.final[0])
            holders = sum(1 for c in cards if team in c.losers)
            if behind == BLOWOUT - 1 and holders:
                name = display_team(g.game.home if team == g.hc else g.game.away)
                short.append((holders, {"kind": "short", "title": "A point short", "who": name,
                              "detail": f"Lost by {behind} – one short of a Big Loser point for {_coaches(holders)}.",
                              "frame": _final_frame(frames, gi)}))
        if g.fav:
            need = line_need(g.game.line)
            by = (g.final[1] - g.final[0]) if g.fav == g.hc else (g.final[0] - g.final[1])
            holders = sum(1 for c in cards if c.picks[gi] == g.fav)
            if by == need - 1 and by > 0 and holders:
                name = display_team(g.game.home if g.fav == g.hc else g.game.away)
                short.append((holders, {"kind": "short", "title": "A point short", "who": name,
                              "detail": f"Won by {by} with the pool's line at {g.game.line:g} – "
                                        f"{_coaches(holders)} needed one more.",
                              "frame": _final_frame(frames, gi)}))
    if short:
        out.append(max(short, key=lambda s: s[0])[1])

    # the front-runner: longest in front alone, and didn't win
    alone_for = [0.0] * len(cards)
    live = set()
    for i, f in enumerate(frames[:-1]):
        if f[2] == "k":
            live.add(f[1])
        elif f[2] in ("f", "o"):
            live.discard(f[1])
        if live and len(leads[i]) == 1:
            (c,) = leads[i]
            alone_for[c] += max(0, frames[i + 1][0] - f[0])
    runner = max((c for c in range(len(cards)) if c not in winners), key=lambda c: alone_for[c], default=None)
    if runner is not None and alone_for[runner] >= FRONT_RUNNER_S:
        mins = int(alone_for[runner] // 60)
        span = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
        first = next(i for i in range(len(frames)) if leads[i] == {runner})
        out.append({"kind": "front-runner", "title": "Front-runner", "who": names[runner],
                    "detail": f"In front alone for {span} of game time – finished {_ordinal(places[runner])}.",
                    "frame": first})

    # back and forth: how often the lead changed hands
    sole, changes, held = None, 0, []
    for i in range(started, len(frames)):
        if len(leads[i]) == 1:
            (c,) = leads[i]
            if sole is not None and c != sole:
                changes += 1
            if c not in held:
                held.append(c)
            sole = c
    if changes >= 3:
        out.append({"kind": "lead-changes", "title": "Back and forth", "who": f"{changes} lead changes",
                    "detail": f"{_names([names[c] for c in held])} each led alone at some point.",
                    "frame": started})
    out = out[:MAX_BEATS]
    for b in out:
        if b.get("frame") is not None:
            b["at"] = int(frames[b["frame"]][0])      # the page says the day and time
    return out


def _side(g: _Game, a: int, h: int) -> str:
    side = results.credited(g.game, h, a)
    return "" if side == results.TIE else team_code(side)


def _final_frame(frames: list[list], gi: int) -> int:
    return next((i for i in range(len(frames) - 1, -1, -1) if frames[i][1] == gi and frames[i][2] == "f"), len(frames) - 1)


def summary(rep: Replay) -> dict:
    """The page's few facts about the replay, beside its file."""
    leads, sole, changes = [_leaders(f[8]) for f in rep.frames], None, 0
    for led in leads:
        if len(led) == 1:
            (c,) = led
            if sole is not None and c != sole:
                changes += 1
            sole = c
    return {"scores": sum(1 for f in rep.frames if f[2] == "s"), "lead_changes": changes}
