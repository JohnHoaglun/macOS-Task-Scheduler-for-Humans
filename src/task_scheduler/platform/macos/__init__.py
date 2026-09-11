"""macOS platform support: launchd plists, process execution, Python detection."""

from __future__ import annotations

from task_scheduler.platform.macos.diagnostic_probes import (
    ArchitectureFinding,
    DiagnosticProbes,
    LocalDiagnosticProbes,
    ProtectedPathFinding,
    probe_executable_architecture,
    probe_protected_paths,
)
from task_scheduler.platform.macos.filesystem import (
    LaunchAgentFilesystem,
    LocalFilesystem,
    SourceChangedError,
    SourceSnapshot,
)
from task_scheduler.platform.macos.finder import (
    FINDER_OPEN_PATH,
    FinderRevealer,
    LocalFinderRevealer,
)
from task_scheduler.platform.macos.launch_agent_store import (
    DiscoveredLaunchAgent,
    LaunchAgentStore,
    default_launch_agents_root,
    validate_label,
)
from task_scheduler.platform.macos.launchctl import (
    LAUNCHCTL_PATH,
    LaunchAgentBackend,
    LaunchAgentStatus,
    LaunchctlAction,
    LaunchctlResult,
)
from task_scheduler.platform.macos.log_reader import (
    LocalLogReader,
    LogReader,
    LogReadResult,
)
from task_scheduler.platform.macos.plist_codec import PlistCodec
from task_scheduler.platform.macos.plist_models import (
    LAUNCHD_TO_WEEKDAY,
    SUPPORTED_KEYS,
    WEEKDAY_TO_LAUNCHD,
    ParsedLaunchAgent,
    ParseSupport,
)
from task_scheduler.platform.macos.plist_reader import parse_bytes, parse_path
from task_scheduler.platform.macos.process_runner import (
    CommandSpec,
    LaunchFailureKind,
    ProcessLaunchFailure,
    ProcessResult,
    ProcessRunner,
    SubprocessRunner,
)
from task_scheduler.platform.macos.python_detection import (
    CandidateSource,
    DetectionContext,
    DetectionNote,
    DetectorContribution,
    DetectorKind,
    EnvironmentDifference,
    InterpreterCandidate,
    LocalPythonDetectorFilesystem,
    PythonDetectionResult,
    PythonDetectionRoots,
    PythonDetectorFilesystem,
    PythonEnvironmentDetector,
    compare_environments,
    detect_python,
    project_environment_candidate,
)
from task_scheduler.platform.macos.python_detectors import default_python_detectors

__all__ = [
    "ArchitectureFinding",
    "DiagnosticProbes",
    "LAUNCHD_TO_WEEKDAY",
    "LocalDiagnosticProbes",
    "ProtectedPathFinding",
    "probe_executable_architecture",
    "probe_protected_paths",
    "SUPPORTED_KEYS",
    "WEEKDAY_TO_LAUNCHD",
    "CandidateSource",
    "CommandSpec",
    "DetectionContext",
    "DetectionNote",
    "DetectorContribution",
    "DetectorKind",
    "DiscoveredLaunchAgent",
    "EnvironmentDifference",
    "InterpreterCandidate",
    "FINDER_OPEN_PATH",
    "LAUNCHCTL_PATH",
    "LaunchAgentBackend",
    "LaunchAgentFilesystem",
    "LaunchAgentStatus",
    "LaunchAgentStore",
    "LaunchctlAction",
    "LaunchctlResult",
    "LaunchFailureKind",
    "LocalFilesystem",
    "LocalFinderRevealer",
    "LocalLogReader",
    "LocalPythonDetectorFilesystem",
    "LogReadResult",
    "LogReader",
    "PlistCodec",
    "ProcessLaunchFailure",
    "ProcessResult",
    "FinderRevealer",
    "ProcessRunner",
    "ParsedLaunchAgent",
    "ParseSupport",
    "PythonDetectionResult",
    "PythonDetectionRoots",
    "PythonDetectorFilesystem",
    "PythonEnvironmentDetector",
    "SubprocessRunner",
    "SourceChangedError",
    "SourceSnapshot",
    "compare_environments",
    "default_launch_agents_root",
    "default_python_detectors",
    "detect_python",
    "parse_bytes",
    "parse_path",
    "project_environment_candidate",
    "validate_label",
]
