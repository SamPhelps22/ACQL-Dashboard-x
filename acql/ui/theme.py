"""Colour tokens and the Qt stylesheet.

Both palettes are selected rather than generated: the dark set is the same
eight hues re-stepped for the dark surface, not an automatic inversion of the
light set. The categorical order is fixed and assigned by slot, never cycled,
so a player keeps their colour when a filter changes the series count.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tokens import HOVER_TINT, LABEL, RADIUS, SPACE, tracking_px


@dataclass(frozen=True)
class Palette:
    name: str
    surface: str          # chart surface
    plane: str            # page background
    raised: str           # cards, headers
    ink: str              # primary text
    ink_secondary: str
    ink_muted: str        # axis labels
    grid: str
    baseline: str
    border: str
    accent: str
    series: tuple[str, ...]
    sequential: tuple[str, ...]
    good: str
    warning: str
    serious: str
    critical: str
    selection: str
    #: The gold of the name and the mark. The accent is for what you can act
    #: on or are looking at; this is for what the thing is.
    brand: str = ""

    def series_color(self, index: int) -> str:
        """Fixed-order slot assignment; past the last slot, fold to muted."""
        if 0 <= index < len(self.series):
            return self.series[index]
        return self.ink_muted


# Operation Sunday: black and graphite, white type, gold for the name, and one
# electric blue for whatever is chosen, focused or can be pressed. Nothing
# else competes with that blue - good and bad news keep their green and red,
# and the data colours are eight that stay apart on either surface.
DARK = Palette(
    name="dark",
    surface="#0b0f15",
    plane="#05070a",
    raised="#111720",
    ink="#f3f6fa",
    ink_secondary="#b6c1cf",
    ink_muted="#77859a",
    grid="#1a2230",
    baseline="#2c3849",
    border="rgba(255,255,255,0.10)",
    accent="#2e9bff",
    series=("#2e9bff", "#e8b84e", "#2fd68a", "#ff7847",
            "#ff5fa8", "#9b8cff", "#22d3ee", "#ff5b5b"),
    sequential=("#0a1b30", "#0d2846", "#11375f", "#15487d",
                "#1a5b9d", "#2071c2", "#2e8ce8", "#66aef6", "#acd4fc"),
    good="#2fd68a",
    warning="#f2b93b",
    serious="#ff8a4c",
    critical="#ff5b5b",
    selection="#12325a",
    brand="#e8b84e",
)

LIGHT = Palette(
    name="light",
    surface="#f8fafc",
    plane="#edf1f6",
    raised="#ffffff",
    ink="#0a0f16",
    ink_secondary="#374353",
    ink_muted="#687587",
    grid="#d8dfe9",
    baseline="#a9b5c4",
    border="rgba(10,15,22,0.10)",
    accent="#1463d9",
    series=("#1463d9", "#b9820a", "#0f9d62", "#e2622b",
            "#d43f86", "#6f56e8", "#0891b2", "#dc3a3a"),
    sequential=("#dbe9fd", "#bcd6fb", "#97bff7", "#6ea5f1",
                "#4789ea", "#2a6edc", "#1c57bd", "#16469a", "#113572"),
    good="#0f9d58",
    warning="#c98600",
    serious="#e2622b",
    critical="#d93025",
    selection="#d5e5fb",
    brand="#a06f0a",
)

# The league's own colours, off its logo: black, gold and the field's green.
# What goes round to the pool - the weekly recap picture - is drawn in these,
# whatever the dashboard itself is wearing.
LEAGUE_DARK = Palette(
    name="dark",
    surface="#0f1613",
    plane="#070b09",
    raised="#17211c",
    ink="#f5f8f5",
    ink_secondary="#c4cfc7",
    ink_muted="#8b998f",
    grid="#223129",
    baseline="#35483c",
    border="rgba(255,255,255,0.10)",
    accent="#f5b82e",
    series=("#f5b82e", "#3d9bff", "#2ee08a", "#ff7a3d",
            "#ff5fa2", "#a98bff", "#27d3e6", "#ff5a5a"),
    sequential=("#0c2b1d", "#10402a", "#155637", "#1b6f46",
                "#228a57", "#2ba869", "#3fc47f", "#74e0a6", "#b8f4d1"),
    good="#2ee08a",
    warning="#ffc233",
    serious="#ff8a4c",
    critical="#ff5a5a",
    selection="#1d4a36",
    brand="#f5b82e",
)

LEAGUE_LIGHT = Palette(
    name="light",
    surface="#fbfcfa",
    plane="#f1f5f0",
    raised="#ffffff",
    ink="#0b100d",
    ink_secondary="#3d4942",
    ink_muted="#73807a",
    grid="#dde5dd",
    baseline="#b5c2b8",
    border="rgba(11,16,13,0.10)",
    accent="#0d7a45",
    series=("#c98a06", "#1f6fe0", "#10a765", "#e8622a",
            "#d93f87", "#7a5cf0", "#0a9fb3", "#e23d3d"),
    sequential=("#d4f2e1", "#b3e6cb", "#8ed9b2", "#67c996",
                "#43b67b", "#2a9d63", "#1b8251", "#12673f", "#0b4a2d"),
    good="#0f9d58",
    warning="#e09a00",
    serious="#e8622a",
    critical="#d93025",
    selection="#d3eede",
    brand="#0d7a45",
)

PALETTES = {"dark": DARK, "light": LIGHT}

# The model's own charts name three things - Deadeye, the betting line and a
# baseline - and all three can share one plot, scatter included, so these are
# chosen for every pair, not only neighbours: blue, a gold stepped down into
# the dark surface's range, and a pink in place of the green that sits too
# near gold for a reader who cannot tell red from green. Checked with the
# six tests of the charting rules (lightness band, chroma, separation under
# simulated protanopia and deuteranopia >= 8, normal vision >= 15, contrast
# against the surface >= 3) on each surface: worst pair 10.8 dark, 13.7 light.
MODEL_SERIES = {
    "dark": ("#2c95f6", "#b28c3a", "#e75597"),
    "light": ("#1463d9", "#b9820a", "#d43f86"),
}


def model_series(palette: Palette) -> tuple[str, str, str]:
    """(Deadeye, the betting line, the baseline) for the model's charts."""
    return MODEL_SERIES.get(palette.name, MODEL_SERIES["dark"])
