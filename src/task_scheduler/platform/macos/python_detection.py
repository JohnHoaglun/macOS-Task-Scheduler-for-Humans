"""Python-environment detection for scheduled jobs.

Given a selected script, this module finds candidate interpreters,
recommends a default working directory, and compares two explicitly
supplied environment mappings. It never runs a shell, never imports the
interactive environment into a job, and never mutates domain objects.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class CandidateSource(StrEnum):
    """Where a candidate interpreter came from, in priority order."""

    VENV = ".venv"
    VENV_FALLBACK = "venv"
    CURRENT = "current"
    PATH = "path"


class InterpreterCandidate(BaseModel):
    """One usable interpreter path, unnormalized and unresolved."""

    path: Path
    source: CandidateSource


class PythonDetectionResult(BaseModel):
    """Detection outcome for one selected script.

    ``working_directory`` is a recommendation only (the script's parent
    when the script path is absolute and not a directory); callers may
    override it freely.
    """

    script: Path
    candidates: list[InterpreterCandidate] = Field(default_factory=list)
    working_directory: Path | None = None


class EnvironmentDifference(BaseModel):
    """Structured comparison of two supplied environment mappings.

    ``different`` maps each key whose values disagree to a
    ``(terminal_value, scheduled_value)`` pair. Values are never logged
    or persisted by this module.
    """

    terminal_only: dict[str, str] = Field(default_factory=dict)
    scheduled_only: dict[str, str] = Field(default_factory=dict)
    different: dict[str, tuple[str, str]] = Field(default_factory=dict)


def detect_python(
    script: Path,
    *,
    current_interpreter: Path | None = None,
    path_lookup: Callable[[str], str | None] | None = None,
) -> PythonDetectionResult:
    """Find candidate interpreters and a default working directory.

    Nearby-venv candidates (`.venv`, `venv`) and the working-directory
    recommendation require an absolute, non-directory script path. The
    current interpreter and a PATH-discovered `python3` are always
    considered. Paths are reported exactly as given (no symlink
    resolution) and deduplicated by exact spelling.
    """
    if current_interpreter is None:
        current_interpreter = Path(sys.executable)
    if path_lookup is None:
        path_lookup = shutil.which

    entries: list[tuple[CandidateSource, Path]] = []
    working_directory: Path | None = None
    if script.is_absolute() and not script.is_dir():
        parent = script.parent
        entries.append((CandidateSource.VENV, parent / ".venv" / "bin" / "python"))
        entries.append((CandidateSource.VENV_FALLBACK, parent / "venv" / "bin" / "python"))
        working_directory = parent
    entries.append((CandidateSource.CURRENT, current_interpreter))
    found = path_lookup("python3")
    if found is not None:
        entries.append((CandidateSource.PATH, Path(found)))

    candidates: list[InterpreterCandidate] = []
    seen: set[str] = set()
    for source, path in entries:
        if _is_usable_interpreter(path) and str(path) not in seen:
            seen.add(str(path))
            candidates.append(InterpreterCandidate(path=path, source=source))
    return PythonDetectionResult(
        script=script, candidates=candidates, working_directory=working_directory
    )


def _is_usable_interpreter(path: Path) -> bool:
    """A candidate must be an absolute regular file with exec permission."""
    return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)


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
