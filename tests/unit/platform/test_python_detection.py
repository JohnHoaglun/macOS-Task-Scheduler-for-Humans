"""Tests for Python-environment detection (all under tmp_path)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from task_scheduler.platform.macos import (
    CandidateSource,
    compare_environments,
    detect_python,
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
