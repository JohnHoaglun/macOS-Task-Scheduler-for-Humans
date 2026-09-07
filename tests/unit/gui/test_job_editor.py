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
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.domain import (
    JobDefinition,
)
from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.presenters.agent_presenter import (
    PREVIEW_INCOMPLETE,
)
from task_scheduler.gui.widgets.direct_test_dialog import DirectTestDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.platform.macos import (
    CandidateSource,
    DetectionNote,
    DetectorKind,
    InterpreterCandidate,
    PythonDetectionResult,
)


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
    script_text: str,
    candidates,
    working_directory=None,
    notes=None,
) -> PythonDetectionResult:
    """A canned detection result for dialog tests."""
    return PythonDetectionResult(
        script=Path(script_text),
        candidates=candidates,
        working_directory=working_directory,
        notes=notes or [],
    )

def fake_detection(
    editor: JobEditor,
    candidates,
    working_directory=None,
    notes=None,
) -> None:
    """Replace the controller's detect_python with a canned responder."""
    editor._controller.detect_python = lambda script: _detection_result(
        str(script), candidates, working_directory, notes
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

    def test_label_edit_updates_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Typing a label pushes it into the draft as a manual label."""
        _, editor, _ = make_editor(qtbot, tmp_path, job=make_job())
        line_edit(editor, "editor-label").textEdited.emit("my.custom.label")
        assert editor._draft is not None
        assert editor._draft.label == "my.custom.label"
        assert editor._draft.label_touched is True

class TestPreview:

    def test_invalid_preview_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        """An invalid draft shows errors instead of a preview."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-preview").click()
        assert errors(editor).isVisible()
        assert preview(editor).toPlainText() == ""
        assert not button(editor, "editor-save").isEnabled()

class TestSave:

    def test_save_invalid_rejects(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Saving an invalid draft shows errors and writes nothing."""
        world, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-save").click()
        assert editor.result() == 0
        assert errors(editor).isVisible()
        assert editor.saved_path is None
        assert not button(editor, "editor-save").isEnabled()

class TestCloseAndBrowse:

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

    def test_no_candidates_with_notes_appends_to_base_note(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Notes also append to the no-match base note."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [],
            notes=[DetectionNote(detector=DetectorKind.POETRY, message="poetry note line")],
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None
        assert note.text() == (
            "No interpreters detected for this script. Type the interpreter path above.\n"
            "poetry note line"
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
    editor = JobEditor(controller, diagnostics=DiagnosticsController(world.services, {}))
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
    "Mon Sep 07 07:30\nMon Sep 14 07:30\nMon Sep 21 07:30\nMon Sep 28 07:30\nMon Oct 05 07:30"
)
PREVIEW_LINES_0800 = (
    "Mon Sep 07 08:00\nMon Sep 14 08:00\nMon Sep 21 08:00\nMon Sep 28 08:00\nMon Oct 05 08:00"
)
PREVIEW_LINES_MULTI = (
    "Mon Sep 07 07:30\nMon Sep 07 17:30\nMon Sep 14 07:30\nMon Sep 14 17:30\nMon Sep 21 07:30"
)

class TestSchedulePreview:
    """Increment 15: the live next-run preview in the editor's Schedule group."""

    def _fixed_editor(self, qtbot: QtBot, tmp_path: Path, job: JobDefinition | None) -> JobEditor:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services), clock=lambda: PREVIEW_NOW)
        qtbot.addWidget(editor)
        if job is None:
            editor.open_new()
        else:
            editor.open_existing(job)
        editor.show()
        return editor

    def test_time_edit_refreshes_preview(self, qtbot: QtBot, tmp_path: Path) -> None:
        editor = self._fixed_editor(qtbot, tmp_path, make_job())
        edit = line_edit(editor, "editor-time")
        edit.selectAll()
        qtbot.keyClicks(edit, "08:00")
        preview = editor.findChild(QLabel, "editor-preview-occurrences")
        assert preview is not None
        assert preview.text() == PREVIEW_LINES_0800

class TestMultiTimeSchedule:
    """Increment 16: multi-time calendar authoring through the time row editor."""

    def _occurrences(self, editor: JobEditor) -> str:
        """The live preview text, asserted present."""
        label = editor.findChild(QLabel, "editor-preview-occurrences")
        assert label is not None
        return label.text()

    def _fixed_editor(self, qtbot: QtBot, tmp_path: Path) -> JobEditor:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services), clock=lambda: PREVIEW_NOW)
        qtbot.addWidget(editor)
        editor.open_existing(make_job())
        editor.show()
        return editor

