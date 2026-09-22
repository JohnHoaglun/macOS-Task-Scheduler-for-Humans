"""Tests for the discovery controller (pure Python, no Qt)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn
from uuid import UUID

from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application import CatalogDiagnostic
from task_scheduler.application.task_command_service import ListingKind, TaskListing
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController

EXTERNAL_ID = UUID("87654321-4321-4321-4321-432143214321")


class _BoomServices:
    def list_agents(self) -> NoReturn:
        raise RuntimeError("boom")


class _OutsideRootServices:
    def inspect_discovered(self, path: Path) -> NoReturn:
        raise ValueError("outside root")


class _DiagnosticServices:
    def __init__(
        self,
        diagnostics: list[CatalogDiagnostic],
        *,
        catalog_error: Exception | None = None,
    ) -> None:
        self._diagnostics = diagnostics
        self._catalog_error = catalog_error

    def list_agents(self) -> list[TaskListing]:
        return []

    def catalog_diagnostics(self) -> list[CatalogDiagnostic]:
        if self._catalog_error is not None:
            raise self._catalog_error
        return self._diagnostics


class TestInspect:
    def test_inspect_saved_listing_is_a_noop(self, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(id=EXTERNAL_ID, label="com.example.saved-only", name="Saved Job")
        world.jobs.import_job(saved)
        controller = DiscoveryController(world.services)
        listing = next(
            agent for agent in world.services.list_agents() if agent.kind is ListingKind.SAVED
        )
        outcome = controller.inspect(listing)
        assert outcome.report is None
        assert outcome.error is None
        assert outcome.diagnostics == ()


class TestRefreshDiagnostics:
    def _diagnostic(self, name: str) -> CatalogDiagnostic:
        return CatalogDiagnostic(path=Path(name), message="JSONDecodeError: bad")

    def test_refresh_success_carries_catalog_diagnostics(self) -> None:
        d1 = self._diagnostic("a.json")
        d2 = self._diagnostic("b.json")
        outcome = DiscoveryController(_DiagnosticServices([d1, d2])).refresh()
        assert outcome.error is None
        assert outcome.diagnostics == (d1, d2)

    def test_refresh_success_without_diagnostics(self) -> None:
        outcome = DiscoveryController(_DiagnosticServices([])).refresh()
        assert outcome.error is None
        assert outcome.diagnostics == ()

    def test_refresh_error_has_empty_diagnostics(self) -> None:
        outcome = DiscoveryController(_BoomServices()).refresh()
        assert outcome.error is not None
        assert outcome.diagnostics == ()

    def test_catalog_diagnostics_failure_is_an_error_outcome(self) -> None:
        outcome = DiscoveryController(
            _DiagnosticServices([], catalog_error=RuntimeError("scan failed"))
        ).refresh()
        assert outcome.error == "scan failed"
        assert outcome.diagnostics == ()
