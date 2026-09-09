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
import tomllib
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


def _is_usable(filesystem: PythonDetectorFilesystem, path: Path) -> bool:
    """A candidate must be an absolute regular file with exec permission."""
    return path.is_absolute() and filesystem.is_file(path) and filesystem.is_executable(path)


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


def _has_table(data: Mapping[str, object], key: str) -> bool:
    """Whether a parsed ``pyproject.toml`` mapping holds ``tool.<key>``."""
    tool = data.get("tool")
    return isinstance(tool, Mapping) and key in tool


class CorePythonDetector:
    """The legacy discovery: nearby venvs, the current interpreter, PATH."""

    kind = DetectorKind.CORE

    def detect(self, context: DetectionContext) -> DetectorContribution:
        entries: list[tuple[CandidateSource, Path]] = []
        if context.script.is_absolute() and not context.filesystem.is_dir(context.script):
            parent = context.script.parent
            entries.append((CandidateSource.VENV, parent / ".venv" / "bin" / "python"))
            entries.append((CandidateSource.VENV_FALLBACK, parent / "venv" / "bin" / "python"))
        entries.append((CandidateSource.CURRENT, context.current_interpreter))
        found = context.path_lookup("python3")
        if found is not None:
            entries.append((CandidateSource.PATH, Path(found)))
        return DetectorContribution(
            candidates=tuple(
                (path, source) for source, path in entries if _is_usable(context.filesystem, path)
            )
        )


class _MarkerDetector:
    """Shared nearest-project-root walk for lock-file and config-table markers.

    The first ancestor holding the marker file (or the config table) is the
    project root; only ``<root>/.venv/bin/python`` is then considered.
    """

    kind: DetectorKind
    marker_file: str
    table_key: str
    no_venv_message: str
    parse_failure_message: str

    def detect(self, context: DetectionContext) -> DetectorContribution:
        if not context.script.is_absolute() or context.filesystem.is_dir(context.script):
            return DetectorContribution()
        notes: list[DetectionNote] = []
        parse_noted = False
        for root in _ancestors(context.script):
            if context.filesystem.exists(root / self.marker_file):
                return self._venv_contribution(context, root, notes)
            pyproject = root / "pyproject.toml"
            if not context.filesystem.exists(pyproject):
                continue
            data = _parse_pyproject(context.filesystem.read_text(pyproject))
            if data is None:
                if not parse_noted:
                    notes.append(
                        DetectionNote(detector=self.kind, message=self.parse_failure_message)
                    )
                    parse_noted = True
                continue
            if _has_table(data, self.table_key):
                return self._venv_contribution(context, root, notes)
        return DetectorContribution(notes=tuple(notes))

    def _venv_contribution(
        self, context: DetectionContext, root: Path, notes: list[DetectionNote]
    ) -> DetectorContribution:
        candidate = root / ".venv" / "bin" / "python"
        if _is_usable(context.filesystem, candidate):
            return DetectorContribution(
                candidates=((candidate, CandidateSource.VENV),), notes=tuple(notes)
            )
        return DetectorContribution(
            notes=(
                *notes,
                DetectionNote(detector=self.kind, message=self.no_venv_message),
            )
        )


def _parse_pyproject(text: str | None) -> Mapping[str, object] | None:
    """Parse ``pyproject.toml`` text; None means unreadable or malformed."""
    if text is None:
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    return data if isinstance(data, Mapping) else None


class UvPythonDetector(_MarkerDetector):
    """uv projects: a ``uv.lock`` or a ``[tool.uv]`` table marks the root."""

    kind = DetectorKind.UV
    marker_file = "uv.lock"
    table_key = "uv"
    no_venv_message = "a uv project was detected, but no usable .venv interpreter is available"
    parse_failure_message = (
        "pyproject.toml could not be read or parsed; uv configuration was ignored"
    )


class PoetryPythonDetector(_MarkerDetector):
    """Poetry projects: a ``poetry.lock`` or a ``[tool.poetry]`` table marks the root."""

    kind = DetectorKind.POETRY
    marker_file = "poetry.lock"
    table_key = "poetry"
    no_venv_message = "a poetry project was detected, but no usable .venv interpreter is available"
    parse_failure_message = (
        "pyproject.toml could not be read or parsed; poetry configuration was ignored"
    )


def default_python_detectors() -> tuple[PythonEnvironmentDetector, ...]:
    """The default registry order: core, then uv, then Poetry."""
    return (CorePythonDetector(), UvPythonDetector(), PoetryPythonDetector())


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

    Runs the default detector registry (core, uv, Poetry) over an injected
    read-only filesystem view and merges their contributions: a path found
    by several detectors appears once, at its first-discovered position,
    with every discovering detector recorded in ``detectors``; notes stay
    in detector-execution order with exact duplicates removed. Paths are
    reported exactly as given (no symlink resolution).
    """
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
