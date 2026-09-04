# PLAN.md

## Current State
Crawl Increments 0–12 complete and pushed to `sched_dev_opencode` (version 0.0.12):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model + schema-versioned JSON persistence
- **Increment 2:** plist encoder (`PlistCodec`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`) + fixtures + round-trip tests
- **Increment 4:** Python detection (`detect_python`, `compare_environments`) + tests
- **Increment 5:** Direct test runner (`SubprocessRunner`, `DirectTestService`, `evaluate_diagnostics`) + tests
- **Increment 6:** LaunchAgent storage (`LaunchAgentStore` write/remove/discover + `LaunchAgentFilesystem`) + tests
- **Increment 7:** launchctl adapter (`LaunchAgentBackend` install/uninstall/status/enable/disable/trigger) + protected integration tests
- **Increment 8:** Typer CLI (`mactask`) with 12 commands + exit codes; `TaskCommandService` façade; `JobService` managed catalog
- **Increment 9:** PySide6 GUI read/discovery (`mactask-gui`): shared `bootstrap.build_services()` composition root, `inspect_discovered` + `DiscoveredInspectReport`, pure presenters/controller, `AgentTableModel`, `AgentInspector`, two-pane `MainWindow`; read-only external-job policy; 413 tests
- **Increment 10:** GUI job creation/edit/save/validate: `JobService.new_managed_job` managed label policy + catalog-only `save`, `TaskCommandService` in-memory editor façade (`validate_job`/`generate_plist_for`/`save_managed_job`/`detect_python`/`resolve_managed_job`), Qt-free `EditorController` + `JobDraft`, `RowTable`, `JobEditor` dialog, New Task / Edit Managed Task actions; 544 tests
- **Increment 11:** GUI installation/lifecycle: unified `TaskListing` (discovered plists + catalog-only saved rows shown as `Saved, not installed`), managed-only service guards, staged reinstall transaction (stage → bootout → backup → activate → bootstrap with retained artifacts, no rollback claim), Qt-free `LifecycleController` + `QThread` `LifecycleWorker` marshaling immutable `LifecycleOutcome`, Lifecycle menu (install/reinstall/uninstall/enable/disable/run now) with gating, confirmations, and result dialog; 676 tests
- Verification at v0.0.11: 676 tests, 100% coverage, ruff + mypy strict clean
- **Increment 12:** GUI diagnostics/logs: job-based façade contracts (`test_job(job, *, detection=None)`, `test(label)` delegating, `compare_environment(job, terminal_environment)`, `read_logs_for(job)` with `read_logs(label)` delegating, `gui_environment()` in the composition layer), Qt-free `DiagnosticsController` + `QThread` `DiagnosticsWorker`, shared `DiagnosticLogsPanel` (test summary, diagnostics, direct/persisted stdout/stderr with Refresh, name-only environment comparison, Python recommendations), main-window Test action with selection/stale-result guard, `DirectTestDialog` for the editor's Test Draft (persists nothing); 766 tests
- Verification at v0.0.12: 766 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Walk Increment 14 — Schedule Model and Migration** (approved plan below; Walk plan approved 2026-09-04).

---

## Blockers
None

---

## Strategy
Incrementally build the PySide6 GUI (Increments 9–12), then package as a local `.app` (Increment 13). The GUI and CLI share the same application services. The GUI must never call `launchctl`, `subprocess`, plist-writing APIs, or live filesystem APIs directly.

```text
PySide6 GUI -> application services (TaskCommandService) -> domain -> macOS platform adapters -> launchd
```

### Pinned Decisions
1. **Save is non-deploying.** Saving an edited managed task updates only its managed JSON catalog entry. A separate explicit **Reinstall** action applies the saved definition to launchd.
2. **Environment comparison** uses the environment inherited by the GUI process. The UI discloses that this may differ from a user's Terminal environment.
3. **Packaging target:** local native bundle for the current machine architecture only. No universal binaries, signing, notarization, DMG/PKG, or updater work in Crawl.
4. **Classification vocabulary (GUI only):**
   - **Managed** — catalog-managed parsed job.
   - **External** — valid supported/partially supported plist outside catalog.
   - **Invalid** — malformed or unsupported plist.
   - No "Imported," "System," or "Vendor" classifications during Crawl.
5. **Label safety:** lifecycle actions (install, uninstall, enable, disable, run now, reinstall) are enabled only for managed tasks. External/invalid jobs are read-only.
6. **Reinstall transaction** replaces the deployed plist safely: stage → boot out (if needed) → write new plist → bootstrap → retain artifacts on failure.
7. **`<job>` identity** remains the exact managed launchd label resolved from the catalog. External job inspection uses the plist path/discovered key instead.

---

## Shared Foundation — Before Increment 9

These small prerequisite changes establish the GUI composition root and add necessary dependencies:

1. Add **PySide6** runtime dependency and **pytest-qt** development dependency.
2. Add **offscreen Qt test configuration** so widget tests run without a visible window.
3. Extract `build_services()` from `cli/app.py` into a neutral composition root:
   `task_scheduler/bootstrap/build_services()` (or `application/composition/build_services()`).
4. CLI `build_services()` imports the shared root. No behavioral change.
5. Add GUI entry point: `task_scheduler/gui/app.py:main`.
6. Keep CLI entry point unchanged externally.

### GUI Package Structure
```
src/task_scheduler/gui/
  app.py                    # QApplication startup and composition only
  main_window.py             # window layout and high-level signal wiring
  controllers/              # service orchestration and view-state transitions
  models/                   # QAbstractItemModel + transient UI-state models
  presenters/               # pure DTO-to-display formatting
  widgets/                  # focused reusable views/forms
  dialogs/                  # validation, preview, operation-result dialogs
```

No GUI module becomes a second application layer. Controllers invoke `TaskCommandService` or explicitly introduced application APIs; widgets render state and emit user intent.

---

## Crawl Increment 9 — GUI Read/Discovery

### Goal
Deliver a usable read-only PySide6 desktop application that discovers all user LaunchAgents, lists them clearly, and lets users inspect both managed and external plists without modifying anything.

### Requirements
- Create the PySide6 main window.
- Discover plists under `~/Library/LaunchAgents`.
- Show supported, partially supported, and invalid plists.
- Clearly identify managed jobs via the JSON catalog.
- Let users inspect command, schedule, enabled/status, warnings, unsupported keys, and raw plist data.
- External, unsupported, and invalid jobs remain read-only.
- Use plain-language labels in ordinary screens; native `launchd` terms in Advanced view.
- Do not add any edit, import, install, uninstall, enable, disable, or run actions.

### Application-Service Work

**New API — discovered agent inspection:**
```python
class DiscoveredInspectReport:
    path: Path
    parsed: ParsedLaunchAgent
    managed: bool
    status: LaunchAgentStatus | None

TaskCommandService.inspect_discovered(path: Path) -> DiscoveredInspectReport
```
- Re-discover only the configured LaunchAgent root.
- Reject paths outside that root.
- Never mutate filesystem or catalog state.
- Return parsed status, raw plist data, warnings, unsupported keys, and managed status.
- Request backend status only when a valid label is available.
- A malformed/unsupported plist must still produce an inspectable report (no GUI-breaking exceptions).

### GUI Design

**Main window:** two-pane layout.
- Left: table/list of discovered tasks.
- Right: selected-task inspector.
- Top-level Refresh action.
- Empty state when no user LaunchAgents exist.
- Non-modal error banner/dialog if discovery fails.

**List columns:**
- Name or label
- Command summary
- Human-readable schedule summary
- Managed/External/Invalid classification
- Parse-support state
- Launchd status (when available)

**Inspector sections:**
- **Overview:** name, label, classification, source plist path, enabled state, loaded status.
- **Command:** executable, script/interpreter where applicable, arguments, working directory.
- **Schedule:** plain-language text + native schedule fields in Advanced.
- **Environment:** configured values (if parsed).
- **Warnings:** unsupported keys and parser warnings (always visible for partial/invalid).
- **Advanced:** raw plist representation + generated/parsed metadata where valid.

Display mapping lives in pure presenters. Widgets must not format domain details inline.

### Testing

**Unit tests (application/domain):**
- `inspect_discovered()` root containment and read-only behavior.
- Supported, partially supported, invalid, managed, and external discovered agents.
- Missing root and malformed plist behavior.
- Status unavailable for invalid/no-label plists.
- Classification/presenter formatting with plain DTO fixtures.

**Widget tests (`pytest-qt`):**
- Main window loads with fake/injected services.
- Refresh renders discovered rows.
- Selecting each classification updates the inspector.
- External/invalid jobs have no edit/lifecycle controls.
- Warnings and raw plist details appear for partial/invalid jobs.
- Empty state and service-failure state render correctly.

All tests must use temporary roots and fakes. No default unit test may touch real user agents or invoke `/bin/launchctl`.

### Documentation at Increment 9 Close
- `README.md`: GUI availability, launch instructions, discovery scope, read-only external-job policy.
- `docs/architecture.md`: GUI package boundary and shared composition root.
- `docs/development.md`: PySide6/Qt test setup and headless test requirements.
- `PROJECT.md`: Increment 9 complete; Increment 10 next.
- `TODOS.md`: mark all Increment 9 tasks complete and record verification.
- `SUMMARY.md`: Increment 9 scope, service contract changes, test total, coverage result, lint/mypy outcome.

**Version: 0.0.8 → 0.0.9**

---

## Crawl Increment 10 — GUI Job Creation, Edit, Save, and Validation

### Goal
Allow users to create and edit application-managed job definitions in the GUI, validate them through the domain model, save them to the managed JSON catalog, and preview the generated plist without deploying it.

### Pinned Decisions (approved 2026-08-29)
1. **Managed label policy:** `io.github.macos-task-scheduler.user.<slug>-<8-hex>` — slug = the job name lowercased to ASCII with runs of non-alphanumerics collapsed to `-` and edge `-` trimmed (blank falls back to `task`); 8-hex = first 8 hex chars of the job UUID. Generated while the label is untouched; a manual edit is kept and must pass domain validation plus catalog uniqueness.
2. **Draft UUID:** created once when a draft is opened (New Task or Edit) and retained for the draft's lifetime so label/working-directory/log-path defaults stay stable across Validate → Save.
3. **Logging:** no toggle — the paths are the model. New drafts default both streams to `~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/`; clearing a path disables that stream, clearing both disables logging.
4. **Save-validity UX:** Save starts enabled and validates on click. After a validation failure Save is disabled until the draft changes. A known-invalid draft is never persisted.
5. **Edit scope:** only the selected **Managed** discovery row with a valid parsed label. The catalog job is resolved by label (`resolve_managed_job`); external/invalid rows and catalog-only (non-deployed) jobs are out of scope this increment.
6. **New Task defaults:** blank schedule (no preselected time or weekdays), no command paths, Python form preselected. The draft is invalid until the user supplies a valid command plus a time plus at least one weekday.
7. **Facade surface (all in-memory, GUI-safe):** `new_managed_job`, `validate_job` (re-validates via Pydantic, not an identity method), `generate_plist_for` (validate then encode; no temporary JSON), `save_managed_job` (catalog only — no plist, no launchctl, no log directories), `detect_python` (delegates to platform detection), `resolve_managed_job`.
8. **Execution:** micro-slice subagent tasks (one source or test group per slice), on-disk verification before each commit, `make check` + 100% package coverage per slice; docs and the 0.0.9 → 0.0.10 bump land in one closeout commit.

### Requirements
- Add **New Task**, **Edit Managed Task**, **Save**, and **Validate** actions.
- Support three command forms:
  - **Python:** interpreter, script, arguments.
  - **Shell:** explicit executable and arguments.
  - **Executable:** explicit executable and arguments.
- Support exactly one execution time and one-or-more weekdays.
- Detect Python interpreters near a selected script: `.venv/bin/python`, `venv/bin/python`, current interpreter, PATH `python3`.
- Recommend the selected script's parent as the default working directory, permitting override.
- Let users explicitly add/remove environment variables.
- Enable logging by default with a deterministic per-job log-path policy:
  ```
  ~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/stdout.log
  ~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/stderr.log
  ```
- Generate plist preview only from a validated `JobDefinition`.
- Persist only managed JSON definitions on Save.
- Permit editing only for managed jobs.
- Do not alter an installed LaunchAgent on Save.

### Application-Service Work

**1. New-job defaults (factory/policy):**
```python
new_managed_job(name: str, command: Command, schedule: Schedule) -> JobDefinition
```
- Generate UUID.
- Derive a valid managed label by a documented, deterministic policy.
- Set `enabled=True`.
- Apply default working directory when a script is selected.
- Apply default stdout/stderr log paths (as shown above).
- Creating directories is not part of Save. Directory creation belongs to install/deploy.

**2. Draft validation and plist preview:**
```python
TaskCommandService.validate_job(job: JobDefinition) -> JobDefinition
TaskCommandService.generate_plist_for(job: JobDefinition) -> str
TaskCommandService.detect_python(script: Path) -> PythonDetectionResult
```
- The GUI constructs a draft, validates through Pydantic, then sends the validated model to the façade.
- Do not build JSON files merely to validate GUI input.

**3. Managed catalog save/update:**
```python
JobService.save(job: JobDefinition) -> Path
TaskCommandService.save_managed_job(job: JobDefinition) -> Path
```
- A new job creates its `<uuid>.json` catalog entry.
- An existing managed job overwrites only its own catalog record, keyed by immutable `job.id`.
- Save rejects an existing label owned by another managed job.
- Save does not write a plist, invoke `launchctl`, or create log directories.
- Save does not permit treating a discovered external plist as an editable managed record.
- Label edits are allowed only if the new label is valid and unique in the catalog.

### GUI Design

**Editor sections:**
- **General:** name, label, command type.
- **Command:** type-specific fields + argument list editor.
- **Schedule:** time picker + weekday checkboxes.
- **Working Directory:** visible default/recommendation + manual override.
- **Environment:** key/value table with explicit add/remove controls.
- **Logging:** default paths shown, editable absolute paths, explanation that values are written to plist during installation.
- **Advanced:** generated plist preview and immutable job ID.

Use an argument table or one-argument-per-row editor. Do not parse free-text shell-like command lines.

**Validation UX:**
- Validate on explicit action and before Save.
- Display field-level validation errors + summary panel/dialog.
- Disable Save while the current draft is known invalid.
- Do not persist invalid drafts.
- Display a sleep/wake disclaimer beside the schedule.

**Python selection UX:**
- Script selection triggers detection.
- Show candidates in priority order, with source/recommendation.
- Selecting a candidate populates the interpreter field.
- Detection failure is informative, not blocking; user can enter an absolute interpreter path manually.

### Testing

**Unit tests (application/domain):**
- New-job UUID, label, working-directory, and log-default policies.
- Draft validation and plist preview from a validated in-memory job.
- New save, existing save, conflict, invalid label, and immutable-ID behavior.
- No deployment side effects from Save.
- Python detection delegation and default recommendation.

**Widget tests:**
- New-task defaults.
- Switching among Python, Shell, and Executable forms.
- Time and weekday validation.
- Interpreter-candidate rendering and manual selection.
- Working-directory recommendation/override.
- Environment-variable add/remove.
- Plist preview from a valid draft.
- Invalid form states and error rendering.
- Managed job edit enabled; external job edit unavailable.
- Save writes through fake services only and does not call lifecycle methods.

### Documentation at Increment 10 Close
- `README.md`: creating, editing, validating, saving, Python detection, schedule limits, log defaults, "Save does not deploy."
- `docs/architecture.md`: new draft/save application contracts and managed JSON lifecycle.
- `docs/development.md`: GUI form-test conventions and fake service setup.
- `PROJECT.md`, `TODOS.md`, `PLAN.md`, and `SUMMARY.md`.

**Version: 0.0.9 → 0.0.10**

---

## Crawl Increment 11 — GUI Installation and Lifecycle

### Goal
Allow users to explicitly deploy saved managed jobs and control their lifecycle through launchd, while protecting external jobs from modification.

### Pinned Decisions (approved 2026-08-30)
1. **Saved jobs are visible and installable:** catalog-only managed jobs (saved but not deployed) are merged into the main listing as an explicit **Saved, not installed** state — one unified table and selection model, no separate Saved section.
2. **Managed-only lifecycle is enforced at both boundaries:** `TaskCommandService` rejects every lifecycle operation whose target is not a managed catalog job (application boundary), and the GUI additionally disables lifecycle actions for non-managed rows (presentation boundary). The previous ability to operate on external labels by raw label is intentionally removed.
3. **Lifecycle state UI is truthful:** state = persisted desired configuration (`JobDefinition.enabled`) + runtime loaded state from launchctl status. Displayed states: **Saved, not installed** / **Installed, configured enabled (loaded/not loaded)** / **Installed, configured disabled (loaded/not loaded)** / **Status unknown**. No speculative launchd runtime enable-state parser in this increment.

### Requirements
- Add **Install**, **Reinstall**, **Uninstall**, **Enable**, **Disable**, and **Run Now** actions for managed jobs.
- Keep **Reinstall** explicit. It applies saved managed JSON changes to a previously installed LaunchAgent.
- Show clear success/failure results, including action, exit code, stdout, stderr, and useful next actions.
- Disable destructive lifecycle actions for external or invalid discovered jobs.
- Restrict operations to user LaunchAgents only.
- Keep all `launchctl` interaction behind `TaskCommandService`, `LaunchAgentBackend`, and `ProcessRunner`.
- Run potentially blocking operations outside the Qt event loop.

### Application-Service Work

**Unified task listing (merged catalog + discovery):**
- Introduce a unified listing DTO (`TaskListing`) carrying: listing kind (`saved` catalog-only / `discovered`), optional plist path, optional parsed plist, classification (managed/external/invalid), canonical `JobDefinition` when managed, and launchd status where available.
- `TaskCommandService.list_agents()` merges discovered LaunchAgents with catalog jobs that have no deployed plist, deterministically sorted.
- `AgentTableModel`, presenters, and the inspector consume the unified DTO; a catalog-only row displays **Saved, not installed** and exposes no plist/Advanced details.

**Pinned lifecycle contracts:**
```python
TaskCommandService.install(job: JobDefinition) -> InstallResult
TaskCommandService.reinstall(label: str) -> InstallResult
```

- **Install:** save/import managed JSON, create deployment plist, bootstrap the agent.
- **Reinstall:** resolve the saved managed JSON, safely replace its deployed plist, and reload/bootstrap.
- **Uninstall:** boot out the LaunchAgent and remove only the matching managed catalog record after successful bootout.
- **Enable/Disable/Run Now/Status:** remain label-based but every label resolves through the managed catalog first.
- Every lifecycle operation preserves the underlying `ProcessResult`.

**Managed-only lifecycle guards (application boundary):**
- `uninstall`, `enable`, `disable`, `status`, `run_now`, and `reinstall` resolve the label through the catalog before any backend call; a non-managed label raises the managed-job-not-found error instead of touching launchd.
- CLI commands surface the managed-only rejection with the established exit codes; service tests prove no backend call occurs for external labels.

**InstallResult enrichment (pinned return type kept):**
- `InstallResult` keeps its primary `ProcessResult` and gains optional bootout/bootstrap phase results, a completed-phase marker, and retained artifact paths (staged/backup) so failures are diagnosable without claiming rollback.

**Reinstall transaction semantics:**
1. Resolve managed job and validate label.
2. Preserve or stage the existing plist safely.
3. Boot out the installed job if required.
4. Write the new generated plist.
5. Bootstrap the new plist.
6. If deployment fails, retain diagnostic artifacts and return an actionable failure result.
7. Do not claim rollback succeeded unless it is verified.
8. Do not silently overwrite an existing plist.

**Staging primitives (minimal):**
- Extend `LaunchAgentFilesystem` + `FakeFilesystem` with the atomic move/replace primitives required: stage a uniquely named sibling plist via create-exclusive semantics, preserve the deployed plist as a uniquely named backup sibling, and an explicit activate step.
- `LaunchAgentStore` staging API: stage → backup → activate; never silently overwrites an existing plist.
- `LaunchAgentBackend` gains the separate bootout and bootstrap phase methods used by the reinstall sequence.

Add only the minimal store/backend capability needed for the explicit replace/reload path, with tests for its failure behavior.

### GUI Design

**Lifecycle actions:**
- A **Lifecycle** menu with stable public `QAction` attributes: `install_action`, `reinstall_action`, `uninstall_action`, `enable_action`, `disable_action`, `run_now_action`.
- A saved (not installed) managed row enables only **Install**.
- An installed managed row enables **Reinstall**, **Uninstall**, **Enable**, **Disable**, and **Run Now**.
- External and invalid rows have no lifecycle actions.

**State presentation:**
- Clearly distinguish: **Saved, not installed** / **Installed, configured enabled (loaded/not loaded)** / **Installed, configured disabled (loaded/not loaded)** / **Status unknown**.
- `JobDefinition.enabled` is presented as configured state, never asserted as a launchd runtime enable state.

**Confirmations and results:**
- Confirm **Uninstall** and **Reinstall**, naming the task, the exact managed label, and the scope (current-user LaunchAgent only).
- Operation-result dialog/panel containing:
  - Human-readable action result.
  - Exit code.
  - Launchd output/error details (stdout/stderr, launch-failure details).
  - "View technical details" expandable section (phase results, retained artifact paths).

**Worker boundary:**
- Qt-free lifecycle controller (`LifecycleAction` enum, immutable outcome DTOs, managed-target validation) plus a `QObject` worker moved to a `QThread`; all mutating service calls run off the main Qt thread; immutable results marshal back via Qt signals.
- All lifecycle controls (and conflicting New/Edit actions) disable while an operation is in flight — no duplicate dispatch; UI state restores on completion or worker exception.
- Refresh the merged listing after successful lifecycle actions; preserve the selected identity where possible and fall back predictably after uninstall.

### Testing

**Unit tests:**
- Install/reinstall request validation.
- Managed-only lifecycle gating.
- Replacement ordering and backend/store calls.
- Failure behavior at each reinstall phase.
- Catalog retention/removal rules.
- Raw process output retention.

**Widget/controller tests:**
- Correct action availability by managed/installed/status state.
- Confirmation flows.
- Busy-state handling.
- Successful result display and refresh.
- Failure result display with stdout/stderr/exit code.
- External/invalid task actions remain unavailable.
- Worker completion/error propagation without calling real platform services.
- Multi-phase transaction tests script ordered results through `FakeProcessRunner`/`FakeTaskWorld` (stage → bootout → backup → activate → bootstrap) and assert per-phase artifact retention on failure.
- Modal confirmation/result dialogs are exercised with the established `QTimer.singleShot(0, ...)` pattern before the synchronous action trigger (pytest-qt runs single-threaded).

Retain existing protected system integration tests. Add real launchctl integration coverage only for behavior that fake-backed tests cannot establish, guarded by `MACTASK_ALLOW_SYSTEM_TESTS=1`.

### Approved Execution Plan (micro-slices, approved 2026-08-30)
1. Unified `TaskListing` DTO + merged `list_agents()` + presenter/table/inspector support (+ tests).
2. Managed-only service guards + CLI rejection + `InstallResult` enrichment (+ tests).
3. Filesystem/store staging primitives + backend bootout/bootstrap phase methods (+ failure tests).
4. `install(job)` / `reinstall(label)` service behavior + exhaustive transaction tests.
5. Qt-free lifecycle controller + `QThread` worker (+ controller/worker tests).
6. Lifecycle menu actions, confirmations, result dialog, state presentation (+ widget tests).
7. GUI integration tests; restore 100% whole-package coverage.
8. Docs + version 0.0.10 → 0.0.11 closeout (README, architecture, development, PROJECT/TODOS/PLAN/SUMMARY), `make check`, commit, push.

Each slice: on-disk verification, `make check` + 100% package coverage, commit before the next slice.

### Documentation at Increment 11 Close
- `README.md`: install, reinstall, uninstall, enable, disable, run-now workflow and user-only safety boundary.
- `docs/architecture.md`: lifecycle worker boundary and explicit redeploy transaction.
- `docs/development.md`: how to run opt-in integration tests and expected cleanup behavior.
- `PROJECT.md`, `TODOS.md`, `PLAN.md`, and `SUMMARY.md`.

**Version: 0.0.10 → 0.0.11**

---

## Crawl Increment 12 — GUI Diagnostics and Logs

### Goal
Complete the primary troubleshooting workflow: directly test managed or validated draft jobs, show stdout/stderr and structured diagnostics, compare environments, recommend Python interpreters, and view persisted logs.

### Pinned Decisions (approved 2026-08-30)
1. **Two entry points:** diagnostics for the selected managed task in the main window, and for the currently validated draft in the job editor (no draft persistence).
2. **Persisted logs are draft-capable:** a job-based façade `read_logs_for(job)` that works for validated drafts, with `read_logs(label)` retained for managed jobs and delegating to it.
3. **Environment disclosure is name-only:** category headings and variable names by default; no reveal control in this increment.
4. **Direct tests run off-thread:** through a `QObject` worker on a `QThread` (same pattern as lifecycle); never on the UI thread.

### Requirements
- Add **Test** for direct execution (Mode A).
- Display direct-test exit code, duration, stdout, stderr, launch failures, and structured diagnostics.
- Display configured persisted stdout/stderr logs.
- Add Refresh for logs.
- Show configured/unconfigured/missing/unreadable log states clearly.
- Add environment comparison between the GUI process environment and the task's configured scheduled environment.
- Disclose that the GUI process environment can differ from the user's Terminal environment.
- Add Python interpreter recommendations when testing Python jobs.
- Do not add log tailing/following, execution history, scheduled-run verification, or generalized shell-environment capture.
- "Reveal in Finder" is optional and deferred unless the specification is explicitly amended.

### Application-Service Work

Extend the façade:
```python
TaskCommandService.test_job(
    job: JobDefinition,
    *,
    detection: PythonDetectionResult | None = None,
) -> DirectTestResult

TaskCommandService.compare_environment(
    job: JobDefinition,
    terminal_environment: Mapping[str, str],
) -> EnvironmentDifference
```

- `test_job()` supports validated, unsaved GUI drafts.
- Existing `test(label)` resolves a saved managed job and invokes the same path.
- For Python jobs, detect candidates before testing and pass detection into `DirectTestService` so interpreter-mismatch diagnostics are available.
- Environment comparison receives a copy of `os.environ` from the GUI composition/controller layer. The platform comparison function remains pure.
- Logs remain read-only through `LogService`.

### GUI Design

**Diagnostics/logs panel:**
- **Test summary:** pass/fail state, exit code, elapsed duration.
- **Diagnostics:** severity, title, explanation, suggested action.
- **Direct stdout** and **Direct stderr** tabs.
- **Persisted logs:** stdout/stderr tabs with Refresh.
- **Environment comparison:** terminal/app-only, scheduled-only, and differing values.
- **Python recommendation:** detected candidate list, selected interpreter, recommended change.

Label the direct test accurately:
> Test runs this command directly using its configured executable, arguments, working directory, and environment. It does not prove launchd can run it on schedule.

Do not render arbitrary raw environment values by default if they may contain secrets. Show variable names and difference categories first.

### Testing

**Unit tests:**
- Draft and saved-job direct tests.
- Python detection passed through to diagnostics.
- All structured diagnostic rule outcomes.
- Environment comparison using a supplied GUI-process environment mapping.
- Logs with content, empty file, missing file, unreadable file, and unconfigured paths.

**Widget tests:**
- Direct-test wording and result rendering.
- stdout/stderr tabs and empty output.
- Diagnostic severity and suggested-action rendering.
- Python recommendation display.
- Environment-difference categories and disclosure text.
- Persisted-log Refresh behavior.
- Error states with fake readers/services.

### Approved Execution Plan (micro-slices, approved 2026-08-30)
1. **Façade contracts:** `test_job(job, *, detection=None)`, `test(label)` refactored to resolve + delegate, `compare_environment(job, terminal_environment)`, `read_logs_for(job)` with `read_logs(label)` delegating, and `gui_environment()` in the composition layer (+ unit tests).
2. **Diagnostics controller + worker:** Qt-free `DiagnosticsController` (request/execute/finish plus synchronous `read_logs`/`compare_environment`) and a `QObject` test worker on a `QThread` (+ controller/worker tests).
3. **Diagnostics presentation + panel:** presenters for test outcome, diagnostics, environment difference, and Python detection; `DiagnosticLogsPanel` with four log tabs, Refresh, and environment/Python groups (`diagnostics-*` object names) (+ widget tests).
4. **MainWindow + JobEditor integration:** panel below the inspector with a selection-gated Test action and the fourth controller wired; "Test Draft" in the editor opens a modal `DirectTestDialog` hosting the shared panel (+ widget tests).
5. **Tests and coverage:** error states with fake readers/services; restore 100% whole-package coverage.
6. **Docs + version 0.0.11 → 0.0.12 closeout** (README, architecture, development, PROJECT/TODOS/PLAN/SUMMARY), `make check`, commit, push.

Each slice: on-disk verification, `make check` + 100% package coverage, commit before the next slice.

**Slice 4 refinements (approved 2026-08-31):** `DirectTestDialog` wires the shared panel's Refresh button to a synchronous re-read of persisted logs and the environment comparison. No dialog-level outcome-label guard: the controller permits a single in-flight request and MainWindow owns the selection/stale-result guard. Test Draft must not persist anything (no catalog record, plist, or lifecycle side effect).

### Documentation at Increment 12 Close
- `README.md`: test semantics, direct-test limitations, diagnostics, environment-comparison disclosure, logs, and security guidance against storing secrets in job definitions.
- `docs/architecture.md`: diagnostics/test façade contracts and presentation-safe environment comparison.
- `docs/development.md`: diagnostic/log test fixtures and safety rules.
- `PROJECT.md`, `TODOS.md`, `PLAN.md`, and `SUMMARY.md`.

**Version: 0.0.11 → 0.0.12**

---

## Crawl Complete

All 13 Crawl increments are implemented.

- **Version:** 0.0.13
- **Tests:** 767 passed, 2 deselected
- **Coverage:** 100% line coverage (3117 statements)
- **Lint/TypeCheck:** ruff + mypy strict clean
- **Artifact:** `dist/macOS Task Scheduler for Humans.app` (self-contained, ad-hoc signed)

**Verification at v0.0.13:** `make check` passes. `make package` produces a standalone `.app` that opens without Terminal or a venv.

---

## Walk Phase — Approved Plan (2026-09-04)

Crawl is complete. The Walk phase covers spec sections 57–63 in eight increments (14–22), each delivered as a small vertical slice: contract → platform/application → CLI → GUI → tests → docs, with `make check` + 100% package coverage and a `+0.0.1` version bump at closeout.

### Pinned Walk Decisions (approved 2026-09-04)
1. **Schema v2 schedule variants:** `JobDefinition.schedule` becomes a discriminated union of `CalendarSchedule` and `IntervalSchedule` (pinned contract below). `SUPPORTED_SCHEMA_VERSION = 2`. v1 JSON remains readable through a storage-layer migration; all writes are v2. No compatibility shims in GUI or plist code.
2. **Core scheduling first:** increments 14–17 (model, preview, multi-time, interval/login) precede detection (18), diagnostics (19), history (20), import (21), and UX/transfer (22).
3. **"Daily" is a UI shortcut** that selects all seven weekdays — it is not a persisted schedule type.
4. **`RunAtLoad` is additive only:** it coexists with a calendar or interval schedule and can never be the sole schedule. Login-only plists remain non-representable and are surfaced as parser warnings.
5. **Interval minimum:** 60 seconds (`MIN_INTERVAL_SECONDS = 60`), persisted as raw seconds, presented as a human duration.
6. **Multi-time plists parse as the Cartesian product:** the reader reconstructs distinct times × distinct weekdays (the codec emits the Cartesian product, so round-trips are lossless).
7. **External imports (§61)** of partially supported plists are allowed only after every unsupported key/warning is shown and explicitly acknowledged (GUI confirmation / CLI flag). Imports are catalog-only and never touch the source plist.
8. **Execution history (§59)** stores metadata only: timestamp, event kind/outcome, exit code, duration, loaded state, diagnostic codes. Never stdout/stderr, environment values, raw launchctl output, or free-text diagnostic descriptions.
9. **Python ecosystem detection (§58)** starts filesystem/config-based (no tool invocation): uv and Poetry first, then pyenv/Conda/Pipenv/Homebrew through the same detector interface. Candidates remain recommendations; no automatic interpreter replacement.
10. **No generic property-list editor**, no claims that derived data reflects launchd's internal queue, and the GUI boundary (no `launchctl`/`subprocess`/plist-writing/live-filesystem calls) is unchanged.

### Pinned v2 Schedule Contract (increment 14 interface — settled before implementation)
```python
# domain/schedule.py
class CalendarSchedule(BaseModel):
    kind: Literal["calendar"] = "calendar"
    times: list[time]        # >= 1; validator sorts ascending and dedupes
    weekdays: set[Weekday]   # >= 1
    run_at_load: bool = False

class IntervalSchedule(BaseModel):
    kind: Literal["interval"] = "interval"
    seconds: int             # >= MIN_INTERVAL_SECONDS (60)
    run_at_load: bool = False

MIN_INTERVAL_SECONDS = 60
Schedule = Annotated[Union[CalendarSchedule, IntervalSchedule], Field(discriminator="kind")]
```
- JSON: `{"kind": "calendar", "times": ["07:30:00"], "weekdays": ["monday"], "run_at_load": false}` / `{"kind": "interval", "seconds": 1800, "run_at_load": false}`.
- v1 migration (storage layer only): `{"time": "07:30:00", "weekdays": [...]}` → calendar variant with one time, `run_at_load=false`, `schema_version=2`.
- Plist codec: calendar → `StartCalendarInterval` grouped by time ascending, weekdays canonical order within each time; interval → `StartInterval`; `run_at_load=True` → `RunAtLoad: True` (absent when `False`).
- Plist reader: multi-time calendar → Cartesian reconstruction; `StartInterval` ≥ 60 → interval variant; `StartInterval` < 60 → partial-support warning, no job; both schedule keys present → conflict warning, no job; `RunAtLoad`-only → warning, no job; `StartInterval`/`RunAtLoad` join `SUPPORTED_KEYS`.

### Increment 14 — Schedule Model and Migration (§57) — current
1. Replace the mandatory single `Schedule(time, weekdays)` contract with the pinned v2 variants.
2. Retain v1 JSON read compatibility; newly saved jobs use schema v2.
3. Centralize v1→v2 normalization in the storage layer.
4. Update `JobDefinition`, JSON repository, validation, `PlistCodec`, `plist_reader`, `plist_models`, and round-trip fixtures.
5. Preserve parser raw-source/warning/unsupported-key reporting for configurations that cannot be represented (login-only, sub-60s intervals, schedule-key conflicts).
6. CLI `format_schedule` and GUI presenters/inspector become variant-aware; the editor continues to author single-time calendar schedules (multi-time authoring is increment 16).
7. Migration, validation, codec, parser, and JSON round-trip tests using fixtures only; `make check` + 100% coverage; docs updated (README schedule limits, architecture v2 persistence).

### Increment 15 — Next-Run Preview (§62)
Pure `upcoming_occurrences(schedule, *, now, count)` with an injected clock; mandatory wording “Estimated upcoming schedule occurrences — application-derived schedule preview, not launchd's internal queue”; displayed in the inspector and editor with a fixed count in local time; disabled jobs show occurrences labeled “configured disabled”; no recurring preview for login-only (not representable anyway); formatting stays in presenters; deterministic boundary tests (same-day before/after, weekday rollover, ordering, count, local-time behavior).

### Increment 16 — Calendar Scheduling Expansion (§57)
Multiple times per day for calendar schedules (times apply to the selected weekdays); reusable time-row editor — `job_editor.py` (489 lines) and `editor_controller.py` (430 lines) are near the review threshold, so decompose rather than append; update rendered descriptions, inspectors, previews, and next-run calculation; ordering/dedupe/invalid-time/round-trip tests.

### Increment 17 — Interval and Login Triggers (§57)
Interval schedules backed by `StartInterval` (human-scale duration input, ≥60s, persisted seconds) and optional login behavior via `RunAtLoad`, parsed and generated and registered in `SUPPORTED_KEYS`; interval previews state the estimate is anchored to the application's supplied clock, not launchd's anchor; external jobs remain read-only; each trigger tested independently and combined.

### Increment 18 — Python Environment Detectors (§58)
Immutable detector protocol + ordered registry behind the existing `detect_python()` facade; extract current `.venv`/`venv`/current/PATH discovery as the first detector with unchanged priority; result DTOs gain detector provenance and non-fatal notes; filesystem/config-only detectors added one at a time (uv, then Poetry; pyenv, Conda, Pipenv, Homebrew in later increments); no ecosystem executables invoked; candidates remain explicit recommendations; injected filesystem/config readers keep tests host-independent.

### Increment 19 — Expanded Diagnostics (§60)
Keep the direct-test engine and its deterministic ordering; add typed diagnostic contexts (lifecycle result, parsed plist, log-read result, inspection result) instead of widening `evaluate_diagnostics()` with unstructured optional arguments; low-risk rules first (runtime executable-not-found, missing working directory, broader Python import failures, malformed plist, invalid label, inaccessible log path, launchctl bootstrap/registration failure); GUI groups findings by source (preflight, direct test, lifecycle, logs, Python environment); protected-folder/privacy and architecture checks only as best-effort warnings distinguishing confirmed / unavailable / not-provable; retain the direct-test limitation wording.

### Increment 20 — Application-Observed Execution History (§59)
Stdlib `sqlite3` append-only repository in `storage/` beside the JSON catalog; event schema per decision 8; events recorded at application-service boundaries (`test_job`, `run_now`, explicit `status` observations, aggregate diagnostic result) so CLI and GUI behave identically; one direct-test event plus one aggregate diagnostic-result event per test; bounded read-only queries; `mactask history <label> --limit N`; Qt-free controller + read-only GUI history panel; corrupt/unavailable database reported safely without affecting scheduler operations; never infer scheduled executions from logs or launchctl state.

### Increment 21 — External Plist Import (§61)
Read-only import preview normalizing a parsed external plist into a candidate managed `JobDefinition` (new durable UUID at commit, never the parser-generated identity); refuse invalid/unrepresentable plists; show every warning/unsupported key and require explicit acknowledgement for partial plists; commit writes managed JSON only (label-conflict rejection, never overwrite); imported jobs retain the original label and stay catalog-only until an explicit deployment path; GUI external-row-only action + `mactask import <plist-path>` with an acknowledgement flag.

### Increment 22 — Walk UX and Managed JSON Transfer (§63)
`QSortFilterProxyModel` search/filters (name/label/command; classification, saved/installed, configured enabled, loaded, parse validation); visual status and validation badges with text fallbacks; context-aware empty states (no tasks vs. no matches + clear filters); retain existing Reinstall/Uninstall confirmations; reveal plist/logs in Finder through a platform adapter (no GUI subprocess); copy command/plist via pure shared formatting + Qt clipboard; catalog-only JSON export/import (schema validation, immutable-ID and label-conflict detection, never deploys) — distinct from increment 21's plist import; CLI transfer equivalents where meaningful.

### Walk Definition of Done (spec §64)
The application answers, with truthful wording: what scheduled jobs exist; what a job will run; which Python it uses; when it should run; why it didn't work; and what launchd currently thinks about it.

---

## Required Verification and Closeout for Every Increment

Before closing each increment:

1. Run `make check`.
2. Run explicit coverage:
   ```bash
   .venv/bin/python -m pytest --cov=task_scheduler --cov-report=term-missing
   ```
3. Run protected integration tests only when platform behavior changes:
   ```bash
   MACTASK_ALLOW_SYSTEM_TESTS=1 make integration
   ```
4. Confirm no unit test accesses real user LaunchAgents, invokes `launchctl`, or depends on host Python environments.
5. Review source sizes: logic-heavy files below 500 lines; review decomposition around 400–450 lines; functions generally below 50 lines.
6. Increment version exactly by `+0.0.1`.
7. Update every registry location in `versions_locations.md`.
8. `grep` the repo for the old version to catch missed references.
9. Update `PROJECT.md`, `TODOS.md`, `SUMMARY.md`, and `PLAN.md` in the same commit.
10. Update README and architecture/development documentation when user-visible behavior, commands, dependencies, safety guarantees, or package behavior changes.
11. Commit only verified changes and push the increment version upstream.
