"""Worker-thread runner for universal external LaunchAgent controls.

An :class:`ExternalControlWorker` is a QObject that the main window moves onto a
QThread and invokes via queued connection; it dispatches by
:class:`ExternalControlKind` to the appropriate
:mod:`~task_scheduler.application.task_command_service` method and marshals the
result (or the raised exception) back through the ``finished`` signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from task_scheduler.application import ExternalEditSession
from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos.plist_models import ExternalEditField

__all__ = [
    "ExternalControlKind",
    "ExternalControlRequest",
    "ExternalControlWorker",
]


class ExternalControlKind(StrEnum):
    """The kind of external control operation."""

    STRUCTURED_EDIT = "structured_edit"
    RAW_EDIT = "raw_edit"
    DISABLE = "disable"
    ENABLE = "enable"
    RUN_NOW = "run_now"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class ExternalControlRequest:
    """Parameters for one external control operation.

    *kind* selects the service method.  *path* is the plist path for
    DISABLE / ENABLE / RUN_NOW / REMOVE.  *session* is the edit session
    for STRUCTURED_EDIT / RAW_EDIT.  *job* and *dirty* are for
    STRUCTURED_EDIT; *raw_text* is for RAW_EDIT.
    """

    kind: ExternalControlKind
    path: Path
    session: ExternalEditSession | None = None
    job: JobDefinition | None = None
    dirty: frozenset[ExternalEditField] = field(default_factory=frozenset)
    raw_text: str | None = None


class ExternalControlWorker(QObject):
    """Runs one external control op on a worker thread and emits the result."""

    finished = Signal(object)

    def __init__(
        self,
        services: TaskCommandService,
        request: ExternalControlRequest,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._request = request

    @Slot()
    def run(self) -> None:
        """Dispatch by kind and emit the result, or the caught exception."""
        try:
            kind = self._request.kind
            if kind is ExternalControlKind.STRUCTURED_EDIT:
                assert self._request.session is not None
                assert self._request.job is not None
                result = self._services.commit_structured_external_edit(
                    self._request.session,
                    self._request.job,
                    self._request.dirty,
                )
            elif kind is ExternalControlKind.RAW_EDIT:
                assert self._request.session is not None
                assert self._request.raw_text is not None
                result = self._services.commit_raw_external_edit(
                    self._request.session,
                    self._request.raw_text,
                )
            elif kind is ExternalControlKind.DISABLE:
                result = self._services.disable_external(self._request.path)
            elif kind is ExternalControlKind.ENABLE:
                result = self._services.enable_external(self._request.path)
            elif kind is ExternalControlKind.RUN_NOW:
                result = self._services.run_now_external(self._request.path)
            elif kind is ExternalControlKind.REMOVE:
                result = self._services.remove_external(self._request.path)
            else:
                raise ValueError(f"unknown control kind: {kind}")
            self.finished.emit(result)
        except Exception as exc:
            self.finished.emit(exc)
