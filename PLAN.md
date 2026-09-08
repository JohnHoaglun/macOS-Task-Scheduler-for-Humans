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

Current focus: none — **Walk Increment 20 — Application-Observed Execution History** shipped 2026-09-07 at v0.0.20 (`22dfa09` plan / `2d261a0` stage 0 / `f93337f` 1A / `b8559ec` 1E / `d005ade` 1B / `bc65d7b` 1C / `8ccf653` 1D / `ad6d511` integration); increments 14–20 complete at v0.0.20.
- Verification at v0.0.20: 1184 tests, 100% coverage (4416 statements), `make check` clean (ruff / mypy strict / pytest, no ResourceWarnings); same-turn ratio enforcement then cut the suite to 323 tests at 100% coverage (tests 5,444 lines = 62.4% of the 8,723 production lines, under the 75% cap)

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

### Increment 14 — Schedule Model and Migration (§57) — DONE (196b0d3)
1. Replace the mandatory single `Schedule(time, weekdays)` contract with the pinned v2 variants.
2. Retain v1 JSON read compatibility; newly saved jobs use schema v2.
3. Centralize v1→v2 normalization in the storage layer.
4. Update `JobDefinition`, JSON repository, validation, `PlistCodec`, `plist_reader`, `plist_models`, and round-trip fixtures.
5. Preserve parser raw-source/warning/unsupported-key reporting for configurations that cannot be represented (login-only, sub-60s intervals, schedule-key conflicts).
6. CLI `format_schedule` and GUI presenters/inspector become variant-aware; the editor continues to author single-time calendar schedules (multi-time authoring is increment 16).
7. Migration, validation, codec, parser, and JSON round-trip tests using fixtures only; `make check` + 100% coverage; docs updated (README schedule limits, architecture v2 persistence).

### Increment 15 — Next-Run Preview (§62) — DONE (v0.0.15)
Pure `upcoming_occurrences(schedule, *, now, count)` with an injected clock; mandatory wording “Estimated upcoming schedule occurrences — application-derived schedule preview, not launchd's internal queue”; displayed in the inspector and editor with a fixed count in local time; disabled jobs show occurrences labeled “configured disabled”; no recurring preview for login-only (not representable anyway); formatting stays in presenters; deterministic boundary tests (same-day before/after, weekday rollover, ordering, count, local-time behavior).

**Pinned decisions (approved 2026-09-04):**
1. **Preview count:** fixed 5 occurrences in both the inspector and the editor.
2. **Boundary rule:** an occurrence exactly at `now` is included (`>= now`).
3. **Calendar-only:** `IntervalSchedule` previews (anchor estimation) are deferred to increment 17; the preview block shows an honest no-preview note for interval schedules.
4. **`run_at_load`** never contributes a dated occurrence (additive only).
5. **Display:** local, naive datetimes; lines formatted `%a %b %d %H:%M` (e.g. `Wed Aug 26 07:30`); the exact disclosure sentence always accompanies the occurrence list; the editor shows a neutral “complete the schedule” state while the visible time/weekday fields are incomplete or invalid.
6. **GUI:** widgets take an injectable `clock: Callable[[], datetime]` (default `datetime.now`) so tests stay deterministic; all wording/formatting lives in the presenter, widgets only place text.

**Implementation plan:**
- `domain/schedule.py`: `upcoming_occurrences(schedule: CalendarSchedule, *, now: datetime, count: int) -> list[datetime]` — pure, no I/O; raises `ValueError` for `count < 1`; walks local dates from `now.date()`, combines configured weekdays (Python `date.weekday()` mapping) with the sorted configured times, keeps candidates `>= now`, returns exactly `count` in chronological order. Exported from `domain/__init__.py`.
- `gui/presenters/agent_presenter.py`: `PREVIEW_COUNT`, `PREVIEW_DISCLOSURE` (exact mandatory sentence), `PREVIEW_HEADING`, `PREVIEW_DISABLED_HEADING`, `PREVIEW_INCOMPLETE`, `PREVIEW_UNAVAILABLE` constants; `format_upcoming_heading(listing)`, `format_upcoming_occurrences(schedule, *, now)` (editor path), `format_upcoming_occurrences_for(listing, *, now)` (inspector path: no job → unavailable note, interval → no-preview note).
- `gui/widgets/agent_inspector.py`: Schedule group gains `schedule-preview-heading` / `schedule-preview-disclosure` / `schedule-preview-occurrences` labels, filled in `_fill`; `__init__` gains the `clock` kwarg.
- `gui/widgets/job_editor.py`: Schedule group gains `editor-preview-heading` / `editor-preview-disclosure` / `editor-preview-occurrences` labels; the preview recomputes from the *visible* time/weekday fields (draft is stale until collect) on load and on every field edit; weekday day-name tuple hoisted to a module constant; `__init__` gains the `clock` kwarg.
- Tests: domain boundary matrix (same-day before/exact/after, Saturday-from-Friday and Sunday→Monday rollovers, multi-time + multi-weekday ordering, counts, naive local-time shape, `run_at_load` ignored, `count < 1` rejected); presenter exact wording and no-preview states; inspector saved/discovered/disabled/interval/invalid states with a fixed clock; editor initial/refresh-on-edit/neutral-incomplete states with a fixed clock.

### Increment 16 — Calendar Scheduling Expansion (§57) — DONE (v0.0.16, approved 2026-09-05)
Multiple times per day for calendar schedules (times apply to the selected weekdays); reusable time-row editor — `job_editor.py` (545 lines) and `editor_controller.py` (441 lines) are past/at the review threshold, so decompose rather than append. The domain, plist codec/reader, CLI rendering, presenter formatting, inspector display, and next-run calculator already support multiple calendar times; this increment closes the authoring gap only.

