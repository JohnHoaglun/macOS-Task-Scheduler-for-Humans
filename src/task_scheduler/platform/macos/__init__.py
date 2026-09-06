"""macOS platform support: launchd plists, process execution, Python detection."""

from __future__ import annotations

from task_scheduler.platform.macos.filesystem import (
    LaunchAgentFilesystem,
    LocalFilesystem,
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
    PythonDetectorFilesystem,
    PythonEnvironmentDetector,
    compare_environments,
    default_python_detectors,
    detect_python,
    project_environment_candidate,
)

__all__ = [
    "LAUNCHD_TO_WEEKDAY",
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
    "LAUNCHCTL_PATH",
    "LaunchAgentBackend",
    "LaunchAgentFilesystem",
    "LaunchAgentStatus",
    "LaunchAgentStore",
    "LaunchctlAction",
    "LaunchctlResult",
    "LaunchFailureKind",
    "LocalFilesystem",
    "LocalLogReader",
    "LocalPythonDetectorFilesystem",
    "LogReadResult",
    "LogReader",
    "PlistCodec",
    "ProcessLaunchFailure",
    "ProcessResult",
    "ProcessRunner",
    "ParsedLaunchAgent",
    "ParseSupport",
    "PythonDetectionResult",
    "PythonDetectorFilesystem",
    "PythonEnvironmentDetector",
    "SubprocessRunner",
    "compare_environments",
    "default_launch_agents_root",
    "default_python_detectors",
    "detect_python",
    "parse_bytes",
    "parse_path",
    "project_environment_candidate",
    "validate_label",
]
