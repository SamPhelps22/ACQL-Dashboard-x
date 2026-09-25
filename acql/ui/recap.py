"""The week in one picture, for the group chat.

Most of the pool will never open the dashboard. What they want on a Monday
night is who won, what it paid, where everyone stands, and which game sank
them - so this lays exactly that out as a single portrait image, the shape a
phone shows best, that can be pasted straight into a chat.

`build()` works out what to say from a Season and knows nothing about
drawing; `render()` draws it with matplotlib alone (no Qt), so the same
picture can be made by the app, by a script, or by a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import Season, same_team
from ..predictions import display_team
from .theme import Palette, mix

#: How many places of the standings the picture shows.
STANDINGS_SHOWN = 10
#: How many upsets it lists, and how few of the pool must have had the game.
UPSETS_SHOWN = 3
UPSET_SHARE = 0.5
#: A correct pick held by at most this share of the pool is a lone-wolf hit.
LONE_WOLF_SHARE = 0.2

WIDTH_IN, DPI = 7.2, 150          # 1080 pixels wide; as tall as it needs
DOT = "·"
UP, DOWN, DASH = "▲", "▼", "–"


@dataclass(frozen=True)
class Standing:
    place: int
    name: str
    wins: int
    move: int | None          # places gained this week (negative = dropped)
    won_week: bool


@dataclass(frozen=True)
class Award:
    title: str
    who: str
    detail: str


@dataclass(frozen=True)
class Upset:
    matchup: str
    winner: str
    right: int
    entrants: int
    line: str


@dataclass(frozen=True)
class Recap:
    season_title: str
    week: int
    entrants: int
    games: int
    average: float
    winners: list[str]
    top_score: int
    payout_each: float
    standings: list[Standing] = field(default_factory=list)
    awards: list[Award] = field(default_factory=list)
    upsets: list[Upset] = field(default_factory=list)
    pool_average: float = 0.0            # average season total through this week
    pool_above: int = 0                  # coaches above that average
    pool_below: int = 0
    crowd_right: int = 0                 # games the pool's majority got right
    crowd_games: int = 0
    killer: str = ""                     # the team that knocked out most suicide coaches
    killed: int = 0                      # coaches it knocked out
    killer_tied: list[str] = field(default_factory=list)
    suicide_left: int | None = None      # coaches still alive after the week
    suicide_picks: int = 0               # coaches who made a suicide pick this week

    @property
    def headline(self) -> str:
        if not self.winners:
            return "No scores yet"
        if len(self.winners) == 1:
            return self.winners[0]
        if len(self.winners) <= 3:
            return ", ".join(self.winners[:-1]) + " & " + self.winners[-1]
        return f"{len(self.winners)}-way tie"

    @property
    def score_line(self) -> str:
        text = f"{self.top_score} wins"
        if self.payout_each:
            text += f"  {DOT}  ${self.payout_each:,.0f}"
            if len(self.winners) > 1:
                text += " each"
        return text


# ---- working out what to say ----------------------------------------------
def _names(season: Season, keys) -> list[str]:
    out = []
    for key in keys:
        player = season.players.get(key)
        out.append(player.display if player else str(key))
    return out


def _places(totals: dict[str, int]) -> dict[str, int]:
    """Competition ranking: 1, 2, 2, 4."""
    order = sorted(totals.values(), reverse=True)
    return {key: order.index(value) + 1 for key, value in totals.items()}


def _through(season: Season, week: int) -> dict[str, int]:
    totals: dict[str, int] = {}
    for number, wk in season.weeks.items():
        if number > week:
            continue
        for key, line in wk.lines.items():
            totals[key] = totals.get(key, 0) + (line.total_wins or 0)
    return totals


def _list(names: list[str], most: int = 2) -> str:
    if len(names) <= most:
        return ", ".join(names)
    return ", ".join(names[:most]) + f" +{len(names) - most} more"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


DEAD_MARKERS = {"dead", "out", "x", "eliminated"}


def _suicide_lost(season: Season, week_number: int, key: str, team: str) -> bool | None:
    """Did this coach's suicide pick lose? None when the files can't say.

    The suicide pool plays by the pool's lines: a team in a lined game has
    to be credited with it - a favourite must win by more than the line, an
    underdog survives by covering it. The Result row already records the
    credited side, so the pick lost exactly when its team isn't the one
    recorded. Before the result is in, the next week's sheet can still say
    (DEAD there means out here; a new team means survived).
    """
    from ..predictions import team_code

    week = season.weeks[week_number]
    game = next(
        (g for g in week.games if g.played and (same_team(team, g.home) or same_team(team, g.away))),
        None,
    )
    if game is not None:
        return not same_team(team, game.winner)

    nxt = season.weeks.get(week_number + 1)
    later = nxt.lines.get(key) if nxt is not None else None
    if later is not None:
        text = (later.suicide_pick or "").strip()
        if later.suicide_out or text.casefold() in DEAD_MARKERS:
            return True
        if team_code(text):
            return False
    return None


def build(season: Season, week_number: int) -> Recap | None:
    """Everything the picture says about one week, or None if it is unscored."""
    from .. import analytics, luck  # heavy; only needed here
    from ..predictions import team_code

    week = season.weeks.get(week_number)
    if week is None or not week.lines or not week.scored:
        return None
    lines = week.lines
    entrants = len(lines)
    scores = {key: line.total_wins or 0 for key, line in lines.items()}
    top = max(scores.values())
    winner_keys = sorted(k for k, v in scores.items() if v == top)
    payouts = analytics.week_payouts(week)
    paid = [payouts.get(k, 0.0) for k in winner_keys if payouts.get(k)]

    # standings through this week, and how they moved
    now = _through(season, week_number)
    before = _through(season, week_number - 1) if week_number > 1 else {}
    place_now = _places(now)
    place_before = _places(before) if before else {}
    order = sorted(now, key=lambda k: (place_now[k], _names(season, [k])[0].casefold()))
    standings = [
        Standing(
            place=place_now[k],
            name=_names(season, [k])[0],
            wins=now[k],
            move=(place_before[k] - place_now[k]) if k in place_before else None,
            won_week=k in winner_keys,
        )
        for k in order[:STANDINGS_SHOWN]
    ]

    played = [g for g in week.games if g.played]
    right = {g.index: week.correct_count(g.index) for g in played}

    # The winner has the banner; the awards are for everyone else's story.
    awards: list[Award] = []

    rarest: tuple[int, str, list[str]] | None = None
    for game in played:
        count = right[game.index]
        if not count or count > LONE_WOLF_SHARE * entrants:
            continue
        who = sorted(
            k for k, line in lines.items()
            if same_team(line.correct_picks.get(game.index), game.winner)
        )
        if rarest is None or count < rarest[0]:
            rarest = (count, display_team(game.winner), who)
    if rarest:
        count, team, who = rarest
        awards.append(Award(
            "Lone wolf", _list(_names(season, who)),
            f"only {count} of {entrants} had {team}",
        ))

    if place_before:
        moves = {k: place_before[k] - place_now[k] for k in place_now if k in place_before}
        best = max(moves.values(), default=0)
        if best >= 2:
            climbers = sorted(k for k, v in moves.items() if v == best)
            awards.append(Award(
                "Biggest climber", _list(_names(season, climbers)),
                f"up {best} places, now {_ordinal(place_now[climbers[0]])}",
            ))

    loser_best = max((line.big_loser_wins or 0 for line in lines.values()), default=0)
    if loser_best:
        kings = sorted(k for k, line in lines.items() if (line.big_loser_wins or 0) == loser_best)
        awards.append(Award(
            "Big Loser", _list(_names(season, kings)),
            f"{loser_best} big-loser point{'s' if loser_best != 1 else ''} this week",
        ))

    # the suicide pool: which team knocked out the most coaches this week
    knocked: dict[str, int] = {}
    pickers = 0
    for key, line in lines.items():
        team = (line.suicide_pick or "").strip()
        if not team_code(team):
            continue
        pickers += 1
        if _suicide_lost(season, week_number, key, team):
            code = team_code(team)
            knocked[code] = knocked.get(code, 0) + 1
    killer, killed, tied = "", 0, []
    if knocked:
        killed = max(knocked.values())
        top_teams = sorted((c for c, n in knocked.items() if n == killed), key=display_team)
        killer = display_team(top_teams[0])
        tied = [display_team(c) for c in top_teams[1:]]

    low = min(scores.values())
    if low < top:
        rough = sorted(k for k, v in scores.items() if v == low)
        awards.append(Award(
            "Rough week", _list(_names(season, rough)),
            f"{low} wins - there's always next week",
        ))

    upsets = []
    for game in sorted(played, key=lambda g: (right[g.index], g.index)):
        if right[game.index] > UPSET_SHARE * entrants or len(upsets) >= UPSETS_SHOWN:
            break
        line = getattr(game, "line", None)
        fav = getattr(game, "line_favourite", "")
        upsets.append(Upset(
            matchup=game.label,
            winner=display_team(game.winner),
            right=right[game.index],
            entrants=entrants,
            line=f"{display_team(fav)} by {line:g}" if line is not None and fav else "",
        ))

    # the pool average: every coach's season total through this week, the
    # same number as the Overview's Pool Average tile
    totals = list(now.values())
    pool_average = sum(totals) / len(totals) if totals else 0.0
    crowd_right, crowd_games = luck.crowd_record(week)

    return Recap(
        pool_average=pool_average,
        pool_above=sum(1 for t in totals if t > pool_average),
        pool_below=sum(1 for t in totals if t < pool_average),
        crowd_right=crowd_right,
        crowd_games=crowd_games,
        killer=killer,
        killed=killed,
        killer_tied=tied,
        suicide_left=(pickers - sum(knocked.values())) if pickers else None,
        suicide_picks=pickers,
        season_title=getattr(season, "title", "") or "ACQL",
        week=week_number,
        entrants=entrants,
        games=len(week.games),
        average=sum(scores.values()) / entrants,
        winners=_names(season, winner_keys),
        top_score=top,
        payout_each=paid[0] if paid else 0.0,
        standings=standings,
        awards=awards,
        upsets=upsets,
    )


# ---- drawing it -----------------------------------------------------------
def _font() -> str:
    from matplotlib import font_manager

    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"):
        if name in have:
            return name
    return "sans-serif"


def default_path(folder: Path, recap: Recap) -> Path:
    return Path(folder) / f"ACQL week {recap.week} recap.png"


def _suicide_tile(recap: Recap) -> tuple[str, str, str]:
    """(label, value, note) for the suicide pool's worst team of the week."""
    if not recap.suicide_picks:
        return "SUICIDE KILLER", "-", "no suicide picks this week"
    if not recap.killer:
        return "SUICIDE KILLER", "Nobody", f"all {recap.suicide_picks} survived"
    from ..predictions import team_code

    # The tile is narrow: about 23 characters of note fit.
    if recap.killer_tied:
        others = (team_code(recap.killer_tied[0]).upper() or _clip(recap.killer_tied[0], 8)
                  if len(recap.killer_tied) == 1 else f"{len(recap.killer_tied)} more")
        note = f"{recap.killed} out {DOT} tied with {others}"
    elif recap.suicide_left is not None:
        note = f"knocked out {recap.killed} {DOT} {recap.suicide_left} left"
    else:
        note = f"knocked out {recap.killed}"
    return "SUICIDE KILLER", _clip(recap.killer, 13), note


