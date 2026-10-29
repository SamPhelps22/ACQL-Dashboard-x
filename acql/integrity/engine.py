"""The Integrity Engine's checks.

Every check reads the one Season that repository.load_season builds (stats.xls
first, then the ACQL Dashboard workbook, the pick sheets and the kept ESPN
scores) and recounts it with the pool's own rules - the same functions the
dashboard and the website use (reconcile.check, analytics.week_payouts,
recap._through, poolpage.snapshot). There is no second scoring engine here:
where a check needs a recount it calls the one that exists and compares.

Each problem becomes a Finding with one of these statuses:

    confirmed     two numbers that must agree don't - both are shown
    suspected     looks wrong, but the rules allow it (or only one source says so)
    unavailable   a source couldn't be read, so the check couldn't be made
    settled       a confirmed difference the commissioner has ruled on (rulings.py)
    note          true and worth knowing, not a fault (e.g. a week worked out
                  here because stats.xls doesn't cover it yet - not official)

Nothing here writes to a source, a result, a pick or a money figure. No Qt.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Callable

CONFIRMED, SUSPECTED, UNAVAILABLE, SETTLED, NOTE = "confirmed", "suspected", "unavailable", "settled", "note"
STATUSES = (CONFIRMED, SUSPECTED, UNAVAILABLE, SETTLED, NOTE)
SEVERITIES = ("critical", "high", "medium", "low", "info")
#: How much each open problem takes off the 100-point health score.
PENALTY = {"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0}
#: Money is compared to the cent, allowing the workbook's rounding of a split pot.
CENTS = 0.02

#: Where each kind of number is shown, so a finding names what it affects.
SHOWN = {
    "standings": ("Website: Standings", "Website: Home", "Dashboard: Standings", "Website: Numbers Room"),
    "weekly": ("Website: One week", "Website: Recap", "Website: Time Machine", "Dashboard: Weekly"),
    "money": ("Website: Money", "Dashboard: Winnings"),
    "big_loser": ("Website: Side pools", "Dashboard: Pools"),
    "suicide": ("Website: Side pools (survivor wall)", "Dashboard: Pools"),
    "roster": ("Website: every page", "Dashboard: every page"),
    "results": ("Website: Games", "Website: Recap", "Dashboard: This Week"),
    "history": ("Website: History", "Website: Time Machine", "Dashboard: Standings"),
}


@dataclass(frozen=True)
class Finding:
    check: str
    status: str
    severity: str
    title: str
    detail: str = ""
    week: int | None = None
    coach: str = ""
    field: str = ""
    official: object = None        # the value the official source holds (never changed here)
    computed: object = None        # what the recount or the other source says
    sources: tuple = ()            # the records the numbers came from
    affects: tuple = ()            # pages that show the number
    action: str = ""               # what to do about it
    items: tuple = ()              # (name, official, computed) rows for a grouped finding
    key: str = ""                  # extra identity when check/week/coach/field isn't enough

    @property
    def id(self) -> str:
        raw = "|".join(str(x) for x in (self.check, self.week, self.coach.casefold(), self.field, self.key))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    @property
    def open(self) -> bool:
        return self.status in (CONFIRMED, SUSPECTED, UNAVAILABLE)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["items"] = [list(i) for i in self.items]
        d["sources"], d["affects"] = list(self.sources), list(self.affects)
        return d


@dataclass
class Report:
    run_at: float
    fingerprint: str = ""
    findings: list[Finding] = field(default_factory=list)
    checks: dict[str, dict] = field(default_factory=dict)   # name -> {ran, seconds, verified, error}
    season_year: int = 0
    through_week: int = 0
    official_week: int = 0          # the newest week stats.xls covers
    seconds: float = 0.0

    @property
    def complete(self) -> bool:
        return all(c.get("ran") for c in self.checks.values())

    @property
    def state(self) -> str:
        """verified | attention | discrepancy | incomplete"""
        live = [f for f in self.findings if f.open and f.severity != "info"]
        if any(f.status == CONFIRMED and f.severity in ("critical", "high", "medium") for f in live):
            return "discrepancy"
        if not self.complete or any(f.status == UNAVAILABLE and f.severity in ("critical", "high") for f in live):
            return "incomplete"
        if live:
            return "attention"
        return "verified"

    @property
    def health(self) -> int:
        lost = sum(PENALTY.get(f.severity, 0) for f in self.findings if f.open)
        lost += 15 * sum(1 for c in self.checks.values() if not c.get("ran"))
        return max(0, 100 - lost)

    def counts(self) -> dict:
        out = {s: 0 for s in STATUSES}
        for f in self.findings:
            out[f.status] = out.get(f.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "run_at": self.run_at, "fingerprint": self.fingerprint, "state": self.state,
            "health": self.health, "complete": self.complete, "counts": self.counts(),
            "season_year": self.season_year, "through_week": self.through_week,
            "official_week": self.official_week, "seconds": round(self.seconds, 2),
            "checks": self.checks, "findings": [f.to_dict() for f in self.findings],
        }


# --- what the checks read ------------------------------------------------------

@dataclass
class Context:
    """The season and the few outside readers, swappable in tests. Every reader
    defaults to what is already kept on this computer: nothing is fetched."""
    season: object
    year: int = 0
    now: float = 0.0
    scores: Callable | None = None          # (year, week) -> kept ESPN scores
    checked_at: Callable | None = None      # (year, week) -> when ESPN was last asked
    ruling: Callable | None = None          # (year, week) -> the commissioner's ruling or None
    recount: Callable | None = None         # (season, week, scores=, year=) -> reconcile.Report
    snapshot: Callable | None = None        # (season) -> the website's data
    feeds: Callable | None = None           # () -> sourcehealth.Health list
    baseline: dict = field(default_factory=dict)   # accepted official weekly totals (history.py)

    def __post_init__(self):
        from ..feeds import results
        from ..pool import reconcile, rulings
        self.now = self.now or time.time()
        self.year = self.year or results.season_year(self.season)
        self.scores = self.scores or results.load
        self.checked_at = self.checked_at or results.checked_at
        self.ruling = self.ruling or rulings.get
        self.recount = self.recount or reconcile.check
        if self.snapshot is None:
            from ..ui import poolpage
            self.snapshot = poolpage.snapshot
        if self.feeds is None:
            from .. import sourcehealth
            self.feeds = sourcehealth.every


# --- where a number came from -------------------------------------------------------

def stats_files(season) -> list:
    return sorted((s for s in season.sources if s.kind == "stats" and not s.error),
                  key=lambda s: (s.week or 0, s.modified))


def official_week(season) -> int:
    files = stats_files(season)
    return max((s.week or 0 for s in files), default=0)


def official_source(season, week: int | None = None) -> str:
    """The stats.xls snapshot a week's official numbers were read from (the newest
    one that covers it - newer snapshots win on overlap)."""
    files = stats_files(season)
    covering = [s for s in files if week is None or (s.week or 0) >= week]
    pick = (covering or files)[-1:] if files else []
    return f"{pick[0].path.name} (stats export, week {pick[0].week or '?'})" if pick else "no stats export found"


def workbook_source(season) -> str:
    path = getattr(season, "workbook_path", None)
    return f"{path.name} (ACQL Dashboard workbook)" if path else "no ACQL Dashboard workbook"


def sheet_source(season, week: int) -> str:
    built = "pick sheet" if week in (getattr(season, "sheet_weeks", []) or []) else "workbook grid"
    return f"week {week} picks ({built})"


def results_source(year: int, week: int) -> str:
    return f"ESPN final scores kept for {year} week {week}"


def _name(season, key: str) -> str:
    p = season.players.get(key)
    return p.display if p else key


def _code(team) -> str:
    from ..model.predictions import team_code
    return team_code(team) or ""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).casefold())


# --- the checks -------------------------------------------------------------------------
# Each takes the Context and returns (findings, how many things it verified).

def check_records(ctx: Context) -> tuple[list[Finding], int]:
    """Missing and duplicate records: games, coaches, official weekly scores."""
    from ..repository import _is_phantom
    s, out, n = ctx.season, [], 0
    seen: dict[str, list[str]] = {}
    for key, p in s.players.items():
        n += 1
        seen.setdefault(_norm(p.display), []).append(p.display)
        if _is_phantom(p.display):
            out.append(Finding("records", CONFIRMED, "high", f"“{p.display}” on the roster is not a coach",
                               "A number or team name was read as a coach.", coach=p.display, field="roster",
                               sources=(official_source(s), workbook_source(s)), affects=SHOWN["roster"],
                               action="Fix the row in the file it came from; the app drops these on load."))
    for names in seen.values():
        if len(names) > 1:
            out.append(Finding("records", SUSPECTED, "medium", f"Possible duplicate coach: {' / '.join(names)}",
                               "Two roster entries spell the same name; one coach's season may be split in two.",
                               coach=names[0], field="roster", key="dup", items=tuple((x, "", "") for x in names),
                               sources=(official_source(s), workbook_source(s)), affects=SHOWN["roster"],
                               action="Add the spelling to aliases.json if they are the same person."))
    for number, week in sorted(s.weeks.items()):
        pairs: dict[frozenset, list[int]] = {}
        teams: dict[str, list[int]] = {}
        indexes: dict[int, int] = {}
        for g in week.games:
            n += 1
            indexes[g.index] = indexes.get(g.index, 0) + 1
            pairs.setdefault(frozenset((_code(g.away), _code(g.home))), []).append(g.index)
            for t in (g.away, g.home):
                if _code(t):
                    teams.setdefault(_code(t), []).append(g.index)
        for idx, count in indexes.items():
            if count > 1:
                out.append(Finding("records", CONFIRMED, "high", f"Week {number} has game #{idx} {count} times",
                                   week=number, field="games", key=f"idx{idx}", sources=(sheet_source(s, number),),
                                   affects=SHOWN["weekly"], action="Remove the repeated row from the pick sheet."))
        for pair, where in pairs.items():
            if len(where) > 1 and all(pair):
                out.append(Finding("records", CONFIRMED, "high",
                                   f"Week {number} lists {' @ '.join(sorted(pair))} {len(where)} times",
                                   f"Games {', '.join('#' + str(i) for i in where)}.", week=number, field="games",
                                   key="pair" + "".join(sorted(pair)), sources=(sheet_source(s, number),),
                                   affects=SHOWN["weekly"], action="Remove the repeated game from the pick sheet."))
        for team, where in teams.items():
            if len(set(where)) > 1:
                # a repeated game is reported above; this is a team in two different games
                if len({frozenset((_code(g.away), _code(g.home))) for g in week.games if g.index in where}) > 1:
                    out.append(Finding("records", CONFIRMED, "high", f"Week {number}: {team} plays twice",
                                       f"In games {', '.join('#' + str(i) for i in sorted(set(where)))}.",
                                       week=number, field="games", key="team" + team,
                                       sources=(sheet_source(s, number),), affects=SHOWN["weekly"],
                                       action="Check the slate against the NFL schedule."))
    # Official weekly scores: a week stats.xls scored for most coaches but not for some.
    official_weeks = sorted({w for p in s.players.values() for w in p.official_weeks})
    for w in official_weeks:
        have = [k for k, p in s.players.items() if w in p.official_weeks]
        lacking = [k for k in s.players if k not in have]
        n += len(have)
        if lacking and len(have) >= len(s.players) / 2:
            names = sorted(_name(s, k) for k in lacking)
            out.append(Finding("records", SUSPECTED, "medium",
                               f"Week {w}: {len(names)} coach{'es' if len(names) > 1 else ''} with no official score",
                               ", ".join(names[:8]) + (" …" if len(names) > 8 else "") +
                               ". Either they didn't play that week or a row is missing from the export.",
                               week=w, field="weekly_wins", key="missing",
                               items=tuple((x, None, "") for x in names),
                               sources=(official_source(s, w),), affects=SHOWN["standings"],
                               action="Check the stats export's row for each name."))
    # A coach with an official score but no card in a finished week.
    for number, week in sorted(s.weeks.items()):
        if not week.lines or not week.games or not all(str(g.winner or "").strip() for g in week.games):
            continue
        absent = [k for k, p in s.players.items() if number in p.official_weeks and k not in week.lines]
        if absent:
            out.append(Finding("records", SUSPECTED, "low",
                               f"Week {number}: {len(absent)} official score(s) with no pick card",
                               ", ".join(sorted(_name(s, k) for k in absent)[:8]),
                               week=number, field="lines", key="nocard",
                               sources=(official_source(s, number), sheet_source(s, number)),
                               affects=SHOWN["weekly"], action="The picks can't be shown or recounted for them."))
    # A game ESPN calls final with no winner on file.
    for number, week in sorted(s.weeks.items()):
        if not week.lines:
            continue
        kept = ctx.scores(ctx.year, number) or []
        from ..feeds import results
        for g in week.games:
            score, _ = results.find(kept, g.away, g.home)
            if score is not None and score.final and not str(g.winner or "").strip():
                out.append(Finding("records", SUSPECTED, "medium", f"Week {number}: {g.label} is final but has no winner",
                                   f"ESPN final {score.away_points}-{score.home_points}.", week=number,
                                   field="winner", key=f"g{g.index}",
                                   sources=(results_source(ctx.year, number), sheet_source(s, number)),
                                   affects=SHOWN["results"], action="Reload; if it stays, check the pool line."))
    return out, n


def check_weekly(ctx: Context) -> tuple[list[Finding], int]:
    """Each card adds up, and each week's official totals match a recount of the
    picks against the results under the coded rules (reconcile.check)."""
    from ..config import BIG_LOSER_PICKS
    s, out, n = ctx.season, [], 0
    for number, week in sorted(s.weeks.items()):
        for key, line in week.lines.items():
            n += 1
            total, parts = int(line.total_wins or 0), int(line.regular_wins or 0) + int(line.big_loser_wins or 0)
            if total != parts:
                out.append(Finding("weekly", CONFIRMED, "high", f"Week {number}: {_name(s, key)}'s card doesn't add up",
                                   f"Total {total}, but {line.regular_wins} regular + {line.big_loser_wins} Big Loser = {parts}.",
                                   week=number, coach=_name(s, key), field="total_wins", official=total, computed=parts,
                                   sources=(sheet_source(s, number),), affects=SHOWN["weekly"],
                                   action="Correct the card's total in the source file."))
            if int(line.big_loser_wins or 0) > BIG_LOSER_PICKS:
                out.append(Finding("weekly", CONFIRMED, "high", f"Week {number}: {_name(s, key)} has {line.big_loser_wins} Big Loser wins",
                                   f"The most possible is {BIG_LOSER_PICKS}.", week=number, coach=_name(s, key),
                                   field="big_loser_wins", official=line.big_loser_wins, computed=BIG_LOSER_PICKS,
                                   sources=(sheet_source(s, number),), affects=SHOWN["big_loser"]))
    # Official (stats.xls) against the workbook / pick sheets, as the loader recorded it.
    grouped: dict[tuple, list] = {}
    for c in s.conflicts:
        m = re.match(r"week (\d+)", str(c.field))
        grouped.setdefault((int(m.group(1)) if m else None, str(c.field)), []).append(c)
    for (number, fld), rows in sorted(grouped.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1])):
        n += len(rows)
        ruled = ctx.ruling(ctx.year, number) if number else None
        out.append(_disagreement("weekly", number, fld, ruled, rows=[(c.player, c.authoritative, c.other) for c in rows],
                                 title=f"stats.xls and the workbook disagree on {fld}",
                                 sources=(official_source(s, number), workbook_source(s), sheet_source(s, number or 0)),
                                 affects=SHOWN["weekly"] + SHOWN["standings"]))
    # Official totals against a recount from picks + ESPN's final scores.
    for number in sorted(s.weeks):
        week = s.weeks[number]
        if not week.lines or not any(str(g.winner or "").strip() for g in week.games):
            continue
        try:
            rep = ctx.recount(s, number, scores=ctx.scores(ctx.year, number), year=ctx.year)
        except Exception as exc:  # noqa: BLE001 - one week that can't be recounted is reported, not fatal
            out.append(Finding("weekly", UNAVAILABLE, "medium", f"Week {number} couldn't be recounted",
                               f"{type(exc).__name__}: {exc}", week=number, field="recount",
                               sources=(sheet_source(s, number), results_source(ctx.year, number))))
            continue
        n += rep.checked_games + rep.checked_coaches
        no_final = [g for g in rep.games if not g.espn]
        wrong = [g for g in rep.games if g.espn]
        if no_final:
            out.append(Finding("weekly", UNAVAILABLE, "low", f"Week {number}: {len(no_final)} result(s) can't be checked",
                               "No ESPN final score is kept for: " + ", ".join(g.matchup for g in no_final[:5]),
                               week=number, field="winner", key="nofinal",
                               sources=(results_source(ctx.year, number),), affects=SHOWN["results"],
                               action="Load the scores (Refresh on This Week) and run the checks again."))
        for g in wrong:
            out.append(Finding("weekly", CONFIRMED, "high", f"Week {number}: {g.matchup} winner differs from ESPN",
                               g.why, week=number, field="winner", key=f"g{g.index}", official=g.stored,
                               computed=g.espn, sources=(sheet_source(s, number), results_source(ctx.year, number)),
                               affects=SHOWN["results"] + SHOWN["weekly"],
                               action="Check the graded sheet and the pool line for this game."))
        if rep.coaches and no_final:
            # Without every final score the recount is short by design: not evidence.
            out.append(Finding("weekly", UNAVAILABLE, "medium",
                               f"Week {number}: official totals can't be recounted yet",
                               f"{len(no_final)} of {len(week.games)} results have no ESPN final score kept, so a "
                               f"recount would differ for {len(rep.coaches)} coach(es) for that reason alone.",
                               week=number, field="recount", key="partial",
                               sources=(results_source(ctx.year, number),), affects=SHOWN["weekly"],
                               action="Load the scores and run the checks again."))
        elif rep.coaches:
            ruled = ctx.ruling(ctx.year, number)
            out.append(_disagreement("weekly", number, "recount", ruled,
                                     rows=[(c.name, c.official, c.recount) for c in rep.coaches],
                                     title="official totals differ from a recount of the picks",
                                     sources=(official_source(s, number), sheet_source(s, number),
                                              results_source(ctx.year, number)),
                                     affects=SHOWN["weekly"] + SHOWN["standings"]))
    return out, n


def _disagreement(check, number, fld, ruled, *, rows, title, sources, affects) -> Finding:
    from ..pool import rulings
    shown = "; ".join(f"{name} {a}→{b}" for name, a, b in rows[:6]) + (" …" if len(rows) > 6 else "")
    head = f"Week {number}: " if number else ""
    if ruled:
        return Finding(check, SETTLED, "info", f"{head}{title} ({len(rows)} coaches) - ruled",
                       f"{rulings.words(ruled)}. {shown}", week=number, field=fld, items=tuple(rows),
                       sources=sources, affects=affects, action="Nothing to do; the ruling stands.")
    return Finding(check, CONFIRMED, "high", f"{head}{title} ({len(rows)} coaches)",
                   f"Official → other: {shown}. The official numbers are kept until the commissioner rules.",
                   week=number, field=fld, items=tuple(rows), sources=sources, affects=affects,
                   action="Record a ruling for the week in the Integrity Center (official or recount stands).")


def check_standings(ctx: Context) -> tuple[list[Finding], int]:
    """Season totals, places, games behind and the tie rule, recounted from the weekly scores."""
    s, out, n = ctx.season, [], 0
    last = s.current_week
    people = [p for p in s.players.values()]
    for p in people:
        n += 1
        expected = sum(v for w, v in p.weekly_wins.items() if w <= last)
        if int(p.wins or 0) != expected:
            out.append(Finding("standings", CONFIRMED, "critical", f"{p.display}'s season wins don't match their weeks",
                               f"Standings say {p.wins}; weeks 1-{last} add up to {expected}.", coach=p.display,
                               field="wins", official=p.wins, computed=expected,
                               items=tuple((f"week {w}", v, "") for w, v in sorted(p.weekly_wins.items())),
                               sources=(official_source(s),), affects=SHOWN["standings"],
                               action="Check the export's W column against its weekly columns."))
    placed = sorted((p for p in people if p.pos is not None), key=lambda p: p.pos)
    for a, b in zip(placed, placed[1:]):
        n += 1
        if a.wins < b.wins:
            out.append(Finding("standings", CONFIRMED, "high", f"{b.display} (#{b.pos}) has more wins than {a.display} (#{a.pos})",
                               f"{b.wins} against {a.wins}.", coach=b.display, field="pos", key=a.display,
                               official=b.pos, computed=a.pos, sources=(official_source(s),), affects=SHOWN["standings"],
                               action="Places follow wins; check the Pos column."))
        elif a.wins == b.wins and a.prev_pos is not None and b.prev_pos is not None and a.prev_pos > b.prev_pos:
            out.append(Finding("standings", SUSPECTED, "low", f"Tie order: {a.display} placed above {b.display}",
                               f"Both on {a.wins}; the tie rule puts whoever was higher last week first "
                               f"(#{b.prev_pos} {b.display} before #{a.prev_pos} {a.display}).",
                               coach=a.display, field="pos", key="tie" + b.display, official=a.pos, computed=b.pos,
                               sources=(official_source(s),), affects=SHOWN["standings"]))
    leader = max((p.wins for p in people), default=0)
    for p in people:
        if p.games_behind and abs(float(p.games_behind) - (leader - p.wins)) > 1e-6:
            n += 1
            out.append(Finding("standings", CONFIRMED, "medium", f"{p.display}'s games behind is off",
                               f"Shown {p.games_behind:g}; leader {leader} - {p.wins} = {leader - p.wins}.",
                               coach=p.display, field="games_behind", official=p.games_behind,
                               computed=leader - p.wins, sources=(official_source(s),), affects=SHOWN["standings"]))
    return out, n


def check_money(ctx: Context) -> tuple[list[Finding], int]:
    """Each week's pot is paid out in full, split evenly on a tie, and every
    coach's net is paid + won. Uses analytics.week_owed - the pool's payout rule."""
    from .. import analytics
    s, out, n = ctx.season, [], 0
    computed = set(getattr(s, "computed_winnings", []) or [])
    for number, week in sorted(s.weeks.items()):
        paid = {k: p.weekly_winnings.get(number) for k, p in s.players.items() if p.weekly_winnings.get(number)}
        if not paid or not week.lines:
            continue
        # A week stats.xls scored is priced on its official scores (they stand
        # over the cards when the two differ); later weeks on the cards.
        official = {k: p.weekly_wins[number] for k, p in s.players.items()
                    if number in p.official_weeks and number in p.weekly_wins}
        if official:
            from types import SimpleNamespace
            week = SimpleNamespace(lines={k: SimpleNamespace(total_wins=v) for k, v in official.items()})
        owed = analytics.week_owed(week)
        pot = sum(owed.values())
        winners = sorted(k for k, behind in owed.items() if behind == 0)
        n += len(owed)
        src = ("computed here from the scores" if number in computed else workbook_source(s), sheet_source(s, number))
        status = SUSPECTED if number in computed else CONFIRMED
        if abs(sum(paid.values()) - pot) > CENTS * max(1, len(winners)):
            why = (" The payout was worked out here from the pick cards (analytics.fill_winnings)."
                   if number in computed else " The payout is the figure the workbook holds; it is kept as is.")
            carded = set(getattr(s.weeks.get(number), "lines", {}) or {})
            uncarded = [_name(s, k) for k in official if k not in carded]
            if uncarded:
                why += f" Official score with no pick card: {', '.join(uncarded)} - their games behind are left out."
            out.append(Finding("money", CONFIRMED, "high", f"Week {number}: payouts don't equal the pot",
                               f"Paid ${sum(paid.values()):.2f} to {len(paid)} coach(es); the pot from the official "
                               f"scores (everyone's games behind the top card, {len(winners)} on top) is ${pot:.2f}.{why}",
                               week=number, field="weekly_winnings", official=round(sum(paid.values()), 2),
                               computed=round(pot, 2), items=tuple((_name(s, k), v, "") for k, v in sorted(paid.items())),
                               sources=src, affects=SHOWN["money"], action="Check the week's money cells."))
        strays = [k for k in paid if k not in winners]
        if strays:
            out.append(Finding("money", status, "high", f"Week {number}: paid a coach without the top card",
                               ", ".join(_name(s, k) for k in strays), week=number, field="weekly_winnings", key="stray",
                               items=tuple((_name(s, k), paid[k], 0) for k in strays), sources=src, affects=SHOWN["money"]))
        shares = {round(paid.get(k, 0), 2) for k in winners}
        if len(winners) > 1 and len(shares) > 1:
            out.append(Finding("money", CONFIRMED, "high", f"Week {number}: a tied pot wasn't split evenly",
                               f"{len(winners)} coaches tied on the top card; each should get ${pot / len(winners):.2f}.",
                               week=number, field="weekly_winnings", key="tie",
                               items=tuple((_name(s, k), paid.get(k, 0), round(pot / len(winners), 2)) for k in winners),
                               sources=src, affects=SHOWN["money"]))
    totals_from = official_source(s) if not getattr(s, "computed_totals", False) else "computed here from the scores"
    for p in s.players.values():
        if not (p.points_won or p.points_paid or p.net_points):
            continue
        n += 1
        if abs((p.points_paid + p.points_won) - p.net_points) > CENTS:
            out.append(Finding("money", CONFIRMED, "high", f"{p.display}'s net isn't paid + won",
                               f"-PTS {p.points_paid:.2f} + +PTS {p.points_won:.2f} = {p.points_paid + p.points_won:.2f}, "
                               f"net shown {p.net_points:.2f}.", coach=p.display, field="net_points",
                               official=p.net_points, computed=round(p.points_paid + p.points_won, 2),
                               sources=(totals_from,), affects=SHOWN["money"],
                               action="The official figure is kept; correct it in the stats export if wrong."))
    if any(p.has_totals for p in s.players.values()):
        n += 1
        total_net = sum(p.net_points for p in s.players.values())
        expected = -s.buy_in * len(s.players) + sum(p.pie_splits for p in s.players.values())
        if abs(total_net - expected) > CENTS * len(s.players):
            out.append(Finding("money", SUSPECTED, "medium", "The pool's money doesn't balance",
                               f"Everyone's net adds up to ${total_net:.2f}; the buy-ins and Pie Splits say ${expected:.2f}. "
                               "Weekly pots move money between coaches and should cancel out.",
                               field="net_points", key="balance", official=round(total_net, 2),
                               computed=round(expected, 2), sources=(totals_from,), affects=SHOWN["money"],
                               action="Look for a week whose pot wasn't fully paid or a buy-in counted twice."))
    return out, n


def check_side_pools(ctx: Context) -> tuple[list[Finding], int]:
    """Big Loser hits against the week's blowouts; survivors against their picks."""
    from ..feeds import results
    s, out, n = ctx.season, [], 0
    for number, week in sorted(s.weeks.items()):
        listed = s.big_losers_by_week.get(number)
        if listed is None:
            continue
        possible = len({_code(t) for t in listed if _code(t)})
        for key, line in week.lines.items():
            n += 1
            if int(line.big_loser_wins or 0) > possible:
                out.append(Finding("side_pools", CONFIRMED, "medium",
                                   f"Week {number}: {_name(s, key)} has more Big Loser wins than there were big losers",
                                   f"{line.big_loser_wins} wins, {possible} team(s) lost by {results.BLOWOUT}+.",
                                   week=number, coach=_name(s, key), field="big_loser_wins",
                                   official=line.big_loser_wins, computed=possible,
                                   sources=(official_source(s, number), sheet_source(s, number)),
                                   affects=SHOWN["big_loser"]))
    for p in s.players.values():
        if p.big_loser_points and p.weekly_big_loser:
            n += 1
            weeks_sum = sum(p.weekly_big_loser.values())
            if abs(p.big_loser_points - weeks_sum) > 1e-6:
                out.append(Finding("side_pools", SUSPECTED, "low", f"{p.display}'s Big Loser points don't match their weeks",
                                   f"Season {p.big_loser_points:g}, weeks add up to {weeks_sum}.", coach=p.display,
                                   field="big_loser_points", official=p.big_loser_points, computed=weeks_sum,
                                   sources=(official_source(s),), affects=SHOWN["big_loser"]))
    start = int(getattr(s, "suicide_restart", 0) or 0)
    for p in s.players.values():
        if not p.suicide_alive:
            continue
        used: dict[str, int] = {}
        for w, team in sorted(p.suicide_picks.items()):
            if w < start or w not in s.weeks:
                continue
            code = _code(team)
            week = s.weeks[w]
            game = next((g for g in week.games if code and code in (_code(g.home), _code(g.away))), None)
            if game is None or not str(game.winner or "").strip():
                continue
            n += 1
            if code in used:
                out.append(Finding("side_pools", CONFIRMED, "medium", f"{p.display} used {team} twice in one survivor round",
                                   f"Weeks {used[code]} and {w}.", week=w, coach=p.display, field="suicide_picks",
                                   key="twice" + code, sources=(official_source(s, w), sheet_source(s, w)),
                                   affects=SHOWN["suicide"]))
            used[code] = w
            if _code(game.winner) != code:
                out.append(Finding("side_pools", CONFIRMED, "high", f"{p.display} is shown alive but {team} lost in week {w}",
                                   f"Winner on file: {game.winner}.", week=w, coach=p.display, field="suicide_alive",
                                   official=True, computed=False, sources=(official_source(s, w), sheet_source(s, w)),
                                   affects=SHOWN["suicide"], action="Check the survivor column in the stats export."))
    return out, n


