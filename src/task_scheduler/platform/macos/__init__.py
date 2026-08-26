"""macOS platform support: launchd plist encoding and reading."""

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

__all__ = [
    "LAUNCHD_TO_WEEKDAY",
    "SUPPORTED_KEYS",
    "WEEKDAY_TO_LAUNCHD",
    "PlistCodec",
    "ParsedLaunchAgent",
    "ParseSupport",
    "parse_bytes",
    "parse_path",
]
