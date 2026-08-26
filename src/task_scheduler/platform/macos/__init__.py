"""macOS platform support: launchd plists and Python-environment detection."""

from __future__ import annotations

from task_scheduler.platform.macos.plist_codec import PlistCodec
from task_scheduler.platform.macos.plist_models import (
    LAUNCHD_TO_WEEKDAY,
    SUPPORTED_KEYS,
    WEEKDAY_TO_LAUNCHD,
    ParsedLaunchAgent,
    ParseSupport,
)
from task_scheduler.platform.macos.plist_reader import parse_bytes, parse_path
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
    "EnvironmentDifference",
    "InterpreterCandidate",
    "PlistCodec",
    "PythonDetectionResult",
    "ParsedLaunchAgent",
    "ParseSupport",
    "compare_environments",
    "detect_python",
    "parse_bytes",
    "parse_path",
]
