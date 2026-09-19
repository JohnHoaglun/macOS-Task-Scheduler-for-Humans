"""Application-level structured file logging and crash capture.

Provides a JSON Lines event stream with bounded retention (10 MB / 14 days),
a telemetry API for structured UI/operation events, and crash hooks that route
unhandled exceptions and unraisables into the same structured log.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType

from task_scheduler.application.job_service import default_job_logs_root

__all__ = [
    "APP_LOG_FILENAME",
    "app_log_path",
    "configure_logging",
    "emit_error",
    "emit_event",
    "install_crash_hooks",
    "new_operation_id",
    "session_id",
]

APP_LOG_FILENAME = "app.log"
_LOG_LEVEL = logging.DEBUG
_MAX_TOTAL_BYTES = 10 * 1024 * 1024
_MAX_AGE_DAYS = 14
_SEGMENT_MAX_BYTES = 1_000_000
_HANDLER_ATTR = "_tss_app_file_handler"
_CRASH_LOGGER = "task_scheduler.crash"
_TELEMETRY_LOGGER = "task_scheduler.telemetry"

_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelno",
        "levelname",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
    }
)

_session_id: str = uuid.uuid4().hex
_sequence: int = 0
_seq_lock = threading.Lock()


def app_log_path() -> Path:
    """Return the application debug-log path (under the user's Logs directory)."""
    return default_job_logs_root() / APP_LOG_FILENAME


def session_id() -> str:
    """Return the process-wide session identifier."""
    return _session_id


def new_operation_id() -> str:
    """Return a unique short operation identifier for correlating related events."""
    return uuid.uuid4().hex[:12]


def _next_seq() -> int:
    global _sequence
    with _seq_lock:
        _sequence += 1
        return _sequence


def _archive_date_key(name: str) -> str | None:
    """Extract a sortable YYYY-MM-DD key from an archive filename, or None."""
    prefix = f"{APP_LOG_FILENAME}."
    if not name.startswith(prefix):
        return None
    remainder = name[len(prefix):]
    parts = remainder.split("-")
    if len(parts) < 3:
        return None
    return f"{parts[0]}-{parts[1]}-{parts[2]}"


def _prune_archives(log_dir: Path) -> None:
    """Remove archives older than _MAX_AGE_DAYS and enforce _MAX_TOTAL_BYTES."""
    cutoff = datetime.now(UTC) - timedelta(days=_MAX_AGE_DAYS)
    dated: list[tuple[str, Path]] = []
    for p in log_dir.iterdir():
        if not p.is_file():
            continue
        date_key = _archive_date_key(p.name)
        if date_key is None:
            continue
        try:
            file_date = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if file_date < cutoff:
            p.unlink(missing_ok=True)
            continue
        dated.append((date_key, p))
    dated.sort(key=lambda x: x[0])
    total = 0
    active = log_dir / APP_LOG_FILENAME
    if active.exists():
        total = active.stat().st_size
    for _, p in dated:
        total += p.stat().st_size
    i = 0
    while total > _MAX_TOTAL_BYTES and i < len(dated):
        _, victim = dated[i]
        total -= victim.stat().st_size
        victim.unlink(missing_ok=True)
        i += 1


class _BoundedJSONLHandler(logging.Handler):
    """JSON Lines file handler with bounded retention (10 MB / 14 days).

    Rotates when a new UTC day begins or the active segment exceeds
    _SEGMENT_MAX_BYTES. Archives are named ``app.log.<YYYY-MM-DD>[-<N>]``.
    Pruning removes archives older than 14 days and enforces the 10 MB
    aggregate cap (oldest first).
    """

    def __init__(self, log_path: Path) -> None:
        super().__init__(level=_LOG_LEVEL)
        self._log_path = log_path
        self._lock = threading.Lock()
        self._current_date: str = datetime.now(UTC).strftime("%Y-%m-%d")
        self._segment_count: int = 0
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = log_path.open("a", encoding="utf-8")
        with suppress(OSError):
            os.chmod(log_path, 0o600)
        _prune_archives(log_path.parent)

    def _rollover_needed(self) -> bool:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._current_date:
            return True
        try:
            return self._log_path.stat().st_size > _SEGMENT_MAX_BYTES
        except FileNotFoundError:
            return True

    def _archive_name(self) -> Path:
        base = f"{APP_LOG_FILENAME}.{self._current_date}"
        if self._segment_count == 0:
            candidate = self._log_path.parent / base
        else:
            candidate = self._log_path.parent / f"{base}-{self._segment_count + 1}"
        counter = 1
        while candidate.exists():
            counter += 1
            candidate = self._log_path.parent / f"{base}-{self._segment_count + 1}-{counter}"
        return candidate

    def _do_rollover(self) -> None:
        self._stream.close()
        archive = self._archive_name()
        self._log_path.rename(archive)
        with suppress(OSError):
            os.chmod(archive, 0o600)
        self._segment_count += 1
        self._current_date = datetime.now(UTC).strftime("%Y-%m-%d")
        self._stream = self._log_path.open("a", encoding="utf-8")
        with suppress(OSError):
            os.chmod(self._log_path, 0o600)
        _prune_archives(self._log_path.parent)

    def _serialize(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "sid": _session_id,
            "seq": _next_seq(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            entry[key] = value
        return json.dumps(entry, default=str, ensure_ascii=False)

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            try:
                if self._rollover_needed():
                    self._do_rollover()
                self._stream.write(self._serialize(record) + "\n")
                self._stream.flush()
            except Exception:
                self.handleError(record)

    def close(self) -> None:
        with self._lock:
            try:
                self._stream.close()
            finally:
                super().close()


def _file_handler(log_path: Path) -> _BoundedJSONLHandler:
    """Create the bounded JSONL handler, tagged for idempotency."""
    handler = _BoundedJSONLHandler(log_path)
    setattr(handler, _HANDLER_ATTR, True)
    return handler


def configure_logging(log_path: Path | None = None) -> Path:
    """Configure root-logger file output (idempotent) and return the log path.

    Creates the log directory and a single bounded JSONL handler at DEBUG level
    so the app's structured events and crashes are captured. Calling it again
    adds no further handlers.
    """
    path = log_path or app_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_ATTR, False) for h in root.handlers):
        return path
    root.setLevel(_LOG_LEVEL)
    root.addHandler(_file_handler(path))
    logging.getLogger(__name__).info("app logging configured at %s", path)
    return path


def emit_event(
    event: str,
    *,
    source: str,
    task_id: str | None = None,
    config: dict[str, object] | None = None,
    outcome: str | None = None,
    **fields: object,
) -> None:
    """Emit a structured telemetry event to the application log."""
    logger = logging.getLogger(_TELEMETRY_LOGGER)
    extra: dict[str, object] = {
        "event": event,
        "source": source,
    }
    if task_id is not None:
        extra["task_id"] = task_id
    if config is not None:
        extra["config"] = config
    if outcome is not None:
        extra["outcome"] = outcome
    extra.update(fields)
    logger.info("telemetry: %s", event, extra=extra)


def emit_error(
    event: str,
    *,
    source: str,
    exc: BaseException,
    op_id: str | None = None,
    task_id: str | None = None,
    **fields: object,
) -> None:
    """Emit a structured error event with exception details."""
    logger = logging.getLogger(_TELEMETRY_LOGGER)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    extra: dict[str, object] = {
        "event": event,
        "source": source,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": tb,
        },
    }
    if op_id is not None:
        extra["op_id"] = op_id
    if task_id is not None:
        extra["task_id"] = task_id
    extra.update(fields)
    logger.error("telemetry: %s", event, extra=extra)


