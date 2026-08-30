"""Unit tests for the launchctl adapter (Increment 7).

All tests use a fake runner and temporary store roots: no test invokes the
real ``/bin/launchctl`` or touches the real user LaunchAgents directory.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from task_scheduler.domain import ShellCommand
from task_scheduler.platform.macos import (
    LAUNCHCTL_PATH,
    LaunchAgentBackend,
    LaunchAgentStore,
    LaunchctlAction,
    ProcessLaunchFailure,
    ProcessResult,
)
from tests.conftest import make_job
from tests.fakes import FakeProcessRunner

UID = 1000
TEST_LABEL = "io.github.mactaskscheduler.test.unit"


def _process(exit_code: int | None = 0, **kwargs: object) -> ProcessResult:
    return ProcessResult(
        exit_code=exit_code,
        duration=timedelta(0),
        launch_failure=kwargs.pop("launch_failure", None),
        **kwargs,
    )


def _store(tmp_path: Path) -> LaunchAgentStore:
    return LaunchAgentStore(tmp_path / "agents")


def _backend(tmp_path: Path, runner: FakeProcessRunner) -> LaunchAgentBackend:
    return LaunchAgentBackend(_store(tmp_path), runner, uid=UID)


class TestCommandConstruction:
    def test_install_argv(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(_process())
        backend = _backend(tmp_path, runner)

        backend.install(make_job(label=TEST_LABEL))

        (spec,) = runner.specs
        assert spec.argv == [
            LAUNCHCTL_PATH,
            "bootstrap",
            f"gui/{UID}",
            str(tmp_path / "agents" / f"{TEST_LABEL}.plist"),
        ]

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("uninstall", ["bootout", f"gui/{UID}/{TEST_LABEL}"]),
            ("status", ["print", f"gui/{UID}/{TEST_LABEL}"]),
            ("enable", ["enable", f"gui/{UID}/{TEST_LABEL}"]),
            ("disable", ["disable", f"gui/{UID}/{TEST_LABEL}"]),
            ("trigger", ["kickstart", "-k", f"gui/{UID}/{TEST_LABEL}"]),
        ],
    )
    def test_lifecycle_argv(
        self,
        tmp_path: Path,
        method: str,
        expected: list[str],
    ) -> None:
        runner = FakeProcessRunner(_process())
        backend = _backend(tmp_path, runner)

        getattr(backend, method)(TEST_LABEL)

        (spec,) = runner.specs
        assert spec.argv == [LAUNCHCTL_PATH, *expected]

    def test_exact_command_spec_empty_environment_no_cwd(
        self, tmp_path: Path
    ) -> None:
        runner = FakeProcessRunner(_process())
        backend = _backend(tmp_path, runner)

        backend.enable(TEST_LABEL)

        (spec,) = runner.specs
        assert spec.environment == {}
        assert spec.working_directory is None

    def test_default_uid_domain(self, tmp_path: Path) -> None:
        backend = LaunchAgentBackend(
            _store(tmp_path), FakeProcessRunner(_process())
        )
        assert backend.domain == f"gui/{os.getuid()}"

    def test_injected_uid_domain(self, tmp_path: Path) -> None:
        backend = _backend(tmp_path, FakeProcessRunner(_process()))
        assert backend.domain == f"gui/{UID}"


class TestInstall:
    def test_writes_persistently_stored_plist_before_bootstrap(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        runner = FakeProcessRunner(_process())
        backend = LaunchAgentBackend(store, runner, uid=UID)
        job = make_job(label=TEST_LABEL)

        result = backend.install(job)

        assert result.action is LaunchctlAction.INSTALL
        assert result.process.exit_code == 0
        assert store.destination_for(TEST_LABEL).is_file()

    def test_storage_conflict_stops_before_launchctl(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        runner = FakeProcessRunner(_process())
        backend = LaunchAgentBackend(store, runner, uid=UID)
        job = make_job(label=TEST_LABEL)
        store.write(job)

        with pytest.raises(FileExistsError):
            backend.install(job)

        assert runner.specs == []

    def test_failed_bootstrap_retains_written_plist(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        runner = FakeProcessRunner(_process(exit_code=3))
        backend = LaunchAgentBackend(store, runner, uid=UID)

        result = backend.install(make_job(label=TEST_LABEL))

        assert result.process.exit_code == 3
        assert store.destination_for(TEST_LABEL).is_file()


class TestUninstall:
    def test_successful_bootout_removes_plist(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write(make_job(label=TEST_LABEL))
        runner = FakeProcessRunner(_process(exit_code=0))
        backend = LaunchAgentBackend(store, runner, uid=UID)

        result = backend.uninstall(TEST_LABEL)

        assert result.action is LaunchctlAction.UNINSTALL
        assert result.process.exit_code == 0
        assert not store.destination_for(TEST_LABEL).exists()

    def test_failed_bootout_retains_plist(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write(make_job(label=TEST_LABEL))
        runner = FakeProcessRunner(_process(exit_code=3))
        backend = LaunchAgentBackend(store, runner, uid=UID)

        result = backend.uninstall(TEST_LABEL)

        assert result.process.exit_code == 3
        assert store.destination_for(TEST_LABEL).is_file()

    def test_bootout_failure_returns_bootout_result_not_exception(
        self, tmp_path: Path
    ) -> None:
        runner = FakeProcessRunner(_process(exit_code=5, stderr="not loaded"))
        backend = _backend(tmp_path, runner)

        result = backend.uninstall(TEST_LABEL)

        assert result.process.exit_code == 5
        assert result.process.stderr == "not loaded"

    def test_sequential_actions_recorded_in_order(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write(make_job(label=TEST_LABEL))
        runner = FakeProcessRunner(
            results=[_process(exit_code=3), _process(exit_code=0)]
        )
        backend = LaunchAgentBackend(store, runner, uid=UID)

        failed = backend.uninstall(TEST_LABEL)
        ok = backend.uninstall(TEST_LABEL)

        assert failed.process.exit_code == 3
        assert ok.process.exit_code == 0
        assert [spec.argv[1] for spec in runner.specs] == ["bootout", "bootout"]
        assert not store.destination_for(TEST_LABEL).exists()


class TestPhaseMethods:
    def test_bootout_argv_action_and_no_plist_touch(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write(make_job(label=TEST_LABEL))
        runner = FakeProcessRunner(_process(exit_code=3))
        backend = LaunchAgentBackend(store, runner, uid=UID)

        result = backend.bootout(TEST_LABEL)

        assert result.action is LaunchctlAction.UNINSTALL
        assert result.process.exit_code == 3
        (spec,) = runner.specs
        assert spec.argv == [LAUNCHCTL_PATH, "bootout", f"gui/{UID}/{TEST_LABEL}"]
        assert store.destination_for(TEST_LABEL).is_file()

    def test_bootstrap_argv_and_action(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.write(make_job(label=TEST_LABEL))
        runner = FakeProcessRunner(_process())
        backend = LaunchAgentBackend(store, runner, uid=UID)

        result = backend.bootstrap(TEST_LABEL)

        assert result.action is LaunchctlAction.INSTALL
        assert result.process.exit_code == 0
        (spec,) = runner.specs
        assert spec.argv == [
            LAUNCHCTL_PATH,
            "bootstrap",
            f"gui/{UID}",
            str(store.destination_for(TEST_LABEL)),
        ]

class TestStatus:
    def test_loaded_on_exit_zero(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(_process(exit_code=0))
        backend = _backend(tmp_path, runner)

        status = backend.status(TEST_LABEL)

        assert status.loaded is True
        assert status.process.exit_code == 0

    def test_unloaded_on_non_zero_exit(self, tmp_path: Path) -> None:
        runner = FakeProcessRunner(_process(exit_code=3))
        backend = _backend(tmp_path, runner)

        assert backend.status(TEST_LABEL).loaded is False

    def test_unknown_when_process_never_started(self, tmp_path: Path) -> None:
        failure = ProcessLaunchFailure(kind="not_found", message="gone")
        runner = FakeProcessRunner(_process(exit_code=None, launch_failure=failure))
        backend = _backend(tmp_path, runner)

        status = backend.status(TEST_LABEL)

        assert status.loaded is None
        assert status.process.launch_failure is failure


class TestLabelSafety:
    @pytest.mark.parametrize("label", ["..", ".", "a/b"])
    @pytest.mark.parametrize(
        "method",
        ["uninstall", "bootout", "bootstrap", "status", "enable", "disable", "trigger"],
    )
    def test_raw_label_methods_reject_unsafe_labels(
        self, tmp_path: Path, method: str, label: str
    ) -> None:
        runner = FakeProcessRunner(_process())
        backend = _backend(tmp_path, runner)

        with pytest.raises(ValueError, match="Label must not be"):
            getattr(backend, method)(label)

        assert runner.specs == []


class TestShellJobWiring:
    def test_install_accepts_non_python_command(self, tmp_path: Path) -> None:
        job = make_job(
            label=TEST_LABEL,
            command=ShellCommand(executable="/bin/echo", arguments=["hi"]),
        )
        store = _store(tmp_path)
        runner = FakeProcessRunner(_process())
        backend = LaunchAgentBackend(store, runner, uid=UID)

        backend.install(job)

        (spec,) = runner.specs
        assert spec.argv[1] == "bootstrap"
        assert store.destination_for(TEST_LABEL).is_file()
