"""Tests for the JobEditor dialog (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton, QStackedWidget
from pytestqt.qtbot import QtBot

from task_scheduler.domain import (
    EnvironmentConfig,
    ExecutableCommand,
    JobDefinition,
    LoggingConfig,
    ShellCommand,
)
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.row_table import RowTable
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld


def make_editor(
    qtbot: QtBot,
    tmp_path: Path,
    job: JobDefinition | None = None,
) -> tuple[FakeTaskWorld, JobEditor, EditorController]:
    """A dialog bound to a world's services, opened on the given job or empty."""
    world = FakeTaskWorld(tmp_path)
    controller = EditorController(world.services)
    editor = JobEditor(controller)
    qtbot.addWidget(editor)
    if job is None:
        editor.open_new()
    else:
        editor.open_existing(job)
    return world, editor, controller


def line_edit(editor: JobEditor, object_name: str) -> QLineEdit:
    """The named line edit, asserted present."""
    edit = editor.findChild(QLineEdit, object_name)
    assert edit is not None
    return edit


def button(editor: JobEditor, object_name: str) -> QPushButton:
    """The named button, asserted present."""
    found = editor.findChild(QPushButton, object_name)
    assert found is not None
    return found


def table(editor: JobEditor, object_name: str) -> RowTable:
    """The named row table, asserted present."""
    found = editor.findChild(RowTable, object_name)
    assert found is not None
    return found


def checkbox(editor: JobEditor, day: str) -> QCheckBox:
    """The named weekday checkbox, asserted present."""
    found = editor.findChild(QCheckBox, f"editor-weekday-{day}")
    assert found is not None
    return found


def combo(editor: JobEditor) -> QComboBox:
    """The command-kind combo box, asserted present."""
    found = editor.findChild(QComboBox, "editor-command-kind")
    assert found is not None
    return found


def stack(editor: JobEditor) -> QStackedWidget:
    """The command-kind page stack, asserted present."""
    found = editor.findChild(QStackedWidget, "editor-command-stack")
    assert found is not None
    return found


class TestOpenNew:
    def test_defaults_populated(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A new dialog opens titled New Task with an empty python draft."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        assert editor.windowTitle() == "New Task"
        assert line_edit(editor, "editor-name").text() == ""
        assert line_edit(editor, "editor-label").text() == ""
        assert combo(editor).currentIndex() == 0
        assert stack(editor).currentIndex() == 0
        assert line_edit(editor, "editor-time").text() == ""
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
            assert not checkbox(editor, day).isChecked()
        assert table(editor, "editor-python-arguments").rows() == []
        assert table(editor, "editor-environment").rows() == []
        assert line_edit(editor, "editor-working-directory").text() == ""
        assert line_edit(editor, "editor-stdout-path").text() == ""
        assert button(editor, "editor-save").isEnabled()


class TestOpenExisting:
    def test_python_job_populated(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A stored python job fills every python page field."""
        _, editor, _ = make_editor(qtbot, tmp_path, job=make_job())
        assert editor.windowTitle() == "Edit Task"
        assert line_edit(editor, "editor-name").text() == "Daily Backup"
        assert (
            line_edit(editor, "editor-label").text()
            == "io.github.macos-task-scheduler.user.daily-backup"
        )
        assert combo(editor).currentIndex() == 0
        assert stack(editor).currentIndex() == 0
        assert (
            line_edit(editor, "editor-interpreter").text()
            == "/Users/example/project/.venv/bin/python"
        )
        assert line_edit(editor, "editor-script").text() == "/Users/example/project/main.py"
        assert table(editor, "editor-python-arguments").rows() == [["--mode"], ["daily"]]
        assert line_edit(editor, "editor-time").text() == "07:30"
        assert checkbox(editor, "monday").isChecked()
        assert not checkbox(editor, "tuesday").isChecked()
        assert line_edit(editor, "editor-working-directory").text() == ""

    def test_shell_job_populated(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A stored shell job lands on the shell page."""
        job = make_job(
            command=ShellCommand(executable="/bin/bash", arguments=["-c", "echo hi"]),
        )
        _, editor, _ = make_editor(qtbot, tmp_path, job=job)
        assert combo(editor).currentIndex() == 1
        assert stack(editor).currentIndex() == 1
        assert line_edit(editor, "editor-shell-executable").text() == "/bin/bash"
        assert table(editor, "editor-shell-arguments").rows() == [["-c"], ["echo hi"]]

    def test_executable_job_populated(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A stored executable job lands on the executable page."""
        job = make_job(
            command=ExecutableCommand(executable="/usr/bin/say", arguments=["--repeat", "2"]),
        )
        _, editor, _ = make_editor(qtbot, tmp_path, job=job)
        assert combo(editor).currentIndex() == 2
        assert stack(editor).currentIndex() == 2
        assert line_edit(editor, "editor-executable").text() == "/usr/bin/say"
        assert table(editor, "editor-executable-arguments").rows() == [["--repeat"], ["2"]]

    def test_environment_and_logs_populated(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Environment rows, working directory, and log paths are restored."""
        job = make_job(
            environment=EnvironmentConfig(variables={"HOME": "/tmp"}),
            working_directory="/Users/example/project",
            logging=LoggingConfig(stdout_path=Path("/tmp/out.log"), stderr_path=None),
        )
        _, editor, _ = make_editor(qtbot, tmp_path, job=job)
        assert table(editor, "editor-environment").rows() == [["HOME", "/tmp"]]
        assert line_edit(editor, "editor-working-directory").text() == "/Users/example/project"
        assert line_edit(editor, "editor-stdout-path").text() == "/tmp/out.log"
        assert line_edit(editor, "editor-stderr-path").text() == ""


class TestKindSwitching:
    def test_selecting_kind_switches_page(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Moving the combo follows with the page stack."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        box = combo(editor)
        box.setCurrentIndex(1)
        assert stack(editor).currentIndex() == 1
        box.setCurrentIndex(2)
        assert stack(editor).currentIndex() == 2
        box.setCurrentIndex(0)
        assert stack(editor).currentIndex() == 0
