"""Plain-text rendering for mactask command output (Increment 8).

Renderers are pure: they turn application results into text, hold no
state, and perform no I/O, so every message shape is directly unit-
testable through the CLI tests.
"""

from __future__ import annotations

import shlex
from datetime import UTC, timedelta
from pathlib import Path

from task_scheduler.application.diagnostic_models import Diagnostic
from task_scheduler.application.external_import import ExternalPlistImportPreview
from task_scheduler.application.history_models import HistoryReadResult
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.application.managed_json_transfer import (
    ManagedJsonImportPreview,
)
from task_scheduler.application.task_command_service import (
    InspectReport,
    ListingKind,
    TaskListing,
)
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import (
    CalendarSchedule,
    IntervalSchedule,
    JobDefinition,
    Schedule,
    human_interval,
)
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos import LaunchAgentStatus

__all__ = [
    "format_argv",
    "format_diagnostics",
    "format_duration",
    "format_export_success",
    "format_history",
    "format_import_disclosure",
    "format_import_json_conflicts",
    "format_import_json_success",
    "format_import_success",
    "format_inspect",
    "format_job_summary",
    "format_label",
    "format_list",
    "format_logs",
    "format_schedule",
    "format_status",
    "format_stream",
    "format_test",
]


def format_schedule(schedule: Schedule) -> str:
    """Render a schedule, e.g. ``07:30 on monday, wednesday`` or ``Every 30 minutes``."""
    if isinstance(schedule, IntervalSchedule):
        text = human_interval(schedule.seconds)
    else:
        text = _calendar_text(schedule)
    if schedule.run_at_load:
        text += " + at login"
    return text


def _calendar_text(schedule: CalendarSchedule) -> str:
    weekdays = ", ".join(weekday.value for weekday in sorted(schedule.weekdays))
    parts = [f"{time:%H:%M}" for time in schedule.times]
    times = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"{times} on {weekdays}"


def format_argv(job: JobDefinition) -> str:
    """Render the exact argv launchd would execute, shell-quoted."""
    return " ".join(shlex.quote(arg) for arg in command_argv(job.command))


def format_job_summary(job: JobDefinition) -> str:
    """Render the key fields of a job definition as labeled lines."""
    lines = [
        f"name: {job.name}",
        f"label: {job.label}",
        f"enabled: {'yes' if job.enabled else 'no'}",
        f"schedule: {format_schedule(job.schedule)}",
        f"command: {format_argv(job)}",
    ]
    if job.working_directory is not None:
        lines.append(f"working directory: {job.working_directory}")
    for key in sorted(job.environment.variables):
        lines.append(f"env {key}={job.environment.variables[key]}")
    if job.logging.stdout_path is not None:
        lines.append(f"stdout log: {job.logging.stdout_path}")
    if job.logging.stderr_path is not None:
        lines.append(f"stderr log: {job.logging.stderr_path}")
    return "\n".join(lines)


def format_label(listing: TaskListing) -> str:
    """Best-effort label for a task row (its plist may be invalid)."""
    job = listing.job or (listing.parsed.job if listing.parsed is not None else None)
    if job is not None:
        return job.label
    if listing.parsed is not None:
        raw_label = listing.parsed.raw.get("Label")
        if isinstance(raw_label, str) and raw_label:
            return raw_label
    return listing.path.name if listing.path is not None else "unknown"


def format_list(listing: TaskListing) -> str:
    """Render one line of the ``list`` output."""
    flag = "managed" if listing.managed else "external"
    if listing.kind is ListingKind.SAVED:
        return f"{format_label(listing)} [saved] ({flag}) (task catalog — not installed)"
    parsed = listing.parsed
    status = parsed.status.value if parsed is not None else "unknown"
    path = str(listing.path) if listing.path is not None else "(no plist)"
    return f"{format_label(listing)} [{status}] ({flag}) {path}"


def format_status(status: LaunchAgentStatus) -> str:
    """Render a launchd status as a human phrase."""
    if status.loaded is True:
        return "loaded in launchd"
    if status.loaded is False:
        return "not loaded in launchd"
    return "launchd status unknown (launchctl could not be queried)"


def format_diagnostics(diagnostics: list[Diagnostic]) -> str:
    """Render the diagnostics of a direct test result."""
    if not diagnostics:
        return "none"
    lines: list[str] = []
    for diagnostic in diagnostics:
        lines.append(
            f"[{diagnostic.severity.value}] {diagnostic.code}: {diagnostic.title}"
        )
        lines.append(f"    {diagnostic.description}")
        lines.append(f"    suggested: {diagnostic.suggested_action}")
    return "\n".join(lines)


def format_duration(duration: timedelta) -> str:
    """Render a process duration with millisecond precision."""
    return f"{duration.total_seconds():.3f}s"


