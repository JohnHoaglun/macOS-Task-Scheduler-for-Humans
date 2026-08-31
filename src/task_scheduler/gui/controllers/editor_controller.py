"""Editor controller: Qt-free draft management for creating and editing managed jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time as Time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from task_scheduler.application.job_service import JobConflictError, managed_label
from task_scheduler.application.task_command_service import TaskCommandService
from task_scheduler.domain import (
    SUPPORTED_SCHEMA_VERSION,
    Command,
    EnvironmentConfig,
    ExecutableCommand,
    JobDefinition,
    LoggingConfig,
    PythonCommand,
    Schedule,
    ShellCommand,
    Weekday,
)
from task_scheduler.platform.macos import PythonDetectionResult

__all__ = [
    "CommandKind",
    "EditorController",
    "EditorOutcome",
    "JobDraft",
    "PreviewOutcome",
    "SaveOutcome",
]

CommandKind = Literal["python", "shell", "executable"]


@dataclass
class JobDraft:
    """Mutable editor draft for one managed job; nothing here is persisted."""

    job_id: UUID
    name: str = ""
    label: str = ""
    label_touched: bool = False
    enabled: bool = True
    command_kind: CommandKind = "python"
    interpreter: str = ""
    script: str = ""
    python_arguments: list[str] = field(default_factory=list)
    shell_executable: str = ""
    shell_arguments: list[str] = field(default_factory=list)
    executable_path: str = ""
    executable_arguments: list[str] = field(default_factory=list)
    time: str = ""
    weekdays: set[str] = field(default_factory=set)
    working_directory: str = ""
    environment: list[tuple[str, str]] = field(default_factory=list)
    stdout_path: str = ""
    stderr_path: str = ""


@dataclass(frozen=True, slots=True)
class EditorOutcome:
    """Result of an editor operation: success flag, message, and field errors."""

    ok: bool
    message: str = ""
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreviewOutcome(EditorOutcome):
    """Result of a plist preview, adding the generated launchd XML text."""

    xml: str = ""


@dataclass(frozen=True, slots=True)
class SaveOutcome(EditorOutcome):
    """Result of a save, adding the persisted catalog path and final label."""

    path: Path | None = None
    label: str = ""


class _DraftError(ValueError):
    """A draft pre-check failure, tagged with the form field it belongs to."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


