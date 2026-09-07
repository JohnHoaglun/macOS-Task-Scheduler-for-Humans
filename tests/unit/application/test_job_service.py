"""Unit tests for the managed job catalog (JobService, Increment 8)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import FIXED_JOB_ID, make_job

from task_scheduler.application import (
    JobConflictError,
    JobService,
)
from task_scheduler.domain import (
    CalendarSchedule,
    PythonCommand,
    Weekday,
)

OTHER_ID = UUID("87654321-4321-4321-4321-432143214321")

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

def _python_command(tmp_path: Path, script_name: str = "backup.py") -> PythonCommand:
    return PythonCommand(
        interpreter=tmp_path / "bin" / "python",
        script=tmp_path / "scripts" / script_name,
    )

def _schedule() -> CalendarSchedule:
    return CalendarSchedule(times=["07:30"], weekdays={Weekday.MONDAY})