LEAGUE = {"dark": LEAGUE_DARK, "light": LEAGUE_LIGHT}


def league(palette: Palette) -> Palette:
    """The league's colours, light or dark to match the palette in use."""
    return LEAGUE.get(palette.name, LEAGUE_DARK)

FONT_STACK = '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
# The dashboard's own voice: the squared, engineered face of a road sign or a
# scoreboard, for the name, page titles, labels and the one big number a tile
# exists to show. It ships with Windows; where it is missing the UI face
# stands in and nothing moves.
DISPLAY_STACK = '"Bahnschrift", "Segoe UI Variable Display", "Segoe UI", sans-serif'
# Figures that sit in a column or among words - chips, label/value lists. The
# UI face's digits are all one width, so a column of them lines up without
# the typewriter look a monospaced face gave "3-way tie" and "$106.50".
NUMERIC_STACK = FONT_STACK
# A real monospace, for the one place that shows code: a failure's details.
MONO_STACK = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'

# One scale, used everywhere. Sizes were ad hoc before - 13, 13.5, 12.5, 12,
# 11.5 all appeared - which is invisible on one page and incoherent across
# twelve. Each step is about 1.15x the one below it, and the names say what
# the step is for rather than how big it is.
TYPE = {
    "display": 32,     # the one number a tile exists to show
    "title": 24,       # page titles
    "heading": 16,     # a name inside a card
    "body": 13,        # everything you read
    "label": 12,       # column headings, card titles
    "caption": 11.5,   # footnotes, units, the small print
}
# Spacing, corners and the label style come from tokens.py, which the pool's
# website reads too, so the window and the site are cut from the same cloth.


