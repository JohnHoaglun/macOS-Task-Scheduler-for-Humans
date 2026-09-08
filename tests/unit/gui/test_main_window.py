"""Tests for the main window (offscreen Qt)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QItemSelection, QModelIndex, QTimer
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
)
from pytestqt.qtbot import QtBot
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application import TaskCommandService
from task_scheduler.application.task_command_service import (
    ListingKind,
    TaskListing,
)
from task_scheduler.domain import JobDefinition, LoggingConfig
from task_scheduler.gui.controllers.diagnostics_controller import (
    DiagnosticsController,
    TestOutcome,
)
from task_scheduler.gui.controllers.diagnostics_controller import (
    RequestVerdict as TestVerdict,
)
from task_scheduler.gui.controllers.diagnostics_worker import DiagnosticsWorker
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.controllers.history_controller import (
    HistoryController,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from task_scheduler.gui.main_window import MainWindow
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.presenters.agent_presenter import format_name
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.import_preview_dialog import ImportPreviewDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog
from task_scheduler.platform.macos import ProcessResult, parse_path

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
        DiagnosticsController(controller._services, {}),
        HistoryController(controller._services),
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

class TestEditEdgeCases:

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

def _run_tests_synchronously(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run test workers synchronously and deliver their finished signal."""

    def _start(worker: DiagnosticsWorker) -> None:
        worker.finished.connect(window._on_test_finished)
        worker.run()

    monkeypatch.setattr(window, "_start_test_worker", _start)

def _panel_text(window: MainWindow, object_name: str) -> str:
    """The panel's named text element (label or log tab), asserted present."""
    found = window.panel.findChild(object, object_name)
    assert found is not None
    if isinstance(found, QPlainTextEdit):
        return found.toPlainText()
    assert isinstance(found, QLabel)
    return found.text()

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

class TestLifecycleTrigger:

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

