"""Tests for the LaunchAgent plist reader."""

from __future__ import annotations

import plistlib
from datetime import time as Time
from pathlib import Path

import pytest

from task_scheduler.domain import ExecutableCommand, PythonCommand, ShellCommand, Weekday
from task_scheduler.platform.macos import ParsedLaunchAgent, ParseSupport, parse_bytes, parse_path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plists"


def _parse(name: str) -> ParsedLaunchAgent:
    return parse_path(FIXTURES / name)


class TestSupported:
    def test_python_supported(self) -> None:
        result = _parse("python_supported.plist")
        assert result.status is ParseSupport.SUPPORTED
        assert result.warnings == []
        assert result.unsupported_keys == []
        job = result.job
        assert job is not None
        assert isinstance(job.command, PythonCommand)
        assert job.command.interpreter == Path("/Users/example/.venv/bin/python")
        assert job.command.script == Path("/Users/example/report.py")
        assert job.command.arguments == []
        assert job.schedule.time == Time(7, 30)
        assert job.schedule.weekdays == {Weekday.MONDAY, Weekday.FRIDAY}
        assert job.working_directory == Path("/Users/example/project")
        assert job.enabled is True
        assert job.name == job.label == "com.example.python-supported"
        assert job.environment.variables == {}

    def test_shell_supported(self) -> None:
        result = _parse("shell_supported.plist")
        assert result.status is ParseSupport.SUPPORTED
        job = result.job
        assert job is not None
        assert isinstance(job.command, ShellCommand)
        assert job.command.executable == Path("/bin/zsh")
        assert job.command.arguments == ["/Users/example/scripts/backup.sh"]
        assert job.schedule.time == Time(9, 15)
        assert job.schedule.weekdays == {Weekday.TUESDAY}

    def test_executable_supported(self) -> None:
        result = _parse("executable_supported.plist")
        assert result.status is ParseSupport.SUPPORTED
        job = result.job
        assert job is not None
        assert isinstance(job.command, ExecutableCommand)
        assert job.command.executable == Path("/opt/homebrew/bin/sync-tool")
        assert job.command.arguments == ["--sync"]
        assert job.schedule.weekdays == {Weekday.SATURDAY}

    def test_with_environment(self) -> None:
        job = _parse("with_environment.plist").job
        assert job is not None
        assert job.environment.variables == {"FOO": "bar", "PATH": "/usr/bin"}

    def test_with_logs(self) -> None:
        job = _parse("with_logs.plist").job
        assert job is not None
        assert job.logging.stdout_path == Path("/Users/example/logs/out.log")
        assert job.logging.stderr_path == Path("/Users/example/logs/err.log")

    def test_disabled(self) -> None:
        result = _parse("disabled.plist")
        assert result.status is ParseSupport.SUPPORTED
        assert result.job is not None
        assert result.job.enabled is False


class TestPartiallySupported:
    def test_keepalive_keeps_job_and_reports_key(self) -> None:
        result = _parse("keepalive.plist")
        assert result.status is ParseSupport.PARTIALLY_SUPPORTED
        assert result.unsupported_keys == ["KeepAlive"]
        assert result.job is not None
        assert result.raw["Label"] == "com.example.keepalive"

    def test_runatload(self) -> None:
        result = _parse("runatload.plist")
        assert result.status is ParseSupport.PARTIALLY_SUPPORTED
        assert result.unsupported_keys == ["RunAtLoad"]
        assert result.job is not None

    def test_multiple_times_drops_job(self) -> None:
        result = _parse("multiple_times.plist")
        assert result.status is ParseSupport.PARTIALLY_SUPPORTED
        assert result.job is None
        assert any("distinct execution times" in warning for warning in result.warnings)

    def test_no_schedule_drops_job(self) -> None:
        result = _parse("no_schedule.plist")
        assert result.status is ParseSupport.PARTIALLY_SUPPORTED
        assert result.job is None
        assert any("no calendar schedule" in warning for warning in result.warnings)


class TestInvalid:
    @pytest.mark.parametrize(
        "name",
        ["malformed.plist", "missing_label.plist", "bad_program_arguments.plist"],
    )
    def test_invalid_fixtures(self, name: str) -> None:
        result = _parse(name)
        assert result.status is ParseSupport.INVALID
        assert result.job is None
        assert result.warnings

    def test_malformed_calendar_weekday(self) -> None:
        result = _parse("malformed_calendar.plist")
        assert result.status is ParseSupport.INVALID
        assert result.job is None
        assert any("Weekday" in warning for warning in result.warnings)

    def test_unreadable_path(self, tmp_path: Path) -> None:
        result = parse_path(tmp_path / "missing.plist")
        assert result.status is ParseSupport.INVALID
        assert result.job is None
        assert result.warnings


class TestParseBytes:
    def test_non_dictionary_top_level(self) -> None:
        parsed = parse_bytes(plistlib.dumps(["a", "b"]))
        assert parsed.status is ParseSupport.INVALID
        assert parsed.job is None

    def test_bad_working_directory_type_is_invalid(self) -> None:
        payload = {
            "Label": "com.example.bad-wd",
            "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            "WorkingDirectory": 42,
        }
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.INVALID

    def test_relative_working_directory_is_partial_without_job(self) -> None:
        payload = {
            "Label": "com.example.relative-wd",
            "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
            "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
            "WorkingDirectory": "relative/dir",
        }
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert parsed.job is None


_BASE = {
    "Label": "com.example.branch",
    "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
    "StartCalendarInterval": [{"Weekday": 1, "Hour": 7, "Minute": 30}],
}
_INVALID = ParseSupport.INVALID


def _entry(hour: object, minute: object) -> dict[str, object]:
    return {"Weekday": 1, "Hour": hour, "Minute": minute}


class TestBranches:
    @pytest.mark.parametrize(
        ("overrides", "status", "job"),
        [
            ({"ProgramArguments": ["/usr/bin/python", "relative.py"]}, None, None),
            ({"ProgramArguments": ["./relative-tool"]}, None, None),
            ({"StartCalendarInterval": {"Weekday": 1}}, _INVALID, None),
            ({"StartCalendarInterval": [_entry(24, 30)]}, _INVALID, None),
            ({"StartCalendarInterval": [_entry(7, 60)]}, _INVALID, None),
            ({"StartCalendarInterval": [_entry("7", 30)]}, _INVALID, None),
            ({"EnvironmentVariables": ["FOO"]}, _INVALID, None),
            ({"EnvironmentVariables": {"FOO": 1}}, _INVALID, None),
            ({"StandardOutPath": 42}, _INVALID, None),
            ({"Disabled": "yes"}, _INVALID, None),
            ({"Label": "com.example." + "a" * 130}, None, None),
        ],
    )
    def test_unrepresentable_or_malformed_branches(
        self,
        overrides: dict[str, object],
        status: ParseSupport | None,
        job: bool | None,
    ) -> None:
        payload: dict[str, object] = dict(_BASE)
        payload.update(overrides)
        parsed = parse_bytes(plistlib.dumps(payload))
        if status is not None:
            assert parsed.status is status
        else:
            assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        if job is not None:
            assert (parsed.job is not None) is job
        else:
            assert parsed.job is None
        assert parsed.warnings

    def test_relative_log_path_is_partial_without_job(self) -> None:
        payload = dict(_BASE)
        payload["StandardOutPath"] = "logs/out.log"
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert parsed.job is None
