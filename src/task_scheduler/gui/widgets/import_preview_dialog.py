"""Import preview dialog showing the normalised candidate job before commit."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.domain import JobDefinition, command_argv
from task_scheduler.gui.controllers.import_controller import ImportOutcome
from task_scheduler.gui.presenters.agent_presenter import format_schedule_value

__all__ = ["ImportPreviewDialog"]


class ImportPreviewDialog(QDialog):
    """Preview of an external-plist import, with warning/unsupported disclosure."""

    def __init__(self, outcome: ImportOutcome, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("import-preview-dialog")
        self._outcome = outcome
        self._import_accepted = False

        self._build_ui()
        self._fill_preview()
        self._handle_acknowledgement()

    def _build_ui(self) -> None:
        """Construct the label/command/schedule/environment + warning/unsupported panes."""
        # Preview details section
        details_box = QGroupBox("Import details", self)
        details_box.setObjectName("import-preview-details")
        details_layout = QVBoxLayout(details_box)

        name_label = QLabel(self)
        name_label.setObjectName("import-name")
        details_layout.addWidget(name_label)

        label_label = QLabel(self)
        label_label.setObjectName("import-label")
        details_layout.addWidget(label_label)

        command_label = QLabel(self)
        command_label.setObjectName("import-command")
        details_layout.addWidget(command_label)

        schedule_label = QLabel(self)
        schedule_label.setObjectName("import-schedule")
        details_layout.addWidget(schedule_label)

        env_label = QLabel(self)
        env_label.setObjectName("import-environment")
        env_label.setWordWrap(True)
        details_layout.addWidget(env_label)

        # Warnings section
        warnings_box = QGroupBox("Warnings", self)
        warnings_box.setObjectName("import-warnings")
        self._warnings_list = QListWidget(warnings_box)
        self._warnings_list.setObjectName("import-warnings-list")
        warnings_layout = QVBoxLayout(warnings_box)
        warnings_layout.addWidget(self._warnings_list)

        # Unsupported keys section
        unsupported_box = QGroupBox("Unsupported keys", self)
        unsupported_box.setObjectName("import-unsupported")
        self._unsupported_list = QListWidget(unsupported_box)
        self._unsupported_list.setObjectName("import-unsupported-list")
        unsupported_layout = QVBoxLayout(unsupported_box)
        unsupported_layout.addWidget(self._unsupported_list)

        # Acknowledge section (populated conditionally)
        self._acknowledge_box = QGroupBox(self)
        self._acknowledge_box.setObjectName("import-acknowledge-group")
        acknowledge_layout = QVBoxLayout(self._acknowledge_box)
        self._acknowledge_check = QCheckBox(self)
        self._acknowledge_check.setObjectName("import-acknowledge")
        acknowledge_layout.addWidget(self._acknowledge_check)
        self._acknowledge_box.hide()

        # Button row
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setObjectName("import-cancel")
        self._confirm_button = QPushButton("Import", self)
        self._confirm_button.setObjectName("import-confirm")
        self._confirm_button.setEnabled(False)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self._cancel_button)
        button_layout.addWidget(self._confirm_button)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(details_box)
        main_layout.addWidget(warnings_box)
        main_layout.addWidget(unsupported_box)
        main_layout.addWidget(self._acknowledge_box)
        main_layout.addLayout(button_layout)

        self._cancel_button.clicked.connect(self._on_cancel)
        self._confirm_button.clicked.connect(self._on_confirm)
        self._acknowledge_check.toggled.connect(self._on_ack_toggled)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _format_schedule(self, job: JobDefinition) -> str:
        """Format the job's schedule for display via the shared schedule presenter."""
        return format_schedule_value(job.schedule)

    def _fill_preview(self) -> None:
        """Fill the preview fields from the outcome's candidate."""
        job = self._outcome.candidate
        if job is None:
            return

        name_label = self.findChild(QLabel, "import-name")
        label_label = self.findChild(QLabel, "import-label")
        command_label = self.findChild(QLabel, "import-command")
        schedule_label = self.findChild(QLabel, "import-schedule")
        env_label = self.findChild(QLabel, "import-environment")

        if name_label is not None:
            name_label.setText(job.name)
        if label_label is not None:
            label_label.setText(job.label)
        if command_label is not None:
            command_label.setText(
                " ".join(command_argv(job.command))
            )
        if schedule_label is not None:
            schedule_label.setText(
                self._format_schedule(job)
            )
        if env_label is not None:
            pairs = ", ".join(f"{k}={v}" for k, v in job.environment.variables.items())
            env_label.setText(
                pairs if pairs else "none configured"
            )

        # Warnings
        for warning in self._outcome.warnings:
            QListWidgetItem(warning, self._warnings_list)

        # Unsupported keys
        for key in self._outcome.unsupported_keys:
            QListWidgetItem(key, self._unsupported_list)

    def _handle_acknowledgement(self) -> None:
        """Show/hide the acknowledge checkbox and toggle Import button state."""
        if not self._outcome.requires_acknowledgement:
            self._acknowledge_box.hide()
            self._confirm_button.setEnabled(True)
        else:
            self._acknowledge_box.show()
            self._acknowledge_check.setChecked(False)
            self._confirm_button.setEnabled(False)

    def _on_ack_toggled(self, checked: bool) -> None:
        self._confirm_button.setEnabled(checked)

    def _on_cancel(self) -> None:
        self._import_accepted = False
        self.reject()

    def _on_confirm(self) -> None:
        self._import_accepted = True
        self.accept()

    def is_accepted(self) -> bool:
        """Whether the Import button was pressed (not cancel)."""
        return self._import_accepted
