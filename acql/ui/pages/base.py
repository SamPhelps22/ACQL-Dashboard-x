"""Shared page scaffolding."""

from __future__ import annotations

import math
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...models import Season
from ..theme import Palette

#: A refresh slower than this is written to the log, so "it feels slow" can
#: be answered with which page and how slow rather than a guess.
SLOW_REFRESH_MS = 250
#: How long a refresh may keep settling its layout before a restored scroll
#: position is given up on (the page may simply have got shorter).
SCROLL_SETTLE_MS = 600
#: The log is trimmed back to about half this size, keeping the newest entries.
LOG_LIMIT = 200_000
LOG_NAME = "acql-log.txt"

# What a page can ask the window to do from one of its state panels.
GO_TO_DATA = "data"
OPEN_FOLDER = "open-folder"
RELOAD = "reload"
# ...and from the Data & Update page's "The app" card.
SELF_CHECK = "self-check"
INSTALL_UPDATE = "install-update"
UNDO_UPDATE = "undo-update"
# ...and from Results: the file the pool's web page is updated from.
POOL_PAGE = "pool-page"

VIEW_CONTENT, VIEW_STATE = 0, 1

Action = tuple[str, Callable[[], None], bool]      # label, callback, primary


def log_path() -> Path:
    """Where problems and slow pages are written down.

    Beside the pool's data when the app knows where that is - the same place
    a coach would be asked to look - otherwise in the home folder.
    """
    try:
        from ...config import DATA_DIR  # lazy: config must never import pages

        folder = Path(DATA_DIR)
    except Exception:  # noqa: BLE001 - a log location is never worth a crash
        folder = Path.home() / ".acql"
    return folder / LOG_NAME


