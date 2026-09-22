"""Tests for the import controller (Qt-free)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application import ExternalPlistImportPreview
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.import_controller import ImportController, ImportOutcome


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


def test_commit_os_error_returns_error() -> None:
    candidate = make_job()
    preview = ExternalPlistImportPreview(
        source_path=Path("/tmp/x.plist"),
        candidate=candidate,
        warnings=(),
        unsupported_keys=(),
        requires_acknowledgement=False,
    )
    outcome = ImportOutcome(source_path=Path("/tmp/x.plist"), candidate=candidate, _preview=preview)
    service = FakeImportService(import_error=OSError("catalog unavailable"))
    result = ImportController(service).commit(outcome)
    assert result.job is None
    assert result.error == "catalog unavailable"
