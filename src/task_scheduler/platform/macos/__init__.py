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
    EnvironmentDifference,
    InterpreterCandidate,
    PythonDetectionResult,
    compare_environments,
    detect_python,
)

__all__ = [
    "LAUNCHD_TO_WEEKDAY",
    "SUPPORTED_KEYS",
    "WEEKDAY_TO_LAUNCHD",
    "CandidateSource",
    "CommandSpec",
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
    "PlistCodec",
    "ProcessLaunchFailure",
    "ProcessResult",
    "ProcessRunner",
    "PythonDetectionResult",
    "ParsedLaunchAgent",
    "ParseSupport",
    "SubprocessRunner",
    "compare_environments",
    "default_launch_agents_root",
    "detect_python",
    "parse_bytes",
    "parse_path",
    "validate_label",
]
