"""Tests for pure modal-dialog sizing."""

from PySide6.QtCore import QSize

from task_scheduler.gui.dialog_sizing import bounded_preferred_size


def test_bounded_preferred_size_keeps_unknown_and_clamps_known_space() -> None:
    preferred = QSize(760, 840)

    assert bounded_preferred_size(preferred, None) == preferred
    assert bounded_preferred_size(preferred, QSize(700, 900)) == QSize(700, 840)
