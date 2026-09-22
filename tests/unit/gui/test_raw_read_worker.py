"""Tests for the raw plist read worker."""

from __future__ import annotations

import base64
import logging
import plistlib
from pathlib import Path
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

import task_scheduler.gui.controllers.raw_read_worker as raw_read_worker
from task_scheduler.application.external_edit_models import RawPlistRead
from task_scheduler.gui.controllers.raw_read_worker import (
    RAW_READ_FAILED_MESSAGE,
    RawReadWorker,
)

SOURCE = {"Label": "com.example.raw", "ProgramArguments": ["/bin/true"]}


def _run(path: Path) -> RawPlistRead:
    worker = RawReadWorker(path)
    emitted: list[object] = []
    worker.finished.connect(lambda value: emitted.append(value))
    worker.run()
    assert len(emitted) == 1
    return cast(RawPlistRead, emitted[0])


class TestRawReadWorker:
    def test_utf8_source_emits_text_read(self, qtbot: QtBot, tmp_path: Path) -> None:
        path = tmp_path / "agent.plist"
        text = plistlib.dumps(SOURCE, fmt=plistlib.FMT_XML).decode("utf-8")
        path.write_text(text)
        read = _run(path)
        assert read.text == text
        assert read.binary_mode is False
        assert read.error is None

    def test_non_utf8_source_emits_base64_read(self, qtbot: QtBot, tmp_path: Path) -> None:
        path = tmp_path / "agent.plist"
        data = plistlib.dumps(SOURCE, fmt=plistlib.FMT_BINARY)
        path.write_bytes(data)
        read = _run(path)
        assert read.text == base64.b64encode(data).decode("ascii")
        assert read.binary_mode is True
        assert read.error is None

    def test_missing_file_emits_error_read(self, qtbot: QtBot, tmp_path: Path) -> None:
        read = _run(tmp_path / "missing.plist")
        assert read.text is None
        assert read.binary_mode is False
        assert read.error is not None

    def test_unexpected_failure_emits_typed_error(
        self,
        qtbot: QtBot,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        def _raise(_path: Path) -> RawPlistRead:
            raise RuntimeError("boom")

        monkeypatch.setattr(raw_read_worker, "read_raw_plist", _raise)
        with caplog.at_level(
            logging.ERROR, logger="task_scheduler.gui.controllers.raw_read_worker"
        ):
            read = _run(tmp_path / "x.plist")
        assert read.text is None
        assert read.error == RAW_READ_FAILED_MESSAGE
        assert sum(1 for record in caplog.records if record.levelno == logging.ERROR) == 1
