"""Unit tests for execution-history recording in TaskCommandService (Lane 1B)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from tests.conftest import make_job
from tests.fakes import FakeProcessRunner, FakeTaskWorld

from task_scheduler.application import JobNotFoundError
from task_scheduler.application.history_models import (
    HISTORY_UNAVAILABLE,
    HistoryEventKind,
    HistoryOutcome,
    HistoryReadResult,
)
from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
    PlistCodec,
    ProcessResult,
    SubprocessRunner,
)


def _assert_event(
    evt,
    *,
    kind,
    outcome,
    exit_code=None,
    duration=None,
    loaded=None,
    codes=(),
):
    """Assert an event matches the expected values."""
    assert evt.kind is kind
    assert evt.outcome is outcome
    assert evt.exit_code == exit_code
    assert evt.duration_seconds == duration
    assert evt.loaded == loaded
    assert evt.diagnostic_codes == codes
    assert evt.created_at.utcoffset() == timedelta(0)


# -- test_job: direct test recording ----------------------------------------


def test_test_job_success_records_two_events(tmp_path: Path) -> None:
    """2 events: DIRECT_TEST success then DIAGNOSTIC_RESULT with fired diagnostics."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    history = service.history(job.label)
    assert len(history.events) == 2

    # DIAGNOSTIC_RESULT is newest (most recent append)
    evt1 = history.events[0]
    assert evt1.kind is HistoryEventKind.DIAGNOSTIC_RESULT
    assert evt1.outcome is HistoryOutcome.FAILURE
    assert evt1.exit_code is None
    assert evt1.duration_seconds is None
    assert evt1.job_id == job.id
    assert evt1.label == job.label
    # Pre-flight probes fire because the job's script doesn't exist
    assert len(evt1.diagnostic_codes) > 0

    # DIRECT_TEST is older
    evt0 = history.events[1]
    _assert_event(
        evt0,
        kind=HistoryEventKind.DIRECT_TEST,
        outcome=HistoryOutcome.SUCCESS,
        exit_code=0,
        duration=0.0,
        loaded=None,
        codes=(),
    )
    assert evt0.job_id == job.id
    assert evt0.label == job.label


def test_test_job_failure_records_two_events(tmp_path: Path) -> None:
    """Failure: 2 events with FAILURE outcomes and diagnostic codes."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    # DirectTestService uses its own runner — replace the runner directly
    world.services._test._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=1, duration=timedelta(seconds=0.5))
    )
    service = world.services

    service.test(job.label)
    history = service.history(job.label)
    assert len(history.events) == 2

    evt1 = history.events[0]
    assert evt1.kind is HistoryEventKind.DIAGNOSTIC_RESULT
    assert evt1.outcome is HistoryOutcome.FAILURE
    assert evt1.exit_code is None
    assert evt1.duration_seconds is None
    assert evt1.job_id == job.id

    evt0 = history.events[1]
    _assert_event(
        evt0,
        kind=HistoryEventKind.DIRECT_TEST,
        outcome=HistoryOutcome.FAILURE,
        exit_code=1,
        duration=0.5,
    )
    assert evt0.job_id == job.id


def test_test_job_launch_failure_exit_code_none(tmp_path: Path) -> None:
    """Launch failure: exit_code=None → DIRECT_TEST failure."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    world.services._test._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=None, duration=timedelta(seconds=0.1))
    )
    service = world.services

    service.test(job.label)
    history = service.history(job.label)

    assert len(history.events) == 2
    evt0 = history.events[1]  # DIRECT_TEST is older (index 1)
    _assert_event(
        evt0,
        kind=HistoryEventKind.DIRECT_TEST,
        outcome=HistoryOutcome.FAILURE,
        exit_code=None,
        duration=0.1,
    )
    assert evt0.job_id == job.id


def test_test_job_unsaved_draft_records_nothing(tmp_path: Path) -> None:
    """Unsaved draft: test_job records nothing when job is not in catalog."""
    job = make_job(id=UUID("00000000-0000-0000-0000-000000000001"))
    world = FakeTaskWorld(tmp_path)
    service = world.services

    service.test_job(job)

    read_result = world.history_repo.read(
        UUID("00000000-0000-0000-0000-000000000001"), limit=50
    )
    assert len(read_result.events) == 0


def test_test_label_delegates_to_test_job(tmp_path: Path) -> None:
    """test(label) → test_job → 2 events."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    history = service.history(job.label)
    assert len(history.events) == 2
    # Most recent = DIAGNOSTIC_RESULT
    assert history.events[0].kind is HistoryEventKind.DIAGNOSTIC_RESULT


# -- run_now recording ------------------------------------------------------


def test_run_now_success(tmp_path: Path) -> None:
    """MANUAL_RUN with exit_code and duration from backend trigger."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    # run_now calls backend.trigger → backend._runner
    world.backend._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, duration=timedelta(seconds=1.2))
    )
    service = world.services

    service.run_now(job.label)
    history = service.history(job.label)

    assert len(history.events) == 1
    evt = history.events[0]
    _assert_event(
        evt,
        kind=HistoryEventKind.MANUAL_RUN,
        outcome=HistoryOutcome.SUCCESS,
        exit_code=0,
        duration=1.2,
    )
    assert evt.job_id == job.id


