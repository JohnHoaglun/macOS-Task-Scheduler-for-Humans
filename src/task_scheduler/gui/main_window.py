"""Main window presenting the discovered-agent browser with an inspector."""

from __future__ import annotations

import base64
import plistlib
from pathlib import Path

from PySide6.QtCore import QItemSelection, QMetaObject, Qt, QThread
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application import ExternalEditResult, ExternalEditSession
from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.application.task_command_service import (
    ListingKind,
    TaskCommandService,
    TaskListing,
)
from task_scheduler.domain import JobDefinition
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
from task_scheduler.gui.controllers.external_control_worker import (
    ExternalControlKind,
    ExternalControlRequest,
    ExternalControlWorker,
)
from task_scheduler.gui.controllers.history_controller import (
    HistoryController,
    HistoryOutcome,
)
from task_scheduler.gui.controllers.import_controller import (
    ImportController,
)
from task_scheduler.gui.controllers.json_transfer_controller import (
    JsonTransferController,
)
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
    RequestVerdict,
    usable_external_label,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from task_scheduler.gui.models.agent_filter_proxy_model import AgentFilterProxyModel
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.presenters.agent_badge_presenter import agent_badges
from task_scheduler.gui.presenters.agent_presenter import shell_safe_command
from task_scheduler.gui.presenters.history_presenter import HISTORY_NOT_APPLICABLE
from task_scheduler.gui.widgets.agent_badge import AgentBadge
from task_scheduler.gui.widgets.agent_empty_state import AgentEmptyState
from task_scheduler.gui.widgets.agent_filter_controls import AgentFilterControls
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel
from task_scheduler.gui.widgets.external_control_dialog import (
    ExternalDisableConfirmDialog,
    ExternalEditGateDialog,
    ExternalRemoveConfirmDialog,
    ExternalReplaceGateDialog,
    RemoveSavedJobConfirmDialog,
)
from task_scheduler.gui.widgets.history_panel import HistoryPanel
from task_scheduler.gui.widgets.import_preview_dialog import ImportPreviewDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.json_transfer_dialog import JsonTransferDialog
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog
from task_scheduler.gui.widgets.raw_plist_editor import RawPlistEditor

__all__ = [
    "MainWindow",
    "EDIT_EXTERNAL_NO_CHANGES",
    "EXTERNAL_EDIT_SUCCESS_LOADED",
    "EXTERNAL_EDIT_SUCCESS_UNLOADED",
    "EXTERNAL_EDIT_RELOAD_FAILED",
    "EXTERNAL_EDIT_BOOTOUT_FAILED",
    "EXTERNAL_DISABLE_LOADED",
    "EXTERNAL_DISABLE_UNLOADED",
    "EXTERNAL_DISABLE_UNKNOWN",
    "EXTERNAL_QUARANTINE_RESULT",
    "EXTERNAL_ENABLE_LOADED",
    "EXTERNAL_ENABLE_UNLOADED",
    "EXTERNAL_ENABLE_UNKNOWN",
    "EXTERNAL_REMOVE_RESULT",
    "EXTERNAL_REMOVE_UNLOADED_FIRST",
    "REMOVED_SAVED_RESULT",
    "RAW_REPLACEMENT_INVALID",
]

EDIT_EXTERNAL_NO_CHANGES = "No changes to save."
EXTERNAL_EDIT_SUCCESS_LOADED = (
    "Updated external LaunchAgent and reloaded it successfully. It remains External."
)
EXTERNAL_EDIT_SUCCESS_UNLOADED = "Updated external LaunchAgent. It remains External."
EXTERNAL_EDIT_RELOAD_FAILED = (
    "The plist was replaced, but launchd could not reload it. "
    "The previous plist is retained at: {backup}"
)
EXTERNAL_EDIT_BOOTOUT_FAILED = (
    "The LaunchAgent could not be unloaded, so the plist was not changed. "
    "A staged copy is retained at: {staged}"
)
EXTERNAL_DISABLE_LOADED = (
    "Disabled {label}. launchd will not restart it; the running instance was unloaded."
)
EXTERNAL_DISABLE_UNLOADED = "Disabled {label}. launchd will not start it."
EXTERNAL_DISABLE_UNKNOWN = (
    "Disabled {label}. The loaded state could not be determined, so no unload was attempted."
)
EXTERNAL_QUARANTINE_RESULT = (
    "Quarantined {source} to {dest}. launchd will no longer load it from its original location."
)
EXTERNAL_ENABLE_LOADED = "Enabled {label}."
EXTERNAL_ENABLE_UNLOADED = "Enabled {label} and loaded it."
EXTERNAL_ENABLE_UNKNOWN = (
    "Enabled {label}. It could not be verified that it is loaded; it will start at the next login."
)
EXTERNAL_REMOVE_RESULT = "Removed {path}. A backup is retained at: {backup}."
EXTERNAL_REMOVE_UNLOADED_FIRST = " It was unloaded first."
REMOVED_SAVED_RESULT = "Removed {name} from the catalog."
RAW_REPLACEMENT_INVALID = "the replacement is not a valid plist"
EXTERNAL_ENABLE_NO_LABEL_TOOLTIP = (
    "This task has no usable launchd label, so it cannot be enabled through launchd. "
    "Edit the plist to add a valid label, or remove the task."
)
EXTERNAL_RUN_NOW_NOT_LOADED_TOOLTIP = (
    "This task is not currently loaded in launchd. Enable it first to load it."
)
EXTERNAL_RUN_NOW_NO_LABEL_TOOLTIP = "This task has no usable launchd label."


