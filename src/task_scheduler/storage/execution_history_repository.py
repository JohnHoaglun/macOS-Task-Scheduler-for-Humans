"""SQLite persistence for execution-history records.

This module implements the append-only ``HistoryRepository`` port backed by
a small, embedded SQLite database — no third-party dependencies.

The store is a low-volume, append-only audit log, so each operation opens a
fresh connection for the duration of the call instead of holding a persistent
connection. This keeps the repository free of long-lived connection state
(no cleanup hooks, no unclosed-connection warnings) at negligible cost.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from task_scheduler.application.history_models import (
    HISTORY_UNAVAILABLE,
    HistoryEvent,
    HistoryEventKind,
    HistoryOutcome,
    HistoryReadResult,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    job_id TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    outcome TEXT NOT NULL,
    exit_code INTEGER,
    duration_seconds REAL,
    loaded INTEGER,
    diagnostic_codes TEXT NOT NULL
)
"""

_INDEX = """
CREATE INDEX IF NOT EXISTS idx_execution_history_job_id
ON execution_history (job_id, id)
"""


def _connect(path: Path) -> sqlite3.Connection:
    """Open a new connection to the database at *path*."""
    return sqlite3.connect(str(path), check_same_thread=False)


class ExecutionHistoryRepository:
    """Append-only execution-history store backed by SQLite.

    Construction validates the path and creates the schema; it never raises
    — any open or schema failure marks the repository unavailable, so later
    ``append`` calls are no-ops and ``read`` returns ``HISTORY_UNAVAILABLE``.

    Each operation opens a fresh connection, so the repository holds no
    long-lived connection state.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._unavailable = False
        db: sqlite3.Connection | None = None
        try:
            db = _connect(path)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(_SCHEMA)
            db.execute(_INDEX)
            db.commit()
        except Exception:
            self._unavailable = True
        finally:
            if db is not None:
                with contextlib.suppress(Exception):
                    db.close()

    def append(self, event: HistoryEvent) -> None:
        """Record one event. Best-effort — never raises."""
        if self._unavailable:
            return

        try:
            created_at = event.created_at.astimezone(UTC).isoformat()
            diagnostic_codes = json.dumps(list(event.diagnostic_codes))
            loaded = (
                1 if event.loaded is True else (
                    0 if event.loaded is False else None
                )
            )

            with contextlib.closing(_connect(self._path)) as db:
                db.execute(
                    """
                    INSERT INTO execution_history
                        (created_at, job_id, label, kind, outcome, exit_code,
                         duration_seconds, loaded, diagnostic_codes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        str(event.job_id),
                        event.label,
                        event.kind.value,
                        event.outcome.value,
                        event.exit_code,
                        event.duration_seconds,
                        loaded,
                        diagnostic_codes,
                    ),
                )
                db.commit()
        except (sqlite3.Error, OSError):
            pass

    def read(
        self, job_id: UUID, *, limit: int
    ) -> HistoryReadResult:
        """Read the most recent events for *job_id*, newest first.

        Raises ``ValueError`` when *limit* is outside ``[1, 100]``.
        Storage failures surface as a safe ``HISTORY_UNAVAILABLE`` result.
        """
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100 inclusive")

        if self._unavailable:
            return HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)

        try:
            with contextlib.closing(_connect(self._path)) as db:
                rows = db.execute(
                    """
                    SELECT created_at, job_id, label, kind, outcome,
                           exit_code, duration_seconds, loaded,
                           diagnostic_codes
                    FROM execution_history
                    WHERE job_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                """,
                    (str(job_id), limit),
                ).fetchall()
        except (sqlite3.Error, OSError):
            return HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)

        events: list[HistoryEvent] = []
        for row in rows:
            created_at_str, row_job_id, label, kind_str, outcome_str, \
                exit_code, duration_seconds, loaded_int, \
                diagnostic_codes_str = row

            try:
                created_at = datetime.fromisoformat(created_at_str)
                kind = HistoryEventKind(kind_str)
                outcome = HistoryOutcome(outcome_str)
                if loaded_int is None:
                    loaded = None
                elif loaded_int == 0:
                    loaded = False
                else:
                    loaded = True
                diag_codes = json.loads(diagnostic_codes_str) if diagnostic_codes_str else ()
                if not isinstance(diag_codes, list):
                    diag_codes = []
                events.append(
                    HistoryEvent(
                        created_at=created_at,
                        job_id=UUID(row_job_id),
                        label=label,
                        kind=kind,
                        outcome=outcome,
                        exit_code=exit_code,
                        duration_seconds=duration_seconds,
                        loaded=loaded,
                        diagnostic_codes=tuple(diag_codes),
                    )
                )
            except Exception:
                continue

        return HistoryReadResult(events=tuple(events))


def default_history_path() -> Path:
    """Return the default location for the history SQLite database.

    Lives alongside the job catalog so ``~/Library/Application Support/
    macOS Task Scheduler for Humans/history.sqlite3`` is the default.
    """
    from task_scheduler.application.job_service import default_job_catalog_root

    return default_job_catalog_root().parent / "history.sqlite3"