def write_log(entry: str) -> None:
    """Append one timestamped entry, trimming the oldest when the file grows.

    Writing the log must never be the thing that breaks the app, so every
    failure here is swallowed.
    """
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {entry.rstrip()}\n")
        if path.stat().st_size > LOG_LIMIT:
            text = path.read_text(encoding="utf-8", errors="replace")
            keep = text[-LOG_LIMIT // 2:]
            # Start on a whole entry rather than halfway through one.
            cut = keep.find("\n[")
            path.write_text(keep[cut + 1:] if cut >= 0 else keep, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def where_it_broke(exc: BaseException) -> str:
    """The deepest frame inside this project, as "pages/standings.py, line 212".

    The last frame of a traceback is usually inside Qt or the standard
    library, which says nothing useful. The last one in our own code is the
    line somebody would actually open.
    """
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if "acql" in Path(f.filename).parts]
    chosen = ours or frames
    if not chosen:
        return ""
    frame = chosen[-1]
    parts = Path(frame.filename).parts
    tail = parts[len(parts) - parts[::-1].index("acql"):] if "acql" in parts else parts[-1:]
    return f"{'/'.join(tail)}, line {frame.lineno} ({frame.name})"


class StatePanel(QWidget):
    """A centred message that stands in for a page's content.

    One widget for the three moments a page has nothing normal to show:
    before the first load, when no data was found, and when the page itself
    failed. Each gets a heading, a sentence, and the one or two buttons that
    move things on - never a blank page and never a bare traceback.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatePanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(2)

        column = QWidget()
        column.setObjectName("StateColumn")
        column.setMaximumWidth(560)
        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.icon = QLabel("")
        self.icon.setObjectName("StateIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading = QLabel("")
        self.heading.setObjectName("StateTitle")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading.setWordWrap(True)
        self.message = QLabel("")
        self.message.setObjectName("StateMessage")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.progress = QProgressBar()
        self.progress.setObjectName("StateProgress")
        self.progress.setRange(0, 0)          # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setFixedWidth(220)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)

        self.details = QPlainTextEdit()
        self.details.setObjectName("StateDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(180)
        self.details.setVisible(False)

        body.addWidget(self.icon)
        body.addWidget(self.heading)
        body.addWidget(self.message)
        body.addSpacing(6)
        body.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignHCenter)
        body.addLayout(self.buttons)
        body.addWidget(self.details)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(column, 4)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)

        self.actions: list[QPushButton] = []

    def show_state(
        self,
        *,
        icon: str,
        title: str,
        message: str,
        tone: str = "",
        busy: bool = False,
        actions: list[Action] | None = None,
        details: str = "",
    ) -> None:
        """Fill the panel with one state, replacing whatever it showed before."""
        self.icon.setText(icon)
        self.heading.setText(title)
        self.message.setText(message)
        for label in (self.icon, self.heading):
            label.setProperty("tone", tone)
            label.style().unpolish(label)
            label.style().polish(label)
        self.progress.setVisible(busy)

        # Buttons and the stretches either side of them are rebuilt whole.
        while (item := self.buttons.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.actions = []
        self.buttons.addStretch(1)
        for label, callback, primary in actions or []:
            button = QPushButton(label)
            if primary:
                button.setObjectName("Primary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, fn=callback: fn())
            self.buttons.addWidget(button)
            self.actions.append(button)
        self.buttons.addStretch(1)

        self.details.setPlainText(details)
        self.details.setVisible(False)


class Page(QWidget):
    """A dashboard page.

    Subclasses build their widgets once in `build()` and refill them in
    `refresh()`, so switching pages never rebuilds the whole tree.

    Lifecycle
    ---------
    * `build()` runs once, from the base `__init__`. Because of that, a
      subclass must not rely on attributes it assigns *after* calling
      `super().__init__()`; read from `self.palette` and class attributes
      instead.
    * `set_season()` / `invalidate()` mark the page as stale. If the page
      is on screen it refreshes immediately; otherwise the refresh is
      deferred until the page is next shown. With a dozen pages, a data
      change then costs one refresh, not twelve.
    * `refresh()` is only ever called by the base class with `self.season`
      set, so subclasses don't need their own `None` guard. Call
      `refresh_now()` (not `refresh()`) from outside so the guard, the
      repaint batching and the stale flag all apply.
    * `restyle()` is called when the palette changes.

    What the base class adds around every refresh
    ---------------------------------------------
    * Until the first season arrives the page says it is loading, rather
      than showing empty cards and tables.
    * With no data at all, a page that needs data says so and offers the way
      forward; set `needs_data = False` on a page that is useful regardless.
    * A refresh that raises no longer leaves a half-drawn page and a
      traceback in a console nobody can see. The page shows what broke and
      where, offers to try again, and writes the details to the log. The
      other pages are unaffected.
    * The scroll position survives a refresh, so pressing Refresh halfway
      down a long page leaves you where you were.
    """

    title: str = "Page"
    subtitle: str = ""
    icon: str = ""

    #: Defer refreshes on hidden pages until they are shown.
    lazy_refresh: bool = True
    #: Keep content top-aligned when a page is shorter than the window.
    stretch_bottom: bool = True
    #: Whether the page has nothing to show without a loaded season.
    needs_data: bool = True
    #: Text shown for missing or non-finite numbers.
    NO_VALUE: str = "—"

    #: Asks the window to go somewhere or do something (GO_TO_DATA and co).
    action_requested = Signal(str)

    def __init__(self, palette: Palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.season: Season | None = None
        self._dirty = False
        self._page_failure = ""
        self._page_restore_to: int | None = None

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._page_views = QStackedWidget()
        self._outer.addWidget(self._page_views)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        self._content.setObjectName("PageContent")
        self.layout_ = QVBoxLayout(self._content)
        self.layout_.setContentsMargins(22, 18, 22, 22)
        self.layout_.setSpacing(14)
        self._scroll.setWidget(self._content)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._page_range_changed)

        self._page_state = StatePanel()
        self._page_views.addWidget(self._scroll)      # VIEW_CONTENT
        self._page_views.addWidget(self._page_state)  # VIEW_STATE

        self.build()
        if self.stretch_bottom:
            self.layout_.addStretch(1)
        self._page_loading()

    # ---- hooks for subclasses -----------------------------------------
    def build(self) -> None:
        """Create the widgets. Called once."""

    def refresh(self) -> None:
        """Repopulate from `self.season` (never None when called by Page)."""

    def restyle(self) -> None:
        """Re-apply palette-dependent styling. Called by `set_palette()`."""

    # ---- data flow -----------------------------------------------------
    def set_season(self, season: Season) -> None:
        self.season = season
        self.invalidate()

    def invalidate(self, *, eager: bool = False) -> None:
        """Mark the data as changed.

        Use this after mutating `self.season` in place. Refreshes right
        away if the page is visible (or `eager`/`lazy_refresh` says so),
        otherwise waits until the page is shown.
        """
        self._dirty = True
        if eager or not self.lazy_refresh or self.isVisible():
            self.refresh_now()

    def refresh_now(self) -> None:
        """Refresh immediately, batching repaints to avoid flicker.

        Never raises: a page that fails shows the failure in place of its
        content, and the rest of the app carries on.
        """
        season = self.season
        if season is None:
            return
        if self.needs_data and season.is_empty:
            self._dirty = False
            self._page_empty()
            return

        showing = self._page_views.currentIndex() == VIEW_CONTENT
        position = self._scroll.verticalScrollBar().value() if showing else 0
        started = time.perf_counter()
        self.setUpdatesEnabled(False)
        try:
            self.refresh()
        except Exception as exc:  # noqa: BLE001 - shown on the page, and logged
            self._dirty = False     # retrying on every show would fail every time
            self._page_failed(exc)
            return
        finally:
            self.setUpdatesEnabled(True)

        self._dirty = False
        self._page_failure = ""
        self._page_views.setCurrentIndex(VIEW_CONTENT)
        self._page_keep_scroll(position)

        took = (time.perf_counter() - started) * 1000
        if took > SLOW_REFRESH_MS:
            write_log(f"slow: {self.title} took {took:.0f} ms to refresh")

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        try:
            self.restyle()
        except Exception as exc:  # noqa: BLE001
            # A theme switch that trips over one chart must not blank a page
            # that was fine a moment ago; note it and keep the content.
            write_log(
                f"restyle failed on {self.title}: {where_it_broke(exc)}\n"
                + "".join(traceback.format_exception(exc))
            )
        self.update()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        if self._dirty:
            self.refresh_now()

    def scroll_to_top(self) -> None:
        self._page_restore_to = None
        self._scroll.verticalScrollBar().setValue(0)

    @property
    def failure(self) -> str:
        """The last refresh error as text, or "" when the page is healthy."""
        return self._page_failure

    # ---- the three states ----------------------------------------------
    def _page_ask(self, what: str) -> Callable[[], None]:
        return lambda: self.action_requested.emit(what)

    def _page_loading(self) -> None:
        self._page_state.show_state(
            icon=self.icon or "\N{HOURGLASS WITH FLOWING SAND}",
            title=self.title,
            message="Reading the spreadsheets\N{HORIZONTAL ELLIPSIS}",
            busy=True,
        )
        self._page_views.setCurrentIndex(VIEW_STATE)

    def _page_empty(self) -> None:
        self._page_state.show_state(
            icon="\N{OPEN FILE FOLDER}",
            title="No pool data yet",
            message=(
                "Put the ACQL Dashboard workbook, the week's pick sheets or a "
                "predictions CSV in the data folder. They are picked up as "
                "soon as they land - there is nothing else to press."
            ),
            actions=[
                ("Open the data folder", self._page_ask(OPEN_FOLDER), True),
                ("See what was found", self._page_ask(GO_TO_DATA), False),
            ],
        )
        self._page_views.setCurrentIndex(VIEW_STATE)

    def _page_failed(self, exc: BaseException) -> None:
        trace = "".join(traceback.format_exception(exc))
        where = where_it_broke(exc)
        summary = f"{type(exc).__name__}: {exc}".strip().rstrip(":")
        self._page_failure = trace
        write_log(f"page failed: {self.title} - {summary} at {where}\n{trace}")

        report = f"ACQL Dashboard - {self.title} page\n{summary}\nat {where}\n\n{trace}"

        def copy() -> None:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(report)

        def toggle() -> None:
            self._page_state.details.setVisible(not self._page_state.details.isVisible())

        self._page_state.show_state(
            icon="\N{WARNING SIGN}",
            title=f"{self.title} couldn't finish drawing",
            message=(
                f"{summary}\n{where}\n\n"
                "The rest of the dashboard is fine. “Copy details” puts "
                "the full report on the clipboard to send on; it is also saved "
                f"in {LOG_NAME} in the data folder."
            ),
            tone="bad",
            actions=[
                ("Try again", self._page_retry, True),
                ("Copy details", copy, False),
                ("Show details", toggle, False),
            ],
            details=report,
        )
        self._page_views.setCurrentIndex(VIEW_STATE)

    def _page_retry(self) -> None:
        self._dirty = True
        self.refresh_now()

    # ---- scroll position -------------------------------------------------
    def _page_keep_scroll(self, position: int) -> None:
        """Put the page back where it was once its new layout has settled.

        Swapping a table out shrinks the page for a moment, and the scroll bar
        clamps to the shorter range - which is what used to throw you to the
        top. The wanted position is held and reapplied as the range grows
        back, then let go of so it never fights a real scroll.
        """
        if position <= 0:
            self._page_restore_to = None
            return
        self._page_restore_to = position
        bar = self._scroll.verticalScrollBar()
        bar.setValue(position)
        QTimer.singleShot(0, lambda: self._page_range_changed(bar.minimum(), bar.maximum()))
        QTimer.singleShot(SCROLL_SETTLE_MS, self._page_let_go_of_scroll)

    def _page_range_changed(self, _minimum: int, maximum: int) -> None:
        wanted = self._page_restore_to
        if wanted is None:
            return
        self._scroll.verticalScrollBar().setValue(min(wanted, maximum))
        if maximum >= wanted:
            self._page_restore_to = None

    def _page_let_go_of_scroll(self) -> None:
        self._page_restore_to = None

    # ---- layout helpers ------------------------------------------------
    @staticmethod
    def clear_layout(layout: QLayout) -> None:
        """Remove and delete everything in a layout, including nested ones."""
        while (item := layout.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                Page.clear_layout(child)
                child.deleteLater()

    # ---- formatting helpers shared by pages ---------------------------
    @staticmethod
    def _sign(value: float, signed: bool) -> str:
        if value < 0:
            return "-"
        return "+" if signed and value > 0 else ""

    @classmethod
    def money(cls, value: float | None, *, signed: bool = False) -> str:
        """Format as dollars, e.g. `$1,234.50`, `-$3.00`, or `+$3.00` if signed."""
        if value is None or not math.isfinite(value):
            return cls.NO_VALUE
        value = round(value, 2)  # round first so -0.004 becomes $0.00, not -$0.00
        return f"{cls._sign(value, signed)}${abs(value):,.2f}"

    @classmethod
    def pct(cls, value: float | None, digits: int = 1, *, signed: bool = False) -> str:
        """Format a 0-1 fraction as a percentage, e.g. `0.253` -> `25.3%`."""
        if value is None or not math.isfinite(value):
            return cls.NO_VALUE
        scaled = round(value * 100, digits)
        return f"{cls._sign(scaled, signed)}{abs(scaled):.{digits}f}%"
