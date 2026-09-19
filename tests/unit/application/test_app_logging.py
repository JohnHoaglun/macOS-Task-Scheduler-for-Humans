"""Tests for application-level structured JSONL logging and crash capture."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace, TracebackType

import pytest

from task_scheduler.application import app_logging
from task_scheduler.application.app_logging import (
    APP_LOG_FILENAME,
    app_log_path,
    configure_logging,
    emit_error,
    emit_event,
    install_crash_hooks,
    new_operation_id,
    session_id,
)
from task_scheduler.application.job_service import default_job_logs_root


@pytest.fixture(autouse=True)
def _isolate_root_handlers():
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
    try:
        raise ValueError("boom")
    except ValueError as exc:
        return type(exc), exc, exc.__traceback__


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _event(path: Path, name: str) -> dict[str, object]:
    matches = [record for record in _read_jsonl(path) if record.get("event") == name]
    assert len(matches) == 1
    return matches[0]


def _record() -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, "m", (), None)


def test_app_log_path_lives_under_default_logs_root() -> None:
    assert app_log_path() == default_job_logs_root() / APP_LOG_FILENAME


def test_configure_logging_creates_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    first = configure_logging(path)
    handlers = len(logging.getLogger().handlers)
    assert configure_logging(path) == first
    assert len(logging.getLogger().handlers) == handlers
    assert path.exists()


def test_configure_logging_uses_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_logging, "app_log_path", lambda: tmp_path / "app.log")
    assert configure_logging() == tmp_path / "app.log"


def test_ids_are_stable_and_unique() -> None:
    assert session_id() == session_id() and len(session_id()) == 32
    first, second = new_operation_id(), new_operation_id()
    assert first != second and len(first) == 12


def test_emit_event_writes_valid_jsonl_with_all_field_kinds(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    configure_logging(path)
    config = {"command": "/bin/echo", "args": ["hi"], "env": {"PATH": "/bin"}}
    emit_event(
        "config.snapshot",
        source="job_editor",
        task_id="com.example.task",
        config=config,
        outcome="success",
        menu="View",
        action="show_filters",
    )
    rec = _event(path, "config.snapshot")
    assert rec["source"] == "job_editor"
    assert rec["task_id"] == "com.example.task"
    assert rec["config"] == config
    assert rec["outcome"] == "success"
    assert rec["menu"] == "View"
    assert rec["action"] == "show_filters"
    assert rec["level"] == "INFO"
    assert "ts" in rec and "seq" in rec


def test_emit_error_includes_exception_details(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    configure_logging(path)
    op = new_operation_id()
    try:
        raise RuntimeError("operation failed")
    except RuntimeError as exc:
        emit_error(
            "operation.lifecycle",
            source="main_window",
            exc=exc,
            op_id=op,
            task_id="com.example.task",
        )
    rec = _event(path, "operation.lifecycle")
    assert rec["level"] == "ERROR"
    assert rec["op_id"] == op
    assert rec["task_id"] == "com.example.task"
    err = rec["error"]
    assert err["type"] == "RuntimeError"
    assert err["message"] == "operation failed"
    assert "Traceback" in err["traceback"]


@pytest.mark.parametrize("with_callback", [True, False])
def test_crash_hook_writes_structured_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_callback: bool
) -> None:
    path = tmp_path / "crash.log"
    configure_logging(path)
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    shown: list[str] = []
    install_crash_hooks(on_crash=lambda: shown.append("dialog") if with_callback else None)
    sys.excepthook(*_exc_and_tb())
    rec = _event(path, "crash.unhandled_exception")
    assert rec["error"]["type"] == "ValueError"
    assert rec["error"]["message"] == "boom"
    assert "Traceback (most recent call last)" in rec["error"]["traceback"]
    assert shown == (["dialog"] if with_callback else [])


def test_crash_hook_callback_failure_does_not_mask_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "crash.log"
    configure_logging(path)

    def broken() -> None:
        raise RuntimeError("ui callback failed")

    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    install_crash_hooks(on_crash=broken)
    sys.excepthook(*_exc_and_tb())
    assert _event(path, "crash.unhandled_exception")["error"]["type"] == "ValueError"
    assert "crash callback failed" in json.dumps(_read_jsonl(path))


def test_unraisable_hook_writes_structured_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(sys, "unraisablehook"):
        pytest.skip("sys.unraisablehook unavailable")
    path = tmp_path / "unraisable.log"
    configure_logging(path)
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: None)
    install_crash_hooks()
    sys.unraisablehook(
        SimpleNamespace(
            err_msg="background failure",
            description="legacy",
            exc_type=ValueError,
            exc_value=ValueError("bg"),
            exc_traceback=None,
        )
    )
    rec = _event(path, "crash.unraisable_exception")
    assert rec["error"]["type"] == "ValueError"
    assert rec["error"]["message"] == "background failure"


def test_retention_prunes_old_archives_and_skips_unusable_entries(tmp_path: Path) -> None:
    old = (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%d")
    old_archive = tmp_path / f"app.log.{old}"
    old_archive.write_text("old\n", encoding="utf-8")
    directory = tmp_path / "app.log.2026-01-01"
    directory.mkdir()
    invalid = tmp_path / "app.log.9999-99-99"
    invalid.write_text("x\n", encoding="utf-8")
    short = tmp_path / "app.log.2026"
    short.write_text("x\n", encoding="utf-8")
    app_logging._prune_archives(tmp_path)
    assert not old_archive.exists()
    assert directory.is_dir()
    assert invalid.exists()
    assert short.exists()


def test_retention_enforces_size_cap(tmp_path: Path) -> None:
    date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    for i in range(15):
        (tmp_path / f"app.log.{date}-{i + 1:03d}").write_bytes(b"x" * 800_000)
    app_logging._prune_archives(tmp_path)
    remaining = [p for p in tmp_path.iterdir() if p.name.startswith(f"{APP_LOG_FILENAME}.")]
    assert sum(p.stat().st_size for p in remaining) <= app_logging._MAX_TOTAL_BYTES


def test_rollover_on_new_day_uses_segment_and_collision_free_names(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text("old\n", encoding="utf-8")
    handler = app_logging._BoundedJSONLHandler(path)
    old_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    handler._current_date = old_date
    handler._segment_count = 1
    (path.parent / f"app.log.{old_date}-2").write_text("x\n", encoding="utf-8")
    handler.emit(_record())
    archives = {p.name for p in path.parent.glob(f"{APP_LOG_FILENAME}.*")}
    handler.close()
    assert f"app.log.{old_date}-2-2" in archives
    assert path.exists()


def test_rollover_archive_name_without_segment_count(tmp_path: Path) -> None:
    handler = app_logging._BoundedJSONLHandler(tmp_path / "app.log")
    handler._current_date = "2026-01-02"
    try:
        assert handler._archive_name() == tmp_path / "app.log.2026-01-02"
    finally:
        handler.close()


def test_rollover_needed_when_log_file_is_missing(tmp_path: Path) -> None:
    handler = app_logging._BoundedJSONLHandler(tmp_path / "app.log")
    (tmp_path / "app.log").unlink()
    try:
        assert handler._rollover_needed()
    finally:
        handler.close()


def test_emit_failure_is_routed_to_handler_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler = app_logging._BoundedJSONLHandler(tmp_path / "app.log")
    monkeypatch.setattr(logging, "raiseExceptions", False)

    def broken(record: logging.LogRecord) -> str:
        raise RuntimeError("write failed")

    monkeypatch.setattr(handler, "_serialize", broken)
    try:
        handler.emit(_record())
    finally:
        handler.close()


def test_log_file_permissions_are_user_only(tmp_path: Path) -> None:
    path = configure_logging(tmp_path / "app.log")
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_sequence_numbers_increase(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    configure_logging(path)
    emit_event("seq.a", source="t")
    emit_event("seq.b", source="t")
    seqs = [
        str(record["seq"])
        for record in _read_jsonl(path)
        if str(record.get("event", "")).startswith("seq.")
    ]
    assert len(set(seqs)) == len(seqs) == 2


def test_format_exception_without_value() -> None:
    assert app_logging._format_exception(None, None, None) == "no exception value available"