def check_cross_page(ctx: Context) -> tuple[list[Finding], int]:
    """The website's numbers (poolpage.snapshot, what gets published) against the
    season the dashboard shows: wins, places, weekly scores and money."""
    s, out, n = ctx.season, [], 0
    data = ctx.snapshot(s)
    by_name = {row["name"]: row for row in data.get("players", [])}
    through = int(data.get("through_week") or 0)
    official = through and through == (s.current_week or through)
    diffs: dict[str, list] = {"wins": [], "place": [], "weekly": [], "net": []}
    for p in s.players.values():
        row = by_name.get(p.display)
        if row is None:
            out.append(Finding("cross_page", CONFIRMED, "high", f"{p.display} is missing from the website",
                               coach=p.display, field="players", sources=("website data (poolpage.snapshot)",),
                               affects=SHOWN["roster"]))
            continue
        n += 1
        if official and int(row["wins"]) != int(p.wins):
            diffs["wins"].append((p.display, p.wins, row["wins"]))
        if official and p.pos is not None and row.get("place") != p.pos:
            diffs["place"].append((p.display, p.pos, row.get("place")))
        for w, shown in (row.get("weekly") or {}).items():
            w = int(w)
            if w in p.official_weeks and int(shown) != int(p.weekly_wins.get(w, shown)):
                diffs["weekly"].append((f"{p.display} wk {w}", p.weekly_wins.get(w), shown))
        if official and data.get("money") and row.get("net") is not None and p.has_totals:
            if abs(float(row["net"]) - p.net_points) > CENTS:
                diffs["net"].append((p.display, p.net_points, row["net"]))
    extra = sorted(set(by_name) - {p.display for p in s.players.values()})
    if extra:
        out.append(Finding("cross_page", CONFIRMED, "high", "The website shows coaches the season doesn't have",
                           ", ".join(extra), field="players", key="extra", sources=("website data (poolpage.snapshot)",),
                           affects=SHOWN["roster"]))
    words = {"wins": ("season wins", "standings"), "place": ("places", "standings"),
             "weekly": ("weekly scores", "weekly"), "net": ("net money", "money")}
    for kind, rows in diffs.items():
        if rows:
            what, shown = words[kind]
            out.append(Finding("cross_page", CONFIRMED, "high" if kind != "place" else "medium",
                               f"The website and the dashboard show different {what} ({len(rows)})",
                               "Dashboard (official) → website: " + "; ".join(f"{a} {b}→{c}" for a, b, c in rows[:6]),
                               field=kind, items=tuple(rows), sources=(official_source(s), "website data (poolpage.snapshot)"),
                               affects=SHOWN[shown], action="Both should come from the same season; reload and re-run."))
    dash = [p.display for p in s.ordered_players()]
    site = [r["name"] for r in data.get("players", [])]
    if official and dash != site:
        n += 1
        first = next((i for i, (a, b) in enumerate(zip(dash, site)) if a != b), min(len(dash), len(site)))
        out.append(Finding("cross_page", SUSPECTED, "low", "The standings order differs between dashboard and website",
                           f"First difference at row {first + 1}: dashboard {dash[first:first + 1]}, website {site[first:first + 1]}.",
                           field="order", sources=(official_source(s), "website data (poolpage.snapshot)"),
                           affects=SHOWN["standings"]))
    return out, n


