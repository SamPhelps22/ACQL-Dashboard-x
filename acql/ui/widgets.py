"""Reusable presentation widgets: cards, stat tiles, tables, banners."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .theme import Palette


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
            self.title_label = QLabel(title.upper())
            self.title_label.setObjectName("CardTitle")
            self._layout.addWidget(self.title_label)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def set_title(self, title: str) -> None:
        if self.title_label is not None:
            self.title_label.setText(title.upper())


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
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setWordWrap(False)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("StatDetail")
        self.detail_label.setWordWrap(True)
        self._layout.addWidget(self.value_label)
        self._layout.addWidget(self.detail_label)
        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(112)

    def update_values(self, value: str, detail: str = "", tone: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        # Tone rides on the detail line; the big number stays in primary ink so
        # a colour never has to carry the meaning on its own.
        self.detail_label.setObjectName({"good": "Good", "bad": "Bad"}.get(tone, "StatDetail"))
        self.detail_label.style().unpolish(self.detail_label)
        self.detail_label.style().polish(self.detail_label)


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
        value = self._rows[row][col]

        if role == Qt.ItemDataRole.DisplayRole:
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in self._numeric:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            tone = self._tones.get((row, col))
            if tone == "good":
                return QColor(self._palette.good)
            if tone == "bad":
                return QColor(self._palette.critical)
            if tone == "muted":
                return QColor(self._palette.ink_muted)
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            color = self._cell_colors.get((row, col))
            return QColor(color) if color else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltips.get((row, col))
        if role == Qt.ItemDataRole.FontRole and col in self._bold:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.UserRole:
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
        if a is None:
            return True
        if b is None:
            return False
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return str(a).lower() < str(b).lower()


def make_table(
    model: TableModel,
    *,
    stretch_column: int | None = None,
    sort_column: int | None = None,
    ascending: bool = True,
    row_height: int = 30,
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
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setHighlightSections(False)
    if stretch_column is not None and stretch_column < model.columnCount():
        header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    if sort_column is not None:
        order = Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder
        view.sortByColumn(sort_column, order)
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
