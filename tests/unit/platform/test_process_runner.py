"""Tests for SubprocessRunner (controlled host tools only, no launchctl)."""

from __future__ import annotations

import sys
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


class TestTimeouts:
    def test_deadline_kills_and_marks_result(self) -> None:
        result = SubprocessRunner().run(_spec(["/bin/sleep", "5"]), timeout=0.2)
        assert result.exit_code is None
        assert result.launch_failure is None
        assert result.timed_out is not None
        assert result.timed_out.deadline == 0.2

    def test_fast_process_ignores_late_deadline(self) -> None:
        result = SubprocessRunner().run(_spec(["/bin/echo", "ok"]), timeout=5)
        assert result.exit_code == 0
        assert result.timed_out is None

    def test_invalid_utf8_is_replaced_not_raised(self) -> None:
        code = "import sys; sys.stdout.buffer.write(b'ab\\xff\\xfe')"
        result = SubprocessRunner().run(_spec([sys.executable, "-c", code]))
        assert result.exit_code == 0
        assert result.stdout == "ab\ufffd\ufffd"

    def test_timeout_partial_output_decoder(self) -> None:
        decode = SubprocessRunner._decode
        assert decode(b"ab\xff") == "ab\ufffd"
        assert decode("text") == "text"
        assert decode(None) == ""


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
