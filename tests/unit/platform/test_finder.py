"""Unit tests for the Finder reveal adapter (Increment 22, spec §63).

Every invocation goes through the injected ProcessRunner; the tests assert the
exact ``/usr/bin/open -R`` argv (empty environment) and the success/failure
message mapping.
"""

from __future__ import annotations

from pathlib import Path

from fakes import FakeProcessRunner
from task_scheduler.platform.macos import (
    FINDER_OPEN_PATH,
    LaunchFailureKind,
    LocalFinderRevealer,
    ProcessLaunchFailure,
    ProcessResult,
)


def test_reveal_success_returns_none_and_uses_open_dash_r(tmp_path: Path) -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0))
    revealer = LocalFinderRevealer(runner)
    target = tmp_path / "target.txt"
    assert revealer.reveal(target) is None
    spec = runner.specs[0]
    assert spec.argv == [FINDER_OPEN_PATH, "-R", str(target)]
    assert spec.environment == {}


def test_reveal_nonzero_exit_reports_stderr(tmp_path: Path) -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=1, stderr="no such file"))
    message = LocalFinderRevealer(runner).reveal(tmp_path / "x")
    assert message == "Finder reveal failed (exit 1): no such file"


def test_reveal_nonzero_exit_without_stderr(tmp_path: Path) -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=1))
    message = LocalFinderRevealer(runner).reveal(tmp_path / "x")
    assert message == "Finder reveal failed (exit 1)"


def test_reveal_launch_failure_reports_reason(tmp_path: Path) -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(
            exit_code=None,
            launch_failure=ProcessLaunchFailure(
                kind=LaunchFailureKind.NOT_FOUND, message="open: not found"
            ),
        )
    )
    message = LocalFinderRevealer(runner).reveal(tmp_path / "x")
    assert message == "could not launch Finder reveal: open: not found"
