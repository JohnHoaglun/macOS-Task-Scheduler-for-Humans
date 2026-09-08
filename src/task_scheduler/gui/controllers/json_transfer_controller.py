"""JsonTransferController: preview and commit managed-JSON import.

Qt-free: all validation, error handling lives here so it can be tested
without an event loop. Mirrors the synchronous pattern of ImportController
-- no worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    ManagedJsonImportPreview,
    StrictJsonDecodeError,
    TaskCommandService,
)
from task_scheduler.domain import JobDefinition

__all__ = [
    "JsonImportCommitOutcome",
    "JsonImportOutcome",
    "JsonTransferController",
]


@dataclass(frozen=True, slots=True)
class JsonImportOutcome:
    """Immutable result of previewing a managed JSON file for import."""

    source_path: Path
    candidate: JobDefinition | None = None
    label: str | None = None
    uuid: str | None = None
    normalized_schema_version: int | None = None
    id_conflict_path: Path | None = None
    label_conflict_path: Path | None = None
    can_import: bool = False
    error: str | None = None
    _preview: ManagedJsonImportPreview | None = None


@dataclass(frozen=True, slots=True)
class JsonImportCommitOutcome:
    """Immutable result of committing a managed-JSON import."""

    job: JobDefinition | None = None
    error: str | None = None


class JsonTransferController:
    """Preview and commit managed-JSON import into the catalog."""

    def __init__(self, service: TaskCommandService) -> None:
        self._service = service

    def preview_import(self, path: Path) -> JsonImportOutcome:
        """Return a preview of importing *path*, or an error description."""
        try:
            preview = self._service.preview_managed_json_import(path)
        except StrictJsonDecodeError as exc:
            return JsonImportOutcome(source_path=path, error=str(exc))
        except JobNotFoundError as exc:
            return JsonImportOutcome(source_path=path, error=str(exc))
        except Exception as exc:
            return JsonImportOutcome(source_path=path, error=str(exc))
        return JsonImportOutcome(
            source_path=preview.source_path,
            candidate=preview.candidate,
            label=preview.candidate.label if preview.candidate is not None else None,
            uuid=str(preview.candidate.id) if preview.candidate is not None else None,
            normalized_schema_version=preview.normalized_schema_version,
            id_conflict_path=preview.id_conflict_path,
            label_conflict_path=preview.label_conflict_path,
            can_import=preview.can_import,
            error=None,
            _preview=preview,
        )

    def commit(self, outcome: JsonImportOutcome) -> JsonImportCommitOutcome:
        """Commit the previewed import. Returns error on failure (never raises)."""
        try:
            preview = outcome._preview
            if preview is None or outcome.error is not None:
                return JsonImportCommitOutcome(
                    job=None,
                    error="no preview available to commit",
                )
            job = self._service.import_managed_json(preview)
            return JsonImportCommitOutcome(job=job, error=None)
        except JobConflictError as exc:
            return JsonImportCommitOutcome(job=None, error=str(exc))
        except Exception as exc:
            return JsonImportCommitOutcome(job=None, error=str(exc))