**Pinned decisions (approved 2026-09-05):**
1. **Schema unchanged:** calendar JSON stays `{"kind": "calendar", "times": ["HH:MM", ...], "weekdays": [...], "run_at_load": bool}` (v2); v1 read migration and the time × weekday Cartesian product contract are untouched.
2. **Draft contract:** `JobDraft.time: str` is replaced by `JobDraft.times: list[str]` — raw visible row strings, verbatim, in row order; new drafts default to `[""]` (one empty slot).
3. **Canonicalization owned by the domain:** the UI passes raw row strings; `CalendarSchedule` remains the sole authority for strict `HH:MM` validation, ascending sort, and duplicate collapse. The GUI implements no second time parser for validate/preview/save.
4. **Reusable widget:** a dedicated `TimeRowEditor` (new `gui/widgets/time_row_editor.py`), not a time-aware `RowTable`. Public API: `rowsChanged` signal, `set_times(values: list[str])`, `times() -> list[str]` (each row `.strip()`ed, row order). Parent object name set by the host (`editor-times`); row object names are `editor-time` (index 0) and `editor-time-<i>` (index i), renumbered on every structural change; internal buttons `timerow-add` / `timerow-remove`.
5. **Row semantics:** new drafts render one blank row; minimum one row — removing the final row restores one blank row; Add appends one blank row; `set_times([])` renders one blank row; each row is a `QLineEdit` with placeholder `HH:MM` and max length 5; no maximum row count.
6. **Signals:** `rowsChanged` emits once per `set_times` replacement and once per add/remove; row text edits propagate through each row's `textEdited` (programmatic `setText` during load does not churn Save state or the preview).
7. **Validation:** schedule-time failures map to the stable field key `times` (message from the domain validator, naming the offending value); empty time list → `_DraftError("times", "at least one time is required")`; weekday failures keep the existing mapping. Duplicate rows are legal in the UI and collapse at the domain boundary.
8. **Preview:** the editor preview builds `CalendarSchedule` from *all* visible rows; any blank/invalid row or no selected weekday makes it neutral (`PREVIEW_INCOMPLETE`) — it never previews a partial subset. All Increment 15 behavior (5 items, `>= now`, local naive, exact disclosure) is preserved unchanged.
9. **Authoring model:** every configured time applies to every selected weekday; per-time weekday selection is explicitly out of scope. External jobs stay read-only; interval schedules are not editable in this increment (increment 17).
10. **Decomposition:** `JobEditor` composes `TimeRowEditor` and owns orchestration only; schedule draft conversion stays inside `EditorController` without growing that file past its review threshold.

**Implementation plan:**
- `gui/widgets/time_row_editor.py` (new): the pinned `TimeRowEditor` widget; own test file `tests/unit/gui/test_time_row_editor.py` (initial row, set/times round trip, strip behavior, add/remove/last-row floor, `set_times([])` floor, signal counts, object-name renumbering).
- `gui/controllers/editor_controller.py`: `JobDraft.times` (default `[""]`); `set_times(draft, values)` (verbatim copy); `open_existing` loads every calendar time as `HH:MM` (interval → `[""]` + empty weekdays, as today); `_build_schedule` raises `_DraftError("times", ...)` for an empty list and delegates invalid values to the `CalendarSchedule` validator (first error message, field key `times`); `Time` import dropped.
- `gui/widgets/job_editor.py`: replace the single `editor-time` line edit with `TimeRowEditor` (`editor-times`) in the "Times (HH:MM)" form row; wire `rowsChanged` → `_on_draft_changed`; `_load_draft` calls `set_times(d.times)`; `_collect` calls `set_times(d, self._times.times())`; `_form_schedule` builds from all visible rows (neutral on blank/invalid rows); schedule note updated to "each scheduled time"; `Time` import dropped, `ValidationError` import added.
- Tests: `test_editor_controller.py` (list draft shape, one-time compatibility, multi-time load/collect/build, ordering/dedupe via the domain, empty-list and invalid-row validation with the `times` field key); `test_job_editor.py` (one-row load, multi-time load in canonical order, add/remove updates the live preview, blank/invalid rows neutral, collect/Validate/Preview/Test Draft/Save carry all rows, fixed-clock multi-time preview ordering); `test_main_window.py` helper updates only if the `editor-time` first-row name does not keep them green; regression coverage for the already-multi-time domain/presenters/inspector/CLI boundaries added where authoring-flow proof is missing.
- Retained as regression gates (no production change expected): `domain/schedule.py`, `platform/macos/plist_codec.py`, `platform/macos/plist_reader.py`, `gui/presenters/agent_presenter.py`, `gui/widgets/agent_inspector.py`, `cli/render.py`.
- Verification: `make check` + explicit 100% package coverage + source-size review (logic-heavy files below 500 lines; `job_editor.py` must shrink from 545); docs (README multi-time authoring, architecture draft contract + time-row boundary, development test conventions); version 0.0.15 → 0.0.16 with registry + stale-reference grep.

### Increment 17 — Interval and Login Triggers (§57) — DONE (v0.0.17, approved 2026-09-05)
The domain, plist codec/reader, CLI rendering, and inspector already support `IntervalSchedule` (`StartInterval`) and `RunAtLoad`; the editor cannot author them — `JobDraft` is calendar-only and an opened interval job loads as blank calendar fields, so saving it silently converts the schedule. This increment closes the authoring gap (interval duration + login trigger, both schedule kinds) and replaces the honest no-interval-preview note with a truthful application-clock-anchored interval estimate.

