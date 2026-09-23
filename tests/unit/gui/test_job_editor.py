"""Tests for the JobEditor dialog (offscreen Qt)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QThread
from PySide6.QtGui import QFontMetrics
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

from task_scheduler.application.job_service import default_job_logs_root, managed_label
from task_scheduler.domain import JobDefinition, LoggingConfig
from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.presenters.agent_presenter import PREVIEW_INCOMPLETE
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
    world = FakeTaskWorld(tmp_path)
    controller = EditorController(world.services)
    editor = JobEditor(controller, detection_debounce_ms=0)
    qtbot.addWidget(editor)
    if job is None:
        editor.open_new()
    else:
        editor.open_existing(job)
    editor.show()
    return world, editor, controller


def line_edit(editor: JobEditor, object_name: str) -> QLineEdit:
    edit = editor.findChild(QLineEdit, object_name)
    assert edit is not None
    return edit


def label(editor: JobEditor) -> QLabel:
    assert editor.findChild(QLineEdit, "editor-label") is None
    found = editor.findChild(QLabel, "editor-label")
    assert found is not None
    return found


def button(editor: JobEditor, object_name: str) -> QPushButton:
    found = editor.findChild(QPushButton, object_name)
    assert found is not None
    return found


def checkbox(editor: JobEditor, day: str) -> QCheckBox:
    found = editor.findChild(QCheckBox, f"editor-weekday-{day}")
    assert found is not None
    return found


def combo(editor: JobEditor) -> QComboBox:
    found = editor.findChild(QComboBox, "editor-command-kind")
    assert found is not None
    return found


def stack(editor: JobEditor) -> QStackedWidget:
    found = editor.findChild(QStackedWidget, "editor-command-stack")
    assert found is not None
    return found


def fill_valid_python(editor: JobEditor) -> None:
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
    editor._controller.detect_python = lambda script: _detection_result(
        str(script), candidates, working_directory, notes
    )


def _cand(path: str, source: CandidateSource) -> InterpreterCandidate:
    return InterpreterCandidate(path=Path(path), source=source)


def errors(editor: JobEditor) -> QPlainTextEdit:
    found = editor.findChild(QPlainTextEdit, "editor-errors")
    assert found is not None
    return found


def preview(editor: JobEditor) -> QTextEdit:
    found = editor.findChild(QTextEdit, "editor-preview")
    assert found is not None
    return found


class TestKindSwitching:
    def test_selecting_kind_switches_page(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        box = combo(editor)
        box.setCurrentIndex(1)
        assert stack(editor).currentIndex() == 1
        box.setCurrentIndex(2)
        assert stack(editor).currentIndex() == 2
        box.setCurrentIndex(0)
        assert stack(editor).currentIndex() == 0


class TestValidation:
    def test_valid_draft_validate_shows_success(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A valid draft shows a non-saving success result and leaves Save enabled."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        fill_valid_python(editor)
        button(editor, "editor-validate").click()
        assert errors(editor).isVisible()
        assert errors(editor).toPlainText() == "No issues found."
        assert button(editor, "editor-save").isEnabled()


class TestIdentity:
    """The Identity group: one editable name, a plain-text derived label."""

    def test_label_is_plain_text(self, qtbot: QtBot, tmp_path: Path) -> None:
        job = make_job()
        _, editor, _ = make_editor(qtbot, tmp_path, job=job)
        shown = label(editor)
        assert shown.text() == job.label
        assert shown.wordWrap() is False
        assert shown.width() >= QFontMetrics(shown.font()).horizontalAdvance(job.label)

    def test_name_edit_auto_fills_label(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Typing a name derives the label into the plain-text display live."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        line_edit(editor, "editor-name").textEdited.emit("Nightly Sync")
        assert editor._draft is not None
        label_field = label(editor)
        assert label_field.text() == managed_label("Nightly Sync", editor._draft.job_id)
        assert editor._draft.label == label_field.text()
        assert editor._draft.label_touched is False

    def test_name_is_forced_to_lowercase(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Typing an uppercase name is rewritten to lowercase to match the label."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        name_field = line_edit(editor, "editor-name")
        name_field.textEdited.emit("Nightly Sync")
        assert name_field.text() == "nightly sync"
        assert editor._draft is not None
        assert editor._draft.name == "nightly sync"

    def test_renaming_existing_job_keeps_label(self, qtbot: QtBot, tmp_path: Path) -> None:
        job = make_job()
        _, editor, _ = make_editor(qtbot, tmp_path, job=job)
        line_edit(editor, "editor-name").textEdited.emit("Renamed Backup")
        assert editor._draft is not None
        assert label(editor).text() == job.label
        assert editor._draft.label == job.label


class TestPreview:
    def test_invalid_preview_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-preview").click()
        assert errors(editor).isVisible()
        assert preview(editor).toPlainText() == ""
        assert not button(editor, "editor-save").isEnabled()


class TestSave:
    def test_save_invalid_rejects(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-save").click()
        assert editor.result() == 0
        assert errors(editor).isVisible()
        assert editor.saved_path is None
        assert not button(editor, "editor-save").isEnabled()


class TestCloseAndBrowse:
    def test_browse_directory_sets_path(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake = staticmethod(lambda *_a: "/tmp/workdir")
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake)
        button(editor, "editor-working-directory-browse").click()
        assert line_edit(editor, "editor-working-directory").text() == "/tmp/workdir"

    def test_browse_empty_path_unchanged(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake = staticmethod(lambda *_a: ("", ""))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", fake)
        line_edit(editor, "editor-interpreter").setText("/keep/this")
        button(editor, "editor-interpreter-browse").click()
        assert line_edit(editor, "editor-interpreter").text() == "/keep/this"

    def test_new_draft_defaults_log_directory_and_derives_paths(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        """A new draft defaults to the app log root with task-derived stream paths."""
        _, editor, _ = make_editor(qtbot, tmp_path)
        root = str(default_job_logs_root())
        assert line_edit(editor, "editor-log-directory").text() == root
        assert line_edit(editor, "editor-stdout-path").text() == f"{root}/task.stdout.log"
        assert line_edit(editor, "editor-stderr-path").text() == f"{root}/task.stderr.log"

    def test_stream_fields_are_read_only_in_managed_mode(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        assert line_edit(editor, "editor-stdout-path").isReadOnly()
        assert line_edit(editor, "editor-stderr-path").isReadOnly()

    def test_browse_log_directory_derives_both_stream_paths(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake = staticmethod(lambda *_a: "/tmp/logs")
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake)
        line_edit(editor, "editor-name").textEdited.emit("Nightly Sync")
        button(editor, "editor-log-directory-browse").click()
        assert line_edit(editor, "editor-log-directory").text() == "/tmp/logs"
        assert line_edit(editor, "editor-stdout-path").text() == "/tmp/logs/nightly sync.stdout.log"
        assert line_edit(editor, "editor-stderr-path").text() == "/tmp/logs/nightly sync.stderr.log"


class TestUnopenedDialog:
    def test_actions_noop_without_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services))
        qtbot.addWidget(editor)
        editor._load_draft()
        editor._collect()
        editor._on_name_edited("new name")
        button(editor, "editor-validate").click()
        button(editor, "editor-preview").click()
        button(editor, "editor-save").click()
        assert not errors(editor).isVisible()
        assert editor.result() == 0

    def test_validate_invalid_draft_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        button(editor, "editor-validate").click()
        assert errors(editor).isVisible()

    def test_test_draft_noop_without_draft(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(
            EditorController(world.services),
            diagnostics=DiagnosticsController(world.services, {}),
        )
        qtbot.addWidget(editor)
        button(editor, "editor-test-draft").click()
        assert not errors(editor).isVisible()


class TestPythonDetection:
    def test_top_candidate_autofills_and_use_keeps_alternatives(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [
                InterpreterCandidate(
                    path=Path("/tmp/proj/.venv/bin/python"), source=CandidateSource.VENV
                ),
                InterpreterCandidate(path=Path("/usr/bin/python3"), source=CandidateSource.PATH),
            ],
            working_directory=Path("/tmp/proj"),
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        qtbot.wait(50)
        combo = editor.findChild(QComboBox, "editor-candidates")
        assert combo is not None
        assert line_edit(editor, "editor-interpreter").text() == "/tmp/proj/.venv/bin/python"
        assert line_edit(editor, "editor-working-directory").text() == "/tmp/proj"
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None
        assert "filled" in note.text()
        combo.setCurrentIndex(1)
        button(editor, "editor-use-candidate").click()
        assert line_edit(editor, "editor-interpreter").text() == "/usr/bin/python3"
        assert line_edit(editor, "editor-working-directory").text() == "/tmp/proj"

    def test_recommended_candidate_autofills_when_top_is_the_app_python(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [_cand("/app/.venv/bin/python3.14", CandidateSource.CURRENT),
             _cand("/opt/homebrew/bin/python3", CandidateSource.PATH)],
            working_directory=Path("/opt/homebrew"),
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        qtbot.wait(50)
        assert line_edit(editor, "editor-interpreter").text() == "/opt/homebrew/bin/python3"
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None and "filled" in note.text()

    def test_interpreter_warning_shows_for_app_venv(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        warning = editor.findChild(QLabel, "editor-interpreter-warning")
        assert warning is not None and not warning.isVisible()
        line_edit(editor, "editor-interpreter").setText(str(Path(sys.executable).parent / "python"))
        assert warning.isVisible() and "runs under" in warning.text()
        line_edit(editor, "editor-interpreter").setText("/tmp/other/bin/python")
        assert not warning.isVisible()

    def test_no_candidates_with_notes_appends_to_base_note(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        fake_detection(
            editor,
            [],
            notes=[DetectionNote(detector=DetectorKind.POETRY, message="poetry note line")],
        )
        editor.findChild(QLineEdit, "editor-script").setText("/tmp/proj/main.py")
        qtbot.wait(50)
        note = editor.findChild(QLabel, "editor-detection-note")
        assert note is not None
        assert note.text() == (
            "No interpreters detected for this script. Type the interpreter path above.\n"
            "poetry note line"
        )

    def test_rapid_edits_coalesce_to_one_detection(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        seen: list[str] = []
        editor._controller.detect_python = lambda s: (seen.append(s), _detection_result("", []))[1]
        for fragment in ("/tmp/", "/tmp/ma"):
            line_edit(editor, "editor-script").setText(fragment)
        line_edit(editor, "editor-script").setText("")
        editor._run_script_detection()
        assert seen == []
        line_edit(editor, "editor-script").setText("/tmp/main.py")
        qtbot.wait(50)
        assert seen == [Path("/tmp/main.py")]

    def test_loading_draft_schedules_no_detection(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor, _ = make_editor(qtbot, tmp_path)
        seen: list[str] = []
        editor._controller.detect_python = lambda s: (seen.append(s), _detection_result("", []))[1]
        assert editor._draft is not None
        editor._draft.script = "/tmp/nightly.py"
        editor._draft.interpreter = "/tmp/venv/bin/python"
        editor._load_draft()
        qtbot.wait(50)
        assert line_edit(editor, "editor-script").text() == "/tmp/nightly.py"
        assert seen == []


def make_test_draft_editor(
    qtbot: QtBot,
    tmp_path: Path,
    job: JobDefinition | None = None,
    *,
    on_test_worker_started: Callable[[QThread, QObject], None] | None = None,
) -> tuple[FakeTaskWorld, JobEditor]:
    world = FakeTaskWorld(tmp_path)
    controller = EditorController(world.services)
    editor = JobEditor(
        controller,
        diagnostics=DiagnosticsController(world.services, {}),
        on_test_worker_started=on_test_worker_started,
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
    def test_invalid_draft_shows_errors_and_opens_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, editor = make_test_draft_editor(qtbot, tmp_path, job=make_job())
        opened = fake_dialog_exec(monkeypatch)
        line_edit(editor, "editor-name").setText("Renamed Backup")
        button(editor, "editor-test-draft").click()
        assert len(opened) == 1
        assert opened[0].name == "Renamed Backup"
        assert opened[0].label == make_job().label


PREVIEW_NOW = datetime(2026, 9, 4, 12, 0)  # Friday
PREVIEW_LINES_0800 = (
    "Mon Sep 07 08:00\nMon Sep 14 08:00\nMon Sep 21 08:00\nMon Sep 28 08:00\nMon Oct 05 08:00"
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


class TestIntervalSchedule:
    """Increment 17: interval and login-trigger authoring through the Schedule group."""

    def _kind_combo(self, editor: JobEditor) -> QComboBox:
        found = editor.findChild(QComboBox, "editor-schedule-kind")
        assert found is not None
        return found

    def _unit_combo(self, editor: JobEditor) -> QComboBox:
        found = editor.findChild(QComboBox, "editor-interval-unit")
        assert found is not None
        return found

    def _schedule_stack(self, editor: JobEditor) -> QStackedWidget:
        found = editor.findChild(QStackedWidget, "editor-schedule-stack")
        assert found is not None
        return found

    def _run_at_load(self, editor: JobEditor) -> QCheckBox:
        found = editor.findChild(QCheckBox, "editor-run-at-load")
        assert found is not None
        return found

    def _occurrences(self, editor: JobEditor) -> str:
        """The live preview text, asserted present."""
        label = editor.findChild(QLabel, "editor-preview-occurrences")
        assert label is not None
        return label.text()

    def _fill_command(self, editor: JobEditor) -> None:
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
        self, qtbot: QtBot, tmp_path: Path, value: str) -> None:
        editor = self._fixed_editor(qtbot, tmp_path)
        self._kind_combo(editor).setCurrentIndex(1)
        edit = line_edit(editor, "editor-interval-value")
        edit.selectAll()
        qtbot.keyClicks(edit, value)
        assert self._occurrences(editor) == PREVIEW_INCOMPLETE

    def test_sub_minimum_interval_is_neutral(self, qtbot: QtBot, tmp_path: Path) -> None:
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


class TestExternalMode:
    EXTERNAL_LABEL = "com.example.external"

    def _open_external(self, qtbot: QtBot, tmp_path: Path) -> tuple[FakeTaskWorld, JobEditor]:
        world, editor, _ = make_editor(qtbot, tmp_path)
        job = make_job(label=self.EXTERNAL_LABEL, name="External Job")
        path = tmp_path / f"{self.EXTERNAL_LABEL}.plist"
        editor.open_external(path, job)
        return world, editor

    def test_external_save_invalid_shows_errors(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor = self._open_external(qtbot, tmp_path)
        line_edit(editor, "editor-script").setText("")
        button(editor, "editor-save").click()
        assert editor.result() == 0
        assert editor.edited_job is None
        assert errors(editor).isVisible()

    def test_external_detection_never_autofills(self, qtbot: QtBot, tmp_path: Path) -> None:
        _, editor = self._open_external(qtbot, tmp_path)
        line_edit(editor, "editor-interpreter").setText("")
        fake_detection(
            editor,
            [InterpreterCandidate(path=Path("/tmp/proj/python"), source=CandidateSource.VENV)],
        )
        line_edit(editor, "editor-script").setText("/tmp/proj/main.py")
        qtbot.wait(50)
        assert line_edit(editor, "editor-interpreter").text() == ""

    def test_external_mode_hides_log_directory_and_keeps_manual_paths(
        self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        editor = JobEditor(EditorController(world.services))
        qtbot.addWidget(editor)
        job = make_job(
            label=self.EXTERNAL_LABEL,
            name="External Job",
            logging=LoggingConfig(
                stdout_path=Path("/tmp/external/out.log"),
                stderr_path=Path("/tmp/external/err.log"),
            ),
        )
        editor.open_external(tmp_path / f"{self.EXTERNAL_LABEL}.plist", job)
        directory = editor.findChild(QLineEdit, "editor-log-directory")
        assert directory is not None
        assert not directory.isVisible()
        stdout = line_edit(editor, "editor-stdout-path")
        stderr = line_edit(editor, "editor-stderr-path")
        assert not stdout.isReadOnly()
        assert not stderr.isReadOnly()
        assert stdout.text() == "/tmp/external/out.log"
        assert stderr.text() == "/tmp/external/err.log"
        # The log-directory slot stays wired while hidden: its guard must keep
        # the manual external paths untouched.
        directory.textEdited.emit("/should/not/apply")
        line_edit(editor, "editor-name").textEdited.emit("renamed")
        assert stdout.text() == "/tmp/external/out.log"
        assert stderr.text() == "/tmp/external/err.log"
