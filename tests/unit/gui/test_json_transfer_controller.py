"""Tests for the json transfer controller (Qt-free)."""

from pathlib import Path
from uuid import uuid4

import pytest

from conftest import make_job
from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    ManagedJsonImportPreview,
    StrictJsonDecodeError,
)
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.json_transfer_controller import (
    JsonImportOutcome,
    JsonTransferController,
)


class FakeSvc:
    """Duck-typed TaskCommandService for json transfer controller tests."""

    def __init__(
        self,
        preview_result: ManagedJsonImportPreview | None = None,
        preview_error: Exception | None = None,
        import_result: JobDefinition | None = None,
        import_error: Exception | None = None,
    ) -> None:
        self.preview_result = preview_result
        self.preview_error = preview_error
        self.import_result = import_result
        self.import_error = import_error

    def preview_managed_json_import(self, path: Path) -> ManagedJsonImportPreview:
        if self.preview_error is not None:
            raise self.preview_error
        assert self.preview_result is not None
        return self.preview_result

    def import_managed_json(self, preview: ManagedJsonImportPreview) -> JobDefinition:
        if self.import_error is not None:
            raise self.import_error
        if self.import_result is not None:
            return self.import_result
        return preview.candidate


def _ctrl(
    preview: ManagedJsonImportPreview | None = None,
    error: Exception | None = None,
    result: JobDefinition | None = None,
    commit_error: Exception | None = None,
) -> JsonTransferController:
    return JsonTransferController(FakeSvc(
        preview_result=preview, preview_error=error,
        import_result=result, import_error=commit_error,
    ))


class TestPreview:
    def test_success(self) -> None:
        job = make_job(label="com.example.transfer")
        p = ManagedJsonImportPreview(
            source_path=Path("/tmp/t.json"), candidate=job,
            normalized_schema_version=2, id_conflict_path=None,
            label_conflict_path=None, can_import=True,
        )
        outcome = _ctrl(preview=p).preview_import(Path("/tmp/t.json"))
        assert outcome.error is None and outcome.candidate is p.candidate
        assert outcome.label == "com.example.transfer" and outcome.uuid == str(job.id)
        assert outcome.normalized_schema_version == 2
        assert outcome.can_import and outcome._preview is p

    def test_conflict(self) -> None:
        p = ManagedJsonImportPreview(
            source_path=Path("/tmp/t.json"),
            candidate=make_job(label="com.example.conflict"),
            normalized_schema_version=2, id_conflict_path=Path("/tmp/x.json"),
            label_conflict_path=None, can_import=False,
        )
        outcome = _ctrl(preview=p).preview_import(Path("/tmp/t.json"))
        assert not outcome.can_import and outcome.id_conflict_path == Path("/tmp/x.json")

    @pytest.mark.parametrize(
        "exc_cls, msg",
        [
            (StrictJsonDecodeError, "malformed JSON"),
            (JobNotFoundError, "com.example.job"),
            (ValueError, "unexpected"),
        ],
    )
    def test_error(self, exc_cls: type[Exception], msg: str) -> None:
        outcome = _ctrl(error=exc_cls(msg)).preview_import(Path("/tmp/bad.json"))
        assert msg in outcome.error and outcome.candidate is None

class TestCommit:
    def test_success(self) -> None:
        job = make_job(label="com.example.transfer")
        p = ManagedJsonImportPreview(
            source_path=Path("/tmp/t.json"), candidate=job,
            normalized_schema_version=2, id_conflict_path=None,
            label_conflict_path=None, can_import=True,
        )
        committed = make_job(label="com.example.transfer", id=uuid4())
        outcome = _ctrl(preview=p).preview_import(Path("/tmp/t.json"))
        result = _ctrl(preview=p, result=committed).commit(outcome)
        assert result.error is None and result.job is committed
    def test_no_preview(self) -> None:
        result = _ctrl().commit(JsonImportOutcome(source_path=Path("/tmp/x.json")))
        assert result.error == "no preview available to commit"
    def test_job_conflict(self) -> None:
        job = make_job(label="com.example.conflict")
        p = ManagedJsonImportPreview(
            source_path=Path("/tmp/t.json"), candidate=job,
            normalized_schema_version=2, id_conflict_path=None,
            label_conflict_path=None, can_import=True,
        )
        outcome = _ctrl(preview=p).preview_import(Path("/tmp/t.json"))
        result = _ctrl(
            preview=p,
            commit_error=JobConflictError(
                "com.example.conflict", Path("/tmp/catalog.json"),
            ),
        ).commit(outcome)
        assert result.job is None and "com.example.conflict" in result.error
    def test_generic_error(self) -> None:
        p = ManagedJsonImportPreview(
            source_path=Path("/tmp/t.json"),
            candidate=make_job(), normalized_schema_version=2,
            id_conflict_path=None, label_conflict_path=None, can_import=True,
        )
        outcome = _ctrl(preview=p).preview_import(Path("/tmp/t.json"))
        result = _ctrl(preview=p, commit_error=ValueError("broke")).commit(outcome)
        assert result.job is None and result.error == "broke"
