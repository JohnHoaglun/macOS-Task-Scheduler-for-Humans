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
from task_scheduler.storage import (
    ExecutionHistoryRepository,
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

# ── job isolation ───────────────────────────────────────────────────────────

# ── limit ───────────────────────────────────────────────────────────────────

def test_limit_over_100_raises(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    with pytest.raises(ValueError):
        repo.read(uuid4(), limit=101)

# ── healthy empty ───────────────────────────────────────────────────────────

# ── corrupt file ────────────────────────────────────────────────────────────

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

# ── no events when job_id not found ─────────────────────────────────────────

# ── diagnostic_codes round-trip ─────────────────────────────────────────────

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