def mix(fg: str, bg: str, amount: float) -> str:
    """Blend `fg` over `bg` (both #rrggbb); `amount` is how much of `fg` shows.

    Solid blended colours are used for hover and active states instead of
    translucent ones: Qt stylesheets read alpha inconsistently, and a solid
    colour renders the same everywhere.
    """
    def channels(colour: str) -> tuple[int, ...]:
        h = colour.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    blended = (
        round(b + (f - b) * amount)
        for f, b in zip(channels(fg), channels(bg))
    )
    return "#{:02x}{:02x}{:02x}".format(*blended)


def ramp_color(palette: Palette, fraction: float) -> str:
    """Pick a sequential step for a 0..1 magnitude.

    The low end always recedes toward the chart surface and the high end always
    stands away from it, so the ramp runs light->dark on the light surface and
    dark->light on the dark one. Each palette stores its steps in that order,
    which is why this function needs no per-mode branch.
    """
    steps = palette.sequential
    if not steps:
        return palette.accent
    fraction = 0.0 if fraction != fraction else max(0.0, min(1.0, fraction))
    idx = int(round(fraction * (len(steps) - 1)))
    return steps[idx]


def ramp_direction(palette: Palette) -> str:
    """The word for 'higher magnitude' on this surface, for chart captions."""
    return "brighter" if palette.name == "dark" else "darker"


def tone_color(p: Palette, tone: str) -> str:
    """The colour a named tone paints in, for widgets that draw themselves."""
    return {
        "good": p.good,
        "warning": p.warning,
        "serious": p.serious,
        "bad": p.critical,
        "muted": p.ink_muted,
    }.get(tone, p.ink_secondary)


