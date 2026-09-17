"""Tests for the main window (offscreen Qt)."""

from __future__ import annotations

import base64
import plistlib
from pathlib import Path
from uuid import UUID

import pytest
from PySide6.QtCore import QItemSelection, QModelIndex, Qt, QThread, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
)
from pytestqt.qtbot import QtBot
from tests.fakes import FakeTaskWorld

from conftest import make_job
from task_scheduler.application import ExternalEditResult, TaskCommandService
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
from task_scheduler.gui.controllers.discovery_controller import DiscoveryController
from task_scheduler.gui.controllers.editor_controller import EditorController
from task_scheduler.gui.controllers.external_control_worker import (
    ExternalControlKind,
    ExternalControlRequest,
    ExternalControlWorker,
)
from task_scheduler.gui.controllers.history_controller import (
    HistoryController,
)
from task_scheduler.gui.controllers.import_controller import ImportController
from task_scheduler.gui.controllers.json_transfer_controller import (
    JsonImportCommitOutcome,
    JsonImportOutcome,
    JsonTransferController,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from task_scheduler.gui.main_window import (
    EDIT_EXTERNAL_NO_CHANGES,
    EXTERNAL_DISABLE_UNKNOWN,
    EXTERNAL_DISABLE_UNLOADED,
    EXTERNAL_EDIT_BOOTOUT_FAILED,
    EXTERNAL_EDIT_RELOAD_FAILED,
    EXTERNAL_EDIT_SUCCESS_LOADED,
    EXTERNAL_EDIT_SUCCESS_UNLOADED,
    EXTERNAL_ENABLE_LOADED,
    EXTERNAL_ENABLE_NO_LABEL_TOOLTIP,
    EXTERNAL_ENABLE_UNKNOWN,
    EXTERNAL_ENABLE_UNLOADED,
    EXTERNAL_QUARANTINE_RESULT,
    EXTERNAL_REMOVE_RESULT,
    EXTERNAL_REMOVE_UNLOADED_FIRST,
    EXTERNAL_RUN_NOW_NO_LABEL_TOOLTIP,
    EXTERNAL_RUN_NOW_NOT_LOADED_TOOLTIP,
    RAW_REPLACEMENT_INVALID,
    REMOVED_SAVED_RESULT,
    MainWindow,
)
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.presenters.agent_presenter import (
    shell_safe_command,
)
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.external_control_dialog import (
    ExternalDisableConfirmDialog,
    ExternalEditGateDialog,
    ExternalRemoveConfirmDialog,
    ExternalReplaceGateDialog,
    RemoveSavedJobConfirmDialog,
)
from task_scheduler.gui.widgets.import_preview_dialog import ImportPreviewDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog
from task_scheduler.gui.widgets.raw_plist_editor import RawPlistEditor
from task_scheduler.platform.macos import (
    CommandSpec,
    ParseSupport,
    ProcessResult,
    parse_path,
)

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


def _window_full(qtbot: QtBot, controller: DiscoveryController) -> MainWindow:
    """A window wired to real services plus the JSON transfer controller."""
    services = controller._services
    window = MainWindow(
        controller,
        EditorController(services),
        LifecycleController(services),
        DiagnosticsController(services, {}),
        HistoryController(services),
        ImportController(services),
        services=services,
        json_transfer=JsonTransferController(services),
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
    external_a = make_job(id=EXTERNAL_A_ID, label="com.example.external", name="External Job")
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


class TestSelectionOutOfRange:
    def test_out_of_range_selection_index_is_ignored(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        world.manage(make_job())
        window = _window(qtbot, DiscoveryController(world.services))
        model = window._model
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
        """Edit Task is disabled with no selection; the method shows a hint."""
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        hint = "Select a task to edit it."
        assert window.edit_task_action.isEnabled() is False
        window.edit_task()
        assert window.statusBar().currentMessage() == hint
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


def _panel_text(window: MainWindow, object_name: str) -> str:
    """The panel's named text element (label or log tab), asserted present."""
    found = window.panel.findChild(object, object_name)
    assert found is not None
    if isinstance(found, QPlainTextEdit):
        return found.toPlainText()
    assert isinstance(found, QLabel)
    return found.text()


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
        window.table.setCurrentIndex(QModelIndex())
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

    def test_finished_ignores_foreign_payloads(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._on_lifecycle_finished("not an outcome")
        assert window._lifecycle_busy is False
        assert window._active_worker is None


class TestDiagnosticsTrigger:
    def test_trigger_without_selection_shows_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_test_triggered()
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_trigger_on_external_row_shows_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
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
        assert window._diagnostics_controller.request_test(listing.job) is TestVerdict.ACCEPTED
        window._on_test_triggered()
        assert window.statusBar().currentMessage() == "Cannot test: busy."

    def test_stale_outcome_is_not_rendered(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        job = make_job()
        world.manage(job)
        job_b = make_job(id=SECOND_JOB_ID, name="Second Job", label="zz.example.second")
        world.manage(job_b)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        window._on_test_finished(TestOutcome(label=job_b.label, result=None, error="boom"))
        assert _panel_text(window, "diagnostics-summary") == (
            "Run Test to check this task directly."
        )
        assert not window._diagnostics_busy

    def test_finished_ignores_foreign_payloads(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._on_test_finished("not an outcome")
        assert window._diagnostics_busy is False
        assert window._active_test_worker is None

    def test_refresh_renders_logs_and_environment(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        out = tmp_path / "out.log"
        out.write_text("persisted out\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=None))
        world.manage(job)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        window.panel.refresh_button.click()
        assert _panel_text(window, "diagnostics-persisted-stdout") == ("persisted out\n")
        assert "GUI process only: none" in _panel_text(window, "diagnostics-environment-text")

    def test_refresh_without_job_shows_hint(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_diagnostics_refresh()
        assert window.statusBar().currentMessage() == "Select a task to refresh its logs."

    def test_production_thread_dispatch(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path, test=ProcessResult(exit_code=0, stdout="direct out"))
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
        assert _panel_text(window, "diagnostics-summary") == ("Passed (exit code 0) in 0.00s")


class TestInspectorReadability:
    """Wrapped inspector text must never be vertically clipped.

    A wide per-widget font forces wrapping the same way the user's Retina
    display does, so the layout invariant is checked deterministically
    offscreen instead of discovered in the field.
    """

    def test_no_inspector_label_is_clipped_when_text_wraps(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        app = QApplication.instance()
        assert app is not None
        saved_font = app.font()
        app.setFont(QFont("Helvetica", 18))
        try:
            world, managed, *_ = _seed_three(tmp_path)
            window = _window(qtbot, DiscoveryController(world.services))
            window.resize(1282, 936)
            _select_managed(world, window, managed)
            inspector = window.inspector
            # Worst case: the user's long values, set after the initial pass.
            _value_label(inspector, "overview-name").setText(
                "ai.hermes.gateway-researcher"
            )
            _value_label(inspector, "overview-source").setText(
                "/Users/johnhoaglun/Library/LaunchAgents/"
                "ai.hermes.gateway-researcher.plist"
            )
            _value_label(inspector, "command-command").setText(
                "/Users/johnhoaglun/.hermes/hermes-agent/venv/bin/python -m "
                "hermes_cli.main --profile researcher gateway run --reload"
            )
            app.processEvents()
            app.processEvents()
            for label in inspector.findChildren(QLabel):
                if not label.isVisible():
                    continue
                if label.wordWrap():
                    assert label.height() >= label.heightForWidth(
                        label.width()
                    ), label.objectName()
                else:
                    assert label.width() >= label.fontMetrics().horizontalAdvance(
                        label.text()
                    ), label.text()
        finally:
            app.setFont(saved_font)


class TestHistoryPanelWiring:
    def test_right_pane_sections_are_vertically_resizable(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        splitter = window._right_splitter
        assert splitter.orientation().name == "Vertical"
        assert [splitter.widget(index) for index in range(splitter.count())] == [
            window.inspector,
            window.panel,
            window.history_panel,
        ]
        # Collapsed diagnostics/history: the inspector owns the bulk of the pane.
        sizes = splitter.sizes()
        assert sizes[0] > sizes[1] and sizes[0] > sizes[2]

    def test_inspector_pane_is_wider_than_the_task_list(self, qtbot: QtBot, tmp_path: Path) -> None:
        """The freed list-pane space goes to the inspector: right starts larger."""
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        splitter = next(
            s
            for s in window.centralWidget().findChildren(QSplitter)
            if s.orientation() == Qt.Orientation.Horizontal
        )
        assert splitter.widget(0) is window.table
        assert splitter.sizes()[1] > splitter.sizes()[0]

    def test_right_pane_has_no_badge_strip(self, qtbot: QtBot, tmp_path: Path) -> None:
        """The value-less status pills are gone; the pane is splitter-only."""
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        assert window.findChild(object, "agent-badge-strip") is None

    def test_inspector_values_wrap_without_horizontal_scrollbar(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Long values wrap; nothing can be clipped at the inspector's edge."""
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        scroll = window.inspector.findChild(QScrollArea)
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        wrapped = (
            "overview-name",
            "overview-label",
            "overview-classification",
            "overview-source",
            "overview-state",
            "overview-enabled",
            "overview-loaded",
            "schedule-preview-heading",
        )
        for name in wrapped:
            label = window.inspector.findChild(QLabel, name)
            assert label is not None and label.wordWrap()

    def test_close_stops_tracked_worker_threads(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        thread = QThread(window)
        window._track_worker_thread(thread)
        thread.start()
        qtbot.waitUntil(thread.isRunning)
        monkeypatch.setattr(MainWindow, "WORKER_THREAD_WAIT_MS", 100)
        window.close()
        assert not thread.isRunning()
        qtbot.waitUntil(lambda: thread not in window._worker_threads)

    def test_close_refuses_to_destroy_a_still_running_worker(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A worker that cannot quit keeps the main window alive safely."""
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))

        class StuckThread:
            def isRunning(self) -> bool:
                return True

            def quit(self) -> None:
                pass

            def wait(self, _: int) -> bool:
                return False

        window._worker_threads.add(StuckThread())  # type: ignore[arg-type]
        monkeypatch.setattr(MainWindow, "WORKER_THREAD_WAIT_MS", 0)
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        window._worker_threads.clear()

    def test_history_refresh_with_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        window._on_history_refresh()
        state = window.history_panel.findChild(object, "history-state-text")
        assert "No execution history recorded" in state.text()

    def test_history_refresh_without_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window.table.setCurrentIndex(QModelIndex())
        window._on_history_refresh()
        assert window.statusBar().currentMessage() == "Select a task to refresh its history."


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


def _import_window(qtbot: QtBot, world: FakeTaskWorld) -> MainWindow:
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
        monkeypatch.setattr(ImportPreviewDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
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
        self._write_plist(tmp_path, world, "com.external.imported.plist", EXTERNAL_PLIST.encode())
        window = _import_window(qtbot, world)
        self._select_external(window)
        monkeypatch.setattr(ImportPreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        window._on_import_triggered()
        assert len(list(world.catalog_root.glob("*.json"))) == 1
        assert window.statusBar().currentMessage() == ""


class TestWave3Composition:
    """3A: proxy mapping, empty-state sync, badges, and transfer/reveal/copy actions."""

    def test_actions_noop_without_context(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))  # no services
        window.table.setCurrentIndex(QModelIndex())
        window._on_reveal_plist()
        window._on_reveal_log("stderr")
        window._on_copy_command()
        window._on_copy_plist()
        window._on_export_json()
        window._on_import_json()
        assert "not available" in window.statusBar().currentMessage()

    def test_copy_command_and_generated_plist(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        window.copy_command_action.trigger()
        assert QApplication.clipboard().text() == shell_safe_command(window._selected_listing())
        monkeypatch.setattr(
            window._services, "generate_plist_for", lambda _job: "<plist>XML</plist>"
        )
        window.copy_plist_action.trigger()
        assert QApplication.clipboard().text() == "<plist>XML</plist>"

    def test_reveal_plist_and_logs(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = tmp_path / "out.log"
        out.write_text("log\n")
        job = make_job(logging=LoggingConfig(stdout_path=out, stderr_path=out))
        world = FakeTaskWorld(tmp_path)
        world.manage(job)
        window = _window_full(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, job)
        revealed: list[Path] = []
        monkeypatch.setattr(window._services, "reveal_path", lambda p: revealed.append(p) or None)
        window.reveal_plist_action.trigger()
        assert len(revealed) == 1
        window.reveal_stdout_action.trigger()
        assert revealed[1] == out
        # A reveal failure surfaces as a status message, not an exception.
        monkeypatch.setattr(window._services, "reveal_path", lambda _p: "cannot reveal")
        window._on_reveal_plist()
        assert "cannot reveal" in window.statusBar().currentMessage()
        window._on_reveal_log("stderr")
        assert "cannot reveal" in window.statusBar().currentMessage()
        # Saved-only listing resolves its plist through plist_path_for.
        saved = TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=job, managed=True)
        window._model.set_agents([saved])
        assert window._plist_path(window._model.listing_at(0)) == world.store.destination_for(
            job.label
        )
        # A listing with neither path nor job has nothing to reveal.
        bare = TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=None, managed=False)
        window._model.set_agents([bare])
        window.table.setCurrentIndex(window._proxy.index(0, 0))
        window._on_reveal_plist()
        assert "No plist path" in window.statusBar().currentMessage()
        # A job without a log path is reported, not raised.
        nologs = TaskListing(
            kind=ListingKind.SAVED,
            path=None,
            parsed=None,
            job=make_job(id=SECOND_JOB_ID, name="NoLogs", label="zz.example.nologs"),
            managed=True,
        )
        window._model.set_agents([nologs])
        window.table.setCurrentIndex(window._proxy.index(0, 0))
        window._on_reveal_log("stdout")
        assert "No log path" in window.statusBar().currentMessage()

    def test_export_json_roundtrip(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        import task_scheduler.gui.main_window as mw

        monkeypatch.setattr(
            mw.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *_a: ("/tmp/x.json", "")),
        )
        dest: list[Path] = []
        monkeypatch.setattr(
            window._services, "export_managed_json", lambda _label, p: dest.append(p)
        )
        window.export_json_action.trigger()
        assert dest == [Path("/tmp/x.json")]
        assert "Exported to" in window.statusBar().currentMessage()

        def _raise(_label, _p):
            raise FileExistsError("exists")

        monkeypatch.setattr(window._services, "export_managed_json", _raise)
        window.export_json_action.trigger()
        assert "Export failed" in window.statusBar().currentMessage()
        # A cancelled save dialog is a no-op (status unchanged).
        dest2: list[Path] = []
        monkeypatch.setattr(window._services, "export_managed_json", lambda _l, p: dest2.append(p))
        monkeypatch.setattr(mw.QFileDialog, "getSaveFileName", staticmethod(lambda *_a: ("", "")))
        window.export_json_action.trigger()
        assert dest2 == [] and "Export failed" in window.statusBar().currentMessage()

    def test_import_json_roundtrip(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        import task_scheduler.gui.main_window as mw
        from task_scheduler.gui.widgets.json_transfer_dialog import JsonTransferDialog

        refreshed: list[int] = []
        monkeypatch.setattr(window, "refresh", lambda: refreshed.append(1))
        # Cancelled dialog open: no-op.
        monkeypatch.setattr(mw.QFileDialog, "getOpenFileName", staticmethod(lambda *_a: ("", "")))
        window.import_json_action.trigger()
        assert refreshed == []
        monkeypatch.setattr(
            mw.QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *_a: ("/tmp/in.json", "")),
        )
        # Preview error: reported, no commit.
        bad = JsonImportOutcome(source_path=Path("/tmp/in.json"), error="bad")
        monkeypatch.setattr(window._json_transfer, "preview_import", lambda _p: bad)
        window.import_json_action.trigger()
        assert "Cannot import" in window.statusBar().currentMessage()
        # Rejected dialog: no commit.
        good = JsonImportOutcome(source_path=Path("/tmp/in.json"))
        monkeypatch.setattr(window._json_transfer, "preview_import", lambda _p: good)
        monkeypatch.setattr(JsonTransferDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
        window.import_json_action.trigger()
        assert refreshed == []
        # Commit error: reported, no refresh.
        monkeypatch.setattr(JsonTransferDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        monkeypatch.setattr(
            window._json_transfer,
            "commit",
            lambda _o: JsonImportCommitOutcome(error="boom"),
        )
        window.import_json_action.trigger()
        assert "Import failed" in window.statusBar().currentMessage()
        # Success: refresh is invoked.
        monkeypatch.setattr(
            window._json_transfer, "commit", lambda _o: JsonImportCommitOutcome(error=None)
        )
        window.import_json_action.trigger()
        assert refreshed == [1]

    def test_defensive_branches(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        # _row_for_identity skips proxy rows that map to no source row.
        previous = window._model.listing_at(0)
        monkeypatch.setattr(window, "_listing_at_table_row", lambda _row: None)
        assert window._row_for_identity(previous) == 0
        # Copy command reports when no command text is available.
        bare = TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=None, managed=False)
        monkeypatch.setattr(window, "_selected_listing", lambda: bare)
        window._on_copy_command()
        assert "No command available" in window.statusBar().currentMessage()


# -- universal task controls ---------------------------------------------------

EXTERNAL_EDIT_LABEL = "com.example.editable"
QUARANTINE_LABEL = "com.example.quarantine"
RAW_LABEL = "com.example.raw"


def _seed_external(tmp_path: Path, *, launches: list[ProcessResult] | None = None) -> FakeTaskWorld:
    world = FakeTaskWorld(tmp_path, launches=launches)
    world.store.write(make_job(label=EXTERNAL_EDIT_LABEL, name="External Editable"))
    return world


def _seed_all_kinds(tmp_path: Path) -> tuple[FakeTaskWorld, dict[str, Path]]:
    """One row per kind: managed installed, saved, external, unrepresentable."""
    world = FakeTaskWorld(tmp_path)
    managed = make_job()
    world.manage(managed)
    world.jobs.import_job(
        make_job(id=SECOND_JOB_ID, label="com.example.saved-only", name="Saved Only")
    )
    external = make_job(id=EXTERNAL_A_ID, label=EXTERNAL_EDIT_LABEL, name="External Editable")
    world.store.write(external)
    unrepresentable = _write_plist(
        world,
        "com.example.partial",
        {
            "Label": "com.example.partial",
            "ProgramArguments": ["/bin/sh", "-c", "echo partial"],
            "StartInterval": 60,
            "KeepAlive": True,
        },
    )
    return world, {
        "managed": world.store.destination_for(managed.label),
        "external": world.store.destination_for(external.label),
        "unrepresentable": unrepresentable,
    }


def _row_by_label(window: MainWindow, label: str) -> int:
    """The table row whose listing carries *label*, asserted present."""
    model = window.table.model()
    for row in range(model.rowCount()):
        listing = model.listing_at(row)
        if listing is not None and listing.job is not None and listing.job.label == label:
            return row
    raise AssertionError(f"no row for {label}")


def _write_plist(world: FakeTaskWorld, label: str, raw: dict[str, object]) -> Path:
    path = world.la_root / f"{label}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(raw))
    return path


def _external_row_path(world: FakeTaskWorld) -> Path:
    return world.la_root / f"{EXTERNAL_EDIT_LABEL}.plist"


def _mutating(specs: list[CommandSpec]) -> list[str]:
    """The non-``print`` launchctl subcommands, in order (refresh noise dropped)."""
    return [spec.argv[1] for spec in specs if spec.argv[1] != "print"]


def _select_row(window: MainWindow, row: int) -> None:
    model = window.table.model()
    window.table.setCurrentIndex(model.index(row, 0))


def _select_external_row(window: MainWindow, world: FakeTaskWorld) -> None:
    _select_row(window, _row_by_path(window.table.model(), _external_row_path(world)))


def _select_plist_row(window: MainWindow, world: FakeTaskWorld, label: str) -> None:
    _select_row(window, _row_by_path(window.table.model(), world.la_root / f"{label}.plist"))


def _script_external_dialogs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate_a: bool = True,
    gate_b: bool = True,
    disable: bool = True,
    remove: bool = True,
    saved: bool = True,
) -> list[str]:
    """Script the external confirm dialogs and record shown titles, in order."""
    titles: list[str] = []

    def _make(script: bool):
        def fake_exec(self: QDialog) -> int:
            titles.append(self.windowTitle())
            self._accepted = script  # type: ignore[attr-defined]
            return QDialog.DialogCode.Accepted if script else QDialog.DialogCode.Rejected

        return fake_exec

    monkeypatch.setattr(ExternalEditGateDialog, "exec", _make(gate_a))
    monkeypatch.setattr(ExternalReplaceGateDialog, "exec", _make(gate_b))
    monkeypatch.setattr(ExternalDisableConfirmDialog, "exec", _make(disable))
    monkeypatch.setattr(ExternalRemoveConfirmDialog, "exec", _make(remove))
    monkeypatch.setattr(RemoveSavedJobConfirmDialog, "exec", _make(saved))
    return titles


def _fake_editor_save(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    *,
    save: bool = True,
    mutate: bool = True,
) -> None:
    """Run the editor's save synchronously; *mutate* changes the schedule time."""

    def fake_exec(self: JobEditor) -> int:
        if not save:
            return QDialog.DialogCode.Rejected
        if mutate:
            self.findChild(QLineEdit, "editor-time").setText("03:00")
        self._on_save()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(JobEditor, "exec", fake_exec)


def _fake_raw_editor(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accept: bool = True,
    replacement: str | None = None,
) -> list[tuple[str, bool]]:
    """Script RawPlistEditor; record (opened text, binary mode) of each open."""
    opened: list[tuple[str, bool]] = []

    def fake_open(
        self: RawPlistEditor,
        *,
        source_path: Path,
        text: str,
        binary_mode: bool,
        label: str | None,
    ) -> None:
        opened.append((text, binary_mode))

    def fake_exec(self: RawPlistEditor) -> int:
        if not accept:
            self._replacement = None
            return QDialog.DialogCode.Rejected
        self._replacement = replacement
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(RawPlistEditor, "open", fake_open)
    monkeypatch.setattr(RawPlistEditor, "exec", fake_exec)
    return opened


def _run_external_synchronously(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    def _start(worker: ExternalControlWorker) -> None:
        worker.finished.connect(window._on_external_finished)
        worker.run()

    monkeypatch.setattr(window, "_start_external_worker", _start)


class TestUniversalExternalEdit:
    def test_no_change_save_shows_pinned_message(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _fake_editor_save(window, monkeypatch, mutate=False)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert window.statusBar().currentMessage() == EDIT_EXTERNAL_NO_CHANGES
        assert not window._external_busy
        assert _mutating(world.launch_runner.specs) == []

    def test_gate_a_cancel_writes_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch, gate_a=False)
        _fake_editor_save(window, monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        path = _external_row_path(world)
        before = path.read_bytes()
        specs_before = len(world.launch_runner.specs)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert path.read_bytes() == before
        assert world.launch_runner.specs[specs_before:] == []
        assert list(world.la_root.iterdir()) == [path]
        assert not window._external_busy

    def test_gate_b_cancel_writes_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch, gate_b=False)
        _fake_editor_save(window, monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        path = _external_row_path(world)
        before = path.read_bytes()
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == [
            "Edit External LaunchAgent?",
            "Replace External LaunchAgent Plist?",
        ]
        assert path.read_bytes() == before
        assert all("print" in spec.argv for spec in world.launch_runner.specs)
        assert not window._external_busy

    def test_editor_reject_stops_before_gate_b(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _fake_editor_save(window, monkeypatch, save=False)
        _run_external_synchronously(window, monkeypatch)
        path = _external_row_path(world)
        before = path.read_bytes()
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert path.read_bytes() == before
        assert not window._external_busy

    def test_session_rejection_shows_verbatim_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        error = "the source plist changed outside this application; review it and open it again"

        def boom(path: Path) -> object:
            raise ValueError(error)

        monkeypatch.setattr(world.services, "open_external_edit_session", boom)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert window.statusBar().currentMessage() == error
        assert not window._external_busy

    def test_source_drift_reports_pinned_conflict(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _fake_editor_save(window, monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        path = _external_row_path(world)
        original = world.services.commit_structured_external_edit

        def drift(*args: object, **kwargs: object) -> object:
            path.write_bytes(b"<changed>")
            return original(*args, **kwargs)

        monkeypatch.setattr(world.services, "commit_structured_external_edit", drift)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert titles == [
            "Edit External LaunchAgent?",
            "Replace External LaunchAgent Plist?",
        ]
        assert window.statusBar().currentMessage() == (
            "the source plist changed outside this application; review it and open it again"
        )
        assert path.read_bytes() == b"<changed>"
        assert list(world.la_root.glob("*.backup.*")) == []

    def test_bootstrap_failure_reports_retained_backup(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fail = ProcessResult(exit_code=1)
        ok = ProcessResult(exit_code=0)
        # 3 status prints (2 construction + session), bootout ok, bootstrap fail
        world = _seed_external(tmp_path, launches=[ok, ok, ok, ok, fail])
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        _fake_editor_save(window, monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        path = _external_row_path(world)
        assert parse_path(path).status is ParseSupport.SUPPORTED
        backups = sorted(world.la_root.glob("*.backup.*"))
        assert len(backups) == 1
        assert window.statusBar().currentMessage() == EXTERNAL_EDIT_RELOAD_FAILED.format(
            backup=str(backups[0])
        )

    def test_unknown_status_edits_without_bootout_bootstrap(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unknown = ProcessResult(exit_code=None)
        world = _seed_external(tmp_path, launches=[unknown, unknown])
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        _fake_editor_save(window, monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.edit_task_action.trigger()
        assert window.statusBar().currentMessage() == EXTERNAL_EDIT_SUCCESS_UNLOADED
        assert _mutating(world.launch_runner.specs) == []


class TestUniversalExternalLifecycle:
    def test_disable_unloaded_skips_bootout(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        not_loaded = ProcessResult(exit_code=1)
        world = _seed_external(tmp_path, launches=[not_loaded, not_loaded])
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.disable_action.trigger()
        assert window.statusBar().currentMessage() == EXTERNAL_DISABLE_UNLOADED.format(
            label=EXTERNAL_EDIT_LABEL
        )
        assert _mutating(world.launch_runner.specs) == ["disable"]

    def test_disable_unknown_status_skips_bootout(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unknown = ProcessResult(exit_code=None)
        world = _seed_external(tmp_path, launches=[unknown, unknown])
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.disable_action.trigger()
        assert window.statusBar().currentMessage() == EXTERNAL_DISABLE_UNKNOWN.format(
            label=EXTERNAL_EDIT_LABEL
        )
        assert _mutating(world.launch_runner.specs) == ["disable"]

    def test_disable_without_label_quarantines(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        path = _write_plist(world, QUARANTINE_LABEL, {"ProgramArguments": ["/bin/true"]})
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_plist_row(window, world, QUARANTINE_LABEL)
        assert window.disable_action.isEnabled()
        assert window.enable_action.isEnabled() is False
        assert window.run_now_action.isEnabled() is False
        assert window.enable_action.toolTip() == EXTERNAL_ENABLE_NO_LABEL_TOOLTIP
        assert window.run_now_action.toolTip() == EXTERNAL_RUN_NOW_NO_LABEL_TOOLTIP
        window.disable_action.trigger()
        assert titles == ["Disable External LaunchAgent?"]
        dest = world.la_root / ".task-scheduler-disabled" / f"{QUARANTINE_LABEL}-1.plist"
        assert dest.is_file()
        assert not path.exists()
        assert window.statusBar().currentMessage() == EXTERNAL_QUARANTINE_RESULT.format(
            source=path, dest=dest
        )
        assert world.launch_runner.specs == []
        assert window._selected_listing() is None

    def test_enable_loaded_shows_pinned_message(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        assert window.enable_action.isEnabled()
        window.enable_action.trigger()
        assert titles == []
        assert window.statusBar().currentMessage() == EXTERNAL_ENABLE_LOADED.format(
            label=EXTERNAL_EDIT_LABEL
        )
        assert _mutating(world.launch_runner.specs) == ["enable"]

    def test_enable_unloaded_loads_it(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        not_loaded = ProcessResult(exit_code=1)
        ok = ProcessResult(exit_code=0)
        # 3 status prints (2 construction + enable) not-loaded, then bootstrap ok
        world = _seed_external(tmp_path, launches=[not_loaded, not_loaded, not_loaded, ok])
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.enable_action.trigger()
        assert window.statusBar().currentMessage() == EXTERNAL_ENABLE_UNLOADED.format(
            label=EXTERNAL_EDIT_LABEL
        )
        assert _mutating(world.launch_runner.specs) == ["enable", "bootstrap"]

    def test_run_now_loaded_kickstarts(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        assert window.run_now_action.isEnabled()
        assert window.run_now_action.toolTip() not in (
            EXTERNAL_RUN_NOW_NOT_LOADED_TOOLTIP,
            EXTERNAL_RUN_NOW_NO_LABEL_TOOLTIP,
        )
        window.run_now_action.trigger()
        assert titles == []
        argvs = [spec.argv for spec in world.launch_runner.specs]
        assert (
            argvs.count(["/bin/launchctl", "kickstart", "-k", f"gui/1000/{EXTERNAL_EDIT_LABEL}"])
            == 1
        )


class TestUniversalRemove:
    def test_remove_external_loaded_backs_up_and_unloads_first(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = _seed_external(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_external_row(window, world)
        window.remove_task_action.trigger()
        assert titles == ["Remove External LaunchAgent?"]
        path = _external_row_path(world)
        assert not path.exists()
        backups = sorted(world.la_root.glob("*.backup.*"))
        assert len(backups) == 1
        assert (
            window.statusBar().currentMessage()
            == EXTERNAL_REMOVE_RESULT.format(path=path, backup=backups[0])
            + EXTERNAL_REMOVE_UNLOADED_FIRST
        )
        assert _mutating(world.launch_runner.specs) == ["bootout"]
        assert window._selected_listing() is None

    def test_remove_saved_shows_pinned_message(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, _ = _seed_all_kinds(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _run_external_synchronously(window, monkeypatch)
        _select_row(window, _row_by_label(window, "com.example.saved-only"))
        window.remove_task_action.trigger()
        assert titles == ["Remove Saved Task?"]
        assert window.statusBar().currentMessage() == REMOVED_SAVED_RESULT.format(name="Saved Only")
        assert all(job.label != "com.example.saved-only" for job in world.jobs.list_jobs())
        model = window.table.model()
        assert not any(
            (listing := model.listing_at(row)) is not None
            and listing.job is not None
            and listing.job.label == "com.example.saved-only"
            for row in range(model.rowCount())
        )


class TestUniversalRawEdit:
    def test_binary_source_shows_base64_and_normalizes(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        raw = {"Label": RAW_LABEL, "ProgramArguments": ["/bin/true"], "KeepAlive": True}
        path = world.la_root / f"{RAW_LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        source = plistlib.dumps(raw, fmt=plistlib.FMT_BINARY)
        path.write_bytes(source)
        window = _window_full(qtbot, DiscoveryController(world.services))
        _script_external_dialogs(monkeypatch)
        new_raw = {
            "Label": RAW_LABEL,
            "ProgramArguments": ["/bin/true"],
            "KeepAlive": True,
            "WorkingDirectory": "/tmp",
        }
        canonical = plistlib.dumps(new_raw, fmt=plistlib.FMT_XML)
        opened = _fake_raw_editor(
            monkeypatch, replacement=base64.b64encode(canonical).decode("ascii")
        )
        _run_external_synchronously(window, monkeypatch)
        _select_plist_row(window, world, RAW_LABEL)
        window.edit_task_action.trigger()
        assert len(opened) == 1
        assert opened[0][0] == base64.b64encode(source).decode("ascii")
        assert opened[0][1] is True
        assert path.read_bytes() == canonical
        assert window.statusBar().currentMessage() == EXTERNAL_EDIT_SUCCESS_LOADED

    def test_binary_replacement_invalid_shows_pinned_error(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        raw = {"Label": RAW_LABEL, "ProgramArguments": ["/bin/true"], "KeepAlive": True}
        path = world.la_root / f"{RAW_LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        source = plistlib.dumps(raw, fmt=plistlib.FMT_BINARY)
        path.write_bytes(source)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _fake_raw_editor(monkeypatch, replacement="not-valid-base64!!")
        _run_external_synchronously(window, monkeypatch)
        _select_plist_row(window, world, RAW_LABEL)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert window.statusBar().currentMessage() == RAW_REPLACEMENT_INVALID
        assert path.read_bytes() == source
        assert list(world.la_root.glob("*.backup.*")) == []
        assert not window._external_busy

    def test_raw_editor_reject_writes_nothing(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        raw = {"Label": RAW_LABEL, "ProgramArguments": ["/bin/true"], "KeepAlive": True}
        path = world.la_root / f"{RAW_LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        source = plistlib.dumps(raw, fmt=plistlib.FMT_XML)
        path.write_bytes(source)
        window = _window_full(qtbot, DiscoveryController(world.services))
        titles = _script_external_dialogs(monkeypatch)
        _fake_raw_editor(monkeypatch, accept=False)
        _run_external_synchronously(window, monkeypatch)
        _select_plist_row(window, world, RAW_LABEL)
        window.edit_task_action.trigger()
        assert titles == ["Edit External LaunchAgent?"]
        assert path.read_bytes() == source
        assert list(world.la_root.glob("*.backup.*")) == []
        assert not window._external_busy


def _ext_result(world: FakeTaskWorld, *, exit_code: int = 0) -> ExternalEditResult:
    return ExternalEditResult(
        source_path=world.la_root / "x.plist",
        label="x",
        process=ProcessResult(exit_code=exit_code),
        phases=(),
        completed_phases=(),
        retained_artifacts=(world.la_root / "x.plist.staged.1",),
        replaced=False,
        reloaded=False,
    )


class TestExternalControlCoverage:
    """White-box coverage of defensive branches the interaction tests skip."""

    def _window(self, qtbot: QtBot, tmp_path: Path) -> tuple[FakeTaskWorld, MainWindow]:
        world = FakeTaskWorld(tmp_path)
        return world, _window_full(qtbot, DiscoveryController(world.services))

    def test_edit_managed_no_job(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._edit_managed_listing(
            TaskListing(kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=True)
        )
        assert window.statusBar().currentMessage() == "Select a task to edit it."

    def test_edit_external_unavailable(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._edit_external_listing(
            TaskListing(
                kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
            )
        )
        assert window.statusBar().currentMessage() == "External editing is not available."

    def test_start_external_no_services(self, qtbot: QtBot, tmp_path: Path) -> None:
        world = FakeTaskWorld(tmp_path)
        window = _window(qtbot, DiscoveryController(world.services))
        window._start_external(
            ExternalControlRequest(
                kind=ExternalControlKind.DISABLE, path=world.la_root / "x.plist"
            ),
            None,
            "msg",
        )
        assert window.statusBar().currentMessage() == "External controls are not available."

    def test_start_external_busy(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._external_busy = True
        window._start_external(
            ExternalControlRequest(
                kind=ExternalControlKind.DISABLE, path=world.la_root / "x.plist"
            ),
            None,
            "msg",
        )
        assert window.statusBar().currentMessage() == "Another operation is in progress."

    def test_show_edit_bootout_failed(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._show_external_result(
            ExternalControlKind.RAW_EDIT, _ext_result(world, exit_code=1), True
        )
        assert window.statusBar().currentMessage() == EXTERNAL_EDIT_BOOTOUT_FAILED.format(
            staged=str(world.la_root / "x.plist.staged.1")
        )

    def test_show_enable_unknown(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._show_external_result(ExternalControlKind.ENABLE, _ext_result(world), None)
        assert window.statusBar().currentMessage() == EXTERNAL_ENABLE_UNKNOWN.format(label="x")

    def test_run_external_lifecycle_no_path(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._run_external_lifecycle(
            LifecycleAction.DISABLE,
            TaskListing(
                kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
            ),
        )
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_remove_no_selection(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._on_remove_task_triggered()
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_remove_saved_no_job(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._remove_saved_listing(
            TaskListing(kind=ListingKind.SAVED, path=None, parsed=None, job=None, managed=True)
        )
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_remove_external_no_path(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        window._remove_external_listing(
            TaskListing(
                kind=ListingKind.DISCOVERED, path=None, parsed=None, job=None, managed=False
            )
        )
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_open_raw_editor_read_error(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)

        class _Session:
            source_path = world.la_root / "missing.plist"

        window._open_raw_editor(_Session())
        assert window.statusBar().currentMessage() == "Cannot read external plist file."

    def test_canonicalize_raw_not_dict(self, qtbot: QtBot, tmp_path: Path) -> None:
        world, window = self._window(qtbot, tmp_path)
        text = base64.b64encode(plistlib.dumps([1, 2, 3], fmt=plistlib.FMT_XML)).decode("ascii")
        assert window._canonicalize_raw_replacement(text) is None
        assert window.statusBar().currentMessage() == RAW_REPLACEMENT_INVALID

    def test_disable_dialog_declined(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(item for item in world.services.list_agents() if not item.managed)
        _script_external_dialogs(monkeypatch, disable=False)
        window._run_external_lifecycle(LifecycleAction.DISABLE, listing)
        assert not window._external_busy

    def test_remove_external_dialog_declined(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(item for item in world.services.list_agents() if not item.managed)
        _script_external_dialogs(monkeypatch, remove=False)
        window._remove_external_listing(listing)
        assert not window._external_busy

    def test_remove_saved_dialog_declined(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.jobs.import_job(
            make_job(
                id=UUID("22222222-2222-4222-8222-222222222222"),
                label="com.example.saved",
                name="Saved",
            )
        )
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(
            item for item in world.services.list_agents() if item.kind is ListingKind.SAVED
        )
        _script_external_dialogs(monkeypatch, saved=False)
        window._remove_saved_listing(listing)
        assert not window._external_busy

    def test_remove_saved_failed(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = FakeTaskWorld(tmp_path)
        world.jobs.import_job(
            make_job(
                id=UUID("33333333-3333-4333-8333-333333333333"),
                label="com.example.saved",
                name="Saved",
            )
        )
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(
            item for item in world.services.list_agents() if item.kind is ListingKind.SAVED
        )
        _script_external_dialogs(monkeypatch, saved=True)
        monkeypatch.setattr(
            window._lifecycle_controller, "request_remove_saved", lambda _label: None
        )
        window._remove_saved_listing(listing)
        assert window.statusBar().currentMessage() == "Failed to remove saved task."

    def test_raw_gate_declined(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, window = self._window(qtbot, tmp_path)
        raw = {"Label": "com.example.raw", "ProgramArguments": ["/bin/true"]}
        path = world.la_root / "com.example.raw.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(raw, fmt=plistlib.FMT_XML))

        class _Session:
            source_path = path
            label = "com.example.raw"
            loaded = False

        _script_external_dialogs(monkeypatch, gate_b=False)
        _fake_raw_editor(
            monkeypatch, accept=True, replacement=plistlib.dumps(raw, fmt=plistlib.FMT_XML).decode()
        )
        window._open_raw_editor(_Session())
        assert not window._external_busy

    def test_remove_managed_installed_routes_uninstall(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, managed, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        _select_managed(world, window, managed)
        monkeypatch.setattr(window, "_on_lifecycle_triggered", lambda _action: None)
        window._on_remove_task_triggered()
        assert window.statusBar().currentMessage() == ""

    def test_edit_external_edited_none(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(item for item in world.services.list_agents() if not item.managed)
        _script_external_dialogs(monkeypatch, gate_a=True)
        monkeypatch.setattr(JobEditor, "exec", lambda self: QDialog.DialogCode.Accepted)
        window._edit_external_listing(listing)
        assert not window._external_busy

    def test_lifecycle_managed_no_job(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, window = self._window(qtbot, tmp_path)
        monkeypatch.setattr(
            window,
            "_selected_listing",
            lambda: TaskListing(
                kind=ListingKind.SAVED, path=None, parsed=None, job=None, managed=True
            ),
        )
        window._on_lifecycle_triggered(LifecycleAction.UNINSTALL)
        assert window.statusBar().currentMessage() == "Select a task first."

    def test_external_worker_thread_body(
        self, qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world, *_ = _seed_three(tmp_path)
        window = _window_full(qtbot, DiscoveryController(world.services))
        listing = next(item for item in world.services.list_agents() if not item.managed)
        _script_external_dialogs(monkeypatch, disable=True)
        window._run_external_lifecycle(LifecycleAction.DISABLE, listing)
        qtbot.waitUntil(lambda: not window._external_busy, timeout=5000)
        assert not window._external_busy
