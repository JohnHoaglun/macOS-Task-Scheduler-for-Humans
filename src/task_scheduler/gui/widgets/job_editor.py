"""Dialog for creating or editing a managed job through the editor controller."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.editor_controller import (
    CommandKind,
    EditorController,
    EditorOutcome,
    JobDraft,
)
from task_scheduler.gui.widgets.row_table import RowTable

__all__ = ["JobEditor"]


class JobEditor(QDialog):
    """Form dialog bound to an EditorController draft; Save and Close are the only exits."""

    def __init__(self, controller: EditorController, parent: QWidget | None = None) -> None:
        """Build the scrollable form, hidden error pane, and the action button row."""
        super().__init__(parent)
        self._controller = controller
        self._draft: JobDraft | None = None
        self._saved_path: Path | None = None
        self._saved_label: str | None = None
        self._working_dir_hint: Path | None = None
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self._build_identity())
        content_layout.addWidget(self._build_command())
        content_layout.addWidget(self._build_schedule())
        content_layout.addWidget(self._build_environment())
        content_layout.addWidget(self._build_advanced())
        content_layout.addWidget(self._build_preview())
        self._scroll = QScrollArea(self)
        self._scroll.setWidget(content)
        self._scroll.setWidgetResizable(True)
        self._errors = QPlainTextEdit(self)
        self._errors.setObjectName("editor-errors")
        self._errors.setReadOnly(True)
        self._errors.hide()
        validate_button = QPushButton("Validate", self)
        validate_button.setObjectName("editor-validate")
        preview_button = QPushButton("Preview", self)
        preview_button.setObjectName("editor-preview")
        self._save_button = QPushButton("Save", self)
        self._save_button.setObjectName("editor-save")
        close_button = QPushButton("Close", self)
        close_button.setObjectName("editor-close")
        buttons = QHBoxLayout()
        for b in (validate_button, preview_button, self._save_button, close_button):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addWidget(self._scroll)
        layout.addWidget(self._errors)
        layout.addLayout(buttons)
        close_button.clicked.connect(self.reject)
        self._name.textEdited.connect(self._on_draft_changed)
        self._label.textEdited.connect(self._on_label_edited)
        self._time.textEdited.connect(self._on_draft_changed)
        self._script.textEdited.connect(self._on_draft_changed)
        self._script.textChanged.connect(self._on_script_changed)
        self._use_candidate.clicked.connect(self._on_use_candidate)
        for checkbox in self._weekdays:
            checkbox.toggled.connect(self._on_draft_changed)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self._python_args.rowsChanged.connect(self._on_draft_changed)
        self._shell_args.rowsChanged.connect(self._on_draft_changed)
        self._executable_args.rowsChanged.connect(self._on_draft_changed)
        self._environment.rowsChanged.connect(self._on_draft_changed)
        validate_button.clicked.connect(self._on_validate)
        preview_button.clicked.connect(self._on_preview)
        self._save_button.clicked.connect(self._on_save)

    def _build_identity(self) -> QGroupBox:
        """The Identity group: editable name and label fields."""
        group = QGroupBox("Identity")
        self._name = QLineEdit(group)
        self._name.setObjectName("editor-name")
        self._label = QLineEdit(group)
        self._label.setObjectName("editor-label")
        form = QFormLayout(group)
        form.addRow("Name", self._name)
        form.addRow("Label", self._label)
        return group

    def _build_command(self) -> QGroupBox:
        """The Command group: kind selector with a page per command kind."""
        group = QGroupBox("Command")
        form = QFormLayout(group)
        self._kind_combo = QComboBox(group)
        self._kind_combo.setObjectName("editor-command-kind")
        self._kind_combo.addItem("Python")
        self._kind_combo.addItem("Shell")
        self._kind_combo.addItem("Executable")
        form.addRow("Command type", self._kind_combo)
        self._stack = QStackedWidget(group)
        self._stack.setObjectName("editor-command-stack")
        python_page = QWidget(self._stack)
        python_form = QFormLayout(python_page)
        self._interpreter, interpreter_row = self._path_row(
            "editor-interpreter", "editor-interpreter-browse", "open"
        )
        python_form.addRow("Interpreter", interpreter_row)
        self._script, script_row = self._path_row("editor-script", "editor-script-browse", "open")
        python_form.addRow("Script", script_row)
        self._python_args = RowTable(1, python_page)
        self._python_args.setObjectName("editor-python-arguments")
        python_form.addRow("Arguments", self._python_args)
        detection_row = QWidget(python_page)
        detection_layout = QHBoxLayout(detection_row)
        detection_layout.setContentsMargins(0, 0, 0, 0)
        self._candidates = QComboBox(detection_row)
        self._candidates.setObjectName("editor-candidates")
        self._use_candidate = QPushButton("Use", detection_row)
        self._use_candidate.setObjectName("editor-use-candidate")
        self._use_candidate.setEnabled(False)
        detection_layout.addWidget(QLabel("Detected interpreters:"))
        detection_layout.addWidget(self._candidates)
        detection_layout.addWidget(self._use_candidate)
        python_form.addRow(detection_row)
        self._detection_note = QLabel(python_page)
        self._detection_note.setObjectName("editor-detection-note")
        self._detection_note.setWordWrap(True)
        self._detection_note.setText("Select a script to detect its interpreter.")
        python_form.addRow(self._detection_note)
        self._stack.addWidget(python_page)
        shell_page = QWidget(self._stack)
        shell_form = QFormLayout(shell_page)
        self._shell_executable, shell_executable_row = self._path_row(
            "editor-shell-executable", "editor-shell-executable-browse", "open"
        )
        shell_form.addRow("Executable", shell_executable_row)
        self._shell_args = RowTable(1, shell_page)
        self._shell_args.setObjectName("editor-shell-arguments")
        shell_form.addRow("Arguments", self._shell_args)
        self._stack.addWidget(shell_page)
        executable_page = QWidget(self._stack)
        executable_form = QFormLayout(executable_page)
        self._executable, executable_row = self._path_row(
            "editor-executable", "editor-executable-browse", "open"
        )
        executable_form.addRow("Executable", executable_row)
        self._executable_args = RowTable(1, executable_page)
        self._executable_args.setObjectName("editor-executable-arguments")
        executable_form.addRow("Arguments", self._executable_args)
        self._stack.addWidget(executable_page)
        form.addRow("", self._stack)
        return group

    def _on_kind_changed(self, index: int) -> None:
        """Switch the command page when the kind selection changes."""
        self._stack.setCurrentIndex(index)

    def _on_script_changed(self, text: str) -> None:
        """Detect interpreter candidates for the current script path."""
        text = text.strip()
        if not text:
            self._candidates.clear()
            self._use_candidate.setEnabled(False)
            self._working_dir_hint = None
            self._detection_note.setText("Select a script to detect its interpreter.")
            return
        result = self._controller.detect_python(Path(text))
        self._working_dir_hint = result.working_directory
        self._candidates.clear()
        for candidate in result.candidates:
            self._candidates.addItem(f"{candidate.path} ({candidate.source.value})", candidate.path)
        self._use_candidate.setEnabled(self._candidates.count() > 0)
        if result.candidates:
            self._detection_note.setText("Choose a candidate or type an interpreter path above.")
        else:
            self._detection_note.setText(
                "No interpreters detected for this script. Type the interpreter path above."
            )

    def _on_use_candidate(self) -> None:
        """Populate the interpreter field with the selected candidate."""
        self._interpreter.setText(str(self._candidates.currentData()))
        if self._working_dir_hint is not None and not self._working_directory.text().strip():
            self._working_directory.setText(str(self._working_dir_hint))

    def _on_draft_changed(self, *_: object) -> None:
        """Enable Save once any draft field has been edited."""
        self._save_button.setEnabled(True)

    def _on_label_edited(self, text: str) -> None:
        """Push the edited label into the draft, stripped of surrounding whitespace."""
        if self._draft is not None:
            self._controller.set_label(self._draft, text.strip())

    def _path_row(
        self, line_edit_name: str, button_name: str, mode: str
    ) -> tuple[QLineEdit, QWidget]:
        """A path line edit with a Browse button; the button opens a file dialog of the
        given mode."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(container)
        line_edit.setObjectName(line_edit_name)
        button = QPushButton("Browse...", container)
        button.setObjectName(button_name)
        row.addWidget(line_edit)
        row.addWidget(button)
        button.clicked.connect(partial(self._on_browse, line_edit, mode))
        return (line_edit, container)

    def _build_schedule(self) -> QGroupBox:
        """The Schedule group: HH:MM time field and weekday checkboxes."""
        group = QGroupBox("Schedule")
        form = QFormLayout(group)
        self._time = QLineEdit(group)
        self._time.setObjectName("editor-time")
        self._time.setPlaceholderText("HH:MM")
        form.addRow("Time", self._time)
        days_widget = QWidget(group)
        days_layout = QHBoxLayout(days_widget)
        days_layout.setContentsMargins(0, 0, 0, 0)
        self._weekdays: list[QCheckBox] = []
        for day, label in zip(
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
            ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), strict=True,
        ):
            box = QCheckBox(label, days_widget)
            box.setObjectName(f"editor-weekday-{day}")
            self._weekdays.append(box)
            days_layout.addWidget(box)
        form.addRow("Weekdays", days_widget)
        self._schedule_note = QLabel(group)
        self._schedule_note.setObjectName("editor-schedule-note")
        self._schedule_note.setWordWrap(True)
        self._schedule_note.setText(
            "launchd starts the job at the scheduled time on the selected days. If the Mac"
            " is asleep the run is not woken, and missed runs are not retried."
        )
        form.addRow(self._schedule_note)
        return group

    def _build_environment(self) -> QGroupBox:
        """The Environment group: variable name/value rows."""
        group = QGroupBox("Environment")
        self._environment = RowTable(2, group)
        self._environment.setObjectName("editor-environment")
        layout = QVBoxLayout(group)
        group.setLayout(layout)
        layout.addWidget(self._environment)
        return group

    def _build_advanced(self) -> QGroupBox:
        """The Advanced group: working directory and per-stream log paths."""
        group = QGroupBox("Advanced")
        form = QFormLayout(group)
        self._working_directory, directory_row = self._path_row(
            "editor-working-directory", "editor-working-directory-browse", "directory"
        )
        form.addRow("Working directory", directory_row)
        self._stdout_path, stdout_row = self._path_row(
            "editor-stdout-path", "editor-stdout-path-browse", "save"
        )
        form.addRow("Stdout log", stdout_row)
        self._stderr_path, stderr_row = self._path_row(
            "editor-stderr-path", "editor-stderr-path-browse", "save"
        )
        form.addRow("Stderr log", stderr_row)
        self._logging_note = QLabel(group)
        self._logging_note.setObjectName("editor-logging-note")
        self._logging_note.setWordWrap(True)
        self._logging_note.setText("Leave a log path empty to disable that stream.")
        form.addRow(self._logging_note)
        return group

    def _build_preview(self) -> QGroupBox:
        """The Preview group: read-only generated plist XML pane."""
        group = QGroupBox("Preview")
        self._preview = QTextEdit(group)
        self._preview.setObjectName("editor-preview")
        self._preview.setReadOnly(True)
        layout = QVBoxLayout(group)
        group.setLayout(layout)
        layout.addWidget(self._preview)
        return group

    def _on_browse(self, line_edit: QLineEdit, mode: str) -> None:
        """Open a file dialog of the given mode and write the chosen path into the line edit."""
        if mode == "directory":
            path = QFileDialog.getExistingDirectory(self, "Select a directory", line_edit.text())
        elif mode == "open":
            path, _ = QFileDialog.getOpenFileName(self, "Select a file", line_edit.text())
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Select a file", line_edit.text())
        if path:
            line_edit.setText(path)

    def open_new(self) -> None:
        """Populate the dialog from a fresh draft and show it for a new job."""
        self._draft = self._controller.open_new()
        self.setWindowTitle("New Task")
        self._load_draft()

    def open_existing(self, job: JobDefinition) -> None:
        """Populate the dialog from a stored job for editing."""
        self._draft = self._controller.open_existing(job)
        self.setWindowTitle("Edit Task")
        self._load_draft()

    def _load_draft(self) -> None:
        """Fill every field from the current draft (setText never re-triggers the change slots)."""
        if self._draft is None:
            return
        d = self._draft
        self._name.setText(d.name)
        self._label.setText(d.label)
        kind_index = {"python": 0, "shell": 1, "executable": 2}[d.command_kind]
        self._kind_combo.setCurrentIndex(kind_index)
        self._stack.setCurrentIndex(kind_index)
        self._interpreter.setText(d.interpreter)
        self._script.setText(d.script)
        self._python_args.set_rows([[value] for value in d.python_arguments])
        self._shell_executable.setText(d.shell_executable)
        self._shell_args.set_rows([[value] for value in d.shell_arguments])
        self._executable.setText(d.executable_path)
        self._executable_args.set_rows([[value] for value in d.executable_arguments])
        self._time.setText(d.time)
        for box, day in zip(
            self._weekdays,
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
            strict=True,
        ):
            box.setChecked(day in d.weekdays)
        self._working_directory.setText(d.working_directory)
        self._environment.set_rows([[key, value] for key, value in d.environment])
        self._stdout_path.setText(d.stdout_path)
        self._stderr_path.setText(d.stderr_path)
        self._preview.clear()
        self._errors.hide()
        self._errors.clear()
        self._save_button.setEnabled(True)

    def _collect(self) -> None:
        """Push every visible field back into the draft through the controller mutators."""
        if self._draft is None:
            return
        d = self._draft
        c = self._controller
        kind: CommandKind = ("python", "shell", "executable")[
            self._kind_combo.currentIndex()
        ]
        c.set_name(d, self._name.text().strip())
        c.set_command_kind(d, kind)
        c.set_interpreter(d, self._interpreter.text().strip())
        c.set_script(d, self._script.text().strip())
        c.set_shell_executable(d, self._shell_executable.text().strip())
        c.set_executable_path(d, self._executable.text().strip())
        args_table = {
            "python": self._python_args,
            "shell": self._shell_args,
            "executable": self._executable_args,
        }[kind]
        c.set_arguments(d, kind, [row[0] for row in args_table.rows()])
        c.set_time(d, self._time.text().strip())
        c.set_weekdays(
            d,
            {
                day
                for box, day in zip(
                    self._weekdays,
                    ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
                    strict=True,
                )
                if box.isChecked()
            },
        )
        c.set_working_directory(d, self._working_directory.text().strip())
        c.set_environment(d, [(row[0], row[1]) for row in self._environment.rows()])
        c.set_stdout_path(d, self._stdout_path.text().strip())
        c.set_stderr_path(d, self._stderr_path.text().strip())

    def _on_validate(self) -> None:
        """Validate the draft and show any field errors."""
        self._collect()
        if self._draft is None:
            return
        self._show_errors(self._controller.validate(self._draft))

    def _on_preview(self) -> None:
        """Render the draft to a plist and show it, or show any field errors."""
        self._collect()
        if self._draft is None:
            return
        outcome = self._controller.preview(self._draft)
        if outcome.ok:
            self._preview.setPlainText(outcome.xml)
            self._errors.hide()
        else:
            self._show_errors(outcome)

    def _on_save(self) -> None:
        """Save the draft to the catalog, or show any field errors."""
        self._collect()
        if self._draft is None:
            return
        outcome = self._controller.save(self._draft)
        if outcome.ok:
            self._saved_path = outcome.path
            self._saved_label = outcome.label
            self.accept()
        else:
            self._show_errors(outcome)

    def _show_errors(self, outcome: EditorOutcome) -> None:
        """Render an outcome's message and field errors into the hidden error pane."""
        if outcome.ok:
            self._errors.hide()
            return
        lines = [outcome.message]
        lines.extend(f"{field}: {text}" for field, text in outcome.fields.items())
        self._errors.setPlainText("\n".join(lines))
        self._errors.show()
        self._save_button.setEnabled(False)

    @property
    def saved_path(self) -> Path | None:
        """The catalog path written by the last successful Save, if any."""
        return self._saved_path

    @property
    def saved_label(self) -> str | None:
        """The label assigned to the last successful Save, if any."""
        return self._saved_label
