"""Tests for the lifecycle result dialog (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPlainTextEdit,
)
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application.task_command_service import (
    InstallPhase,
    InstallResult,
    UninstallResult,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleOutcome,
)
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog
from task_scheduler.platform.macos import (
    LaunchAgentStatus,
    LaunchctlAction,
    LaunchctlResult,
    ProcessResult,
)

LABEL = "io.github.macos-task-scheduler.user.daily-backup"
PLIST_PATH = Path("/Users/example/Library/LaunchAgents/com.example.backup.plist")

def _process(**overrides: object) -> ProcessResult:
    kwargs: dict[str, object] = {"exit_code": 0}
    kwargs.update(overrides)
    return ProcessResult(**kwargs)  # type: ignore[arg-type]

def _install_result(**overrides: object) -> InstallResult:
    kwargs: dict[str, object] = {
        "job": make_job(),
        "plist_path": PLIST_PATH,
        "process": _process(),
    }
    kwargs.update(overrides)
    return InstallResult(**kwargs)  # type: ignore[arg-type]

def _dialog(qtbot: QtBot, outcome: LifecycleOutcome) -> LifecycleResultDialog:
    dialog = LifecycleResultDialog(outcome)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog

def _exit_label(dialog: LifecycleResultDialog) -> QLabel:
    label = dialog.findChild(QLabel, "lifecycle-result-exit")
    assert label is not None
    return label

class TestExitCode:

    def test_exit_code_none_without_failure(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.DISABLE,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.DISABLE, process=_process(exit_code=None)
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        exit_label = _exit_label(dialog)
        assert exit_label.text() == "Exit code: unavailable (launchd did not start)"

class TestOutputPanes:

    def test_both_shown_when_present(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.UNINSTALL,
            label=LABEL,
            result=UninstallResult(
                label=LABEL,
                process=_process(stdout="out", stderr="err"),
                catalog_removed=True,
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        stdout = dialog.findChild(QPlainTextEdit, "lifecycle-result-stdout")
        stderr = dialog.findChild(QPlainTextEdit, "lifecycle-result-stderr")
        assert stdout is not None and stderr is not None
        assert stdout.isVisible() and stdout.toPlainText() == "out"
        assert stderr.isVisible() and stderr.toPlainText() == "err"

class TestTechnicalDetails:
    def _technical(self, dialog: LifecycleResultDialog) -> QPlainTextEdit:
        pane = dialog.findChild(QPlainTextEdit, "lifecycle-technical-details")
        assert pane is not None
        return pane

    def test_install_phases_completed_and_retained(self, qtbot: QtBot) -> None:
        retained = PLIST_PATH.parent / "com.example.backup.plist.staged"
        result = _install_result(
            phases=(InstallPhase(name="bootstrap", process=_process()),),
            completed_phases=("bootstrap",),
            retained_artifacts=(retained,),
        )
        outcome = LifecycleOutcome(
            action=LifecycleAction.REINSTALL, label=LABEL, result=result, error=None
        )
        dialog = _dialog(qtbot, outcome)
        text = self._technical(dialog).toPlainText()
        assert "bootstrap: exit 0" in text
        assert "completed: bootstrap" in text
        assert str(retained) in text

    def test_status_loaded(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.INSTALL,
            label=LABEL,
            result=LaunchAgentStatus(loaded=True, process=_process()),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        assert self._technical(dialog).toPlainText() == "loaded in launchd: True"

    def test_no_result(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.DISABLE, label=LABEL, result=None, error="boom"
        )
        dialog = _dialog(qtbot, outcome)
        assert self._technical(dialog).toPlainText() == "(no launchd process ran)"

class TestDiagnosticsGroup:
    def _box(self, dialog: LifecycleResultDialog) -> QGroupBox:
        box = dialog.findChild(QGroupBox, "lifecycle-result-diagnostics")
        assert box is not None
        return box
