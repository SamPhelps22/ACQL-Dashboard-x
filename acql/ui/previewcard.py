"""The picture a chat app shows when the pool website's link is pasted.

1200 x 630 - the size every chat app and social site expects for a link
preview. It says the week at a glance: who won it, who leads the season, and
how many are left in the suicide pool. Drawn straight onto an image, with no
window, so it works while the dashboard is busy publishing.
"""

from __future__ import annotations

import io

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse, FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath

WIDTH, HEIGHT = 1200, 630
# The website's night colours: the logo's black, the pool's green and gold.
GROUND = "#0a0d0b"
SURFACE = "#131815"
RULE = "#263029"
INK = "#f1f4f1"
MUTED = "#98a39a"
FIELD = "#4cc486"
GOLD = "#f2b83a"
GOLD_SOFT = "#2b2411"

# ---- the crest ---------------------------------------------------------------------
# The league's crest: an armchair with a football on its seat, on a shield.
# Drawn on a 100 x 112 grid, y downwards - the same numbers as the website's
# own SVG (pool_page.html, CREST), so the two always match.
CREST_GREEN = "#1d6a44"
CREST_GOLD = "#e8b23a"
CREST_CHAIR = "#f4f7f2"
CREST_INK = "#0d1b2c"
SHIELD = [("M", 8, 6), ("L", 92, 6), ("L", 92, 52), ("C", 92, 80, 70, 98, 50, 108),
          ("C", 30, 98, 8, 80, 8, 52), ("Z",)]
CHAIR = [  # (x, y, width, height, corner radius)
    (30, 20, 40, 38, 8),     # the back
    (21, 46, 13, 26, 5),     # the arms
    (66, 46, 13, 26, 5),
    (31, 58, 38, 13, 4),     # the seat
    (26, 70, 6, 10, 1.5),    # the legs
    (68, 70, 6, 10, 1.5),
]
BALL = (50, 54, 26, 15, -14)  # centre x, centre y, width, height, tilt (degrees, y down)


def crest(ax, to, scale: float, flipped: bool) -> None:
    """Draw the crest onto `ax`. `to(x, y)` maps the 100 x 112 grid to the
    axes; `scale` is axes units per grid unit (for line widths, in points per
    grid unit); `flipped` says whether the axes' y runs downwards too."""
    verts, codes = [], []
    for step in SHIELD:
        if step[0] in "ML":
            verts.append(to(step[1], step[2]))
            codes.append(MplPath.MOVETO if step[0] == "M" else MplPath.LINETO)
        elif step[0] == "C":
            for i in (1, 3, 5):
                verts.append(to(step[i], step[i + 1]))
                codes.append(MplPath.CURVE4)
        else:
            verts.append(verts[0])
            codes.append(MplPath.CLOSEPOLY)
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=CREST_GREEN, edgecolor=CREST_GOLD,
                           linewidth=max(1.0, 3.2 * scale), joinstyle="round"))
    for x, y, w, h, r in CHAIR:
        (x0, y0), (x1, y1) = to(x, y), to(x + w, y + h)
        left, bottom = min(x0, x1), min(y0, y1)
        width, height = abs(x1 - x0), abs(y1 - y0)
        rad = r * width / w
        ax.add_patch(FancyBboxPatch((left + rad, bottom + rad), width - 2 * rad, height - 2 * rad,
                                    boxstyle=f"round,pad={rad}", facecolor=CREST_CHAIR,
                                    edgecolor=CREST_INK, linewidth=max(0.6, 1.2 * scale)))
    cx, cy, bw, bh, tilt = BALL
    (ex, ey), (fx, fy) = to(cx, cy), to(cx + bw, cy + bh)
    w, h = abs(fx - ex), abs(fy - ey)
    # The grid's y runs down, as on screen: a tilt of -14 lifts the ball's
    # right end. Matplotlib turns angles counter-clockwise in its own y, so
    # on axes whose y runs up the sign flips.
    angle = tilt if flipped else -tilt
    ax.add_patch(Ellipse((ex, ey), w, h, angle=angle, facecolor=CREST_GOLD,
                         edgecolor=CREST_INK, linewidth=max(0.6, 1.4 * scale)))
    # the laces, along the ball
    import math
    rad = math.radians(tilt)
    def along(t: float, across: float = 0.0):
        x = cx + t * math.cos(rad) - across * math.sin(rad)
        y = cy + t * math.sin(rad) + across * math.cos(rad)
        return to(x, y)
    (a0, b0), (a1, b1) = along(-6), along(6)
    ax.plot([a0, a1], [b0, b1], color=CREST_CHAIR, linewidth=max(0.8, 1.6 * scale), solid_capstyle="round")
    for t in (-4, 0, 4):
        (a0, b0), (a1, b1) = along(t, -2.2), along(t, 2.2)
        ax.plot([a0, a1], [b0, b1], color=CREST_CHAIR, linewidth=max(0.8, 1.3 * scale), solid_capstyle="round")


def _names(names: list[str], most: int = 2) -> str:
    if len(names) <= most:
        return " & ".join(names)
    return ", ".join(names[:most - 1]) + f" & {len(names) - most + 1} more"