def _clip(text: str, most: int) -> str:
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def render(recap: Recap, path: str | Path, palette: Palette) -> Path:
    """Draw the recap to a PNG and return where it went.

    The picture is exactly as tall as what it has to say: the sections are
    measured first and the canvas cut to fit, so a quiet week is a short
    image rather than a long one with a blank bottom half.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyBboxPatch

    p = palette
    font = _font()
    W = WIDTH_IN * DPI
    margin, gap = 54, 26
    col_w = (W - 2 * margin - gap) / 2

    # ---- measure ----
    header_h = 128
    winner_h = 150
    strip_h = 112
    stand_h = 76 + len(recap.standings) * 44 + 16
    award_h = 76 + max(1, len(recap.awards)) * 96
    body_h = max(stand_h, award_h)
    up_row = 72
    upsets_h = 76 + len(recap.upsets) * up_row if recap.upsets else 0
    footer_h = 70
    H = (header_h + winner_h + gap + strip_h + gap + body_h + gap
         + (upsets_h + gap if upsets_h else 0) + footer_h)

    fig = Figure(figsize=(WIDTH_IN, H / DPI), dpi=DPI)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(p.plane)

    def y(px: float) -> float:            # pixels from the top -> figure fraction
        return 1 - px / H

    def x(px: float) -> float:
        return px / W

    def text(px, py, s, size, color=p.ink, weight="normal", ha="left", va="top"):
        fig.text(x(px), y(py), s, fontsize=size, color=color, fontweight=weight,
                 ha=ha, va=va, fontfamily=font)

    def card(left, top, width, height, fill=p.surface, edge=p.grid):
        fig.patches.append(FancyBboxPatch(
            (x(left), y(top + height)), width / W, height / H,
            boxstyle=f"round,pad=0,rounding_size={14 / H:.4f}", transform=fig.transFigure,
            facecolor=fill, edgecolor=edge, linewidth=1.2, zorder=0,
        ))

    # ---- header ----
    text(margin, 48, f"{recap.season_title} {DOT} Week {recap.week}", 22, weight="bold")
    text(margin, 94, f"{recap.entrants} coaches {DOT} {recap.games} games", 12, color=p.ink_muted)

    # ---- the winner: names on one line, the score and pay on the next ----
    top = header_h
    card(margin, top, W - 2 * margin, winner_h, fill=mix(p.accent, p.surface, 0.16), edge=p.accent)
    text(margin + 28, top + 22, "WEEK WINNERS" if len(recap.winners) > 1 else "WEEK WINNER",
         10.5, color=p.accent, weight="bold")
    headline = recap.headline
    size = 24 if len(headline) <= 26 else 20 if len(headline) <= 34 else 16
    text(margin + 28, top + 48, headline, size, weight="bold")
    text(margin + 28, top + 104, recap.score_line, 14, weight="bold", color=p.ink_secondary)

    # ---- four numbers: this week, the pool, the crowd, the suicide pool ----
    top = header_h + winner_h + gap
    stats = [
        ("WEEK AVERAGE", f"{recap.average:.1f}", "wins per coach"),
        ("POOL AVERAGE", f"{recap.pool_average:.1f}",
         f"{recap.pool_above} above {DOT} {recap.pool_below} below"),
        ("CROWD WAS RIGHT", f"{recap.crowd_right} of {recap.crowd_games}"
         if recap.crowd_games else "-", "games the majority got"),
        _suicide_tile(recap),
    ]
    tile_gap = 14
    tile_w = (W - 2 * margin - 3 * tile_gap) / 4
    for i, (label, value, note) in enumerate(stats):
        left = margin + i * (tile_w + tile_gap)
        card(left, top, tile_w, strip_h)
        text(left + 18, top + 16, label, 8.5, color=p.ink_muted, weight="bold")
        text(left + 18, top + 40, value, 18 if len(value) <= 8 else 13.5, weight="bold")
        text(left + 18, top + 82, _clip(note, 24), 8.5, color=p.ink_secondary)

    # ---- standings (left) and awards (right) ----
    top = header_h + winner_h + gap + strip_h + gap
    card(margin, top, col_w, body_h)
    text(margin + 24, top + 22, "STANDINGS", 10.5, color=p.ink_muted, weight="bold")
    for i, s in enumerate(recap.standings):
        ry = top + 64 + i * 44
        text(margin + 24, ry, f"{s.place}", 13, color=p.ink_muted)
        text(margin + 66, ry, _clip(s.name, 18), 13.5,
             color=p.ink if s.won_week else p.ink_secondary,
             weight="bold" if s.won_week else "normal")
        text(margin + col_w - 92, ry, f"{s.wins}", 13.5, ha="right", weight="bold")
        if s.move:
            up = s.move > 0
            text(margin + col_w - 24, ry, f"{UP if up else DOWN}{abs(s.move)}", 11.5,
                 color=p.good if up else p.critical, ha="right")
        elif s.move == 0:
            text(margin + col_w - 24, ry, DASH, 11.5, color=p.ink_muted, ha="right")

    award_left = margin + col_w + gap
    card(award_left, top, col_w, body_h)
    text(award_left + 24, top + 22, "THIS WEEK'S AWARDS", 10.5, color=p.ink_muted, weight="bold")
    if not recap.awards:
        text(award_left + 24, top + 64, "A quiet week.", 12, color=p.ink_secondary)
    for i, a in enumerate(recap.awards):
        ay = top + 64 + i * 96
        text(award_left + 24, ay, a.title.upper(), 9.5, color=p.accent, weight="bold")
        text(award_left + 24, ay + 22, _clip(a.who, 26), 14, weight="bold")
        text(award_left + 24, ay + 52, _clip(a.detail, 44), 10.5, color=p.ink_secondary)

    # ---- upsets ----
    top += body_h + gap
    if recap.upsets:
        card(margin, top, W - 2 * margin, upsets_h)
        text(margin + 24, top + 22, "THE GAMES THAT SANK THE POOL", 10.5,
             color=p.ink_muted, weight="bold")
        for i, u in enumerate(recap.upsets):
            uy = top + 64 + i * up_row
            text(margin + 24, uy, u.matchup, 13.5, weight="bold")
            sub = f"{u.winner} won" + (f" on the pool line ({u.line})" if u.line else "")
            text(margin + 24, uy + 32, sub, 10.5, color=p.ink_secondary)
            share = u.right / u.entrants if u.entrants else 0
            text(W - margin - 24, uy + 6, f"{u.right} of {u.entrants} had it", 13,
                 ha="right", weight="bold", color=p.critical if share < 0.25 else p.warning)

    text(W / 2, H - 30, "ACQL Dashboard", 9.5, color=p.ink_muted, ha="center", va="bottom")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor=p.plane)
    return path