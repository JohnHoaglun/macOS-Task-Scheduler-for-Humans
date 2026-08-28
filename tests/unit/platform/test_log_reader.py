"""Unit tests for the local log reader adapter (Increment 8)."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.platform.macos import LocalLogReader


def test_reads_full_utf8_content(tmp_path: Path) -> None:
    log = tmp_path / "out.log"
    log.write_text("line one\nline two\n", encoding="utf-8")
    result = LocalLogReader().read(log)
    assert result.content == "line one\nline two\n"
    assert result.error is None


def test_missing_file_reports_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.log"
    result = LocalLogReader().read(missing)
    assert result.content is None
    assert result.error == f"log file not found: {missing}"


def test_invalid_utf8_reports_read_error(tmp_path: Path) -> None:
    log = tmp_path / "binary.log"
    log.write_bytes(b"\xff\xfe\x00garbage")
    result = LocalLogReader().read(log)
    assert result.content is None
    assert result.error is not None
    assert result.error.startswith("could not read log file ")
    assert str(log) in result.error
