"""Ctrl+K: open a setting or run a command by typing a few letters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


@dataclass(frozen=True)
class Command:
    label: str
    hint: str  # shortcut shown beside the label
    run: Callable[[], None]


class CommandPalette(QDialog):
    """Ctrl+K settings list: type a few letters, press Enter.

    Styled by the app stylesheet; target `QDialog#CommandPalette` in the
    theme to give it its own look.
    """

    def __init__(self, commands: list[Command], parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("CommandPalette")
        self.setModal(True)
        self.setFixedWidth(520)
        self._commands = commands

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a setting or command\u2026")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results.setFixedHeight(260)
        self.results.itemClicked.connect(lambda _item: self._run_current())
        layout.addWidget(self.results)

        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        terms = text.lower().split()
        self.results.clear()
        for index, command in enumerate(self._commands):
            label = command.label.lower()
            if all(term in label for term in terms):
                shown = f"{command.label}   ({command.hint})" if command.hint else command.label
                item = QListWidgetItem(shown)
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        else:
            empty = QListWidgetItem("No matches")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(empty)

    def _run_current(self) -> None:
        item = self.results.currentItem()
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is None:
            return
        command = self._commands[index]
        self.accept()
        # Run after the dialog has closed so page switches don't fight its focus.
        QTimer.singleShot(0, command.run)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = self.results.count()
                if count:
                    step = 1 if key == Qt.Key.Key_Down else -1
                    self.results.setCurrentRow((self.results.currentRow() + step) % count)
                return True
        return super().eventFilter(obj, event)
