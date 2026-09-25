"""Colour tokens and the Qt stylesheet.

Both palettes are selected rather than generated: the dark set is the same
eight hues re-stepped for the dark surface, not an automatic inversion of the
light set. The categorical order is fixed and assigned by slot, never cycled,
so a player keeps their colour when a filter changes the series count.
"""

from __future__ import annotations

from dataclasses import dataclass


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

    def series_color(self, index: int) -> str:
        """Fixed-order slot assignment; past the last slot, fold to muted."""
        if 0 <= index < len(self.series):
            return self.series[index]
        return self.ink_muted


DARK = Palette(
    name="dark",
    surface="#1a1a19",
    plane="#0d0d0d",
    raised="#232322",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    grid="#2c2c2a",
    baseline="#383835",
    border="rgba(255,255,255,0.10)",
    accent="#3987e5",
    series=("#3987e5", "#d95926", "#199e70", "#c98500",
            "#d55181", "#008300", "#9085e9", "#e66767"),
    sequential=("#0d366b", "#184f95", "#256abf", "#2a78d6",
                "#3987e5", "#5598e7", "#86b6ef", "#b7d3f6", "#cde2fb"),
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    selection="#1c5cab",
)

LIGHT = Palette(
    name="light",
    surface="#fcfcfb",
    plane="#f9f9f7",
    raised="#ffffff",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#898781",
    grid="#e1e0d9",
    baseline="#c3c2b7",
    border="rgba(11,11,11,0.10)",
    accent="#2a78d6",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
            "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    sequential=("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef",
                "#5598e7", "#3987e5", "#256abf", "#184f95", "#0d366b"),
    good="#0ca30c",
    warning="#fab219",
    serious="#ec835a",
    critical="#d03b3b",
    selection="#cde2fb",
)

PALETTES = {"dark": DARK, "light": LIGHT}

FONT_STACK = '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
# Numbers read better when they line up in a column, which the UI font's
# proportional digits refuse to do. Every figure in a tile or a table is set
# in this instead, so a column of them is scannable.
NUMERIC_STACK = '"SF Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'

# One scale, used everywhere. Sizes were ad hoc before - 13, 13.5, 12.5, 12,
# 11.5 all appeared - which is invisible on one page and incoherent across
# twelve. Each step is about 1.15x the one below it, and the names say what
# the step is for rather than how big it is.
TYPE = {
    "display": 30,     # the one number a tile exists to show
    "title": 22,       # page titles
    "heading": 16,     # a name inside a card
    "body": 13,        # everything you read
    "label": 12,       # column headings, card titles
    "caption": 11.5,   # footnotes, units, the small print
}
# Spacing steps, so margins and gaps come from a ladder rather than taste.
SPACE = {"hair": 2, "tight": 4, "snug": 8, "step": 12, "room": 18, "gap": 24}
RADIUS = {"chip": 6, "control": 7, "card": 10, "tile": 12}


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


