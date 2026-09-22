"""External-plist edit and control models for the Universal Task Controls.

Direct editing rewrites an external user LaunchAgent plist at its exact
source path and never creates or updates a managed catalog record — the
edited task remains external (pinned decision, v0.0.27). Sessions
fingerprint the original raw bytes and capture the launchd loaded state
so every transaction (edit, disable, enable, run-now, remove) can fail
closed when anything changed out-of-band.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from task_scheduler.domain import JobDefinition
from task_scheduler.platform.macos import ParseSupport, ProcessResult

__all__ = [
    "ExternalEditPhase",
    "ExternalEditPreview",
    "ExternalEditResult",
    "ExternalEditSession",
    "RawPlistRead",
    "read_raw_plist",
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
class ExternalEditSession:
    """Everything the GUI needs to open an external edit, captured once.

    ``original`` is the decoded plist dict (lossless; present whenever
    the plist decoded), ``job`` the representable domain job (``None``
    for unrepresentable plists), ``label`` the usable launchd label
    (``None`` when absent or not launchd-safe) and ``loaded`` the launchd
    loaded state (``None`` when no status could be queried).
    ``edit_mode`` selects the editor: structured edits need a
    representable job; everything else falls back to the raw editor
    (pinned decision, Universal Task Controls, v0.0.27). ``nonce`` is
    informational — commit protection is the source fingerprint
    re-verification, not the nonce.
    """

    source_path: Path
    sha256: str
    identity: tuple[int, int]
    nonce: str
    label: str | None
    loaded: bool | None
    original: dict[str, object] | None
    status: ParseSupport
    job: JobDefinition | None

    def edit_mode(self) -> Literal["structured", "raw"]:
        return "structured" if self.job is not None else "raw"


@dataclass(frozen=True, slots=True)
class ExternalEditResult:
    """Outcome of an external edit, disable, enable, run-now, or remove.

    ``process`` is the last launchctl phase's result, or ``None`` when
    no launchctl phase was attempted. ``replaced`` marks that the
    source plist's bytes were swapped and ``reloaded`` that launchd was
    re-bootstrapped. ``quarantined_path`` is set when a no-label disable
    moved the plist to the quarantine directory. ``removed`` marks a
    completed remove. ``retained_artifacts`` always includes the backup
    sibling on success (external edits and removes keep a recovery
    point) and, on failure, any staged sibling kept for diagnosis. The
    transaction never claims a rollback.
    """

    source_path: Path
    label: str | None
    process: ProcessResult | None
    phases: tuple[ExternalEditPhase, ...]
    completed_phases: tuple[str, ...]
    retained_artifacts: tuple[Path, ...]
    replaced: bool
    reloaded: bool
    quarantined_path: Path | None = None
    removed: bool = False


@dataclass(frozen=True, slots=True)
class RawPlistRead:
    """Result of reading a source plist for the raw editor.

    Exactly one of ``text``/``error`` is non-None. ``binary_mode`` is True
    only when ``text`` is the base64 encoding of non-UTF-8 source bytes.
    """

    text: str | None
    binary_mode: bool
    error: str | None


def read_raw_plist(path: Path) -> RawPlistRead:
    """Read *path* as UTF-8 text, or base64-encode non-UTF-8 source bytes.

    Returns a ``RawPlistRead`` with ``error`` set when the file cannot be
    read; never raises.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return RawPlistRead(None, False, str(exc))
    try:
        return RawPlistRead(data.decode("utf-8"), False, None)
    except UnicodeDecodeError:
        return RawPlistRead(base64.b64encode(data).decode("ascii"), True, None)
