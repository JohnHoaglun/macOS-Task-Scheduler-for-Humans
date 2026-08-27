"""LaunchAgent storage: write, remove, and discover user plists (Increment 6).

Targets only the user's ``~/Library/LaunchAgents`` directory (or an injected
root for tests). Never writes outside the root, never touches ``/Library``,
and never shells out — no ``launchctl`` calls until the Increment 7 adapter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos.filesystem import (
    LaunchAgentFilesystem,
    LocalFilesystem,
)
from task_scheduler.platform.macos.plist_codec import PlistCodec
from task_scheduler.platform.macos.plist_models import ParsedLaunchAgent
from task_scheduler.platform.macos.plist_reader import parse_bytes

__all__ = [
    "DiscoveredLaunchAgent",
    "LaunchAgentStore",
    "default_launch_agents_root",
]


def default_launch_agents_root() -> Path:
    """Return ``~/Library/LaunchAgents`` for the current user."""
    return Path.home() / "Library" / "LaunchAgents"


@dataclass(frozen=True, slots=True)
class DiscoveredLaunchAgent:
    """One plist found during discovery, with its parse outcome."""

    path: Path
    parsed: ParsedLaunchAgent


class LaunchAgentStore:
    """Persist and list LaunchAgent plists under a single root directory."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        filesystem: LaunchAgentFilesystem | None = None,
        codec: PlistCodec | None = None,
    ) -> None:
        self._root = Path(root) if root is not None else default_launch_agents_root()
        self._filesystem = filesystem if filesystem is not None else LocalFilesystem()
        self._codec = codec if codec is not None else PlistCodec()

    @property
    def root(self) -> Path:
        """The directory this store writes into (and only into)."""
        return self._root

    def destination_for(self, label: str) -> Path:
        """Return the managed plist path for ``label`` after validation."""
        self._validate_label(label)
        return self._root / f"{label}.plist"

    def write(self, job: JobDefinition) -> Path:
        """Serialize ``job`` as its managed plist; create-only, never overwrite."""
        destination = self.destination_for(job.label)
        self._filesystem.create_root(self._root)
        self._filesystem.create_exclusive(destination, self._codec.encode_bytes(job))
        return destination

    def remove(self, label: str) -> bool:
        """Remove the managed plist for ``label``.

        Idempotent: returns ``True`` when a plist was removed and ``False``
        when nothing was present. No launchctl state is touched.
        """
        return self._filesystem.remove_file(self.destination_for(label))

    def discover(self) -> list[DiscoveredLaunchAgent]:
        """Parse every direct-child plist under the root, without mutation.

        A missing root yields an empty list. Invalid or unsupported plists
        remain visible through :class:`ParsedLaunchAgent` and never raise.
        """
        if not self._root.is_dir():
            return []
        discovered: list[DiscoveredLaunchAgent] = []
        for path in self._filesystem.list_plist_files(self._root):
            payload = self._filesystem.read_plist_bytes(path)
            discovered.append(
                DiscoveredLaunchAgent(path=path, parsed=parse_bytes(payload))
            )
        return discovered

    @staticmethod
    def _validate_label(label: str) -> None:
        if label in {".", ".."} or "/" in label or os.sep in label:
            raise ValueError(
                "Label must not be '.'/'..' or contain path separators: "
                f"{label!r}"
            )
