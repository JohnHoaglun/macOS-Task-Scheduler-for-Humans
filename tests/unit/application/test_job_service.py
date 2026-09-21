"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import UUID

from tests.conftest import make_job

from task_scheduler.application import (
    JobConflictError,
    JobService,
)

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
