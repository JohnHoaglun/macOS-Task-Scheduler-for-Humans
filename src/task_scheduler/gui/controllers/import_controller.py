"""Import controller bridging the import flow to TaskCommandService.

Qt-free: all validation, error handling lives here so it can be tested
without an event loop. Mirrors the synchronous pattern of HistoryController
— no worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_scheduler.application import (
    ExternalPlistImportPreview,
    JobConflictError,
    TaskCommandService,
)
from task_scheduler.domain import JobDefinition

__all__ = ["ImportController", "ImportCommitOutcome", "ImportOutcome"]


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """Immutable result of previewing an external plist for import."""

    source_path: Path
    candidate: JobDefinition | None = None
    warnings: tuple[str, ...] = ()
    unsupported_keys: tuple[str, ...] = ()
    requires_acknowledgement: bool = False
    error: str | None = None
    _preview: ExternalPlistImportPreview | None = None


@dataclass(frozen=True, slots=True)
class ImportCommitOutcome:
    """Immutable result of committing an imported external plist."""

    job: JobDefinition | None = None
    error: str | None = None


class ImportController:
    """Preview and commit external-plist import into the managed catalog."""

    def __init__(self, services: TaskCommandService) -> None:
        self._services = services

    def preview(self, path: Path) -> ImportOutcome:
        """Return a preview of importing *path*, or an error description."""
        try:
            preview = self._services.preview_external_plist(path)
        except ValueError as exc:
            return ImportOutcome(
                source_path=path,
                error=str(exc),
            )
        return ImportOutcome(
            source_path=preview.source_path,
            candidate=preview.candidate,
            warnings=preview.warnings,
            unsupported_keys=preview.unsupported_keys,
            requires_acknowledgement=preview.requires_acknowledgement,
            error=None,
            _preview=preview,
        )

    def commit(
        self,
        outcome: ImportOutcome,
        *,
        acknowledge_partial: bool = False,
    ) -> ImportCommitOutcome:
        """Commit the previewed import. Returns error on failure (never raises)."""
        try:
            preview = outcome._preview
            if preview is None:
                return ImportCommitOutcome(
                    job=None,
                    error="no preview available to commit",
                )
            job = self._services.import_external_plist(
                preview,
                acknowledge_partial=acknowledge_partial,
            )
            return ImportCommitOutcome(job=job, error=None)
        except (ValueError, JobConflictError) as exc:
            return ImportCommitOutcome(job=None, error=str(exc))
