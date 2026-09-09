"""Python-environment detection for scheduled jobs.

Given a selected script, an ordered registry of read-only detectors finds
candidate interpreters, records non-fatal discovery notes, recommends a
default working directory, and compares two explicitly supplied environment
mappings. Detection never runs a shell, never invokes an ecosystem tool
(``uv``, ``poetry``, or any other), never resolves symlinks, and never
mutates domain objects; candidates are recommendations only and are never
applied automatically.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class CandidateSource(StrEnum):
    """Where a candidate interpreter came from, in priority order."""

    VENV = ".venv"
    VENV_FALLBACK = "venv"
    CURRENT = "current"
    PATH = "path"


class DetectorKind(StrEnum):
    """The detector that discovered an interpreter path."""

    CORE = "core"
    UV = "uv"
    POETRY = "poetry"
    PYENV = "pyenv"
    CONDA = "conda"
    PIPENV = "pipenv"
    HOMEBREW = "homebrew"


class DetectionNote(BaseModel):
    """A non-fatal discovery note; notes never cancel detection."""

    model_config = ConfigDict(frozen=True)

    detector: DetectorKind
    message: str


class PythonDetectorFilesystem(Protocol):
    """Read-only filesystem view used by the detectors; never raises."""

    def exists(self, path: Path) -> bool: ...

    def is_file(self, path: Path) -> bool: ...

    def is_dir(self, path: Path) -> bool: ...

    def is_executable(self, path: Path) -> bool: ...

    def read_text(self, path: Path) -> str | None: ...


class LocalPythonDetectorFilesystem:
    """The protocol over the live filesystem, without path resolution."""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def is_executable(self, path: Path) -> bool:
        return os.access(path, os.X_OK)

    def read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None


@dataclass(frozen=True)
class PythonDetectionRoots:
    """Well-known interpreter tool locations, injected into every detection run.

    :meth:`default` resolves the production values and is the only place that
    reads the home directory; detectors read only these pre-resolved paths, so
    tests can point them at ``tmp_path`` without touching live host state.
    """

    pyenv: tuple[Path, ...]
    conda: tuple[Path, ...]
    homebrew: tuple[Path, ...]

    @classmethod
    def default(cls) -> PythonDetectionRoots:
        home = Path.home()
        return cls(
            pyenv=(home / ".pyenv",),
            conda=(
                home / ".conda",
                home / "miniconda3",
                home / "anaconda3",
                home / "miniforge3",
                home / "mambaforge",
            ),
            homebrew=(Path("/opt/homebrew"), Path("/usr/local")),
        )


@dataclass(frozen=True)
class DetectionContext:
    """Everything one detector may look at for a single detection run."""

    script: Path
    current_interpreter: Path
    path_lookup: Callable[[str], str | None]
    filesystem: PythonDetectorFilesystem
    roots: PythonDetectionRoots


@dataclass(frozen=True)
class DetectorContribution:
    """One detector's output: contributed candidates and non-fatal notes."""

    candidates: tuple[tuple[Path, CandidateSource], ...] = ()
    notes: tuple[DetectionNote, ...] = ()


class PythonEnvironmentDetector(Protocol):
    """A read-only interpreter detector behind the shared interface."""

    kind: DetectorKind

    def detect(self, context: DetectionContext) -> DetectorContribution: ...


class InterpreterCandidate(BaseModel):
    """One usable interpreter path, unnormalized and unresolved."""

    path: Path
    source: CandidateSource
    detectors: tuple[DetectorKind, ...] = (DetectorKind.CORE,)


class PythonDetectionResult(BaseModel):
    """Detection outcome for one selected script.

    ``working_directory`` is a recommendation only (the script's parent
    when the script path is absolute and not a directory); callers may
    override it freely. ``notes`` are non-fatal discovery problems in
    detector-execution order.
    """

    script: Path
    candidates: list[InterpreterCandidate] = Field(default_factory=list)
    working_directory: Path | None = None
    notes: list[DetectionNote] = Field(default_factory=list)


class EnvironmentDifference(BaseModel):
    """Structured comparison of two supplied environment mappings.

    ``different`` maps each key whose values disagree to a
    ``(terminal_value, scheduled_value)`` pair. Values are never logged
    or persisted by this module.
    """

    terminal_only: dict[str, str] = Field(default_factory=dict)
    scheduled_only: dict[str, str] = Field(default_factory=dict)
    different: dict[str, tuple[str, str]] = Field(default_factory=dict)


