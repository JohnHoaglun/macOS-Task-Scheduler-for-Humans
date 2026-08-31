"""Tests for the lifecycle result dialog (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton
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
    ProcessLaunchFailure,
    ProcessResult,
)
from task_scheduler.platform.macos.process_runner import LaunchFailureKind

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


def _title(dialog: LifecycleResultDialog) -> QLabel:
    title = dialog.findChild(QLabel, "lifecycle-result-title")
    assert title is not None
    return title


def _exit_label(dialog: LifecycleResultDialog) -> QLabel:
    label = dialog.findChild(QLabel, "lifecycle-result-exit")
    assert label is not None
    return label


class TestHeadline:
    def test_success_headline(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.INSTALL,
            label=LABEL,
            result=_install_result(),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        assert _title(dialog).text() == f"Install succeeded for {LABEL}."

    def test_exception_failure_headline(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE,
            label=LABEL,
            result=None,
            error="launchd refused the request",
        )
        dialog = _dialog(qtbot, outcome)
        assert (
            _title(dialog).text()
            == f"Enable failed for {LABEL}: launchd refused the request."
        )

    def test_nonzero_exit_headline_has_no_reason_suffix(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.RUN_NOW,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.TRIGGER, process=_process(exit_code=69)
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        assert _title(dialog).text() == f"Run Now failed for {LABEL}."


class TestExitCode:
    def test_no_process_ran(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.UNINSTALL, label=LABEL, result=None, error="boom"
        )
        dialog = _dialog(qtbot, outcome)
        exit_label = _exit_label(dialog)
        assert exit_label.text() == "Exit code: unavailable (no launchd process ran)"

    def test_launch_failure_is_named(self, qtbot: QtBot) -> None:
        failure = ProcessLaunchFailure(
            kind=LaunchFailureKind.NOT_FOUND,
            message="no such file or directory",
        )
        outcome = LifecycleOutcome(
            action=LifecycleAction.DISABLE,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.DISABLE,
                process=_process(exit_code=None, launch_failure=failure),
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        exit_label = _exit_label(dialog)
        assert "launchd did not start" in exit_label.text()
        assert "no such file or directory" in exit_label.text()

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

    def test_exit_code_value(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.RUN_NOW,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.TRIGGER, process=_process(exit_code=3)
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        exit_label = _exit_label(dialog)
        assert exit_label.text() == "Exit code: 3"


class TestOutputPanes:
    def test_stdout_shown_and_empty_stderr_hidden(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.ENABLE,
                process=_process(stdout="booted\n"),
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        stdout = dialog.findChild(QPlainTextEdit, "lifecycle-result-stdout")
        stderr = dialog.findChild(QPlainTextEdit, "lifecycle-result-stderr")
        assert stdout is not None and stderr is not None
        assert stdout.isVisible()
        assert stdout.toPlainText() == "booted\n"
        assert not stderr.isVisible()

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

    def test_both_hidden_without_result(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE, label=LABEL, result=None, error="boom"
        )
        dialog = _dialog(qtbot, outcome)
        stdout = dialog.findChild(QPlainTextEdit, "lifecycle-result-stdout")
        stderr = dialog.findChild(QPlainTextEdit, "lifecycle-result-stderr")
        assert stdout is not None and stderr is not None
        assert not stdout.isVisible()
        assert not stderr.isVisible()


class TestTechnicalDetails:
    def _technical(self, dialog: LifecycleResultDialog) -> QPlainTextEdit:
        pane = dialog.findChild(QPlainTextEdit, "lifecycle-technical-details")
        assert pane is not None
        return pane

    def test_hidden_until_toggled(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE,
            label=LABEL,
            result=LaunchctlResult(
                action=LaunchctlAction.ENABLE, process=_process()
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        pane = self._technical(dialog)
        toggle = dialog.findChild(QPushButton, "lifecycle-details-toggle")
        assert toggle is not None
        assert not pane.isVisible()
        toggle.setChecked(True)
        assert pane.isVisible()
        toggle.setChecked(False)
        assert not pane.isVisible()

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

    def test_uninstall_catalog_removed(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.UNINSTALL,
            label=LABEL,
            result=UninstallResult(
                label=LABEL, process=_process(), catalog_removed=True
            ),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        assert (
            self._technical(dialog).toPlainText() == "catalog record removed: True"
        )

    def test_launchctl_action(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE,
            label=LABEL,
            result=LaunchctlResult(action=LaunchctlAction.ENABLE, process=_process()),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        assert (
            self._technical(dialog).toPlainText() == "launchctl action: enable"
        )

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


class TestCloseButton:
    def test_close_accepts_the_dialog(self, qtbot: QtBot) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.ENABLE,
            label=LABEL,
            result=LaunchctlResult(action=LaunchctlAction.ENABLE, process=_process()),
            error=None,
        )
        dialog = _dialog(qtbot, outcome)
        close = dialog.findChild(QPushButton, "lifecycle-result-close")
        assert close is not None
        close.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
