"""Reusable presentation widgets: cards, stat tiles, tables, banners."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette, TYPE, tone_color

#: The tones a widget may be given; anything else is treated as no tone.
TONES = ("good", "warning", "serious", "bad", "muted")


class ElidedLabel(QLabel):
    """A one-line label that ends in an ellipsis instead of widening its parent.

    A plain QLabel refuses to shrink below its text, so a long player name in
    a big headline tile pushes the whole row wider than the window. This one
    shrinks and shows the full text as a tooltip when it has been cut.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # The stylesheet sets the font after construction; re-measure with it.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self.width(), 0)
        )
        if shown != self.text():
            super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class Card(QFrame):
    """A titled surface. The title is a quiet label, not a heading."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self._layout.addWidget(self.title_label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def set_title(self, title: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(title)


class StatTile(Card):
    """A single headline number. No plot, so no hover layer is needed."""

    def __init__(
        self,
        title: str,
        value: str = "-",
        detail: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        # A different object name lets the theme lift tiles above the cards.
        self.setObjectName("StatTile")
        self._palette: Palette | None = None
        self.bar: Sparkbar | None = None
        self.value_label = ElidedLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setWordWrap(False)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("StatDetail")
        self.detail_label.setProperty("tone", "")
        self.detail_label.setWordWrap(True)
        self._layout.addWidget(self.value_label)
        self._layout.addWidget(self.detail_label)
        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(112)

    def update_values(self, value: str, detail: str = "", tone: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        # A headline that is a team name, not a number, steps the type down
        # rather than eliding - losing the end of "San Francisco" is worse
        # than showing it smaller.
        length = "verylong" if len(value) > 15 else ("long" if len(value) > 9 else "")
        self._restyle(self.value_label, "length", length)
        # The tabular face is for figures: it lines digits up in a column and
        # keeps them from shifting as they change. On words - "7-way tie",
        # "New York Giants" - it just reads like a typewriter, so a headline
        # with no digit in it gets the page's own face instead.
        self._restyle(
            self.value_label, "kind",
            "text" if not any(c.isdigit() for c in value) else "",
        )
        # Tone rides on the detail line; the big number stays in primary ink so
        # a colour never has to carry the meaning on its own. It is a property
        # rather than a new object name so the label keeps its size and font.
        self._restyle(self.detail_label, "tone", tone if tone in TONES else "")

    def show_bar(
        self,
        value: float,
        marker: float | None = None,
        tone: str = "",
        palette: Palette | None = None,
    ) -> None:
        """Add a hairline bar under the number, against an optional reference.

        Used where a figure only means something next to another one - a hit
        rate against the pool's, a share against an average. A palette is
        needed to draw it; without one the tile simply keeps its number.
        """
        self._palette = palette or self._palette
        if self._palette is None:
            return
        if self.bar is None:
            self.bar = Sparkbar(self._palette)
            self._layout.insertWidget(self._layout.count() - 1, self.bar)
        self.bar.set_values(value, marker, tone)
        self.bar.show()

    def hide_bar(self) -> None:
        if self.bar is not None:
            self.bar.hide()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        if self.bar is not None:
            self.bar.set_palette(palette)

    @staticmethod
    def _restyle(widget: QWidget, name: str, value: str) -> None:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class Pill(QLabel):
    """One figure in a tinted chip, for a number that sits among words."""

    def __init__(self, text: str = "", tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Pill")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone if tone in TONES else "")
        self.style().unpolish(self)
        self.style().polish(self)

    def update_values(self, text: str, tone: str = "") -> None:
        self.setText(text)
        self.set_tone(tone)


class Sparkbar(QWidget):
    """A hairline bar showing one proportion, with an optional marker.

    Made for a figure that only means something against a reference - a
    player's hit rate against the pool's, a share of the pool against an
    average. The number says how much; this says how much compared with what.
    """

    def __init__(
        self,
        palette: Palette,
        height: int = 6,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.palette_ = palette
        self._value = 0.0
        self._marker: float | None = None
        self._tone = ""
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self.update()

    def set_values(self, value: float, marker: float | None = None, tone: str = "") -> None:
        """`value` and `marker` are 0..1; anything outside is clamped."""
        self._value = min(max(float(value), 0.0), 1.0)
        self._marker = None if marker is None else min(max(float(marker), 0.0), 1.0)
        self._tone = tone
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self.palette_
        radius = self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.grid))
        painter.drawRoundedRect(self.rect(), radius, radius)
        filled = int(self.width() * self._value)
        if filled > 0:
            painter.setBrush(QColor(tone_color(p, self._tone) if self._tone else p.accent))
            bar = self.rect()
            bar.setWidth(max(filled, self.height()))
            painter.drawRoundedRect(bar, radius, radius)
        if self._marker is not None:
            x = int(self.width() * self._marker)
            painter.setBrush(QColor(p.ink))
            painter.drawRect(max(0, min(x - 1, self.width() - 2)), 0, 2, self.height())
        painter.end()


class MetricRow(QWidget):
    """A label, a figure and an optional note, on one line.

    Several of these in a card read as a small table without the weight of
    an actual table - which is what most of these cards were reaching for.
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        note: str = "",
        tone: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)
        self.label = ElidedLabel(label)
        self.label.setObjectName("MetricLabel")
        self.value = QLabel(value)
        self.value.setObjectName("MetricValue")
        self.value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.note = QLabel(note)
        self.note.setObjectName("MetricNote")
        row.addWidget(self.label, 1)
        row.addWidget(self.value)
        row.addWidget(self.note)
        self.note.setVisible(bool(note))
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.value.setProperty("tone", tone if tone in TONES else "")
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)

    def update_values(self, value: str, note: str = "", tone: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.set_tone(tone)


def tile_grid(tiles: list[QWidget], per_row: int = 4, spacing: int = 12) -> QGridLayout:
    """Lay tiles out in rows rather than squeezing them all onto one line.

    Six tiles across a laptop screen leaves each one too narrow to hold its
    own number, and the value label quietly elides. Wrapping at four keeps
    every tile readable at any window width.
    """
    grid = QGridLayout()
    grid.setSpacing(spacing)
    for index, tile in enumerate(tiles):
        grid.addWidget(tile, index // per_row, index % per_row)
    for column in range(min(per_row, len(tiles))):
        grid.setColumnStretch(column, 1)
    return grid


class Banner(QFrame):
    """A dismissible strip for warnings and load messages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        self.icon = QLabel("\N{WARNING SIGN}")
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.label, 1)
        self.hide()

    def show_messages(self, messages: list[str], icon: str = "\N{WARNING SIGN}") -> None:
        text = [m for m in messages if m]
        if not text:
            self.hide()
            return
        self.icon.setText(icon)
        if len(text) == 1:
            self.label.setText(text[0])
        else:
            self.label.setText("\n".join(f"•  {m}" for m in text))
        self.show()


class TableModel(QAbstractTableModel):
    """A table over plain rows, with per-column alignment and optional tone.

    `rows` are display-ready values. `sort_values` supplies the value used for
    ordering where it differs from what is shown (so "-39.97" sorts
    numerically while displaying as "-$39.97").
    """

    def __init__(
        self,
        headers: list[str],
        rows: list[list[object]],
        *,
        palette: Palette,
        numeric_columns: set[int] | None = None,
        sort_values: dict[int, list[object]] | None = None,
        tones: dict[tuple[int, int], str] | None = None,
        cell_colors: dict[tuple[int, int], str] | None = None,
        tooltips: dict[tuple[int, int], str] | None = None,
        bold_columns: set[int] | None = None,
    ) -> None:
        super().__init__()
        self._headers = headers
        self._rows = rows
        self._palette = palette
        self._numeric = numeric_columns or set()
        self._sort_values = sort_values or {}
        self._tones = tones or {}
        self._cell_colors = cell_colors or {}
        self._tooltips = tooltips or {}
        self._bold = bold_columns or set()
        self._bold_font = QFont()
        self._bold_font.setBold(True)

        # Everything below is worked out once, because `data()` is called by
        # Qt for every cell, for half a dozen roles, on every paint, sort and
        # resize - tens of thousands of calls for one table. Anything built
        # inside it is built that many times. A QColor per cell per paint was
        # most of why the tables felt heavy.
        self._text = [
            ["" if value is None else str(value) for value in row] for row in rows
        ]
        self._align = [
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column in self._numeric else
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for column in range(len(headers))
        ]
        self._tone_colors = {
            "good": QColor(palette.good),
            "bad": QColor(palette.critical),
            "muted": QColor(palette.ink_muted),
        }
        self._foreground = {
            cell: self._tone_colors.get(tone)
            for cell, tone in self._tones.items()
        }
        self._background = {
            cell: QColor(color) for cell, color in self._cell_colors.items() if color
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()

        # Ordered by how often Qt asks: display and alignment on every cell of
        # every paint, the rest only where something was set.
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text[row][col]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._align[col]
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground.get((row, col))
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background.get((row, col))
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltips.get((row, col))
        if role == Qt.ItemDataRole.FontRole and col in self._bold:
            return self._bold_font
        if role == Qt.ItemDataRole.UserRole:
            value = self._rows[row][col]
            # The sort key: explicit override, else the raw value.
            override = self._sort_values.get(col)
            return override[row] if override is not None else value
        return None

    def row_values(self, row: int) -> list[object]:
        return self._rows[row]


class SortProxy(QSortFilterProxyModel):
    """Sorts on UserRole so numbers order numerically, and filters on text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._filter_columns: list[int] = []

    def set_filter_columns(self, columns: list[int]) -> None:
        self._filter_columns = columns

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True
        model = self.sourceModel()
        columns = self._filter_columns or range(model.columnCount())
        for col in columns:
            index = model.index(source_row, col, source_parent)
            text = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")
            if pattern.lower() in text.lower():
                return True
        return False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        a = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        b = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        # Blanks sort first. Two blanks are equal, not "each less than the
        # other", which would give the sort an inconsistent order.
        if a is None or b is None:
            return a is None and b is not None
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return str(a).lower() < str(b).lower()


# No single column may take more than this. A "Why" or a matchup runs long,
# and a column sized to its longest entry pushes every column after it off the
# edge of the card - so the table scrolls sideways to reach a two-character
# number. Capped, the long text elides with an ellipsis and the rest of the
# row stays on screen, which is the right trade: the full text is one hover
# away, the numbers are the reason the table is there.
MAX_COLUMN_WIDTH = 240


def make_table(
    model: TableModel,
    *,
    stretch_column: int | None = None,
    sort_column: int | None = None,
    ascending: bool = True,
    row_height: int = 30,
    max_column_width: int = MAX_COLUMN_WIDTH,
) -> tuple[QTableView, SortProxy]:
    """Build a configured table view over a model."""
    proxy = SortProxy()
    proxy.setSourceModel(model)
    view = QTableView()
    view.setModel(proxy)
    view.setAlternatingRowColors(True)
    view.setSortingEnabled(True)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(row_height)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
    view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
    view.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)

    header = view.horizontalHeader()
    header.setHighlightSections(False)
    # Columns are measured once, here, rather than left on ResizeToContents.
    # That mode re-measures every cell of every column on every sort, scroll
    # and repaint, and each measurement asks the model for the cell - which
    # for a seventeen-column table of thirty-five coaches is the difference
    # between a page that opens and a window that stops answering.
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    if sort_column is not None:
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        view.sortByColumn(sort_column, order)
    view.resizeColumnsToContents()
    for column in range(model.columnCount()):
        if column != stretch_column and header.sectionSize(column) > max_column_width:
            header.resizeSection(column, max_column_width)
    if stretch_column is not None and stretch_column < model.columnCount():
        header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    return view, proxy


def section(title: str, subtitle: str = "") -> QWidget:
    """A page heading block."""
    wrap = QWidget()
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return wrap
