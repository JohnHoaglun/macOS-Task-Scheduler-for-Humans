"""Tests for the main window (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QItemSelection
from PySide6.QtWidgets import QLabel, QScrollArea, QTextEdit
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application import TaskCommandService
from task_scheduler.application.task_command_service import AgentListing
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.main_window import MainWindow
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.presenters.agent_presenter import format_name
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from tests.fakes import FakeTaskWorld

EXTERNAL_A_ID = UUID("11111111-1111-4111-8111-111111111111")
EXTERNAL_B_ID = UUID("22222222-2222-4222-8222-222222222222")
SECOND_JOB_ID = UUID("33333333-3333-4333-8333-333333333333")
INVALID_LABEL = "com.example.invalid"


def _value_label(inspector: AgentInspector, object_name: str) -> QLabel:
    """The named value QLabel, asserted present."""
    label = inspector.findChild(QLabel, object_name)
    assert label is not None
    return label


def _message_label(inspector: AgentInspector) -> QLabel:
    """The top-level message QLabel.

    Every value QLabel is re-parented into its group box by the layouts, so
    the message is the only QLabel whose parent is the inspector itself.
    """
    direct = [
        label
        for label in inspector.findChildren(QLabel)
        if label.parent() is not None and label.parent() == inspector
    ]
    assert len(direct) == 1
    return direct[0]


def _scroll_area(inspector: AgentInspector) -> QScrollArea:
    scroll = inspector.findChild(QScrollArea)
    assert scroll is not None
    return scroll


def _advanced_text(inspector: AgentInspector) -> QTextEdit:
    text = inspector.findChild(QTextEdit, "advanced-text")
    assert text is not None
    return text


def _window(qtbot: QtBot, controller: DiscoveryController) -> MainWindow:
    """A constructed, shown window kept alive by qtbot."""
    window = MainWindow(controller)
    qtbot.addWidget(window)
    window.show()
    return window


def _row_by_path(model: AgentTableModel, path: Path) -> int:
    """The table row holding *path*, asserted present."""
    for row in range(model.rowCount()):
        listing = model.listing_at(row)
        if listing is not None and listing.path == path:
            return row
    raise AssertionError(f"no row for {path}")


def _seed_three(
    tmp_path: Path,
) -> tuple[FakeTaskWorld, JobDefinition, JobDefinition, JobDefinition]:
    """A world with one managed and two external agents (sorted discovery)."""
    world = FakeTaskWorld(tmp_path)
    managed = make_job()
    world.manage(managed)
    external_a = make_job(
        id=EXTERNAL_A_ID, label="com.example.external", name="External Job"
    )
    world.store.write(external_a)
    external_b = make_job(id=EXTERNAL_B_ID, label="com.example.other", name="Other Job")
    world.store.write(external_b)
    return world, managed, external_a, external_b


class TestStartupSmoke:
    def test_startup_populates_table_and_inspector(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        assert model.rowCount() == 1
        assert _scroll_area(window.inspector).isVisible()
        listing = model.listing_at(0)
        assert listing is not None
        assert _value_label(window.inspector, "overview-name").text() == format_name(listing)
        assert _value_label(window.inspector, "overview-classification").text() == "Managed"


class TestEmptyState:
    def test_no_agents_shows_placeholder(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        assert window.table.model().rowCount() == 0
        assert _scroll_area(window.inspector).isHidden()
        assert _message_label(window.inspector).text() == "No tasks found."


class TestRefreshPopulates:
    def test_populates_table_with_three_agents(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.refresh()
        model = window.table.model()
        assert model.rowCount() == 3
        top = model.listing_at(0)
        assert top is not None
        assert model.data(model.index(0, 0)) == format_name(top)

    def test_refresh_action_triggers_a_refresh(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        controller = DiscoveryController(world.services)
        refreshes = 0
        original = controller.refresh

        def counting_refresh():
            nonlocal refreshes
            refreshes += 1
            return original()

        controller.refresh = counting_refresh
        window = MainWindow(controller)
        qtbot.addWidget(window)
        assert window.refresh_action is not None
        assert window.refresh_action.text() == "Refresh"
        assert refreshes == 1
        window.refresh_action.trigger()
        assert refreshes == 2
        assert window.table.model().rowCount() == 3


class TestSelectManagedAgent:
    def test_selecting_managed_agent_shows_details(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(managed.label))
        window.table.setCurrentIndex(model.index(row, 0))
        assert _scroll_area(window.inspector).isVisible()
        listing = model.listing_at(row)
        assert listing is not None
        assert _value_label(window.inspector, "overview-name").text() == format_name(listing)
        assert _value_label(window.inspector, "overview-classification").text() == "Managed"
        assert _value_label(window.inspector, "overview-loaded").text() == "loaded"
        assert _advanced_text(window.inspector).isReadOnly()


class TestSelectInvalidAgent:
    def test_malformed_plist_is_invalid_with_warnings(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        invalid_path = world.la_root / f"{INVALID_LABEL}.plist"
        world.la_root.mkdir(parents=True)
        invalid_path.write_bytes(b"not a plist at all")
        window.refresh()
        model = window.table.model()
        assert model.rowCount() == 1
        row = _row_by_path(model, invalid_path)
        window.table.setCurrentIndex(model.index(row, 0))
        assert _value_label(window.inspector, "overview-classification").text() == "Invalid"
        warnings = _value_label(window.inspector, "warnings-text").text()
        assert warnings != "none"
        assert warnings
        assert "malformed plist" in warnings


class _BoomServices:
    """Duck-typed TaskCommandService: discovery fails, inspect is unused."""

    def list_agents(self) -> None:
        raise RuntimeError("boom")

    def inspect_discovered(self, path: Path) -> None:
        raise NotImplementedError


class TestDiscoveryFailure:
    def test_discovery_failure_is_surfaced(self, qtbot: QtBot) -> None:
        window = _window(qtbot, DiscoveryController(_BoomServices()))
        assert window.table.model().rowCount() == 0
        assert _message_label(window.inspector).text() == "boom"
        assert window.statusBar().currentMessage() == "boom"
        assert _scroll_area(window.inspector).isHidden()


class TestRefreshPreservesSelection:
    def test_refresh_keeps_the_selected_agent(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        job_b = make_job(id=SECOND_JOB_ID, name="Second Job", label="zz.example.second")
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        path_b = world.store.destination_for(job_b.label)
        row_b = _row_by_path(model, path_b)
        assert row_b != 0
        window.table.setCurrentIndex(model.index(row_b, 0))
        window.refresh()
        listing = model.listing_at(window.table.currentIndex().row())
        assert listing is not None
        assert listing.path == path_b
        assert _value_label(window.inspector, "overview-name").text() == "zz.example.second"


class TestRefreshSelectionFallback:
    def test_refresh_falls_back_to_row_zero_when_selected_agent_vanishes(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        job_b = make_job(id=SECOND_JOB_ID, name="Second Job", label="zz.example.second")
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        path_b = world.store.destination_for(job_b.label)
        row_b = _row_by_path(model, path_b)
        assert row_b != 0
        window.table.setCurrentIndex(model.index(row_b, 0))
        path_b.unlink()
        window.refresh()
        current_row = window.table.currentIndex().row()
        assert current_row == 0
        listing = model.listing_at(current_row)
        top = model.listing_at(0)
        assert listing is not None
        assert top is not None
        assert listing.path == top.path
        assert _value_label(window.inspector, "overview-name").text() == format_name(top)


class TestSelectionCleared:
    def test_clearing_the_selection_shows_the_inspector_placeholder(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _window(qtbot, DiscoveryController(world.services))
        assert _scroll_area(window.inspector).isVisible()
        window.table.clearSelection()
        assert (
            _message_label(window.inspector).text() == "Select a task to inspect its details."
        )
        assert _scroll_area(window.inspector).isHidden()


class TestSelectionOutOfRange:
    def test_out_of_range_selection_index_is_ignored(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        before = _value_label(window.inspector, "overview-name").text()
        index = model.createIndex(999, 0)
        assert index.isValid()
        window._on_selection_changed(QItemSelection(index, index), QItemSelection())
        assert _value_label(window.inspector, "overview-name").text() == before
        assert _scroll_area(window.inspector).isVisible()


class _InspectFailingServices:
    """Duck-typed TaskCommandService: discovery works, inspect always fails."""

    def __init__(self, inner: TaskCommandService) -> None:
        self._inner = inner

    def list_agents(self) -> list[AgentListing]:
        return self._inner.list_agents()

    def inspect_discovered(self, path: Path) -> None:
        raise ValueError("plist is corrupted")


class TestInspectFailure:
    def test_inspect_failure_is_surfaced_in_the_inspector(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _window(qtbot, DiscoveryController(_InspectFailingServices(world.services)))
        model = window.table.model()
        assert model.rowCount() == 1
        window.table.setCurrentIndex(model.index(0, 0))
        assert _message_label(window.inspector).text() == "plist is corrupted"
        assert _scroll_area(window.inspector).isHidden()
