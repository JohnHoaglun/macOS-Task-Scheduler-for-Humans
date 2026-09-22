"""Unit tests for execution-history recording in TaskCommandService (Lane 1B)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application.history_models import HISTORY_UNAVAILABLE, HistoryReadResult
from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    SubprocessRunner,
)


def test_history_no_repo_returns_unavailable(tmp_path: Path) -> None:
    from task_scheduler.application.job_service import JobService
    from task_scheduler.application.log_service import LogService
    from task_scheduler.application.test_service import DirectTestService
    from task_scheduler.storage import JsonJobRepository

    store = LaunchAgentStore(tmp_path / "la")
    jobs = JobService(tmp_path / "catalog")
    job = make_job()
    jobs.import_job(job)
    service = TaskCommandService(
        repository=JsonJobRepository(),
        jobs=jobs,
        store=store,
        backend=LaunchAgentBackend(store, SubprocessRunner()),
        codec=PlistCodec(),
        test=DirectTestService(SubprocessRunner()),
        logs=LogService(),
    )
    result = service.history(job.label)
    assert result == HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)
    # verify that test/run/status work without errors when history is None
    # (this also exercises the early-return path in _record_event)
    service.test(job.label)
