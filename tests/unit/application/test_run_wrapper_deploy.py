"""Tests for deployment of the launchd run wrapper."""

from __future__ import annotations

from pathlib import Path

from task_scheduler.application import run_wrapper_deploy
from task_scheduler.application.run_wrapper_deploy import (
    default_wrapper_path,
    ensure_run_wrapper,
)
from task_scheduler.platform.macos.run_wrapper import WRAPPER_BASENAME


def _source_bytes() -> bytes:
    source = (
        Path(run_wrapper_deploy.__file__).resolve().parents[1]
        / "platform"
        / "macos"
        / WRAPPER_BASENAME
    )
    return source.read_bytes()

class TestDefaultWrapperPath:
    def test_is_the_local_app_bin(self) -> None:
        path = default_wrapper_path()
        assert path.name == WRAPPER_BASENAME
        assert path.parent.name == "bin"
        assert "Application Support" in str(path)
        assert str(path).startswith(str(Path.home()))

class TestEnsureRunWrapper:
    def test_deploys_executable_copy(self, tmp_path: Path) -> None:
        destination = ensure_run_wrapper(tmp_path / "bin" / "run_wrapper.py")
        assert destination == tmp_path / "bin" / "run_wrapper.py"
        assert destination.read_bytes() == _source_bytes()
        assert destination.read_bytes().startswith(b"#!")
        assert destination.stat().st_mode & 0o111 == 0o111

    def test_idempotent_when_up_to_date(self, tmp_path: Path) -> None:
        destination = ensure_run_wrapper(tmp_path / "run_wrapper.py")
        first_mtime = destination.stat().st_mtime_ns
        assert ensure_run_wrapper(destination) == destination
        assert destination.stat().st_mtime_ns == first_mtime

    def test_overwrites_stale_deployment(self, tmp_path: Path) -> None:
        destination = tmp_path / "run_wrapper.py"
        destination.write_bytes(b"stale")
        result = ensure_run_wrapper(destination)
        assert result.read_bytes() == _source_bytes()

    def test_accepts_str_destination(self, tmp_path: Path) -> None:
        assert ensure_run_wrapper(str(tmp_path / "run_wrapper.py")).parent == tmp_path
