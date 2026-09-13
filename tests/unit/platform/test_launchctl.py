"""Unit tests for LaunchAgentBackend (Increment 7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import OK_PROCESS, FakeProcessRunner

from task_scheduler.platform.macos import (
    LaunchAgentBackend,
    LaunchAgentStore,
)


class TestBootstrapPath:
    def test_bootstrap_path_rejects_outside_root(self, tmp_path: Path) -> None:
        store = LaunchAgentStore(tmp_path / "agents")
        runner = FakeProcessRunner(result=OK_PROCESS)
        backend = LaunchAgentBackend(store, runner, uid=1000)
        outside = tmp_path / "elsewhere" / "job.plist"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"data")
        with pytest.raises(ValueError, match="outside the LaunchAgent root"):
            backend.bootstrap_path("io.example.job", outside)
