"""The icon drawings themselves, apart from Qt.

icons.py turns these into pixmaps for the window; the page builder hands the
ones the website also uses to the site (WEB_NAMES), so a cup, a calendar or a
magnifying glass is the same drawing on either surface. Every shape is on the
same 24-unit grid, stroked at tokens.ICON_STROKE with round ends and no fill.
"""

from __future__ import annotations

ICONS = {
    # the season: a cup
    "trophy": (
        '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/>'
        '<path d="M8 5.6H5.2v1.2A3.2 3.2 0 0 0 8.3 10"/>'
        '<path d="M16 5.6h2.8v1.2A3.2 3.2 0 0 1 15.7 10"/>'
        '<path d="M12 13v3.6"/><path d="M9.6 16.6h4.8l.8 3.4H8.8z"/>'
    ),
    # this week's card
    "calendar": (
        '<rect x="4" y="5.2" width="16" height="14.8" rx="2"/>'
        '<path d="M4 9.8h16"/><path d="M8.5 3.2v3.6"/><path d="M15.5 3.2v3.6"/>'
        '<path d="M8 13.4h1.2"/><path d="M11.4 13.4h1.2"/><path d="M14.8 13.4h1.2"/>'
        '<path d="M8 16.6h1.2"/><path d="M11.4 16.6h1.2"/>'
    ),
    # game day: the ball
    "football": (
        '<g transform="rotate(-38 12 12)">'
        '<path d="M2.2 12Q12 1.4 21.8 12Q12 22.6 2.2 12z"/>'
        '<path d="M8.6 12h6.8"/><path d="M10 10.4v3.2"/><path d="M12 10.4v3.2"/><path d="M14 10.4v3.2"/>'
        '</g>'
    ),
    # results, week by week
    "bars": (
        '<rect x="4.4" y="13" width="3.6" height="7" rx=".6"/>'
        '<rect x="10.2" y="8.8" width="3.6" height="11.2" rx=".6"/>'
        '<rect x="16" y="4.4" width="3.6" height="15.6" rx=".6"/>'
    ),
    # the side pools: the field
    "people": (
        '<circle cx="12" cy="8.2" r="3"/><path d="M6.6 19.6v-.8a5.4 5.4 0 0 1 10.8 0v.8"/>'
        '<circle cx="4.9" cy="10.6" r="1.9"/><path d="M1.8 18.4v-.4a3.2 3.2 0 0 1 2.5-3.1"/>'
        '<circle cx="19.1" cy="10.6" r="1.9"/><path d="M22.2 18.4v-.4a3.2 3.2 0 0 0-2.5-3.1"/>'
    ),
    # one coach
    "person": '<circle cx="12" cy="8" r="3.6"/><path d="M5 20.2v-.8a7 7 0 0 1 14 0v.8"/>',
    # intelligence
    "search": '<circle cx="10.6" cy="10.6" r="6"/><path d="M15.1 15.1l5 5"/>',
    # Deadeye
    "crosshair": (
        '<circle cx="12" cy="12" r="6.4"/>'
        '<path d="M12 2.4v5"/><path d="M12 16.6v5"/><path d="M2.4 12h5"/><path d="M16.6 12h5"/>'
        '<circle cx="12" cy="12" r="1" fill="{colour}" stroke="none"/>'
    ),
    # the data
    "database": (
        '<ellipse cx="12" cy="6" rx="7" ry="2.8"/>'
        '<path d="M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6"/>'
        '<path d="M5 12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8"/>'
    ),
    "refresh": '<path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.3"/><path d="M19.6 4.2v4h-4"/>',
    # settings: three sliders
    "sliders": (
        '<path d="M4 7h8.6"/><path d="M17.4 7H20"/><circle cx="15" cy="7" r="2.2"/>'
        '<path d="M4 12h2.6"/><path d="M11.4 12H20"/><circle cx="9" cy="12" r="2.2"/>'
        '<path d="M4 17h9.6"/><path d="M18.4 17H20"/><circle cx="16" cy="17" r="2.2"/>'
    ),
    # a card kept
    "bookmark": '<path d="M7 4h10v16.2l-5-3.7-5 3.7z"/>',
    "copy": (
        '<rect x="8.4" y="8.4" width="11.2" height="11.6" rx="1.8"/>'
        '<path d="M5 15.4V5.8A1.8 1.8 0 0 1 6.8 4h8.4"/>'
    ),
    "camera": (
        '<path d="M4 8.4h3.3l1.5-2.4h6.4l1.5 2.4H20v10.8H4z"/><circle cx="12" cy="13.4" r="3.3"/>'
    ),
    "mail": '<rect x="3.6" y="5.8" width="16.8" height="12.4" rx="1.8"/><path d="M4.4 7.4l7.6 6 7.6-6"/>',
    "globe": (
        '<circle cx="12" cy="12" r="8.2"/><ellipse cx="12" cy="12" rx="3.5" ry="8.2"/><path d="M3.8 12h16.4"/>'
    ),
    "theme": '<circle cx="12" cy="12" r="7.6"/><path d="M12 4.4a7.6 7.6 0 0 1 0 15.2z" fill="{colour}"/>',
    # something wants a look
    "alert": (
        '<path d="M12 4.2L21 19.4H3z"/><path d="M12 10.2v4.4"/>'
        '<circle cx="12" cy="16.9" r=".6" fill="{colour}" stroke="none"/>'
    ),
    # a note
    "info": (
        '<circle cx="12" cy="12" r="8.2"/><path d="M12 11.2v5"/>'
        '<circle cx="12" cy="8" r=".6" fill="{colour}" stroke="none"/>'
    ),
    # nothing loaded yet: the data folder
    "folder": '<path d="M3.6 7.2V18a1.6 1.6 0 0 0 1.6 1.6h13.6A1.6 1.6 0 0 0 20.4 18V9.4a1.6 1.6 0 0 0-1.6-1.6h-6.6L10 5.4H5.2a1.6 1.6 0 0 0-1.6 1.8z"/>',
    # marks, and the season's superlatives (pages/overview.py, pages/readiness.py)
    "check": '<path d="M5 12.6l4.6 4.6L19 7.4"/>',
    "cross": '<path d="M6.4 6.4l11.2 11.2"/><path d="M17.6 6.4L6.4 17.6"/>',
    "coin": '<circle cx="12" cy="12" r="8.2"/><path d="M14.6 9.6c-.5-.9-1.5-1.4-2.6-1.4-1.5 0-2.7.7-2.7 1.9s1 1.6 2.7 1.9 2.7.7 2.7 1.9-1.2 1.9-2.7 1.9c-1.1 0-2.1-.5-2.6-1.4"/><path d="M12 6.6v1.6"/><path d="M12 15.8v1.6"/>',
    "banknote": '<rect x="3" y="6.6" width="18" height="10.8" rx="1.6"/><circle cx="12" cy="12" r="2.6"/><path d="M6.2 9.8v4.4"/><path d="M17.8 9.8v4.4"/>',
    "hourglass": '<path d="M7 3.6h10"/><path d="M7 20.4h10"/><path d="M8 3.6v3.2c0 2 4 3.4 4 5.2s-4 3.2-4 5.2v3.2"/><path d="M16 3.6v3.2c0 2-4 3.4-4 5.2s4 3.2 4 5.2v3.2"/>',
    "star": '<path d="M12 3.6l2.5 5.3 5.8.7-4.3 4 1.1 5.8L12 16.6l-5.1 2.8 1.1-5.8-4.3-4 5.8-.7z"/>',
    "flame": '<path d="M12 3.4c.6 3.2 5 5.2 5 10a5 5 0 0 1-10 0c0-1.8.8-3.2 1.8-4.2.2 1.6 1 2.4 1.8 2.6-.4-3 .2-6.2 1.4-8.4z"/>',
    "bolt": '<path d="M13.2 3.2L5.6 13.4h5.2l-1 7.4 7.6-10.2h-5.2z"/>',
    "snowflake": '<path d="M12 3v18"/><path d="M4.2 7.5l15.6 9"/><path d="M19.8 7.5l-15.6 9"/><path d="M9.8 4.6L12 6.6l2.2-2"/><path d="M9.8 19.4l2.2-2 2.2 2"/>',
    "crown": '<path d="M4 17.6L3 8l5 4 4-6.4 4 6.4 5-4-1 9.6z"/><path d="M4.6 20.2h14.8"/>',
    "medal": '<circle cx="12" cy="14.6" r="5.2"/><path d="M8.6 10.4L6 3.6h4l2 4.4"/><path d="M15.4 10.4L18 3.6h-4l-2 4.4"/>',
    "sprout": '<path d="M12 20.4v-8"/><path d="M12 12.4c0-3.4-2.4-5.4-6.4-5.4 0 3.6 2.4 5.6 6.4 5.4z"/><path d="M12 10c0-3 2.2-5 6.4-5 0 3.4-2.4 5.2-6.4 5z"/>',
    "trend-up": '<path d="M3.6 17l5.6-5.6 3.6 3.6 7.4-7.6"/><path d="M15.4 7.2h4.8V12"/>',
    "trend-down": '<path d="M3.6 7l5.6 5.6 3.6-3.6 7.4 7.6"/><path d="M15.4 16.8h4.8V12"/>',
    "skull": '<path d="M5.4 11.2a6.6 6.6 0 0 1 13.2 0c0 2.2-.9 3.7-2.2 4.7v2.9a1.4 1.4 0 0 1-1.4 1.4H9a1.4 1.4 0 0 1-1.4-1.4v-2.9c-1.3-1-2.2-2.5-2.2-4.7z"/><circle cx="9.4" cy="11.6" r="1.3"/><circle cx="14.6" cy="11.6" r="1.3"/><path d="M10.6 20v-2.2"/><path d="M13.4 20v-2.2"/>',
    "dice": '<rect x="4.4" y="4.4" width="15.2" height="15.2" rx="2.6"/><circle cx="8.6" cy="8.6" r=".9" fill="{colour}" stroke="none"/><circle cx="15.4" cy="15.4" r=".9" fill="{colour}" stroke="none"/><circle cx="12" cy="12" r=".9" fill="{colour}" stroke="none"/><circle cx="15.4" cy="8.6" r=".9" fill="{colour}" stroke="none"/><circle cx="8.6" cy="15.4" r=".9" fill="{colour}" stroke="none"/>',
    "shield": '<path d="M12 3.4l7 2.6v5.4c0 4.4-2.8 7.6-7 9.2-4.2-1.6-7-4.8-7-9.2V6z"/>',
    "shield-check": '<path d="M12 3.4l7 2.6v5.4c0 4.4-2.8 7.6-7 9.2-4.2-1.6-7-4.8-7-9.2V6z"/><path d="M8.8 11.8l2.3 2.4 4.2-4.6"/>',
    "down": '<path d="M5 7.4h14L12 18.6z"/>',
    "anchor": '<circle cx="12" cy="5.6" r="2"/><path d="M12 7.6v12.6"/><path d="M8.4 11h7.2"/><path d="M4.6 13.6a7.4 7.4 0 0 0 14.8 0"/>',
    "split": '<path d="M12 20.4v-7.6"/><path d="M12 12.8L5.6 6.4"/><path d="M12 12.8l6.4-6.4"/><path d="M5.4 10.6V6.2h4.4"/><path d="M18.6 10.6V6.2h-4.4"/>',
    "chevron-left": '<path d="M14.6 5.6L8.2 12l6.4 6.4"/>',
    "chevron-right": '<path d="M9.4 5.6l6.4 6.4-6.4 6.4"/>',
    "screen": '<rect x="3.2" y="4.6" width="17.6" height="11.6" rx="1.6"/><path d="M8.6 20h6.8"/><path d="M12 16.2V20"/>',
    # Operation Sunday's own mark: the ball in the sights
    "mark": (
        '<circle cx="12" cy="12" r="8.6"/>'
        '<path d="M12 .9v4.6"/><path d="M12 18.5v4.6"/><path d="M.9 12h4.6"/><path d="M18.5 12h4.6"/>'
        '<path d="M12 5.4Q19 12 12 18.6Q5 12 12 5.4z"/>'
        '<path d="M12 9.6v4.8"/><path d="M10.9 10.9h2.2"/><path d="M10.9 13.1h2.2"/>'
    ),
}