class EditorController:
    """Bridges the editor view to job services without Qt imports."""

    def __init__(self, services: TaskCommandService) -> None:
        self._services = services

    def open_new(self) -> JobDraft:
        """Create an empty draft for a new job with a freshly generated id."""
        return JobDraft(job_id=uuid4())

    def open_existing(self, job: JobDefinition) -> JobDraft:
        """Populate a draft from a persisted job definition."""
        command = job.command
        interpreter = ""
        script = ""
        python_arguments: list[str] = []
        shell_executable = ""
        shell_arguments: list[str] = []
        executable_path = ""
        executable_arguments: list[str] = []
        if isinstance(command, PythonCommand):
            interpreter = str(command.interpreter)
            script = str(command.script)
            python_arguments = list(command.arguments)
        elif isinstance(command, ShellCommand):
            shell_executable = str(command.executable)
            shell_arguments = list(command.arguments)
        elif isinstance(command, ExecutableCommand):
            executable_path = str(command.executable)
            executable_arguments = list(command.arguments)
        return JobDraft(
            job_id=job.id,
            name=job.name,
            label=job.label,
            label_touched=True,
            enabled=job.enabled,
            command_kind=command.type,
            interpreter=interpreter,
            script=script,
            python_arguments=python_arguments,
            shell_executable=shell_executable,
            shell_arguments=shell_arguments,
            executable_path=executable_path,
            executable_arguments=executable_arguments,
            time=job.schedule.time.strftime("%H:%M"),
            weekdays={weekday.value for weekday in job.schedule.weekdays},
            working_directory=(
                str(job.working_directory) if job.working_directory is not None else ""
            ),
            environment=list(job.environment.variables.items()),
            stdout_path=str(job.logging.stdout_path)
            if job.logging.stdout_path is not None
            else "",
            stderr_path=str(job.logging.stderr_path)
            if job.logging.stderr_path is not None
            else "",
        )

    def set_name(self, draft: JobDraft, value: str) -> None:
        """Rename the draft, regenerating the managed label until touched."""
        draft.name = value
        if not draft.label_touched:
            draft.label = managed_label(value, draft.job_id)

    def set_label(self, draft: JobDraft, value: str) -> None:
        """Set the label explicitly, marking it as user-touched."""
        draft.label = value
        draft.label_touched = True

    def set_command_kind(self, draft: JobDraft, kind: CommandKind) -> None:
        """Switch the draft's command kind."""
        draft.command_kind = kind

    def set_interpreter(self, draft: JobDraft, value: str) -> None:
        """Set the Python interpreter path."""
        draft.interpreter = value

    def set_script(self, draft: JobDraft, value: str) -> None:
        """Set the Python script path, inferring the working directory once."""
        draft.script = value
        if value and not draft.working_directory:
            draft.working_directory = str(Path(value).parent)

    def set_shell_executable(self, draft: JobDraft, value: str) -> None:
        """Set the shell executable path."""
        draft.shell_executable = value

    def set_executable_path(self, draft: JobDraft, value: str) -> None:
        """Set the executable path."""
        draft.executable_path = value

    def arguments_for(self, draft: JobDraft, kind: CommandKind) -> list[str]:
        """Return the draft's argument list for the given command kind."""
        if kind == "python":
            return draft.python_arguments
        if kind == "shell":
            return draft.shell_arguments
        return draft.executable_arguments

    def add_argument(self, draft: JobDraft, kind: CommandKind) -> None:
        """Append an empty argument for the given command kind."""
        self.arguments_for(draft, kind).append("")

    def set_argument(
        self, draft: JobDraft, kind: CommandKind, index: int, value: str
    ) -> None:
        """Replace one argument for the given command kind."""
        self.arguments_for(draft, kind)[index] = value

    def remove_argument(self, draft: JobDraft, kind: CommandKind, index: int) -> None:
        """Remove one argument for the given command kind."""
        del self.arguments_for(draft, kind)[index]

    def set_time(self, draft: JobDraft, value: str) -> None:
        """Set the scheduled time as an HH:MM string."""
        draft.time = value

    def set_weekdays(self, draft: JobDraft, selected: set[str]) -> None:
        """Replace the selected weekdays."""
        draft.weekdays = set(selected)

    def set_working_directory(self, draft: JobDraft, value: str) -> None:
        """Set the working directory path."""
        draft.working_directory = value

    def add_environment_row(self, draft: JobDraft) -> None:
        """Append an empty environment variable row."""
        draft.environment.append(("", ""))

    def set_environment_key(self, draft: JobDraft, index: int, value: str) -> None:
        """Replace the key of one environment variable row."""
        _, row_value = draft.environment[index]
        draft.environment[index] = (value, row_value)

    def set_environment_value(self, draft: JobDraft, index: int, value: str) -> None:
        """Replace the value of one environment variable row."""
        row_key, _ = draft.environment[index]
        draft.environment[index] = (row_key, value)

    def remove_environment_row(self, draft: JobDraft, index: int) -> None:
        """Remove one environment variable row."""
        del draft.environment[index]

    def set_stdout_path(self, draft: JobDraft, value: str) -> None:
        """Set the stdout capture path."""
        draft.stdout_path = value

    def set_stderr_path(self, draft: JobDraft, value: str) -> None:
        """Set the stderr capture path."""
        draft.stderr_path = value

    def set_arguments(self, draft: JobDraft, kind: CommandKind, values: list[str]) -> None:
        """Replace the argument list for the given command kind."""
        if kind == "python":
            draft.python_arguments = list(values)
        elif kind == "shell":
            draft.shell_arguments = list(values)
        else:
            draft.executable_arguments = list(values)

    def set_environment(self, draft: JobDraft, rows: list[tuple[str, str]]) -> None:
        """Replace the draft's environment rows."""
        draft.environment = list(rows)

    def detect_python(self, script: Path) -> PythonDetectionResult:
        """Return interpreter candidates and a working-directory hint for a script."""
        return self._services.detect_python(script)

    def resolve(self, label: str) -> JobDefinition:
        """Return the managed job for the given label."""
        return self._services.resolve_managed_job(label)

    def validate(self, draft: JobDraft) -> EditorOutcome:
        """Validate the draft, mapping failures to per-field form errors."""
        try:
            job = self.build_job(draft)
            self._services.validate_job(job)
        except ValueError as exc:
            return EditorOutcome(
                ok=False,
                message="Fix the highlighted fields.",
                fields=self._field_errors(exc),
            )
        return EditorOutcome(ok=True, message="Valid")

    def preview(self, draft: JobDraft) -> PreviewOutcome:
        """Render the launchd plist for the draft, mapping failures to field errors."""
        try:
            job = self.build_job(draft)
            xml = self._services.generate_plist_for(job)
        except ValueError as exc:
            return PreviewOutcome(
                ok=False,
                message="Fix the highlighted fields.",
                fields=self._field_errors(exc),
            )
        return PreviewOutcome(ok=True, xml=xml)

    def save(self, draft: JobDraft) -> SaveOutcome:
        """Persist the draft to the catalog, mapping failures to outcomes."""
        try:
            job = self.build_job(draft)
        except ValueError as exc:
            return SaveOutcome(
                ok=False,
                message="Fix the highlighted fields.",
                fields=self._field_errors(exc),
            )
        try:
            path = self._services.save_managed_job(job)
        except JobConflictError as exc:
            return SaveOutcome(ok=False, message=str(exc), fields={"label": str(exc)})
        except OSError as exc:
            return SaveOutcome(ok=False, message=str(exc), fields={"job": str(exc)})
        return SaveOutcome(ok=True, path=path, label=job.label)

    def _field_errors(self, exc: Exception) -> dict[str, str]:
        """Map a draft or model validation failure to per-field form errors."""
        if isinstance(exc, _DraftError):
            return {exc.field: str(exc)}
        if isinstance(exc, ValidationError):
            for error in exc.errors():
                loc = error["loc"]
                head = str(loc[0])
                second = str(loc[1]) if len(loc) > 1 else ""
                if head in {
            "name",
            "label",
            "working_directory",
            "environment",
            "stdout_path",
            "stderr_path",
        }:
                    return {head: str(error["msg"])}
                if head == "schedule":
                    return {second or "time": str(error["msg"])}
                if head == "logging":
                    return {second or "stdout_path": str(error["msg"])}
                if head == "command":
                    if second in {"interpreter", "script", "executable"}:
                        return {second: str(error["msg"])}
                    return {"script": str(error["msg"])}
        return {"job": str(exc)}

    def build_job(self, draft: JobDraft) -> JobDefinition:
        """Assemble a JobDefinition from the editor draft, raising on missing fields.

        Public because non-persisting consumers (e.g. the draft direct test)
        need the validated job object itself, not a save.
        """
        name = draft.name.strip()
        if not name:
            raise _DraftError("name", "a job name is required")
        return JobDefinition(
            schema_version=SUPPORTED_SCHEMA_VERSION,
            id=draft.job_id,
            name=name,
            label=draft.label,
            enabled=draft.enabled,
            command=self._build_command(draft),
            schedule=self._build_schedule(draft),
            environment=EnvironmentConfig(variables=self._build_variables(draft)),
            working_directory=(
                Path(draft.working_directory) if draft.working_directory else None
            ),
            logging=LoggingConfig(
                stdout_path=Path(draft.stdout_path) if draft.stdout_path else None,
                stderr_path=Path(draft.stderr_path) if draft.stderr_path else None,
            ),
        )

    def _build_command(self, draft: JobDraft) -> Command:
        """Build the command object for the draft's selected command kind."""
        if draft.command_kind == "python":
            if not draft.interpreter:
                raise _DraftError("interpreter", "an interpreter is required")
            interpreter = Path(draft.interpreter)
            if not interpreter.is_absolute():
                raise _DraftError("interpreter", "the interpreter path must be absolute")
            if not draft.script:
                raise _DraftError("script", "a script is required")
            script = Path(draft.script)
            if not script.is_absolute():
                raise _DraftError("script", "the script path must be absolute")
            return PythonCommand(
                interpreter=interpreter,
                script=script,
                arguments=list(draft.python_arguments),
            )
        elif draft.command_kind == "shell":
            if not draft.shell_executable:
                raise _DraftError("shell_executable", "a shell executable is required")
            executable = Path(draft.shell_executable)
            if not executable.is_absolute():
                raise _DraftError("shell_executable", "the shell executable path must be absolute")
            return ShellCommand(
                executable=executable,
                arguments=list(draft.shell_arguments),
            )
        else:
            if not draft.executable_path:
                raise _DraftError("executable", "an executable is required")
            executable = Path(draft.executable_path)
            if not executable.is_absolute():
                raise _DraftError("executable", "the executable path must be absolute")
            return ExecutableCommand(
                executable=executable,
                arguments=list(draft.executable_arguments),
            )

    def _build_schedule(self, draft: JobDraft) -> Schedule:
        """Build the weekly schedule from the draft's time and selected weekdays."""
        if not draft.weekdays:
            raise _DraftError("weekdays", "at least one weekday is required")
        try:
            hour, minute = map(int, draft.time.split(":"))
            schedule_time = Time(hour, minute)
        except ValueError:
            raise _DraftError(
                "time", f"the time must look like HH:MM, got {draft.time!r}"
            ) from None
        return Schedule(time=schedule_time, weekdays={Weekday(w) for w in draft.weekdays})

    def _build_variables(self, draft: JobDraft) -> dict[str, str]:
        """Collect environment rows, raising on empty keys and duplicate keys."""
        result: dict[str, str] = {}
        for key, value in draft.environment:
            if not key:
                raise _DraftError("environment", "environment variable names must not be empty")
            if key in result:
                raise _DraftError("environment", f"duplicate environment variable: {key}")
            result[key] = value
        return result