def check_freshness(ctx: Context) -> tuple[list[Finding], int]:
    """Sources that are missing, unreadable or stale - and weeks that are worked
    out here rather than official."""
    s, out, n = ctx.season, [], 0
    files = stats_files(s)
    n += len(s.sources)
    if not files:
        out.append(Finding("freshness", UNAVAILABLE, "critical", "No stats export (stats.xls) was found",
                           "The official standings source is missing; every total shown is worked out here.",
                           field="stats", sources=("data folders",), affects=SHOWN["standings"],
                           action="Put the commissioner's latest stats.xls in the project folder."))
    for bad in (src for src in s.sources if src.error):
        out.append(Finding("freshness", UNAVAILABLE, "high", f"{bad.path.name} couldn't be read", bad.error,
                           field="source", key=bad.path.name, sources=(bad.path.name,), affects=SHOWN["roster"]))
    for w in s.warnings:
        if "could not be read" in w:
            out.append(Finding("freshness", UNAVAILABLE, "high", "A source file couldn't be read", w,
                               field="source", key=w[:60], sources=(w.split(":")[0],)))
    if not getattr(s, "workbook_path", None):
        out.append(Finding("freshness", UNAVAILABLE, "low", "The ACQL Dashboard workbook isn't in the folder",
                           "The app runs without it; its cross-check against stats.xls is skipped.",
                           field="workbook", sources=("ACQL Dashboard.xlsx",)))
    stats_wk = official_week(s)
    rolled = sorted(w for w in s.weeks if stats_wk < w <= (s.current_week or 0) and s.weeks[w].lines)
    if rolled:
        out.append(Finding("freshness", NOTE, "info",
                           f"Week{'s' if len(rolled) > 1 else ''} {', '.join(map(str, rolled))} worked out here, not yet official",
                           f"The newest stats export covers week {stats_wk}. Later standings are recounted from the "
                           "picks and ESPN's scores and are shown as provisional until the export arrives.",
                           field="stats", key="rolled", sources=(official_source(s),), affects=SHOWN["standings"]))
    # The kept scores for a week being played, gone stale while games are on.
    for number in sorted(s.weeks, reverse=True):
        kept = ctx.scores(ctx.year, number) or []
        if not kept:
            continue
        n += 1
        live = [sc for sc in kept if not sc.final and not sc.called_off and sc.kickoff and sc.kickoff < ctx.now]
        at = ctx.checked_at(ctx.year, number)
        if live and (at is None or ctx.now - at > 3 * 3600):
            out.append(Finding("freshness", SUSPECTED, "medium", f"Week {number}'s scores may be stale",
                               f"{len(live)} game(s) kicked off but aren't final, and ESPN was last asked "
                               f"{'never' if at is None else f'{(ctx.now - at) / 3600:.0f} hours ago'}.",
                               week=number, field="scores", sources=(results_source(ctx.year, number),),
                               affects=SHOWN["results"], action="Refresh scores; the check re-runs after."))
        break
    for h in ctx.feeds() or []:
        n += 1
        failing = h.last_bad and (h.last_good is None or h.last_bad > h.last_good)
        if failing and ctx.now - (h.last_good or 0) > 2 * 86400:
            out.append(Finding("freshness", UNAVAILABLE, "medium", f"{h.name} has been failing",
                               f"Last good answer: {'never' if not h.last_good else time.strftime('%Y-%m-%d %H:%M', time.localtime(h.last_good))}. "
                               f"{h.last_note}", field="feed", key=h.source, sources=(h.name,)))
    return out, n


