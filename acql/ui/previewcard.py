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
from matplotlib.patches import FancyBboxPatch

WIDTH, HEIGHT = 1200, 630
GROUND = "#0e1411"
SURFACE = "#151d18"
RULE = "#26312a"
INK = "#e8eee8"
MUTED = "#8c998f"
FIELD = "#52bd86"
GOLD = "#e6b34b"
GOLD_SOFT = "#2c2415"


def _names(names: list[str], most: int = 2) -> str:
    if len(names) <= most:
        return " & ".join(names)
    return ", ".join(names[:most - 1]) + f" & {len(names) - most + 1} more"


def render(data: dict) -> bytes:
    """The preview card for a pool page snapshot (poolpage.snapshot) as PNG bytes."""
    weeks = data.get("weeks") or []
    week = next((w for w in weeks if w.get("week") == data.get("through_week")), weeks[-1] if weeks else None)
    players = data.get("players") or []
    year = str(data.get("generated", ""))[:4] or ""

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

    # masthead
    brand = ax.text(64, 52, "ACQL", fontsize=54, color=INK, fontweight="bold", va="top")
    # the year goes just after the word, wherever the font makes it end
    end = ax.transData.inverted().transform(brand.get_window_extent(renderer).corners()[-1])[0]
    text(end + 22, 52, year, 54, FIELD, "bold")
    through = data.get("through_week", "")
    text(WIDTH - 64, 64, f"AFTER WEEK {through}", 26, FIELD, "bold", ha="right")
    text(66, 132, f"{data.get('entrants', len(players))} coaches · weekly pick'em, Big Loser and the suicide pool",
         19, MUTED)
    ax.plot([64, WIDTH - 64], [182, 182], color=RULE, linewidth=2)

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
