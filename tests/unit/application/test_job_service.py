"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from tests.conftest import make_job

from task_scheduler.application import (
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