#: An award (acql.pool.awards, by key) -> the drawing its tile wears, so the
#: Overview's superlatives are in the same family as every other icon rather
#: than twenty emoji from twenty hands. An award missing here keeps its emoji.
AWARD_ICONS = {
    "payday": "coin", "cashed": "banknote", "waiting": "hourglass", "best": "star",
    "hot": "flame", "streak": "bolt", "cold": "snowflake", "weekwinner": "crown",
    "bridesmaid": "medal", "bloomer": "sprout", "choke": "skull", "climber": "trend-up",
    "freefall": "trend-down", "dead": "cross", "consistent": "crosshair", "boom": "dice",
    "reliable": "shield-check", "average": "search", "bigloser": "down", "suicide": "shield",
    "ironman": "anchor", "contrarian": "split", "sheep": "people",
}

#: The website's name for an icon -> the drawing it shares with the window.
#: Icons the window has no use for (menu, close, share, ...) are drawn in the
#: page itself, on the same grid and at the same stroke.
WEB_NAMES = {
    "search": "search",
    "history": "trophy",
    "weeks": "calendar",
    "me": "person",
    "pools": "people",
    "money": "banknote",
    "theme": "theme",
}


def web_icons() -> dict[str, str]:
    """The shared drawings, under the names the website calls them by."""
    return {web: ICONS[ours] for web, ours in WEB_NAMES.items() if ours in ICONS}
