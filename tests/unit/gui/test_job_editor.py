"""Tests for the JobEditor dialog (offscreen Qt)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLabel,
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
from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.presenters.agent_presenter import (
    PREVIEW_HEADING,
    PREVIEW_INCOMPLETE,
)
from task_scheduler.gui.widgets.direct_test_dialog import DirectTestDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.row_table import RowTable
from task_scheduler.platform.macos import (
    CandidateSource,
    InterpreterCandidate,
    PythonDetectionResult,
)
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


def _detection_result(
    script_text: str, candidates, working_directory=None,
) -> PythonDetectionResult:
    """A canned detection result for dialog tests."""
    return PythonDetectionResult(
        script=Path(script_text),
        candidates=candidates,
        working_directory=working_directory,
    )


def fake_detection(
    editor: JobEditor,
    candidates,
    working_directory=None,
) -> None:
    """Replace the controller's detect_python with a canned responder."""
    editor._controller.detect_python = lambda script: _detection_result(
        str(script), candidates, working_directory
    )


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

    def test_test_draft_noop_without_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Test Draft no-ops on a dialog that was never opened."""
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(
            EditorController(world.services),
            diagnostics=DiagnosticsController(world.services, {}),
        )
        qtbot.addWidget(editor)
        button(editor, "editor-test-draft").click()
        assert not errors(editor).isVisible()


class TestPythonDetection:
    def test_note_initial(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A fresh python page shows the idle detection note."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None
        assert note.text() == "Select a script to detect its interpreter."

    def test_script_change_populates_candidates(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Editing the script fills the candidate combo with sources."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [
                InterpreterCandidate(
                    path=Path("/tmp/proj/.venv/bin/python"), source=CandidateSource.VENV
                ),
                InterpreterCandidate(path=Path("/usr/bin/python3"), source=CandidateSource.PATH),
            ],
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        combo = editor.findChild(QComboBox, "editor-candidates")
        assert combo is not None
        assert combo.count() == 2
        assert combo.itemText(0) == "/tmp/proj/.venv/bin/python (.venv)"
        use = button(editor, "editor-use-candidate")
        assert use.isEnabled()

    def test_use_candidate_populates_interpreter_and_working_dir(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Using a candidate fills the interpreter and the empty working dir."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [
                InterpreterCandidate(
                    path=Path("/tmp/proj/.venv/bin/python"), source=CandidateSource.VENV
                )
            ],
            working_directory=Path("/tmp/proj"),
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        combo = editor.findChild(QComboBox, "editor-candidates")
        assert combo is not None
        combo.setCurrentIndex(0)
        button(editor, "editor-use-candidate").click()
        assert line_edit(editor, "editor-interpreter").text() == "/tmp/proj/.venv/bin/python"
        assert line_edit(editor, "editor-working-directory").text() == "/tmp/proj"

    def test_no_candidates_informs(self, qtbot: QtBot, tmp_path: Path) -> None:
        """An empty candidate list disables Use and shows the no-match note."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(editor, [])
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        combo = editor.findChild(QComboBox, "editor-candidates")
        assert combo is not None
        assert combo.count() == 0
        assert not button(editor, "editor-use-candidate").isEnabled()
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None
        assert note.text() == (
            "No interpreters detected for this script. Type the interpreter path above."
        )

    def test_script_cleared_resets_detection(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Blanking the script clears candidates and resets the note."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [InterpreterCandidate(path=Path("/usr/bin/python3"), source=CandidateSource.PATH)],
        )
        script = line_edit(editor, "editor-script")
        script.setText("/tmp/proj/main.py")
        combo = editor.findChild(QComboBox, "editor-candidates")
        assert combo is not None
        assert combo.count() == 1
        script.setText("")
        assert combo.count() == 0
        assert not button(editor, "editor-use-candidate").isEnabled()


def make_test_draft_editor(
    qtbot: QtBot, tmp_path: Path, job: JobDefinition | None = None
) -> tuple[FakeTaskWorld, JobEditor]:
    """An editor with a diagnostics controller, ready to run Test Draft."""
    world = FakeTaskWorld(tmp_path)
    controller = EditorController(world.services)
    editor = JobEditor(
        controller, diagnostics=DiagnosticsController(world.services, {})
    )
    qtbot.addWidget(editor)
    if job is None:
        editor.open_new()
    else:
        editor.open_existing(job)
    editor.show()
    return world, editor


