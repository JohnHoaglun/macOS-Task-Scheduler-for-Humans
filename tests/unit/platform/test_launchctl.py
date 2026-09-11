"""Unit tests for LaunchAgentBackend (Increment 7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import OK_PROCESS, FakeProcessRunner

from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    LaunchAgentBackend,
    LaunchAgentStore,
    LaunchctlAction,
)
from task_scheduler.platform.macos.process_runner import ProcessResult


class TestBootstrapPath:

    def test_bootstrap_path_success(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"plist-data")
        result = backend.bootstrap_path("io.example.job", plist)
        assert result.action == LaunchctlAction.INSTALL
        assert result.process.exit_code == 0
        assert runner.specs[-1].argv == [
            LAUNCHCTL_PATH,
            "bootstrap",
            "gui/1000",
            str(plist),
        ]

    @pytest.mark.parametrize(
        "label",
        [".", "..", "foo/bar"],
    )
    def test_bootstrap_path_rejects_bad_label(
        self, tmp_path: Path, label: str
    ) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"data")
        with pytest.raises(ValueError, match="Label must not be"):
            backend.bootstrap_path(label, plist)

    def test_bootstrap_path_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        outside = tmp_path / "elsewhere" / "job.plist"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            backend.bootstrap_path("io.example.job", outside)

    def test_bootstrap_path_maps_failure(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        fail = FakeProcessRunner(result=ProcessResult(exit_code=71))
        backend = LaunchAgentBackend(store, fail, uid=1000)
        plist = tmp_path / "agents" / "io.example.job.plist"
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"data")
        result = backend.bootstrap_path("io.example.job", plist)
        assert result.process.exit_code == 71
