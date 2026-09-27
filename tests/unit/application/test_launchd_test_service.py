"""Tests for the LaunchD test service (Mode B: kickstart + observe run log)."""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeClock, RunLogLaunchdBackend

from task_scheduler.application.launchd_test_service import (
    DEFAULT_LAUNCHD_TEST_TIMEOUT,
    LaunchdTestService,
)
from task_scheduler.platform.macos import RunLogWatcher


def _service(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    write_run_log: bool = True,
    kickstart_exit: int = 0,
    poll_interval: float = 0.1,
) -> LaunchdTestService:
    watcher = RunLogWatcher(job_logs_root=tmp_path / "run-logs")
    backend = RunLogLaunchdBackend(
        watcher,
        exit_code=exit_code,
        write_run_log=write_run_log,
        kickstart_exit=kickstart_exit,
    )
    return LaunchdTestService(backend, watcher, poll_interval=poll_interval)

def test_default_timeout_is_180() -> None:
    assert DEFAULT_LAUNCHD_TEST_TIMEOUT == 180.0

def test_run_passes_on_exit_zero(tmp_path: Path) -> None:
    result = _service(tmp_path, exit_code=0).run("demo", now=FakeClock(), sleep=lambda _s: None)
    assert result.passed and result.observed and not result.timed_out
    assert result.run is not None and result.run.exit_code == 0
    assert "exited 0" in result.reason

def test_run_fails_on_nonzero_exit(tmp_path: Path) -> None:
    result = _service(tmp_path, exit_code=3).run("demo", now=FakeClock(), sleep=lambda _s: None)
    assert not result.passed and result.observed and result.run is not None
    assert result.run.exit_code == 3 and "run failed" in result.reason

def test_run_rejected_when_kickstart_fails(tmp_path: Path) -> None:
    service = _service(tmp_path, kickstart_exit=1)
    result = service.run("demo", now=FakeClock(), sleep=lambda _s: None)
    assert not result.passed and not result.observed and result.run is None
    assert "kickstart rejected" in result.reason

def test_run_times_out_when_no_run_recorded(tmp_path: Path) -> None:
    service = _service(tmp_path, write_run_log=False, poll_interval=0.25)
    clock = FakeClock()
    result = service.run("demo", timeout=0.5, now=clock, sleep=clock.advance)
    assert not result.passed and result.timed_out and result.run is None
    assert "no run observed" in result.reason
