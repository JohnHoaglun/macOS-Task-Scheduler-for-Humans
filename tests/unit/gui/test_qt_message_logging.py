"""Tests for routing Qt C++ log messages into the app log."""

from __future__ import annotations

import logging
import os

import pytest
from PySide6.QtCore import QtMsgType

from task_scheduler.gui.qt_message_logging import install_qt_message_handler, qt_message_level


class _FakeContext:
    """Stand-in for ``QMessageLogContext`` (file/function used for the log tag)."""

    def __init__(self, file: str | None = None, function: str | None = None) -> None:
        self.file = file
        self.function = function
        self.line = 0


def test_qt_message_level_maps_known_types() -> None:
    assert qt_message_level(QtMsgType.QtDebugMsg) == logging.DEBUG
    assert qt_message_level(QtMsgType.QtInfoMsg) == logging.INFO
    assert qt_message_level(QtMsgType.QtWarningMsg) == logging.WARNING
    assert qt_message_level(QtMsgType.QtCriticalMsg) == logging.ERROR
    assert qt_message_level(QtMsgType.QtFatalMsg) == logging.CRITICAL


def test_install_qt_message_handler_routes_to_app_log(caplog: pytest.LogCaptureFixture) -> None:
    handler = install_qt_message_handler()
    with caplog.at_level(logging.DEBUG, logger="task_scheduler.qt"):
        handler(QtMsgType.QtDebugMsg, _FakeContext(file="foo.cpp"), "dbg message")
        handler(QtMsgType.QtWarningMsg, _FakeContext(function="doWork"), "warn message")
    assert "Qt [foo.cpp]: dbg message" in caplog.text
    assert "Qt [doWork]: warn message" in caplog.text


def test_install_qt_message_handler_falls_back_to_qt_tag(caplog: pytest.LogCaptureFixture) -> None:
    handler = install_qt_message_handler()
    with caplog.at_level(logging.DEBUG, logger="task_scheduler.qt"):
        handler(QtMsgType.QtInfoMsg, _FakeContext(), "no location")
    assert "Qt [qt]: no location" in caplog.text


def test_fatal_message_is_logged_flushed_then_aborted(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    aborts: list[None] = []
    monkeypatch.setattr(os, "abort", lambda: aborts.append(None))
    handler = install_qt_message_handler()
    with caplog.at_level(logging.CRITICAL, logger="task_scheduler.qt"):
        handler(QtMsgType.QtFatalMsg, _FakeContext(file="fatal.cpp"), "fatal message")
    criticals = [record for record in caplog.records if record.levelno == logging.CRITICAL]
    assert len(criticals) == 1
    assert "Qt [fatal.cpp]: fatal message" in criticals[0].getMessage()
    assert len(aborts) == 1
