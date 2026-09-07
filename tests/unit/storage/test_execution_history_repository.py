"""Tests for the SQLite execution-history repository."""

import contextlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import task_scheduler.storage.execution_history_repository as ehr_module
from task_scheduler.application.history_models import (
    HISTORY_UNAVAILABLE,
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
)
from task_scheduler.application.job_service import default_job_catalog_root
from task_scheduler.storage import (
    ExecutionHistoryRepository,
    default_history_path,
)


def _make_event(
    job_id: UUID | None = None,
    *,
    exit_code: int | None = None,
    duration_seconds: float | None = None,
    loaded: bool | None = None,
    diagnostic_codes: tuple[str, ...] = (),
    kind: HistoryEventKind = HistoryEventKind.MANUAL_RUN,
    outcome: HistoryOutcome = HistoryOutcome.SUCCESS,
    label: str = "test-job",
    created_at: datetime | None = None,
) -> HistoryEvent:
    if created_at is None:
        created_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return HistoryEvent(
        created_at=created_at,
        job_id=job_id if job_id is not None else uuid4(),
        label=label,
        kind=kind,
        outcome=outcome,
        exit_code=exit_code,
        duration_seconds=duration_seconds,
        loaded=loaded,
        diagnostic_codes=diagnostic_codes,
    )


# ── round-trip ──────────────────────────────────────────────────────────────

def test_append_read_round_trip(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()

    e1 = _make_event(job_id=jid, exit_code=0, duration_seconds=1.5,
                     created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC))
    e2 = _make_event(job_id=jid, exit_code=1, duration_seconds=2.5,
                     created_at=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC))
    e3 = _make_event(job_id=jid, exit_code=0, duration_seconds=3.0,
                     loaded=True,
                     diagnostic_codes=("DEP001", "TIMEOUT"),
                     created_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC))

    repo.append(e1)
    repo.append(e2)
    repo.append(e3)

    result = repo.read(jid, limit=10)

    assert len(result.events) == 3
    assert result.error is None

    # newest-first order
    assert result.events[0].created_at == e3.created_at
    assert result.events[1].created_at == e2.created_at
    assert result.events[2].created_at == e1.created_at

    # exact field equality
    ev3 = result.events[0]
    assert ev3.exit_code == 0
    assert ev3.duration_seconds == 3.0
    assert ev3.loaded is True
    assert ev3.diagnostic_codes == ("DEP001", "TIMEOUT")
    assert ev3.kind == HistoryEventKind.MANUAL_RUN
    assert ev3.outcome == HistoryOutcome.SUCCESS

    ev1 = result.events[2]
    assert ev1.exit_code == 0
    assert ev1.duration_seconds == 1.5
    assert ev1.loaded is None


# ── job isolation ───────────────────────────────────────────────────────────

