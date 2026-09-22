"""Unit tests for LaunchAgentBackend (Increment 7)."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest
from tests.fakes import OK_PROCESS, FakeProcessRunner

from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    LAUNCHCTL_TIMEOUT_SECONDS,
    LaunchAgentBackend,
    LaunchAgentStore,
)


class TestCommandDeadline:
    def test_every_command_runs_under_the_shared_deadline(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        backend.status("io.example.job")
        backend.trigger("io.example.job")
        assert runner.specs and all(spec.argv[0] == "/bin/launchctl" for spec in runner.specs)
        assert runner.timeouts == [LAUNCHCTL_TIMEOUT_SECONDS] * len(runner.specs)


class TestBootstrapPath:
    @staticmethod
    def _write(store: LaunchAgentStore, name: str, data: dict[str, object]) -> Path:
        path = store.root / name
        store.root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))
        return path

    def test_bootstrap_path_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        outside = tmp_path / "elsewhere" / "job.plist"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            backend.bootstrap_path("io.example.job", outside)

    def test_bootstrap_path_runs_when_label_matches(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        path = self._write(store, "io.example.job.plist", {"Label": "io.example.job"})
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        result = backend.bootstrap_path("io.example.job", path)
        assert result.process.exit_code == 0
        assert runner.specs[0].argv == [LAUNCHCTL_PATH, "bootstrap", "gui/1000", str(path)]

    @pytest.mark.parametrize(
        "data",
        [
            {"Label": "io.example.other", "ProgramArguments": ["/bin/echo"]},
            {"ProgramArguments": ["/bin/echo"]},
        ],
    )
    def test_bootstrap_path_label_mismatch_raises(
        self, tmp_path: Path, data: dict[str, object]) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        path = self._write(store, "io.example.job.plist", data)
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        with pytest.raises(ValueError, match="plist label does not match"):
            backend.bootstrap_path("io.example.job", path)
        assert runner.specs == []