def fake_dialog_exec(monkeypatch: pytest.MonkeyPatch) -> list[JobDefinition]:
    """Replace DirectTestDialog.exec with a recorder; returns the captured jobs."""
    opened: list[JobDefinition] = []

    def fake_exec(self: DirectTestDialog) -> int:
        opened.append(self._job)
        return 1

    monkeypatch.setattr(DirectTestDialog, "exec", fake_exec)
    return opened


class TestDirectTestDraft:
    def test_button_disabled_without_diagnostics(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Without a diagnostics controller, Test Draft stays disabled."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        assert not button(editor, "editor-test-draft").isEnabled()

    def test_button_enabled_with_diagnostics(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """With a diagnostics controller, Test Draft is enabled."""
        _, editor = make_test_draft_editor(qtbot, tmp_path)
        assert button(editor, "editor-test-draft").isEnabled()

    def test_invalid_draft_shows_errors_and_opens_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalid draft shows field errors, opens no dialog, saves nothing."""
        world, editor = make_test_draft_editor(qtbot, tmp_path)
        opened = fake_dialog_exec(monkeypatch)
        button(editor, "editor-test-draft").click()
        assert opened == []
        assert errors(editor).isVisible()
        assert errors(editor).toPlainText().strip()
        assert editor.saved_path is None
        assert editor.saved_label is None

    def test_valid_draft_opens_dialog_with_canonical_job(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid current draft opens the dialog holding the built job."""
        world, editor = make_test_draft_editor(qtbot, tmp_path, job=make_job())
        opened = fake_dialog_exec(monkeypatch)
        button(editor, "editor-test-draft").click()
        assert len(opened) == 1
        assert opened[0].label == make_job().label
        assert world.jobs.find(opened[0].label) is None
        assert editor.saved_path is None
        assert editor.saved_label is None

    def test_test_draft_uses_current_edited_fields(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fields edited before the click are part of the tested job."""
        _, editor = make_test_draft_editor(qtbot, tmp_path, job=make_job())
        opened = fake_dialog_exec(monkeypatch)
        line_edit(editor, "editor-name").setText("Renamed Backup")
        button(editor, "editor-test-draft").click()
        assert len(opened) == 1
        assert opened[0].name == "Renamed Backup"
        assert opened[0].label == make_job().label


PREVIEW_NOW = datetime(2026, 9, 4, 12, 0)  # Friday
PREVIEW_LINES_0730 = (
    "Mon Sep 07 07:30\n"
    "Mon Sep 14 07:30\n"
    "Mon Sep 21 07:30\n"
    "Mon Sep 28 07:30\n"
    "Mon Oct 05 07:30"
)
PREVIEW_LINES_0800 = (
    "Mon Sep 07 08:00\n"
    "Mon Sep 14 08:00\n"
    "Mon Sep 21 08:00\n"
    "Mon Sep 28 08:00\n"
    "Mon Oct 05 08:00"
)


class TestSchedulePreview:
    """Increment 15: the live next-run preview in the editor's Schedule group."""

    def _fixed_editor(
        self, qtbot: QtBot, tmp_path: Path, job: JobDefinition | None
    ) -> JobEditor:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services), clock=lambda: PREVIEW_NOW)
        qtbot.addWidget(editor)
        if job is None:
            editor.open_new()
        else:
            editor.open_existing(job)
        editor.show()
        return editor

    def test_existing_job_shows_preview(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, make_job())
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_LINES_0730
        heading = editor.findChild(QLabel, "editor-preview-heading")
        assert heading is not None
        assert heading.text() == PREVIEW_HEADING

    def test_new_job_starts_neutral(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, None)
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_INCOMPLETE

    def test_time_edit_refreshes_preview(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, make_job())
        edit = line_edit(editor, "editor-time")
        edit.selectAll()
        qtbot.keyClicks(edit, "08:00")
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_LINES_0800

    def test_invalid_time_is_neutral(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, make_job())
        edit = line_edit(editor, "editor-time")
        edit.selectAll()
        qtbot.keyClicks(edit, "25:99")
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_INCOMPLETE

    def test_no_weekday_selected_is_neutral(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, make_job())
        checkbox(editor, "monday").setChecked(False)
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_INCOMPLETE
