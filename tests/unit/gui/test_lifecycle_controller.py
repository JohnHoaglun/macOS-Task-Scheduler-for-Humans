"""Tests for the lifecycle controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application import ExternalEditResult
from task_scheduler.application.task_command_service import (
    InstallResult,
    ListingKind,
    TaskListing,
    UninstallResult,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
    LifecycleRequest,
    RequestVerdict,
)
from task_scheduler.platform.macos import LaunchctlResult, ProcessResult

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")
SAVED_LABEL = "com.example.saved-only"
JOB_LABEL = "io.github.macos-task-scheduler.user.daily-backup"
INSTALLED_ACTIONS = frozenset(
    {
        LifecycleAction.REINSTALL,
        LifecycleAction.UNINSTALL,
        LifecycleAction.ENABLE,
        LifecycleAction.DISABLE,
        LifecycleAction.RUN_NOW,
    }
)


def _saved_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.jobs.import_job(make_job(id=EXTERNAL_ID, label=SAVED_LABEL, name="Saved Job"))
    return world, world.services.list_agents()[0]


def _managed_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.manage(make_job())
    return world, world.services.list_agents()[0]


def _external_world(tmp_path: Path) -> tuple[FakeTaskWorld, TaskListing]:
    world = FakeTaskWorld(tmp_path)
    world.store.write(make_job(id=EXTERNAL_ID, label="com.example.external", name="External Job"))
    return world, world.services.list_agents()[0]


class TestRequest:
    def test_refuses_second_request_while_busy(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(LifecycleAction.UNINSTALL, listing) is RequestVerdict.ACCEPTED
        assert controller.request(LifecycleAction.ENABLE, listing) is RequestVerdict.BUSY

    def test_refuses_unmanaged_target(self, tmp_path: Path) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        # External rows are never uninstalled; the File menu's Remove handles them.
        assert controller.request(LifecycleAction.UNINSTALL, listing) is RequestVerdict.NOT_ALLOWED
        assert not controller.busy


class TestExecute:
    def test_install_deploys_and_bootstraps(self, tmp_path: Path) -> None:
        world, listing = _saved_world(tmp_path)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.INSTALL, listing)
        outcome = controller.execute()
        assert outcome.error is None
        assert isinstance(outcome.result, InstallResult)
        assert outcome.result.process.exit_code == 0
        assert outcome.result.plist_path == world.la_root / f"{SAVED_LABEL}.plist"
        assert (world.la_root / f"{SAVED_LABEL}.plist").is_file()
        assert [spec.argv[1] for spec in world.launch_runner.specs] == ["bootstrap"]

    def test_uninstall_removes_plist_and_catalog_record(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.UNINSTALL, listing)
        outcome = controller.execute()
        assert isinstance(outcome.result, UninstallResult)
        assert outcome.result.catalog_removed is True
        assert not (world.la_root / f"{JOB_LABEL}.plist").exists()
        assert world.services.list_agents() == []

    @pytest.mark.parametrize(
        "action",
        [LifecycleAction.ENABLE, LifecycleAction.DISABLE, LifecycleAction.RUN_NOW],
    )
    def test_launchctl_actions_return_launchctl_result(
        self, tmp_path: Path, action: LifecycleAction) -> None:
        world, listing = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(action, listing) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.error is None
        assert isinstance(outcome.result, LaunchctlResult)
        assert outcome.result.process.exit_code == 0

    def test_reinstall_after_catalog_removal_reports_error(self, tmp_path: Path) -> None:
        world, listing = _managed_world(tmp_path)
        assert listing.job is not None
        controller = LifecycleController(world.services)
        controller.request(LifecycleAction.REINSTALL, listing)
        world.jobs.remove(listing.job.id)
        outcome = controller.execute()
        assert outcome.result is None
        assert "no managed job" in (outcome.error or "")


def _external_result(path: Path) -> ExternalEditResult:
    return ExternalEditResult(
        source_path=path,
        label="com.example.external",
        process=ProcessResult(exit_code=0),
        phases=(),
        completed_phases=("disable",),
        retained_artifacts=(),
        replaced=False,
        reloaded=False,
    )


class TestListingEdgeCases:
    def test_enabled_actions_managed_without_job_is_empty(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        listing = TaskListing(
            kind=ListingKind.DISCOVERED,
            path=world.la_root / "x.plist",
            parsed=None,
            job=None,
            managed=True,
            loaded=True,
        )
        assert controller.enabled_actions(listing) == frozenset()

    def test_request_managed_without_job_is_not_managed(self, tmp_path: Path, monkeypatch) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        monkeypatch.setattr(
            controller, "enabled_actions", lambda _l: frozenset({LifecycleAction.UNINSTALL})
        )
        listing = TaskListing(
            kind=ListingKind.DISCOVERED,
            path=world.la_root / "x.plist",
            parsed=None,
            job=None,
            managed=True,
            loaded=True,
        )
        assert controller.request(LifecycleAction.UNINSTALL, listing) is RequestVerdict.NOT_MANAGED

    def test_request_external_without_path_is_not_managed(self, tmp_path: Path) -> None:
        world, _ = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        listing = TaskListing(
            kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
        )
        assert controller.request(LifecycleAction.DISABLE, listing) is RequestVerdict.NOT_MANAGED

    def test_request_none_listing_is_not_managed(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        assert controller.request(LifecycleAction.UNINSTALL, None) is RequestVerdict.NOT_MANAGED

    def test_is_success_without_result_is_false(self) -> None:
        outcome = LifecycleOutcome(
            action=LifecycleAction.RUN_NOW, label=None, result=None, error=None
        )
        assert outcome.is_success is False


class TestExternalExecution:
    def test_execute_external_disable(self, tmp_path: Path, monkeypatch) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        monkeypatch.setattr(world.services, "disable_external", lambda p: _external_result(p))
        assert controller.request(LifecycleAction.DISABLE, listing) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.external_result is not None
        assert outcome.is_success is True

    def test_execute_external_enable(self, tmp_path: Path, monkeypatch) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        monkeypatch.setattr(world.services, "enable_external", lambda p: _external_result(p))
        assert controller.request(LifecycleAction.ENABLE, listing) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.external_result is not None

    def test_execute_external_run_now(self, tmp_path: Path, monkeypatch) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)
        monkeypatch.setattr(world.services, "run_now_external", lambda p: _external_result(p))
        controller._current = LifecycleRequest(
            action=LifecycleAction.RUN_NOW, label="com.example.external", source_path=listing.path
        )
        outcome = controller.execute()
        assert outcome.external_result is not None

    def test_execute_external_error(self, tmp_path: Path, monkeypatch) -> None:
        world, listing = _external_world(tmp_path)
        controller = LifecycleController(world.services)

        def boom(_p: Path) -> None:
            raise RuntimeError("nope")

        monkeypatch.setattr(world.services, "disable_external", boom)
        assert controller.request(LifecycleAction.DISABLE, listing) is RequestVerdict.ACCEPTED
        outcome = controller.execute()
        assert outcome.external_result is None
        assert outcome.error == "nope"

    def test_execute_managed_missing_job_raises_error(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        controller._current = LifecycleRequest(
            action=LifecycleAction.INSTALL, label="com.example.x", job=None
        )
        outcome = controller.execute()
        assert outcome.result is None
        assert "missing the managed job" in (outcome.error or "")

    def test_execute_label_none_short_circuits(self, tmp_path: Path) -> None:
        world, _ = _managed_world(tmp_path)
        controller = LifecycleController(world.services)
        controller._current = LifecycleRequest(action=LifecycleAction.INSTALL, label=None, job=None)
        outcome = controller.execute()
        assert outcome.result is None
        assert outcome.error == "the request has no usable label"

    def test_request_remove_saved_error_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        world, _ = _saved_world(tmp_path)
        controller = LifecycleController(world.services)
        from task_scheduler.application.job_service import JobNotFoundError

        def boom(_label: str) -> None:
            raise JobNotFoundError("nope")

        monkeypatch.setattr(world.services, "remove_saved_job", boom)
        assert controller.request_remove_saved("com.example.x") is None
