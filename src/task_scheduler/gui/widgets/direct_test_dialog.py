"""Modal dialog hosting the diagnostics panel for a direct test of a job."""

from __future__ import annotations

from PySide6.QtCore import QMetaObject, Qt, QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
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
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel

__all__ = ["DirectTestDialog"]


class DirectTestDialog(QDialog):
    """Runs one direct test and renders it in the shared diagnostics panel.

    The dialog owns no controller state beyond the shared
    :class:`DiagnosticsController`; the test runs on a worker thread and the
    panel renders when the outcome arrives. Closing early is safe: a late
    outcome is dropped.
    """

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
        self._start()

    def _start(self) -> None:
        """Request the test and dispatch a worker, or explain the refusal."""
        verdict = self._controller.request_test(self._job)
        if verdict is not TestVerdict.ACCEPTED:
            self.panel.show_notice(f"Cannot test: {verdict.value}.")
            return
        worker = DiagnosticsWorker(self._controller)
        self._worker = worker
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)

    def _on_finished(self, outcome: object) -> None:
        """Render the outcome and the synchronous log/environment reads."""
        if not isinstance(outcome, TestOutcome) or self._closing:
            return
        self.panel.show_test_outcome(self._job, outcome)
        self._render_logs()

    def _on_refresh(self) -> None:
        """Re-read the job's persisted logs and environment comparison."""
        self._render_logs()

    def _render_logs(self) -> None:
        """Fill the panel with synchronous log and environment reads."""
        self.panel.show_logs_outcome(self._controller.read_logs(self._job))
        self.panel.show_environment_outcome(
            self._controller.compare_environment(self._job)
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Drop any outcome arriving after the dialog has closed."""
        self._closing = True
        super().closeEvent(event)
