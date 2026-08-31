"""Tests for the main window (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QItemSelection, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
)
from pytestqt.qtbot import QtBot

from conftest import make_job
from task_scheduler.application import TaskCommandService
from task_scheduler.application.task_command_service import (
    ListingKind,
    TaskListing,
    UninstallResult,
)
from task_scheduler.domain import JobDefinition
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
    RequestVerdict,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from task_scheduler.gui.main_window import MainWindow
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.presenters.agent_presenter import format_name
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog
from task_scheduler.platform.macos import ProcessResult, parse_path
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


def _window(
    qtbot: QtBot,
    controller: DiscoveryController,
    editor: EditorController | None = None,
) -> MainWindow:
    """A constructed, shown window kept alive by qtbot."""
    window = MainWindow(
        controller,
        editor or EditorController(controller._services),
        LifecycleController(controller._services),
    )
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


def _fill_valid_python(editor: JobEditor) -> None:
    """Fill a new python draft so it validates."""
    editor.findChild(QLineEdit, "editor-name").setText("Nightly Sync")
    editor.findChild(QLineEdit, "editor-interpreter").setText("/tmp/venv/bin/python")
    editor.findChild(QLineEdit, "editor-script").setText("/tmp/nightly.py")
    editor.findChild(QLineEdit, "editor-time").setText("01:00")
    editor.findChild(QCheckBox, "editor-weekday-monday").setChecked(True)


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
        window = MainWindow(
            controller,
            EditorController(controller._services),
            LifecycleController(controller._services),
        )
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
        world.jobs.remove(job_b.id)
        window.refresh()
        current_row = window.table.currentIndex().row()
        assert current_row == 0
        listing = model.listing_at(current_row)
        top = model.listing_at(0)
        assert listing is not None
        assert top is not None
        assert listing.path == top.path
        assert _value_label(window.inspector, "overview-name").text() == format_name(top)

    def test_refresh_follows_selected_job_to_its_saved_row(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        job_b = make_job(id=SECOND_JOB_ID, name="Second Job", label="zz.example.second")
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row_b = _row_by_path(model, world.store.destination_for(job_b.label))
        assert row_b != 0
        window.table.setCurrentIndex(model.index(row_b, 0))
        world.store.destination_for(job_b.label).unlink()
        window.refresh()
        listing = model.listing_at(window.table.currentIndex().row())
        assert listing is not None
        assert listing.kind is ListingKind.SAVED
        assert listing.job is not None
        assert listing.job.label == job_b.label
        assert (
            _value_label(window.inspector, "overview-state").text()
            == "Saved, not installed"
        )


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

    def list_agents(self) -> list[TaskListing]:
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


class TestTaskActions:
    def test_new_task_action_opens_editor(self, qtbot: QtBot, tmp_path: Path) -> None:
        """The New Task action opens the editor modal titled New Task."""
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        editor = window._editor
        QTimer.singleShot(0, editor.reject)
        window.new_task_action.trigger()
        assert editor.windowTitle() == "New Task"
        assert editor.result() == 0
        assert editor.saved_path is None

    def test_new_task_save_writes_catalog(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Saving from New Task writes a catalog file and accepts."""
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        editor = window._editor

        def fill_and_save() -> None:
            _fill_valid_python(editor)
            editor.findChild(QPushButton, "editor-save").click()

        QTimer.singleShot(0, fill_and_save)
        window.new_task_action.trigger()
        assert editor.result() == 1
        assert editor.saved_path is not None and editor.saved_path.is_file()
        assert "Nightly Sync" in editor.saved_path.read_text()

    def test_edit_action_requires_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Edit Managed Task with no selection shows a status hint."""
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        hint = "Select a managed task to edit it."
        QTimer.singleShot(0, window.edit_task_action.trigger)
        qtbot.waitUntil(lambda: window.statusBar().currentMessage() == hint)
        assert not window._editor.isVisible()

    def test_edit_action_rejects_unmanaged(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Edit Managed Task on an external agent shows the same hint."""
        world, managed, external_a, _ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(external_a.label))
        window.table.setCurrentIndex(model.index(row, 0))
        hint = "Select a managed task to edit it."
        QTimer.singleShot(0, window.edit_task_action.trigger)
        qtbot.waitUntil(lambda: window.statusBar().currentMessage() == hint)
        assert not window._editor.isVisible()

    def test_edit_managed_task_opens_editor(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Selecting a managed agent and editing opens a populated dialog."""
        world, managed, _, _ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(managed.label))
        window.table.setCurrentIndex(model.index(row, 0))
        editor = window._editor
        QTimer.singleShot(0, editor.reject)
        window.edit_task_action.trigger()
        assert editor.windowTitle() == "Edit Task"
        assert editor.findChild(QLineEdit, "editor-name").text() == "Daily Backup"
        assert editor.result() == 0

    def test_edit_managed_task_save_renames(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Renaming and saving a managed job rewrites its catalog file."""
        world, managed, _, _ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(managed.label))
        window.table.setCurrentIndex(model.index(row, 0))
        editor = window._editor

        def rename_and_save() -> None:
            editor.findChild(QLineEdit, "editor-name").setText("Renamed Backup")
            editor.findChild(QPushButton, "editor-save").click()

        QTimer.singleShot(0, rename_and_save)
        window.edit_task_action.trigger()
        assert editor.result() == 1
        assert editor.saved_path is not None
        assert "Renamed Backup" in editor.saved_path.read_text()


