"""Tests for the TimeRowEditor widget (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
from pytest import MonkeyPatch
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


class TestInitial:
    def test_initial_single_blank_row(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        rows = row_edits(editor)
        assert len(rows) == 1
        assert rows[0].text() == ""
        assert rows[0].objectName() == "editor-time"
        assert rows[0].placeholderText() == "HH:MM"
        assert rows[0].maxLength() == 5

    def test_no_emission_during_construction(self, qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
        counter = _EmissionCounter()
        monkeypatch.setattr(TimeRowEditor, "rowsChanged", counter)
        editor = TimeRowEditor()
        qtbot.addWidget(editor)
        assert counter.count == 0


class TestSetTimes:
    def test_set_times_sets_exact_texts_and_names(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        emissions = spy(editor)
        editor.set_times(["07:30", "17:30"])
        rows = row_edits(editor)
        assert [edit.text() for edit in rows] == ["07:30", "17:30"]
        assert [edit.objectName() for edit in rows] == ["editor-time", "editor-time-1"]
        assert len(emissions) == 1

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


class TestTimes:
    def test_times_strips_and_preserves_order(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times([" 07:3", "17:3 "])
        rows = row_edits(editor)
        assert [edit.text() for edit in rows] == [" 07:3", "17:3 "]
        assert editor.times() == ["07:3", "17:3"]


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
    def test_remove_without_focus_drops_last_row(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30", "17:30"])
        assert QApplication.focusWidget() is None
        emissions = spy(editor)
        remove = editor.findChild(QPushButton, "timerow-remove")
        assert remove is not None
        remove.click()
        rows = row_edits(editor)
        assert [edit.text() for edit in rows] == ["07:30"]
        assert rows[0].objectName() == "editor-time"
        assert len(emissions) == 1

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


class TestTextEdited:
    def test_typing_emits_rows_changed(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.show()
        emissions = spy(editor)
        target = row_edits(editor)[0]
        target.setFocus()
        qtbot.waitUntil(lambda: QApplication.focusWidget() is target)
        qtbot.keyClicks(target, "07:30")
        assert target.text() == "07:30"
        assert len(emissions) == 5

    def test_programmatic_set_text_does_not_emit(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        emissions = spy(editor)
        target = row_edits(editor)[0]
        target.setText("17:30")
        assert target.text() == "17:30"
        assert len(emissions) == 0


class TestRenumbering:
    def test_renumber_after_set_times_then_remove(self, qtbot: QtBot) -> None:
        editor = make_editor(qtbot)
        editor.set_times(["07:30", "08:00", "09:00"])
        names = [edit.objectName() for edit in row_edits(editor)]
        assert names == ["editor-time", "editor-time-1", "editor-time-2"]
        remove = editor.findChild(QPushButton, "timerow-remove")
        assert remove is not None
        remove.click()
        rows = row_edits(editor)
        assert [edit.objectName() for edit in rows] == ["editor-time", "editor-time-1"]
        assert [edit.text() for edit in rows] == ["07:30", "08:00"]
