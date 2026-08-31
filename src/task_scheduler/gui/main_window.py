"""Main window presenting the discovered-agent browser with an inspector."""

from __future__ import annotations

from PySide6.QtCore import QItemSelection, QMetaObject, Qt, QThread
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from task_scheduler.application.job_service import JobNotFoundError
from task_scheduler.application.task_command_service import ListingKind, TaskListing
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
from task_scheduler.gui.controllers.lifecycle_controller import (
    LifecycleAction,
    LifecycleController,
    LifecycleOutcome,
    RequestVerdict,
)
from task_scheduler.gui.controllers.lifecycle_worker import LifecycleWorker
from task_scheduler.gui.models.agent_table_model import AgentTableModel
from task_scheduler.gui.widgets.agent_inspector import AgentInspector
from task_scheduler.gui.widgets.diagnostic_logs_panel import DiagnosticLogsPanel
from task_scheduler.gui.widgets.job_editor import JobEditor
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
        self._editor = JobEditor(editor, diagnostics=diagnostics)
        self._model = AgentTableModel()
        self.table = QTreeView()
        self.table.setModel(self._model)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.header().setStretchLastSection(True)
        self.inspector = AgentInspector()
        self.panel = DiagnosticLogsPanel()
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.inspector)
        right_layout.addWidget(self.panel)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(right_pane)
        splitter.setSizes([600, 400])
        self.setCentralWidget(splitter)
        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_action.triggered.connect(self.refresh)
        self.new_task_action = QAction("New Task...", self)
        self.new_task_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_task_action.triggered.connect(self.new_task)
        self.edit_task_action = QAction("Edit Managed Task...", self)
        self.edit_task_action.triggered.connect(self.edit_managed_task)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_task_action)
        file_menu.addAction(self.edit_task_action)
        file_menu.addAction(self.refresh_action)
        self.test_action = QAction("Test Task", self)
        self.test_action.setEnabled(False)
        self.test_action.triggered.connect(self._on_test_triggered)
        diagnostics_menu = self.menuBar().addMenu("Diagnostics")
        diagnostics_menu.addAction(self.test_action)
        self.panel.refresh_button.clicked.connect(self._on_diagnostics_refresh)
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
                lambda _checked=False, lifecycle_action=lifecycle_action:
                    self._on_lifecycle_triggered(lifecycle_action)
            )
            lifecycle_menu.addAction(action)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.refresh()

    def refresh(self) -> None:
        """Reload the agent listings, preserving the selected agent when possible."""
        outcome = self._controller.refresh()
        if outcome.error is not None:
            self._model.set_agents([])
            self.inspector.show_error(outcome.error)
            self.statusBar().showMessage(outcome.error)
            self._update_lifecycle_actions()
            return
        if not outcome.agents:
            self._model.set_agents([])
            self.inspector.show_placeholder("No tasks found.")
            self.statusBar().clearMessage()
            self._update_lifecycle_actions()
            return
        previous = self._selected_listing()
        self._model.set_agents(outcome.agents)
        row = self._row_for_identity(previous)
        self.table.setCurrentIndex(self.table.model().index(row, 0))
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
        row = self.table.currentIndex().row()
        listing = self._model.listing_at(row) if row >= 0 else None
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
        row = self.table.currentIndex().row()
        return self._model.listing_at(row) if row >= 0 else None

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
        for row in range(self._model.rowCount()):
            listing = self._model.listing_at(row)
            if listing is None:
                continue
            if label is not None and self._label_of(listing) == label:
                return row
            if (
                label is None
                and previous.path is not None
                and listing.path is not None
                and listing.path == previous.path
            ):
                return row
        return 0

    def _update_lifecycle_actions(self) -> None:
        """Enable only the actions the selection allows, unless one is in flight."""
        listing = self._selected_listing()
        allowed = (
            frozenset() if self._lifecycle_busy
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

    def _on_selection_changed(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        """Inspect the selected agent, or show a placeholder when the selection is empty."""
        rows = sorted({index.row() for index in selected.indexes()})
        if not rows:
            self.inspector.show_placeholder("Select a task to inspect its details.")
            self._update_lifecycle_actions()
            return
        listing = self._model.listing_at(rows[0])
        if listing is None:
            self._update_lifecycle_actions()
            return
        if listing.kind is ListingKind.SAVED:
            self.inspector.show_saved(listing)
            self._update_lifecycle_actions()
            return
        result = self._controller.inspect(listing)
        if result.error is not None:
            self.inspector.show_error(result.error)
            self._update_lifecycle_actions()
            return
        assert result.report is not None
        self.inspector.show_agent(listing, result.report)
        self._update_lifecycle_actions()

    # -- lifecycle -----------------------------------------------------------

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
        if (
            listing is None
            or listing.job is None
            or self._label_of(listing) != outcome.label
        ):
            return
        self.panel.show_test_outcome(listing.job, outcome)
        self._render_diagnostics(listing.job)

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
        self.panel.show_environment_outcome(
            self._diagnostics_controller.compare_environment(job)
        )
