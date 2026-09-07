"""Unit tests for the mactask history CLI command and format_history renderer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from task_scheduler.application import JobService, LogService, TaskCommandService
from task_scheduler.application.history_models import (
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
    HistoryReadResult,
)
from task_scheduler.application.test_service import DirectTestService
from task_scheduler.cli import app as cli_app
from task_scheduler.cli import render
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    ProcessResult,
)
from task_scheduler.storage import JsonJobRepository
from tests.conftest import FIXED_JOB_ID, make_job
from tests.fakes import FakeTaskWorld

RUNNER = CliRunner()
OK_PROCESS = ProcessResult(exit_code=0)


def invoke(world: FakeTaskWorld, *args: str) -> object:
    return RUNNER.invoke(cli_app.create_app(world.services), list(args))


def invoke_from(services: TaskCommandService, *args: str) -> object:
    return RUNNER.invoke(cli_app.create_app(services), list(args))


class FakeProcessRunner:
    """Minimal process runner stub for unavailable-service test."""

    def __init__(self, result: ProcessResult) -> None:
        self._result = result
        self.specs = []

    def run(self, spec: object) -> ProcessResult:
        self.specs.append(spec)
        return self._result





# ── format_history renderer tests ──────────────────────────────────────────


def test_format_history_status_observation_full() -> None:
    """A status_observation event with every optional field rendered."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=0,
                duration_seconds=1.256,
                loaded=True,
                diagnostic_codes=("slow_execution",),
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    expected = (
        "2025-06-15T10:30:00Z status_observation success "
        "exit=0 duration=1.256s loaded=yes codes=slow_execution"
    )
    assert out == expected


def test_format_history_direct_test_no_loaded() -> None:
    """direct_test kind must NOT render a loaded field."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.DIRECT_TEST,
                outcome=HistoryOutcome.FAILURE,
                exit_code=1,
                duration_seconds=0.5,
                loaded=False,  # should be ignored
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "loaded=" not in out
    assert "exit=1" in out
    assert "duration=0.500s" in out


def test_format_history_empty_codes_omitted() -> None:
    """Empty diagnostic_codes must not render a codes field."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.DIAGNOSTIC_RESULT,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=None,
                duration_seconds=None,
                loaded=None,
                diagnostic_codes=(),
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert out == "2025-06-15T10:30:00Z diagnostic_result success"
    assert "codes=" not in out


def test_format_history_exit_code_none_omitted() -> None:
    """exit_code None must not render an exit= field."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.MANUAL_RUN,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=None,
                duration_seconds=None,
                loaded=None,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "exit=" not in out


def test_format_history_duration_none_omitted() -> None:
    """duration_seconds None must not render a duration= field."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.DIAGNOSTIC_RESULT,
                outcome=HistoryOutcome.FAILURE,
                exit_code=None,
                duration_seconds=None,
                loaded=None,
                diagnostic_codes=("module_not_found", "executable_not_found"),
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "duration=" not in out
    assert "codes=module_not_found,executable_not_found" in out


def test_format_history_empty_events() -> None:
    """Empty events tuple produces empty string."""
    result = HistoryReadResult(events=())
    assert render.format_history(result, "com.example.job") == ""


