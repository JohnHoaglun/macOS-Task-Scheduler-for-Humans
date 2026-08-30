"""Tests for the RowTable widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.row_table import RowTable


def make_table(qtbot: QtBot, columns: int) -> RowTable:
    """A fresh table kept alive by qtbot."""
    table = RowTable(columns)
    qtbot.addWidget(table)
    return table


class TestRows:
    def test_add_and_rows(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 2)
        t.add_row(["a", "1"])
        t.add_row()
        assert t.row_count() == 2
        assert t.rows() == [["a", "1"], ["", ""]]

    def test_rows_reflect_edits(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        t.add_row(["a"])
        t.cells(0)[0].setText("b")
        assert t.rows() == [["b"]]

    def test_remove_row(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        t.set_rows([["a"], ["b"], ["c"]])
        t.remove_row(1)
        assert t.rows() == [["a"], ["c"]]

    def test_clear(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        t.set_rows([["a"]])
        t.clear()
        assert t.row_count() == 0


class TestSetRows:
    def test_set_rows_replaces(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 2)
        t.add_row(["old", "x"])
        t.set_rows([["a", "1"], ["b", "2"]])
        assert t.rows() == [["a", "1"], ["b", "2"]]

    def test_set_rows_emits_once(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        emissions: list[int] = []

        def count() -> None:
            emissions.append(1)

        t.rowsChanged.connect(count)
        t.set_rows([["a"], ["b"]])
        assert len(emissions) == 1


class TestSignalsAndButtons:
    def test_add_row_emits(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        emissions: list[int] = []

        def count() -> None:
            emissions.append(1)

        t.rowsChanged.connect(count)
        t.add_row(["a"])
        assert len(emissions) == 1

    def test_cell_edit_emits(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        t.add_row(["a"])
        emissions: list[int] = []

        def count() -> None:
            emissions.append(1)

        t.rowsChanged.connect(count)
        t.cells(0)[0].setText("b")
        assert len(emissions) == 1

    def test_add_and_remove_buttons(self, qtbot: QtBot) -> None:
        t = make_table(qtbot, 1)
        add = t.findChild(QPushButton, "rowtable-add")
        remove = t.findChild(QPushButton, "rowtable-remove")
        assert add is not None and remove is not None
        add.click()
        assert t.rows() == [[""]]
        remove.click()
        assert t.row_count() == 0


class TestGaps:
    def test_columns_reports_count(self, qtbot: QtBot) -> None:
        """columns() reports the constructor's column count."""
        t = make_table(qtbot, 2)
        assert t.columns() == 2
        t.add_row(["a", "b"])
        assert t.columns() == 2

    def test_remove_out_of_range_is_noop(self, qtbot: QtBot) -> None:
        """Removing an out-of-range index leaves the rows untouched."""
        t = make_table(qtbot, 1)
        t.set_rows([["a"], ["b"]])
        t.remove_row(5)
        t.remove_row(-1)
        assert t.rows() == [["a"], ["b"]]

    def test_remove_button_drops_focused_row(self, qtbot: QtBot) -> None:
        """With a cell focused, the remove button drops that row, not the last."""
        t = make_table(qtbot, 1)
        t.set_rows([["a"], ["b"], ["c"]])
        t.show()
        target = t.cells(1)[0]
        target.setFocus()
        QApplication.processEvents()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is target)
        remove = t.findChild(QPushButton, "rowtable-remove")
        assert remove is not None
        remove.click()
        assert t.rows() == [["a"], ["c"]]
