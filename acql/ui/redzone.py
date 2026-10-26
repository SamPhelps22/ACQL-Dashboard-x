"""RedZone mode: a frame around a stream playing underneath it.

The scores ribbon runs along the top, the pool's standings down the right,
and the middle is a real hole in the window (a mask), so RedZone playing in
Chrome or the YouTube TV app shows through it and takes the clicks. The
stream itself is never played here: those services use copy protection the
dashboard's browser cannot play.

Fed by the window's LiveFeed, like Cinema mode, so nothing is fetched twice.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import places
from ..pool import gameday as GD
from ..pool import livestate as LS
from . import icons, teamlogos
from .cinema import set_prop
from .cinema import Changes, Leaderboard, stylesheet
from .ribbon import ScoreboardRibbon

#: The standings column on the right.
SIDE_WIDTH = 300
#: The thin gold edge drawn round the hole.
EDGE = 2
#: How much of the stream window's top is tucked up behind the scores bar
#: (browser bars and the site's menu), remembered; ▲/▼ nudge it.
#: The band under the stream: at least this tall; taller when the 16:9 picture leaves more room.
BAND_MIN = 90
#: How many 'just happened' lines the band shows.
BAND_RECENT = 3
TRIM_KEY = "redzone/trim"
TRIM_DEFAULT, TRIM_STEP = 170, 20


class RedZoneWindow(QWidget):
    closed = Signal()

    def __init__(self, window, feed, palette) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.window_ = window
        self.feed = feed
        self.palette_ = palette
        self.setObjectName("Cinema")
        self.setWindowTitle(f"{places.BRAND} – RedZone")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.ribbon = ScoreboardRibbon(palette)
        self.ribbon.cinema_btn.hide()
        self.ribbon.redzone_btn.hide()
        outer.addWidget(self.ribbon)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        middle = QVBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.hole = QWidget()              # where the stream shows through
        self.hole.setObjectName("RedZoneHole")
        middle.addWidget(self.hole, 1)
        middle.addWidget(self._build_band())
        body.addLayout(middle, 1)
        body.addWidget(self._build_side())
        outer.addLayout(body, 1)
        self.restyle(palette)

    def _build_band(self) -> QWidget:
        """Under the stream: your picks as logos (green winning, red losing,
        grey to come) and the last few things that happened."""
        band = QFrame()
        band.setObjectName("RedZoneBand")
        band.setFixedHeight(BAND_MIN)
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.picks_head = QLabel("MY PICKS")
        self.picks_head.setObjectName("CinemaHeading")
        left.addWidget(self.picks_head)
        self.picks_row = QHBoxLayout()
        self.picks_row.setSpacing(6)
        left.addLayout(self.picks_row)
        left.addStretch(1)
        row.addLayout(left)
        row.addStretch(1)
        right = QVBoxLayout()
        right.setSpacing(4)
        head = QLabel("JUST HAPPENED")
        head.setObjectName("CinemaHeading")
        right.addWidget(head)
        self.recent = QLabel("")
        self.recent.setObjectName("RedZoneRecent")
        self.recent.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.recent, 1)
        row.addLayout(right)
        self.band = band
        self.chips: list[tuple[QLabel, QLabel]] = []
        return band

    def _show_band(self, you) -> None:
        states = sorted(self.feed.states, key=lambda s: (s.kickoff or 0, s.index))
        picked = [(st, you.picks.get(st.index, GD.NOBODY)) for st in states] if you is not None else []
        picked = [(st, side) for st, side in picked if side != GD.NOBODY]
        while len(self.chips) > len(picked):
            logo, word = self.chips.pop()
            logo.parentWidget().deleteLater()
        while len(self.chips) < len(picked):
            cell = QFrame()
            cell.setObjectName("RedZonePick")
            box = QVBoxLayout(cell)
            box.setContentsMargins(4, 3, 4, 3)
            box.setSpacing(1)
            logo, word = QLabel(), QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word.setObjectName("RedZonePickWord")
            box.addWidget(logo)
            box.addWidget(word)
            self.picks_row.addWidget(cell)
            self.chips.append((logo, word))
        winning = losing = 0
        for (logo, word), (st, side) in zip(self.chips, picked):
            team = st.team(side)
            pix = teamlogos.pixmap(team, 30)
            if pix is not None:
                logo.setPixmap(pix)
            else:
                logo.setText(str(team)[:3].upper())
            if st.state in ("in", "final") and st.leader != GD.NOBODY:
                status = "win" if st.leader == side else "lose"
                winning += status == "win"
                losing += status == "lose"
            elif st.state in ("in", "final"):
                status = "even"
            else:
                status = "pre"
            word.setText({"pre": (LS.kickoff_et(st.kickoff).split(" ") + [""])[1] if st.kickoff else "–",
                          "even": "EVEN"}.get(status, "FINAL" if st.state == "final" else (st.clock or "LIVE").split(" ")[0]))
            set_prop(logo.parentWidget(), "status", status)
            logo.parentWidget().setToolTip(f"{st.game.label} · your pick {team} · line {st.line_text()}")
        self.picks_head.setText(f"MY PICKS · {winning} WINNING · {losing} LOSING" if picked else
                                "MY PICKS · none on the sheet yet")
        items = list(self.feed.recent)[:BAND_RECENT]
        self.recent.setText("\n".join(f"{LS.clock_et(at)}   {text}" for at, text, _ in items) if items else
                            "Scores that change while this is open show here.")

    def _size_band(self) -> None:
        """The band takes what a 16:9 picture leaves under it."""
        width = self.width() - SIDE_WIDTH
        room = self.height() - self.ribbon.sizeHint().height()
        self.band.setFixedHeight(max(BAND_MIN, room - round(width * 9 / 16)))

    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("CinemaSide")
        side.setFixedWidth(SIDE_WIDTH)
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel("ACQL")
        self.title.setObjectName("RedZoneTitle")
        top.addWidget(self.title, 1)
        self.exit_btn = QPushButton()
        self.exit_btn.setObjectName("CinemaExit")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setToolTip("Close RedZone mode (Esc)")
        self.exit_btn.clicked.connect(self.close)
        top.addWidget(self.exit_btn)
        box.addLayout(top)
        self.fit_btn = QPushButton("FIT STREAM")
        self.fit_btn.setObjectName("CinemaExit")
        self.fit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fit_btn.setToolTip("Finds the Spectrum / RedZone window and sizes it to fill the middle")
        self.fit_btn.clicked.connect(self.fit_stream)
        fit_row = QHBoxLayout()
        fit_row.addWidget(self.fit_btn, 1)
        for text, way, tip in (("▲", 1, "Hide more of the stream's top"), ("▼", -1, "Show more of the stream's top")):
            nudge = QPushButton(text)
            nudge.setObjectName("CinemaExit")
            nudge.setFixedWidth(44)
            nudge.setToolTip(tip)
            nudge.setCursor(Qt.CursorShape.PointingHandCursor)
            nudge.clicked.connect(lambda *_, w=way: self.nudge(w))
            fit_row.addWidget(nudge)
        box.addLayout(fit_row)
        self.open_btn = QPushButton("OPEN SPECTRUM")
        self.open_btn.setObjectName("CinemaExit")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setToolTip("Opens Spectrum's live TV in a bare Chrome window and fits it into the gap")
        self.open_btn.clicked.connect(self.open_spectrum)
        box.addWidget(self.open_btn)
        self.heading = QLabel("POOL · IF IT ENDED NOW")
        self.heading.setObjectName("CinemaHeading")
        box.addWidget(self.heading)
        scroll = QScrollArea()
        scroll.setObjectName("CinemaScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.board = Leaderboard()
        scroll.setWidget(self.board)
        box.addWidget(scroll, 1)
        self.note = QLabel("")
        self.note.setObjectName("CinemaMeta")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        return side

    def restyle(self, palette) -> None:
        self.palette_ = palette
        gold = palette.brand or palette.accent
        self.board.gold = gold
        self.ribbon.restyle(palette)
        self.setStyleSheet(stylesheet(palette) + f"""
            #RedZoneTitle {{ color: {gold}; font-size: 22px; font-weight: 800; letter-spacing: 4px; }}
            #CinemaSide {{ border-left: {EDGE}px solid {gold}; }}
            #ScoreRibbon {{ border-bottom: {EDGE}px solid {gold}; }}
            #RedZoneBand {{ border-top: {EDGE}px solid {gold}; }}
            #RedZoneRecent {{ font-size: 13px; color: {palette.ink}; }}
            #RedZonePick {{ border-radius: 6px; border: 1px solid {palette.ink_muted}; min-width: 46px; }}
            #RedZonePick[status="win"] {{ border: 2px solid #3ccf7a; background: rgba(60,207,122,0.16); }}
            #RedZonePick[status="lose"] {{ border: 2px solid #e5484d; background: rgba(229,72,77,0.16); }}
            #RedZonePick[status="even"] {{ border: 2px solid #e8b84e; }}
            #RedZonePickWord {{ font-size: 10px; font-weight: 700; color: {palette.ink_muted}; }}""")
        self.exit_btn.setIcon(icons.icon("cross", palette.ink, palette.ink, 16))

    # ---- in and out ------------------------------------------------------------
    def enter(self) -> None:
        from . import extras
        screen = extras.cinema_screen(self.window_.screen())
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        self.refresh(Changes(self.feed.week))
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(300, self.fit_stream)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)
        self.closed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._size_band()
        self._cut_hole()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._cut_hole()

    def _cut_hole(self) -> None:
        """The window keeps only the ribbon and the side column; the middle
        is not part of it at all, so the stream underneath gets the clicks."""
        self.layout().activate()
        hole = QRect(self.hole.mapTo(self, self.hole.rect().topLeft()), self.hole.size())
        self.setMask(QRegion(self.rect()).subtracted(QRegion(hole)))

    def trim(self) -> int:
        try:
            return max(0, int(QSettings().value(TRIM_KEY, TRIM_DEFAULT)))
        except (TypeError, ValueError):
            return TRIM_DEFAULT

    def nudge(self, way: int) -> None:
        QSettings().setValue(TRIM_KEY, max(0, self.trim() + way * TRIM_STEP))
        self.fit_stream()

    def open_spectrum(self) -> None:
        from . import streamfit
        if not streamfit.open_spectrum():
            self.note.setText("Chrome was not found.")
            return
        self.note.setText("Opening Spectrum… it fits itself in a few seconds.")
        QTimer.singleShot(5000, self.fit_stream)

    def fit_stream(self) -> None:
        """Size the stream's window to the gap, its title bar under the scores bar."""
        from . import streamfit
        found = streamfit.find_stream()
        if found is None:
            self.note.setText("No Spectrum / RedZone window found. Open it (not full screen), then press Fit.")
            return
        screen = self.screen()
        dpr = screen.devicePixelRatio()
        origin = screen.geometry().topLeft()
        corner = self.hole.mapToGlobal(self.hole.rect().topLeft())
        x = origin.x() + round((corner.x() - origin.x()) * dpr)
        y = origin.y() + round((corner.y() - origin.y()) * dpr)
        room = screen.geometry().height() - self.hole.height()     # Windows caps a window at the screen's height
        trim = round(min(self.trim(), max(0, room)) * dpr)
        ok = streamfit.fit(found[0], x, y - trim, round(self.hole.width() * dpr),
                           round(self.hole.height() * dpr) + trim)
        self.raise_()
        self.note.setText(f"Fitted: {found[1][:40]}. If the player goes full screen, leave it and press Fit again."
                          if ok else "Windows would not move that window.")

    # ---- what it shows ------------------------------------------------------------
    def refresh(self, changes: Changes | None = None) -> None:
        feed = self.feed
        season = self.window_.season
        self.ribbon.set_feed(feed, season, changes)
        if not feed.week:
            self.ribbon.show()          # the ribbon hides itself with no week; here it stays as the frame
        self.heading.setText(f"WEEK {feed.week} · IF IT ENDED NOW" if feed.week else "POOL STANDINGS")
        bd = None
        if feed.week and feed.states:
            from .ribbon import viewer
            try:
                bd = GD.board(season, feed.week, viewer(season), kept=feed.kept)
            except Exception:  # noqa: BLE001 - the scores still show without the standings
                bd = None
        try:
            self._show_band(bd.you.card if bd is not None and bd.you is not None else None)
        except Exception:  # noqa: BLE001 - the band is extra; the frame still shows
            pass
        if bd is None or not bd.standings:
            self.board.show_rows([], LS.Movement())
            self.note.setText("Standings appear once the week's pick sheet is in.")
            return
        rows = [(s.card.name, s.place, s.total_now, s.card.you)
                for s in bd.standings if s.place is not None and s.card.name]
        self.board.show_rows(rows, LS.Movement())
