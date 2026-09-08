"""Tests for the import controller (Qt-free)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from tests.conftest import make_job

from task_scheduler.application import ExternalPlistImportPreview, JobConflictError
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
        self.last_preview: ExternalPlistImportPreview | None = None

    def preview_external_plist(self, path: Path) -> ExternalPlistImportPreview:
        if self.preview_error is not None:
            raise self.preview_error
        assert self.preview_result is not None
        self.last_preview = self.preview_result
        return self.preview_result

    def import_external_plist(
        self, preview: ExternalPlistImportPreview, *, acknowledge_partial: bool = False
    ) -> JobDefinition:
        if self.import_error is not None:
            raise self.import_error
        if (
            preview.requires_acknowledgement
            and not acknowledge_partial
        ):
            raise ValueError("partially supported; must acknowledge")
        if self.import_result is not None:
            return self.import_result
        return preview.candidate


class TestPreviewSuccess:
    def test_carry_candidate_and_metadata(self):
        job = make_job(label="com.example.job", name="Test Job")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/external.plist"),
            candidate=job,
            warnings=("key X is ignored",),
            unsupported_keys=("Label",),
            requires_acknowledgement=False,
        )
        svc = FakeImportService(preview_result=preview)
        ctrl = ImportController(svc)
        outcome = ctrl.preview(Path("/tmp/external.plist"))
        assert outcome.error is None
        assert outcome.source_path == Path("/tmp/external.plist")
        assert outcome.candidate is not None
        assert outcome.candidate.label == "com.example.job"
        assert outcome.warnings == ("key X is ignored",)
        assert outcome.unsupported_keys == ("Label",)
        assert outcome.requires_acknowledgement is False

    def test_requires_acknowledgement_when_partially_supported(self):
        job = make_job(label="com.example.partial")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/partial.plist"),
            candidate=job,
            warnings=("key Y unknown",),
            unsupported_keys=("Label", "StartInterval"),
            requires_acknowledgement=True,
        )
        svc = FakeImportService(preview_result=preview)
        ctrl = ImportController(svc)
        outcome = ctrl.preview(Path("/tmp/partial.plist"))
        assert outcome.requires_acknowledgement is True


class TestPreviewInvalid:
    def test_invalid_plist_yields_error_no_candidate(self):
        svc = FakeImportService(preview_error=ValueError("not a valid plist"))
        ctrl = ImportController(svc)
        outcome = ctrl.preview(Path("/tmp/bad.plist"))
        assert outcome.error == "not a valid plist"
        assert outcome.candidate is None
        assert outcome.warnings == ()
        assert outcome.unsupported_keys == ()


class TestCommitSuccess:
    def test_supported_preview_returns_job(self):
        job = make_job(label="com.example.job")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/x.plist"),
            candidate=job,
            warnings=(),
            unsupported_keys=(),
            requires_acknowledgement=False,
        )
        committed = make_job(label="com.example.job", id=uuid4())
        svc = FakeImportService(preview_result=preview, import_result=committed)
        ctrl = ImportController(svc)
        outcome = ImportOutcome(
            source_path=Path("/tmp/x.plist"),
            candidate=preview.candidate,
            warnings=(),
            unsupported_keys=(),
            requires_acknowledgement=False,
            error=None,
            _preview=preview,
        )
        result = ctrl.commit(outcome)
        assert result.error is None
        assert result.job is not None
        assert result.job.label == "com.example.job"

    def test_unacknowledged_partial_raises_value_error(self):
        job = make_job(label="com.example.partial")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/p.plist"),
            candidate=job,
            warnings=("partial",),
            unsupported_keys=("Label",),
            requires_acknowledgement=True,
        )
        svc = FakeImportService(preview_result=preview)
        ctrl = ImportController(svc)
        outcome = ImportOutcome(
            source_path=Path("/tmp/p.plist"),
            candidate=preview.candidate,
            warnings=preview.warnings,
            unsupported_keys=preview.unsupported_keys,
            requires_acknowledgement=True,
            error=None,
            _preview=preview,
        )
        result = ctrl.commit(outcome, acknowledge_partial=False)
        assert result.job is None
        assert "partially supported" in result.error

    def test_acknowledge_on_partial_returns_job(self):
        job = make_job(label="com.example.partial")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/p.plist"),
            candidate=job,
            warnings=("partial",),
            unsupported_keys=("Label",),
            requires_acknowledgement=True,
        )
        svc = FakeImportService(preview_result=preview)
        ctrl = ImportController(svc)
        outcome = ImportOutcome(
            source_path=Path("/tmp/p.plist"),
            candidate=preview.candidate,
            warnings=preview.warnings,
            unsupported_keys=preview.unsupported_keys,
            requires_acknowledgement=True,
            error=None,
            _preview=preview,
        )
        result = ctrl.commit(outcome, acknowledge_partial=True)
        assert result.error is None
        assert result.job is not None

    def test_job_conflict_returns_error(self):
        job = make_job(label="com.example.conflict")
        preview = ExternalPlistImportPreview(
            source_path=Path("/tmp/c.plist"),
            candidate=job,
            warnings=(),
            unsupported_keys=(),
            requires_acknowledgement=False,
        )
        svc = FakeImportService(
            preview_result=preview,
            import_error=JobConflictError("com.example.conflict", Path("/tmp/c.plist")),
        )
        ctrl = ImportController(svc)
        outcome = ImportOutcome(
            source_path=Path("/tmp/c.plist"),
            candidate=preview.candidate,
            error=None,
            _preview=preview,
        )
        result = ctrl.commit(outcome)
        assert result.job is None
        assert "com.example.conflict" in result.error

    def test_commit_without_preview_returns_error(self):
        ctrl = ImportController(FakeImportService())
        outcome = ImportOutcome(
            source_path=Path("/tmp/x.plist"),
            candidate=None,
            error="preview failed",
        )
        result = ctrl.commit(outcome)
        assert result.job is None
        assert result.error == "no preview available to commit"
