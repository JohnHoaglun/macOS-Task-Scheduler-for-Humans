"""Tests for Python-environment detection (all under tmp_path)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from task_scheduler.platform.macos import (
    DetectorKind,
    LocalPythonDetectorFilesystem,
    PythonDetectionResult,
    detect_python,
)

UV_NO_VENV = "a uv project was detected, but no usable .venv interpreter is available"
POETRY_NO_VENV = "a poetry project was detected, but no usable .venv interpreter is available"
UV_PARSE_NOTE = "pyproject.toml could not be read or parsed; uv configuration was ignored"
POETRY_PARSE_NOTE = "pyproject.toml could not be read or parsed; poetry configuration was ignored"

class FakePythonDetectorFilesystem:
    """Dict-backed read-only filesystem for deterministic detector tests."""

    def __init__(
        self,
        files: dict[Path, str],
        executable: set[Path],
        dirs: set[Path] | None = None,
        unreadable: set[Path] | None = None,
    ) -> None:
        self.files = files
        self.executable = executable
        self.dirs = dirs or set()
        self.unreadable = unreadable or set()

    def exists(self, path: Path) -> bool:
        return path in self.files or path in self.dirs or path in self.unreadable

    def is_file(self, path: Path) -> bool:
        return path in self.files

    def is_dir(self, path: Path) -> bool:
        return path in self.dirs

    def is_executable(self, path: Path) -> bool:
        return path in self.executable

    def read_text(self, path: Path) -> str | None:
        if path in self.unreadable:
            return None
        return self.files.get(path)

def _detect(script: Path, filesystem: FakePythonDetectorFilesystem) -> PythonDetectionResult:
    return detect_python(
        script,
        current_interpreter=script.parent / "missing-interpreter",
        path_lookup=_lookup(None),
        filesystem=filesystem,
    )

def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o755)
    return path

def _lookup(target: Path | None) -> Callable[[str], str | None]:
    def which(name: str) -> str | None:
        return str(target) if name == "python3" and target is not None else None

    return which

@pytest.fixture
def script(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    target = project / "report.py"
    _make_executable(target)
    return target

class TestProjectRootWalk:

    def test_table_key_is_ecosystem_specific(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={
                root / "pyproject.toml": '[tool.poetry]\nname = "demo"\n',
                venv_python: "",
            },
            executable={venv_python},
        )
        result = _detect(script, filesystem)
        assert len(result.candidates) == 1
        assert result.candidates[0].detectors == (DetectorKind.CORE, DetectorKind.POETRY)

    def test_directory_script_skips_ecosystem_walk(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": ""}, executable=set(), dirs={root}
        )
        result = _detect(root, filesystem)
        assert result.candidates == []
        assert result.notes == []

class TestEcosystemNotes:

    def test_markers_from_both_detectors_order_notes(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", root / "poetry.lock": ""}, executable=set()
        )
        result = _detect(script, filesystem)
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_NO_VENV),
            (DetectorKind.POETRY, POETRY_NO_VENV),
        ]

    def test_unreadable_pyproject_reports_parse_note_once(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = outer / "inner"
        script = inner / "job.py"
        filesystem = FakePythonDetectorFilesystem(
            files={},
            executable=set(),
            unreadable={inner / "pyproject.toml", outer / "pyproject.toml"},
        )
        result = _detect(script, filesystem)
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_PARSE_NOTE),
            (DetectorKind.POETRY, POETRY_PARSE_NOTE),
        ]

    def test_malformed_pyproject_reports_parse_note(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "pyproject.toml": "not [valid toml"}, executable=set()
        )
        result = _detect(script, filesystem)
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_PARSE_NOTE),
            (DetectorKind.POETRY, POETRY_PARSE_NOTE),
        ]

class TestRegistryAndLocalReader:

    def test_local_reader_roundtrip(self, tmp_path: Path) -> None:
        reader = LocalPythonDetectorFilesystem()
        file = tmp_path / "sample.py"
        file.write_text("print(1)", encoding="utf-8")
        file.chmod(0o700)
        assert reader.exists(file)
        assert reader.is_file(file)
        assert not reader.is_dir(file)
        assert reader.is_executable(file)
        assert reader.read_text(file) == "print(1)"
        missing = tmp_path / "missing.py"
        assert not reader.exists(missing)
        assert reader.read_text(missing) is None
        assert reader.is_dir(tmp_path)
