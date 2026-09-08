"""Unit tests for CLI render helpers not exercised by the CLI tests."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.cli import render
from task_scheduler.domain import CalendarSchedule, IntervalSchedule
from task_scheduler.platform.macos import LaunchAgentStatus, ProcessResult


def test_format_status_unknown() -> None:
    status = LaunchAgentStatus(loaded=None, process=ProcessResult(exit_code=None))
    assert render.format_status(status) == (
        "launchd status unknown (launchctl could not be queried)"
    )

def test_format_schedule_interval() -> None:
    assert render.format_schedule(IntervalSchedule(seconds=1800)) == "Every 30 minutes"

def test_format_schedule_run_at_load() -> None:
    schedule = CalendarSchedule(times=["07:30"], weekdays={"monday"}, run_at_load=True)
    assert render.format_schedule(schedule) == "07:30 on monday + at login"


def test_format_export_success() -> None:
    result = render.format_export_success("com.example.job", Path("/tmp/out.json"))
    assert result == "exported com.example.job -> /tmp/out.json"


def test_format_import_json_success() -> None:
    result = render.format_import_json_success("com.example.job", 2)
    assert result == "imported com.example.job (schema v2) (catalog only; no plist created)"


def test_format_import_json_conflicts_id_only() -> None:
    from tests.conftest import make_job

    from task_scheduler.application.managed_json_transfer import ManagedJsonImportPreview

    job = make_job()
    preview = ManagedJsonImportPreview(
        source_path=Path("/tmp/x.json"),
        candidate=job,
        normalized_schema_version=2,
        id_conflict_path=Path("/catalog/abc.json"),
        label_conflict_path=None,
        can_import=False,
    )
    result = render.format_import_json_conflicts(preview)
    lines = result.split("\n")
    assert lines[0] == "import refused (conflict):"
    assert "  id conflict: /catalog/abc.json" in result
    assert "label conflict" not in result


def test_format_import_json_conflicts_label_only() -> None:
    from tests.conftest import make_job

    from task_scheduler.application.managed_json_transfer import ManagedJsonImportPreview

    job = make_job()
    preview = ManagedJsonImportPreview(
        source_path=Path("/tmp/x.json"),
        candidate=job,
        normalized_schema_version=2,
        id_conflict_path=None,
        label_conflict_path=Path("/catalog/def.json"),
        can_import=False,
    )
    result = render.format_import_json_conflicts(preview)
    lines = result.split("\n")
    assert lines[0] == "import refused (conflict):"
    assert "label conflict: /catalog/def.json" in result
    assert "id conflict" not in result


def test_format_import_json_conflicts_both() -> None:
    from tests.conftest import make_job

    from task_scheduler.application.managed_json_transfer import ManagedJsonImportPreview

    job = make_job()
    preview = ManagedJsonImportPreview(
        source_path=Path("/tmp/x.json"),
        candidate=job,
        normalized_schema_version=2,
        id_conflict_path=Path("/catalog/abc.json"),
        label_conflict_path=Path("/catalog/def.json"),
        can_import=False,
    )
    result = render.format_import_json_conflicts(preview)
    lines = result.split("\n")
    assert lines[0] == "import refused (conflict):"
    assert "  id conflict: /catalog/abc.json" in result
    assert "  label conflict: /catalog/def.json" in result
