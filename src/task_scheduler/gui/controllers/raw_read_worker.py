"""Worker-thread runner for raw plist reads.

A :class:`RawReadWorker` is a QObject that the main window moves onto a
QThread and invokes via queued connection; it reads the external source
plist off the main thread and marshals the immutable
:class:`~task_scheduler.application.external_edit_models.RawPlistRead`
back through the ``finished`` signal. An unexpected failure is logged and
reported as a typed error read so the UI never sees a crash.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from task_scheduler.application.external_edit_models import RawPlistRead, read_raw_plist

__all__ = ["RAW_READ_FAILED_MESSAGE", "RawReadWorker"]

logger = logging.getLogger(__name__)

RAW_READ_FAILED_MESSAGE = "Could not read the plist file; see the application log."


class RawReadWorker(QObject):
    """Reads one raw plist off the UI thread and emits the result."""

    finished = Signal(object)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path

    @Slot()
    def run(self) -> None:
        """Read the plist and emit the result, logging unexpected failures."""
        try:
            result = read_raw_plist(self._path)
        except Exception:
            logger.exception("Raw plist read failed unexpectedly")
            result = RawPlistRead(None, False, RAW_READ_FAILED_MESSAGE)
        self.finished.emit(result)
