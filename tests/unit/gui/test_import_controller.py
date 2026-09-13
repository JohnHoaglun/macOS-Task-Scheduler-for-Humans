"""Tests for the import controller (Qt-free)."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.application import ExternalPlistImportPreview
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.import_controller import (
    ImportController,
    ImportOutcome,
)


class FakeImportService:
    """Duck-typed TaskCommandService for import controller tests."""

    def __init__(
        self,
        preview_result: ExternalPlistImportPreview | None = None,
        preview_error: Exception | None = None,
        import_result: JobDefinition | None = None,
        import_error: Exception | None = None,
    ) -> None:
        self.preview_result = preview_result
        self.preview_error = preview_error
        self.import_result = import_result
        self.import_error = import_error

    def preview_external_plist(self, path: Path) -> ExternalPlistImportPreview:
        if self.preview_error is not None:
            raise self.preview_error
        assert self.preview_result is not None
        return self.preview_result

    def import_external_plist(
        self, preview: ExternalPlistImportPreview, *, acknowledge_partial: bool = False
    ) -> JobDefinition:
        if self.import_error is not None:
            raise self.import_error
        if preview.requires_acknowledgement and not acknowledge_partial:
            raise ValueError("partially supported; must acknowledge")
        if self.import_result is not None:
            return self.import_result
        return preview.candidate


class TestCommitSuccess:
    def test_commit_without_preview_returns_error(self) -> None:
        outcome = ImportOutcome(
            source_path=Path("/tmp/x.plist"), candidate=None, error="preview failed"
        )
        result = ImportController(FakeImportService()).commit(outcome)
        assert result.job is None and result.error == "no preview available to commit"
