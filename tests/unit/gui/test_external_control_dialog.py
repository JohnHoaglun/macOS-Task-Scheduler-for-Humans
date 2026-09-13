"""Accept/cancel handler coverage for the universal external-control dialogs.

The main-window tests drive these dialogs through a mocked ``exec()``, so the
Cancel/Accept button handlers (``_on_cancel``/``_on_accept``) are never reached.
These tests exercise both handlers on each gate dialog.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.external_control_dialog import (
    ExternalDisableConfirmDialog,
    ExternalEditGateDialog,
    ExternalRemoveConfirmDialog,
    ExternalReplaceGateDialog,
    RemoveSavedJobConfirmDialog,
)


def _both_handlers(dialog: QDialog) -> None:
    dialog._on_cancel()
    assert dialog.is_accepted is False
    dialog._on_accept()
    assert dialog.is_accepted is True


def test_edit_gate_raw_no_label(qtbot: QtBot) -> None:
    d = ExternalEditGateDialog.raw("/tmp/a.plist", None)
    qtbot.addWidget(d)
    _both_handlers(d)


def test_replace_gate_raw_unloaded(qtbot: QtBot) -> None:
    d = ExternalReplaceGateDialog(mode="raw", path="/tmp/a.plist", loaded=False)
    qtbot.addWidget(d)
    _both_handlers(d)


def test_disable_quarantine_variant(qtbot: QtBot) -> None:
    d = ExternalDisableConfirmDialog(label=None, path="/tmp/a.plist", loaded=False)
    qtbot.addWidget(d)
    _both_handlers(d)


def test_remove_confirm(qtbot: QtBot) -> None:
    d = ExternalRemoveConfirmDialog(path="/tmp/a.plist", loaded=True)
    qtbot.addWidget(d)
    _both_handlers(d)


def test_remove_saved_job(qtbot: QtBot) -> None:
    d = RemoveSavedJobConfirmDialog(name="My Task", label="com.x.y")
    qtbot.addWidget(d)
    _both_handlers(d)