def _format_exception(
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
) -> str:
    """Render a full traceback, tolerating a missing type, value, or traceback."""
    if exc_value is None:
        return "no exception value available"
    exc_type = exc_type or type(exc_value)
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def install_crash_hooks(on_crash: Callable[[], None] | None = None) -> None:
    """Route unhandled exceptions and unraisables into the app log.

    The full traceback is always written as a structured crash event.
    *on_crash*, when given, is then invoked best-effort — the GUI uses it to
    show a modal crash dialog. Previous hooks are preserved and still run.
    """
    crash_logger = logging.getLogger(_CRASH_LOGGER)
    default_hook = sys.excepthook

    def _excepthook(
        exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
    ) -> None:
        crash_logger.error(
            "unhandled exception",
            extra={
                "event": "crash.unhandled_exception",
                "source": "python",
                "error": {
                    "type": exc_type.__name__,
                    "message": str(exc_value),
                    "traceback": _format_exception(exc_type, exc_value, exc_tb),
                },
            },
        )
        if on_crash is not None:
            try:
                on_crash()
            except Exception:
                crash_logger.exception("crash callback failed")
        default_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    if hasattr(sys, "unraisablehook"):
        default_unraisable = sys.unraisablehook

        def _unraisablehook(unraisable: sys.UnraisableHookArgs) -> None:
            message = str(
                getattr(unraisable, "err_msg", None)
                or getattr(unraisable, "description", None)
                or "unknown"
            )
            crash_logger.error(
                "unraisable exception",
                extra={
                    "event": "crash.unraisable_exception",
                    "source": "python",
                    "error": {
                        "type": getattr(unraisable, "exc_type", type).__name__
                        if getattr(unraisable, "exc_type", None)
                        else "Unknown",
                        "message": message,
                        "traceback": _format_exception(
                            unraisable.exc_type,
                            unraisable.exc_value,
                            unraisable.exc_traceback,
                        ),
                    },
                },
            )
            default_unraisable(unraisable)

        sys.unraisablehook = _unraisablehook
