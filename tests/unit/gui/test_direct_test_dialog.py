"""Tests for the DirectTestDialog (offscreen Qt)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, QThread
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit
from pytestqt.qtbot import QtBot
from tests.conftest import make_job
from tests.fakes import FakeTaskWorld

from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, LoggingConfig
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    TestOutcome,
)
from task_scheduler.gui.dialog_sizing import bounded_preferred_size
from task_scheduler.gui.widgets.direct_test_dialog import DirectTestDialog
from task_scheduler.platform.macos import ProcessResult

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

    def test_worker_registration_callback_receives_thread_and_worker(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        controller = DiagnosticsController(world.services, {})
        seen: list[tuple[QThread, object]] = []
        dialog = DirectTestDialog(
            controller,
            make_job(),
            on_worker_started=lambda thread, worker: seen.append((thread, worker)),
        )
        qtbot.addWidget(dialog)
        assert len(seen) == 1
        assert seen[0][0] is dialog._thread
        assert seen[0][1] is dialog._worker
        qtbot.waitUntil(lambda: not controller.busy, timeout=5000)
        dialog.close()
        qtbot.waitUntil(lambda: dialog not in DirectTestDialog._closing_dialogs, timeout=5000)

    def test_initial_size_is_bounded_to_the_primary_screen(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        dialog = DirectTestDialog(DiagnosticsController(world.services, {}), make_job())
        qtbot.addWidget(dialog)
        screen = QApplication.primaryScreen()
        available_size = screen.availableGeometry().size() if screen is not None else None
        assert dialog.size() == bounded_preferred_size(QSize(760, 560), available_size)
        dialog.close()
        qtbot.waitUntil(lambda: dialog not in DirectTestDialog._closing_dialogs)

    def test_refresh_rereads_logs_after_change(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Refresh re-reads the persisted logs and environment comparison."""
        out = tmp_path / "out.log"
        out.write_text("first\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=0, stdout="direct out"))
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
            return DirectTestResult(process=ProcessResult(exit_code=0, stdout="late"))

        monkeypatch.setattr(world.services, "test_job", blocked)
        dialog = DirectTestDialog(controller, job)
        qtbot.addWidget(dialog)
        assert dialog._thread is not None
        assert dialog._thread.parent() is None
        assert dialog._thread in DirectTestDialog._active_threads
        dialog.close()
        assert dialog in DirectTestDialog._closing_dialogs
        dialog._on_finished(TestOutcome(label=job.label, result=None, error="late"))
        assert _summary(dialog) == DEFAULT_SUMMARY
        release.set()
        qtbot.waitUntil(
            lambda: not controller.busy and dialog not in DirectTestDialog._closing_dialogs,
            timeout=5000,
        )
        assert dialog._worker is None
        assert dialog._thread is None
        assert DirectTestDialog._active_threads == set()