def check_history(ctx: Context) -> tuple[list[Finding], int]:
    """Official weekly scores against the totals accepted on earlier runs: a
    historical record that changes is reported, never silently taken."""
    s, out, n = ctx.season, [], 0
    accepted = (ctx.baseline or {}).get(str(ctx.year)) or {}
    current = official_scores(s)
    for wk, then in sorted(accepted.items(), key=lambda kv: int(kv[0])):
        now = current.get(wk, {})
        changed = [(name, v, now.get(name)) for name, v in sorted(then.items()) if now.get(name) != v]
        n += len(then)
        if not changed:
            continue
        gone = [c for c in changed if c[2] is None]
        moved = [c for c in changed if c[2] is not None]
        if moved:
            out.append(Finding("history", CONFIRMED, "critical", f"Week {wk}'s official scores changed since they were accepted",
                               "Accepted → now: " + "; ".join(f"{a} {b}→{c}" for a, b, c in moved[:6]),
                               week=int(wk), field="weekly_wins", key="moved", official=None, items=tuple(moved),
                               sources=(official_source(s, int(wk)),), affects=SHOWN["history"] + SHOWN["standings"],
                               action="If the commissioner corrected the week, accept the change in the Integrity Center; "
                                      "otherwise an older or wrong export was loaded."))
        if gone:
            out.append(Finding("history", CONFIRMED, "high", f"Week {wk}: {len(gone)} accepted score(s) disappeared",
                               ", ".join(a for a, _, _ in gone[:8]), week=int(wk), field="weekly_wins", key="gone",
                               items=tuple(gone), sources=(official_source(s, int(wk)),), affects=SHOWN["history"]))
    return out, n


