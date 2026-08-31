"""Dialog presenting the outcome of one lifecycle operation."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application.task_command_service import InstallResult, UninstallResult
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleOutcome,
)
from task_scheduler.platform.macos import LaunchAgentStatus, LaunchctlResult, ProcessResult

__all__ = ["LifecycleResultDialog"]

_ACTION_TITLES = {
    LifecycleAction.INSTALL: "Install",
    LifecycleAction.REINSTALL: "Reinstall",
    LifecycleAction.UNINSTALL: "Uninstall",
    LifecycleAction.ENABLE: "Enable",
    LifecycleAction.DISABLE: "Disable",
    LifecycleAction.RUN_NOW: "Run Now",
}


class LifecycleResultDialog(QDialog):
    """Headline, exit code, raw output, and an expandable technical-details pane."""

    def __init__(self, outcome: LifecycleOutcome, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._outcome = outcome
        title = QLabel(self)
        title.setObjectName("lifecycle-result-title")
        title.setWordWrap(True)
        title.setText(self._headline())
        exit_label = QLabel(self)
        exit_label.setObjectName("lifecycle-result-exit")
        exit_label.setText(self._exit_code_text())
        self._stdout = self._output_pane("lifecycle-result-stdout")
        self._stderr = self._output_pane("lifecycle-result-stderr")
        self._fill_output()
        details = QGroupBox("Technical details", self)
        details.setObjectName("lifecycle-technical-group")
        toggle = QPushButton("View technical details", details)
        toggle.setObjectName("lifecycle-details-toggle")
        toggle.setCheckable(True)
        self._technical = QPlainTextEdit(details)
        self._technical.setObjectName("lifecycle-technical-details")
        self._technical.setReadOnly(True)
        self._technical.setPlainText(self._technical_text())
        self._technical.hide()
        details_layout = QVBoxLayout(details)
        details_layout.addWidget(toggle)
        details_layout.addWidget(self._technical)
        close = QPushButton("Close", self)
        close.setObjectName("lifecycle-result-close")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(exit_label)
        layout.addWidget(self._stdout)
        layout.addWidget(self._stderr)
        layout.addWidget(details)
        layout.addLayout(buttons)
        toggle.toggled.connect(self._technical.setVisible)

    def _fill_output(self) -> None:
        """Show raw stdout/stderr only when the process actually produced some."""
        process = self._process()
        if process is None:
            self._stdout.hide()
            self._stderr.hide()
            return
        if process.stdout:
            self._stdout.setPlainText(process.stdout)
        else:
            self._stdout.hide()
        if process.stderr:
            self._stderr.setPlainText(process.stderr)
        else:
            self._stderr.hide()

    def _output_pane(self, object_name: str) -> QPlainTextEdit:
        pane = QPlainTextEdit(self)
        pane.setObjectName(object_name)
        pane.setReadOnly(True)
        return pane

    def _headline(self) -> str:
        action = _ACTION_TITLES[self._outcome.action]
        if self._outcome.is_success:
            return f"{action} succeeded for {self._outcome.label}."
        reason = f": {self._outcome.error}" if self._outcome.error is not None else ""
        return f"{action} failed for {self._outcome.label}{reason}."

    def _process(self) -> ProcessResult | None:
        result = self._outcome.result
        return result.process if result is not None else None

    def _exit_code_text(self) -> str:
        process = self._process()
        if process is None:
            return "Exit code: unavailable (no launchd process ran)"
        if process.exit_code is None:
            detail = f": {process.launch_failure}" if process.launch_failure else ""
            return f"Exit code: unavailable (launchd did not start{detail})"
        return f"Exit code: {process.exit_code}"

    def _technical_text(self) -> str:
        lines: list[str] = []
        result = self._outcome.result
        if isinstance(result, InstallResult):
            for phase in result.phases:
                exit_code = (
                    str(phase.process.exit_code)
                    if phase.process.exit_code is not None
                    else "did not start"
                )
                lines.append(f"{phase.name}: exit {exit_code}")
            if result.completed_phases:
                lines.append(f"completed: {', '.join(result.completed_phases)}")
            if result.retained_artifacts:
                lines.append("retained artifacts:")
                lines.extend(f"  {path}" for path in result.retained_artifacts)
        elif isinstance(result, UninstallResult):
            lines.append(f"catalog record removed: {result.catalog_removed}")
        elif isinstance(result, LaunchctlResult):
            lines.append(f"launchctl action: {result.action.value}")
        elif isinstance(result, LaunchAgentStatus):
            lines.append(f"loaded in launchd: {result.loaded}")
        if not lines:
            lines.append("(no launchd process ran)")
        return "\n".join(lines)
