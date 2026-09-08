"""Tests for the json transfer dialog (offscreen Qt)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.gui.controllers.json_transfer_controller import JsonImportOutcome
from task_scheduler.gui.widgets.json_transfer_dialog import JsonTransferDialog


def _dlg(
    qtbot,
    *,
    candidate=None,
    error=None,
    id_conflict=None,
    label_conflict=None,
):
    if candidate is None and error is None:
        candidate = make_job(label="com.example.test")
    outcome = JsonImportOutcome(
        source_path=Path("/tmp/transfer.json"),
        candidate=candidate,
        label=candidate.label if candidate is not None else None,
        uuid=str(candidate.id) if candidate is not None else None,
        normalized_schema_version=candidate.schema_version if candidate is not None else None,
        id_conflict_path=id_conflict,
        label_conflict_path=label_conflict,
        can_import=id_conflict is None and label_conflict is None,
        error=error,
        _preview=None,
    )
    dlg = JsonTransferDialog.from_outcome(outcome)
    if qtbot is not None:
        qtbot.addWidget(dlg)
        dlg.show()
    return dlg


class TestObjectNames:
    def test_all_names(self, qtbot: QtBot) -> None:
        dlg = _dlg(qtbot)
        assert dlg.objectName() == "json-transfer-dialog"
        for name in ("json-transfer-details", "json-transfer-conflicts",
                     "json-transfer-confirm", "json-transfer-cancel"):
            assert dlg.findChild(object, name) is not None


class TestPreview:
    def test_display_and_enable(self, qtbot: QtBot) -> None:
        job = make_job(label="com.example.special", id=make_job().id)
        dlg = _dlg(qtbot, candidate=job)
        assert "com.example.special" in dlg.findChild(QLabel, "json-transfer-label").text()
        assert str(job.id) in dlg.findChild(QLabel, "json-transfer-uuid").text()
        assert "2" in dlg.findChild(QLabel, "json-transfer-schema").text()
        assert dlg.findChild(QPushButton, "json-transfer-confirm").isEnabled()

    @pytest.mark.parametrize("kwarg", [
        ("id_conflict", "ID conflict"),
        ("label_conflict", "Label conflict"),
    ])
    def test_conflicts_disabled(self, kwarg: tuple[str, str]) -> None:
        dlg = _dlg(None, **{kwarg[0]: Path("/tmp/other.json")})
        assert not dlg.findChild(QPushButton, "json-transfer-confirm").isEnabled()

    def test_conflict_messages(self, qtbot: QtBot) -> None:
        dlg = _dlg(qtbot, id_conflict=Path("/tmp/other.json"),
                   label_conflict=Path("/tmp/other.json"))
        labels = dlg.findChild(object, "json-transfer-conflicts").findChildren(QLabel)
        texts = [t.text() for t in labels]
        assert any("ID conflict" in t and "/tmp/other.json" in t for t in texts)
        assert any("Label conflict" in t and "/tmp/other.json" in t for t in texts)
    def test_cancel_not_accepted(self, qtbot: QtBot) -> None:
        dlg = _dlg(qtbot)
        dlg.findChild(QPushButton, "json-transfer-cancel").click()
        assert dlg.result() == 0 and not dlg.is_accepted()
    def test_confirm_accepted(self, qtbot: QtBot) -> None:
        dlg = _dlg(qtbot)
        dlg.findChild(QPushButton, "json-transfer-confirm").click()
        assert dlg.result() == 1 and dlg.is_accepted()
    def test_no_candidate_labels_when_error(self, qtbot: QtBot) -> None:
        assert _dlg(qtbot, candidate=None, error="x").findChild(
            QLabel, "json-transfer-label",
        ).text() == ""
