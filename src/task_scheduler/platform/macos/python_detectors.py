"""Python interpreter detectors and the default detector registry.

Each detector is read-only: it inspects an injected filesystem view and the
pre-resolved ``PythonDetectionRoots`` to propose interpreter candidates and
non-fatal notes. Detection never runs a shell, never invokes an ecosystem tool
(``pyenv``, ``conda``, ``pipenv``, or any other), never resolves symlinks, and
never mutates domain objects; candidates are recommendations only and are never
applied automatically.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from task_scheduler.platform.macos.python_detection import (
    CandidateSource,
    DetectionContext,
    DetectionNote,
    DetectorContribution,
    DetectorKind,
    PythonDetectorFilesystem,
    PythonEnvironmentDetector,
    _ancestors,
    nearest_marker_root,
)

_NAME_LINE = re.compile(r"^name:\s*(?P<value>.+?)\s*$")


def _is_usable(filesystem: PythonDetectorFilesystem, path: Path) -> bool:
    """A candidate must be an absolute regular file with exec permission."""
    return path.is_absolute() and filesystem.is_file(path) and filesystem.is_executable(path)


def _has_table(data: Mapping[str, object], key: str) -> bool:
    """Whether a parsed ``pyproject.toml`` mapping holds ``tool.<key>``."""
    tool = data.get("tool")
    return isinstance(tool, Mapping) and key in tool


def _parse_pyproject(text: str | None) -> Mapping[str, object] | None:
    """Parse ``pyproject.toml`` text; None means unreadable or malformed."""
    if text is None:
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    return data if isinstance(data, Mapping) else None


def _first_top_level_name(text: str | None) -> str | None:
    """The first top-level ``name:`` value in a Conda environment file, else None."""
    for line in (text or "").splitlines():
        match = _NAME_LINE.match(line)
        if match:
            return match.group("value").strip("'\"") or None
    return None


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


class PyenvPythonDetector:
    """pyenv projects: a ``.python-version`` file selects a named interpreter."""

    kind = DetectorKind.PYENV
    no_interpreter_message = (
        "a pyenv project was detected, but no usable configured interpreter is available"
    )

    def detect(self, context: DetectionContext) -> DetectorContribution:
        root = nearest_marker_root(context.script, context.filesystem, ".python-version")
        if root is None:
            return DetectorContribution()
        name = (context.filesystem.read_text(root / ".python-version") or "").strip()
        if not name or name == "system":
            return self._note()
        for pyenv_root in context.roots.pyenv:
            candidate = pyenv_root / "versions" / name / "bin" / "python"
            if _is_usable(context.filesystem, candidate):
                return DetectorContribution(candidates=((candidate, CandidateSource.VENV),))
        return self._note()

    def _note(self) -> DetectorContribution:
        return DetectorContribution(
            notes=(DetectionNote(detector=self.kind, message=self.no_interpreter_message),)
        )


class CondaPythonDetector:
    """Conda projects: an ``environment.yml``/``.yaml`` with a top-level ``name:``."""

    kind = DetectorKind.CONDA
    no_interpreter_message = (
        "a Conda project was detected, but no usable configured interpreter is available"
    )

    def detect(self, context: DetectionContext) -> DetectorContribution:
        yml_root = nearest_marker_root(context.script, context.filesystem, "environment.yml")
        if yml_root is not None:
            root = yml_root
            marker = "environment.yml"
        else:
            yaml_root = nearest_marker_root(context.script, context.filesystem, "environment.yaml")
            if yaml_root is None:
                return DetectorContribution()
            root = yaml_root
            marker = "environment.yaml"
        name = _first_top_level_name(context.filesystem.read_text(root / marker))
        if name is None:
            return self._note()
        for prefix in context.roots.conda:
            if name == "base":
                candidate = prefix / "bin" / "python"
            else:
                candidate = prefix / "envs" / name / "bin" / "python"
            if _is_usable(context.filesystem, candidate):
                return DetectorContribution(candidates=((candidate, CandidateSource.VENV),))
        return self._note()

    def _note(self) -> DetectorContribution:
        return DetectorContribution(
            notes=(DetectionNote(detector=self.kind, message=self.no_interpreter_message),)
        )


class PipenvPythonDetector:
    """Pipenv projects: a ``Pipfile`` marks the root and its ``.venv`` is used."""

    kind = DetectorKind.PIPENV
    no_venv_message = "a Pipenv project was detected, but no usable .venv interpreter is available"

    def detect(self, context: DetectionContext) -> DetectorContribution:
        root = nearest_marker_root(context.script, context.filesystem, "Pipfile")
        if root is None:
            return DetectorContribution()
        candidate = root / ".venv" / "bin" / "python"
        if _is_usable(context.filesystem, candidate):
            return DetectorContribution(candidates=((candidate, CandidateSource.VENV),))
        return DetectorContribution(
            notes=(DetectionNote(detector=self.kind, message=self.no_venv_message),)
        )


class HomebrewPythonDetector:
    """Homebrew Python: a fixed-prefix ``python3``; contributes nothing without a match."""

    kind = DetectorKind.HOMEBREW

    def detect(self, context: DetectionContext) -> DetectorContribution:
        for prefix in context.roots.homebrew:
            candidate = prefix / "bin" / "python3"
            if _is_usable(context.filesystem, candidate):
                return DetectorContribution(candidates=((candidate, CandidateSource.PATH),))
        return DetectorContribution()


def default_python_detectors() -> tuple[PythonEnvironmentDetector, ...]:
    """The default registry order: core, uv, poetry, pipenv, pyenv, conda, homebrew."""
    return (
        CorePythonDetector(),
        UvPythonDetector(),
        PoetryPythonDetector(),
        PipenvPythonDetector(),
        PyenvPythonDetector(),
        CondaPythonDetector(),
        HomebrewPythonDetector(),
    )