def test_format_history_multiple_events_newest_first() -> None:
    """Multiple events preserve order (newest first)."""
    ts1 = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    ts2 = datetime(2025, 6, 15, 9, 0, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts1,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.OBSERVED,
                loaded=True,
            ),
            HistoryEvent(
                created_at=ts2,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.DIRECT_TEST,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=0,
                duration_seconds=None,
                loaded=None,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    lines = out.split("\n")
    assert len(lines) == 2
    assert "10:30:00Z" in lines[0]
    assert "09:00:00Z" in lines[1]


def test_format_history_duration_three_decimals() -> None:
    """Duration must render with exactly 3 decimal places, rounded."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=0,
                duration_seconds=0.5,
                loaded=True,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "duration=0.500s" in out

    result2 = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.SUCCESS,
                exit_code=0,
                duration_seconds=1.2567,
                loaded=True,
            ),
        )
    )
    out2 = render.format_history(result2, "com.example.job")
    assert "duration=1.257s" in out2


def test_format_history_codes_comma_join_no_spaces() -> None:
    """Diagnostic codes must be comma-joined with NO spaces."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.DIAGNOSTIC_RESULT,
                outcome=HistoryOutcome.FAILURE,
                diagnostic_codes=("a", "b", "c"),
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "codes=a,b,c" in out
    assert "codes=a, b, c" not in out


def test_format_history_non_utc_converts_to_utc_z() -> None:
    """Non-UTC-aware datetimes are converted to UTC, then rendered with Z suffix."""
    est = timezone(timedelta(hours=-5))
    ts = datetime(2025, 6, 15, 5, 30, 0, tzinfo=est)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.OBSERVED,
                loaded=True,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    # 5:30 EST = 10:30 UTC
    assert "10:30:00Z" in out


def test_format_history_status_observation_loaded_unknown() -> None:
    """loaded=None for status_observation → loaded=unknown."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.OBSERVED,
                loaded=None,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert "loaded=unknown" in out


def test_format_history_no_trailing_space() -> None:
    """Each line must not end with a trailing space."""
    ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC)
    result = HistoryReadResult(
        events=(
            HistoryEvent(
                created_at=ts,
                job_id=FIXED_JOB_ID,
                label="com.example.job",
                kind=HistoryEventKind.STATUS_OBSERVATION,
                outcome=HistoryOutcome.OBSERVED,
                loaded=True,
            ),
        )
    )
    out = render.format_history(result, "com.example.job")
    assert not out.endswith(" ")
    for line in out.split("\n"):
        assert not line.endswith(" ")


# ── CLI history command tests ──────────────────────────────────────────────


def test_history_unknown_label_exits_usage(tmp_path: Path) -> None:
    """Unknown label → exit 2 with JobNotFoundError message."""
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "history", "missing.label")
    assert result.exit_code == 2
    assert "no managed job with label" in result.stderr


def test_history_limit_zero_exits_usage(tmp_path: Path) -> None:
    """limit=0 → exit 2 with ValueError message."""
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "history", "com.example.job", "--limit", "0")
    assert result.exit_code == 2
    assert "limit must be between 1 and 100 inclusive" in result.stderr


def test_history_limit_101_exits_usage(tmp_path: Path) -> None:
    """limit=101 → exit 2."""
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "history", "com.example.job", "--limit", "101")
    assert result.exit_code == 2
    assert "limit must be between 1 and 100 inclusive" in result.stderr


def test_history_limit_negative_exits_usage(tmp_path: Path) -> None:
    """limit=-1 → exit 2."""
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "history", "com.example.job", "--limit", "-1")
    assert result.exit_code == 2
    assert "limit must be between 1 and 100 inclusive" in result.stderr


def test_history_unavailable_service_exits_failure(tmp_path: Path) -> None:
    """Service without history repo → exit 1, error on stderr."""
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    la_root = tmp_path / "launchagents"
    la_root.mkdir()
    store = LaunchAgentStore(la_root)
    jobs = JobService(catalog_root)
    backend = LaunchAgentBackend(store, FakeProcessRunner(result=OK_PROCESS), uid=1000)
    services = TaskCommandService(
        repository=JsonJobRepository(),
        jobs=jobs,
        store=store,
        backend=backend,
        codec=PlistCodec(),
        test=DirectTestService(FakeProcessRunner(result=OK_PROCESS)),
        logs=LogService(),
        history=None,
    )
    job = make_job(label="com.example.job")
    jobs.import_job(job)
    store.write(job)
    result = invoke_from(services, "history", "com.example.job")
    assert result.exit_code == 1
    assert "execution history unavailable" in result.stderr
    assert result.stdout == ""


def test_history_zero_events(tmp_path: Path) -> None:
    """No history events → exit 0 with 'No history found.'"""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    result = invoke(world, "history", job.label)
    assert result.exit_code == 0
    assert result.stdout.strip() == "No history found."


def test_history_with_events(tmp_path: Path) -> None:
    """Events present → exit 0 with formatted output."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    # Trigger a status observation via services.status
    services = world.services
    services.status(job.label)
    result = invoke(world, "history", job.label)
    assert result.exit_code == 0
    assert "status_observation" in result.stdout
    assert "2025" in result.stdout or "2026" in result.stdout


def test_history_with_multiple_events_via_direct_test(tmp_path: Path) -> None:
    """Multiple events from direct_test + diagnostic_result."""
    world = FakeTaskWorld(
        tmp_path,
        test=ProcessResult(
            exit_code=0,
            stdout="ok",
            duration=timedelta(milliseconds=120),
        ),
    )
    job = make_job()
    world.manage(job)
    services = world.services
    services.test(job.label)
    result = invoke(world, "history", job.label)
    assert result.exit_code == 0
    assert "direct_test" in result.stdout
    assert "diagnostic_result" in result.stdout


def test_history_limit_option(tmp_path: Path) -> None:
    """--limit option works."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    services = world.services
    services.status(job.label)
    result = invoke(world, "history", job.label, "--limit", "1")
    assert result.exit_code == 0
