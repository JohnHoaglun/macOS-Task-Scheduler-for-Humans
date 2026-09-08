"""Tests for the import controller (Qt-free)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
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


def _preview(
    candidate: JobDefinition,
    *,
    src: Path = Path("/tmp/x.plist"),
    warnings: tuple[str, ...] = (),
    unsupported_keys: tuple[str, ...] = (),
    requires: bool = False,
) -> ExternalPlistImportPreview:
    return ExternalPlistImportPreview(
        source_path=src,
        candidate=candidate,
        warnings=warnings,
        unsupported_keys=unsupported_keys,
        requires_acknowledgement=requires,
    )


def _outcome(preview: ExternalPlistImportPreview, **overrides: object) -> ImportOutcome:
    base: dict[str, object] = {
        "source_path": preview.source_path,
        "candidate": preview.candidate,
        "warnings": preview.warnings,
        "unsupported_keys": preview.unsupported_keys,
        "requires_acknowledgement": preview.requires_acknowledgement,
        "error": None,
        "_preview": preview,
    }
    base.update(overrides)
    return ImportOutcome(**base)  # type: ignore[arg-type]


class TestPreviewSuccess:
    def test_carry_candidate_and_metadata(self) -> None:
        preview = _preview(
            make_job(label="com.example.job", name="Test Job"),
            src=Path("/tmp/external.plist"),
            warnings=("key X is ignored",),
            unsupported_keys=("Label",),
        )
        ctrl = ImportController(FakeImportService(preview_result=preview))
        outcome = ctrl.preview(Path("/tmp/external.plist"))
        assert outcome.error is None and outcome.candidate.label == "com.example.job"
        assert (outcome.warnings, outcome.unsupported_keys) == (("key X is ignored",), ("Label",))
        assert outcome.requires_acknowledgement is False

    def test_requires_acknowledgement_when_partially_supported(self) -> None:
        preview = _preview(make_job(label="com.example.partial"), requires=True)
        ctrl = ImportController(FakeImportService(preview_result=preview))
        assert ctrl.preview(Path("/tmp/partial.plist")).requires_acknowledgement is True


class TestPreviewInvalid:
    def test_invalid_plist_yields_error_no_candidate(self) -> None:
        svc = FakeImportService(preview_error=ValueError("not a valid plist"))
        outcome = ImportController(svc).preview(Path("/tmp/bad.plist"))
        assert outcome.error == "not a valid plist" and outcome.candidate is None
        assert (outcome.warnings, outcome.unsupported_keys) == ((), ())


class TestCommitSuccess:
    def test_supported_preview_returns_job(self) -> None:
        preview = _preview(make_job(label="com.example.job"))
        committed = make_job(label="com.example.job", id=uuid4())
        svc = FakeImportService(preview_result=preview, import_result=committed)
        result = ImportController(svc).commit(_outcome(preview))
        assert result.error is None and result.job.label == "com.example.job"

    @pytest.mark.parametrize("acknowledge", [False, True])
    def test_partial_acknowledgement(self, acknowledge: bool) -> None:
        preview = _preview(make_job(label="com.example.partial"), requires=True)
        svc = FakeImportService(preview_result=preview)
        result = ImportController(svc).commit(_outcome(preview), acknowledge_partial=acknowledge)
        if acknowledge:
            assert result.error is None and result.job is not None
        else:
            assert result.job is None and "partially supported" in result.error

    def test_job_conflict_returns_error(self) -> None:
        preview = _preview(make_job(label="com.example.conflict"))
        svc = FakeImportService(
            preview_result=preview,
            import_error=JobConflictError("com.example.conflict", Path("/tmp/c.plist")),
        )
        result = ImportController(svc).commit(_outcome(preview))
        assert result.job is None and "com.example.conflict" in result.error

    def test_commit_without_preview_returns_error(self) -> None:
        outcome = ImportOutcome(
            source_path=Path("/tmp/x.plist"), candidate=None, error="preview failed"
        )
        result = ImportController(FakeImportService()).commit(outcome)
        assert result.job is None and result.error == "no preview available to commit"