class TestSelectSavedRow:
    def test_selecting_saved_row_shows_saved_inspector(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(
            id=SECOND_JOB_ID, label="io.github.macos-task-scheduler.user.saved-only"
        )
        world.jobs.import_job(saved)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        assert model.rowCount() == 1
        listing = model.listing_at(0)
        assert listing is not None
        assert listing.kind is ListingKind.SAVED
        assert listing.path is None
        window.table.setCurrentIndex(model.index(0, 0))
        assert _scroll_area(window.inspector).isVisible()
        assert _value_label(window.inspector, "overview-name").text() == "Daily Backup"
        assert _value_label(window.inspector, "overview-classification").text() == "Managed"
        assert _value_label(window.inspector, "overview-source").text() == (
            "(task catalog — not installed)"
        )
        assert _value_label(window.inspector, "overview-loaded").text() == "not installed"
        assert _value_label(window.inspector, "warnings-text").text() == "none"

    def test_edit_saved_row_opens_populated_editor(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(
            id=SECOND_JOB_ID, label="io.github.macos-task-scheduler.user.saved-only"
        )
        world.jobs.import_job(saved)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        window.table.setCurrentIndex(model.index(0, 0))
        editor = window._editor
        QTimer.singleShot(0, editor.reject)
        window.edit_task_action.trigger()
        assert editor.windowTitle() == "Edit Task"
        assert editor.findChild(QLineEdit, "editor-name").text() == "Daily Backup"
        assert editor.result() == 0


class TestEditEdgeCases:
    def test_edit_action_selected_row_without_catalog_job(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """A selected row with no catalog job shows the edit hint."""
        world = FakeTaskWorld(tmp_path)
        label = "io.github.macos-task-scheduler.user.unparseable"
        plist_path = world.la_root / f"{label}.plist"
        world.la_root.mkdir(parents=True)
        plist_path.write_bytes(b"not a plist at all")
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        listing = TaskListing(
            kind=ListingKind.DISCOVERED,
            path=plist_path,
            parsed=parse_path(plist_path),
            job=None,
            managed=True,
        )
        model.set_agents([listing])
        row = _row_by_path(model, plist_path)
        window.table.setCurrentIndex(model.index(row, 0))
        window.edit_task_action.trigger()
        assert window.statusBar().currentMessage() == "Select a managed task to edit it."
        assert not window._editor.isVisible()

    def test_edit_action_missing_catalog_entry(self, qtbot: QtBot, tmp_path: Path) -> None:
        """A parseable managed agent absent from the catalog shows a hint."""
        world = FakeTaskWorld(tmp_path)
        job = make_job(label="io.github.macos-task-scheduler.user.orphan")
        world.manage(job)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(job.label))
        window.table.setCurrentIndex(model.index(row, 0))
        world.jobs.remove(job.id)
        window.edit_task_action.trigger()
        assert window.statusBar().currentMessage() == "This task is not in the task catalog."
        assert not window._editor.isVisible()


def _capture_lifecycle(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> list[LifecycleOutcome]:
    """Run lifecycle workers synchronously and record their dialog outcomes."""
    outcomes: list[LifecycleOutcome] = []

    def fake_exec(self: LifecycleResultDialog) -> int:
        outcomes.append(self._outcome)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LifecycleResultDialog, "exec", fake_exec)

    def _start(worker: LifecycleWorker) -> None:
        worker.finished.connect(window._on_lifecycle_finished)
        worker.run()

    monkeypatch.setattr(window, "_start_worker", _start)
    return outcomes


def _lifecycle_actions(window: MainWindow) -> list[QAction]:
    return [
        window.install_action,
        window.reinstall_action,
        window.uninstall_action,
        window.enable_action,
        window.disable_action,
        window.run_now_action,
    ]


def _select_managed(world: FakeTaskWorld, window: MainWindow, job: JobDefinition) -> None:
    model = window.table.model()
    row = _row_by_path(model, world.store.destination_for(job.label))
    window.table.setCurrentIndex(model.index(row, 0))


class TestLifecycleGating:
    def test_installed_managed_row_gates_the_five_actions(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        assert not window.install_action.isEnabled()
        for action in _lifecycle_actions(window)[1:]:
            assert action.isEnabled()
        assert window.new_task_action.isEnabled()
        assert window.edit_task_action.isEnabled()

    def test_saved_row_gates_install_only(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(
            id=SECOND_JOB_ID, label="io.github.macos-task-scheduler.user.saved-only"
        )
        world.jobs.import_job(saved)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        window.table.setCurrentIndex(model.index(0, 0))
        assert window.install_action.isEnabled()
        for action in _lifecycle_actions(window)[1:]:
            assert not action.isEnabled()

    def test_external_row_gates_all_actions(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, _, external_a, _ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, external_a)
        for action in _lifecycle_actions(window):
            assert not action.isEnabled()

    def test_invalid_row_gates_all_actions(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        path = world.la_root / f"{INVALID_LABEL}.plist"
        world.la_root.mkdir(parents=True)
        path.write_bytes(b"not a plist at all")
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        row = _row_by_path(model, path)
        window.table.setCurrentIndex(model.index(row, 0))
        for action in _lifecycle_actions(window):
            assert not action.isEnabled()

    def test_no_selection_gates_all_actions(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(window.table.model().index(0, 0))
        window.table.clearSelection()
        for action in _lifecycle_actions(window):
            assert not action.isEnabled()
        assert window.new_task_action.isEnabled()
        assert window.edit_task_action.isEnabled()

    def test_busy_disables_everything(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        window._lifecycle_busy = True
        window._update_lifecycle_actions()
        for action in _lifecycle_actions(window):
            assert not action.isEnabled()
        assert not window.new_task_action.isEnabled()
        assert not window.edit_task_action.isEnabled()
        window._lifecycle_busy = False
        window._update_lifecycle_actions()
        for action in _lifecycle_actions(window)[1:]:
            assert action.isEnabled()


class TestLifecycleTrigger:
    def test_reinstall_confirms_and_runs(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        outcomes = _capture_lifecycle(window, monkeypatch)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, text: QMessageBox.StandardButton.Yes,
        )
        _select_managed(world, window, managed)
        window.reinstall_action.trigger()
        assert len(outcomes) == 1
        assert outcomes[0].action is LifecycleAction.REINSTALL
        assert outcomes[0].label == managed.label
        assert outcomes[0].is_success
        assert world.launch_runner.specs

    def test_reinstall_declined_confirmation_runs_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        outcomes = _capture_lifecycle(window, monkeypatch)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, text: QMessageBox.StandardButton.No,
        )
        _select_managed(world, window, managed)
        baseline = len(world.launch_runner.specs)
        window.reinstall_action.trigger()
        assert outcomes == []
        assert len(world.launch_runner.specs) == baseline

    def test_reinstall_confirmation_names_task_and_label(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _capture_lifecycle(window, monkeypatch)
        seen: list[str] = []

        def confirm(parent, title, text):
            seen.append(text)
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", confirm)
        _select_managed(world, window, managed)
        window.reinstall_action.trigger()
        assert managed.name in seen[0]
        assert managed.label in seen[0]
        assert "LaunchAgent" in seen[0]

    def test_install_saved_row_deploys_without_confirmation(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        saved = make_job(
            id=SECOND_JOB_ID, label="io.github.macos-task-scheduler.user.saved-only"
        )
        world.jobs.import_job(saved)
        window = _window(qtbot, DiscoveryController(world.services))
        outcomes = _capture_lifecycle(window, monkeypatch)

        def no_confirm(*args, **kwargs):
            raise AssertionError("confirmation must not be asked for install")

        monkeypatch.setattr(QMessageBox, "question", no_confirm)
        model = window.table.model()
        window.table.setCurrentIndex(model.index(0, 0))
        window.install_action.trigger()
        assert len(outcomes) == 1
        assert outcomes[0].action is LifecycleAction.INSTALL
        assert outcomes[0].is_success
        assert world.store.destination_for(saved.label).is_file()

    def test_failure_does_not_refresh(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path, launch=ProcessResult(exit_code=1))
        job = make_job()
        world.manage(job)
        controller = DiscoveryController(world.services)
        refreshes = 0
        original = controller.refresh

        def counting_refresh():
            nonlocal refreshes
            refreshes += 1
            return original()

        controller.refresh = counting_refresh
        window = _window(qtbot, controller)
        outcomes = _capture_lifecycle(window, monkeypatch)
        _select_managed(world, window, job)
        window.enable_action.trigger()
        assert len(outcomes) == 1
        assert outcomes[0].is_success is False
        assert refreshes == 1

    def test_success_refreshes(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        controller = DiscoveryController(world.services)
        refreshes = 0
        original = controller.refresh

        def counting_refresh():
            nonlocal refreshes
            refreshes += 1
            return original()

        controller.refresh = counting_refresh
        window = _window(qtbot, controller)
        outcomes = _capture_lifecycle(window, monkeypatch)
        _select_managed(world, window, job)
        window.enable_action.trigger()
        assert len(outcomes) == 1
        assert outcomes[0].is_success
        assert refreshes == 2

    def test_uninstall_removes_row_and_catalog_record(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        outcomes = _capture_lifecycle(window, monkeypatch)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, text: QMessageBox.StandardButton.Yes,
        )
        _select_managed(world, window, managed)
        window.uninstall_action.trigger()
        assert len(outcomes) == 1
        assert outcomes[0].is_success
        assert outcomes[0].result is not None
        assert isinstance(outcomes[0].result, UninstallResult)
        assert outcomes[0].result.catalog_removed
        model = window.table.model()
        assert model.rowCount() == 2
        assert world.jobs.find(managed.label) is None

    def test_production_thread_dispatch(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        outcomes: list[LifecycleOutcome] = []

        def fake_exec(self: LifecycleResultDialog) -> int:
            outcomes.append(self._outcome)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(LifecycleResultDialog, "exec", fake_exec)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, text: QMessageBox.StandardButton.Yes,
        )
        _select_managed(world, window, managed)
        window.run_now_action.trigger()
        assert window._lifecycle_busy is True
        qtbot.waitUntil(
            lambda: window._lifecycle_busy is False and len(outcomes) == 1,
            timeout=5000,
        )
        assert outcomes[0].action is LifecycleAction.RUN_NOW
        assert outcomes[0].is_success


class TestLifecycleEdgeCases:
    def test_trigger_without_selection_shows_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.clearSelection()
        window._on_lifecycle_triggered(LifecycleAction.ENABLE)
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_busy_request_is_refused(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        listing = window._model.listing_at(window.table.currentIndex().row())
        assert listing is not None
        assert (
            window._lifecycle_controller.request(LifecycleAction.ENABLE, listing)
            is RequestVerdict.ACCEPTED
        )
        window._on_lifecycle_triggered(LifecycleAction.ENABLE)
        assert window.statusBar().currentMessage() == "Cannot run enable: busy."

    def test_not_allowed_action_is_refused(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        window._on_lifecycle_triggered(LifecycleAction.INSTALL)
        assert window.statusBar().currentMessage() == "Cannot run install: not allowed."

    def test_confirm_without_job_refuses(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        path = world.la_root / f"{INVALID_LABEL}.plist"
        world.la_root.mkdir(parents=True)
        path.write_bytes(b"not a plist at all")
        window = _window(qtbot, DiscoveryController(world.services))
        listing = TaskListing(
            kind=ListingKind.DISCOVERED,
            path=path,
            parsed=parse_path(path),
            job=None,
            managed=True,
        )
        assert window._confirm_lifecycle(LifecycleAction.UNINSTALL, listing) is False

    def test_row_for_identity_skips_missing_rows(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        job_b = make_job(id=SECOND_JOB_ID, name="Second Job", label="zz.example.second")
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        previous = model.listing_at(1)
        assert previous is not None
        real = model.listing_at

        def flaky(row: int) -> TaskListing | None:
            return None if row == 0 else real(row)

        model.listing_at = flaky
        assert window._row_for_identity(previous) == 1

    def test_row_for_identity_falls_back_to_path(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        path = world.la_root / f"{INVALID_LABEL}.plist"
        world.la_root.mkdir(parents=True)
        path.write_bytes(b"not a plist at all")
        window = _window(qtbot, DiscoveryController(world.services))
        model = window.table.model()
        previous = model.listing_at(0)
        assert previous is not None
        assert previous.job is None
        assert window._row_for_identity(previous) == 0
        assert window._row_for_identity(None) == 0

    def test_finished_ignores_foreign_payloads(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._on_lifecycle_finished("not an outcome")
        assert window._lifecycle_busy is False
        assert window._active_worker is None


class TestProductionLifecycleFlows:
    def test_disable_flow_through_production_thread(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        window = _window(qtbot, DiscoveryController(world.services))
        dialogs: list[LifecycleResultDialog] = []
        monkeypatch.setattr(
            LifecycleResultDialog,
            "exec",
            lambda self: dialogs.append(self) or QDialog.DialogCode.Accepted,
        )
        _select_managed(world, window, job)
        window.disable_action.trigger()
        qtbot.waitUntil(lambda: window._lifecycle_busy is False and bool(dialogs), timeout=5000)
        dialog = dialogs[0]
        title = dialog.findChild(QLabel, "lifecycle-result-title")
        assert title is not None
        assert title.text() == f"Disable succeeded for {job.label}."
        assert any(spec.argv[1] == "disable" for spec in world.launch_runner.specs)

    def test_uninstall_flow_through_production_thread(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        dialogs: list[LifecycleResultDialog] = []
        monkeypatch.setattr(
            LifecycleResultDialog,
            "exec",
            lambda self: dialogs.append(self) or QDialog.DialogCode.Accepted,
        )
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, text: QMessageBox.StandardButton.Yes,
        )
        _select_managed(world, window, managed)
        window.uninstall_action.trigger()
        qtbot.waitUntil(lambda: window._lifecycle_busy is False and bool(dialogs), timeout=5000)
        dialog = dialogs[0]
        title = dialog.findChild(QLabel, "lifecycle-result-title")
        assert title is not None
        assert title.text() == f"Uninstall succeeded for {managed.label}."
        toggle = dialog.findChild(QPushButton, "lifecycle-details-toggle")
        assert toggle is not None
        toggle.setChecked(True)
        details = dialog.findChild(QPlainTextEdit, "lifecycle-technical-details")
        assert details is not None
        assert "catalog record removed: True" in details.toPlainText()
        assert window.table.model().rowCount() == 2
        assert world.jobs.find(managed.label) is None