def official_scores(season) -> dict[str, dict[str, int]]:
    """{week: {coach: official total}} for every week stats.xls covers."""
    out: dict[str, dict[str, int]] = {}
    for p in season.players.values():
        for w in p.official_weeks:
            if w in p.weekly_wins:
                out.setdefault(str(w), {})[p.display] = int(p.weekly_wins[w])
    return out


CHECKS: tuple[tuple[str, str, Callable], ...] = (
    ("records", "Missing and duplicate records", check_records),
    ("weekly", "Weekly scores and recount", check_weekly),
    ("standings", "Standings, totals and ties", check_standings),
    ("money", "Weekly pots and money", check_money),
    ("side_pools", "Big Loser and survivor pools", check_side_pools),
    ("cross_page", "Website against dashboard", check_cross_page),
    ("freshness", "Sources and freshness", check_freshness),
    ("history", "Historical records", check_history),
)


def run(ctx: Context, *, only: tuple[str, ...] = ()) -> Report:
    """Every check. One that crashes is recorded as not run (the report is then
    'incomplete'), never as passed."""
    started = time.perf_counter()
    rep = Report(run_at=ctx.now, season_year=ctx.year, through_week=int(ctx.season.current_week or 0),
                 official_week=official_week(ctx.season))
    for name, label, fn in CHECKS:
        if only and name not in only:
            continue
        t = time.perf_counter()
        try:
            found, verified = fn(ctx)
            rep.findings.extend(found)
            rep.checks[name] = {"label": label, "ran": True, "verified": verified,
                                "seconds": round(time.perf_counter() - t, 3), "error": ""}
        except Exception as exc:  # noqa: BLE001 - a broken check is a result
            where = traceback.extract_tb(exc.__traceback__)[-1]
            err = f"{type(exc).__name__}: {exc} ({where.filename.rsplit(chr(92), 1)[-1]}, line {where.lineno})"
            rep.checks[name] = {"label": label, "ran": False, "verified": 0,
                                "seconds": round(time.perf_counter() - t, 3), "error": err}
            rep.findings.append(Finding(name, UNAVAILABLE, "high", f"The “{label}” check couldn't run", err,
                                        field="check", action="Fix the cause and run the checks again."))
    order = {s: i for i, s in enumerate(SEVERITIES)}
    stat = {CONFIRMED: 0, UNAVAILABLE: 1, SUSPECTED: 2, NOTE: 3, SETTLED: 4}
    rep.findings.sort(key=lambda f: (stat.get(f.status, 9), order.get(f.severity, 9), f.week or 0, f.title))
    rep.seconds = time.perf_counter() - started
    return rep


