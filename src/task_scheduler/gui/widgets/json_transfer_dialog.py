"""JsonTransferDialog: preview of a managed-JSON import before commit."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.gui.controllers.json_transfer_controller import JsonImportOutcome

__all__ = ["JsonTransferDialog"]


class JsonTransferDialog(QDialog):
    """Preview of a managed-JSON import with conflict disclosure."""

    def __init__(self, outcome: JsonImportOutcome, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("json-transfer-dialog")
        self._outcome = outcome
        self._import_accepted = False

        self._build_ui()
        self._fill_preview()
        self._handle_conflicts()

    def _build_ui(self) -> None:
        """Construct the label/uuid/schema/conflicts disclosure panes."""
        # Preview details section
        details_box = QGroupBox("Transfer details", self)
        details_box.setObjectName("json-transfer-details")
        details_layout = QVBoxLayout(details_box)

        label_label = QLabel(self)
        label_label.setObjectName("json-transfer-label")
        details_layout.addWidget(label_label)

        uuid_label = QLabel(self)
        uuid_label.setObjectName("json-transfer-uuid")
        details_layout.addWidget(uuid_label)

        schema_label = QLabel(self)
        schema_label.setObjectName("json-transfer-schema")
        details_layout.addWidget(schema_label)

        # Conflicts section
        conflicts_box = QGroupBox("Conflicts", self)
        conflicts_box.setObjectName("json-transfer-conflicts")
        self._conflicts_layout = QVBoxLayout(conflicts_box)

        # Button row
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("json-transfer-cancel")
        self._confirm_button = QPushButton("Import", self)
        self._confirm_button.setObjectName("json-transfer-confirm")
        self._confirm_button.setEnabled(False)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self._cancel_button)
        button_layout.addWidget(self._confirm_button)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(details_box)
        main_layout.addWidget(conflicts_box)
        main_layout.addLayout(button_layout)

        self._cancel_button.clicked.connect(self._on_cancel)
        self._confirm_button.clicked.connect(self._on_confirm)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _fill_preview(self) -> None:
        """Fill the preview fields from the outcome's candidate."""
        job = self._outcome.candidate
        if job is None:
            return

        label_label = self.findChild(QLabel, "json-transfer-label")
        uuid_label = self.findChild(QLabel, "json-transfer-uuid")
        schema_label = self.findChild(QLabel, "json-transfer-schema")

        if label_label is not None:
            label_label.setText(f"Label: {job.label}")
        if uuid_label is not None:
            uuid_label.setText(f"UUID: {job.id}")
        if schema_label is not None:
            schema_label.setText(f"Schema version: {job.schema_version}")

    def _handle_conflicts(self) -> None:
        """Show/hide conflict info and toggle Import button state."""
        if self._outcome.error is not None:
            error_label = QLabel(self._outcome.error, self)
            self._conflicts_layout.addWidget(error_label)
            self._confirm_button.setEnabled(False)
            return

        conflicts = []
        if self._outcome.id_conflict_path is not None:
            path = self._outcome.id_conflict_path
            conflicts.append(f"ID conflict: same UUID at {path}")
        if self._outcome.label_conflict_path is not None:
            path = self._outcome.label_conflict_path
            conflicts.append(f"Label conflict: same label at {path}")

        if conflicts:
            for conflict in conflicts:
                conflict_label = QLabel(conflict, self)
                self._conflicts_layout.addWidget(conflict_label)
            self._confirm_button.setEnabled(False)
        else:
            no_conflicts = QLabel("No conflicts", self)
            self._conflicts_layout.addWidget(no_conflicts)
            self._confirm_button.setEnabled(True)

    def _on_cancel(self) -> None:
        self._import_accepted = False
        self.reject()

    def _on_confirm(self) -> None:
        self._import_accepted = True
        self.accept()

    def is_accepted(self) -> bool:
        """Whether the Import button was pressed (not cancel)."""
        return self._import_accepted

    @classmethod
    def from_outcome(
        cls,
        outcome: JsonImportOutcome,
        parent: QWidget | None = None,
    ) -> JsonTransferDialog:
        """Build the dialog from a :class:`JsonImportOutcome`."""
        return cls(outcome, parent)
