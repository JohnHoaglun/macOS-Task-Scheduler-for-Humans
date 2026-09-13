"""Tests for the raw plist editor widget."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from task_scheduler.gui.widgets.raw_plist_editor import RawPlistEditor


def _editor() -> RawPlistEditor:
    return RawPlistEditor()


class TestRawPlistEditor:
    def test_open_binary_mode(self, qtbot: QtBot) -> None:
        e = _editor()
        qtbot.addWidget(e)
        e.open(source_path=Path("com.x.plist"), text="Zm9v", binary_mode=True, label=None)
        assert e._mode_label.text() == "Base64-encoded plist (binary source)"
        assert "base64" in e._banner.text()

    def test_exec_rejected_resets_replacement(self, qtbot: QtBot, monkeypatch) -> None:
        e = _editor()
        qtbot.addWidget(e)
        e.open(source_path=Path("com.x.plist"), text="orig", binary_mode=False, label=None)
        e._on_save()
        assert e.replacement_text() == "orig"
        monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        assert e.exec() == QDialog.DialogCode.Rejected
        assert e.replacement_text() is None
