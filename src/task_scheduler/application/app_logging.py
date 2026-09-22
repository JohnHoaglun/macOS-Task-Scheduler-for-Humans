"""Application-level structured logging, crash capture, and degraded fallback.

Provides a JSON Lines event stream with bounded retention (10 MB / 14 days)
and crash hooks that route unhandled exceptions, unraisables, and native
crash dumps into the same structured log.

The secure file handler is the normal application log target. If the secure
log directory, file, permissions, retention, or stream cannot be established,
the module falls back to a structured JSONL ``sys.stderr`` handler and exposes
a stable, non-sensitive degraded reason.
"""

from __future__ import annotations

import faulthandler
import io
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
from typing import TextIO

from task_scheduler.application.job_service import default_job_logs_root

__all__ = [
    "APP_LOG_FILENAME",
    "app_log_path",
    "configure_logging",
    "install_crash_hooks",
    "logging_degraded_reason",
    "new_operation_id",
    "session_id",
]

APP_LOG_FILENAME = "app.log"
_LOG_LEVEL = logging.DEBUG
_MAX_TOTAL_BYTES = 10 * 1024 * 1024
_MAX_AGE_DAYS = 14
_SEGMENT_MAX_BYTES = 1_000_000
_TAG_ATTR = "_tss_app_logging_handler"
_KIND_ATTR = "_tss_app_logging_kind"
_PATH_ATTR = "_tss_app_logging_path"
_REASON_ATTR = "_tss_logging_degraded_reason"
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
_fault_file: TextIO | None = None


class _LoggingFault(OSError):
    """Internal fault carrying a stable, non-sensitive degraded reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def app_log_path() -> Path:
    """Return the application debug-log path (under the user's Logs directory)."""
    return default_job_logs_root() / APP_LOG_FILENAME


def session_id() -> str:
    """Return the process-wide session identifier."""
    return _session_id


def new_operation_id() -> str:
    """Return a unique short operation identifier for correlating related events."""
    return uuid.uuid4().hex[:12]


def logging_degraded_reason() -> str | None:
    """Return the stable degraded-logging reason, or ``None`` when healthy."""
    handler = _app_handler()
    if handler is None or getattr(handler, _KIND_ATTR, None) != "stderr":
        return None
    reason = getattr(handler, _REASON_ATTR, None)
    return reason if isinstance(reason, str) else "log-write-failed"


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


def _enforce_user_only(path: Path) -> int:
    """Apply and verify user-only ``0600`` permissions, returning the size."""
    os.chmod(path, 0o600)
    stat = os.stat(path)
    if stat.st_mode & 0o777 != 0o600:
        raise OSError("log file permissions could not be verified")
    return stat.st_size


def _serialize(record: logging.LogRecord) -> str:
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


def _prune_archives(log_dir: Path) -> int:
    """Remove expired archives, enforce permissions, and apply the size cap."""
    cutoff = datetime.now(UTC) - timedelta(days=_MAX_AGE_DAYS)
    dated: list[tuple[str, Path, int]] = []
    try:
        entries = list(log_dir.iterdir())
    except OSError as exc:
        raise _LoggingFault("log-directory-unavailable") from exc
    for path in entries:
        if not path.is_file():
            continue
        date_key = _archive_date_key(path.name)
        if date_key is None:
            continue
        try:
            file_date = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if file_date < cutoff:
            with suppress(OSError):
                path.unlink()
            continue
        dated.append((date_key, path, 0))
    dated.sort(key=lambda item: item[0])
    active = log_dir / APP_LOG_FILENAME
    total = 0
    if active.exists():
        try:
            total = _enforce_user_only(active)
        except OSError as exc:
            raise _LoggingFault("log-permissions-unavailable") from exc
    for index, (date_key, path, _) in enumerate(dated):
        try:
            size = _enforce_user_only(path)
            total += size
            dated[index] = (date_key, path, size)
        except OSError as exc:
            raise _LoggingFault("log-permissions-unavailable") from exc
    index = 0
    while total > _MAX_TOTAL_BYTES and index < len(dated):
        _, victim, size = dated[index]
        total -= size
        with suppress(OSError):
            victim.unlink()
        index += 1
    return total


def _tag_handler(
    handler: logging.Handler,
    kind: str,
    path: Path,
    reason: str | None = None,
) -> None:
    setattr(handler, _TAG_ATTR, True)
    setattr(handler, _KIND_ATTR, kind)
    setattr(handler, _PATH_ATTR, path)
    if reason is not None:
        setattr(handler, _REASON_ATTR, reason)


def _app_handler(root: logging.Logger | None = None) -> logging.Handler | None:
    root = root if root is not None else logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _TAG_ATTR, False):
            return handler
    return None


def _remove_tagged_handler(handler: logging.Handler, root: logging.Logger) -> None:
    root.removeHandler(handler)
    with suppress(Exception):
        handler.close()


def _install_fallback(
    root: logging.Logger,
    path: Path,
    reason: str,
) -> None:
    fallback = _StderrJSONLHandler()
    _tag_handler(fallback, "stderr", path, reason)
    root.addHandler(fallback)
    with suppress(Exception):
        logging.getLogger(_TELEMETRY_LOGGER).warning(
            "app logging degraded",
            extra={
                "event": "app.logging_degraded",
                "source": "app_logging",
                "reason": reason,
            },
        )


class _StderrJSONLHandler(logging.StreamHandler[TextIO]):
    """Structured JSONL fallback that never raises from ``emit``."""

    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.stream.write(_serialize(record) + "\n")
            self.stream.flush()
        except Exception:
            pass


