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


def stylesheet(p: Palette) -> str:
    """Qt stylesheet for the whole application."""
    return f"""
    * {{ font-family: {FONT_STACK}; }}

    QWidget {{
        background: {p.plane};
        color: {p.ink};
        font-size: 13px;
    }}

    QMainWindow, QDialog {{ background: {p.plane}; }}

    /* ---- left navigation ---- */
    #Sidebar {{
        background: {p.surface};
        border-right: 1px solid {p.grid};
    }}
    #SidebarTitle {{
        color: {p.ink};
        font-size: 17px;
        font-weight: 700;
        padding: 18px 16px 2px 16px;
    }}
    #SidebarSubtitle {{
        color: {p.ink_muted};
        font-size: 12px;
        padding: 0 16px 14px 16px;
    }}
    QPushButton#NavButton {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        color: {p.ink_secondary};
        text-align: left;
        padding: 11px 16px;
        font-size: 13.5px;
    }}
    QPushButton#NavButton:hover {{
        background: {p.raised};
        color: {p.ink};
    }}
    QPushButton#NavButton:checked {{
        background: {p.raised};
        border-left: 3px solid {p.accent};
        color: {p.ink};
        font-weight: 600;
    }}

    /* ---- cards & headings ---- */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.grid};
        border-radius: 10px;
    }}
    #PageTitle {{ font-size: 21px; font-weight: 700; color: {p.ink}; }}
    #PageSubtitle {{ font-size: 13px; color: {p.ink_muted}; }}
    #CardTitle {{
        font-size: 11px;
        font-weight: 700;
        color: {p.ink_muted};
        letter-spacing: 0.9px;
    }}
    #StatValue {{ font-size: 30px; font-weight: 700; color: {p.ink}; }}
    #StatDetail {{ font-size: 12px; color: {p.ink_secondary}; }}
    #Good {{ color: {p.good}; font-weight: 600; }}
    #Bad {{ color: {p.critical}; font-weight: 600; }}
    #Muted {{ color: {p.ink_muted}; }}

    /* ---- tables ---- */
    QTableView {{
        background: {p.surface};
        alternate-background-color: {p.raised};
        gridline-color: {p.grid};
        border: 1px solid {p.grid};
        border-radius: 8px;
        selection-background-color: {p.selection};
        selection-color: {p.ink};
        font-size: 13px;
    }}
    QTableView::item {{ padding: 5px 8px; border: none; }}
    QHeaderView::section {{
        background: {p.raised};
        color: {p.ink_muted};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {p.grid};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QHeaderView::section:hover {{ color: {p.ink}; }}
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
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:disabled {{ color: {p.ink_muted}; border-color: {p.grid}; }}
    QPushButton#Primary {{
        background: {p.accent};
        border-color: {p.accent};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {p.selection}; }}
    QPushButton#Primary:disabled {{ background: {p.raised}; color: {p.ink_muted}; }}
    QPushButton#Danger {{ border-color: {p.critical}; color: {p.critical}; }}

    QComboBox, QLineEdit, QSpinBox {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        border-radius: 7px;
        padding: 6px 10px;
        min-height: 18px;
    }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {p.accent}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        selection-background-color: {p.selection};
        outline: none;
    }}

    QTabWidget::pane {{ border: 1px solid {p.grid}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.ink_muted};
        padding: 8px 16px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {p.ink}; border-bottom: 2px solid {p.accent}; }}

    QScrollArea {{ border: none; background: {p.plane}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.baseline}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.ink_muted}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p.baseline}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QToolTip {{
        background: {p.raised};
        color: {p.ink};
        border: 1px solid {p.grid};
        border-radius: 6px;
        padding: 6px 9px;
    }}
    #Banner {{
        background: {p.raised};
        border: 1px solid {p.warning};
        border-radius: 8px;
        padding: 2px;
    }}
    QStatusBar {{ background: {p.surface}; color: {p.ink_muted}; border-top: 1px solid {p.grid}; }}
    QSplitter::handle {{ background: {p.grid}; }}
    QCheckBox {{ spacing: 7px; }}
    """