**Pinned decisions (approved 2026-09-05):**
1. **Schema unchanged:** v2 JSON stays `{"kind": "interval", "seconds": int, "run_at_load": bool}` / `{"kind": "calendar", ...}`; `MIN_INTERVAL_SECONDS = 60` is untouched; plist encoding/reading (`StartInterval`, `RunAtLoad`) is untouched — editor authoring only.
2. **Draft contract:** `JobDraft` gains `schedule_kind: Literal["calendar", "interval"]` (new drafts default to `"calendar"`), `interval_value: str` (raw visible number text, verbatim), `interval_unit: str` (one of `"seconds"`, `"minutes"`, `"hours"`, `"days"`), and `run_at_load: bool` (default `False`). Existing `times` / `weekdays` fields remain and hold calendar-mode values.
3. **Duration input:** a whole-number field plus a unit selector (Seconds / Minutes / Hours / Days). `Seconds` is mandatory in the unit set because the domain legally accepts any integer ≥ 60 (e.g. 61) that a minutes-only control could not represent. The GUI performs no seconds math beyond the single unit conversion `value * unit_seconds`; the domain remains the sole authority for the ≥ 60 validation.
4. **Load normalization:** existing interval seconds load into the largest exact unit — days, then hours, then minutes, then seconds (e.g. 3600 → `1` + `hours`, 90 → `90` + `seconds`, 172800 → `2` + `days`, 93600 → `26` + `hours` because it is not an exact day multiple).
5. **Mode switching preserves per-mode values:** switching Calendar ↔ Interval keeps both sets of field values in the draft; only the selected kind is built and saved. `run_at_load` is shared by both kinds and survives switches.
6. **RunAtLoad is additive only:** one common "Run at login" checkbox in the Schedule group, default off; the editor never offers a login-only schedule (no schedule kind without a time source), matching the domain invariant.
7. **Validation:** empty/non-integer/zero/negative duration → stable field key `interval`; a converted total below 60 seconds fails through the domain `IntervalSchedule` validator with its message mapped to `interval`. Calendar validation/preview behavior is preserved unchanged.
8. **Interval preview:** new pure `upcoming_interval_occurrences(schedule, *, now, count)` in `domain/schedule.py` — the first estimated occurrence is exactly `now + seconds` (the first run *after* the interval, per the user's choice), then each subsequent interval; naive local datetimes, chronological, exact `count` (≥ 1, else `ValueError`), `run_at_load` ignored. Displayed with seconds precision (`%a %b %d %H:%M:%S`) so sub-minute intervals stay truthful; calendar display stays minute-precision.
9. **Preview wording:** the existing mandatory disclosure is preserved verbatim; the interval body states the estimate starts one interval after the application clock and that launchd's actual anchor is not known. Calendar wording/behavior unchanged; the `PREVIEW_NO_INTERVAL` note is replaced by the estimate in both inspector and editor.
10. **External jobs stay read-only:** inspector shows the new interval estimate for discovered/invalid/partial listings; no edit path is added for non-managed jobs.
11. **Decomposition:** `JobEditor` adds the kind selector, two stacked schedule pages (calendar page reuses `TimeRowEditor` + weekday checkboxes with their existing object names), interval page (value + unit), and the shared checkbox; schedule draft conversion stays in `EditorController`.

**Implementation plan:**
- **Lane A — domain preview helper:** `domain/schedule.py`: `upcoming_interval_occurrences(schedule, *, now, count)` (accepts `IntervalSchedule` only); `domain/__init__.py` export if the export convention requires it; `tests/unit/domain/test_schedule.py` (exact `now + seconds` first occurrence, chronology, multi-day span, non-minute seconds, counts, `count < 1` rejected, `run_at_load` ignored, calendar argument rejected).
- **Lane B — controller migration:** `gui/controllers/editor_controller.py`: `JobDraft` fields per decision 2; mutators `set_schedule_kind`, `set_interval(draft, value, unit)`, `set_run_at_load`; `open_existing` loads either variant faithfully (calendar rows/weekdays, interval value/unit normalized per decision 4, `run_at_load`); `_build_schedule` branches by `schedule_kind` — calendar path unchanged, interval path converts `interval_value` × unit (empty/non-integer/zero/negative → `_DraftError("interval", ...)`; converted total delegates to the domain validator, message mapped to `interval`); `tests/unit/gui/test_editor_controller.py` (new-draft defaults, unit conversions, sub-60 rejection with domain message, non-minute load/save fidelity, interval + `run_at_load`, calendar + `run_at_load`, mode-preserved inactive values, plist preview contains `StartInterval`/`RunAtLoad`).
- **Lane C — presenter + inspector:** `gui/presenters/agent_presenter.py`: interval estimate formatting (second-precision occurrence lines), interval anchor wording, exact `PREVIEW_*` constants; `gui/widgets/agent_inspector.py`: consumes the new presenter output (no new formatting); `tests/unit/gui/test_agent_presenter.py` + `test_agent_inspector.py` (exact wording, disabled interval, second precision, calendar regression).
- **Lane D — JobEditor composition:** `gui/widgets/job_editor.py`: stable object names `editor-schedule-kind` (combo), `editor-schedule-stack` (stack), `editor-calendar-schedule` / `editor-interval-schedule` (pages), `editor-interval-value` (QSpinBox-like whole-number field), `editor-interval-unit` (combo), `editor-run-at-load` (checkbox); all new controls wired to draft-change, load, collect, field errors, Validate/Preview/Test Draft/Save; live preview branches by kind (interval builds `IntervalSchedule` from the visible value/unit; invalid/blank → neutral).
- **Lane E — JobEditor tests:** `tests/unit/gui/test_job_editor.py` (object names, page switching preserves per-mode values, visible collection, fixed-clock interval preview with second precision, `interval` field errors, plist preview for interval + login, save/reopen fidelity incl. 61s and 93600s, calendar regressions); `tests/unit/gui/test_main_window.py` helper updates only if the calendar-default first-row name stops keeping it green.
- **Regression gates (no production change expected):** `platform/macos/plist_codec.py`, `plist_reader.py`, `cli/render.py`; plus one new semantic round-trip test for interval + `RunAtLoad` in `tests/unit/platform/test_round_trip.py`.
- **Verification:** `make check` + explicit 100% package coverage + source-size review; docs (README interval authoring + login trigger + interval preview wording, architecture draft contract + interval estimate boundary, development test conventions); version 0.0.16 → 0.0.17 with registry + stale-reference grep.

### Increment 18 — Python Environment Detectors (§58) — DONE (v0.0.18, approved 2026-09-06)
Immutable detector protocol + ordered registry behind the existing `detect_python()` facade; extract current `.venv`/`venv`/current/PATH discovery as the first detector with unchanged priority; result DTOs gain detector provenance and non-fatal notes; filesystem/config-only detectors added one at a time (uv, then Poetry; pyenv, Conda, Pipenv, Homebrew in later increments); no ecosystem executables invoked; candidates remain explicit recommendations; injected filesystem/config readers keep tests host-independent.

**Pinned decisions (approved 2026-09-06):**
1. **Project scope (user decision):** uv and Poetry locate the **nearest** project root by walking ancestor directories from the script's parent (script must be absolute and not a directory, same gate as today). uv marker: `uv.lock` present OR `[tool.uv]` table in `pyproject.toml`. Poetry marker: `poetry.lock` present OR `[tool.poetry]` table in `pyproject.toml`. Walk stops at the first ancestor with the marker. Detectors only inspect `<root>/.venv/bin/python` — no global/managed environment stores, no tool invocation, no shell, no subprocess.
2. **Registry order (behavioral contract):** `default_python_detectors() -> tuple[PythonEnvironmentDetector, ...]` = (core, uv, poetry). Core keeps its exact internal candidate order: `.venv/bin/python` beside script → `venv/bin/python` → current interpreter → PATH `python3`. Global candidate list = core candidates (internal order), then uv, then poetry; a path already contributed by an earlier detector is not duplicated (exact-spelling dedupe, as today) but gains the later detector's provenance.
3. **Merged provenance (user decision):** `InterpreterCandidate` gains `detectors: tuple[DetectorKind, ...]` — the detectors, in registry order, that found the exact path. First discovery keeps placement, path spelling, and the existing `source` value. Default `(DetectorKind.CORE,)` keeps all existing direct constructions working.
4. **CandidateSource unchanged:** no new enum values. uv/Poetry candidates for `<root>/.venv/bin/python` carry `source = CandidateSource.VENV` (they are venvs); ecosystem attribution lives in `detectors` only.
5. **DTOs:**
   - `DetectorKind` (StrEnum, platform layer): `CORE = "core"`, `UV = "uv"`, `POETRY = "poetry"`.
   - `DetectionNote` (frozen pydantic): `detector: DetectorKind`, `message: str`.
   - `PythonDetectionResult` gains `notes: list[DetectionNote] = Field(default_factory=list)` — ordered by detector execution, exact duplicates removed.
   - `DetectionContext` (frozen dataclass): `script: Path`, `current_interpreter: Path`, `path_lookup: Callable[[str], str | None]`, `filesystem: PythonDetectorFilesystem`.
   - `PythonDetectorFilesystem` (Protocol): `exists(path) -> bool`, `is_file(path) -> bool`, `is_dir(path) -> bool`, `is_executable(path) -> bool`, `read_text(path) -> str | None` (None = missing or unreadable). Default `LocalPythonDetectorFilesystem` uses `Path`/`os.access` (no resolution).
   - `DetectorContribution` (frozen dataclass): `candidates: tuple[tuple[Path, CandidateSource], ...] = ()`, `notes: tuple[DetectionNote, ...] = ()`.
   - `PythonEnvironmentDetector` (Protocol): `kind: DetectorKind`, `detect(context) -> DetectorContribution`.
   - Façade: `detect_python(script, *, current_interpreter=None, path_lookup=None, filesystem=None)` — signature extended with `filesystem`; existing callers unchanged. Working-directory rule unchanged (script parent when absolute and not a directory, via `filesystem.is_dir`).
6. **Non-fatal notes (exact wording, tests assert verbatim):**
   - uv, marker found but `<root>/.venv/bin/python` missing/non-file/non-executable: `a uv project was detected, but no usable .venv interpreter is available`
   - poetry, same condition: `a poetry project was detected, but no usable .venv interpreter is available`
   - uv, first `pyproject.toml` encountered during the walk exists but is unreadable or unparseable (stdlib `tomllib`; one such note per detector walk, at most): `pyproject.toml could not be read or parsed; uv configuration was ignored`
   - poetry, same condition: `pyproject.toml could not be read or parsed; poetry configuration was ignored`
   - Notes never raise; a detector's failure to parse never cancels its lock-file marker path or the other detectors.
7. **Recommendation policy:** project-affine candidate = first candidate with `source` in `{VENV, VENV_FALLBACK}` (unchanged rule; ecosystem `.venv` candidates qualify through their source). The duplicated inline selection is replaced by one shared pure helper `project_environment_candidate(detection) -> InterpreterCandidate | None` in the platform layer, used by both `diagnostic_service._rule_interpreter_mismatch` and the diagnostics presenter. No automatic interpreter replacement anywhere; `TestOutcome`/`test_job` flow unchanged.
8. **Presentation (GUI/diagnostics only — user decision, no CLI changes):**
   - New pure presenter helpers in `diagnostics_presenter.py`: `format_python_candidate(candidate) -> str` — `path (source)` when `detectors` is core-only (regression-safe), else `path (source; uv)` / `path (source; uv, poetry)` (ecosystem kinds only, comma-joined, in candidate order); and `format_detection_notes(notes) -> str` — `"\n".join(message)`, empty string when none.
   - `format_python_detection`: candidates rendered via `format_python_candidate`; when `notes` is non-empty the note messages are appended as final lines (after the recommendation line, or after `No candidate interpreters detected.`).
   - `JobEditor._on_script_changed`: combo items use `format_python_candidate`; when `notes` is non-empty the note messages are appended to the base note in `editor-detection-note` (one `\n` between base and notes). Candidate `userData`, **Use** behavior, and working-directory hint unchanged.
   - No new widgets or object names; `diagnostics-python-text` / `editor-detection-note` reused.
9. **Safety boundaries:** no `uv`/`poetry`/shell invocation, no symlink resolution, paths reported unresolved with exact spelling, candidates are recommendations only, GUI never touches the live filesystem directly (detector runs inside the platform layer via the existing service façade).
10. **Size gate:** `python_detection.py` stays a single module; if it would exceed ~450 lines after the split, extract `src/task_scheduler/platform/macos/python_detectors.py` (detectors + registry) instead — report which at closeout.
11. **Verification:** `make check` + explicit 100% package coverage + source-size review; docs (README detection provenance + local-only semantics, architecture detector protocol + registry + notes, development synthetic-project test conventions); version 0.0.17 → 0.0.18 with registry + stale-reference grep.

**Lane plan:**
- Lane A (platform): `python_detection.py` protocol/context/reader/core-extraction/uv/poetry/normalization/façade + `__init__.py` exports + `tests/unit/platform/test_python_detection.py` extensions (fakes for the filesystem protocol; host-independent).
- Lane B (presentation): `diagnostic_service.py` shared-helper delegation + `diagnostics_presenter.py` helpers/notes/affinity + `job_editor.py` combo/notes + tests (`test_diagnostic_service.py`, `test_diagnostics_presenter.py`, `test_job_editor.py`).
- Regression: `test_task_command_service.py` / `test_editor_controller.py` delegation tests must stay green unchanged; no CLI changes.

### Increment 19 — Expanded Diagnostics (§60)

**Pinned decisions (approved 2026-09-06):**

1. **Keep the direct-test engine and its deterministic ordering.** `evaluate_diagnostics(job=None, *, process=None, spec_argv0=None, detection=None)` keeps its exact legacy signature, its existing seven codes (`executable_missing`, `script_missing`, `working_directory_missing`, `permission_denied`, `relative_executable`, `interpreter_mismatch`, `module_not_found`), and their order. One new code, `executable_not_found_runtime`, is inserted immediately after the `permission_denied` position (i.e. between `permission_denied` and `relative_executable`) and fires only when the process launch failure kind is `NOT_FOUND` and the static executable check passed (file exists) — static and runtime evidence never yield two findings.
2. **Typed contexts, not unstructured optional arguments.** New frozen slots dataclasses in `application/diagnostic_models.py`: `PreflightContext(job, protected_findings=(), architecture_finding=None)`, `DirectTestContext(job, process, spec_argv0=None)`, `PythonEnvironmentContext(job, detection)`, `LifecycleContext(label, action, result)` (`result: InstallResult | LaunchctlResult | LaunchAgentStatus | UninstallResult`; `action` is the lifecycle action string, e.g. `"install"`), `LogContext(job, logs: JobLogs)`, `InspectionContext(path, parsed: ParsedLaunchAgent)`. Union alias `DiagnosticContext`.
3. **Report model.** `Diagnostic` gains `evidence_state: EvidenceState | None = None` (default None = plain confirmed finding; JSON/serialization compatible). `EvidenceState` StrEnum: `CONFIRMED` / `NOT_PROVABLE` / `UNAVAILABLE` (UNAVAILABLE is represented by rule silence — a finding is never emitted with that state; the probe could not establish the fact, so no claim is made). `DiagnosticSource` StrEnum: `PREFLIGHT` / `DIRECT_TEST` / `PYTHON_ENVIRONMENT` / `LIFECYCLE` / `LOGS` / `PLIST`. `DiagnosticGroup(source, diagnostics: tuple[Diagnostic, ...])` and `DiagnosticReport(groups: tuple[DiagnosticGroup, ...])` are frozen slots dataclasses; `DiagnosticReport.all` flattens in group order.
4. **Grouped evaluation.** `evaluate_diagnostic_report(*contexts) -> DiagnosticReport` is pure, accepts contexts in any order, and returns groups in the pinned order: preflight, direct test, lifecycle, logs, python environment, plist; empty groups are omitted. Within-group rule order is pinned per group (preflight: executable_missing, script_missing, working_directory_missing, permission (static), relative_executable, protected_path, architecture_mismatch; direct test: permission (runtime, only when static did not fire), executable_not_found_runtime, module_not_found; python environment: interpreter_mismatch; lifecycle: bootstrap_failure; logs: log_path_unreadable stdout-then-stderr; plist: malformed_plist, invalid_plist_label). Legacy flat order = preflight + direct-test + python-env findings re-ordered to the legacy sequence of §1.
5. **New rules (low-risk first).**
   - `executable_not_found_runtime` ERROR, direct test (per §1).
   - `module_not_found` broadened: patterns `ModuleNotFoundError`, `ImportError`, `No module named`, `cannot import name` (substrings of stderr); code unchanged, title becomes "Python import failure in process output".
   - `log_path_unreadable` WARNING, logs: one finding per configured stream with a read error, naming stream, path, and the reader error.
   - `bootstrap_failure` ERROR, lifecycle: fires only for `InstallResult` whose bootstrap phase exited non-zero; names the label and exit code. Non-bootstrap launchctl failures (bootout/uninstall/kickstart) are intentionally not diagnosed (they already surface in the result dialog headline + stderr).
   - `malformed_plist` ERROR, plist: `ParsedLaunchAgent.status` is INVALID; description joins parser warnings.
   - `invalid_plist_label` ERROR, plist: fires when `raw` is a non-empty dict (the file decoded as a plist dict) and `raw.get("Label")` is missing, not a string, empty, or raises `validate_label`; when `raw` is empty (undecodable) the rule stays silent and `malformed_plist` covers the file.
6. **Best-effort probes (platform layer, `platform/macos/diagnostic_probes.py`).** `probe_protected_paths(paths, *, home=None)` (pure path arithmetic, no FS access) returns `ProtectedPathFinding(path, root)` for each configured path under an injectable-home root list: `home`/Desktop|Documents|Downloads|Movies|Music|Pictures, `home/Library/Mobile Documents`, `/Users/Shared`. `probe_executable_architecture(executable, *, machine=None)` reads at most 32 bytes (thin Mach-O magics `FEEDFACF`/`FEEDFACE`/`CEFAEDFE`, fat `CAFEBABE`/`BEBAFECA` — the magic bytes are always read big-endian, `BEBAFECA` dispatching to a little-endian entry read; within the 32-byte read the first fat_arch entry is the only one parseable, which is the one that matters for the host-match check) and returns `ArchitectureFinding(path, declared, host)` only when no declared cputype matches the host cputype (`platform.machine()`: arm64 → 0x0100000C, x86_64 → 0x07000003; any other machine → None; 32-bit headers always mismatch on arm64 hosts); never raises, returns None on missing/unreadable/short/non-Mach-O input. `DiagnosticProbes` protocol + `LocalDiagnosticProbes` (home = `Path.home()`, machine = `platform.machine()`) are injectable everywhere.
   - `protected_path` WARNING, preflight, `evidence_state=NOT_PROVABLE`: wording states macOS *may* restrict the location and that this app cannot confirm launchd's access decision; suggested action moves the path or grants Full Disk Access.
   - `architecture_mismatch` WARNING, preflight, `evidence_state=CONFIRMED`: wording states the header declares X on host Y, launchd *may* not start it without translation, and this app cannot confirm Rosetta behavior.
7. **Probe-fed preflight.** `PreflightContext` carries precomputed probe findings (the engine stays pure). Probed paths, in order: executable, script (Python only), working directory, stdout path, stderr path (None entries skipped). `DirectTestService(runner, *, probes=None)` (default `LocalDiagnosticProbes`) and `TaskCommandService` (new optional `probes` constructor parameter, default `LocalDiagnosticProbes`) compute them; `bootstrap.build_services()` is unchanged.
8. **Compatibility.** `DirectTestResult` gains `report: DiagnosticReport` (empty-report default factory); `diagnostics` stays the legacy flat list, so CLI rendering and existing consumers are unchanged. `Diagnostic`/`DiagnosticSeverity` and the report models live canonically in `diagnostic_models.py` (imported from `diagnostic_service.py` under `TYPE_CHECKING` only, keeping the dependency graph acyclic); `diagnostic_service.py` does **not** re-export them — the five existing import sites (`cli/render.py`, `gui/presenters/diagnostics_presenter.py`, and three test files) import from `diagnostic_models` instead, all updated within this increment.
9. **Façade methods (all pure, no new I/O):** `diagnostic_report_for(job, *, detection=None, logs=None) -> DiagnosticReport` (preflight + optional python-environment + optional logs groups), `log_diagnostics_for(job, logs) -> tuple[Diagnostic, ...]`, `lifecycle_diagnostics(label, action, result) -> tuple[Diagnostic, ...]`, `inspection_diagnostics(path, parsed) -> tuple[Diagnostic, ...]`.
10. **GUI grouping.** `LogsOutcome` gains `diagnostics: tuple[Diagnostic, ...] = ()` (controller fills it via `log_diagnostics_for`, failure → `()`); `LifecycleOutcome` gains `diagnostics` (controller fills it via `lifecycle_diagnostics`, failure → `()`); `InspectOutcome` gains `diagnostics` (discovery controller fills it via `inspection_diagnostics`, failure → `()`). New pure presenter helpers in `diagnostics_presenter.py`: `SOURCE_TITLES` (preflight → "Configuration checks", direct test → "Direct test", python environment → "Python environment", lifecycle → "Lifecycle", logs → "Logs", plist → "Plist"), `format_evidence(state)`, `format_diagnostic_block(diagnostic)` (severity/title + evidence suffix, description, "Suggested: …"), `format_report(report)` (group headings `== <title> ==`, "No diagnostics." when empty), `format_log_diagnostics` / `format_lifecycle_diagnostics` (single-group rendering, empty → ""). `DiagnosticLogsPanel` renders `format_report(result.report)` in the diagnostics pane and appends the logs group when a log read produced findings (both cleared to their neutral state on failed outcomes); initial pane text becomes "No diagnostics.". `LifecycleResultDialog` shows a Diagnostics group (object names `lifecycle-result-diagnostics` / `-text`) only when the outcome carries findings. `AgentInspector.show_agent` gains `*, diagnostics=()` and appends `agent_presenter.format_inspection_diagnostics(...)` (self-contained block formatting incl. evidence suffix) to the Warnings section; `MainWindow` passes `result.diagnostics` through. `TEST_LIMITATION_TEXT` and all existing wording stay verbatim.
11. **CLI.** `mactask test` renders the expanded flat diagnostics through the unchanged `format_test`/`format_diagnostics` path. `mactask inspect` appends a `diagnostics:` section (via `format_inspect(report, diagnostics=())`) when the deployed plist parse is not SUPPORTED. `mactask install` appends lifecycle diagnostics on stderr when the bootstrap phase failed. `logs`/other lifecycle commands are unchanged (their failures produce no new findings).
12. **Safety boundaries.** Probes never invoke tools, resolve symlinks, or write anything; architecture probe reads a bounded header only; protected-path probe is pure string/path arithmetic; GUI never imports `cli/`/`storage/` and gains no new subprocess/`os.environ` access; diagnostics remain recommendations only.
13. **Size gate.** `diagnostic_service.py` stays under ~500 lines via the `diagnostic_models.py` split; `diagnostic_probes.py` expected ~180 lines; review both at closeout.
14. **Verification.** `make check` + explicit 100% package coverage; test/code ratio cap (tests ≤ 75% of production) re-checked at closeout; docs (README expanded-diagnostics section incl. evidence states, architecture engine/probes/façade contracts, development fake-probe and Mach-O-fixture conventions); version 0.0.18 → 0.0.19 with registry + stale-reference grep.

**Lane plan:**
- Lane A (core): `platform/macos/diagnostic_probes.py` + exports, `application/diagnostic_models.py`, `diagnostic_service.py` rewrite (rules + engine + legacy wrapper), `test_service.py` report + probes, `task_command_service.py` façade methods, `tests/fakes.py` `FakeDiagnosticProbes`, tests (`test_diagnostic_probes.py`, `test_diagnostic_service.py`, `test_test_service.py`, `test_task_command_service.py`).
- Lane B (GUI): controller DTO additions (`diagnostics_controller`, `lifecycle_controller`, `discovery_controller`), presenter helpers, `diagnostic_logs_panel.py` grouped rendering, `lifecycle_result.py` diagnostics group, `agent_inspector.py` + `agent_presenter.py` inspection diagnostics, `main_window.py` pass-through, tests (`test_diagnostics_controller.py`, `test_lifecycle_controller.py`, `test_discovery_controller.py`, `test_diagnostics_presenter.py`, `test_diagnostic_logs_panel.py`, `test_lifecycle_result.py`, `test_agent_inspector.py`, `test_main_window.py`).
- Lane C (CLI + docs): `cli/render.py` (`format_inspect` diagnostics, lifecycle section), `cli/app.py` (inspect/install wiring), `test_cli.py`/`test_render.py`, README + architecture + development docs.
- Regression: legacy `evaluate_diagnostics` ordering test and every existing diagnostics/presenter/CLI test stay green unchanged (new code appended, not rewritten, where the legacy contract is asserted).

### Increment 20 — Application-Observed Execution History (§59)
Stdlib `sqlite3` append-only repository in `storage/` beside the JSON catalog; event schema per decision 8; events recorded at application-service boundaries (`test_job`, `run_now`, explicit `status` observations, aggregate diagnostic result) so CLI and GUI behave identically; one direct-test event plus one aggregate diagnostic-result event per test; bounded read-only queries; `mactask history <label> --limit N`; Qt-free controller + read-only GUI history panel; corrupt/unavailable database reported safely without affecting scheduler operations; never infer scheduled executions from logs or launchctl state.

**User decisions (approved 2026-09-07):**
1. **Event scope — plan scope only:** direct tests, manual runs (`run_now`), explicit `status` observations, and one aggregate diagnostic-result event per direct test. Lifecycle operations (install/reinstall/uninstall/enable/disable) are out of scope for this increment.
2. **Write failures are best-effort and non-blocking:** a failed history append never changes the test/run/status result, is not surfaced by the operation itself, and is discoverable only via the history query, which reports the safe unavailable state.

**Pinned contract (settled before implementation; every lane builds against it):**
1. **Models (`application/history_models.py`, written serially at stage 0, shared by all lanes):**
   - `HistoryEventKind` StrEnum: `DIRECT_TEST = "direct_test"`, `MANUAL_RUN = "manual_run"`, `STATUS_OBSERVATION = "status_observation"`, `DIAGNOSTIC_RESULT = "diagnostic_result"`.
   - `HistoryOutcome` StrEnum: `SUCCESS = "success"`, `FAILURE = "failure"`, `OBSERVED = "observed"`.
   - `HistoryEvent` (frozen slots dataclass): `created_at: datetime` (tz-aware UTC), `job_id: UUID`, `label: str`, `kind: HistoryEventKind`, `outcome: HistoryOutcome`, `exit_code: int | None = None`, `duration_seconds: float | None = None`, `loaded: bool | None = None`, `diagnostic_codes: tuple[str, ...] = ()`. Metadata only — never stdout/stderr, environment values, raw launchctl output, or free text (decision 8).
   - `HistoryReadResult` (frozen slots dataclass): `events: tuple[HistoryEvent, ...] = ()` (newest first), `error: str | None = None`.
   - `HistoryRepository` Protocol (port): `append(event: HistoryEvent) -> None` (best-effort, never raises); `read(job_id: UUID, *, limit: int) -> HistoryReadResult` (storage failures become a safe `error`, never exceptions).
   - `HISTORY_UNAVAILABLE = "execution history unavailable"` — the single safe error string, used everywhere.
2. **Event semantics (recorded only at `TaskCommandService` boundaries, after the normal result is produced; results are never modified by recording):**
   - `test_job` (and `test(label)`, which delegates): only when `self._jobs.find(validated.label)` resolves — unsaved drafts record nothing. Exactly two events, in order: (a) `DIRECT_TEST` — `SUCCESS` when `process.exit_code == 0`, else `FAILURE`; `exit_code = process.exit_code` (launch failure → `FAILURE` with `exit_code=None`); `duration_seconds = process.duration.total_seconds()`; `loaded=None`; `diagnostic_codes=()`. (b) `DIAGNOSTIC_RESULT` — `SUCCESS` when `result.report.all` is empty, else `FAILURE`; `exit_code=None`; `duration_seconds=None`; `loaded=None`; `diagnostic_codes = tuple(d.code for d in result.report.all)` (report's pinned group order).
   - `run_now`: `MANUAL_RUN` — `SUCCESS` when `process.exit_code == 0`, else `FAILURE`; `exit_code = process.exit_code`; `duration_seconds = process.duration.total_seconds()`; `loaded=None`; `codes=()`.
   - `status`: only successful façade calls (unknown labels raise before recording; `inspect`/`inspect_discovered`/`list_agents` never record): `STATUS_OBSERVATION` — `OBSERVED`; `exit_code = status.process.exit_code`; `duration_seconds = status.process.duration.total_seconds()`; `loaded = status.loaded` (True/False/None); `codes=()`.
   - Timestamps: the service stamps `datetime.now(timezone.utc)` (no clock injection; tests assert UTC-ness, not wall-clock values).
3. **Repository (`storage/execution_history_repository.py`, lane 1A):** `ExecutionHistoryRepository(path: Path)` — stdlib `sqlite3` only; the constructor opens the database and creates the schema; any open/schema failure marks the store unhealthy (later `append`s are no-ops, `read`s return the unavailable error) — the constructor never raises. Append-only table `execution_history`: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `created_at TEXT` (UTC ISO-8601), `job_id TEXT` (UUID), `label TEXT`, `kind TEXT`, `outcome TEXT`, `exit_code INTEGER` (NULL), `duration_seconds REAL` (NULL), `loaded INTEGER` (NULL/0/1), `diagnostic_codes TEXT` (JSON array), plus an index on `(job_id, id)`; the repository exposes no UPDATE/DELETE. `read` is scoped by `job_id` with `ORDER BY id DESC LIMIT ?` (rowid as tie-breaker); `limit` outside 1–100 raises `ValueError`; `sqlite3.Error`/`OSError` convert to `HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)`. `default_history_path() -> Path` = `default_job_catalog_root().parent / "history.sqlite3"` (sibling of `jobs/`, in Application Support).
4. **Service integration (lane 1B):** `TaskCommandService.__init__` gains keyword `history: HistoryRepository | None = None` (default `None` = no recording, unchanged behavior); `bootstrap.build_services()` wires `ExecutionHistoryRepository(default_history_path())`. New façade `history(label: str, *, limit: int = 50) -> HistoryReadResult`: validates limit (1–100, `ValueError`), resolves the label through `_require_managed` (`JobNotFoundError` when unknown), returns `self._history.read(job.id, limit=limit)`; with no repository wired it returns `HistoryReadResult(events=(), error=HISTORY_UNAVAILABLE)`. `FakeTaskWorld` gains a real temp-rooted `ExecutionHistoryRepository` (`tmp_path / "history.sqlite3"`) wired into the service so service tests read back rows with no fake.
5. **CLI (lane 1C):** `mactask history <label> --limit N` (default 50). Unknown label → exit 2 (`JobNotFoundError` message, the existing label-command pattern); limit outside 1–100 → exit 2 usage failure; `result.error` → message on stderr + exit 1; zero events → `No history found.` on stdout + exit 0; otherwise one line per event, newest first, via pure `format_history(result: HistoryReadResult, label: str) -> str` in `cli/render.py`: `<ts> <kind> <outcome> [exit=<code>] [duration=<s>s] [loaded=<yes|no|unknown>] [codes=<a,b>]` — `<ts>` = `created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`, `duration` with 3 decimals, `loaded` present only for `status_observation` events, `codes` present only when non-empty (comma-joined, no spaces), optional fields omitted (never rendered empty), single spaces, no header line.
6. **GUI (lane 1D):** Qt-free `gui/controllers/history_controller.py` — `HistoryController(service)` with synchronous `history_for(label: str) -> HistoryOutcome` (frozen dataclass `label: str`, `events: tuple[HistoryEvent, ...]`, `error: str | None`; mirrors the established synchronous fast-read pattern of `read_logs` — no worker thread; `JobNotFoundError` captured into `error`). Pure `gui/presenters/history_presenter.py`: `HISTORY_DISCLOSURE = "Records only what this application observed (tests, manual runs, status checks). It does not prove launchd ran the task on schedule."`, `HISTORY_EMPTY = "No execution history recorded for this task."`, `HISTORY_NOT_APPLICABLE = "Execution history is only recorded for managed tasks."`, `format_event_time(event)` (local `%Y-%m-%d %H:%M:%S`), `format_event_kind(kind)` ("Direct test" / "Manual run" / "Status check" / "Diagnostics"), `format_event_outcome(outcome)` ("Succeeded" / "Failed" / "Observed"), `format_event_details(event)` (parts joined with `" · "`: `exit code <n>`, `<d>s`, `loaded` / `not loaded` / `load state unknown`, `codes: a, b`). `gui/models/history_table_model.py`: `HistoryTableModel` over a `list[HistoryEvent]` (newest first), columns Time / Type / Result / Details, read-only. `gui/widgets/history_panel.py`: `HistoryPanel` with object names `history-panel`, `history-disclosure`, `history-table`, `history-state-text`, `history-refresh`; `show_history(outcome)` — error → state text shows the error string verbatim with the table hidden; empty → `HISTORY_EMPTY` with the table hidden; otherwise the table model is populated; a Refresh button emitting `refreshRequested`. `MainWindow` gains the fifth controller and places the panel at the bottom of the right-pane splitter (below `DiagnosticLogsPanel`); selecting a managed row (saved-only or discovered-managed) loads the most recent 50; external/invalid rows show `HISTORY_NOT_APPLICABLE` (no query); after a successful direct test or manual run of the selected task the history is re-queried.
7. **Docs (lane 1E):** README gains a short Execution-history section (what is recorded, the CLI command, the GUI panel, the disclosure text, what is deliberately not stored); `docs/architecture.md` gains a section covering the port/adapter split, the table schema, the service-boundary recording rule, best-effort write semantics, the read path, and the metadata-only data-minimization stance; `docs/development.md` gains guidance: service tests use the real temp-rooted repository in `FakeTaskWorld` (no fake repository), storage tests use `tmp_path` directly, event fixtures pass explicit `created_at` values, the corrupt-database fixture writes garbage bytes to a `.sqlite3` path, and unit tests never touch a host database.

**Lane plan:**
- **Stage 0 (build, serial):** `application/history_models.py` exactly per contract item 1; ruff + mypy + pytest green; committed before any lane starts.
- **Lanes 1A–1E (five `faster` subagents, dispatched in parallel, no git in lanes):**
  - **1A persistence:** `storage/execution_history_repository.py` + `default_history_path` + `storage/__init__.py` export + `tests/unit/storage/test_execution_history_repository.py` (uses `tmp_path` directly).
  - **1B application:** `task_command_service.py` (history kwarg, `_record_*` helpers, `history()` façade) + `bootstrap.py` wiring + `tests/fakes.py` (`FakeTaskWorld` gains the real temp-rooted repository) + service history tests.
  - **1C CLI:** `format_history` in `cli/render.py` + `history` command in `cli/app.py` + CLI tests (exit codes 0/1/2, line formatting).
  - **1D GUI:** the four new GUI files + `main_window.py`/`gui/app.py` wiring + GUI tests (controller, presenter, model, panel, wiring).
  - **1E docs:** README, `docs/architecture.md`, `docs/development.md` per item 7.
- **Integration & closeout (build, serial):** review every lane diff against the contract, one commit per lane, `make check` + explicit 100% package coverage, source-size review, test/code ratio report, finalize SUMMARY/TODOS/PLAN, grep for stale version references, commit, push.

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
7. Update every registry location in `VERSIONS_LOCATIONS.md`.
8. `grep` the repo for the old version to catch missed references.
9. Update `PROJECT.md`, `TODOS.md`, `SUMMARY.md`, and `PLAN.md` in the same commit.
10. Update README and architecture/development documentation when user-visible behavior, commands, dependencies, safety guarantees, or package behavior changes.
11. Commit only verified changes and push the increment version upstream.
