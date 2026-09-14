"""Confirmation gates for universal external LaunchAgent controls.

Replaces the narrow ExternalEditDialog with four distinct gate dialogs
for structured/raw edit, disable/quarantine, remove, and remove-saved-job.
Cancel is the default button everywhere.  Exact wording matches the
pinned-contract strings in PLAN.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "ExternalDisableConfirmDialog",
    "ExternalEditGateDialog",
    "ExternalRemoveConfirmDialog",
    "ExternalReplaceGateDialog",
    "RemoveSavedJobConfirmDialog",
]

_Mode = Literal["structured", "raw"]


class ExternalEditGateDialog(QDialog):
    """Gate A: warns the user before entering the editor.

    Mode selects structured (shows file path and preservation message)
    or raw (explains the raw editor and label requirements).
    """

    def __init__(
        self,
        *,
        mode: _Mode,
        path: str,
        label: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("external-edit-gate-dialog")
        self._accepted = False
        self.setWindowTitle("Edit External LaunchAgent?")

        if mode == "structured":
            body = (
                "This task is managed outside macOS Task Scheduler for Humans.\n\n"
                "Saving will rewrite only the settings you change in this user LaunchAgent plist:\n"
                f"{path}\n\n"
                "Every other setting in the file is preserved unchanged. "
                "The task remains External and is not added to the managed task catalog."
            )
        else:
            label_clause = (
                f"The replacement must keep the same launchd label ({label}).\n\n"
                if label is not None
                else "The replacement must contain a valid launchd label.\n\n"
            )
            body = (
                "This task is managed outside macOS Task Scheduler for Humans, and this app cannot "
                "represent its plist with the normal editor.\n\n"
                f"You will edit the raw plist text. Saving replaces the file:\n{path}\n\n"
                f"{label_clause}"
                "The task remains External and is not added to the managed task catalog."
            )

        message = QLabel(body, self)
        message.setObjectName("external-edit-gate-message")
        message.setWordWrap(True)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("external-edit-gate-cancel")
        self._cancel_button.setDefault(True)
        self._accept_button = QPushButton("Continue to Edit", self)
        self._accept_button.setObjectName("external-edit-gate-accept")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._accept_button.clicked.connect(self._on_accept)

    @classmethod
    def structured(cls, path: str, parent: QWidget | None = None) -> ExternalEditGateDialog:
        return cls(mode="structured", path=path, label=None, parent=parent)

    @classmethod
    def raw(
        cls,
        path: str,
        label: str | None,
        parent: QWidget | None = None,
    ) -> ExternalEditGateDialog:
        return cls(mode="raw", path=path, label=label, parent=parent)

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def _on_cancel(self) -> None:
        self._accepted = False
        self.reject()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()


class ExternalReplaceGateDialog(QDialog):
    """Gate B: confirm the pre-commit replacement.

    Wording adapts to structured / raw mode and the loaded state.
    """

    def __init__(
        self,
        *,
        mode: _Mode,
        path: str,
        loaded: bool | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("external-replace-gate-dialog")
        self._accepted = False
        self.setWindowTitle("Replace External LaunchAgent Plist?")

        loaded_sentence = (
            "The application will reload the LaunchAgent so the change can take effect now."
            if loaded
            else "The LaunchAgent is not currently loaded; no reload is needed."
        )

        if mode == "structured":
            body = (
                f"Replace the settings in {path} with the values you edited?\n\n"
                "Only the changed settings are rewritten; every other setting in the file is "
                "preserved. The task remains External.\n\n"
                f"{loaded_sentence}"
            )
            accept_text = "Replace and Reload" if loaded else "Replace Plist"
        else:
            body = (
                f"Replace {path} with the plist text you supplied?\n\n"
                "The entire file is replaced and normalized to XML before writing. "
                "The task remains External.\n\n"
                f"{loaded_sentence}"
            )
            accept_text = "Replace and Reload" if loaded else "Replace Plist"

        message = QLabel(body, self)
        message.setObjectName("external-replace-gate-message")
        message.setWordWrap(True)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("external-replace-gate-cancel")
        self._cancel_button.setDefault(True)
        self._accept_button = QPushButton(accept_text, self)
        self._accept_button.setObjectName("external-replace-gate-accept")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._accept_button.clicked.connect(self._on_accept)

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def _on_cancel(self) -> None:
        self._accepted = False
        self.reject()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()


class ExternalDisableConfirmDialog(QDialog):
    """Confirm disable (label variant) or quarantine (no-label variant)."""

    def __init__(
        self,
        *,
        label: str | None,
        path: str,
        loaded: bool | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("external-disable-confirm-dialog")
        self._accepted = False

        if label is not None:
            self.setWindowTitle("Disable External LaunchAgent?")
            body = (
                f"Disable {label}?\n\n"
                "This writes Disabled = true into the plist file, so launchd "
                "will not start the agent at login. Because the change is "
                "stored in the plist itself, it stays disabled across restarts "
                "and is visible in the file. If the agent is currently running, "
                "it will be unloaded now. A backup of the current plist is kept "
                "alongside it.\n\n"
                f"{path}"
            )
            accept_text = "Disable"
        else:
            self.setWindowTitle("Disable External LaunchAgent?")
            dest = Path(path).parent / ".task-scheduler-disabled"
            label_text = (
                "This task has no usable launchd label, so it cannot be told "
                "to stop through launchd.\n\n"
                "It will be moved out of your LaunchAgents folder to:\n"
                f"{dest}\n\n"
                "launchd will no longer load it from its original location. "
                "A running instance may stop, but this app cannot verify that "
                "without a usable label."
            )
            body = label_text
            accept_text = "Move and Disable"

        message = QLabel(body, self)
        message.setObjectName("external-disable-message")
        message.setWordWrap(True)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("external-disable-cancel")
        self._cancel_button.setDefault(True)
        self._accept_button = QPushButton(accept_text, self)
        self._accept_button.setObjectName("external-disable-accept")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._accept_button.clicked.connect(self._on_accept)

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def _on_cancel(self) -> None:
        self._accepted = False
        self.reject()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()


class ExternalRemoveConfirmDialog(QDialog):
    """Confirm removal of an external LaunchAgent plist."""

    def __init__(
        self,
        *,
        path: str,
        loaded: bool | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("external-remove-confirm-dialog")
        self._accepted = False
        self.setWindowTitle("Remove External LaunchAgent?")

        loaded_clause = ""
        if loaded is True:
            loaded_clause = "It is currently running; it will be unloaded first.\n\n"

        body = (
            "Permanently remove this plist file?\n\n"
            f"{path}\n\n"
            f"{loaded_clause}"
            "A byte-identical backup is retained as a sibling file in the same folder."
        )

        message = QLabel(body, self)
        message.setObjectName("external-remove-message")
        message.setWordWrap(True)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("external-remove-cancel")
        self._cancel_button.setDefault(True)
        self._accept_button = QPushButton("Remove", self)
        self._accept_button.setObjectName("external-remove-accept")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._accept_button.clicked.connect(self._on_accept)

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def _on_cancel(self) -> None:
        self._accepted = False
        self.reject()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()


class RemoveSavedJobConfirmDialog(QDialog):
    """Confirm removal of a saved (catalog-only) managed job."""

    def __init__(
        self,
        *,
        name: str,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("remove-saved-job-dialog")
        self._accepted = False
        self.setWindowTitle("Remove Saved Task?")

        body = (
            "Remove this task from the managed catalog?\n\n"
            f"{name} ({label}) is saved but not installed. "
            "Removing it deletes the saved definition; no launchd change is made."
        )

        message = QLabel(body, self)
        message.setObjectName("remove-saved-job-message")
        message.setWordWrap(True)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("remove-saved-job-cancel")
        self._cancel_button.setDefault(True)
        self._accept_button = QPushButton("Remove", self)
        self._accept_button.setObjectName("remove-saved-job-accept")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)
        buttons.addWidget(self._accept_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)
        self._cancel_button.clicked.connect(self._on_cancel)
        self._accept_button.clicked.connect(self._on_accept)

    @property
    def is_accepted(self) -> bool:
        return self._accepted

    def _on_cancel(self) -> None:
        self._accepted = False
        self.reject()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()
