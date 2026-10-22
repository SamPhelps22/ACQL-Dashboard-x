"""The design tokens the dashboard and the pool's website share.

The window and the website grew up apart: one counted corners in 6, 7, 10 and
12, the other in 2, 3, 4, 6, 8, 10, 12, 14 and 16; one tracked its labels at
1.6px, the other at four different fractions of an em; one drew its icons at
a 1.7 stroke and the other at 2. Side by side they read as two products.

This module is the one place those numbers live. It imports nothing from Qt,
so the stylesheet (theme.py) reads it and so does the page builder
(poolpage.py), which writes `css()` into the website's stylesheet each time
the site is published. Colour stays with each surface - the window and the
website wear their own palettes - but the shape of things is the same.
"""

from __future__ import annotations

#: The spacing ladder. Every margin, gap and padding is one of these steps.
SPACE = {"hair": 2, "tight": 4, "snug": 8, "step": 12, "room": 16, "gap": 24, "wide": 32}

#: Corners. Small things are nearly square, containers a touch softer; nothing
#: in between. `pill` is for the fully rounded tags.
RADIUS = {"xs": 2, "sm": 4, "md": 6, "lg": 10, "pill": 999}

#: A small-capitals label (column headings, kickers, what a tile measures):
#: the same size, weight and tracking wherever one appears.
LABEL = {"size": 11, "weight": 600, "tracking_em": 0.08}

#: Icon stroke on the 24-unit grid, for every icon on either surface.
ICON_STROKE = 1.7

#: How long a hover or focus change takes, where the surface animates at all.
MOTION_MS = 150

#: How strongly a hovered edge leans toward the accent. Hover hints at the
#: accent; focus and the chosen item commit to it.
HOVER_TINT = 0.45

#: The game-day motion vocabulary, in milliseconds, for both surfaces: the
#: gold wash on a score that really changed, a card changing state, a row
#: moving place on the leaderboard, a points total counting up, and going
#: into or out of Cinema mode. Each plays once, for a real change; with
#: reduced motion each becomes a still mark instead.
MOTION = {"flash": 1400, "state": 240, "rank": 450, "count": 700, "cinema": 220}

#: One easing for all of it: quick out, gentle settle (CSS cubic-bezier;
#: Qt's OutCubic is the same curve).
EASE = (0.22, 1.0, 0.36, 1.0)

#: How old a feed's last good look may get before the screen calls it stale,
#: in seconds. Scores are looked at every 30 seconds while a game is on and
#: every five minutes otherwise (feeds/results.py), so three missed looks is
#: stale. Standings follow the scores and are worked out from them.
FRESHNESS = {"scores_live_s": 90, "scores_s": 900, "standings_live_s": 90, "standings_s": 900}


def tracking_px(size: float, em: float = LABEL["tracking_em"]) -> float:
    """Letter-spacing in pixels for a face set at `size` - Qt has no `em`."""
    return round(size * em, 2)


def css() -> str:
    """The tokens as CSS custom properties, for the website's stylesheet."""
    s, r = SPACE, RADIUS
    props = [
        *(f"--sp-{i}: {v}px;" for i, v in enumerate(
            (s["hair"], s["tight"], s["snug"], s["step"], s["room"], s["gap"], s["wide"]), start=1)),
        *(f"--r-{name}: {v}px;" for name, v in r.items()),
        f"--label-size: {LABEL['size']}px;",
        f"--label-weight: {LABEL['weight']};",
        f"--label-tracking: {LABEL['tracking_em']}em;",
        f"--icon-stroke: {ICON_STROKE};",
        f"--motion: {MOTION_MS}ms;",
        f"--hover-tint: {round(HOVER_TINT * 100)}%;",
        # game day: the motion vocabulary, and the freshness limits the page's
        # script reads back as numbers (getComputedStyle), so one place holds them
        *(f"--m-{name}: {ms}ms;" for name, ms in MOTION.items()),
        f"--ease: cubic-bezier({', '.join(f'{v:g}' for v in EASE)});",
        *(f"--fresh-{name.replace('_', '-')}: {s};" for name, s in FRESHNESS.items()),
    ]
    return ":root { " + " ".join(props) + " }"
