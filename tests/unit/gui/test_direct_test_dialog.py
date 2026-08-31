"""Tests for the DirectTestDialog (offscreen Qt)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
from pytestqt.qtbot import QtBot

from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, LoggingConfig
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    RequestVerdict,
    TestOutcome,
)
from task_scheduler.gui.widgets.direct_test_dialog import DirectTestDialog
from task_scheduler.platform.macos import ProcessResult
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

DEFAULT_SUMMARY = "Run Test to check this task directly."


def _summary(dialog: DirectTestDialog) -> str:
    """The panel's summary line, asserted present."""
    label = dialog.panel.findChild(QLabel, "diagnostics-summary")
    assert label is not None
    return label.text()


def _tab(dialog: DirectTestDialog, object_name: str) -> str:
    """A named log tab's content, asserted present."""
    tab = dialog.panel.findChild(QPlainTextEdit, object_name)
    assert tab is not None
    return tab.toPlainText()


def _tab_env(dialog: DirectTestDialog) -> str:
    """The panel's environment text, asserted present."""
    label = dialog.panel.findChild(QLabel, "diagnostics-environment-text")
    assert label is not None
    return label.text()


def _wait_rendered(qtbot: QtBot, dialog: DirectTestDialog) -> None:
    """Wait until the main thread has rendered the worker's outcome.

    Rendering happens in the same queued-signal batch as the worker thread's
    quit, so the thread is on its way out when the summary changes — safe
    to tear the dialog down at test end. Waiting on ``controller.busy``
    alone is not: it clears on the worker thread before the main loop
    dispatches the thread's quit.
    """
    qtbot.waitUntil(lambda: _summary(dialog) != DEFAULT_SUMMARY, timeout=5000)


class TestDirectTestDialog:
    def test_dialog_hosts_panel_and_close_rejects(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """The dialog titles itself, hosts the shared panel, and Close rejects."""
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        dialog = DirectTestDialog(controller, make_job())
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Test 'Daily Backup'"
        assert dialog.panel is not None
        close = dialog.findChild(QPushButton, "direct-test-close")
        assert close is not None
        close.click()
        assert dialog.result() == 0
        _wait_rendered(qtbot, dialog)

    def test_accepted_run_renders_direct_and_persisted(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """A worker-thread run renders the summary, outputs, and logs."""
        out = tmp_path / "out.log"
        out.write_text("persisted\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world = FakeTaskWorld(
            tmp_path, test=ProcessResult(exit_code=0, stdout="direct out")
        )
        controller = DiagnosticsController(world.services, {})
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        _wait_rendered(qtbot, dialog)
        assert _summary(dialog) == "Passed (exit code 0) in 0.00s"
        assert _tab(dialog, "diagnostics-direct-stdout") == "direct out"
        assert _tab(dialog, "diagnostics-persisted-stdout") == "persisted\n"
        assert "GUI process only: none" in _tab_env(dialog)

    def test_failed_run_renders_failure(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """A non-zero exit renders the failure summary and stderr."""
        job = make_job()
        world = FakeTaskWorld(
            tmp_path, test=ProcessResult(exit_code=2, stderr="boom")
        )
        controller = DiagnosticsController(world.services, {})
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        _wait_rendered(qtbot, dialog)
        assert _summary(dialog) == "Failed (exit code 2) in 0.00s"
        assert _tab(dialog, "diagnostics-direct-stderr") == "boom"

    def test_service_error_renders_error_summary(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A test-service exception renders the error summary line."""
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        controller = DiagnosticsController(world.services, {})

        def boom(target: JobDefinition, *, detection: object = None) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(world.services, "test_job", boom)
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        _wait_rendered(qtbot, dialog)
        assert _summary(dialog) == "Test could not run: boom"

    def test_busy_request_shows_notice(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """A refused busy request shows the notice and starts no worker."""
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        controller = DiagnosticsController(world.services, {})
        assert controller.request_test(job) is RequestVerdict.ACCEPTED
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        assert _summary(dialog) == "Cannot test: busy."
        assert controller.busy
        assert dialog._worker is None

    def test_invalid_job_request_shows_notice(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refused invalid-job request shows the notice and starts no worker."""
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})

        def bad_validate(job: JobDefinition) -> None:
            raise ValueError("bad")

        monkeypatch.setattr(world.services, "validate_job", bad_validate)
        dialog = DirectTestDialog(controller, make_job())
        qtbot.addWidget(dialog)
        assert _summary(dialog) == "Cannot test: invalid job."
        assert not controller.busy
        assert dialog._worker is None

    def test_refresh_rereads_logs_after_change(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Refresh re-reads the persisted logs and environment comparison."""
        out = tmp_path / "out.log"
        out.write_text("first\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world = FakeTaskWorld(
            tmp_path, test=ProcessResult(exit_code=0, stdout="direct out")
        )
        controller = DiagnosticsController(world.services, {})
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        _wait_rendered(qtbot, dialog)
        assert _tab(dialog, "diagnostics-persisted-stdout") == "first\n"
        out.write_text("first\nsecond\n")
        dialog.panel.refresh_button.click()
        assert _tab(dialog, "diagnostics-persisted-stdout") == "first\nsecond\n"

    def test_closed_dialog_ignores_late_outcome(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An outcome delivered after closeEvent leaves the panel unchanged."""
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        controller = DiagnosticsController(world.services, {})
        release = threading.Event()

        def blocked(target: JobDefinition, *, detection: object = None) -> DirectTestResult:
            release.wait(timeout=5)
            return DirectTestResult(
                process=ProcessResult(exit_code=0, stdout="late")
            )

        monkeypatch.setattr(world.services, "test_job", blocked)
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        dialog.close()
        dialog._on_finished(TestOutcome(label=job.label, result=None, error="late"))
        assert _summary(dialog) == DEFAULT_SUMMARY
        release.set()
        qtbot.waitUntil(lambda: not controller.busy, timeout=5000)
        qtbot.wait(50)

    def test_non_outcome_payload_is_ignored(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """A payload that is not a TestOutcome changes nothing."""
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        dialog = DirectTestDialog(controller, make_job())
        qtbot.addWidget(dialog)
        dialog._on_finished("not an outcome")
        assert _summary(dialog) == DEFAULT_SUMMARY
        _wait_rendered(qtbot, dialog)
