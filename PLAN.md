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

Current focus: **Crawl Increment 13 — Packaging** (planned below).

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

## Crawl Increment 13 — Packaging

### Goal
Produce a locally usable, double-clickable `macOS Task Scheduler for Humans.app` for the current Mac using PySide6 deployment tooling.

### Requirements
- Use `pyside6-deploy`.
- Produce a local `.app` bundle named `macOS Task Scheduler for Humans.app`.
- Target the current development machine's native architecture.
- Preserve the independent `mactask` CLI entry point.
- Do not require code signing, hardened runtime, notarization, App Store distribution, universal builds, DMG/PKG generation, automatic updates, or CI release publishing.

### Implementation Approach
1. Add/verify a GUI executable entry point:
   - Creates `QApplication`.
   - Constructs services through the shared bootstrap composition root.
   - Opens the main window.
   - Returns the Qt event-loop exit code.
2. Add a version-controlled PySide6 deployment configuration file.
3. Define:
   - app display name,
   - bundle name,
   - GUI entry point,
   - output location ignored by Git,
   - current-machine architecture expectation,
   - icon policy if an approved icon asset exists.
4. Add a `make package` target that invokes the deployment configuration.
5. Add a `make run-gui` target for development startup.
6. Ensure the generated app does not depend on the source checkout or activated virtual environment at runtime.
7. Keep deployment artifacts out of source control.

### Pinned Decisions (approved 2026-08-31)
1. **Entry point:** `main()` returns the Qt event-loop exit code (`int`); a module launcher (`if __name__ == "__main__": sys.exit(main())`) provides direct and bundled execution; the installed `mactask-gui` console script exits with the returned code.
2. **Deployment configuration:** version-controlled `pysidedeploy.spec` at the repository root — title/bundle name `macOS Task Scheduler for Humans`, `input_file = src/task_scheduler/gui/app.py`, `exec_directory = dist`, `mode = standalone`, no custom icon (PySide6 fallback icon until an approved asset exists).
3. **Artifacts:** final bundle at `dist/macOS Task Scheduler for Humans.app`; the Nuitka intermediate directory (`deployment/`) and `dist/` are Git-ignored; the generated app must run without the source checkout or an activated virtual environment.
4. **Build interface:** `make package` invokes `.venv/bin/pyside6-deploy -c pysidedeploy.spec -f` (non-interactive); `make run-gui` starts the development GUI through the venv. Full bundle builds are not part of `make check`.
5. **Config-only deployment fixes:** missing Qt plugins/frameworks are fixed in the spec (`[qt]`, `[nuitka]`), never with ad hoc runtime-path code in application modules.
6. **Icon policy:** ship with the PySide6 fallback icon; no custom `.icns` in this increment.

### Approved Execution Plan (micro-slices, approved 2026-08-31)
1. **Entry point + build interface:** `main() -> int` + module launcher, entry-point test update, `make run-gui`, `make package`, `deployment/` ignore rule (+ `make check`, coverage, commit).
2. **Deployment configuration:** root `pysidedeploy.spec`; first real `make package` build producing `dist/macOS Task Scheduler for Humans.app`; spec-level adjustments if Qt dependencies are missing (+ `make check`, coverage, commit).
3. **Standalone bundle verification:** the manual macOS smoke checklist against the built bundle (Finder/`open` launch, no Terminal/venv, safe discovery, New Task, no startup lifecycle, current-user scope, non-destructive paths) (+ record results, commit).
4. **Docs + version 0.0.12 → 0.0.13 closeout** (README, development, architecture, PROJECT/TODOS/PLAN/SUMMARY), `make check`, commit, push.

Each slice: on-disk verification, `make check` + 100% package coverage, commit before the next slice.

### Packaging Verification
```bash
make check
.venv/bin/python -m pytest --cov=task_scheduler --cov-report=term-missing
make package
```

### Manual macOS Smoke Checklist
1. Launch the generated `.app` from Finder or `open`.
2. Confirm the main window opens without Terminal or an activated virtual environment.
3. Confirm discovery loads safely.
4. Confirm New Task opens.
5. Confirm no lifecycle operation runs merely at app startup.
6. Verify the app uses the current-user LaunchAgent scope only.
7. Exercise a fake/non-destructive path before testing actual install behavior.
8. If real lifecycle behavior is manually tested, use a unique test-owned label and clean it up.

If the bundle fails because a Qt/plugin/framework is missing, fix the deployment configuration rather than adding ad hoc runtime path code to application modules.

### Documentation at Increment 13 Close
- `README.md`: prerequisites, package command, generated artifact location, local architecture scope, launch instructions, and explicit signing/notarization status.
- `docs/development.md`: package build, cleanup, and bundle smoke-test procedure.
- `docs/architecture.md`: GUI entry point and packaging boundary.
- `PROJECT.md`: Crawl GUI/package state and next product-phase direction.
- `TODOS.md`: mark packaging complete with the verified artifact and smoke-check result.
- `PLAN.md`: replace Crawl implementation strategy with the next Walk-phase plan or explicitly mark Crawl complete.
- `SUMMARY.md`: packaging implementation, verification outcome, app artifact location, and deferred distribution scope.

**Version: 0.0.12 → 0.0.13**

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
