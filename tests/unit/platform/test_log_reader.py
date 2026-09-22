"""Unit tests for the local log reader adapter (Increment 8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from task_scheduler.platform.macos import LocalLogReader
from task_scheduler.platform.macos.log_reader import LOG_TAIL_BYTES


def _reader() -> LocalLogReader:
    return LocalLogReader()


def test_invalid_utf8_reports_read_error(tmp_path: Path) -> None:
    log = tmp_path / "binary.log"
    log.write_bytes(b"\xff\xfe\x00garbage")
    result = _reader().read(log)
    assert result.content is None
    assert result.error is not None
    assert result.error.startswith("could not read log file ")
    assert str(log) in result.error


def test_missing_file_reports_not_found(tmp_path: Path) -> None:
    log = tmp_path / "missing.log"
    result = _reader().read(log)
    assert result.error == f"log file not found: {log}"
    assert result.content is None
    assert result.truncated is False
    assert result.total_bytes is None


def test_stat_oserror_reports_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "job.log"
    log.write_bytes(b"x")

    def _denied(_path: Path) -> object:
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(Path, "stat", _denied)
    result = _reader().read(log)
    assert result.content is None
    assert result.error is not None
    assert result.error.startswith("could not read log file ")
    assert str(log) in result.error


def test_small_file_reads_in_full(tmp_path: Path) -> None:
    log = tmp_path / "small.log"
    log.write_bytes(b"a\nb\n")
    result = _reader().read(log)
    assert result.content == "a\nb\n"
    assert result.error is None
    assert result.truncated is False
    assert result.total_bytes == 4


def test_file_at_cap_is_not_truncated(tmp_path: Path) -> None:
    log = tmp_path / "cap.log"
    log.write_bytes(b"x" * LOG_TAIL_BYTES)
    result = _reader().read(log)
    assert result.content == "x" * LOG_TAIL_BYTES
    assert result.truncated is False
    assert result.total_bytes == LOG_TAIL_BYTES


def test_file_over_cap_returns_tail_from_first_newline(tmp_path: Path) -> None:
    log = tmp_path / "big.log"
    head = b"0123456789\n"
    tail = b"t" * (LOG_TAIL_BYTES - 7) + b"\n"
    log.write_bytes(head + tail)
    result = _reader().read(log)
    assert result.content == tail.decode()
    assert result.truncated is True
    assert result.total_bytes == LOG_TAIL_BYTES + 5


def test_file_over_cap_without_newline_keeps_full_tail(tmp_path: Path) -> None:
    log = tmp_path / "blob.log"
    log.write_bytes(b"partial" + b"y" * (LOG_TAIL_BYTES + 2))
    result = _reader().read(log)
    assert result.content == "y" * LOG_TAIL_BYTES
    assert result.truncated is True
    assert result.total_bytes == LOG_TAIL_BYTES + 9


def test_tail_open_oserror_reports_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "big.log"
    log.write_bytes(b"y" * (LOG_TAIL_BYTES + 1))

    def _denied(*_args: object, **_kwargs: object) -> object:
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(Path, "open", _denied)
    result = _reader().read(log)
    assert result.content is None
    assert result.error is not None
    assert result.error.startswith("could not read log file ")