def _luminance(colour: str) -> float:
    """Relative luminance (WCAG), 0 for black to 1 for white."""
    h = colour.lstrip("#")
    parts = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        parts.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast(a: str, b: str) -> float:
    """The contrast ratio between two colours, 1 (none) to 21."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _bright(colour: str) -> bool:
    """Whether dark text reads better than white on a colour."""
    return contrast(colour, "#05070a") >= contrast(colour, "#ffffff")


def stylesheet(p: Palette) -> str:
    """Qt stylesheet for the whole application."""
    hover = mix(p.ink, p.surface, 0.07)       # neutral hover wash
    pressed = mix(p.ink, p.raised, 0.12)      # a button while it is held down
    # The primary button's hover used to borrow the selection colour, which
    # in the light theme is a pale blue: white text on it measured 1.3:1 and
    # all but vanished. It now deepens the accent itself, which raises the
    # label's contrast in both themes (light 4.4 -> 5.7, dark 3.6 -> 4.7).
    primary_hover = mix(p.accent, "#000000", 0.86)
    primary_pressed = mix(p.accent, "#000000", 0.74)
    # What is written on the accent: dark on the dark theme's gold, white on
    # the light theme's green - whichever reads.
    on_accent = "#05070a" if _bright(p.accent) else "#ffffff"
    brand = p.brand or p.accent
    lit = mix(p.accent, p.surface, 0.26)      # the chosen place, at the edge the bar is on
    rule = mix(p.accent, p.raised, 0.40)      # a hairline in the accent
    # One hairline for every edge - panels, tables and controls alike - and
    # one hovered edge: hover leans toward the accent, focus commits to it.
    # The website does the same with its --rule and --rule-hover.
    line = p.grid
    line_hover = mix(p.accent, p.raised, HOVER_TINT)
    label_tracking = tracking_px(LABEL["size"])
    sheen = mix(p.ink, p.surface, 0.035)      # the light a panel catches along its top
    gilt = mix(brand, p.raised, 0.10)         # the gold, barely there: the lead tile's wash
    t = TYPE
    s = SPACE
    r = RADIUS
    # A tinted chip for each tone, mixed over the tile surface so it stays
    # solid - Qt reads alpha inconsistently between platforms.
    chips = "".join(
        f"""
    #Pill[tone="{name}"] {{
        background: {mix(colour, p.raised, 0.16)};
        color: {colour};
    }}
    #StatDetail[tone="{name}"] {{ color: {colour}; font-weight: 600; }}
    #MetricValue[tone="{name}"] {{ color: {colour}; }}"""
        for name, colour in (
            ("good", p.good), ("warning", p.warning),
            ("serious", p.serious), ("bad", p.critical),
        )
    )
    return f"""
    * {{ font-family: {FONT_STACK}; }}

    QWidget {{
        background: {p.plane};
        color: {p.ink};
        font-size: {t["body"]}px;
    }}
    /* Text sits on whatever surface is behind it, not on a plane-coloured box. */
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

    QMainWindow, QDialog {{ background: {p.plane}; }}

    /* ---- left navigation ---- */
    #Sidebar {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {p.surface}, stop:1 {mix(p.surface, p.plane, 0.35)});
        border-right: 1px solid {p.grid};
    }}
    /* The name: OPERATION in light capitals, SUNDAY under it in gold. */
    #BrandTop {{
        color: {p.ink_secondary};
        font-family: {DISPLAY_STACK};
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 5px;
    }}
    #SidebarTitle {{
        color: {brand};
        font-family: {DISPLAY_STACK};
        font-size: 21px;
        font-weight: 700;
        letter-spacing: 3.4px;
    }}
    #BrandLine {{
        color: {p.ink_muted};
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 1.7px;
        padding: 0 18px 0 18px;
    }}
    #BrandRule {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {brand}, stop:0.55 {mix(brand, p.surface, 0.25)}, stop:1 {p.surface});
        border: none;
        margin: 10px 18px 10px 18px;
    }}
    #SidebarSubtitle {{
        color: {p.ink_muted};
        font-size: {t["caption"]}px;
        padding: 0 18px 6px 18px;
    }}
    /* A place: its icon and its name, edge to edge. The chosen one carries
       the blue down its left edge and a wash of it fading to the right. */
    #Sidebar QPushButton#NavButton {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0px;
        color: {p.ink_secondary};
        text-align: left;
        padding: 10px 14px 10px 17px;
        margin: 1px 0px;
        font-size: {t["body"]}px;
        letter-spacing: 0.3px;
    }}
    #Sidebar QPushButton#NavButton:hover,
    #Sidebar QPushButton#NavButton:focus {{
        background: {hover};
        color: {p.ink};
    }}
    #Sidebar QPushButton#NavButton:checked {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {lit}, stop:1 {mix(p.accent, p.surface, 0.03)});
        border-left: 3px solid {p.accent};
        color: {p.ink};
        font-weight: 700;
    }}

    /* Refresh / theme / jump: quiet outlines, so the nav stays the loudest thing. */
    #Sidebar QPushButton {{
        background: transparent;
        border: 1px solid {line};
        border-radius: {r["sm"]}px;
        color: {p.ink_secondary};
        text-align: left;
        padding: 7px 11px;
    }}
    #Sidebar QPushButton:hover {{
        background: {hover};
        border-color: {line_hover};
        color: {p.ink};
    }}
    #Sidebar QPushButton:disabled {{ color: {p.ink_muted}; }}

    /* ---- cards & headings ---- */
    /* A panel catches a little light along its top edge and has an outline
       you sense rather than see - depth from the surface, not from a box. */
    #Card {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 {sheen}, stop:0.12 {p.surface}, stop:1 {p.surface});
        border: 1px solid {line};
        border-radius: {r["md"]}px;
    }}
    /* Headline numbers sit one step above the content cards. They are quiet
       by default: the first tile of a row is the page's headline and is the
       only one lit (in the gold), so a row of six has somewhere to start. */
    #StatTile {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {mix(p.ink, p.raised, 0.04)}, stop:0.5 {p.raised});
        border: 1px solid {line};
        border-radius: {r["md"]}px;
    }}
    #StatTile[lead="true"] {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {gilt}, stop:0.6 {p.raised});
        border: 1px solid {mix(brand, p.raised, 0.28)};
        border-top: 2px solid {brand};
    }}
    /* What a tile measures, as an instrument labels its dials. */
    #StatTile #CardTitle {{
        color: {p.ink_muted};
        font-family: {DISPLAY_STACK};
        font-size: {LABEL["size"]}px;
        font-weight: {LABEL["weight"]};
        letter-spacing: {label_tracking}px;
        border: none;
        padding: 0;
    }}
    #StatTile[lead="true"] #CardTitle {{ color: {brand}; }}
    /* An award tile is a stat tile with a hairline down its left edge tinted
       by tone, so a good or bad award reads at a glance without the text
       itself having to be coloured. */
    #AwardTile {{
        background: {p.raised};
        border: 1px solid {line};
        border-left: 3px solid {p.baseline};
        border-radius: {r["md"]}px;
    }}
    #AwardTile[tone="good"] {{ border-left-color: {p.good}; }}
    #AwardTile[tone="bad"] {{ border-left-color: {p.critical}; }}
    #AwardIcon {{ font-size: {t["heading"]}px; }}
    #AwardWinner {{ font-size: {t["heading"]}px; font-weight: 700; color: {p.ink}; }}
    #AwardDetail {{ font-size: {t["caption"]}px; color: {p.ink_muted}; }}
    /* The number reads as a chip so it never competes with the name. */
    #AwardValue {{
        background: {mix(p.ink, p.raised, 0.08)};
        border-radius: {r["sm"]}px;
        padding: {s["hair"]}px {s["snug"]}px;
        font-family: {NUMERIC_STACK};
        font-size: {t["label"]}px;
        font-weight: 700;
        color: {p.ink_secondary};
    }}
    #AwardValue[tone="good"] {{
        background: {mix(p.good, p.raised, 0.16)};
        color: {p.good};
    }}
    #AwardValue[tone="bad"] {{
        background: {mix(p.critical, p.raised, 0.16)};
        color: {p.critical};
    }}

    /* Game Day: one game, scoreboard style. The left edge says how your
       pick stands - credited now, not, or a game on you have no pick in. */
    #GameCard {{
        background: {p.raised};
        border: 1px solid {line};
        border-left: 4px solid {p.baseline};
        border-radius: {r["md"]}px;
    }}
    #GameCard[tone="good"] {{ border-left-color: {p.good}; }}
    #GameCard[tone="bad"] {{ border-left-color: {p.critical}; }}
    #GameCard[tone="live"] {{ border-left-color: {p.accent}; }}
    #GameState {{
        font-size: {t["caption"]}px;
        font-weight: 700;
        letter-spacing: 0.4px;
        color: {p.ink_secondary};
    }}
    #GameState[live="true"] {{ color: {p.critical}; }}
    #GameTeam {{ font-size: {t["body"] + 1}px; font-weight: 600; color: {p.ink}; }}
    #GameTeam[faded="true"] {{ color: {p.ink_muted}; font-weight: 500; }}
    #GameScore {{
        font-family: {DISPLAY_STACK};
        font-size: {t["title"]}px;
        font-weight: 600;
        color: {p.ink};
    }}
    #GameScore[faded="true"] {{ color: {p.ink_muted}; }}
    #GameLine {{ font-size: {t["caption"]}px; color: {p.ink_secondary}; font-weight: 600; }}
    #GameMeta {{ font-size: {t["caption"]}px; color: {p.ink_secondary}; }}
    #GameNote {{ font-size: {t["caption"]}px; color: {p.ink_muted}; font-style: italic; }}
    #Ball {{ font-size: {t["label"]}px; }}

    #PageTitle {{
        font-family: {DISPLAY_STACK};
        font-size: {t["title"]}px;
        font-weight: 600;
        letter-spacing: 2.4px;
        color: {p.ink};
    }}
    /* The gold rule under a page's name - the same line the sidebar draws
       under the dashboard's own. */
    #TitleRule {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {brand}, stop:1 {mix(brand, p.plane, 0.30)});
        border: none;
        border-radius: 1px;
    }}
    #PageSubtitle {{ font-size: {t["body"]}px; color: {p.ink_muted}; }}
    /* A card's title, behind a tick of the gold: gold names things, the blue
       is kept for what is chosen or can be pressed. */
    #CardTitle {{
        font-family: {DISPLAY_STACK};
        font-size: {t["body"]}px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: {p.ink};
        border-left: 2px solid {brand};
        padding-left: 8px;
    }}
    #StatValue {{
        font-family: {DISPLAY_STACK};
        font-size: {t["display"]}px;
        font-weight: 600;
        color: {p.ink};
    }}
    /* A tile whose headline is a name rather than a number needs the room
       more than it needs the size, so it steps down instead of eliding. */
    #StatValue[length="long"] {{ font-size: {t["title"]}px; }}
    #StatValue[length="verylong"] {{ font-size: {t["heading"] + 1}px; }}
    #StatDetail {{ font-size: {t["caption"]}px; color: {p.ink_secondary}; }}
    #StatDetail[tone="good"] {{ color: {p.good}; font-weight: 600; }}
    #StatDetail[tone="bad"] {{ color: {p.critical}; font-weight: 600; }}
    /* ---- small shared pieces ---- */
    /* A chip: one number with a tone behind it, for a figure that has to be
       read next to words without shouting over them. */
    #Pill {{
        background: {mix(p.ink, p.raised, 0.08)};
        border-radius: {r["sm"]}px;
        padding: {s["hair"]}px {s["snug"]}px;
        font-family: {NUMERIC_STACK};
        font-size: {t["caption"]}px;
        font-weight: 700;
        color: {p.ink_secondary};
    }}{chips}
    /* A label/value pair, for dense lists of figures inside a card. */
    #MetricLabel {{ color: {p.ink_muted}; font-size: {t["caption"]}px; }}
    #MetricValue {{
        font-family: {NUMERIC_STACK};
        font-size: {t["body"]}px;
        font-weight: 600;
        color: {p.ink};
    }}
    #MetricNote {{ color: {p.ink_muted}; font-size: {t["caption"]}px; }}

    #Good {{ color: {p.good}; font-weight: 600; }}
    #Bad {{ color: {p.critical}; font-weight: 600; }}
    #Muted {{ color: {p.ink_muted}; }}

    /* ---- tables ---- */
    QTableView {{
        background: {p.surface};
        alternate-background-color: {p.raised};
        gridline-color: {p.grid};
        border: 1px solid {line};
        border-radius: {r["md"]}px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
        font-size: 13px;
    }}
    QTableView::item {{ padding: 5px 8px; border: none; }}
    /* A table inside a card is already framed by the card: a second outline
       round it made every table a box in a box. */
    #Card QTableView {{ border: none; border-radius: 0px; }}
    /* There was a hover rule here that lifted the row under the cursor. It
       reads well and costs too much: a `::item` state rule makes Qt style and
       repaint cells one at a time as the mouse moves across a table, and with
       thirty-five coaches against seventeen columns that was enough to make
       the whole window feel slow. Alternating rows carry the eye instead. */
    QHeaderView::section {{
        background: {p.raised};
        color: {p.ink_muted};
        padding: 9px 8px;
        border: none;
        border-bottom: 1px solid {rule};
        /* the narrower cut: a heading is the first thing to run out of room */
        font-family: "Bahnschrift SemiCondensed", {DISPLAY_STACK};
        font-size: {t["label"]}px;
        font-weight: {LABEL["weight"]};
        letter-spacing: {tracking_px(t["label"], 0.04)}px;
    }}
    QHeaderView::section:hover {{ color: {p.ink}; background: {mix(p.ink, p.raised, 0.05)}; }}
    /* Qt's own sort arrow is not drawn: it has no room of its own, so over a
       heading set to its column's edge it sat on top of the label. The arrow
       is written into the heading instead (TableModel.mark_sorted). */
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        image: none;
        width: 0px;
        height: 0px;
    }}
    /* The sorted column keeps a hairline under it, which is quieter than Qt's
       default arrow and survives a narrow column. */
    QHeaderView::section:checked {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}
    QTableCornerButton::section {{ background: {p.raised}; border: none; }}

    /* ---- controls ---- */
    QPushButton {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {line};
        border-radius: {r["sm"]}px;
        padding: {s["snug"] - 1}px {s["room"]}px;
        font-size: {t["body"]}px;
    }}
    QPushButton:hover {{ background: {hover}; border-color: {line_hover}; }}
    QPushButton:focus {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {pressed}; }}
    QPushButton:disabled {{ color: {p.ink_muted}; border-color: {line}; }}
    QPushButton#Primary {{
        background: {p.accent};
        border-color: {p.accent};
        color: {on_accent};
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{ background: {primary_hover}; border-color: {primary_hover}; }}
    QPushButton#Primary:pressed {{ background: {primary_pressed}; border-color: {primary_pressed}; }}
    QPushButton#Primary:disabled {{ background: {p.raised}; border-color: {p.grid}; color: {p.ink_muted}; }}
    QPushButton#Danger {{ border-color: {p.critical}; color: {p.critical}; }}

    /* QAbstractSpinBox rather than QSpinBox: the decimal boxes on Next Week
       are QDoubleSpinBox, a sibling class the old selector never reached,
       so they drew unstyled next to every other input. */
    QComboBox, QLineEdit, QAbstractSpinBox {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {line};
        border-radius: {r["sm"]}px;
        padding: {s["snug"] - 2}px {s["step"] - 2}px;
        min-height: 18px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
    }}
    QComboBox:hover, QLineEdit:hover, QAbstractSpinBox:hover {{ border-color: {line_hover}; }}
    QComboBox:focus, QLineEdit:focus, QAbstractSpinBox:focus {{ border-color: {p.accent}; }}
    QComboBox:disabled, QLineEdit:disabled, QAbstractSpinBox:disabled {{ color: {p.ink_muted}; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        border: none;
        background: transparent;
        width: 16px;
    }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {hover}; }}
    /* Inputs living inside a table row: inset so they sit in the middle of
       the row with a little air, instead of filling it edge to edge. */
    QTableView QComboBox, QTableView QAbstractSpinBox {{
        margin: {s["tight"]}px {s["snug"] - 2}px;
        padding: {s["hair"]}px {s["snug"]}px;
        min-height: 0px;
        border-radius: {r["xs"]}px;
    }}

    /* Multi-line text (the predictions paste box, error details) sat on the
       bare page colour with no edge; it now matches the other inputs. */
    QPlainTextEdit, QTextEdit {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {line};
        border-radius: {r["sm"]}px;
        padding: {s["snug"] - 2}px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
    }}
    QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {line_hover}; }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {line};
        selection-background-color: {p.selection};
        outline: none;
    }}

    QListWidget {{
        background: {p.surface};
        border: 1px solid {line};
        border-radius: {r["md"]}px;
        outline: none;
    }}
    QListWidget::item {{ padding: {s["snug"]}px {s["step"]}px; border-radius: {r["sm"]}px; }}
    QListWidget::item:hover {{ background: {hover}; }}
    QListWidget::item:selected {{ background: {p.selection}; color: {p.ink}; }}

    QTabWidget::pane {{ border: 1px solid {line}; border-radius: {r["md"]}px; top: -1px; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.ink_muted};
        padding: {s["snug"]}px {s["room"]}px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; }}
    QTabBar::tab:selected {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}

    /* ---- the tabs above a grouped page (groups.py) ---- */
    #GroupTabs {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p.surface}, stop:1 {p.plane});
        border-bottom: 1px solid {p.grid};
    }}
    /* Which of the sidebar's places these tabs belong to. */
    #GroupKicker {{
        color: {brand};
        font-family: {DISPLAY_STACK};
        font-size: {LABEL["size"]}px;
        font-weight: {LABEL["weight"]};
        letter-spacing: {label_tracking}px;
        padding: 3px 14px 0 0;
        border-right: 1px solid {p.baseline};
        margin: 9px 10px 9px 0;
    }}
    QTabBar#GroupTabBar {{ background: transparent; }}
    QTabBar#GroupTabBar::tab {{
        font-family: {DISPLAY_STACK};
        font-size: {t["body"]}px;
        font-weight: 600;
        letter-spacing: 1px;
        padding: {s["step"] - 2}px {s["room"]}px {s["snug"] + 1}px {s["room"]}px;
        margin-right: {s["tight"]}px;
    }}
    QTabBar#GroupTabBar::tab:hover {{ background: {hover}; }}

    QScrollArea {{ border: none; background: {p.plane}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.baseline}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.baseline}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {p.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QProgressBar {{ background: {p.grid}; border: none; border-radius: {r["sm"]}px; }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: {r["sm"]}px; }}

    /* A slider: a hairline track, lit up to the handle. */
    QSlider::groove:horizontal {{ height: 4px; background: {p.grid}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {p.accent};
        border: 2px solid {p.surface};
        width: 14px;
        margin: -7px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{ background: {p.ink}; }}

    /* Tooltips carry a lot of the explanation in this app, so they are set
       for reading rather than for glancing. */
    /* The \u24d8 beside a figure: quiet until hovered or focused. */
    QToolButton#InfoIcon {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {r["sm"]}px;
        color: {p.ink_muted};
        font-size: {t["body"]}px;
        padding: 0 2px;
    }}
    QToolButton#InfoIcon:hover, QToolButton#InfoIcon:focus {{
        color: {p.accent};
        border-color: {p.accent};
    }}
    QToolTip {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {rule};
        border-radius: {r["sm"]}px;
        padding: {s["snug"]}px {s["step"]}px;
        font-size: {t["body"]}px;
    }}
    #Banner {{
        background: {mix(p.warning, p.raised, 0.07)};
        border: 1px solid {mix(p.warning, p.raised, 0.55)};
        border-radius: {r["md"]}px;
        padding: {s["hair"]}px;
    }}
    #Banner[tone="info"] {{
        background: {mix(p.accent, p.raised, 0.07)};
        border-color: {mix(p.accent, p.raised, 0.55)};
    }}
    #BannerIcon {{ color: {p.warning}; }}
    #Banner[tone="info"] #BannerIcon {{ color: {p.accent}; }}
    #Banner QPushButton#BannerToggle {{
        background: transparent;
        border: none;
        color: {p.accent};
        font-weight: 600;
        padding: 0 6px;
    }}
    #Banner QPushButton#BannerToggle:hover {{ color: {p.ink}; text-decoration: underline; }}

    /* ---- page states: loading, no data, a page that failed ---- */
    #StatePanel, #StateColumn {{ background: {p.plane}; }}
    #StateIcon {{ font-size: 40px; color: {p.ink_muted}; }}
    #StateIcon[tone="bad"] {{ color: {p.critical}; }}
    #StateTitle {{
        font-family: {DISPLAY_STACK};
        font-size: {t["title"] - 2}px;
        font-weight: 600;
        letter-spacing: 1px;
        color: {p.ink};
    }}
    #StateMessage {{ font-size: {t["body"]}px; color: {p.ink_secondary}; }}
    #StateProgress {{ background: {p.grid}; border-radius: {r["xs"]}px; }}
    #StateProgress::chunk {{ background: {p.accent}; border-radius: {r["xs"]}px; }}
    #StateDetails {{
        font-family: {MONO_STACK};
        font-size: {t["caption"]}px;
        color: {p.ink_secondary};
    }}

    /* ---- settings list (Ctrl+K) ---- */
    QDialog#CommandPalette {{
        background: {p.surface};
        border: 1px solid {p.baseline};
    }}
    QDialog#CommandPalette QLineEdit {{
        font-size: {t["heading"]}px;
        padding: {s["snug"]}px {s["step"]}px;
    }}
    QDialog#CommandPalette QListWidget {{ background: transparent; border: none; }}
    QDialog#CommandPalette QListWidget::item {{ color: {p.ink_secondary}; }}
    QDialog#CommandPalette QListWidget::item:selected {{ color: {p.ink}; }}

    /* ---- status bar ---- */
    QStatusBar {{ background: {p.surface}; color: {p.ink_muted}; border-top: 1px solid {p.grid}; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QPushButton {{
        background: transparent;
        border: none;
        color: {p.accent};
        font-weight: 600;
        padding: 0 10px;
    }}
    QStatusBar QPushButton:hover {{ color: {p.ink}; text-decoration: underline; }}

    QSplitter::handle {{ background: {p.grid}; }}
    QCheckBox {{ spacing: 7px; }}
    """