def render(data: dict) -> bytes:
    """The preview card for a pool page snapshot (poolpage.snapshot) as PNG bytes."""
    weeks = data.get("weeks") or []
    week = next((w for w in weeks if w.get("week") == data.get("through_week")), weeks[-1] if weeks else None)
    players = data.get("players") or []
    from .. import siteextras
    # January's page is still last autumn's season
    year = str(siteextras.season_year(data.get("generated"))) if data.get("generated") else ""

    fig = Figure(figsize=(WIDTH / 100, HEIGHT / 100), dpi=100)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(GROUND)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.axis("off")

    def box(x, y, w, h, face, edge=None):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=14",
                                    facecolor=face, edgecolor=edge or face, linewidth=1.5))

    def text(x, y, s, size, color=INK, weight="normal", **kw):
        return ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, va="top", **kw)

    renderer = fig.canvas.get_renderer()

    def fitted(x, y, s, size, room, color=INK, weight="bold"):
        """Big text, shrunk (never below half size) until it fits `room` pixels."""
        t = text(x, y, s, size, color, weight)
        wide = t.get_window_extent(renderer).width
        if wide > room:
            t.set_fontsize(max(size * room / wide, size * 0.5))
        return t

    # masthead: the league's logo (the drawn crest without it), then the wordmark
    from . import brand
    logo = brand.image(220)
    if logo is not None:
        ax.imshow(logo, extent=(50, 154, 142, 38), aspect="auto", interpolation="lanczos", zorder=3)
        ax.set_xlim(0, WIDTH)
        ax.set_ylim(HEIGHT, 0)
    else:
        crest(ax, lambda x, y: (64 + x * 0.82, 40 + y * 0.82), 0.82 * 0.9, flipped=True)
    brand = ax.text(162, 52, "ACQL", fontsize=54, color=INK, fontweight="bold", va="top")
    # the year goes just after the word, wherever the font makes it end
    end = ax.transData.inverted().transform(brand.get_window_extent(renderer).corners()[-1])[0]
    text(end + 22, 52, year, 54, FIELD, "bold")
    through = data.get("through_week", "")
    text(WIDTH - 64, 64, f"AFTER WEEK {through}", 26, FIELD, "bold", ha="right")
    fitted(164, 120, "ARM CHAIR QUARTERBACK LEAGUE", 20, WIDTH - 228, FIELD)
    text(164, 153, f"{data.get('entrants', len(players))} coaches · weekly pick'em, Big Loser and the suicide pool",
         16, MUTED)
    ax.plot([64, WIDTH - 64], [190, 190], color=RULE, linewidth=2)

    # the week's winner, big
    if week:
        winners = list(week.get("winners") or [])
        label = f"WEEK {week.get('week')} {'WINNERS' if len(winners) > 1 else 'WINNER'}"
        box(64, 212, WIDTH - 128, 170, GOLD_SOFT)
        text(96, 236, label, 18, GOLD, "bold")
        name = _names(winners)
        fitted(96, 268, name, 48, WIDTH - 128 - 64)
        text(96, 338, f"{week.get('top', '')} wins" + (f"  ·  ${week['payout_each']:,.2f}"
             + (" each" if len(winners) > 1 else "") if week.get("payout_each") else ""), 20, INK)

    # three facts across the bottom
    facts = []
    if players:
        best = players[0].get("wins", 0)
        leaders = [p["name"] for p in players if p.get("wins") == best]
        facts.append(("SEASON LEADER", _names(leaders), f"{best} wins"))
    if week:
        facts.append((f"WEEK {week.get('week')} AVERAGE", f"{week.get('average', 0):.1f}", "wins per coach"))
        alive = sum(1 for p in players if (p.get("suicide") or {}).get("alive"))
        sui = week.get("suicide") or {}
        detail = f"{sui['killer']} knocked out {sui['killed']}" if sui.get("killer") else "every pick came in"
        facts.append(("SUICIDE POOL", f"{alive} left", detail))
    gap = 24
    width = (WIDTH - 128 - gap * (len(facts) - 1)) / max(1, len(facts))
    for i, (label, value, detail) in enumerate(facts):
        x = 64 + i * (width + gap)
        box(x, 410, width, 160, SURFACE, RULE)
        text(x + 26, 432, label, 16, MUTED, "bold")
        fitted(x + 26, 462, value, 38, width - 52)
        text(x + 26, 526, detail, 16, MUTED)

    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100, facecolor=GROUND)
    return out.getvalue()


ICON_GROUND = "#0d1b2c"


def icon(size: int = 512) -> bytes:
    """The home-screen icon: the league's crest on the website's navy, as a
    square PNG.

    Full-bleed colour with the crest inside the middle 60%, so phones that
    cut icons into circles or rounded squares never clip it.
    """
    fig = Figure(figsize=(size / 100, size / 100), dpi=100)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(ICON_GROUND)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, size)
    ax.set_ylim(size, 0)
    ax.axis("off")
    tall = size * 0.62                     # the crest's height: inside the safe middle
    unit = tall / 112
    left = (size - 100 * unit) / 2
    top = (size - tall) / 2
    crest(ax, lambda x, y: (left + x * unit, top + y * unit), unit * 72 / 100, flipped=True)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100, facecolor=ICON_GROUND)
    return out.getvalue()
