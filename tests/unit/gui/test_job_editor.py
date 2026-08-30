"""Tests for the JobEditor dialog (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
)
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
    editor.show()
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


def fill_valid_python(editor: JobEditor) -> None:
    """Fill a new python draft so it validates."""
    line_edit(editor, "editor-name").setText("Nightly Sync")
    line_edit(editor, "editor-interpreter").setText("/tmp/venv/bin/python")
    line_edit(editor, "editor-script").setText("/tmp/nightly.py")
    line_edit(editor, "editor-time").setText("01:00")
    checkbox(editor, "monday").setChecked(True)


def errors(editor: JobEditor) -> QPlainTextEdit:
    """The hidden error pane, asserted present."""
    found = editor.findChild(QPlainTextEdit, "editor-errors")
    assert found is not None
    return found


def preview(editor: JobEditor) -> QTextEdit:
    """The preview pane, asserted present."""
    found = editor.findChild(QTextEdit, "editor-preview")
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


class TestValidation:
    def test_valid_draft_validate_keeps_errors_hidden(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A valid draft passes validate with no error pane shown."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fill_valid_python(editor)
        button(editor, "editor-validate").click()
        assert not errors(editor).isVisible()
        assert button(editor, "editor-save").isEnabled()

    def test_empty_draft_validate_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        """An empty draft fails validate, shows the pane, disables Save."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-validate").click()
        assert errors(editor).isVisible()
        assert errors(editor).toPlainText().strip()
        assert not button(editor, "editor-save").isEnabled()

    def test_label_edit_updates_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Typing a label pushes it into the draft as a manual label."""
        _, editor, _ = make_editor(qtbot, tmp_path, job=make_job())
        line_edit(editor, "editor-label").textEdited.emit("my.custom.label")
        assert editor._draft is not None
        assert editor._draft.label == "my.custom.label"
        assert editor._draft.label_touched is True

    def test_edit_reenables_save_after_failure(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Any field edit re-enables Save after a failed outcome."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-validate").click()
        assert not button(editor, "editor-save").isEnabled()
        line_edit(editor, "editor-name").textEdited.emit("x")
        assert button(editor, "editor-save").isEnabled()


class TestPreview:
    def test_valid_preview_renders_plist(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A valid draft renders a plist containing the name-derived label."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        pane = preview(editor)
        fill_valid_python(editor)
        button(editor, "editor-preview").click()
        text = pane.toPlainText()
        assert "<plist" in text
        assert "nightly-sync" in text
        assert not errors(editor).isVisible()

    def test_invalid_preview_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        """An invalid draft shows errors instead of a preview."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-preview").click()
        assert errors(editor).isVisible()
        assert preview(editor).toPlainText() == ""
        assert not button(editor, "editor-save").isEnabled()


class TestSave:
    def test_saved_properties_initially_none(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A fresh dialog reports no saved path or label."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        assert editor.saved_path is None
        assert editor.saved_label is None

    def test_save_valid_writes_catalog(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Saving a valid draft accepts and writes a catalog file."""
        world, editor, _ = make_editor(qtbot, tmp_path)
        fill_valid_python(editor)
        button(editor, "editor-save").click()
        assert editor.result() == 1
        assert editor.saved_path is not None and editor.saved_path.is_file()
        assert editor.saved_label is not None
        assert editor.saved_label.startswith("io.github.macos-task-scheduler.user.")
        assert world.catalog_root in editor.saved_path.parents

    def test_save_invalid_rejects(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Saving an invalid draft shows errors and writes nothing."""
        world, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-save").click()
        assert editor.result() == 0
        assert errors(editor).isVisible()
        assert editor.saved_path is None
        assert not button(editor, "editor-save").isEnabled()


class TestCloseAndBrowse:
    def test_close_rejects(self, qtbot: QtBot, tmp_path: Path) -> None:
        """The Close button rejects the dialog."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-close").click()
        assert editor.result() == 0

    def test_browse_open_sets_path(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browse dialog path lands in the line edit."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *args, **kwargs: ("/tmp/venv/bin/python", "")),
        )
        button(editor, "editor-interpreter-browse").click()
        assert line_edit(editor, "editor-interpreter").text() == "/tmp/venv/bin/python"

    def test_browse_directory_sets_path(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directory browse mode writes the chosen directory."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            staticmethod(lambda *args, **kwargs: "/tmp/workdir"),
        )
        button(editor, "editor-working-directory-browse").click()
        assert line_edit(editor, "editor-working-directory").text() == "/tmp/workdir"

    def test_browse_empty_path_unchanged(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cancelled browse leaves the line edit untouched."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *args, **kwargs: ("", "")),
        )
        line_edit(editor, "editor-interpreter").setText("/keep/this")
        button(editor, "editor-interpreter-browse").click()
        assert line_edit(editor, "editor-interpreter").text() == "/keep/this"

    def test_browse_save_sets_path(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Save-mode browse writes the chosen file path into the line edit."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        monkeypatch.setattr(
            QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *args, **kwargs: ("/tmp/out.log", "")),
        )
        button(editor, "editor-stdout-path-browse").click()
        assert line_edit(editor, "editor-stdout-path").text() == "/tmp/out.log"


class TestUnopenedDialog:
    def test_actions_noop_without_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Action slots no-op on a dialog that was never opened."""
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services))
        qtbot.addWidget(editor)
        editor._load_draft()
        editor._collect()
        button(editor, "editor-validate").click()
        button(editor, "editor-preview").click()
        button(editor, "editor-save").click()
        assert not errors(editor).isVisible()
        assert editor.result() == 0
