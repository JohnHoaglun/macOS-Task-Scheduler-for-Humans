"""Tests for application-level structured JSONL logging and crash capture."""

from __future__ import annotations

import faulthandler
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace, TracebackType

import pytest

from task_scheduler.application import app_logging as al
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
    assert al.app_log_path() == default_job_logs_root() / al.APP_LOG_FILENAME


def test_configure_logging_creates_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    first = al.configure_logging(path)
    handlers = len(logging.getLogger().handlers)
    assert al.configure_logging(path) == first
    assert len(logging.getLogger().handlers) == handlers
    assert path.exists()


def test_ids_are_stable_and_unique() -> None:
    assert al.session_id() == al.session_id() and len(al.session_id()) == 32
    first, second = al.new_operation_id(), al.new_operation_id()
    assert first != second and len(first) == 12


@pytest.mark.parametrize("with_callback", [True, False])
def test_crash_hook_writes_structured_traceback(tmp_path, monkeypatch, with_callback):
    path = tmp_path / "crash.log"
    al.configure_logging(path)
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    shown: list[str] = []
    al.install_crash_hooks(on_crash=lambda: shown.append("dialog") if with_callback else None)
    sys.excepthook(*_exc_and_tb())
    rec = _event(path, "crash.unhandled_exception")
    assert rec["error"]["type"] == "ValueError"
    assert rec["error"]["message"] == "boom"
    assert "Traceback (most recent call last)" in rec["error"]["traceback"]
    assert shown == (["dialog"] if with_callback else [])


def test_crash_hook_callback_failure_does_not_mask_crash(tmp_path, monkeypatch):
    path = tmp_path / "crash.log"
    al.configure_logging(path)

    def broken():
        raise RuntimeError("ui callback failed")

    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    al.install_crash_hooks(on_crash=broken)
    sys.excepthook(*_exc_and_tb())
    assert _event(path, "crash.unhandled_exception")["error"]["type"] == "ValueError"
    assert "crash callback failed" in json.dumps(_read_jsonl(path))


def test_unraisable_hook_writes_structured_log(tmp_path, monkeypatch):
    if not hasattr(sys, "unraisablehook"):
        pytest.skip("sys.unraisablehook unavailable")
    path = tmp_path / "unraisable.log"
    al.configure_logging(path)
    monkeypatch.setattr(sys, "unraisablehook", lambda unraisable: None)
    al.install_crash_hooks()
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
    al._prune_archives(tmp_path)
    assert not old_archive.exists()
    assert directory.is_dir()
    assert invalid.exists()
    assert short.exists()


def test_retention_enforces_size_cap(tmp_path: Path) -> None:
    date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    for i in range(15):
        (tmp_path / f"app.log.{date}-{i + 1:03d}").write_bytes(b"x" * 800_000)
    al._prune_archives(tmp_path)
    remaining = [p for p in tmp_path.iterdir() if p.name.startswith(f"{al.APP_LOG_FILENAME}.")]
    assert sum(p.stat().st_size for p in remaining) <= al._MAX_TOTAL_BYTES


