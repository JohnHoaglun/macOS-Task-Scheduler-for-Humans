"""Tests for the SQLite execution-history repository."""

import contextlib
import logging
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
from task_scheduler.storage import ExecutionHistoryRepository


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


def test_limit_over_100_raises(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    with pytest.raises(ValueError):
        repo.read(uuid4(), limit=101)


def test_unusable_path(tmp_path: Path) -> None:
    bad_path = tmp_path / "no" / "such" / "dir.sqlite3"
    repo = ExecutionHistoryRepository(bad_path)
    assert repo._unavailable is True
    repo.append(_make_event())
    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


def test_loaded_field_round_trip(tmp_path: Path) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()
    e_true = _make_event(job_id=jid, loaded=True, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    e_false = _make_event(job_id=jid, loaded=False, created_at=datetime(2025, 1, 2, tzinfo=UTC))
    e_none = _make_event(job_id=jid, loaded=None, created_at=datetime(2025, 1, 3, tzinfo=UTC))
    repo.append(e_true)
    repo.append(e_false)
    repo.append(e_none)
    result = repo.read(jid, limit=10)
    assert len(result.events) == 3
    # newest-first: e_none (day 3), e_false (day 2), e_true (day 1)
    assert result.events[0].loaded is None
    assert result.events[1].loaded is False
    assert result.events[2].loaded is True


def test_append_sqlite_error_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    jid = uuid4()
    repo.append(_make_event(job_id=jid))
    assert len(repo.read(jid, limit=10).events) == 1

    def _failing_connect(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("simulated disk error")

    monkeypatch.setattr(ehr_module, "_connect", _failing_connect)
    repo.append(_make_event(job_id=jid))  # marks the repository unavailable
    monkeypatch.undo()
    result = repo.read(jid, limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


@pytest.mark.parametrize("exc_type", (sqlite3.OperationalError, OSError))
def test_append_failure_logs_once_then_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc_type: type[Exception],
) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")

    def _failing_connect(path: Path) -> sqlite3.Connection:
        raise exc_type("simulated append failure")

    monkeypatch.setattr(ehr_module, "_connect", _failing_connect)
    with caplog.at_level(
        logging.ERROR, logger="task_scheduler.storage.execution_history_repository"
    ):
        repo.append(_make_event())
        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].exc_info is not None
        assert errors[0].getMessage() == (
            "execution history append failed; recording is now unavailable"
        )
        repo.append(_make_event())
        assert sum(1 for record in caplog.records if record.levelno == logging.ERROR) == 1
    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


def test_read_sqlite_error_returns_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = ExecutionHistoryRepository(tmp_path / "hist.db")
    repo.append(_make_event())

    def _failing_connect(path: Path) -> sqlite3.Connection:
        raise sqlite3.OperationalError("read error")

    monkeypatch.setattr(ehr_module, "_connect", _failing_connect)
    result = repo.read(uuid4(), limit=10)
    assert result.events == ()
    assert result.error == HISTORY_UNAVAILABLE


def test_diagnostic_codes_not_list_stored_raw(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    ExecutionHistoryRepository(db_path)
    cols = (
        "created_at, job_id, label, kind, outcome, exit_code, "
        "duration_seconds, loaded, diagnostic_codes"
    )
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


def test_malformed_row_is_skipped(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    repo = ExecutionHistoryRepository(db_path)
    jid = uuid4()
    e = _make_event(job_id=jid)
    repo.append(e)
    cols = (
        "created_at, job_id, label, kind, outcome, exit_code, "
        "duration_seconds, loaded, diagnostic_codes"
    )
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


def _seed(db_path: Path, job_id: UUID, count: int, prefix: str = "seed") -> None:
    ExecutionHistoryRepository(db_path)
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        db.executemany(
            "INSERT INTO execution_history "
            "(created_at, job_id, label, kind, outcome, diagnostic_codes) "
            "VALUES ('2025-01-01T00:00:00+00:00', ?, ?, 'manual_run', 'success', '[]')",
            [(str(job_id), f"{prefix}-{i:04d}") for i in range(count)],
        )
        db.commit()


def _count(db_path: Path, job_id: UUID) -> int:
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        return db.execute(
            "SELECT COUNT(*) FROM execution_history WHERE job_id = ?", (str(job_id),)
        ).fetchone()[0]


def test_max_events_per_job_is_1000() -> None:
    assert ehr_module.MAX_EVENTS_PER_JOB == 1000


@pytest.mark.parametrize(("seed", "expected"), [(1000, 1000), (999, 1000), (5, 6)])
def test_append_prunes_at_and_below_cap(
    tmp_path: Path, seed: int, expected: int) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, seed)
    ExecutionHistoryRepository(db_path).append(_make_event(job_id=jid))
    assert _count(db_path, jid) == expected


def test_append_prune_leaves_other_jobs_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid_a, jid_b = uuid4(), uuid4()
    _seed(db_path, jid_a, 1000)
    _seed(db_path, jid_b, 1000)
    ExecutionHistoryRepository(db_path).append(_make_event(job_id=jid_a))
    assert _count(db_path, jid_a) == 1000
    assert _count(db_path, jid_b) == 1000


def test_open_prunes_preexisting_oversized_job(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, 1005)
    ExecutionHistoryRepository(db_path)
    assert _count(db_path, jid) == 1000


def test_open_prunes_every_job(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid_a, jid_b = uuid4(), uuid4()
    _seed(db_path, jid_a, 1001)
    _seed(db_path, jid_b, 1002)
    ExecutionHistoryRepository(db_path)
    assert _count(db_path, jid_a) == 1000
    assert _count(db_path, jid_b) == 1000


def test_prune_deletes_oldest_keeps_newest(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, 1001, prefix="e")
    ExecutionHistoryRepository(db_path)
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        labels = {
            row[0]
            for row in db.execute(
                "SELECT label FROM execution_history WHERE job_id = ?", (str(jid),)
            )
        }
    assert len(labels) == 1000
    assert "e-0000" not in labels
    assert "e-1000" in labels


def test_retention_is_by_row_id_not_created_at(tmp_path: Path) -> None:
    # rowid grows while created_at shrinks: timestamp-based retention would
    # keep r-0000 (newest timestamp), rowid-based retention deletes it.
    db_path = tmp_path / "hist.db"
    ExecutionHistoryRepository(db_path)
    jid = uuid4()
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        db.executemany(
            "INSERT INTO execution_history "
            "(created_at, job_id, label, kind, outcome, diagnostic_codes) "
            "VALUES (?, ?, ?, 'manual_run', 'success', '[]')",
            [
                (
                    f"2025-{1 + (1000 - i) // 366:02d}-01T00:00:00+00:00",
                    str(jid),
                    f"r-{i:04d}",
                )
                for i in range(1001)
            ],
        )
        db.commit()
    ExecutionHistoryRepository(db_path)
    assert _count(db_path, jid) == 1000
    with contextlib.closing(sqlite3.connect(str(db_path))) as db:
        labels = {
            row[0]
            for row in db.execute(
                "SELECT label FROM execution_history WHERE job_id = ?", (str(jid),)
            )
        }
    assert "r-0000" not in labels
    assert "r-1000" in labels


def test_read_after_prune_returns_newest_first(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, 1001)
    repo = ExecutionHistoryRepository(db_path)
    result = repo.read(jid, limit=100)
    assert len(result.events) == 100
    assert {event.label for event in result.events} == {f"seed-{i:04d}" for i in range(901, 1001)}


def test_repeated_appends_stay_at_cap(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, 999)
    repo = ExecutionHistoryRepository(db_path)
    for _ in range(3):
        repo.append(_make_event(job_id=jid))
    assert _count(db_path, jid) == 1000


def test_pruned_repository_still_appends(tmp_path: Path) -> None:
    db_path = tmp_path / "hist.db"
    jid = uuid4()
    _seed(db_path, jid, 1001)
    repo = ExecutionHistoryRepository(db_path)
    repo.append(_make_event(job_id=jid, label="newest"))
    assert _count(db_path, jid) == 1000
    result = repo.read(jid, limit=1)
    assert result.events[0].label == "newest"
