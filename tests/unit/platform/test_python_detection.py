"""Tests for Python-environment detection (all under tmp_path)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.fakes import EMPTY_DETECTION_ROOTS, FakePythonDetectorFilesystem, detect_context

from task_scheduler.platform.macos import (
    CandidateSource,
    DetectorContribution,
    DetectorKind,
    LocalPythonDetectorFilesystem,
    PythonDetectionResult,
    PythonDetectionRoots,
    detect_python,
)
from task_scheduler.platform.macos.python_detection import nearest_marker_root
from task_scheduler.platform.macos.python_detectors import (
    CondaPythonDetector,
    HomebrewPythonDetector,
    PipenvPythonDetector,
    PyenvPythonDetector,
    default_python_detectors,
)

UV_NO_VENV = "a uv project was detected, but no usable .venv interpreter is available"
POETRY_NO_VENV = "a poetry project was detected, but no usable .venv interpreter is available"
UV_PARSE_NOTE = "pyproject.toml could not be read or parsed; uv configuration was ignored"
POETRY_PARSE_NOTE = "pyproject.toml could not be read or parsed; poetry configuration was ignored"
PYENV_NO_INTERP = "a pyenv project was detected, but no usable configured interpreter is available"
CONDA_NO_INTERP = "a Conda project was detected, but no usable configured interpreter is available"
PIPENV_NO_VENV = "a Pipenv project was detected, but no usable .venv interpreter is available"


def _detect(script: Path, filesystem: FakePythonDetectorFilesystem) -> PythonDetectionResult:
    return detect_python(
        script,
        current_interpreter=script.parent / "missing-interpreter",
        path_lookup=_lookup(None),
        filesystem=filesystem,
        roots=EMPTY_DETECTION_ROOTS,
    )

def _lookup(target: Path | None) -> Callable[[str], str | None]:
    def which(name: str) -> str | None:
        return str(target) if name == "python3" and target is not None else None

    return which

def _roots(pyenv: tuple = (), conda: tuple = (), homebrew: tuple = ()) -> PythonDetectionRoots:
    return PythonDetectionRoots(pyenv=pyenv, conda=conda, homebrew=homebrew)

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


class TestPyenvDetector:

    @pytest.mark.parametrize(
        "detector_cls", [PyenvPythonDetector, CondaPythonDetector, PipenvPythonDetector]
    )
    def test_no_marker_contributes_nothing(self, tmp_path: Path, detector_cls) -> None:
        fs = FakePythonDetectorFilesystem(files={}, executable=set())
        context = detect_context(tmp_path / "job.py", fs, EMPTY_DETECTION_ROOTS)
        assert detector_cls().detect(context) == DetectorContribution()

    def test_system_name_reports_note(self, tmp_path: Path) -> None:
        files = {tmp_path / ".python-version": "system"}
        fs = FakePythonDetectorFilesystem(files=files, executable=set())
        context = detect_context(tmp_path / "job.py", fs, EMPTY_DETECTION_ROOTS)
        assert [n.message for n in PyenvPythonDetector().detect(context).notes] == [PYENV_NO_INTERP]

    def test_named_version_selects_usable_interpreter(self, tmp_path: Path) -> None:
        interp = tmp_path / "pyenv" / "versions" / "3.12" / "bin" / "python"
        files = {tmp_path / ".python-version": "3.12", interp: ""}
        fs = FakePythonDetectorFilesystem(files=files, executable={interp})
        context = detect_context(tmp_path / "job.py", fs, _roots(pyenv=(tmp_path / "pyenv",)))
        assert PyenvPythonDetector().detect(context).candidates == ((interp, CandidateSource.VENV),)

    def test_named_version_without_usable_interpreter_reports_note(self, tmp_path: Path) -> None:
        files = {tmp_path / ".python-version": "3.12"}
        fs = FakePythonDetectorFilesystem(files=files, executable=set())
        context = detect_context(tmp_path / "job.py", fs, _roots(pyenv=(tmp_path / "pyenv",)))
        assert [n.message for n in PyenvPythonDetector().detect(context).notes] == [PYENV_NO_INTERP]


class TestCondaDetector:

    def test_base_env_selects_prefix_python(self, tmp_path: Path) -> None:
        prefix = tmp_path / "conda"
        interp = prefix / "bin" / "python"
        files = {tmp_path / "environment.yml": "name: base\n", interp: ""}
        fs = FakePythonDetectorFilesystem(files=files, executable={interp})
        context = detect_context(tmp_path / "job.py", fs, _roots(conda=(prefix,)))
        assert CondaPythonDetector().detect(context).candidates == ((interp, CandidateSource.VENV),)

    def test_named_env_from_yaml_selects_env_python(self, tmp_path: Path) -> None:
        prefix = tmp_path / "conda"
        interp = prefix / "envs" / "ml" / "bin" / "python"
        text = "channels:\n  - defaults\nname: ml\n"
        files = {tmp_path / "environment.yaml": text, interp: ""}
        fs = FakePythonDetectorFilesystem(files=files, executable={interp})
        context = detect_context(tmp_path / "job.py", fs, _roots(conda=(prefix,)))
        assert CondaPythonDetector().detect(context).candidates == ((interp, CandidateSource.VENV),)

    def test_missing_top_level_name_reports_note(self, tmp_path: Path) -> None:
        files = {tmp_path / "environment.yml": "channels:\n  - defaults\n"}
        fs = FakePythonDetectorFilesystem(files=files, executable=set())
        context = detect_context(tmp_path / "job.py", fs, _roots(conda=(tmp_path / "conda",)))
        assert [n.message for n in CondaPythonDetector().detect(context).notes] == [CONDA_NO_INTERP]

    def test_named_env_without_usable_interpreter_reports_note(self, tmp_path: Path) -> None:
        files = {tmp_path / "environment.yml": "name: ml\n"}
        fs = FakePythonDetectorFilesystem(files=files, executable=set())
        roots = _roots(conda=(tmp_path / "c1", tmp_path / "c2"))
        context = detect_context(tmp_path / "job.py", fs, roots)
        assert [n.message for n in CondaPythonDetector().detect(context).notes] == [CONDA_NO_INTERP]


class TestPipenvDetector:

    def test_uses_project_venv(self, tmp_path: Path) -> None:
        interp = tmp_path / ".venv" / "bin" / "python"
        files = {tmp_path / "Pipfile": "[packages]\n", interp: ""}
        fs = FakePythonDetectorFilesystem(files=files, executable={interp})
        context = detect_context(tmp_path / "job.py", fs, EMPTY_DETECTION_ROOTS)
        contribution = PipenvPythonDetector().detect(context)
        assert contribution.candidates == ((interp, CandidateSource.VENV),)

    def test_missing_venv_reports_note(self, tmp_path: Path) -> None:
        files = {tmp_path / "Pipfile": "[packages]\n"}
        fs = FakePythonDetectorFilesystem(files=files, executable=set())
        context = detect_context(tmp_path / "job.py", fs, EMPTY_DETECTION_ROOTS)
        assert [n.message for n in PipenvPythonDetector().detect(context).notes] == [PIPENV_NO_VENV]


class TestHomebrewDetector:

    def test_uses_first_usable_prefix(self, tmp_path: Path) -> None:
        interp = tmp_path / "h2" / "bin" / "python3"
        files = {interp: ""}
        fs = FakePythonDetectorFilesystem(files=files, executable={interp})
        roots = _roots(homebrew=(tmp_path / "h1", tmp_path / "h2"))
        context = detect_context(tmp_path / "job.py", fs, roots)
        contribution = HomebrewPythonDetector().detect(context)
        assert contribution.candidates == ((interp, CandidateSource.PATH),)

    def test_no_prefix_matches_contributes_nothing(self, tmp_path: Path) -> None:
        fs = FakePythonDetectorFilesystem(files={}, executable=set())
        roots = _roots(homebrew=(tmp_path / "h1", tmp_path / "h2"))
        context = detect_context(tmp_path / "job.py", fs, roots)
        assert HomebrewPythonDetector().detect(context) == DetectorContribution()


class TestRegistryOrder:

    def test_default_registry_order(self) -> None:
        assert [d.kind for d in default_python_detectors()] == [
            DetectorKind.CORE, DetectorKind.UV, DetectorKind.POETRY,
            DetectorKind.PIPENV, DetectorKind.PYENV, DetectorKind.CONDA, DetectorKind.HOMEBREW,
        ]
