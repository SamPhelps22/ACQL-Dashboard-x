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

from .iconset import ICONS
from .tokens import ICON_STROKE

#: Stroke width on the 24-unit grid - the same for every icon, here and on the website.
STROKE = ICON_STROKE
#: Screen densities each icon is drawn for.
DENSITIES = (1.0, 2.0, 3.0)

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