def _ancestors(script: Path) -> list[Path]:
    """The script's parent directory and its ancestors, nearest first."""
    parent = script.parent
    return [parent, *parent.parents]


def nearest_marker_root(
    script: Path,
    filesystem: PythonDetectorFilesystem,
    marker_file: str,
) -> Path | None:
    """The nearest ancestor of ``script`` (parent first) that holds ``marker_file``.

    Returns ``None`` when the script is relative, is itself a directory, or no
    ancestor contains the marker.
    """
    if not script.is_absolute() or filesystem.is_dir(script):
        return None
    for root in _ancestors(script):
        if filesystem.exists(root / marker_file):
            return root
    return None


def project_environment_candidate(
    detection: PythonDetectionResult,
) -> InterpreterCandidate | None:
    """The first venv candidate, if any — the recommendation anchor."""
    return next(
        (
            candidate
            for candidate in detection.candidates
            if candidate.source in (CandidateSource.VENV, CandidateSource.VENV_FALLBACK)
        ),
        None,
    )


def detect_python(
    script: Path,
    *,
    current_interpreter: Path | None = None,
    path_lookup: Callable[[str], str | None] | None = None,
    filesystem: PythonDetectorFilesystem | None = None,
    roots: PythonDetectionRoots | None = None,
) -> PythonDetectionResult:
    """Find candidate interpreters and a default working directory.

    Runs the default detector registry (core, uv, poetry, pipenv, pyenv,
    conda, homebrew) over an injected read-only filesystem view and merges
    their contributions: a path found by several detectors appears once, at
    its first-discovered position, with every discovering detector recorded in
    ``detectors``; notes stay in detector-execution order with exact duplicates
    removed. Paths are reported exactly as given (no symlink resolution).
    """
    from task_scheduler.platform.macos.python_detectors import default_python_detectors

    if current_interpreter is None:
        current_interpreter = Path(sys.executable)
    if path_lookup is None:
        path_lookup = shutil.which
    if filesystem is None:
        filesystem = LocalPythonDetectorFilesystem()
    if roots is None:
        roots = PythonDetectionRoots.default()
    context = DetectionContext(
        script=script,
        current_interpreter=current_interpreter,
        path_lookup=path_lookup,
        filesystem=filesystem,
        roots=roots,
    )
    working_directory = (
        script.parent if script.is_absolute() and not filesystem.is_dir(script) else None
    )

    candidates: list[InterpreterCandidate] = []
    by_spelling: dict[str, InterpreterCandidate] = {}
    notes: list[DetectionNote] = []
    seen_notes: set[tuple[DetectorKind, str]] = set()
    for detector in default_python_detectors():
        contribution = detector.detect(context)
        for path, source in contribution.candidates:
            key = str(path)
            existing = by_spelling.get(key)
            if existing is None:
                candidate = InterpreterCandidate(
                    path=path, source=source, detectors=(detector.kind,)
                )
                by_spelling[key] = candidate
                candidates.append(candidate)
            elif detector.kind not in existing.detectors:
                existing.detectors = existing.detectors + (detector.kind,)
        for note in contribution.notes:
            marker = (note.detector, note.message)
            if marker not in seen_notes:
                seen_notes.add(marker)
                notes.append(note)
    return PythonDetectionResult(
        script=script,
        candidates=candidates,
        working_directory=working_directory,
        notes=notes,
    )


def compare_environments(
    terminal: Mapping[str, str],
    scheduled: Mapping[str, str],
) -> EnvironmentDifference:
    """Compare a terminal environment against a scheduled-job environment.

    Both mappings are supplied by the caller; this function never
    captures a shell environment on its own.
    """
    terminal_only = {key: value for key, value in terminal.items() if key not in scheduled}
    scheduled_only = {key: value for key, value in scheduled.items() if key not in terminal}
    different = {
        key: (terminal[key], scheduled[key])
        for key in terminal
        if key in scheduled and terminal[key] != scheduled[key]
    }
    return EnvironmentDifference(
        terminal_only=terminal_only,
        scheduled_only=scheduled_only,
        different=different,
    )
