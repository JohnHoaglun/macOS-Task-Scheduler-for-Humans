"""Tests for Python-environment detection (all under tmp_path)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.fakes import EMPTY_DETECTION_ROOTS, FakePythonDetectorFilesystem

from task_scheduler.platform.macos import (
    DetectorKind,
    LocalPythonDetectorFilesystem,
    PythonDetectionResult,
    PythonDetectionRoots,
    detect_python,
)
from task_scheduler.platform.macos.python_detection import nearest_marker_root

UV_NO_VENV = "a uv project was detected, but no usable .venv interpreter is available"
POETRY_NO_VENV = "a poetry project was detected, but no usable .venv interpreter is available"
UV_PARSE_NOTE = "pyproject.toml could not be read or parsed; uv configuration was ignored"
POETRY_PARSE_NOTE = "pyproject.toml could not be read or parsed; poetry configuration was ignored"


def _detect(script: Path, filesystem: FakePythonDetectorFilesystem) -> PythonDetectionResult:
    return detect_python(
        script,
        current_interpreter=script.parent / "missing-interpreter",
        path_lookup=_lookup(None),
        filesystem=filesystem,
        roots=EMPTY_DETECTION_ROOTS,
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


class TestDetectionContract:

    def test_default_roots_resolve_the_known_locations(self) -> None:
        home = Path.home()
        roots = PythonDetectionRoots.default()
        assert roots.pyenv == (home / ".pyenv",)
        assert roots.homebrew == (Path("/opt/homebrew"), Path("/usr/local"))
        assert home / "miniconda3" in roots.conda

    def test_nearest_marker_root_returns_nearest_ancestor(self, tmp_path: Path) -> None:
        fs = FakePythonDetectorFilesystem(files={tmp_path / "a" / "uv.lock": ""}, executable=set())
        assert nearest_marker_root(tmp_path / "a" / "b" / "job.py", fs, "uv.lock") == tmp_path / "a"

    def test_nearest_marker_root_none_when_absent_or_invalid(self, tmp_path: Path) -> None:
        fs = FakePythonDetectorFilesystem(files={}, executable=set(), dirs={tmp_path})
        assert nearest_marker_root(tmp_path / "job.py", fs, "uv.lock") is None
        assert nearest_marker_root(Path("relative.py"), fs, "uv.lock") is None
        assert nearest_marker_root(tmp_path, fs, "uv.lock") is None
