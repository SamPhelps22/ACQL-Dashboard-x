"""The Chaos Simulator panel: one button, 10,000 Sundays, where you land.

Self-contained on purpose - it draws its own black, gold and blue, needs
nothing from the page around it but a season (`set_season`), and can be
dropped into any layout. The numbers come from acql.pool.chaos.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..pool import chaos, me

INK = "#05070c"
PANEL = "#0b111c"
EDGE = "#1c2a40"
GOLD = "#e8b64c"
BLUE = "#3aa0ff"
TEXT = "#e9eef7"
MUTED = "#8091ab"
#: How long the animation runs, whatever the sums take.
ANIMATION_MS = 1500

STYLE = f"""
QFrame#ChaosPanel {{ background: {INK}; border: 1px solid {EDGE}; border-radius: 10px; }}
QFrame#ChaosPanel QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#ChaosTitle {{ color: {GOLD}; font-size: 15px; font-weight: 700; letter-spacing: 3px; }}
QLabel#ChaosMuted {{ color: {MUTED}; font-size: 12px; }}
QLabel#ChaosKicker {{ color: {MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QLabel#ChaosValue {{ color: {TEXT}; font-size: 22px; font-weight: 700; }}
QLabel#ChaosValueGold {{ color: {GOLD}; font-size: 22px; font-weight: 700; }}
QLabel#ChaosDetail {{ color: {MUTED}; font-size: 11px; }}
QLabel#ChaosLeverage {{ color: {TEXT}; font-size: 13px; }}
QFrame#ChaosTile {{ background: {PANEL}; border: 1px solid {EDGE}; border-radius: 6px; }}
QPushButton#ChaosGo {{
    color: {INK}; background: {GOLD}; border: none; border-radius: 6px;
    font-weight: 800; letter-spacing: 2px; padding: 9px 22px;
}}
QPushButton#ChaosGo:hover {{ background: #f4c865; }}
QPushButton#ChaosGo:disabled {{ background: #6b5a31; color: #1a1408; }}
QComboBox#ChaosWho {{
    color: {TEXT}; background: {PANEL}; border: 1px solid {EDGE}; border-radius: 6px;
    padding: 6px 10px; min-width: 150px;
}}
QComboBox#ChaosWho QAbstractItemView {{ color: {TEXT}; background: {PANEL}; selection-background-color: {EDGE}; }}
"""


class _Storm(QWidget):
    """The animation: two rings chasing each other round a ticking scoreboard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._start = 0.0
        self._digits = ["0"] * 6
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def begin(self) -> None:
        self._start = time.monotonic()
        self._timer.start()

    def end(self) -> None:
        self._timer.stop()

    def progress(self) -> float:
        return min(1.0, (time.monotonic() - self._start) * 1000 / ANIMATION_MS)

    def _tick(self) -> None:
        self._digits = [str(random.randint(0, 9)) for _ in self._digits]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(INK))
        t = (time.monotonic() - self._start) if self._start else 0.0
        done = self.progress()
        cx, cy = self.width() / 2, self.height() / 2 - 10
        r = min(self.width(), self.height()) * 0.32

        # faint grid, like a radar screen
        p.setPen(QPen(QColor(EDGE), 1))
        for k in range(1, 4):
            p.drawEllipse(QRectF(cx - r * k / 3, cy - r * k / 3, 2 * r * k / 3, 2 * r * k / 3))

        for colour, radius, speed, span in ((GOLD, r, 420, 110), (BLUE, r * 0.8, -560, 80),
                                             (GOLD, r * 0.6, 760, 40)):
            pen = QPen(QColor(colour), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            box = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
            p.drawArc(box, int((t * speed) % 360 * 16), int(span * 16))

        # orbiting sparks
        for k in range(10):
            a = t * (2.2 + k * 0.17) + k
            d = r * (0.35 + 0.65 * ((k * 37) % 10) / 10)
            glow = QColor(BLUE if k % 2 else GOLD)
            glow.setAlpha(120 + int(120 * abs(math.sin(t * 6 + k))))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(cx + d * math.cos(a) - 2, cy + d * math.sin(a) - 2, 4, 4))

        font = QFont(self.font())
        font.setPointSize(20)
        font.setBold(True)
        font.setFamily("Consolas")
        p.setFont(font)
        p.setPen(QColor(TEXT))
        sims = f"{int(chaos.SIMULATIONS * done):,}"
        p.drawText(QRectF(0, cy - 18, self.width(), 36), Qt.AlignmentFlag.AlignCenter, sims)

        small = QFont(self.font())
        small.setPointSize(8)
        small.setBold(True)
        small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(small)
        p.setPen(QColor(GOLD))
        p.drawText(QRectF(0, cy + r + 14, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   "PLAYING SUNDAYS  " + " ".join(self._digits))

        # progress rail
        w = self.width() * 0.5
        x0, y0 = (self.width() - w) / 2, self.height() - 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(EDGE))
        p.drawRoundedRect(QRectF(x0, y0, w, 4), 2, 2)
        p.setBrush(QColor(BLUE))
        p.drawRoundedRect(QRectF(x0, y0, w * done, 4), 2, 2)
        p.end()