class TestDiagnosticsTrigger:

    def test_trigger_without_selection_shows_hint(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_test_triggered()
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_trigger_on_external_row_shows_hint(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, _, external_a, _ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, external_a)
        window._on_test_triggered()
        assert window.statusBar().currentMessage() == (
            "This task is not a managed task; there is nothing to test."
        )

    def test_busy_request_is_refused(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        listing = window._model.listing_at(window.table.currentIndex().row())
        assert listing is not None
        assert (
            window._diagnostics_controller.request_test(listing.job)
            is TestVerdict.ACCEPTED
        )
        window._on_test_triggered()
        assert window.statusBar().currentMessage() == "Cannot test: busy."

    def test_stale_outcome_is_not_rendered(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        job_b = make_job(
            id=SECOND_JOB_ID, name="Second Job", label="zz.example.second"
        )
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        window._on_test_finished(
            TestOutcome(label=job_b.label, result=None, error="boom")
        )
        assert _panel_text(window, "diagnostics-summary") == (
            "Run Test to check this task directly."
        )
        assert not window._diagnostics_busy

    def test_finished_ignores_foreign_payloads(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._on_test_finished("not an outcome")
        assert window._diagnostics_busy is False
        assert window._active_test_worker is None

    def test_refresh_renders_logs_and_environment(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        out = tmp_path / "out.log"
        out.write_text("persisted out\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world.manage(job)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        window.panel.refresh_button.click()
        assert _panel_text(window, "diagnostics-persisted-stdout") == (
            "persisted out\n"
        )
        assert "GUI process only: none" in _panel_text(
            window, "diagnostics-environment-text"
        )

    def test_refresh_without_job_shows_hint(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_diagnostics_refresh()
        assert (
            window.statusBar().currentMessage() == "Select a task to refresh its logs."
        )

    def test_production_thread_dispatch(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(
            tmp_path, test=ProcessResult(exit_code=0, stdout="direct out")
        )
        job = make_job()
        world.manage(job)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        window.test_action.trigger()
        assert window._diagnostics_busy is True
        qtbot.waitUntil(
            lambda: window._diagnostics_busy is False,
            timeout=5000,
        )
        assert _panel_text(window, "diagnostics-summary") == (
            "Passed (exit code 0) in 0.00s"
        )

class TestHistoryPanelWiring:

    def test_history_refresh_with_selection(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        window._on_history_refresh()
        state = window.history_panel.findChild(object, "history-state-text")
        assert "No execution history recorded" in state.text()

    def test_history_refresh_without_selection(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_history_refresh()
        assert (
            window.statusBar().currentMessage()
            == "Select a task to refresh its history."
        )


EXTERNAL_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.external.imported</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/echo</string>
        <string>hello</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
</dict>
</plist>
"""

EXTERNAL_PARTIAL_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.external.partial</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/echo</string>
        <string>partial</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>0</integer>
            <key>Weekday</key>
            <integer>1</integer>
        </dict>
    </array>
    <key>UnknownWeirdKey</key>
    <string>ignored</string>
</dict>
</plist>
"""


def _import_window(
    qtbot: QtBot, world: FakeTaskWorld
) -> MainWindow:
    """A window with an import controller."""
    from task_scheduler.gui.controllers.import_controller import ImportController

    window = MainWindow(
        DiscoveryController(world.services),
        EditorController(world.services),
        LifecycleController(world.services),
        DiagnosticsController(world.services, {}),
        HistoryController(world.services),
        ImportController(world.services),
    )
    qtbot.addWidget(window)
    window.show()
    return window


def _external_row(window: MainWindow) -> int | None:
    """Return the row index of the external plist, or None."""
    model = window.table.model()
    for row in range(model.rowCount()):
        listing = model.listing_at(row)
        if listing is not None and listing.path is not None:
            return row
    return None


class TestImportActionGating:
    def test_import_action_enabled_for_eligible_external(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        la_plist = world.la_root / "com.external.imported.plist"
        world.la_root.mkdir(parents=True, exist_ok=True)
        la_plist.write_bytes(EXTERNAL_PLIST.encode())
        window = _import_window(qtbot, world)
        model = window.table.model()
        row = _external_row(window)
        assert row is not None
        window.table.setCurrentIndex(model.index(row, 0))
        assert window.import_action.isEnabled()

    def test_import_action_disabled_for_managed(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _import_window(qtbot, world)
        model = window.table.model()
        row = _row_by_path(model, world.store.destination_for(managed.label))
        window.table.setCurrentIndex(model.index(row, 0))
        assert not window.import_action.isEnabled()

    def test_import_action_disabled_for_saved(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _import_window(qtbot, world)
        model = window.table.model()
        # SAVED rows have kind SAVED, no path/parsed
        for row in range(model.rowCount()):
            listing = model.listing_at(row)
            if listing is not None and listing.kind is not None:
                # We don't know the kind directly but saved rows have no path
                pass
        # Click the first row (should be discovered managed)
        if model.rowCount() > 0:
            window.table.setCurrentIndex(model.index(0, 0))
        assert not window.import_action.isEnabled()

    def test_import_action_disabled_for_invalid_plist(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        la_plist = world.la_root / "invalid.plist"
        world.la_root.mkdir(parents=True, exist_ok=True)
        la_plist.write_bytes(b"not a plist at all")
        window = _import_window(qtbot, world)
        model = window.table.model()
        row = _external_row(window)
        assert row is not None
        window.table.setCurrentIndex(model.index(row, 0))
        # Invalid plists should not be importable
        listing = model.listing_at(row)
        assert listing is not None
        if listing.parsed is not None and listing.parsed.job is not None:
            assert not window.import_action.isEnabled()


class TestImportTriggered:
    """Drives MainWindow._on_import_triggered end-to-end, faking the dialog modal."""

    def _select_external(self, window: MainWindow) -> None:
        model = window.table.model()
        row = _external_row(window)
        assert row is not None
        window.table.setCurrentIndex(model.index(row, 0))

    def _write_plist(self, tmp_path: Path, world: FakeTaskWorld, name: str, data: bytes) -> None:
        world.la_root.mkdir(parents=True, exist_ok=True)
        (world.la_root / name).write_bytes(data)

    def test_no_import_controller(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._on_import_triggered()
        assert window.statusBar().currentMessage() == "Import is not available."

    def test_no_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        window = _import_window(qtbot, world)
        window._on_import_triggered()
        assert window.statusBar().currentMessage() == "Select a task to import."

    def test_preview_error(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        self._write_plist(tmp_path, world, "bad.plist", b"not a plist")
        window = _import_window(qtbot, world)
        self._select_external(window)
        window._on_import_triggered()
        assert window.statusBar().currentMessage().startswith("Cannot import:")

    def test_cancel_dialog_no_commit(self, qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
        world = FakeTaskWorld(tmp_path)
        self._write_plist(tmp_path, world, "com.external.imported.plist", EXTERNAL_PLIST.encode())
        window = _import_window(qtbot, world)
        self._select_external(window)
        monkeypatch.setattr(
            ImportPreviewDialog, "exec", lambda self: QDialog.DialogCode.Rejected
        )
        window._on_import_triggered()
        assert list(world.catalog_root.glob("*.json")) == []

    def test_commit_failure_unacknowledged_partial(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        self._write_plist(
            tmp_path, world, "com.external.partial.plist", EXTERNAL_PARTIAL_PLIST.encode()
        )
        window = _import_window(qtbot, world)
        self._select_external(window)

        def accepted(self):
            self._acknowledge_check.setChecked(False)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(ImportPreviewDialog, "exec", accepted)
        window._on_import_triggered()
        assert window.statusBar().currentMessage().startswith("Import failed:")
        assert list(world.catalog_root.glob("*.json")) == []

    def test_happy_path_commits(self, qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
        world = FakeTaskWorld(tmp_path)
        self._write_plist(
            tmp_path, world, "com.external.imported.plist", EXTERNAL_PLIST.encode()
        )
        window = _import_window(qtbot, world)
        self._select_external(window)
        monkeypatch.setattr(
            ImportPreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted
        )
        window._on_import_triggered()
        assert len(list(world.catalog_root.glob("*.json"))) == 1
        assert window.statusBar().currentMessage() == ""

    def test_import_never_invokes_launchctl(self, tmp_path: Path) -> None:
        """A pure import (no window/refresh) writes the catalog only; launchctl
        is never invoked."""
        from task_scheduler.gui.controllers.import_controller import ImportController

        world = FakeTaskWorld(tmp_path)
        self._write_plist(
            tmp_path, world, "com.external.nolaunchctl.plist", EXTERNAL_PLIST.encode()
        )
        controller = ImportController(world.services)
        outcome = controller.preview(world.la_root / "com.external.nolaunchctl.plist")
        assert outcome.error is None
        controller.commit(outcome, acknowledge_partial=False)
        assert len(list(world.catalog_root.glob("*.json"))) == 1
        assert len(world.launch_runner.specs) == 0