class MainWindow(QMainWindow):
    """Main window: a discovered-agent table on the left, an inspector on the right."""

    def __init__(
        self,
        controller: DiscoveryController,
        editor: EditorController,
        lifecycle: LifecycleController,
        diagnostics: DiagnosticsController,
        history: HistoryController,
        import_ctrl: ImportController | None = None,
        services: TaskCommandService | None = None,
        json_transfer: JsonTransferController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._editor_controller = editor
        self._lifecycle_controller = lifecycle
        self._lifecycle_busy = False
        self._active_worker: LifecycleWorker | None = None
        self._external_busy = False
        self._active_external_worker: ExternalControlWorker | None = None
        self._external_kind: ExternalControlKind | None = None
        self._external_loaded: bool | None = None
        self._diagnostics_controller = diagnostics
        self._diagnostics_busy = False
        self._active_test_worker: DiagnosticsWorker | None = None
        self._history_controller = history
        self._import_controller = import_ctrl
        self._services = services
        self._json_transfer = json_transfer
        self._editor = JobEditor(editor, diagnostics=diagnostics)
        self._model = AgentTableModel()
        self._proxy = AgentFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self.table = QTreeView()
        self.table.setModel(self._proxy)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.header().setStretchLastSection(True)
        self._filter_controls = AgentFilterControls(self)
        self._filter_controls.attach(self._proxy)
        self._empty_state = AgentEmptyState(self)
        self._badge_strip = QWidget()
        self._badge_strip.setObjectName("agent-badge-strip")
        self._badge_layout = QHBoxLayout(self._badge_strip)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        self._badges = [AgentBadge() for _ in range(5)]
        for badge in self._badges:
            self._badge_layout.addWidget(badge)
        self._badge_strip.hide()
        self.inspector = AgentInspector()
        self.panel = DiagnosticLogsPanel()
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._badge_strip)
        right_layout.addWidget(self.inspector, 1)
        right_layout.addWidget(self.panel)
        self.history_panel = HistoryPanel()
        right_layout.addWidget(self.history_panel)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(right_pane)
        splitter.setSizes([600, 400])
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self._filter_controls)
        central_layout.addWidget(self._empty_state)
        central_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh)
        self.new_task_action = QAction("New Task...", self)
        self.new_task_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_task_action.triggered.connect(self.new_task)
        self.edit_task_action = QAction("Edit Task…", self)
        self.edit_task_action.triggered.connect(self.edit_task)
        self.import_action = QAction("Import as Managed Job...", self)
        self.import_action.setEnabled(False)
        self.import_action.triggered.connect(self._on_import_triggered)
        self.remove_task_action = QAction("Remove Task…", self)
        self.remove_task_action.triggered.connect(self._on_remove_task_triggered)
        self.export_json_action = QAction("Export JSON...", self)
        self.export_json_action.setEnabled(False)
        self.export_json_action.triggered.connect(self._on_export_json)
        self.import_json_action = QAction("Import JSON...", self)
        self.import_json_action.triggered.connect(self._on_import_json)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_task_action)
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.remove_task_action)
        file_menu.addAction(self.export_json_action)
        file_menu.addAction(self.import_json_action)
        file_menu.addAction(self.refresh_action)
        self.edit_menu = self.menuBar().addMenu("Edit")
        self.edit_menu.addAction(self.edit_task_action)
        self.reveal_plist_action = QAction("Reveal Plist", self)
        self.reveal_plist_action.setEnabled(False)
        self.reveal_plist_action.triggered.connect(self._on_reveal_plist)
        self.reveal_stdout_action = QAction("Reveal Stdout Log", self)
        self.reveal_stdout_action.setEnabled(False)
        self.reveal_stdout_action.triggered.connect(
            lambda _checked=False: self._on_reveal_log("stdout")
        )
        self.reveal_stderr_action = QAction("Reveal Stderr Log", self)
        self.reveal_stderr_action.setEnabled(False)
        self.reveal_stderr_action.triggered.connect(
            lambda _checked=False: self._on_reveal_log("stderr")
        )
        self.copy_command_action = QAction("Copy Command", self)
        self.copy_command_action.setEnabled(False)
        self.copy_command_action.triggered.connect(self._on_copy_command)
        self.copy_plist_action = QAction("Copy Generated Plist", self)
        self.copy_plist_action.setEnabled(False)
        self.copy_plist_action.triggered.connect(self._on_copy_plist)
        actions_menu = self.menuBar().addMenu("Actions")
        for action in (
            self.reveal_plist_action,
            self.reveal_stdout_action,
            self.reveal_stderr_action,
            self.copy_command_action,
            self.copy_plist_action,
        ):
            actions_menu.addAction(action)
        self.test_action = QAction("Test Task", self)
        self.test_action.setEnabled(False)
        self.test_action.triggered.connect(self._on_test_triggered)
        diagnostics_menu = self.menuBar().addMenu("Diagnostics")
        diagnostics_menu.addAction(self.test_action)
        self.panel.refresh_button.clicked.connect(self._on_diagnostics_refresh)
        self.history_panel.refresh_requested.connect(self._on_history_refresh)
        self.install_action = QAction("Install", self)
        self.reinstall_action = QAction("Reinstall...", self)
        self.uninstall_action = QAction("Uninstall...", self)
        self.enable_action = QAction("Enable", self)
        self.disable_action = QAction("Disable", self)
        self.run_now_action = QAction("Run Now", self)
        lifecycle_actions = (
            (self.install_action, LifecycleAction.INSTALL),
            (self.reinstall_action, LifecycleAction.REINSTALL),
            (self.uninstall_action, LifecycleAction.UNINSTALL),
            (self.enable_action, LifecycleAction.ENABLE),
            (self.disable_action, LifecycleAction.DISABLE),
            (self.run_now_action, LifecycleAction.RUN_NOW),
        )
        lifecycle_menu = self.menuBar().addMenu("Lifecycle")
        for action, lifecycle_action in lifecycle_actions:
            action.setEnabled(False)
            action.triggered.connect(
                lambda _checked=False, lifecycle_action=lifecycle_action: (
                    self._on_lifecycle_triggered(lifecycle_action)
                )
            )
            lifecycle_menu.addAction(action)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._empty_state.cleared.connect(self._filter_controls.reset)
        self._proxy.layoutChanged.connect(self._update_empty_state)
        self.refresh()

    def refresh(self) -> None:
        """Reload the agent listings, preserving the selected agent when possible."""
        outcome = self._controller.refresh()
        if outcome.error is not None:
            self._model.set_agents([])
            self.inspector.show_error(outcome.error)
            self.statusBar().showMessage(outcome.error)
            self._update_empty_state()
            self._populate_badges(None)
            self._update_lifecycle_actions()
            return
        if not outcome.agents:
            self._model.set_agents([])
            self.inspector.show_placeholder("No tasks found.")
            self.statusBar().clearMessage()
            self._update_empty_state()
            self._populate_badges(None)
            self._update_lifecycle_actions()
            return
        previous = self._selected_listing()
        self._model.set_agents(outcome.agents)
        self._update_empty_state()
        row = self._row_for_identity(previous)
        if row < self._proxy.rowCount():
            self.table.setCurrentIndex(self._proxy.index(row, 0))
        self._populate_badges(self._selected_listing())
        self.statusBar().clearMessage()
        self._update_lifecycle_actions()

    def new_task(self) -> None:
        """Open the editor for a new managed task and refresh on save."""
        self._editor.open_new()
        self._editor.exec()
        if self._editor.saved_path is not None:
            self.refresh()

    def edit_task(self) -> None:
        """Open the editor for the selected task, managed or external."""
        listing = self._selected_listing()
        if listing is None:
            self.statusBar().showMessage("Select a task to edit it.")
            return
        if listing.managed:
            self._edit_managed_listing(listing)
        else:
            self._edit_external_listing(listing)

    def _edit_managed_listing(self, listing: TaskListing) -> None:
        """Resolve the managed job, open it in the editor, refresh on save."""
        if listing.job is None:
            self.statusBar().showMessage("Select a task to edit it.")
            return
        try:
            resolved = self._editor_controller.resolve(listing.job.label)
        except JobNotFoundError:
            self.statusBar().showMessage("This task is not in the task catalog.")
            return
        self._editor.open_existing(resolved)
        self._editor.exec()
        if self._editor.saved_path is not None:
            self.refresh()

    def _edit_external_listing(self, listing: TaskListing) -> None:
        """Gate A, open the edit session, then edit the external plist."""
        services = self._services
        path = listing.path
        if services is None or path is None:
            self.statusBar().showMessage("External editing is not available.")
            return
        if listing.parsed is not None and listing.parsed.job is not None:
            gate = ExternalEditGateDialog.structured(str(path), self)
        else:
            gate = ExternalEditGateDialog.raw(str(path), usable_external_label(listing), self)
        gate.exec()
        if not gate.is_accepted:
            return
        try:
            session = services.open_external_edit_session(path)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            return
        if session.job is None:
            self._open_raw_editor(session)
            return
        self._editor.open_external(path, session.job)
        if not self._editor.exec():
            return
        edited = self._editor.edited_job
        if edited is None:
            return
        dirty = self._editor.dirty_fields
        if not dirty:
            self.statusBar().showMessage(EDIT_EXTERNAL_NO_CHANGES)
            return
        confirm = ExternalReplaceGateDialog(
            mode="structured",
            path=str(path),
            loaded=session.loaded,
            parent=self,
        )
        confirm.exec()
        if not confirm.is_accepted:
            return
        self._start_external(
            ExternalControlRequest(
                kind=ExternalControlKind.STRUCTURED_EDIT,
                path=path,
                session=session,
                job=edited,
                dirty=dirty,
            ),
            session.loaded,
            "Replacing external LaunchAgent...",
        )

    def _selected_listing(self) -> TaskListing | None:
        """The currently selected row, or None when nothing is selected."""
        return self._listing_at_table_row(self.table.currentIndex().row())

    def _source_row(self, table_row: int) -> int | None:
        """Map a table (proxy) row to its source row, or None when invalid."""
        if table_row < 0:
            return None
        source_index = self._proxy.mapToSource(self._proxy.index(table_row, 0))
        if not source_index.isValid():
            return None
        return source_index.row()

    def _listing_at_table_row(self, table_row: int) -> TaskListing | None:
        """The source listing behind a table (proxy) row, or None when absent."""
        row = self._source_row(table_row)
        if row is None:
            return None
        return self._model.listing_at(row)

    def _update_empty_state(self) -> None:
        """Sync the empty-state banner and table visibility with the filters."""
        self._empty_state.set_counts(self._model.rowCount(), self._proxy.rowCount())
        self.table.setVisible(self._proxy.rowCount() > 0)

    def _label_of(self, listing: TaskListing) -> str | None:
        """Stable task identity: the job label, catalog or deployed parse."""
        if listing.job is not None:
            return listing.job.label
        parsed = listing.parsed
        if parsed is not None and parsed.job is not None:
            return parsed.job.label
        return None

    def _row_for_identity(self, previous: TaskListing | None) -> int:
        """First row matching the previous selection's identity, else row 0."""
        if previous is None:
            return 0
        label = self._label_of(previous)
        for table_row in range(self._proxy.rowCount()):
            listing = self._listing_at_table_row(table_row)
            if listing is None:
                continue
            if label is not None and self._label_of(listing) == label:
                return table_row
            if (
                label is None
                and previous.path is not None
                and listing.path is not None
                and listing.path == previous.path
            ):
                return table_row
        return 0

    def _update_lifecycle_actions(self) -> None:
        """Enable only the actions the selection allows, unless one is in flight."""
        listing = self._selected_listing()
        busy = self._lifecycle_busy or self._external_busy
        allowed = frozenset() if busy else self._lifecycle_controller.enabled_actions(listing)
        self.install_action.setEnabled(LifecycleAction.INSTALL in allowed)
        self.reinstall_action.setEnabled(LifecycleAction.REINSTALL in allowed)
        self.uninstall_action.setEnabled(LifecycleAction.UNINSTALL in allowed)
        self.enable_action.setEnabled(LifecycleAction.ENABLE in allowed)
        self.disable_action.setEnabled(LifecycleAction.DISABLE in allowed)
        self.run_now_action.setEnabled(LifecycleAction.RUN_NOW in allowed)
        self.new_task_action.setEnabled(not busy)
        self.test_action.setEnabled(
            listing is not None
            and listing.managed
            and listing.job is not None
            and not self._diagnostics_busy
        )
        self._update_import_action(listing)
        self._update_action_menu(listing)
        self._update_edit_menu(listing)
        self._update_lifecycle_tooltips(listing)

    def _update_edit_menu(self, listing: TaskListing | None) -> None:
        """Enable Edit menu actions based on the selection."""
        busy = self._lifecycle_busy or self._external_busy
        self.edit_task_action.setEnabled(listing is not None and not busy)
        self.remove_task_action.setEnabled(
            listing is not None
            and self._lifecycle_controller.enabled_remove_action(listing)
            and not busy
        )

    def _update_lifecycle_tooltips(self, listing: TaskListing | None) -> None:
        """Explain why an external action is unavailable for the selection."""
        if listing is None or listing.managed:
            self.enable_action.setToolTip("")
            self.run_now_action.setToolTip("")
            return
        label = usable_external_label(listing)
        self.enable_action.setToolTip("" if label is not None else EXTERNAL_ENABLE_NO_LABEL_TOOLTIP)
        if label is None:
            self.run_now_action.setToolTip(EXTERNAL_RUN_NOW_NO_LABEL_TOOLTIP)
        elif listing.loaded is not True:
            self.run_now_action.setToolTip(EXTERNAL_RUN_NOW_NOT_LOADED_TOOLTIP)
        else:
            self.run_now_action.setToolTip("")

    def _update_action_menu(self, listing: TaskListing | None) -> None:
        """Enable reveal/copy/export actions based on the selection."""
        has_service = self._services is not None
        job = listing.job if listing is not None else None
        self.export_json_action.setEnabled(has_service and job is not None)
        command = shell_safe_command(listing) if listing is not None else ""
        self.copy_command_action.setEnabled(bool(command))
        self.copy_plist_action.setEnabled(has_service and job is not None)
        if listing is None or not has_service:
            self.reveal_plist_action.setEnabled(False)
            self.reveal_stdout_action.setEnabled(False)
            self.reveal_stderr_action.setEnabled(False)
            return
        self.reveal_plist_action.setEnabled(self._plist_path(listing) is not None)
        logs = job.logging if job is not None else None
        self.reveal_stdout_action.setEnabled(
            bool(logs and logs.stdout_path and logs.stdout_path.exists())
        )
        self.reveal_stderr_action.setEnabled(
            bool(logs and logs.stderr_path and logs.stderr_path.exists())
        )

    def _on_selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        """Inspect the selected agent, or show a placeholder when the selection is empty."""
        rows = sorted({index.row() for index in selected.indexes()})
        if not rows:
            self.inspector.show_placeholder("Select a task to inspect its details.")
            self.history_panel.show_history(HistoryOutcome(label="", events=()))
            self._populate_badges(None)
            self._update_lifecycle_actions()
            return
        listing = self._listing_at_table_row(rows[0])
        if listing is None:
            self._populate_badges(None)
            self._update_lifecycle_actions()
            return
        if listing.kind is ListingKind.SAVED:
            self.inspector.show_saved(listing)
            if listing.job is not None:
                self.history_panel.show_history(
                    self._history_controller.history_for(listing.job.label)
                )
            self._populate_badges(listing)
            self._update_lifecycle_actions()
            return
        result = self._controller.inspect(listing)
        if result.error is not None:
            self.inspector.show_error(result.error)
            self._populate_badges(None)
            self._update_lifecycle_actions()
            return
        assert result.report is not None
        self.inspector.show_agent(listing, result.report, diagnostics=result.diagnostics)
        self._populate_badges(listing)
        self._update_lifecycle_actions()
        if listing.managed and listing.job is not None:
            self.history_panel.show_history(self._history_controller.history_for(listing.job.label))
        else:
            self.history_panel.show_history(
                HistoryOutcome(label="", events=(), error=HISTORY_NOT_APPLICABLE)
            )

    # -- lifecycle -----------------------------------------------------------

    def _update_import_action(self, listing: TaskListing | None) -> None:
        """Enable the import action only for an eligible external representable row."""
        eligible = (
            listing is not None
            and listing.kind is ListingKind.DISCOVERED
            and listing.managed is False
            and listing.parsed is not None
            and listing.parsed.job is not None
        )
        self.import_action.setEnabled(eligible)

    def _on_import_triggered(self) -> None:
        """Preview and optionally commit an external-plist import."""
        if self._import_controller is None:
            self.statusBar().showMessage("Import is not available.")
            return
        listing = self._selected_listing()
        if listing is None or listing.path is None:
            self.statusBar().showMessage("Select a task to import.")
            return
        outcome = self._import_controller.preview(listing.path)
        if outcome.error is not None:
            self.statusBar().showMessage(f"Cannot import: {outcome.error}")
            return
        dialog = ImportPreviewDialog(outcome, self)
        if not dialog.exec():
            return
        result = self._import_controller.commit(
            outcome, acknowledge_partial=dialog._acknowledge_check.isChecked()
        )
        if result.error is not None:
            self.statusBar().showMessage(f"Import failed: {result.error}")
            return
        self.refresh()

    # -- universal external controls -------------------------------------------

    def _start_external(
        self,
        request: ExternalControlRequest,
        loaded: bool | None,
        message: str,
    ) -> None:
        """Dispatch an external-control worker under the single busy slot."""
        services = self._services
        if services is None:
            self.statusBar().showMessage("External controls are not available.")
            return
        if self._external_busy or self._lifecycle_busy:
            self.statusBar().showMessage("Another operation is in progress.")
            return
        self._external_busy = True
        self._external_kind = request.kind
        self._external_loaded = loaded
        self._update_lifecycle_actions()
        self.statusBar().showMessage(message)
        worker = ExternalControlWorker(services, request)
        self._active_external_worker = worker
        self._start_external_worker(worker)

    def _start_external_worker(self, worker: ExternalControlWorker) -> None:
        """Run the external-control worker on a QThread and invoke it through the queue."""
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_external_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)

    def _on_external_finished(self, outcome: object) -> None:
        """Restore the UI, present the pinned result message, and refresh."""
        kind = self._external_kind
        loaded = self._external_loaded
        self._external_busy = False
        self._active_external_worker = None
        self._external_kind = None
        self._external_loaded = None
        if not isinstance(outcome, ExternalEditResult):
            self.refresh()
            if isinstance(outcome, Exception):
                self.statusBar().showMessage(str(outcome))
            self._update_lifecycle_actions()
            return
        self.refresh()
        if outcome.removed or outcome.quarantined_path is not None:
            self.table.clearSelection()
        if kind is not None:
            self._show_external_result(kind, outcome, loaded)
        self._update_lifecycle_actions()

    def _show_external_result(
        self,
        kind: ExternalControlKind,
        outcome: ExternalEditResult,
        loaded: bool | None,
    ) -> None:
        """Show the pinned status-bar message for a finished external operation."""
        if kind in (ExternalControlKind.STRUCTURED_EDIT, ExternalControlKind.RAW_EDIT):
            if outcome.replaced:
                if loaded is True and not outcome.reloaded:
                    backup = self._backup_artifact(outcome)
                    self.statusBar().showMessage(EXTERNAL_EDIT_RELOAD_FAILED.format(backup=backup))
                elif loaded is True:
                    self.statusBar().showMessage(EXTERNAL_EDIT_SUCCESS_LOADED)
                else:
                    self.statusBar().showMessage(EXTERNAL_EDIT_SUCCESS_UNLOADED)
            else:
                staged = next(iter(outcome.retained_artifacts), "")
                self.statusBar().showMessage(EXTERNAL_EDIT_BOOTOUT_FAILED.format(staged=staged))
        elif kind is ExternalControlKind.DISABLE:
            if outcome.quarantined_path is not None:
                self.statusBar().showMessage(
                    EXTERNAL_QUARANTINE_RESULT.format(
                        source=outcome.source_path,
                        dest=outcome.quarantined_path,
                    )
                )
            else:
                label = outcome.label or ""
                if loaded is True:
                    self.statusBar().showMessage(EXTERNAL_DISABLE_LOADED.format(label=label))
                elif loaded is False:
                    self.statusBar().showMessage(EXTERNAL_DISABLE_UNLOADED.format(label=label))
                else:
                    self.statusBar().showMessage(EXTERNAL_DISABLE_UNKNOWN.format(label=label))
        elif kind is ExternalControlKind.ENABLE:
            label = outcome.label or ""
            if loaded is True:
                self.statusBar().showMessage(EXTERNAL_ENABLE_LOADED.format(label=label))
            elif loaded is False:
                self.statusBar().showMessage(EXTERNAL_ENABLE_UNLOADED.format(label=label))
            else:
                self.statusBar().showMessage(EXTERNAL_ENABLE_UNKNOWN.format(label=label))
        elif kind is ExternalControlKind.REMOVE:
            message = EXTERNAL_REMOVE_RESULT.format(
                path=outcome.source_path,
                backup=self._backup_artifact(outcome),
            )
            if loaded is True:
                message += EXTERNAL_REMOVE_UNLOADED_FIRST
            self.statusBar().showMessage(message)

    def _backup_artifact(self, outcome: ExternalEditResult) -> str:
        """The retained .backup. sibling for *outcome*, or an empty string."""
        return next(
            (
                str(artifact)
                for artifact in outcome.retained_artifacts
                if ".backup." in artifact.name
            ),
            "",
        )

    # -- external lifecycle and removal controls --------------------------------

    def _run_external_lifecycle(self, action: LifecycleAction, listing: TaskListing) -> None:
        """Dispatch disable / enable / run-now for an external row."""
        path = listing.path
        if path is None:
            self.statusBar().showMessage("Select a task first.")
            return
        loaded = listing.loaded
        if action is LifecycleAction.DISABLE:
            dialog = ExternalDisableConfirmDialog(
                label=usable_external_label(listing),
                path=str(path),
                loaded=loaded,
                parent=self,
            )
            dialog.exec()
            if not dialog.is_accepted:
                return
            kind = ExternalControlKind.DISABLE
            message = "Disabling external LaunchAgent..."
        elif action is LifecycleAction.ENABLE:
            kind = ExternalControlKind.ENABLE
            message = "Enabling external LaunchAgent..."
        else:
            kind = ExternalControlKind.RUN_NOW
            message = "Running external LaunchAgent now..."
        self._start_external(
            ExternalControlRequest(kind=kind, path=path),
            loaded,
            message,
        )

    def _on_remove_task_triggered(self) -> None:
        """Remove the selected task: uninstall, catalog delete, or external removal."""
        listing = self._selected_listing()
        if listing is None:
            self.statusBar().showMessage("Select a task first.")
            return
        if listing.managed:
            if listing.kind is ListingKind.SAVED:
                self._remove_saved_listing(listing)
            else:
                self._on_lifecycle_triggered(LifecycleAction.UNINSTALL)
            return
        self._remove_external_listing(listing)

    def _remove_saved_listing(self, listing: TaskListing) -> None:
        """Remove a saved (not installed) managed job from the catalog."""
        job = listing.job
        if job is None:
            self.statusBar().showMessage("Select a task first.")
            return
        dialog = RemoveSavedJobConfirmDialog(name=job.name, label=job.label, parent=self)
        dialog.exec()
        if not dialog.is_accepted:
            return
        result = self._lifecycle_controller.request_remove_saved(job.label)
        if result is not None:
            self.refresh()
            self.table.clearSelection()
            self.statusBar().showMessage(REMOVED_SAVED_RESULT.format(name=job.name))
        else:
            self.statusBar().showMessage("Failed to remove saved task.")

    def _remove_external_listing(self, listing: TaskListing) -> None:
        """Remove an external plist after confirmation (unloading first when loaded)."""
        path = listing.path
        if path is None:
            self.statusBar().showMessage("Select a task first.")
            return
        loaded = listing.loaded
        dialog = ExternalRemoveConfirmDialog(path=str(path), loaded=loaded, parent=self)
        dialog.exec()
        if not dialog.is_accepted:
            return
        self._start_external(
            ExternalControlRequest(kind=ExternalControlKind.REMOVE, path=path),
            loaded,
            "Removing external LaunchAgent...",
        )

    def _open_raw_editor(self, session: ExternalEditSession) -> None:
        """Open the raw plist editor for an external LaunchAgent plist."""
        try:
            data = session.source_path.read_bytes()
        except OSError:
            self.statusBar().showMessage("Cannot read external plist file.")
            return
        try:
            text = data.decode("utf-8")
            binary_mode = False
        except UnicodeDecodeError:
            text = base64.b64encode(data).decode("ascii")
            binary_mode = True
        editor = RawPlistEditor(self)
        editor.open(
            source_path=session.source_path,
            text=text,
            binary_mode=binary_mode,
            label=session.label,
        )
        editor.exec()
        replacement = editor.replacement_text()
        if replacement is None:
            return
        if binary_mode:
            replacement = self._canonicalize_raw_replacement(replacement)
            if replacement is None:
                return
        gate = ExternalReplaceGateDialog(
            mode="raw",
            path=str(session.source_path),
            loaded=session.loaded,
            parent=self,
        )
        gate.exec()
        if not gate.is_accepted:
            return
        self._start_external(
            ExternalControlRequest(
                kind=ExternalControlKind.RAW_EDIT,
                path=session.source_path,
                session=session,
                raw_text=replacement,
            ),
            session.loaded,
            "Replacing external LaunchAgent...",
        )

    def _canonicalize_raw_replacement(self, text: str) -> str | None:
        """Decode a base64 replacement to canonical XML, or report the pinned error."""
        try:
            decoded = base64.b64decode(text.encode("ascii"), validate=True)
            value = plistlib.loads(decoded)
            if not isinstance(value, dict):
                raise ValueError("not a plist dict")
            return plistlib.dumps(value, fmt=plistlib.FMT_XML).decode("utf-8")
        except Exception:
            self.statusBar().showMessage(RAW_REPLACEMENT_INVALID)
            return None

    # -- transfer and file actions -------------------------------------------

    def _plist_path(self, listing: TaskListing) -> Path | None:
        """The plist path for *listing*: the discovered path, else the managed one."""
        if listing.path is not None:
            return listing.path
        if listing.job is not None and self._services is not None:
            return self._services.plist_path_for(listing.job.label)
        return None

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied to clipboard.")

    def _on_reveal_plist(self) -> None:
        listing = self._selected_listing()
        if listing is None or self._services is None:
            return
        path = self._plist_path(listing)
        if path is None:
            self.statusBar().showMessage("No plist path available.")
            return
        error = self._services.reveal_path(path)
        if error is not None:
            self.statusBar().showMessage(error)

    def _on_reveal_log(self, stream: str) -> None:
        listing = self._selected_listing()
        if listing is None or self._services is None or listing.job is None:
            return
        path = (
            listing.job.logging.stdout_path
            if stream == "stdout"
            else listing.job.logging.stderr_path
        )
        if path is None:
            self.statusBar().showMessage("No log path configured.")
            return
        error = self._services.reveal_path(path)
        if error is not None:
            self.statusBar().showMessage(error)

    def _on_copy_command(self) -> None:
        listing = self._selected_listing()
        if listing is None:
            return
        text = shell_safe_command(listing)
        if not text:
            self.statusBar().showMessage("No command available to copy.")
            return
        self._copy_text(text)

    def _on_copy_plist(self) -> None:
        listing = self._selected_listing()
        if listing is None or listing.job is None or self._services is None:
            self.statusBar().showMessage("Select a managed task.")
            return
        self._copy_text(self._services.generate_plist_for(listing.job))

    def _on_export_json(self) -> None:
        listing = self._selected_listing()
        if listing is None or listing.job is None or self._services is None:
            self.statusBar().showMessage("Select a task to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Managed JSON", listing.job.label + ".json"
        )
        if not path:
            return
        try:
            self._services.export_managed_json(listing.job.label, Path(path))
        except FileExistsError as exc:
            self.statusBar().showMessage(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(f"Exported to {path}")

    def _on_import_json(self) -> None:
        if self._json_transfer is None:
            self.statusBar().showMessage("JSON import is not available.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import Managed JSON")
        if not path:
            return
        outcome = self._json_transfer.preview_import(Path(path))
        if outcome.error is not None:
            self.statusBar().showMessage(f"Cannot import: {outcome.error}")
            return
        dialog = JsonTransferDialog(outcome, self)
        if not dialog.exec():
            return
        result = self._json_transfer.commit(outcome)
        if result.error is not None:
            self.statusBar().showMessage(f"Import failed: {result.error}")
            return
        self.refresh()

    def _populate_badges(self, listing: TaskListing | None) -> None:
        """Render the five status badges for *listing* in the right-pane strip."""
        if listing is None:
            self._badge_strip.hide()
            return
        self._badge_strip.show()
        badge_set = agent_badges(listing)
        descriptors = (
            badge_set.state,
            badge_set.installed,
            badge_set.enabled,
            badge_set.loaded,
            badge_set.command,
        )
        for badge, descriptor in zip(self._badges, descriptors, strict=True):
            badge.set_descriptor(descriptor)

    def _on_lifecycle_triggered(self, action: LifecycleAction) -> None:
        """Route to the external controls or the managed lifecycle worker."""
        listing = self._selected_listing()
        if listing is None:
            self.statusBar().showMessage("Select a task first.")
            return
        if not listing.managed:
            self._run_external_lifecycle(action, listing)
            return
        if listing.job is None:
            self.statusBar().showMessage("Select a task first.")
            return
        needs_confirm = action in (LifecycleAction.REINSTALL, LifecycleAction.UNINSTALL)
        if needs_confirm and not self._confirm_lifecycle(action, listing):
            return
        verdict = self._lifecycle_controller.request(action, listing)
        if verdict is not RequestVerdict.ACCEPTED:
            self.statusBar().showMessage(f"Cannot run {action.value}: {verdict.value}.")
            return
        self._lifecycle_busy = True
        self._update_lifecycle_actions()
        self.statusBar().showMessage(f"Running {action.value}...")
        worker = LifecycleWorker(self._lifecycle_controller)
        self._active_worker = worker
        self._start_worker(worker)

    def _confirm_lifecycle(self, action: LifecycleAction, listing: TaskListing) -> bool:
        """Ask for confirmation naming the task, exact label, and user-only scope."""
        job = listing.job
        if job is None:
            return False
        answer = QMessageBox.question(
            self,
            f"Confirm {action.value.title()}",
            (
                f"{action.value.title()} the task '{job.name}' "
                f"(label: {job.label})?\n\n"
                "This affects the current user's LaunchAgents only."
            ),
        )
        return answer == QMessageBox.StandardButton.Yes

    def _start_worker(self, worker: LifecycleWorker) -> None:
        """Run the worker on a QThread and invoke it through the queue."""
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_lifecycle_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)

    def _on_lifecycle_finished(self, outcome: object) -> None:
        """Restore the UI, refresh on success, and show the result dialog."""
        if not isinstance(outcome, LifecycleOutcome):
            return
        self._lifecycle_busy = False
        self._active_worker = None
        self._update_lifecycle_actions()
        if outcome.is_success:
            self.refresh()
            if outcome.action is LifecycleAction.RUN_NOW:
                listing = self._selected_listing()
                if listing is not None and listing.job is not None:
                    self.history_panel.show_history(
                        self._history_controller.history_for(listing.job.label)
                    )
        dialog = LifecycleResultDialog(outcome, self)
        dialog.exec()

    # -- diagnostics ---------------------------------------------------------

    def _on_test_triggered(self) -> None:
        """Request a direct test of the selected job and dispatch a worker."""
        listing = self._selected_listing()
        if listing is None:
            self.statusBar().showMessage("Select a task first.")
            return
        if not listing.managed or listing.job is None:
            self.statusBar().showMessage(
                "This task is not a managed task; there is nothing to test."
            )
            return
        verdict = self._diagnostics_controller.request_test(listing.job)
        if verdict is not TestVerdict.ACCEPTED:
            self.statusBar().showMessage(f"Cannot test: {verdict.value}.")
            return
        self._diagnostics_busy = True
        self._update_lifecycle_actions()
        self.statusBar().showMessage("Testing task...")
        worker = DiagnosticsWorker(self._diagnostics_controller)
        self._active_test_worker = worker
        self._start_test_worker(worker)

    def _start_test_worker(self, worker: DiagnosticsWorker) -> None:
        """Run the test worker on a QThread and invoke it through the queue."""
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self._on_test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)

    def _on_test_finished(self, outcome: object) -> None:
        """Render the test result only when the selection still matches it."""
        if not isinstance(outcome, TestOutcome):
            return
        self._diagnostics_busy = False
        self._active_test_worker = None
        self._update_lifecycle_actions()
        self.statusBar().clearMessage()
        listing = self._selected_listing()
        if listing is None or listing.job is None or self._label_of(listing) != outcome.label:
            return
        self.panel.show_test_outcome(listing.job, outcome)
        self._render_diagnostics(listing.job)
        self.history_panel.show_history(self._history_controller.history_for(outcome.label))

    def _on_history_refresh(self) -> None:
        """Re-query execution history for the selected task."""
        listing = self._selected_listing()
        if listing is None or listing.job is None:
            self.statusBar().showMessage("Select a task to refresh its history.")
            return
        self.history_panel.show_history(self._history_controller.history_for(listing.job.label))

    def _on_diagnostics_refresh(self) -> None:
        """Re-read the selected job's persisted logs and environment diff."""
        listing = self._selected_listing()
        if listing is None or listing.job is None:
            self.statusBar().showMessage("Select a task to refresh its logs.")
            return
        self._render_diagnostics(listing.job)

    def _render_diagnostics(self, job: JobDefinition) -> None:
        """Fill the panel with a job's persisted logs and environment diff."""
        self.panel.show_logs_outcome(self._diagnostics_controller.read_logs(job))
        self.panel.show_environment_outcome(self._diagnostics_controller.compare_environment(job))
