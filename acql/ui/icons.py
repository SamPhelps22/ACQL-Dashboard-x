"""One icon family for the whole dashboard, drawn here rather than borrowed.

The sidebar used to mark its places with emoji: nine pictures from nine
different hands, each in its own colours, none of which followed the theme.
These are one family instead - every icon on the same 24-unit grid, the same
stroke, round ends, no fill - and they take whatever colour the theme gives
them, so the current place can light up and the rest stay quiet.

Each icon is a few SVG shapes; Qt's SVG renderer draws them at whatever size
and screen density is asked for. Should that renderer be missing from a build,
`icon` and `pixmap` hand back empty ones and the labels stand on their own.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:  # noqa: BLE001 - a build without the SVG module shows labels alone
    QSvgRenderer = None

#: Stroke width on the 24-unit grid - the same for every icon.
STROKE = 1.7
#: Screen densities each icon is drawn for.
DENSITIES = (1.0, 2.0, 3.0)

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
    # Operation Sunday's own mark: the ball in the sights
    "mark": (
        '<circle cx="12" cy="12" r="8.6"/>'
        '<path d="M12 .9v4.6"/><path d="M12 18.5v4.6"/><path d="M.9 12h4.6"/><path d="M18.5 12h4.6"/>'
        '<path d="M12 5.4Q19 12 12 18.6Q5 12 12 5.4z"/>'
        '<path d="M12 9.6v4.8"/><path d="M10.9 10.9h2.2"/><path d="M10.9 13.1h2.2"/>'
    ),
}

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{colour}" '
        'stroke-width="{weight}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def pixmap(name: str, colour: str, size: int = 20, density: float = 2.0, weight: float = STROKE) -> QPixmap:
    """One icon in one colour, `size` points square, drawn for a screen of that density."""
    side = max(1, int(round(size * density)))
    image = QPixmap(side, side)
    image.fill(Qt.GlobalColor.transparent)
    body = ICONS.get(name)
    if QSvgRenderer is not None and body:
        svg = _SVG.format(colour=colour, weight=weight, body=body.replace("{colour}", colour))
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, side, side))
        painter.end()
    image.setDevicePixelRatio(density)
    return image


def icon(name: str, colour: str, lit: str | None = None, size: int = 20) -> QIcon:
    """An icon for a button: `colour` at rest, `lit` while the button is the
    one chosen. Empty when the icon can't be drawn."""
    made = QIcon()
    if QSvgRenderer is None or name not in ICONS:
        return made
    lit = lit or colour
    for density in DENSITIES:
        resting, chosen = pixmap(name, colour, size, density), pixmap(name, lit, size, density)
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected, QIcon.Mode.Disabled):
            made.addPixmap(resting, mode, QIcon.State.Off)
            made.addPixmap(chosen, mode, QIcon.State.On)
    return made
