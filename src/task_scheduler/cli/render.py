"""Plain-text rendering for mactask command output (Increment 8).

Renderers are pure: they turn application results into text, hold no
state, and perform no I/O, so every message shape is directly unit-
testable through the CLI tests.
"""

from __future__ import annotations

import shlex
from datetime import timedelta

from task_scheduler.application.diagnostic_service import Diagnostic
from task_scheduler.application.log_service import JobLogs, LogStream
from task_scheduler.application.task_command_service import (
    AgentListing,
    InspectReport,
)
from task_scheduler.application.test_service import DirectTestResult
from task_scheduler.domain import JobDefinition, Schedule
from task_scheduler.domain.command import command_argv
from task_scheduler.platform.macos import LaunchAgentStatus

__all__ = [
    "format_argv",
    "format_diagnostics",
    "format_duration",
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
    """Render a schedule as ``HH:MM on monday, wednesday``."""
    weekdays = ", ".join(weekday.value for weekday in sorted(schedule.weekdays))
    return f"{schedule.time:%H:%M} on {weekdays}"


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


def format_label(agent: AgentListing) -> str:
    """Best-effort label for a discovered agent (its plist may be invalid)."""
    parsed = agent.parsed
    if parsed.job is not None:
        return parsed.job.label
    raw_label = parsed.raw.get("Label")
    if isinstance(raw_label, str) and raw_label:
        return raw_label
    return agent.path.name


def format_list(agent: AgentListing) -> str:
    """Render one line of the ``list`` output."""
    flag = "managed" if agent.managed else "external"
    return f"{format_label(agent)} [{agent.parsed.status.value}] ({flag}) {agent.path}"


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


def format_inspect(report: InspectReport) -> str:
    """Render an inspect report: job, plist detail, launchd status."""
    lines = [format_job_summary(report.job)]
    lines.append("")
    lines.append(f"plist: {report.plist_path} [{report.plist.status.value}]")
    for key in report.plist.unsupported_keys:
        lines.append(f"  unsupported key: {key}")
    for warning in report.plist.warnings:
        lines.append(f"  warning: {warning}")
    lines.append("")
    lines.append(f"launchd: {format_status(report.status)}")
    return "\n".join(lines)