def stylesheet(p: Palette) -> str:
    """Qt stylesheet for the whole application."""
    hover = mix(p.ink, p.surface, 0.07)       # neutral hover wash
    active = mix(p.accent, p.surface, 0.18)   # the current page in the sidebar
    pressed = mix(p.ink, p.raised, 0.12)      # a button while it is held down
    # The primary button's hover used to borrow the selection colour, which
    # in the light theme is a pale blue: white text on it measured 1.3:1 and
    # all but vanished. It now deepens the accent itself, which raises the
    # label's contrast in both themes (light 4.4 -> 5.7, dark 3.6 -> 4.7).
    primary_hover = mix(p.accent, "#000000", 0.86)
    primary_pressed = mix(p.accent, "#000000", 0.74)
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
        background: {p.surface};
        border-right: 1px solid {p.grid};
    }}
    #SidebarTitle {{
        color: {p.ink};
        font-size: {t["heading"]}px;
        font-weight: 700;
        padding: 22px 24px 2px 24px;
    }}
    #SidebarSubtitle {{
        color: {p.ink_muted};
        font-size: {t["label"]}px;
        padding: 0 24px 16px 24px;
    }}
    #Sidebar QPushButton#NavButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: {p.ink_secondary};
        text-align: left;
        padding: 10px 14px;
        margin: 1px 10px;
        font-size: {t["body"]}px;
    }}
    #Sidebar QPushButton#NavButton:hover,
    #Sidebar QPushButton#NavButton:focus {{
        background: {hover};
        color: {p.ink};
    }}
    #Sidebar QPushButton#NavButton:checked {{
        background: {active};
        color: {p.ink};
        font-weight: 600;
    }}

    /* Refresh / theme / jump: quiet outlines, so the nav stays the loudest thing. */
    #Sidebar QPushButton {{
        background: transparent;
        border: 1px solid {p.grid};
        border-radius: 8px;
        color: {p.ink_secondary};
        text-align: left;
        padding: 7px 12px;
    }}
    #Sidebar QPushButton:hover {{
        background: {hover};
        border-color: {p.baseline};
        color: {p.ink};
    }}
    #Sidebar QPushButton:disabled {{ color: {p.ink_muted}; }}

    /* ---- cards & headings ---- */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.grid};
        border-radius: 10px;
    }}
    /* Headline numbers sit one step above the content cards. */
    #StatTile {{
        background: {p.raised};
        border: 1px solid {p.grid};
        border-radius: 12px;
    }}
    /* An award tile is a stat tile with a hairline down its left edge tinted
       by tone, so a good or bad award reads at a glance without the text
       itself having to be coloured. */
    #AwardTile {{
        background: {p.raised};
        border: 1px solid {p.grid};
        border-left: 3px solid {p.baseline};
        border-radius: 10px;
    }}
    #AwardTile[tone="good"] {{ border-left-color: {p.good}; }}
    #AwardTile[tone="bad"] {{ border-left-color: {p.critical}; }}
    #AwardIcon {{ font-size: {t["heading"]}px; }}
    #AwardWinner {{ font-size: {t["heading"]}px; font-weight: 700; color: {p.ink}; }}
    #AwardDetail {{ font-size: {t["caption"]}px; color: {p.ink_muted}; }}
    /* The number reads as a chip so it never competes with the name. */
    #AwardValue {{
        background: {mix(p.ink, p.raised, 0.08)};
        border-radius: 6px;
        padding: 2px 8px;
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

    #PageTitle {{ font-size: {t["title"]}px; font-weight: 700; color: {p.ink}; }}
    #PageSubtitle {{ font-size: {t["body"]}px; color: {p.ink_muted}; }}
    #CardTitle {{
        font-size: {t["label"]}px;
        font-weight: 600;
        color: {p.ink_secondary};
    }}
    #StatValue {{
        font-family: {NUMERIC_STACK};
        font-size: {t["display"]}px;
        font-weight: 700;
        color: {p.ink};
    }}
    /* A tile whose headline is a name rather than a number needs the room
       more than it needs the size, so it steps down instead of eliding. */
    #StatValue[length="long"] {{ font-size: {t["title"]}px; }}
    #StatValue[length="verylong"] {{ font-size: {t["heading"]}px; }}
    /* And a headline with no digit in it is a phrase, not a figure. */
    #StatValue[kind="text"] {{ font-family: {FONT_STACK}; letter-spacing: -0.2px; }}
    #StatDetail {{ font-size: {t["caption"]}px; color: {p.ink_secondary}; }}
    #StatDetail[tone="good"] {{ color: {p.good}; font-weight: 600; }}
    #StatDetail[tone="bad"] {{ color: {p.critical}; font-weight: 600; }}
    /* ---- small shared pieces ---- */
    /* A chip: one number with a tone behind it, for a figure that has to be
       read next to words without shouting over them. */
    #Pill {{
        background: {mix(p.ink, p.raised, 0.08)};
        border-radius: {r["chip"]}px;
        padding: 2px 8px;
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
        border: 1px solid {p.grid};
        border-radius: 10px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
        font-size: 13px;
    }}
    QTableView::item {{ padding: 5px 8px; border: none; }}
    /* There was a hover rule here that lifted the row under the cursor. It
       reads well and costs too much: a `::item` state rule makes Qt style and
       repaint cells one at a time as the mouse moves across a table, and with
       thirty-five coaches against seventeen columns that was enough to make
       the whole window feel slow. Alternating rows carry the eye instead. */
    QHeaderView::section {{
        background: {p.raised};
        color: {p.ink_muted};
        padding: 9px 10px;
        border: none;
        border-bottom: 1px solid {p.grid};
        font-size: 12px;
        font-weight: 600;
    }}
    QHeaderView::section:hover {{ color: {p.ink}; background: {mix(p.ink, p.raised, 0.05)}; }}
    /* The sort arrow sits at the right of its heading. Left to the Windows 11
       style it was drawn centred ABOVE the heading text, where it read as a
       stray mark floating over every table. */
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 9px;
        height: 9px;
        right: 2px;
    }}
    /* The sorted column keeps a hairline under it, which is quieter than Qt's
       default arrow and survives a narrow column. */
    QHeaderView::section:checked {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}
    QTableCornerButton::section {{ background: {p.raised}; border: none; }}

    /* ---- controls ---- */
    QPushButton {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        border-radius: 7px;
        padding: 7px 15px;
        font-size: 13px;
    }}
    QPushButton:hover, QPushButton:focus {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {pressed}; }}
    QPushButton:disabled {{ color: {p.ink_muted}; border-color: {p.grid}; }}
    QPushButton#Primary {{
        background: {p.accent};
        border-color: {p.accent};
        color: #ffffff;
        font-weight: 600;
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
        border: 1px solid {p.grid};
        border-radius: 7px;
        padding: 6px 10px;
        min-height: 18px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
    }}
    QComboBox:hover, QLineEdit:hover, QAbstractSpinBox:hover {{ border-color: {p.baseline}; }}
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
        margin: 4px 6px;
        padding: 2px 8px;
        min-height: 0px;
        border-radius: 6px;
    }}

    /* Multi-line text (the predictions paste box, error details) sat on the
       bare page colour with no edge; it now matches the other inputs. */
    QPlainTextEdit, QTextEdit {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        border-radius: 8px;
        padding: 6px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        selection-background-color: {p.selection};
        outline: none;
    }}

    QListWidget {{
        background: {p.surface};
        border: 1px solid {p.grid};
        border-radius: 8px;
        outline: none;
    }}
    QListWidget::item {{ padding: 8px 12px; border-radius: 6px; }}
    QListWidget::item:hover {{ background: {hover}; }}
    QListWidget::item:selected {{ background: {p.selection}; color: {p.ink}; }}

    QTabWidget::pane {{ border: 1px solid {p.grid}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.ink_muted};
        padding: 8px 16px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; }}
    QTabBar::tab:selected {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}

    /* ---- the tabs above a grouped page (groups.py) ---- */
    #GroupTabs {{
        background: {p.plane};
        border-bottom: 1px solid {p.grid};
    }}
    QTabBar#GroupTabBar {{ background: transparent; }}
    QTabBar#GroupTabBar::tab {{
        font-size: {t["body"]}px;
        font-weight: 600;
        padding: 9px 18px 8px 18px;
        margin-right: 4px;
    }}

    QScrollArea {{ border: none; background: {p.plane}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.baseline}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.ink_muted}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.baseline}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {p.ink_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QProgressBar {{ background: {p.grid}; border: none; border-radius: 4px; }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}

    /* Tooltips carry a lot of the explanation in this app, so they are set
       for reading rather than for glancing. */
    QToolTip {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.baseline};
        border-radius: {r["chip"]}px;
        padding: {s["snug"]}px {s["step"]}px;
        font-size: {t["body"]}px;
    }}
    #Banner {{
        background: {mix(p.warning, p.raised, 0.07)};
        border: 1px solid {mix(p.warning, p.raised, 0.55)};
        border-radius: 8px;
        padding: 2px;
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
    #StateTitle {{ font-size: {t["title"]}px; font-weight: 700; color: {p.ink}; }}
    #StateMessage {{ font-size: {t["body"]}px; color: {p.ink_secondary}; }}
    #StateProgress {{ background: {p.grid}; border-radius: 3px; }}
    #StateProgress::chunk {{ background: {p.accent}; border-radius: 3px; }}
    #StateDetails {{
        font-family: {NUMERIC_STACK};
        font-size: {t["caption"]}px;
        color: {p.ink_secondary};
    }}

    /* ---- quick switcher (Ctrl+K) ---- */
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