def test_rollover_on_new_day_uses_segment_and_collision_free_names(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text("old\n", encoding="utf-8")
    handler = al._BoundedJSONLHandler(path)
    old_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    handler._current_date = old_date
    handler._segment_count = 1
    (path.parent / f"app.log.{old_date}-2").write_text("x\n", encoding="utf-8")
    handler.emit(_record())
    archives = {p.name for p in path.parent.glob(f"{al.APP_LOG_FILENAME}.*")}
    handler.close()
    assert f"app.log.{old_date}-2-2" in archives
    assert path.exists()


def test_rollover_archive_name_without_segment_count(tmp_path: Path) -> None:
    handler = al._BoundedJSONLHandler(tmp_path / "app.log")
    handler._current_date = "2026-01-02"
    try:
        assert handler._archive_name() == tmp_path / "app.log.2026-01-02"
    finally:
        handler.close()


def test_rollover_needed_when_log_file_is_missing(tmp_path: Path) -> None:
    handler = al._BoundedJSONLHandler(tmp_path / "app.log")
    (tmp_path / "app.log").unlink()
    try:
        assert handler._rollover_needed()
    finally:
        handler.close()


def _tagged_handlers() -> list[logging.Handler]:
    return [
        handler for handler in logging.getLogger().handlers if getattr(handler, al._TAG_ATTR, False)
    ]


def _raise_permission_error(*_args: object, **_kwargs: object) -> None:
    raise PermissionError


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        (al._LoggingFault("log-directory-unavailable"), "log-directory-unavailable"),
        (OSError("open failed"), "log-file-unavailable"),
    ],
)
def test_startup_fault_installs_stderr_fallback(tmp_path, monkeypatch, capfd, fault, expected):
    def broken(_path):
        raise fault

    monkeypatch.setattr(al, "_BoundedJSONLHandler", broken)
    target = tmp_path / "app.log"
    assert al.configure_logging(target) == target
    tagged = _tagged_handlers()
    assert len(tagged) == 1 and getattr(tagged[0], al._KIND_ATTR) == "stderr"
    assert al.logging_degraded_reason() == expected
    lines = [json.loads(line) for line in capfd.readouterr().err.splitlines() if line.strip()]
    assert any(
        rec.get("event") == "app.logging_degraded" and rec.get("reason") == expected
        for rec in lines
    )


def test_failed_replacement_preserves_existing_handler(tmp_path, monkeypatch):
    first = tmp_path / "first.log"
    al.configure_logging(first)

    def broken(_path):
        raise OSError("replacement failed")

    monkeypatch.setattr(al, "_BoundedJSONLHandler", broken)
    second = tmp_path / "second.log"
    assert al.configure_logging(second) == second
    tagged = _tagged_handlers()
    assert len(tagged) == 1 and getattr(tagged[0], al._PATH_ATTR) == first
    assert al.logging_degraded_reason() is None


def test_reconfiguration_replaces_tagged_handler(tmp_path: Path) -> None:
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    al.configure_logging(first)
    assert al.configure_logging(second) == second
    tagged = _tagged_handlers()
    assert len(tagged) == 1 and getattr(tagged[0], al._PATH_ATTR) == second
    assert first.exists() and second.exists() and al.logging_degraded_reason() is None


def test_handler_init_reports_unavailable_log_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(al._LoggingFault) as exc:
        al._BoundedJSONLHandler(blocker / "app.log")
    assert exc.value.reason == "log-directory-unavailable"


def test_handler_init_reports_unavailable_log_file(tmp_path: Path) -> None:
    log_path = tmp_path / "app.log"
    log_path.mkdir()
    with pytest.raises(al._LoggingFault) as exc:
        al._BoundedJSONLHandler(log_path)
    assert exc.value.reason == "log-file-unavailable"


def test_handler_init_reports_permission_fault(tmp_path, monkeypatch):
    monkeypatch.setattr(al.os, "chmod", _raise_permission_error)
    with pytest.raises(al._LoggingFault) as exc:
        al._BoundedJSONLHandler(tmp_path / "app.log")
    assert exc.value.reason == "log-permissions-unavailable"


def test_handler_init_reports_retention_fault(tmp_path, monkeypatch):
    (tmp_path / "app.log").write_text("x", encoding="utf-8")
    monkeypatch.setattr(al, "_prune_archives", lambda _dir: al._MAX_TOTAL_BYTES + 1)
    with pytest.raises(al._LoggingFault) as exc:
        al._BoundedJSONLHandler(tmp_path / "app.log")
    assert exc.value.reason == "log-rollover-failed"


