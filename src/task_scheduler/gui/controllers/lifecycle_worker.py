"""Worker-thread runner for accepted lifecycle requests.

A :class:`LifecycleWorker` is a QObject that the main window moves onto a
QThread and invokes via queued connection; it runs the controller's accepted
request off the main thread and marshals the immutable
:class:`~task_scheduler.gui.controllers.lifecycle_controller.LifecycleOutcome`
back through the ``finished`` signal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from task_scheduler.gui.controllers.lifecycle_controller import LifecycleController

__all__ = ["LifecycleWorker"]


class LifecycleWorker(QObject):
    """Runs one accepted lifecycle request and emits its outcome."""

    finished = Signal(object)

    def __init__(self, controller: LifecycleController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller

    @Slot()
    def run(self) -> None:
        """Execute the accepted request, restore the busy state, emit the outcome."""
        try:
            outcome = self._controller.execute()
        finally:
            self._controller.finish()
        self.finished.emit(outcome)
