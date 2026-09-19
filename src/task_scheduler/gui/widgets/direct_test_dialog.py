"""Modal dialog hosting the diagnostics panel for a direct test of a job."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QMetaObject, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    TestOutcome,
)
from task_scheduler.gui.controllers.diagnostics_controller import (
    RequestVerdict as TestVerdict,
)
from task_scheduler.gui.controllers.diagnostics_worker import DiagnosticsWorker
from task_scheduler.gui.dialog_sizing import bounded_preferred_size
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel

__all__ = ["DirectTestDialog"]


class DirectTestDialog(QDialog):
    """Runs one direct test and renders it in the shared diagnostics panel.

    The dialog owns no controller state beyond the shared
    :class:`DiagnosticsController`; the test runs on a worker thread and the
    panel renders when the outcome arrives. Closing early is safe: a late
    outcome is dropped.
    """

    _closing_dialogs: ClassVar[list[DirectTestDialog]] = []
    _active_threads: ClassVar[set[QThread]] = set()

    def __init__(
        self,
        controller: DiagnosticsController,
        job: JobDefinition,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._job = job
        self._closing = False
        self._worker: DiagnosticsWorker | None = None
        self._thread: QThread | None = None
        self.setWindowTitle(f"Test '{job.name}'")
        self.panel = DiagnosticLogsPanel(self)
        self.panel.refresh_button.clicked.connect(self._on_refresh)
        close_button = QPushButton("Close", self)
        close_button.setObjectName("direct-test-close")
        close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)
        layout.addLayout(buttons)
        screen = QApplication.primaryScreen()
        available_size = screen.availableGeometry().size() if screen is not None else None
        self.resize(bounded_preferred_size(QSize(760, 560), available_size))
        self._start()

    def _start(self) -> None:
        """Request the test and dispatch a worker, or explain the refusal."""
        verdict = self._controller.request_test(self._job)
        if verdict is not TestVerdict.ACCEPTED:
            self.panel.show_notice(f"Cannot test: {verdict.value}.")
            return
        worker = DiagnosticsWorker(self._controller)
        self._worker = worker
        thread = QThread()
        self._thread = thread
        DirectTestDialog._active_threads.add(thread)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.destroyed.connect(self._on_thread_destroyed)
        thread.start()
        QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)

    def _on_finished(self, outcome: object) -> None:
        """Render the outcome and the synchronous log/environment reads."""
        if not isinstance(outcome, TestOutcome) or self._closing:
            return
        self.panel.show_test_outcome(self._job, outcome)
        self._render_logs()

    def _on_thread_destroyed(self) -> None:
        """Release the worker, drop the thread, then release a closed dialog after Qt deleted it."""
        self._worker = None
        if self._thread is not None:
            DirectTestDialog._active_threads.discard(self._thread)
            self._thread = None
        QTimer.singleShot(0, self._release_after_thread_deleted)

    def _release_after_thread_deleted(self) -> None:
        """Allow normal deletion after the deferred QThread deletion completes."""
        if self in self._closing_dialogs:
            self._closing_dialogs.remove(self)

    def _on_refresh(self) -> None:
        """Re-read the job's persisted logs and environment comparison."""
        self._render_logs()

    def _render_logs(self) -> None:
        """Fill the panel with synchronous log and environment reads."""
        self.panel.show_logs_outcome(self._controller.read_logs(self._job))
        self.panel.show_environment_outcome(self._controller.compare_environment(self._job))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Drop any outcome arriving after the dialog has closed."""
        self._closing = True
        if self._thread is not None and self not in self._closing_dialogs:
            self._closing_dialogs.append(self)
        super().closeEvent(event)
