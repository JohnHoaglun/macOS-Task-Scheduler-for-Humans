"""Tests for SubprocessRunner (controlled host tools only, no launchctl)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fakes import FakeClock
from task_scheduler.platform.macos import (
    CommandSpec,
    LaunchFailureKind,
    SubprocessRunner,
)


def _spec(
    argv: list[str],
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> CommandSpec:
    return CommandSpec(argv=argv, environment=environment or {}, working_directory=cwd)

class TestSuccessfulRuns:

    def test_duration_from_injected_clock(self) -> None:
        runner = SubprocessRunner(clock=FakeClock(step=1.5))
        result = runner.run(_spec(["/bin/echo", "x"]))
        assert result.duration == timedelta(seconds=1.5)

class TestLaunchFailures:

    def test_permission_denied(self, tmp_path: Path) -> None:
        script = tmp_path / "noperm.sh"
        script.write_text("#!/bin/zsh\necho hi\n")
        script.chmod(0o644)
        result = SubprocessRunner().run(_spec([str(script)]))
        assert result.exit_code is None
        assert result.launch_failure is not None
        assert result.launch_failure.kind is LaunchFailureKind.PERMISSION_DENIED

    def test_os_error(self, tmp_path: Path) -> None:
        link_a = tmp_path / "loop_a"
        link_b = tmp_path / "loop_b"
        link_a.symlink_to(link_b)
        link_b.symlink_to(link_a)
        result = SubprocessRunner().run(_spec([str(link_a)]))
        assert result.exit_code is None
        assert result.launch_failure is not None
        assert result.launch_failure.kind is LaunchFailureKind.OS_ERROR