class _Finishes(QWidget):
    """Chance of each finishing place, as bars; first is gold."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.finishes: tuple[float, ...] = ()
        self.expected = 0.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.finishes)
        if not n:
            return
        top = max(self.finishes) or 1.0
        left, bottom, h = 4, self.height() - 18, self.height() - 30
        step = (self.width() - 8) / n
        for i, share in enumerate(self.finishes):
            bar = h * share / top
            colour = QColor(GOLD if i == 0 else BLUE)
            if i and share < top * 0.05:
                colour.setAlpha(110)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
            p.drawRoundedRect(QRectF(left + i * step + 1, bottom - bar, max(2.0, step - 2), bar), 1.5, 1.5)
        # the average finish, marked
        x = left + (self.expected - 0.5) * step
        p.setPen(QPen(QColor(TEXT), 1, Qt.PenStyle.DashLine))
        p.drawLine(int(x), 6, int(x), bottom)
        f = QFont(self.font())
        f.setPointSize(7)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        for place in (1, 5, 10, 15, 20, 25, 30, 35):
            if place <= n:
                p.drawText(QRectF(left + (place - 1) * step - 10, bottom + 3, step + 20, 14),
                           Qt.AlignmentFlag.AlignCenter, chaos.ordinal(place))
        p.end()


def _tile(kicker: str, gold: bool = False) -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("ChaosTile")
    box = QVBoxLayout(frame)
    box.setContentsMargins(12, 8, 12, 10)
    box.setSpacing(2)
    k = QLabel(kicker.upper())
    k.setObjectName("ChaosKicker")
    v = QLabel("-")
    v.setObjectName("ChaosValueGold" if gold else "ChaosValue")
    d = QLabel("")
    d.setObjectName("ChaosDetail")
    d.setWordWrap(True)
    for w in (k, v, d):
        box.addWidget(w)
    return frame, v, d


class ChaosPanel(QFrame):
    """SIMULATE SUNDAY, then expected score, finishes, best and worst, leverage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ChaosPanel")
        self.setStyleSheet(STYLE)
        self.season = None
        self.week: int | None = None
        self._sim: chaos.Simulation | None = None
        self._sim_for: tuple | None = None
        self._notes: list[str] = []
        self._ready = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("CHAOS SIMULATOR")
        title.setObjectName("ChaosTitle")
        self.subtitle = QLabel("10,000 Sundays, played on the market's odds.")
        self.subtitle.setObjectName("ChaosMuted")
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.who = QComboBox()
        self.who.setObjectName("ChaosWho")
        self.who.currentIndexChanged.connect(self._show_report)
        head.addWidget(self.who)
        self.go = QPushButton("SIMULATE SUNDAY")
        self.go.setObjectName("ChaosGo")
        self.go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go.clicked.connect(self.run)
        head.addWidget(self.go)
        outer.addLayout(head)

        self.stack = QStackedWidget()
        idle = QLabel("Press SIMULATE SUNDAY to play the week out 10,000 times.")
        idle.setObjectName("ChaosMuted")
        idle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        idle.setMinimumHeight(80)
        self.storm = _Storm()
        self.results = self._build_results()
        for w in (idle, self.storm, self.results):
            self.stack.addWidget(w)
        outer.addWidget(self.stack)

        self._clock = QTimer(self)
        self._clock.setSingleShot(True)
        self._clock.timeout.connect(self._finish)

    def _build_results(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.t_score = _tile("Expected score")
        self.t_first = _tile("Chance of 1st", gold=True)
        self.t_finish = _tile("Average finish")
        self.t_best = _tile("Best case")
        self.t_worst = _tile("Worst case")
        for col, t in enumerate((self.t_score, self.t_first, self.t_finish, self.t_best, self.t_worst)):
            grid.addWidget(t[0], 0, col)
            grid.setColumnStretch(col, 1)
        box.addLayout(grid)
        k = QLabel("WHERE YOU FINISH")
        k.setObjectName("ChaosKicker")
        box.addWidget(k)
        self.bars = _Finishes()
        box.addWidget(self.bars)
        self.leverage = QLabel("")
        self.leverage.setObjectName("ChaosLeverage")
        self.leverage.setWordWrap(True)
        self.leverage.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.leverage)
        self.basis = QLabel("")
        self.basis.setObjectName("ChaosDetail")
        self.basis.setWordWrap(True)
        box.addWidget(self.basis)
        return page

    # ---- wiring ---------------------------------------------------------------
    def set_season(self, season, week: int | None = None) -> None:
        """Give the panel a season (and optionally the week; default the coming one)."""
        from .. import analytics

        self.season = season
        self.week = week if week is not None else analytics.upcoming_week(season)
        self.subtitle.setText(f"Week {self.week}: 10,000 Sundays, played on the market's odds.")
        names = sorted((p.display for p in (getattr(season, "players", None) or {}).values()),
                       key=str.casefold)
        mine = me.display(season) or me.NAME
        if mine in names:
            names.remove(mine)
        names.insert(0, mine)
        current = self.who.currentText()
        self.who.blockSignals(True)
        self.who.clear()
        self.who.addItems(names)
        self.who.setCurrentIndex(max(0, self.who.findText(current)) if current else 0)
        self.who.blockSignals(False)
        if self._sim_for != self._key():
            self._sim = None
            self.stack.setCurrentIndex(0)

    def _key(self) -> tuple:
        return (id(self.season), self.week)

    def run(self) -> None:
        self.go.setEnabled(False)
        self._ready = False
        self.stack.setCurrentWidget(self.storm)
        self.storm.begin()
        self._clock.start(ANIMATION_MS)
        QTimer.singleShot(30, self._compute)

    def _compute(self) -> None:
        try:
            games, coaches, self._notes = chaos.build(self.season, self.week or 1)
            names = {c.name.casefold() for c in coaches}
            if self.who.currentText() and self.who.currentText().casefold() not in names:
                self.who.addItem(self.who.currentText())
            self._sim = chaos.simulate(games, coaches) if games else None
        except Exception as exc:  # noqa: BLE001 - the panel says so, the page lives on
            self._sim, self._notes = None, [f"Couldn't simulate: {exc}"]
        self._sim_for = self._key()
        self._ready = True
        if not self._clock.isActive():
            self._finish()

    def _finish(self) -> None:
        if not self._ready:
            return              # sums still going: _compute calls back
        self.storm.end()
        self.go.setEnabled(True)
        self.stack.setCurrentWidget(self.results)
        self._show_report()

    def _show_report(self) -> None:
        if self._sim is None:
            if self._ready:
                self.leverage.setText("No market lines stored for this week yet - "
                                      "nothing to simulate. " + " ".join(self._notes[:2]))
                self.basis.setText("")
            return
        try:
            r = chaos.report(self._sim, self.who.currentText())
        except KeyError:
            return
        self.t_score[1].setText(f"{r.expected_score:.1f}")
        self.t_score[2].setText(f"of {len(self._sim.games)} games")
        self.t_first[1].setText(f"{r.first:.1%}")
        self.t_first[2].setText(f"{r.first_alone:.1%} outright · fair share {1 / r.field_size:.1%}")
        self.t_finish[1].setText(f"{r.expected_finish:.1f}")
        lo, hi = r.typical_range
        self.t_finish[2].setText(f"usually {chaos.ordinal(lo)} to {chaos.ordinal(hi)}")
        self.t_best[1].setText(chaos.ordinal(r.best_finish))
        self.t_best[2].setText(f"{r.best_score} right · {r.best_chance:.1%} of Sundays")
        self.t_worst[1].setText(chaos.ordinal(r.worst_finish))
        self.t_worst[2].setText(f"{r.worst_score} right · {r.worst_chance:.1%} of Sundays")
        self.bars.finishes, self.bars.expected = r.finishes, r.expected_finish
        self.bars.update()
        if r.leverage is not None:
            s = r.leverage
            good, bad = ((s.if_home, s.finish_if_home), (s.if_away, s.finish_if_away))
            if bad[1] < good[1]:
                good, bad = bad, good
            self.leverage.setText(
                f"<span style='color:{GOLD};font-weight:700'>LEVERAGE GAME</span>&nbsp; "
                f"{s.game}: credited to <b>{good[0]}</b>, you average "
                f"<span style='color:{GOLD}'>{good[1]:.1f}</span>; to <b>{bad[0]}</b>, "
                f"<span style='color:{BLUE}'>{bad[1]:.1f}</span>. A {s.size:.1f}-place swing."
            )
        from collections import Counter
        bases = Counter(c.basis for c in self._sim.coaches)
        how = {chaos.BASIS_SHEET: "from their pick sheet", chaos.BASIS_HISTORY: "from their pick history",
               chaos.BASIS_FAVOURITES: "assumed to pick favourites"}
        field = " · ".join(f"{n} {how[b]}" for b, n in bases.most_common())
        self.basis.setText(
            f"{r.coach}'s card: {r.basis}. Field: {field}. Results drawn from the "
            f"market's lines and moneylines, never Deadeye. Regular picks only; Big Losers "
            f"not simulated. {r.sims:,} Sundays, fixed seed."
        )