class _BoundedJSONLHandler(logging.Handler):
    """Secure JSON Lines file handler with bounded retention and recovery.

    Rotates when a new UTC day begins or the active segment exceeds
    ``_SEGMENT_MAX_BYTES``. Archives are named ``app.log.<YYYY-MM-DD>[-<N>]``.
    Pruning removes archives older than 14 days and enforces the 10 MB
    aggregate active-plus-archive cap.
    """

    def __init__(self, log_path: Path) -> None:
        super().__init__(level=_LOG_LEVEL)
        self._log_path = log_path
        self._lock = threading.Lock()
        self._current_date: str = datetime.now(UTC).strftime("%Y-%m-%d")
        self._segment_count: int = 0
        self._disabled: bool = False
        self._stream: io.TextIOBase
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _LoggingFault("log-directory-unavailable") from exc
        try:
            self._stream = log_path.open("a", encoding="utf-8")
        except OSError as exc:
            raise _LoggingFault("log-file-unavailable") from exc
        try:
            _enforce_user_only(log_path)
        except OSError as exc:
            self._close_stream()
            raise _LoggingFault("log-permissions-unavailable") from exc
        try:
            self._enforce_retention()
        except _LoggingFault:
            self._close_stream()
            raise
        except OSError as exc:
            self._close_stream()
            raise _LoggingFault("log-rollover-failed") from exc

    def _close_stream(self) -> None:
        with suppress(OSError):
            self._stream.close()

    def _enforce_retention(self) -> None:
        total = _prune_archives(self._log_path.parent)
        if total <= _MAX_TOTAL_BYTES:
            return
        active_size = self._log_path.stat().st_size if self._log_path.exists() else 0
        if active_size > 0:
            self._do_rollover()
            total = _prune_archives(self._log_path.parent)
        if total > _MAX_TOTAL_BYTES:
            raise _LoggingFault("log-rollover-failed")

    def _rollover_needed(self) -> bool:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._current_date:
            return True
        if not self._log_path.exists():
            return True
        return self._log_path.stat().st_size > _SEGMENT_MAX_BYTES

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
        self._close_stream()
        if self._log_path.exists():
            archive = self._archive_name()
            self._log_path.rename(archive)
            _enforce_user_only(archive)
            self._segment_count += 1
        self._current_date = datetime.now(UTC).strftime("%Y-%m-%d")
        self._stream = self._log_path.open("a", encoding="utf-8")
        _enforce_user_only(self._log_path)

    def _recover_stream(self) -> None:
        self._close_stream()
        self._stream = self._log_path.open("a", encoding="utf-8")
        _enforce_user_only(self._log_path)

    def _degrade(self, reason: str) -> None:
        self._disabled = True
        self._close_stream()
        root = logging.getLogger()
        root.removeHandler(self)
        with suppress(Exception):
            logging.Handler.close(self)
        fallback = _StderrJSONLHandler()
        _tag_handler(fallback, "stderr", self._log_path, reason)
        root.addHandler(fallback)
        with suppress(Exception):
            logging.getLogger(_TELEMETRY_LOGGER).warning(
                "app logging degraded",
                extra={
                    "event": "app.logging_degraded",
                    "source": "app_logging",
                    "reason": reason,
                },
            )

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            if self._disabled:
                return
            reason = "log-write-failed"
            for attempt in range(2):
                try:
                    if self._rollover_needed():
                        self._do_rollover()
                        _prune_archives(self._log_path.parent)
                    self._stream.write(_serialize(record) + "\n")
                    self._stream.flush()
                    return
                except _LoggingFault as exc:
                    reason = exc.reason
                except Exception:
                    reason = "log-write-failed"
                if attempt == 0:
                    try:
                        self._recover_stream()
                    except Exception:
                        self._degrade(reason)
                        return
            self._degrade(reason)

    def close(self) -> None:
        with self._lock:
            self._close_stream()
            super().close()


def configure_logging(log_path: Path | None = None) -> Path:
    """Configure root-logger output and return the intended log path.

    A healthy configuration installs exactly one secure file handler. If the
    secure file handler cannot be established, a structured JSONL stderr
    fallback is installed instead. Same-path calls are idempotent; a different
    path replaces only the tagged application handler and preserves the
    previous handler if the replacement fails.
    """
    path = log_path or app_log_path()
    root = logging.getLogger()
    existing = _app_handler(root)
    if existing is not None and getattr(existing, _PATH_ATTR, None) == path:
        return path
    root.setLevel(_LOG_LEVEL)
    try:
        handler = _BoundedJSONLHandler(path)
    except _LoggingFault as exc:
        if existing is None:
            _install_fallback(root, path, exc.reason)
        return path
    except OSError:
        if existing is None:
            _install_fallback(root, path, "log-file-unavailable")
        return path
    _tag_handler(handler, "file", path)
    if existing is not None:
        _remove_tagged_handler(existing, root)
    root.addHandler(handler)
    logging.getLogger(__name__).info("app logging configured at %s", path)
    return path


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


def install_crash_hooks(
    on_crash: Callable[[], None] | None = None, log_path: Path | None = None
) -> None:
    """Route unhandled exceptions and unraisables into the app log.

    The full traceback is always written as a structured crash event.
    *on_crash*, when given, is then invoked best-effort — the GUI uses it to
    show a modal crash dialog. Previous hooks are preserved and still run.
    Native crash dumps (faulthandler) are written to *log_path* when given
    and openable, else stderr.
    """
    global _fault_file
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

    if log_path is not None:
        try:
            # Kept open for the process lifetime: the faulthandler owns this stream.
            _fault_file = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
            faulthandler.enable(file=_fault_file)
            return
        except OSError:
            pass
    faulthandler.enable()
