"""Unit tests for the mactask history CLI command and format_history renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.conftest import FIXED_JOB_ID, make_job
from tests.fakes import FakeTaskWorld
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

def test_format_history_empty_events() -> None:
    """Empty events tuple produces empty string."""
    result = HistoryReadResult(events=())
    assert render.format_history(result, "com.example.job") == ""

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

# ── CLI history command tests ──────────────────────────────────────────────

def test_history_unknown_label_exits_usage(tmp_path: Path) -> None:
    """Unknown label → exit 2 with JobNotFoundError message."""
    world = FakeTaskWorld(tmp_path)
    result = invoke(world, "history", "missing.label")
    assert result.exit_code == 2
    assert "no managed job with label" in result.stderr

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

def test_history_limit_option(tmp_path: Path) -> None:
    """--limit option works."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    services = world.services
    services.status(job.label)
    result = invoke(world, "history", job.label, "--limit", "1")
    assert result.exit_code == 0
