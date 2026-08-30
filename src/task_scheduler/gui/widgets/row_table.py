"""Generic editable table of single-line text rows with add/remove controls."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["RowTable"]


class RowTable(QWidget):
    """Editable rows of text fields; emits rowsChanged on any mutation."""

    rowsChanged = Signal()

    def __init__(self, columns: int, parent: QWidget | None = None) -> None:
        """Create the grid, the add/remove buttons, and the row storage."""
        super().__init__(parent)
        self._columns = columns
        self._rows: list[list[QLineEdit]] = []
        self._grid = QGridLayout()
        layout = QVBoxLayout(self)
        layout.addLayout(self._grid)
        self._add_button = QPushButton("Add", self)
        self._add_button.setObjectName("rowtable-add")
        self._remove_button = QPushButton("Remove", self)
        self._remove_button.setObjectName("rowtable-remove")
        self._add_button.clicked.connect(self._on_add_clicked)
        self._remove_button.clicked.connect(self._on_remove_clicked)
        button_row = QHBoxLayout()
        button_row.addWidget(self._add_button)
        button_row.addWidget(self._remove_button)
        layout.addLayout(button_row)

    def columns(self) -> int:
        """The number of columns in every row."""
        return self._columns

    def row_count(self) -> int:
        """The number of rows currently in the table."""
        return len(self._rows)

    def cells(self, row: int) -> list[QLineEdit]:
        """The line edits of one row; IndexError on a bad index."""
        return self._rows[row]

    def rows(self) -> list[list[str]]:
        """The current text of every cell, row by row."""
        return [[edit.text() for edit in row] for row in self._rows]

    def add_row(self, values: list[str] | None = None) -> None:
        """Add a row of empty or pre-filled edits and emit rowsChanged."""
        self._add_row(values)
        self.rowsChanged.emit()

    def _add_row(self, values: list[str] | None = None) -> None:
        """Create the edit widgets for a new row without emitting."""
        row: list[QLineEdit] = []
        for column in range(self._columns):
            edit = QLineEdit(self)
            self._grid.addWidget(edit, len(self._rows), column)
            if values is not None:
                edit.setText(values[column])
            edit.textChanged.connect(self._on_text_changed)
            row.append(edit)
        self._rows.append(row)

    def remove_row(self, index: int) -> None:
        """Remove the row at index, shifting the rest up; no-op out of range."""
        if not 0 <= index < len(self._rows):
            return
        removed = self._rows.pop(index)
        for edit in removed:
            self._grid.removeWidget(edit)
            edit.setParent(None)
        for new_index, row in enumerate(self._rows):
            for column, edit in enumerate(row):
                self._grid.removeWidget(edit)
                self._grid.addWidget(edit, new_index, column)
        self.rowsChanged.emit()

    def _remove_focused_row(self) -> None:
        """Remove the row containing the focused edit, else the last row."""
        focused = QApplication.focusWidget()
        if focused is not None:
            for index, row in enumerate(self._rows):
                for edit in row:
                    if edit is focused:
                        self.remove_row(index)
                        return
        if self._rows:
            self.remove_row(len(self._rows) - 1)

    def set_rows(self, values: list[list[str]]) -> None:
        """Replace all rows from the given values, emitting rowsChanged once."""
        self._clear_rows()
        for entry in values:
            self._add_row(entry)
        self.rowsChanged.emit()

    def clear(self) -> None:
        """Remove every row and emit rowsChanged."""
        self.set_rows([])

    def _clear_rows(self) -> None:
        """Detach every row's edits from the grid without emitting."""
        for row in self._rows:
            for edit in row:
                self._grid.removeWidget(edit)
                edit.setParent(None)
        self._rows = []

    def _on_add_clicked(self) -> None:
        """Add-button slot: append an empty row."""
        self.add_row()

    def _on_remove_clicked(self) -> None:
        """Remove-button slot: drop the focused row, else the last row."""
        self._remove_focused_row()

    def _on_text_changed(self, _text: str) -> None:
        """Forward a cell text change to rowsChanged."""
        self.rowsChanged.emit()
