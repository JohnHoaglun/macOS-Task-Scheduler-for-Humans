"""Application-level file logging and crash capture for diagnostics.

The app previously wrote no log of its own, so an unhandled exception in the
GUI (or CLI) printed a traceback to stderr — which a macOS GUI app discards —
and exited with nothing to inspect. This module gives the app a rotating debug
log under the user's standard Logs directory and routes every unhandled
exception (plus background "unraisable" failures) into it, so crashes leave a
trace.
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from task_scheduler.application.job_service import default_job_logs_root

__all__ = [
    "APP_LOG_FILENAME",
    "app_log_path",
    "configure_logging",
    "install_crash_hooks",
]

APP_LOG_FILENAME = "app.log"
_LOG_LEVEL = logging.DEBUG
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_HANDLER_ATTR = "_tss_app_file_handler"
_CRASH_LOGGER = "task_scheduler.crash"


def app_log_path() -> Path:
    """Return the application debug-log path (under the user's Logs directory)."""
    return default_job_logs_root() / APP_LOG_FILENAME


def _file_handler(log_path: Path) -> RotatingFileHandler:
    """A size-rotating file handler at debug level, tagged so we stay idempotent."""
    handler = RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setLevel(_LOG_LEVEL)
    handler.setFormatter(logging.Formatter(_FORMAT))
    setattr(handler, _HANDLER_ATTR, True)
    return handler


def configure_logging(log_path: Path | None = None) -> Path:
    """Configure root-logger file output (idempotent) and return the log path.

    Creates the log directory and a single rotating file handler at DEBUG level
    so the app's own activity and crashes are captured for diagnosis. Calling
    it again adds no further handlers.
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

    The full traceback is always written first. *on_crash*, when given, is then
    invoked best-effort — the GUI uses it to show a modal crash dialog. The
    previous hooks are preserved and still run, so standard reporting and exit
    behaviour are unchanged.
    """
    crash_logger = logging.getLogger(_CRASH_LOGGER)
    default_hook = sys.excepthook

    def _excepthook(
        exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
    ) -> None:
        crash_logger.error(
            "unhandled exception:\n%s", _format_exception(exc_type, exc_value, exc_tb)
        )
        if on_crash is not None:
            try:
                on_crash()
            except Exception:  # noqa: BLE001 - a failing UI hook must not mask the crash
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
                "unraisable exception (%s):\n%s",
                message,
                _format_exception(
                    unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback
                ),
            )
            default_unraisable(unraisable)

        sys.unraisablehook = _unraisablehook
