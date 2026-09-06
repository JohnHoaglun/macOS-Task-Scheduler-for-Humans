"""Tests for Python-environment detection (all under tmp_path)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from task_scheduler.platform.macos import (
    CandidateSource,
    DetectorKind,
    InterpreterCandidate,
    LocalPythonDetectorFilesystem,
    PythonDetectionResult,
    compare_environments,
    default_python_detectors,
    detect_python,
    project_environment_candidate,
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


def _fake_interpreter(tmp_path: Path) -> Path:
    return _make_executable(tmp_path / "current.py")


class TestCandidateDiscovery:
    def test_priority_order_with_all_sources(self, script: Path, tmp_path: Path) -> None:
        _make_executable(script.parent / ".venv" / "bin" / "python")
        _make_executable(script.parent / "venv" / "bin" / "python")
        current = _fake_interpreter(tmp_path)
        path_python = _make_executable(tmp_path / "usr" / "bin" / "python3")
        result = detect_python(
            script, current_interpreter=current, path_lookup=_lookup(path_python)
        )
        assert [candidate.source for candidate in result.candidates] == [
            CandidateSource.VENV,
            CandidateSource.VENV_FALLBACK,
            CandidateSource.CURRENT,
            CandidateSource.PATH,
        ]
        assert result.candidates[0].path == script.parent / ".venv" / "bin" / "python"

    def test_only_venv_fallback(self, script: Path, tmp_path: Path) -> None:
        _make_executable(script.parent / "venv" / "bin" / "python")
        result = detect_python(
            script, current_interpreter=_fake_interpreter(tmp_path), path_lookup=_lookup(None)
        )
        assert [candidate.source for candidate in result.candidates] == [
            CandidateSource.VENV_FALLBACK,
            CandidateSource.CURRENT,
        ]

    def test_missing_everything(self, script: Path, tmp_path: Path) -> None:
        result = detect_python(
            script,
            current_interpreter=tmp_path / "missing.py",
            path_lookup=_lookup(None),
        )
        assert result.candidates == []
        assert result.working_directory == script.parent

    def test_non_executable_rejected(self, script: Path, tmp_path: Path) -> None:
        venv_python = _make_executable(script.parent / ".venv" / "bin" / "python")
        venv_python.chmod(0o644)
        result = detect_python(
            script, current_interpreter=_fake_interpreter(tmp_path), path_lookup=_lookup(None)
        )
        assert [candidate.source for candidate in result.candidates] == [CandidateSource.CURRENT]

    def test_relative_current_rejected(self, script: Path) -> None:
        result = detect_python(
            script, current_interpreter=Path("relative.py"), path_lookup=_lookup(None)
        )
        assert result.candidates == []

    def test_symlink_candidate_accepted(self, script: Path, tmp_path: Path) -> None:
        target = _make_executable(tmp_path / "real" / "python")
        link = script.parent / ".venv" / "bin" / "python"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        result = detect_python(
            script, current_interpreter=_fake_interpreter(tmp_path), path_lookup=_lookup(None)
        )
        assert [candidate.source for candidate in result.candidates] == [
            CandidateSource.VENV,
            CandidateSource.CURRENT,
        ]
        assert result.candidates[0].path == link

    def test_dedup_when_current_is_venv(self, script: Path, tmp_path: Path) -> None:
        venv_python = _make_executable(script.parent / ".venv" / "bin" / "python")
        result = detect_python(
            script, current_interpreter=venv_python, path_lookup=_lookup(None)
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].source is CandidateSource.VENV
        assert result.candidates[0].path == venv_python


class TestScriptShapeRules:
    def test_relative_script_skips_venv_candidates(self, tmp_path: Path) -> None:
        result = detect_python(
            Path("relative/report.py"),
            current_interpreter=_fake_interpreter(tmp_path),
            path_lookup=_lookup(None),
        )
        assert [candidate.source for candidate in result.candidates] == [CandidateSource.CURRENT]
        assert result.working_directory is None

    def test_directory_script_skips_venv_candidates(self, script: Path, tmp_path: Path) -> None:
        _make_executable(script.parent / ".venv" / "bin" / "python")
        result = detect_python(
            script.parent,
            current_interpreter=_fake_interpreter(tmp_path),
            path_lookup=_lookup(None),
        )
        assert [candidate.source for candidate in result.candidates] == [CandidateSource.CURRENT]
        assert result.working_directory is None


class TestWorkingDirectory:
    def test_default_is_script_parent(self, script: Path, tmp_path: Path) -> None:
        result = detect_python(
            script,
            current_interpreter=_fake_interpreter(tmp_path),
            path_lookup=_lookup(None),
        )
        assert result.working_directory == script.parent
        assert result.script == script


class TestDefaultDependencies:
    def test_default_current_interpreter_is_sys_executable(
        self, script: Path, tmp_path: Path
    ) -> None:
        result = detect_python(script, path_lookup=_lookup(None))
        assert len(result.candidates) == 1
        assert result.candidates[0].path == Path(sys.executable)
        assert result.candidates[0].source is CandidateSource.CURRENT

    def test_default_path_lookup(self, script: Path, tmp_path: Path) -> None:
        result = detect_python(script, current_interpreter=_fake_interpreter(tmp_path))
        assert result.working_directory == script.parent
        assert CandidateSource.CURRENT in [c.source for c in result.candidates]


class TestCompareEnvironments:
    def test_terminal_only(self) -> None:
        diff = compare_environments({"PATH": "/bin", "TERM": "xterm"}, {"PATH": "/bin"})
        assert diff.terminal_only == {"TERM": "xterm"}
        assert diff.scheduled_only == {}
        assert diff.different == {}

    def test_scheduled_only(self) -> None:
        diff = compare_environments({"PATH": "/bin"}, {"PATH": "/bin", "FOO": "bar"})
        assert diff.scheduled_only == {"FOO": "bar"}
        assert diff.terminal_only == {}

    def test_different_values(self) -> None:
        diff = compare_environments({"PATH": "/bin"}, {"PATH": "/usr/bin"})
        assert diff.different == {"PATH": ("/bin", "/usr/bin")}
        assert diff.terminal_only == {}
        assert diff.scheduled_only == {}

    def test_identical(self) -> None:
        diff = compare_environments({"PATH": "/bin"}, {"PATH": "/bin"})
        assert diff.terminal_only == {}
        assert diff.scheduled_only == {}
        assert diff.different == {}

    def test_mixed(self) -> None:
        diff = compare_environments(
            {"PATH": "/bin", "TERM": "xterm", "OLD": "a"},
            {"PATH": "/usr/bin", "FOO": "bar", "OLD": "b"},
        )
        assert diff.terminal_only == {"TERM": "xterm"}
        assert diff.scheduled_only == {"FOO": "bar"}
        assert diff.different == {"PATH": ("/bin", "/usr/bin"), "OLD": ("a", "b")}


class TestMergedProvenance:
    def test_uv_shares_core_venv_candidate(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", venv_python: ""}, executable={venv_python}
        )
        result = _detect(script, filesystem)
        assert len(result.candidates) == 1
        assert result.candidates[0].path == venv_python
        assert result.candidates[0].source is CandidateSource.VENV
        assert result.candidates[0].detectors == (DetectorKind.CORE, DetectorKind.UV)
        assert result.notes == []

    def test_pure_uv_candidate_keeps_venv_source(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "src" / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", venv_python: ""}, executable={venv_python}
        )
        result = _detect(script, filesystem)
        assert len(result.candidates) == 1
        assert result.candidates[0].path == venv_python
        assert result.candidates[0].source is CandidateSource.VENV
        assert result.candidates[0].detectors == (DetectorKind.UV,)

    def test_uv_and_poetry_merge_on_one_candidate(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "src" / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", root / "poetry.lock": "", venv_python: ""},
            executable={venv_python},
        )
        result = _detect(script, filesystem)
        assert len(result.candidates) == 1
        assert result.candidates[0].detectors == (DetectorKind.UV, DetectorKind.POETRY)

    def test_core_candidate_defaults_to_core_only(self, tmp_path: Path) -> None:
        script = tmp_path / "job.py"
        venv_python = script.parent / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={venv_python: ""}, executable={venv_python}
        )
        result = _detect(script, filesystem)
        assert result.candidates[0].detectors == (DetectorKind.CORE,)


class TestProjectRootWalk:
    def test_nearest_uv_root_wins(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = outer / "inner"
        script = inner / "job.py"
        outer_venv = outer / ".venv" / "bin" / "python"
        inner_venv = inner / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={
                outer / "uv.lock": "",
                inner / "uv.lock": "",
                outer_venv: "",
                inner_venv: "",
            },
            executable={outer_venv, inner_venv},
        )
        result = _detect(script, filesystem)
        assert [candidate.path for candidate in result.candidates] == [inner_venv]

    def test_nearest_poetry_root_wins(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = outer / "inner"
        script = inner / "job.py"
        outer_venv = outer / ".venv" / "bin" / "python"
        inner_venv = inner / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={
                outer / "poetry.lock": "",
                inner / "poetry.lock": "",
                outer_venv: "",
                inner_venv: "",
            },
            executable={outer_venv, inner_venv},
        )
        result = _detect(script, filesystem)
        assert [candidate.path for candidate in result.candidates] == [inner_venv]

    def test_config_table_marks_root_over_outer_lock(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = outer / "inner"
        script = inner / "job.py"
        inner_venv = inner / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={
                outer / "uv.lock": "",
                inner / "pyproject.toml": '[tool.uv]\npackage = true\n',
                inner_venv: "",
            },
            executable={inner_venv},
        )
        result = _detect(script, filesystem)
        assert [candidate.path for candidate in result.candidates] == [inner_venv]

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

    def test_relative_script_skips_ecosystem_walk(self) -> None:
        filesystem = FakePythonDetectorFilesystem(files={"uv.lock": ""}, executable=set())
        result = _detect(Path("relative/job.py"), filesystem)
        assert result.candidates == []
        assert result.notes == []
        assert result.working_directory is None

    def test_directory_script_skips_ecosystem_walk(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": ""}, executable=set(), dirs={root}
        )
        result = _detect(root, filesystem)
        assert result.candidates == []
        assert result.notes == []


class TestEcosystemNotes:
    def test_uv_project_without_venv_reports_note(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": ""}, executable=set()
        )
        result = _detect(script, filesystem)
        assert result.candidates == []
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_NO_VENV)
        ]

    def test_uv_project_with_non_executable_venv_reports_note(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", venv_python: ""}, executable=set()
        )
        result = _detect(script, filesystem)
        assert result.candidates == []
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_NO_VENV)
        ]

    def test_poetry_project_without_venv_reports_note(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "job.py"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "poetry.lock": ""}, executable=set()
        )
        result = _detect(script, filesystem)
        assert result.candidates == []
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.POETRY, POETRY_NO_VENV)
        ]

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

    def test_parse_failure_does_not_stop_walk(self, tmp_path: Path) -> None:
        outer = tmp_path / "outer"
        inner = outer / "inner"
        script = inner / "job.py"
        outer_venv = outer / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={
                inner / "pyproject.toml": "broken {{{",
                outer / "pyproject.toml": "[tool.uv]\npackage = true\n",
                outer_venv: "",
            },
            executable={outer_venv},
        )
        result = _detect(script, filesystem)
        assert [candidate.path for candidate in result.candidates] == [outer_venv]
        assert [(note.detector, note.message) for note in result.notes] == [
            (DetectorKind.UV, UV_PARSE_NOTE),
            (DetectorKind.POETRY, POETRY_PARSE_NOTE),
        ]


class TestProjectEnvironmentCandidate:
    def test_prefers_first_venv_candidate(self, tmp_path: Path) -> None:
        venv = InterpreterCandidate(
            path=tmp_path / ".venv" / "bin" / "python",
            source=CandidateSource.VENV,
            detectors=(DetectorKind.UV,),
        )
        detection = PythonDetectionResult(
            script=tmp_path / "job.py",
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "current", source=CandidateSource.CURRENT
                ),
                venv,
            ],
        )
        assert project_environment_candidate(detection) is venv

    def test_falls_back_to_venv_fallback(self, tmp_path: Path) -> None:
        detection = PythonDetectionResult(
            script=tmp_path / "job.py",
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "venv" / "bin" / "python",
                    source=CandidateSource.VENV_FALLBACK,
                )
            ],
        )
        assert project_environment_candidate(detection) is detection.candidates[0]

    def test_none_when_no_venv_candidate(self, tmp_path: Path) -> None:
        detection = PythonDetectionResult(
            script=tmp_path / "job.py",
            candidates=[
                InterpreterCandidate(
                    path=tmp_path / "current", source=CandidateSource.CURRENT
                )
            ],
        )
        assert project_environment_candidate(detection) is None

    def test_pure_uv_candidate_qualifies_via_source(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        script = root / "src" / "job.py"
        venv_python = root / ".venv" / "bin" / "python"
        filesystem = FakePythonDetectorFilesystem(
            files={root / "uv.lock": "", venv_python: ""}, executable={venv_python}
        )
        result = _detect(script, filesystem)
        assert project_environment_candidate(result) is result.candidates[0]


class TestRegistryAndLocalReader:
    def test_default_registry_order(self) -> None:
        assert [detector.kind for detector in default_python_detectors()] == [
            DetectorKind.CORE,
            DetectorKind.UV,
            DetectorKind.POETRY,
        ]

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
