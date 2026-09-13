"""Tests for the import preview dialog (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QListWidget, QPushButton
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application import ExternalPlistImportPreview
from task_scheduler.gui.controllers.import_controller import ImportOutcome
from task_scheduler.gui.widgets.import_preview_dialog import ImportPreviewDialog


def _preview_outcome(
    qtbot: QtBot,
    *,
    requires_ack: bool = False,
    warnings: tuple[str, ...] = (),
    unsupported_keys: tuple[str, ...] = (),
) -> ImportPreviewDialog:
    job = make_job(label="com.example.test", name="Test Job")
    preview = ExternalPlistImportPreview(
        source_path=Path("/tmp/test.plist"),
        candidate=job,
        warnings=warnings,
        unsupported_keys=unsupported_keys,
        requires_acknowledgement=requires_ack,
    )
    outcome = ImportOutcome(
        source_path=Path("/tmp/test.plist"),
        candidate=preview.candidate,
        warnings=preview.warnings,
        unsupported_keys=preview.unsupported_keys,
        requires_acknowledgement=preview.requires_acknowledgement,
    )
    dialog = ImportPreviewDialog(outcome)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


class TestPartialPreview:
    def test_import_enabled_after_check(self, qtbot: QtBot) -> None:
        dialog = _preview_outcome(qtbot, requires_ack=True)
        ack = dialog.findChild(QCheckBox, "import-acknowledge")
        confirm = dialog.findChild(QPushButton, "import-confirm")
        ack.setChecked(True)
        assert confirm.isEnabled()


class TestWarningRendering:
    def test_warnings_list_populated(self, qtbot: QtBot) -> None:
        dialog = _preview_outcome(
            qtbot,
            warnings=("warning one", "warning two"),
            unsupported_keys=("keyX",),
        )
        wlist = dialog.findChild(QListWidget, "import-warnings-list")
        assert wlist is not None
        assert wlist.count() == 2
        assert wlist.item(0).text() == "warning one"


class TestCancel:
    def test_cancel_returns_not_accepted(self, qtbot: QtBot) -> None:
        dialog = _preview_outcome(qtbot)
        dialog.findChild(QPushButton, "import-cancel").click()
        assert dialog.result() == 0  # QDialog.Rejected
        assert dialog.is_accepted() is False


class TestConfirm:
    def test_confirm_returns_accepted(self, qtbot: QtBot) -> None:
        dialog = _preview_outcome(qtbot)
        dialog.findChild(QPushButton, "import-confirm").click()
        assert dialog.result() == 1  # QDialog.Accepted
        assert dialog.is_accepted() is True


class TestErrorOutcome:
    def test_error_outcome_constructs_without_candidate(self, qtbot: QtBot) -> None:
        outcome = ImportOutcome(
            source_path=Path("/tmp/bad.plist"),
            candidate=None,
            error="not representable",
        )
        dialog = ImportPreviewDialog(outcome)
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.is_accepted() is False
