"""Main window presenting the discovered-agent browser with an inspector."""

from __future__ import annotations

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
from task_scheduler.gui.widgets.history_panel import HistoryPanel
from task_scheduler.gui.widgets.import_preview_dialog import ImportPreviewDialog
from task_scheduler.gui.widgets.job_editor import JobEditor
from task_scheduler.gui.widgets.json_transfer_dialog import JsonTransferDialog
from task_scheduler.gui.widgets.lifecycle_result import LifecycleResultDialog

__all__ = ["MainWindow"]


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
        self.edit_task_action = QAction("Edit Managed Task...", self)
        self.edit_task_action.triggered.connect(self.edit_managed_task)
        self.import_action = QAction("Import as Managed Job...", self)
        self.import_action.setEnabled(False)
        self.import_action.triggered.connect(self._on_import_triggered)
        self.export_json_action = QAction("Export JSON...", self)
        self.export_json_action.setEnabled(False)
        self.export_json_action.triggered.connect(self._on_export_json)
        self.import_json_action = QAction("Import JSON...", self)
        self.import_json_action.triggered.connect(self._on_import_json)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_task_action)
        file_menu.addAction(self.edit_task_action)
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.export_json_action)
        file_menu.addAction(self.import_json_action)
        file_menu.addAction(self.refresh_action)
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

    def edit_managed_task(self) -> None:
        """Open the editor for the selected managed task and refresh on save."""
        listing = self._listing_at_table_row(self.table.currentIndex().row())
        if listing is None or not listing.managed or listing.job is None:
            self.statusBar().showMessage("Select a managed task to edit it.")
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
        allowed = (
            frozenset()
            if self._lifecycle_busy
            else self._lifecycle_controller.enabled_actions(listing)
        )
        self.install_action.setEnabled(LifecycleAction.INSTALL in allowed)
        self.reinstall_action.setEnabled(LifecycleAction.REINSTALL in allowed)
        self.uninstall_action.setEnabled(LifecycleAction.UNINSTALL in allowed)
        self.enable_action.setEnabled(LifecycleAction.ENABLE in allowed)
        self.disable_action.setEnabled(LifecycleAction.DISABLE in allowed)
        self.run_now_action.setEnabled(LifecycleAction.RUN_NOW in allowed)
        self.new_task_action.setEnabled(not self._lifecycle_busy)
        self.edit_task_action.setEnabled(not self._lifecycle_busy)
        self.test_action.setEnabled(
            listing is not None
            and listing.managed
            and listing.job is not None
            and not self._diagnostics_busy
        )
        self._update_import_action(listing)
        self._update_action_menu(listing)

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
        """Confirm when required, request through the controller, dispatch a worker."""
        listing = self._selected_listing()
        if listing is None or listing.job is None:
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
