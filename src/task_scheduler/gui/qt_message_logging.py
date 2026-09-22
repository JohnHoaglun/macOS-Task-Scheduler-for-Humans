"""Route Qt C++ log messages (qDebug/qWarning/qCritical/qFatal) into the app log.

A class of "silent crash" in Qt apps is a C++-side ``qFatal``/assert, which
aborts the process without raising a Python exception — so it never reaches
``sys.excepthook``. Installing a Qt message handler captures those (and Qt
warnings/criticals) into the same rotating file log. Fatal messages are
logged, the handlers are flushed, and the process is then aborted, mirroring
Qt's default qFatal behavior so the fatal record is durable before the abort.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

__all__ = ["qt_message_level", "install_qt_message_handler"]

_LOGGER = "task_scheduler.qt"
_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def qt_message_level(message_type: QtMsgType) -> int:
    """Map a Qt message type onto a Python logging level (INFO when unknown)."""
    return _LEVELS.get(message_type, logging.INFO)


def _make_handler() -> Callable[[QtMsgType, object, str], None]:
    """Build a Qt message handler that forwards to the app log under *``_LOGGER``*."""
    logger = logging.getLogger(_LOGGER)

    def _handler(message_type: QtMsgType, context: object, message: str) -> None:
        location = getattr(context, "file", None) or getattr(context, "function", None) or "qt"
        logger.log(qt_message_level(message_type), "Qt [%s]: %s", location, message)
        if message_type == QtMsgType.QtFatalMsg:
            for handler in logging.root.handlers:
                handler.flush()
            os.abort()

    return _handler


def install_qt_message_handler() -> Callable[[QtMsgType, object, str], None]:
    """Install the app-log Qt message handler and return it (for testing)."""
    handler = _make_handler()
    qInstallMessageHandler(handler)
    return handler
