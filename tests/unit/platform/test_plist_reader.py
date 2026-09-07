"""Tests for the LaunchAgent plist reader."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from task_scheduler.platform.macos import ParsedLaunchAgent, ParseSupport, parse_bytes, parse_path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plists"

def _parse(name: str) -> ParsedLaunchAgent:
    return parse_path(FIXTURES / name)

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
_INTERVAL_BASE = {
    "Label": "com.example.interval",
    "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
    "StartInterval": 300,
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

class TestScheduleBranches:

    def test_interval_below_minimum_drops_job(self) -> None:
        payload = dict(_INTERVAL_BASE)
        payload["StartInterval"] = 30
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert parsed.job is None
        assert any("below the" in warning for warning in parsed.warnings)

    def test_calendar_and_interval_conflict_drops_job(self) -> None:
        payload = dict(_INTERVAL_BASE)
        payload["StartCalendarInterval"] = [{"Weekday": 1, "Hour": 7, "Minute": 30}]
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert parsed.job is None
        assert any("conflict" in warning for warning in parsed.warnings)

    def test_run_at_load_without_schedule_drops_job(self) -> None:
        payload = {
            "Label": "com.example.runatload-only",
            "ProgramArguments": ["/bin/zsh", "/Users/example/scripts/x.sh"],
            "RunAtLoad": True,
        }
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.PARTIALLY_SUPPORTED
        assert parsed.job is None
        assert any("RunAtLoad" in warning for warning in parsed.warnings)

    def test_non_integer_start_interval_is_invalid(self) -> None:
        payload = dict(_INTERVAL_BASE)
        payload["StartInterval"] = "300"
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.INVALID
        assert parsed.job is None

    def test_non_boolean_run_at_load_is_invalid(self) -> None:
        payload = dict(_BASE)
        payload["RunAtLoad"] = "yes"
        parsed = parse_bytes(plistlib.dumps(payload))
        assert parsed.status is ParseSupport.INVALID
        assert parsed.job is None
