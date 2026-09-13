"""Raw plist editor for external LaunchAgent files that cannot be parsed structurally."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["RawPlistEditor"]


class RawPlistEditor(QDialog):
    """Dialog for editing the raw plist text of an external LaunchAgent.

    objectNames: ``raw-plist-editor``, ``raw-plist-banner``, ``raw-plist-mode``,
    ``raw-plist-text``, ``raw-plist-errors``, ``raw-plist-save``, ``raw-plist-cancel``.
    Cancel is the default button. No plist validation lives in the widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("raw-plist-editor")
        self._replacement: str | None = None

        content = QWidget()
        self._banner = QLabel(content)
        self._banner.setObjectName("raw-plist-banner")
        self._banner.setWordWrap(True)
        self._mode_label = QLabel(content)
        self._mode_label.setObjectName("raw-plist-mode")
        self._text_edit = QPlainTextEdit(content)
        self._text_edit.setObjectName("raw-plist-text")
        self._text_edit.setReadOnly(False)
        self._text_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._errors = QLabel(content)
        self._errors.setObjectName("raw-plist-errors")
        self._errors.setWordWrap(True)
        self._errors.hide()
        self._save_button = QPushButton("Save Plist…", self)
        self._save_button.setObjectName("raw-plist-save")
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("raw-plist-cancel")
        self._cancel_button.setDefault(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addWidget(self._mode_label)
        layout.addWidget(self._text_edit)
        layout.addWidget(self._errors)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self.reject)
        self._save_button.clicked.connect(self._on_save)

    def open(  # type: ignore[override]
        self,
        *,
        source_path: Path,
        text: str,
        binary_mode: bool,
        label: str | None,
    ) -> None:
        """Configure the dialog for a source plist file.

        *text* is the UTF-8 decoded content. When *binary_mode* is True,
        the content is actually base64-encoded bytes.
        """
        self.setWindowTitle(f"Edit External Plist — {source_path.name}")
        banner = (
            f"Raw plist editor — the text below is the entire plist. Saving replaces {source_path}."
        )
        if binary_mode:
            banner += (
                " The source is not UTF-8 text; it is shown base64-encoded. "
                "Decoding your replacement must produce a plist dict."
            )
        self._banner.setText(banner)
        if binary_mode:
            self._mode_label.setText("Base64-encoded plist (binary source)")
        else:
            self._mode_label.setText("XML plist text")
        self._text_edit.setPlainText(text)
        self._errors.hide()
        self._replacement = None

    def replacement_text(self) -> str | None:
        """The text the user supplied via the save button, or None if cancelled."""
        return self._replacement

    def _on_save(self) -> None:
        self._replacement = self._text_edit.toPlainText()
        self.accept()

    def exec(self) -> int:
        result = super().exec()
        if result != QDialog.DialogCode.Accepted:
            self._replacement = None
        return result
