"""Tests for routing Qt C++ log messages into the app log."""

from __future__ import annotations

import logging

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


def test_qt_message_level_unknown_defaults_to_info() -> None:
    # An out-of-range value that is not one of the known Qt message types.
    assert qt_message_level(12345) == logging.INFO  # type: ignore[arg-type]


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
