"""Worker-thread runner for accepted direct-test requests.

A :class:`DiagnosticsWorker` is a QObject that the main window moves onto a
QThread and invokes via queued connection; it runs the controller's accepted
direct test off the main thread and marshals the immutable
:class:`~task_scheduler.gui.controllers.diagnostics_controller.TestOutcome`
back through the ``finished`` signal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from task_scheduler.gui.controllers.diagnostics_controller import DiagnosticsController

__all__ = ["DiagnosticsWorker"]


class DiagnosticsWorker(QObject):
    """Runs one accepted direct test and emits its outcome."""

    finished = Signal(object)

    def __init__(
        self, controller: DiagnosticsController, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._controller = controller

    @Slot()
    def run(self) -> None:
        """Execute the accepted test, restore the busy state, emit the outcome."""
        try:
            outcome = self._controller.execute()
        finally:
            self._controller.finish()
        self.finished.emit(outcome)
