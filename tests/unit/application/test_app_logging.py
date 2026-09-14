"""Tests for application-level file logging and crash capture."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType

import pytest

from task_scheduler.application import app_logging
from task_scheduler.application.app_logging import (
    APP_LOG_FILENAME,
    app_log_path,
    configure_logging,
    install_crash_hooks,
)
from task_scheduler.application.job_service import default_job_logs_root


@pytest.fixture(autouse=True)
def _isolate_root_handlers():
    """Remove any app file handlers and restore the root level after each test."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(original_level)


def _exc_and_tb() -> tuple[type[BaseException], BaseException, TracebackType | None]:
    """Build a real (type, value, traceback) triple for the crash hook."""
    try:
        raise ValueError("boom")
    except ValueError as exc:
        return type(exc), exc, exc.__traceback__


class _Unraisable:
    """A minimal stand-in for the object ``sys.unraisablehook`` receives."""

    def __init__(self) -> None:
        self.err_msg = "background failure"
        self.description = "legacy description"
        self.exc_type = ValueError
        self.exc_value = ValueError("bg boom")
        self.exc_traceback = None


def test_app_log_path_lives_under_default_logs_root() -> None:
    assert app_log_path() == default_job_logs_root() / APP_LOG_FILENAME


def test_configure_logging_creates_file_and_returns_path(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "app.log"
    assert configure_logging(log_path) == log_path
    assert log_path.exists()


def test_configure_logging_uses_default_path_when_not_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_logging, "app_log_path", lambda: tmp_path / "app.log")
    assert configure_logging() == tmp_path / "app.log"
    assert (tmp_path / "app.log").exists()


def test_configure_logging_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_logging, "app_log_path", lambda: tmp_path / "app.log")
    first = configure_logging()
    handlers_after_first = len(logging.getLogger().handlers)
    second = configure_logging()
    assert second == first
    assert len(logging.getLogger().handlers) == handlers_after_first


def test_format_exception_handles_missing_value() -> None:
    assert app_logging._format_exception(None, None, None) == "no exception value available"


def test_crash_hook_writes_traceback_and_invokes_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "crash.log"
    configure_logging(log_path)
    monkeypatch.setattr(app_logging, "app_log_path", lambda: log_path)
    # Chain to a benign default so we don't trip pytest-qt's excepthook handler.
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    shown: list[str] = []
    install_crash_hooks(on_crash=lambda: shown.append("dialog"))
    sys.excepthook(*_exc_and_tb())

    assert shown == ["dialog"]
    text = log_path.read_text(encoding="utf-8")
    assert "unhandled exception" in text
    assert "ValueError: boom" in text
    assert "Traceback (most recent call last)" in text


def test_crash_hook_without_callback_still_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "crash.log"
    configure_logging(log_path)
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    install_crash_hooks()
    sys.excepthook(*_exc_and_tb())

    text = log_path.read_text(encoding="utf-8")
    assert "unhandled exception" in text
    assert "ValueError: boom" in text


def test_crash_hook_callback_failure_does_not_mask_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "crash.log"
    configure_logging(log_path)

    def _broken_callback() -> None:
        raise RuntimeError("ui callback failed")

    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    install_crash_hooks(on_crash=_broken_callback)
    sys.excepthook(*_exc_and_tb())  # must not raise out of the hook

    text = log_path.read_text(encoding="utf-8")
    assert "unhandled exception" in text
    assert "crash callback failed" in text
    assert "ui callback failed" in text


def test_unraisable_hook_writes_to_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(sys, "unraisablehook"):
        pytest.skip("sys.unraisablehook unavailable")
    log_path = tmp_path / "unraisable.log"
    configure_logging(log_path)
    monkeypatch.setattr(app_logging, "app_log_path", lambda: log_path)
    # Chain to a benign default so we don't feed pytest's unraisable tracker.
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: None)
    install_crash_hooks()
    sys.unraisablehook(_Unraisable())

    text = log_path.read_text(encoding="utf-8")
    assert "unraisable exception" in text
    # ``err_msg`` (the 3.12+ attribute) wins over the legacy ``description``.
    assert "background failure" in text
    assert "legacy description" not in text
    assert "bg boom" in text