def test_handler_init_reports_retention_oserror(tmp_path, monkeypatch):
    def broken_retention(_self):
        raise OSError("retention failed")

    monkeypatch.setattr(al._BoundedJSONLHandler, "_enforce_retention", broken_retention)
    with pytest.raises(al._LoggingFault) as exc:
        al._BoundedJSONLHandler(tmp_path / "app.log")
    assert exc.value.reason == "log-rollover-failed"


def test_emit_recovers_and_degrades_after_persistent_fault(tmp_path, monkeypatch):
    handler = al._BoundedJSONLHandler(tmp_path / "app.log")
    logging.getLogger().addHandler(handler)

    def broken_fault(_record):
        raise al._LoggingFault("log-rollover-failed")

    monkeypatch.setattr(al, "_serialize", broken_fault)
    handler.emit(_record())
    assert al.logging_degraded_reason() == "log-rollover-failed"
    handler.emit(_record())


def test_emit_degrades_when_stream_recovery_fails(tmp_path, monkeypatch):
    handler = al._BoundedJSONLHandler(tmp_path / "app.log")
    logging.getLogger().addHandler(handler)

    def broken_stream(_record):
        raise RuntimeError("write failed")

    def broken_recovery():
        raise OSError("reopen failed")

    monkeypatch.setattr(al, "_serialize", broken_stream)
    monkeypatch.setattr(handler, "_recover_stream", broken_recovery)
    handler.emit(_record())
    assert al.logging_degraded_reason() == "log-write-failed"


def test_stderr_handler_swallows_write_failure() -> None:
    handler = al._StderrJSONLHandler()

    def broken_write(*_args, **_kwargs):
        raise OSError("stderr failed")

    handler.stream = SimpleNamespace(write=broken_write, flush=lambda: None)
    handler.emit(_record())


def test_enforce_user_only_rejects_unverifiable_permissions(tmp_path, monkeypatch):
    path = tmp_path / "file"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(al.os, "chmod", lambda *_a: None)
    monkeypatch.setattr(al.os, "stat", lambda *_a: SimpleNamespace(st_mode=0o644, st_size=1))
    with pytest.raises(OSError):
        al._enforce_user_only(path)


def test_prune_reports_unreadable_directory(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(al._LoggingFault) as exc:
        al._prune_archives(file)
    assert exc.value.reason == "log-directory-unavailable"


@pytest.mark.parametrize("active_present", [True, False])
def test_prune_reports_permission_fault(tmp_path, monkeypatch, active_present):
    if active_present:
        (tmp_path / al.APP_LOG_FILENAME).write_text("x", encoding="utf-8")
    else:
        date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        (tmp_path / f"app.log.{date}").write_text("x", encoding="utf-8")
    monkeypatch.setattr(al.os, "chmod", _raise_permission_error)
    with pytest.raises(al._LoggingFault) as exc:
        al._prune_archives(tmp_path)
    assert exc.value.reason == "log-permissions-unavailable"


def test_retention_rolls_over_oversized_active_log(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_bytes(b"x" * (al._MAX_TOTAL_BYTES + 1))
    handler = al._BoundedJSONLHandler(path)
    try:
        handler.emit(_record())
    finally:
        handler.close()
    total = sum(p.stat().st_size for p in tmp_path.iterdir() if p.is_file())
    assert total <= al._MAX_TOTAL_BYTES
    assert path.exists()


def test_crash_hooks_register_faulthandler(tmp_path: Path) -> None:
    log = tmp_path / "fault.log"
    try:
        al.install_crash_hooks(log_path=log)
        assert faulthandler.is_enabled()
        assert al._fault_file is not None
        assert al._fault_file.name == str(log)
        al.install_crash_hooks(log_path=tmp_path)  # unopenable: falls back to stderr
    finally:
        faulthandler.disable()
        if al._fault_file is not None:
            al._fault_file.close()
            al._fault_file = None


def test_format_exception_without_value() -> None:
    assert al._format_exception(None, None, None) == "no exception value available"
