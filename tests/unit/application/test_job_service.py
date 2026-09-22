"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import make_job

from task_scheduler.application import JobConflictError, JobService
from task_scheduler.domain import JobDefinition

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")


def test_remove_is_idempotent(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    service.import_job(job)
    assert service.remove(job.id) is True
    assert service.remove(job.id) is False
    assert service.find(job.label) is None


def test_concurrent_imports_exactly_one_wins(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    successes = 0
    conflicts = 0
    lock = threading.Lock()

    def attempt() -> None:
        nonlocal successes, conflicts
        try:
            service.import_job(job)
        except JobConflictError:
            with lock:
                conflicts += 1
        else:
            with lock:
                successes += 1

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert (successes, conflicts) == (1, 3)
    assert len(service.list_jobs()) == 1


def test_corrupt_catalog_file_is_skipped_with_diagnostic(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    service.import_job(job)
    corrupt = tmp_path / "jobs" / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    assert service.list_jobs() == [job]
    diagnostics = service.catalog_diagnostics()
    assert len(diagnostics) == 1
    assert diagnostics[0].path == corrupt
    assert diagnostics[0].message


def test_clean_catalog_has_no_diagnostics(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    service.import_job(make_job())
    assert service.list_jobs()
    assert service.catalog_diagnostics() == []
    assert JobService(tmp_path / "missing").catalog_diagnostics() == []


def test_unreadable_catalog_file_is_skipped_with_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    other = make_job(id=OTHER_ID, label="io.github.macos-task-scheduler.user.other")
    service.import_job(job)
    service.import_job(other)
    target = service._path_for(other.id)
    original = service._repository.load

    def failing_load(path: Path) -> JobDefinition:
        if path == target:
            raise OSError("simulated read failure")
        return original(path)

    monkeypatch.setattr(service._repository, "load", failing_load)
    assert service.list_jobs() == [job]
    diagnostics = service.catalog_diagnostics()
    assert len(diagnostics) == 1
    assert diagnostics[0].path == target
    assert "OSError" in diagnostics[0].message


def test_save_conflicting_label_raises(tmp_path: Path) -> None:
    service = JobService(tmp_path / "jobs")
    job = make_job()
    service.save(job)
    with pytest.raises(JobConflictError):
        service.save(make_job(id=OTHER_ID))
    assert service.list_jobs() == [job]
