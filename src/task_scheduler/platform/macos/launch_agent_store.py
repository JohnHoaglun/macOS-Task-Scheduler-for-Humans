"""LaunchAgent storage: write, remove, discover, and stage user plists.

Targets only the user's ``~/Library/LaunchAgents`` directory (or an injected
root for tests). Never writes outside the root, never touches ``/Library``,
and never shells out — the Increment 7 adapter owns all ``launchctl`` calls.

The staging API (stage → backup → activate) supports the explicit
replace/reload path: staging and backup are create-exclusive sibling files
that never silently overwrite anything, and activation is the one explicit
atomic replacement.
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
    "validate_label",
]


def default_launch_agents_root() -> Path:
    """Return ``~/Library/LaunchAgents`` for the current user."""
    return Path.home() / "Library" / "LaunchAgents"


def validate_label(label: str) -> None:
    """Reject labels that could escape the managed root as file names.

    The domain model already constrains job labels, but the store (and the
    Increment 7 adapter) also accept raw label strings, so the path-safety
    check is enforced here, at the filesystem boundary.
    """
    if label in {".", ".."} or "/" in label or os.sep in label:
        raise ValueError(
            "Label must not be '.'/'..' or contain path separators: " f"{label!r}"
        )


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
        validate_label(label)
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

    # -- staging (explicit replace/reload path) ------------------------------

    def stage_plist(self, label: str, payload: bytes) -> Path:
        """Create a uniquely named staged sibling for ``label``'s plist.

        Create-exclusive: nothing existing is ever overwritten. The caller
        owns the staged file — activate it or clean it up.
        """
        destination = self.destination_for(label)
        self._filesystem.create_root(self._root)
        for attempt in range(1, 1001):
            candidate = destination.with_name(f"{destination.name}.staged.{attempt}")
            try:
                self._filesystem.create_exclusive(candidate, payload)
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError(f"could not allocate a unique staged sibling for {label!r}")

    def backup_plist(self, label: str) -> Path | None:
        """Preserve ``label``'s deployed plist as a uniquely named backup sibling.

        Create-exclusive and read-only with respect to the deployed plist.
        Returns the backup path, or ``None`` when no deployed plist exists.
        """
        destination = self.destination_for(label)
        try:
            payload = self._filesystem.read_plist_bytes(destination)
        except FileNotFoundError:
            return None
        for attempt in range(1, 1001):
            candidate = destination.with_name(f"{destination.name}.backup.{attempt}")
            try:
                self._filesystem.create_exclusive(candidate, payload)
                return candidate
            except FileExistsError:
                continue
        raise RuntimeError(f"could not allocate a unique backup sibling for {label!r}")

    def activate_staged(self, label: str, staged: Path) -> Path:
        """Atomically replace ``label``'s deployed plist with the staged payload.

        This is the one explicit overwrite in the staging flow; the staged
        file is removed once the replacement has completed.
        """
        destination = self.destination_for(label)
        self._filesystem.replace(staged, destination)
        self._filesystem.remove_file(staged)
        return destination

    def remove_sibling(self, path: Path) -> bool:
        """Remove a staging/backup sibling file by exact path.

        Only direct children of the root are accepted; ``True`` when the
        file was removed, ``False`` when it was already absent.
        """
        if path.parent != self._root:
            raise ValueError(f"path is outside the LaunchAgent root: {path}")
        return self._filesystem.remove_file(path)