def publish_gate(report: Report | dict | None) -> list[str]:
    """Why new numbers shouldn't go out as official, or [] when nothing stands in
    the way. Unruled disagreements in the standings, money or history - and a
    run that didn't complete - each give a reason."""
    if report is None:
        return ["the integrity checks haven't run"]
    d = report.to_dict() if isinstance(report, Report) else report
    out = []
    if not d.get("complete"):
        out.append("the last integrity run didn't complete")
    for f in d.get("findings", []):
        if f["status"] == CONFIRMED and f["severity"] in ("critical", "high") and \
                f["check"] in ("standings", "money", "history", "cross_page"):
            out.append(f["title"])
    return out


def fingerprint(season) -> str:
    """A short hash of everything the checks read: the source files, the kept
    scores and the rulings. Same hash, same answer - no need to run again."""
    from .. import store
    parts = [(str(src.path), src.modified, src.digest, src.error) for src in season.sources]
    parts.append(sorted(getattr(season, "sheet_weeks", []) or []))
    for kind in ("results", "rulings", "picks", "pool-lines", "suicide-rounds"):
        try:
            items = store.items(kind)
        except Exception:  # noqa: BLE001 - an unreadable store changes the hash, which re-runs
            items = {"unreadable": kind}
        parts.append([kind, hashlib.sha1(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest()])
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]
