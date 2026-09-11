"""External-plist edit models: preview and result for direct in-place editing.

Direct editing rewrites an external user LaunchAgent plist at its exact
source path and never creates or updates a managed catalog record — the
edited task remains external (pinned decision, v0.0.27 increment). The
preview fingerprints the original raw bytes and captures the launchd
loaded state so commit can fail closed when anything changed out-of-band.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import ProcessResult

__all__ = [
    "ExternalEditPhase",
    "ExternalEditPreview",
    "ExternalEditResult",
]


@dataclass(frozen=True, slots=True)
class ExternalEditPhase:
    """One launchctl phase of an external-edit transaction, in order."""

    name: str
    process: ProcessResult


@dataclass(frozen=True, slots=True)
class ExternalEditPreview:
    """Read-only preview of editing an external plist at its exact path.

    ``sha256`` and ``identity`` fingerprint the original raw bytes;
    ``identity`` is the ``(st_dev, st_ino)`` pair captured at preview
    time. ``loaded`` is the launchd loaded state observed at preview
    time; commit refuses when the status was unknown rather than
    guessing. ``nonce`` must be passed back unchanged at commit — a
    hand-constructed preview cannot be committed.
    """

    source_path: Path
    label: str
    candidate: JobDefinition
    sha256: str
    identity: tuple[int, int]
    loaded: bool
    nonce: str


@dataclass(frozen=True, slots=True)
class ExternalEditResult:
    """Outcome of a committed external-edit transaction.

    ``process`` is the last launchctl phase's result, or ``None`` when
    the job was not loaded and no launchctl phase was attempted.
    ``replaced`` marks that the source plist's bytes were swapped and
    ``reloaded`` that launchd was re-bootstrapped. ``retained_artifacts``
    always includes the backup sibling on success (external edits keep a
    recovery point) and, on failure, any staged sibling kept for
    diagnosis. The transaction never claims a rollback.
    """

    source_path: Path
    label: str
    process: ProcessResult | None
    phases: tuple[ExternalEditPhase, ...]
    completed_phases: tuple[str, ...]
    retained_artifacts: tuple[Path, ...]
    replaced: bool
    reloaded: bool
