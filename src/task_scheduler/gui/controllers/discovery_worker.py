"""Worker-thread runner for discovery refreshes.

A :class:`DiscoveryWorker` is a QObject that the main window moves onto a
QThread and invokes via queued connection; it runs the
:meth:`DiscoveryController.refresh` unit of work off the main thread and
marshals the immutable :class:`RefreshOutcome` back through the
``finished`` signal. An unexpected failure is logged and reported as a
typed error outcome so the UI never sees a crash.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from task_scheduler.gui.controllers.discovery_controller import (
    DiscoveryController,
    RefreshOutcome,
)

__all__ = ["DISCOVERY_FAILED_MESSAGE", "DiscoveryWorker"]

logger = logging.getLogger(__name__)

DISCOVERY_FAILED_MESSAGE = "Discovery failed unexpectedly; see the application log."


class DiscoveryWorker(QObject):
    """Runs one discovery refresh and emits its outcome."""

    finished = Signal(object)

    def __init__(self, controller: DiscoveryController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller

    @Slot()
    def run(self) -> None:
        """Refresh the agent listings and emit the outcome, logging failures."""
        try:
            outcome = self._controller.refresh()
        except Exception:
            logger.exception("Discovery refresh failed unexpectedly")
            outcome = RefreshOutcome(agents=None, error=DISCOVERY_FAILED_MESSAGE)
        self.finished.emit(outcome)
