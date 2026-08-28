"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import FIXED_JOB_ID, make_job

from task_scheduler.application import (
    JobConflictError,
    JobNotFoundError,
    JobService,
)

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def seed(root: Path, *jobs: object) -> None:
    service = JobService(root)
    for job in jobs:
        service.import_job(job)  # type: ignore[arg-type]


def test_list_jobs_missing_root_returns_empty(tmp_path: Path) -> None:
    assert JobService(tmp_path / "nope").list_jobs() == []


def test_list_jobs_empty_root_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "jobs").mkdir()
    assert JobService(tmp_path / "jobs").list_jobs() == []


def test_list_jobs_ignores_non_json_and_subdirectories(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    root.mkdir()
    (root / "notes.txt").write_text("not a job")
    (root / "nested").mkdir()
    (root / "nested" / f"{FIXED_JOB_ID}.json").write_text("{}")
    assert JobService(root).list_jobs() == []


def test_list_jobs_sorted_by_label(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    first = make_job(id=OTHER_ID, label="io.github.mactaskscheduler.user.b")
    second = make_job(label="io.github.mactaskscheduler.user.a")
    seed(root, first, second)
    jobs = JobService(root).list_jobs()
    assert [job.label for job in jobs] == [second.label, first.label]


def test_find_returns_job_or_none(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    job = make_job()
    seed(root, job)
    service = JobService(root)
    assert service.find(job.label) == job
    assert service.find("other.label") is None


def test_resolve_raises_for_unknown_label(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    seed(root, make_job())
    with pytest.raises(JobNotFoundError) as exc:
        JobService(root).resolve("missing.label")
    assert exc.value.label == "missing.label"


def test_import_job_creates_catalog_record(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    path = service.import_job(job)
    assert path == service.root / f"{FIXED_JOB_ID}.json"
    assert path.is_file()
    assert service.find(job.label) == job


def test_import_job_conflicts_on_existing_id(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    service = JobService(root)
    service.import_job(make_job())
    with pytest.raises(JobConflictError) as exc:
        service.import_job(make_job())
    assert exc.value.label == make_job().label
    assert exc.value.path == root / f"{FIXED_JOB_ID}.json"


def test_remove_is_idempotent(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    service.import_job(job)
    assert service.remove(job.id) is True
    assert service.remove(job.id) is False
    assert service.find(job.label) is None


def test_root_property_accepts_str_and_path(tmp_path: Path) -> None:
    assert JobService(str(tmp_path / "jobs")).root == tmp_path / "jobs"