def test_job_isolation(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    job_a = uuid4()
    job_b = uuid4()

    e_a = _make_event(job_id=job_a, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    e_b = _make_event(job_id=job_b, created_at=datetime(2025, 1, 2, tzinfo=UTC))

    repo.append(e_a)
    repo.append(e_b)

    result_a = repo.read(job_a, limit=10)
    result_b = repo.read(job_b, limit=10)

    assert len(result_a.events) == 1
    assert result_a.events[0].job_id == job_a
    assert len(result_b.events) == 1
    assert result_b.events[0].job_id == job_b


# ── limit ───────────────────────────────────────────────────────────────────

def test_limit_returns_newest_only(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()

    for i in range(5):
        e = _make_event(
            job_id=jid,
            created_at=datetime(2025, 1, i + 1, tzinfo=UTC),
        )
        repo.append(e)

    result = repo.read(jid, limit=1)
    assert len(result.events) == 1
    assert result.events[0].created_at.day == 5


def test_limit_zero_raises(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    with pytest.raises(ValueError):
        repo.read(uuid4(), limit=0)


def test_limit_over_100_raises(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    with pytest.raises(ValueError):
        repo.read(uuid4(), limit=101)


# ── healthy empty ───────────────────────────────────────────────────────────

def test_healthy_empty_returns_empty_result(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()
    result = repo.read(jid, limit=10)
    assert result.events == ()
    assert result.error is None


# ── corrupt file ────────────────────────────────────────────────────────────

def test_corrupt_database_file(tmp_path: Path) -> None:
    db_path = tmp_path / "history.sqlite3"
    db_path.write_bytes(b"this is not a sqlite database" * 100)

    repo = ExecutionHistoryRepository(db_path)
    assert repo._unavailable is True

    repo.append(_make_event())

    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


# ── unusable path ───────────────────────────────────────────────────────────

def test_unusable_path(tmp_path: Path) -> None:
    bad_path = tmp_path / "no" / "such" / "dir.sqlite3"
    repo = ExecutionHistoryRepository(bad_path)
    assert repo._unavailable is True

    repo.append(_make_event())

    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


# ── default_history_path ────────────────────────────────────────────────────

def test_default_history_path_returns_correct_path(tmp_path: Path) -> None:
    path = default_history_path()
    assert path.name == "history.sqlite3"
    expected = default_job_catalog_root().parent / "history.sqlite3"
    assert path == expected


# ── loaded field round-trip ─────────────────────────────────────────────────

def test_loaded_field_round_trip(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()

    e_true = _make_event(job_id=jid, loaded=True,
                         created_at=datetime(2025, 1, 1, tzinfo=UTC))
    e_false = _make_event(job_id=jid, loaded=False,
                          created_at=datetime(2025, 1, 2, tzinfo=UTC))
    e_none = _make_event(job_id=jid, loaded=None,
                         created_at=datetime(2025, 1, 3, tzinfo=UTC))

    repo.append(e_true)
    repo.append(e_false)
    repo.append(e_none)

    result = repo.read(jid, limit=10)
    assert len(result.events) == 3

    # newest-first: e_none (day 3), e_false (day 2), e_true (day 1)
    assert result.events[0].loaded is None
    assert result.events[1].loaded is False
    assert result.events[2].loaded is True


# ── kind and outcome decode ─────────────────────────────────────────────────

def test_kind_and_outcome_decode(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()

    e = _make_event(
        job_id=jid,
        kind=HistoryEventKind.DIAGNOSTIC_RESULT,
        outcome=HistoryOutcome.FAILURE,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    repo.append(e)
    result = repo.read(jid, limit=10)

    assert result.events[0].kind == HistoryEventKind.DIAGNOSTIC_RESULT
    assert result.events[0].outcome == HistoryOutcome.FAILURE


# ── no events when job_id not found ─────────────────────────────────────────

def test_no_events_for_unknown_job(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()
    repo.append(_make_event(job_id=uuid4()))
    result = repo.read(jid, limit=10)
    assert result.events == ()
    assert result.error is None


# ── diagnostic_codes round-trip ─────────────────────────────────────────────

def test_diagnostic_codes_round_trip(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()

    e = _make_event(
        job_id=jid,
        diagnostic_codes=("E001", "E002", "E003"),
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    repo.append(e)
    result = repo.read(jid, limit=10)

    assert result.events[0].diagnostic_codes == ("E001", "E002", "E003")


# ── sqlite3 error in append ─────────────────────────────────────────────────

def test_append_sqlite_error_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()
    repo.append(_make_event(job_id=jid))
    assert len(repo.read(jid, limit=10).events) == 1

    def _failing_connect(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("simulated disk error")

    monkeypatch.setattr(ehr_module, "_connect", _failing_connect)
    repo.append(_make_event(job_id=jid))  # no-op on connection failure
    monkeypatch.undo()

    assert len(repo.read(jid, limit=10).events) == 1


# ── sqlite3 error in read ───────────────────────────────────────────────────

def test_read_sqlite_error_returns_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    repo.append(_make_event())

    def _failing_connect(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("read error")

    monkeypatch.setattr(ehr_module, "_connect", _failing_connect)
    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


# ── malformed diagnostic_codes column (not a list) ──────────────────────────

def test_diagnostic_codes_not_list_stored_raw(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    ExecutionHistoryRepository(db_path)
    cols = "created_at, job_id, label, kind, outcome, exit_code, " \
           "duration_seconds, loaded, diagnostic_codes"
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        db.execute(
            f"INSERT INTO execution_history ({cols}) "
            'VALUES ("2025-01-01T00:00:00+00:00", '
            '"deadbeef-dead-beef-dead-beefdeadbeef", '
            '"x", "manual_run", "success", NULL, NULL, NULL, "42")'
        )
        db.commit()
    repo = ExecutionHistoryRepository(db_path)
    jid = UUID("deadbeef-dead-beef-dead-beefdeadbeef")
    result = repo.read(jid, limit=10)
    # json.loads("42") == 42, not a list, so diag_codes = [] → event created
    # with empty diagnostic_codes
    assert len(result.events) == 1
    assert result.events[0].diagnostic_codes == ()


# ── malformed row (invalid kind string) is skipped ─────────────────────────

def test_malformed_row_is_skipped(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    repo = ExecutionHistoryRepository(db_path)
    jid = uuid4()
    e = _make_event(job_id=jid)
    repo.append(e)

    cols = "created_at, job_id, label, kind, outcome, exit_code, " \
           "duration_seconds, loaded, diagnostic_codes"
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        db.execute(
            f"INSERT INTO execution_history ({cols}) "
            'VALUES ("2025-01-01T00:00:00+00:00", ?, '
            '"x", "bogus_kind", "bogus_outcome", NULL, NULL, NULL, "[]")',
            (str(jid),),
        )
        db.commit()

    result = repo.read(jid, limit=10)
    assert len(result.events) == 1
    assert result.events[0].kind == e.kind


# ── per-operation connections ───────────────────────────────────────────────

def test_new_instance_sees_existing_records(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    first = ExecutionHistoryRepository(db_path)
    first.append(_make_event(job_id=jid))
    second = ExecutionHistoryRepository(db_path)
    result = second.read(jid, limit=10)
    assert len(result.events) == 1
    assert result.events[0].job_id == jid