def test_run_now_failure(tmp_path: Path) -> None:
    """MANUAL_RUN FAILURE outcome for nonzero exit code."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    world.backend._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=1, duration=timedelta(seconds=0.3))
    )
    service = world.services

    service.run_now(job.label)
    history = service.history(job.label)

    assert len(history.events) == 1
    evt = history.events[0]
    _assert_event(
        evt,
        kind=HistoryEventKind.MANUAL_RUN,
        outcome=HistoryOutcome.FAILURE,
        exit_code=1,
        duration=0.3,
    )


# -- status recording -------------------------------------------------------


def test_status_observed_success(tmp_path: Path) -> None:
    """STATUS_OBSERVATION with outcome OBSERVED, loaded=True."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    status = service.status(job.label)
    history = service.history(job.label)

    assert len(history.events) == 1
    evt = history.events[0]
    _assert_event(
        evt,
        kind=HistoryEventKind.STATUS_OBSERVATION,
        outcome=HistoryOutcome.OBSERVED,
        exit_code=status.process.exit_code,
        duration=status.process.duration.total_seconds(),
        loaded=status.loaded,
    )
    assert evt.diagnostic_codes == ()


def test_status_loaded_none(tmp_path: Path) -> None:
    """loaded=None round-trips when launchctl status can't start."""
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    world.backend._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=None, duration=timedelta(seconds=0.1))
    )
    service = world.services

    result = service.status(job.label)
    assert result.loaded is None
    history = service.history(job.label)
    assert len(history.events) == 1
    evt = history.events[0]
    assert evt.loaded is None
    assert evt.exit_code is None


# -- history() method --------------------------------------------------------


def test_history_unknown_label_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    service = world.services
    with pytest.raises(JobNotFoundError):
        service.history("nope")


def test_history_limit_zero_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        service.history(job.label, limit=0)


def test_history_limit_101_raises(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        service.history(job.label, limit=101)


def test_history_limit_validated_before_label(tmp_path: Path) -> None:
    """Bad limit with bad label still raises ValueError, not JobNotFoundError."""
    world = FakeTaskWorld(tmp_path)
    service = world.services
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        service.history("nope", limit=0)


def test_history_no_repo_returns_unavailable(tmp_path: Path) -> None:
    """When no history repo is wired, history() returns unavailable."""
    from task_scheduler.application.job_service import JobService
    from task_scheduler.application.log_service import LogService
    from task_scheduler.application.test_service import DirectTestService
    from task_scheduler.storage import JsonJobRepository

    store = LaunchAgentStore(tmp_path / "la")
    jobs = JobService(tmp_path / "catalog")
    job = make_job()
    jobs.import_job(job)
    service = TaskCommandService(
        repository=JsonJobRepository(),
        jobs=jobs,
        store=store,
        backend=LaunchAgentBackend(store, SubprocessRunner()),
        codec=PlistCodec(),
        test=DirectTestService(SubprocessRunner()),
        logs=LogService(),
    )

    result = service.history(job.label)
    assert result == HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)
    # verify that test/run/status work without errors when history is None
    # (this also exercises the early-return path in _record_event)
    service.test(job.label)


# -- timestamp UTC-ness -----------------------------------------------------


def test_timestamp_utc(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    history = service.history(job.label)
    assert len(history.events) >= 1
    for evt in history.events:
        assert evt.created_at.utcoffset() == timedelta(0)


# -- lifecycle non-recording ------------------------------------------------


def test_lifecycle_operations_do_not_record(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    history_before = service.history(job.label)
    count_before = len(history_before.events)

    service.enable(job.label)
    service.disable(job.label)

    history_after = service.history(job.label)
    count_after = len(history_after.events)
    assert count_after == count_before


# -- limit clamping through the façade ---------------------------------------


def test_history_limit_clamping(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    for _ in range(6):
        service.test(job.label)

    history = service.history(job.label, limit=2)
    assert len(history.events) == 2
    # Most recent: DIAGNOSTIC_RESULT (2nd event of last test)
    assert history.events[0].kind is HistoryEventKind.DIAGNOSTIC_RESULT
    # Second most recent: DIRECT_TEST (1st event of last test)
    assert history.events[1].kind is HistoryEventKind.DIRECT_TEST


# -- combined history: test + run + status -----------------------------------


def test_history_combined_workflow(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    world.backend._runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, duration=timedelta(seconds=1.0))
    )
    service.run_now(job.label)
    service.status(job.label)

    history = service.history(job.label)
    assert len(history.events) == 4
    # Newest first:
    assert history.events[0].kind is HistoryEventKind.STATUS_OBSERVATION
    assert history.events[1].kind is HistoryEventKind.MANUAL_RUN
    assert history.events[2].kind is HistoryEventKind.DIAGNOSTIC_RESULT
    assert history.events[3].kind is HistoryEventKind.DIRECT_TEST


def test_history_preserves_job_id(tmp_path: Path) -> None:
    world = FakeTaskWorld(tmp_path)
    job = make_job()
    world.manage(job)
    service = world.services

    service.test(job.label)
    history = service.history(job.label)
    assert len(history.events) == 2
    for evt in history.events:
        assert evt.job_id == job.id
