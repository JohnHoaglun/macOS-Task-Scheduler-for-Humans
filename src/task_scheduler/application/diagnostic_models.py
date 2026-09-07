"""Diagnostic report models: evidence states, sources, contexts, and groups.

This module is the canonical home for DiagnosticSeverity and Diagnostic.
The diagnostic_service module re-exports these symbols so every existing
import path continues to work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from task_scheduler.application.log_service import JobLogs
from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos.process_runner import ProcessResult
from task_scheduler.platform.macos.python_detection import PythonDetectionResult

if TYPE_CHECKING:
    from task_scheduler.application.task_command_service import (
        InstallResult,
        UninstallResult,
    )
    from task_scheduler.platform.macos.diagnostic_probes import (
        ArchitectureFinding,
        ProtectedPathFinding,
    )
    from task_scheduler.platform.macos.launchctl import (
        LaunchAgentStatus,
        LaunchctlResult,
    )
    from task_scheduler.platform.macos.plist_models import ParsedLaunchAgent


class EvidenceState(StrEnum):
    """Quality of the evidence backing a diagnostic finding."""

    CONFIRMED = "confirmed"
    NOT_PROVABLE = "not_provable"
    UNAVAILABLE = "unavailable"


class DiagnosticSource(StrEnum):
    """Which subsystem produced a diagnostic group."""

    PREFLIGHT = "preflight"
    DIRECT_TEST = "direct_test"
    PYTHON_ENVIRONMENT = "python_environment"
    LIFECYCLE = "lifecycle"
    LOGS = "logs"
    PLIST = "plist"


class DiagnosticSeverity(StrEnum):
    """Severity level for a diagnostic finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Diagnostic(BaseModel):
    """One structured finding, independent of any UI rendering."""

    severity: DiagnosticSeverity
    code: str
    title: str
    description: str
    suggested_action: str
    evidence_state: EvidenceState | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticGroup:
    """A named group of diagnostics from one source."""

    source: DiagnosticSource
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """An ordered collection of diagnostic groups.

    ``all`` flattens every group's diagnostics in group order.
    """

    groups: tuple[DiagnosticGroup, ...] = ()

    @property
    def all(self) -> tuple[Diagnostic, ...]:
        """All diagnostics flattened in group order."""
        result: list[Diagnostic] = []
        for group in self.groups:
            result.extend(group.diagnostics)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class PreflightContext:
    """Pre-flight checks: paths and architecture."""

    job: JobDefinition
    protected_findings: tuple[ProtectedPathFinding, ...] = ()
    architecture_finding: ArchitectureFinding | None = None


@dataclass(frozen=True, slots=True)
class DirectTestContext:
    """Result of running a job's command directly."""

    job: JobDefinition
    process: ProcessResult
    spec_argv0: str | None = None


@dataclass(frozen=True, slots=True)
class PythonEnvironmentContext:
    """Python-environment detection result."""

    job: JobDefinition
    detection: PythonDetectionResult


@dataclass(frozen=True, slots=True)
class LifecycleContext:
    """Outcome of an install/uninstall/enable/disable/trigger action."""

    label: str
    action: str
    result: InstallResult | LaunchctlResult | LaunchAgentStatus | UninstallResult


@dataclass(frozen=True, slots=True)
class LogContext:
    """Persisted log read outcome."""

    job: JobDefinition
    logs: JobLogs


@dataclass(frozen=True, slots=True)
class InspectionContext:
    """Parsed external plist inspection."""

    path: Path
    parsed: ParsedLaunchAgent


DiagnosticContext = (
    PreflightContext
    | DirectTestContext
    | PythonEnvironmentContext
    | LifecycleContext
    | LogContext
    | InspectionContext
)
