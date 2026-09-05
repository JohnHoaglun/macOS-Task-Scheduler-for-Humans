"""Single-column editor for HH:MM time rows with add/remove controls."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["TimeRowEditor"]


class TimeRowEditor(QWidget):
    """Editable HH:MM time rows; emits rowsChanged on any mutation."""

    rowsChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create one blank row and the add/remove buttons without emitting."""
        super().__init__(parent)
        self._rows: list[QLineEdit] = []
        self._rows_layout = QVBoxLayout()
        layout = QVBoxLayout(self)
        layout.addLayout(self._rows_layout)
        self._add_button = QPushButton("Add", self)
        self._add_button.setObjectName("timerow-add")
        self._remove_button = QPushButton("Remove", self)
        self._remove_button.setObjectName("timerow-remove")
        self._add_button.clicked.connect(self._on_add_clicked)
        self._remove_button.clicked.connect(self._on_remove_clicked)
        button_row = QHBoxLayout()
        button_row.addWidget(self._add_button)
        button_row.addWidget(self._remove_button)
        layout.addLayout(button_row)
        self._add_row()
        self._renumber()

    def set_times(self, values: list[str]) -> None:
        """Replace all rows from the given values, emitting rowsChanged once."""
        self._clear_rows()
        for value in values:
            self._add_row(value)
        if not self._rows:
            self._add_row()
        self._renumber()
        self.rowsChanged.emit()

    def times(self) -> list[str]:
        """The current text of every row, stripped, in row order."""
        return [edit.text().strip() for edit in self._rows]

    def _add_row(self, value: str = "") -> None:
        """Create one row edit with the given text without emitting."""
        edit = QLineEdit(self)
        edit.setPlaceholderText("HH:MM")
        edit.setMaxLength(5)
        edit.setText(value)
        edit.textEdited.connect(self._on_text_edited)
        self._rows_layout.addWidget(edit)
        self._rows.append(edit)

    def _clear_rows(self) -> None:
        """Detach every row edit from the layout without emitting."""
        for edit in self._rows:
            self._rows_layout.removeWidget(edit)
            edit.setParent(None)
        self._rows = []

    def _renumber(self) -> None:
        """Set editor-time object names in order and restore layout order."""
        for index, edit in enumerate(self._rows):
            name = "editor-time" if index == 0 else f"editor-time-{index}"
            edit.setObjectName(name)
            self._rows_layout.removeWidget(edit)
            self._rows_layout.addWidget(edit)

    def _remove_focused_row(self) -> None:
        """Remove the focused row, else the last row, keeping at least one row."""
        if len(self._rows) == 1:
            self._rows[0].setText("")
            self.rowsChanged.emit()
            return
        index = len(self._rows) - 1
        focused = QApplication.focusWidget()
        if focused is not None:
            for candidate, edit in enumerate(self._rows):
                if edit is focused:
                    index = candidate
                    break
        self._rows_layout.removeWidget(self._rows[index])
        self._rows.pop(index).setParent(None)
        self._renumber()
        self.rowsChanged.emit()

    def _on_add_clicked(self) -> None:
        """Add-button slot: append a blank row."""
        self._add_row()
        self._renumber()
        self.rowsChanged.emit()

    def _on_remove_clicked(self) -> None:
        """Remove-button slot: drop the focused row, else the last row."""
        self._remove_focused_row()

    def _on_text_edited(self, _text: str) -> None:
        """Forward a row's user edit to rowsChanged."""
        self.rowsChanged.emit()