PREVIEW_INTERVAL_LINES_900 = (
    "Fri Sep 04 12:15:00\n"
    "Fri Sep 04 12:30:00\n"
    "Fri Sep 04 12:45:00\n"
    "Fri Sep 04 13:00:00\n"
    "Fri Sep 04 13:15:00"
)
PREVIEW_INTERVAL_LINES_61 = (
    "Fri Sep 04 12:01:01\n"
    "Fri Sep 04 12:02:02\n"
    "Fri Sep 04 12:03:03\n"
    "Fri Sep 04 12:04:04\n"
    "Fri Sep 04 12:05:05"
)

class TestIntervalSchedule:
    """Increment 17: interval and login-trigger authoring through the Schedule group."""

    def _kind_combo(self, editor: JobEditor) -> QComboBox:
        """The schedule-kind combo box, asserted present."""
        found = editor.findChild(QComboBox, "editor-schedule-kind")
        assert found is not None
        return found

    def _unit_combo(self, editor: JobEditor) -> QComboBox:
        """The interval-unit combo box, asserted present."""
        found = editor.findChild(QComboBox, "editor-interval-unit")
        assert found is not None
        return found

    def _schedule_stack(self, editor: JobEditor) -> QStackedWidget:
        """The schedule page stack, asserted present."""
        found = editor.findChild(QStackedWidget, "editor-schedule-stack")
        assert found is not None
        return found

    def _run_at_load(self, editor: JobEditor) -> QCheckBox:
        """The Run at login checkbox, asserted present."""
        found = editor.findChild(QCheckBox, "editor-run-at-load")
        assert found is not None
        return found

    def _occurrences(self, editor: JobEditor) -> str:
        """The live preview text, asserted present."""
        label = editor.findChild(QLabel, "editor-preview-occurrences")
        assert label is not None
        return label.text()

    def _fill_command(self, editor: JobEditor) -> None:
        """Fill the command fields so a draft can validate or save."""
        line_edit(editor, "editor-name").setText("Nightly Sync")
        line_edit(editor, "editor-interpreter").setText("/tmp/venv/bin/python")
        line_edit(editor, "editor-script").setText("/tmp/nightly.py")

    def _fixed_editor(self, qtbot: QtBot, tmp_path: Path) -> JobEditor:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services), clock=lambda: PREVIEW_NOW)
        qtbot.addWidget(editor)
        editor.open_new()
        editor.show()
        return editor

    @pytest.mark.parametrize("value", ["1.5", "abc", "0", "-5"])
    def test_invalid_interval_value_is_neutral(
        self, qtbot: QtBot, tmp_path: Path, value: str
    ) -> None:
        """A non-whole, zero, or negative duration keeps the preview neutral."""
        editor = self._fixed_editor(qtbot, tmp_path)
        self._kind_combo(editor).setCurrentIndex(1)
        edit = line_edit(editor, "editor-interval-value")
        edit.selectAll()
        qtbot.keyClicks(edit, value)
        assert self._occurrences(editor) == PREVIEW_INCOMPLETE

    def test_sub_minimum_interval_is_neutral(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A duration below the domain minimum keeps the preview neutral."""
        editor = self._fixed_editor(qtbot, tmp_path)
        self._kind_combo(editor).setCurrentIndex(1)
        self._unit_combo(editor).setCurrentIndex(0)
        edit = line_edit(editor, "editor-interval-value")
        edit.selectAll()
        qtbot.keyClicks(edit, "30")
        assert self._occurrences(editor) == PREVIEW_INCOMPLETE

    def test_interval_preview_xml(self, qtbot: QtBot, tmp_path: Path) -> None:
        """An interval draft previews a plist with StartInterval plus RunAtLoad."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        self._fill_command(editor)
        self._kind_combo(editor).setCurrentIndex(1)
        line_edit(editor, "editor-interval-value").setText("15")
        self._run_at_load(editor).setChecked(True)
        button(editor, "editor-preview").click()
        text = preview(editor).toPlainText()
        assert "<key>StartInterval</key>" in text
        assert "<integer>900</integer>" in text
        assert "<key>RunAtLoad</key>" in text
        assert "StartCalendarInterval" not in text