def _block(text: str) -> list[str]:
    """Render an output stream, marking empty content explicitly."""
    return text.splitlines() if text else ["(empty)"]


def format_test(result: DirectTestResult) -> str:
    """Render a direct test outcome: result, streams, diagnostics."""
    process = result.process
    if process.launch_failure is not None:
        failure = process.launch_failure
        lines: list[str] = [
            f"launch failed ({failure.kind.value}): {failure.message}"
        ]
    else:
        lines = [f"exit code: {process.exit_code}"]
    lines.append(f"duration: {format_duration(process.duration)}")
    lines.append("stdout:")
    lines.extend(_block(process.stdout))
    lines.append("stderr:")
    lines.extend(_block(process.stderr))
    lines.append("diagnostics:")
    lines.extend(_block(format_diagnostics(result.diagnostics)))
    return "\n".join(lines)


def format_logs(logs: JobLogs) -> str:
    """Render both log streams of a managed job."""
    return "\n\n".join(format_stream(stream) for stream in (logs.stdout, logs.stderr))


def format_stream(stream: LogStream) -> str:
    """Render one log stream with a heading and its content or problem."""
    lines = [f"=== {stream.name} ==="]
    if stream.path is None:
        lines.append(f"not configured (no {stream.name} log path set)")
    elif stream.error is not None:
        lines.append(stream.error)
    elif not stream.content:
        lines.append("(empty)")
    else:
        lines.extend(stream.content.splitlines())
    return "\n".join(lines)


def format_history(result: HistoryReadResult, label: str) -> str:
    """Render execution-history events as lines (newest first)."""
    if not result.events:
        return ""
    lines: list[str] = []
    for event in result.events:
        ts = event.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [ts, str(event.kind), str(event.outcome)]
        if event.exit_code is not None:
            parts.append(f"exit={event.exit_code}")
        if event.duration_seconds is not None:
            parts.append(f"duration={event.duration_seconds:.3f}s")
        if event.kind == "status_observation" and event.loaded is not None:
            parts.append(f"loaded={'yes' if event.loaded else 'no'}")
        elif event.kind == "status_observation" and event.loaded is None:
            parts.append("loaded=unknown")
        if event.diagnostic_codes:
            parts.append(f"codes={','.join(event.diagnostic_codes)}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_inspect(
    report: InspectReport,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> str:
    """Render an inspect report: job, plist detail, launchd status.

    A trailing ``diagnostics:`` section is appended when the plist parse
    produced findings (i.e. the plist is not fully supported).
    """
    lines = [format_job_summary(report.job)]
    lines.append("")
    lines.append(f"plist: {report.plist_path} [{report.plist.status.value}]")
    for key in report.plist.unsupported_keys:
        lines.append(f"  unsupported key: {key}")
    for warning in report.plist.warnings:
        lines.append(f"  warning: {warning}")
    lines.append("")
    lines.append(f"launchd: {format_status(report.status)}")
    if diagnostics:
        lines.append("")
        lines.append("diagnostics:")
        lines.extend(_block(format_diagnostics(list(diagnostics))))
    return "\n".join(lines)


def format_import_success(label: str) -> str:
    """Render the post-import confirmation line."""
    return f"Imported {label} as a managed task (catalog only; source plist unchanged)."


def format_import_disclosure(
    preview: ExternalPlistImportPreview, *, include_prompt: bool = True
) -> str:
    """Render the warning/unsupported-key disclosure block.

    When *include_prompt* is True (stderr path), appends the
    ``--acknowledge-partial`` prompt.  When False (stdout, already
    acknowledged), only warnings and unsupported keys are emitted.
    """
    lines: list[str] = []
    for warning in preview.warnings:
        lines.append(f"warning: {warning}")
    for key in preview.unsupported_keys:
        lines.append(f"unsupported key: {key}")
    if include_prompt and (preview.warnings or preview.unsupported_keys):
        lines.append(
            "Use --acknowledge-partial to import a partially supported plist."
        )
    return "\n".join(lines)


def format_export_success(label: str, destination: Path) -> str:
    """Render the post-export confirmation line."""
    return f"exported {label} -> {destination}"


def format_import_json_conflicts(preview: ManagedJsonImportPreview) -> str:
    """Render the import-refused conflict block for managed JSON."""
    lines = ["import refused (conflict):"]
    if preview.id_conflict_path is not None:
        lines.append(f"  id conflict: {preview.id_conflict_path}")
    if preview.label_conflict_path is not None:
        lines.append(f"  label conflict: {preview.label_conflict_path}")
    return "\n".join(lines)


def format_import_json_success(label: str, schema_version: int) -> str:
    """Render the post-managed-json-import confirmation line."""
    return f"imported {label} (schema v{schema_version}) (catalog only; no plist created)"
