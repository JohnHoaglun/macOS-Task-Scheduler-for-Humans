"""Tests for the TimeRowEditor widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.time_row_editor import TimeRowEditor


def make_editor(qtbot: QtBot) -> TimeRowEditor:
    """A fresh editor kept alive by qtbot."""
    editor = TimeRowEditor()
    qtbot.addWidget(editor)
    return editor

def row_edits(editor: TimeRowEditor) -> list[QLineEdit]:
    """The row edits in row order, keyed by object name."""
    return sorted(editor.findChildren(QLineEdit), key=lambda edit: edit.objectName())

def spy(editor: TimeRowEditor) -> list[int]:
    """A list that gains one entry per rowsChanged emission."""
    emissions: list[int] = []

    def count() -> None:
        emissions.append(1)

    editor.rowsChanged.connect(count)
    return emissions

class _EmissionCounter:
    """Stand-in for rowsChanged that records emissions made during init."""

    def __init__(self) -> None:
        self.count = 0

    def emit(self, *args: object) -> None:
        self.count += 1

class TestSetTimes:

    def test_set_times_empty_keeps_one_blank_row(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30", "17:30"])
        emissions = spy(editor)
        editor.set_times([])
        rows = row_edits(editor)
        assert len(rows) == 1
        assert rows[0].text() == ""
        assert rows[0].objectName() == "editor-time"
        assert len(emissions) == 1

class TestAddButton:
    def test_add_appends_blank_row_with_new_name(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30"])
        emissions = spy(editor)
        add = editor.findChild(QPushButton, "timerow-add")
        assert add is not None
        add.click()
        rows = row_edits(editor)
        assert [edit.text() for edit in rows] == ["07:30", ""]
        assert [edit.objectName() for edit in rows] == ["editor-time", "editor-time-1"]
        assert len(emissions) == 1

class TestRemoveButton:

    def test_remove_with_single_row_clears_it(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30"])
        emissions = spy(editor)
        remove = editor.findChild(QPushButton, "timerow-remove")
        assert remove is not None
        remove.click()
        rows = row_edits(editor)
        assert len(rows) == 1
        assert rows[0].text() == ""
        assert rows[0].objectName() == "editor-time"
        assert len(emissions) == 1

    def test_remove_drops_focused_non_last_row(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30", "08:00", "09:00"])
        editor.show()
        target = row_edits(editor)[1]
        target.setFocus()
        QApplication.processEvents()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is target)
        remove = editor.findChild(QPushButton, "timerow-remove")
        assert remove is not None
        remove.click()
        rows = row_edits(editor)
        assert [edit.text() for edit in rows] == ["07:30", "09:00"]
        assert [edit.objectName() for edit in rows] == ["editor-time", "editor-time-1"]

