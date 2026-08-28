"""Unit tests for LogService (Increment 8)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import make_job

from task_scheduler.application import LogService
from task_scheduler.domain import LoggingConfig


def job_with_logs(root: Path):
    return make_job(
        logging=LoggingConfig(stdout_path=root / "out.log", stderr_path=root / "err.log")
    )


def test_unconfigured_streams_have_no_path_or_error() -> None:
    logs = LogService().read(make_job())
    assert logs.stdout.path is None
    assert logs.stdout.content is None
    assert logs.stdout.error is None
    assert logs.stderr.path is None
    assert logs.stderr.name == "stderr"


def test_configured_streams_are_read_in_full(tmp_path: Path) -> None:
    (tmp_path / "out.log").write_text("stdout data\n")
    (tmp_path / "err.log").write_text("stderr data\n")
    logs = LogService().read(job_with_logs(tmp_path))
    assert logs.stdout.path == tmp_path / "out.log"
    assert logs.stdout.content == "stdout data\n"
    assert logs.stdout.error is None
    assert logs.stderr.content == "stderr data\n"
    assert logs.stderr.error is None


def test_missing_and_unreadable_streams_report_errors(tmp_path: Path) -> None:
    (tmp_path / "out.log").write_text("stdout data\n")
    (tmp_path / "err.log").write_bytes(b"\xff\xfebinary")
    logs = LogService().read(job_with_logs(tmp_path))
    assert logs.stdout.content == "stdout data\n"
    assert logs.stderr.content is None
    assert logs.stderr.error is not None
    assert "err.log" in logs.stderr.error


def test_empty_file_yields_empty_content(tmp_path: Path) -> None:
    (tmp_path / "out.log").write_text("")
    (tmp_path / "err.log").write_text("")
    logs = LogService().read(job_with_logs(tmp_path))
    assert logs.stdout.content == ""
    assert logs.stderr.content == ""
    assert logs.stdout.error is None
    assert logs.stderr.error is None
