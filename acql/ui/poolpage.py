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

import json
import time
from pathlib import Path

from .. import analytics
from ..models import Season
from ..predictions import display_team
from . import recap

SCHEMA = 1
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


def _week_games(season: Season, number: int) -> list[dict]:
    week = season.weeks[number]
    out = []
    for game in sorted(week.games, key=lambda g: g.index):
        line = getattr(game, "line", None)
        fav = getattr(game, "line_favourite", "") or ""
        out.append({
            "matchup": game.label,
            "winner": display_team(game.winner) if game.played else "",
            "line": f"{display_team(fav)} by {line:g}" if line is not None and fav else "",
            "right": week.correct_count(game.index) if game.played else None,
        })
    return out


def _week(season: Season, number: int, *, money_known: bool = True) -> dict | None:
    made = recap.build(season, number)
    if made is None:
        return None
    return {
        "week": number,
        "entrants": made.entrants,
        "games": made.games,
        "average": round(made.average, 2),
        "winners": list(made.winners),
        "top": made.top_score,
        "payout_each": _money(made.payout_each) if money_known else None,
        "pool_average": round(made.pool_average, 2),
        "crowd": {"right": made.crowd_right, "games": made.crowd_games},
        "awards": [{"title": a.title, "who": a.who, "detail": a.detail} for a in made.awards],
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


def _suicide_status(season: Season, weeks: list[int], *, official: bool = True,
                    ) -> dict[str, tuple[bool, int | None]]:
    """key -> (still alive, week knocked out).

    Worked out week by week from each coach's pick and the result, with the
    pool's lines applied - the same rule as the recap, so the page and the
    recap always agree. The loader's own flags are only used for a coach
    whose picks don't settle it, and never name a week the page doesn't
    show: a DEAD marker on next week's sheet means out THIS week.
    """
    from ..predictions import team_code
    latest = max(weeks, default=0)
    out: dict[str, tuple[bool, int | None]] = {}
    for key, person in season.players.items():
        entered, knocked = False, None
        for number in weeks:
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


def snapshot(season: Season, *, generated: str | None = None) -> dict:
    """Everything the pool page shows, worked out from the season."""
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
                          if w in weeks},
            },
        })
    players.sort(key=lambda r: (r["place"] if r["place"] is not None else 999, -r["wins"],
                                r["name"].casefold()))

    return {
        "schema": SCHEMA,
        "title": getattr(season, "title", "") or "ACQL",
        "generated": generated or time.strftime("%Y-%m-%d %H:%M"),
        "through_week": latest,
        "buy_in": _money(season.buy_in),
        "entrants": len(season.players),
        "money": money_from,               # "" when the files don't give it
        "players": players,
        "weeks": [
            w for w in (
                _week(season, n, money_known=n not in set(getattr(season, "computed_winnings", []) or []))
                for n in weeks
            )
            if w is not None
        ],
    }


def to_json(data: dict) -> str:
    """JSON safe to put inside a <script> block (no "</" can end it early)."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


TEMPLATE = Path(__file__).with_name("pool_page.html")
SITE = "__SITE__"               # the website's address, filled in on upload
PREVIEW = "preview.png"         # the link-preview picture, next to the page


def page_html(season: Season, *, generated: str | None = None) -> str:
    """The whole pool page as one web page, for the pool's own website.

    The same page as the Claude one, marked as hosted so it offers no
    "update this page" controls - the dashboard publishes it instead.
    """
    import html as _html
    data = snapshot(season, generated=generated)
    if not data["weeks"]:
        raise ValueError("no finished week to put on the page yet")
    data["hosted"] = "web"
    fragment = TEMPLATE.read_text(encoding="utf-8").replace("__POOL_DATA__", to_json(data))
    head, body = fragment.split('<div id="app"', 1)
    year = data["generated"][:4]
    version = f"{data['through_week']}-" + "".join(ch for ch in data["generated"] if ch.isdigit())
    blurb = (f"Standings, results and side pools after week {data['through_week']} - "
             f"{data['entrants']} coaches.")
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
