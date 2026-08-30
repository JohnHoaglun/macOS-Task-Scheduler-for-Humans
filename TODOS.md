# TODOS.md (v0.0.9)

## Crawl Increment 0 — Project Foundation (DONE)
- [x] Create project directory
- [x] Integrate upstream repo (sched_dev_opencode branch)
- [x] Add LICENSE file
- [x] Create pyproject.toml
- [x] Create Makefile
- [x] Set up package structure (src/task_scheduler/)
- [x] Configure pytest, ruff, mypy
- [x] Create .gitignore
- [x] `make check` passes

## Crawl Increment 1 — Domain Model (DONE)
- [x] JobDefinition, Command, Schedule, Environment, Logging models
- [x] JSON serialization (schema-versioned JsonJobRepository)
- [x] Tests: valid/invalid jobs, schema version, round-trip

## Crawl Increment 2 — plist Generator (DONE)
- [x] JobDefinition → LaunchAgent plist (PlistCodec)
- [x] Label, ProgramArguments, WorkingDirectory, EnvironmentVariables, StartCalendarInterval, StandardOutPath, StandardErrorPath, Disabled
- [x] Golden tests (JSON + plist bytes)

## Crawl Increment 3 — plist Reader (DONE)
- [x] LaunchAgent parsing (parse_bytes/parse_path, never raises)
- [x] Classify: supported/partially_supported/invalid
- [x] 14 reader fixtures + round-trip tests; 123 tests, 100% coverage

## Crawl Increment 4 — Python Detection (DONE)
- [x] `python_detection.py`: `CandidateSource`, `InterpreterCandidate`, `PythonDetectionResult`, `EnvironmentDifference`
- [x] `detect_python`: .venv / venv / current / PATH-python3 candidates, executable-file qualification, dedupe, injection points
- [x] Working-directory recommendation (script parent, absolute only)
- [x] `compare_environments`: terminal_only / scheduled_only / different
- [x] Exports via `platform/macos/__init__.py`
- [x] Tests: tmp_path fixtures for all candidate shapes + environment comparison
- [x] `make check` green, 140 tests, 100% coverage, file-size review

## Crawl Increment 5 — Direct Test Runner (DONE)
- [x] `process_runner.py`: `CommandSpec`, `ProcessResult`, `ProcessLaunchFailure`, `ProcessRunner` protocol, `SubprocessRunner` (injectable clock)
- [x] `command_argv` in `domain/command.py`; `PlistCodec` refactored onto it
- [x] `application/test_service.py`: `DirectTestService` (exact env, no timeout, no mutation)
- [x] `application/diagnostic_service.py`: 7 structured rules (positive + negative tests each)
- [x] `tests/fakes.py`: `FakeProcessRunner`, `FakeClock`
- [x] Runner/test-service/diagnostic tests; host-independent (`tmp_path`)
- [x] `make check` green, 177 tests, 100% coverage, file-size review

## Crawl Increment 6 — LaunchAgent Storage (DONE)
- [x] `filesystem.py`: `LaunchAgentFilesystem` protocol + `LocalFilesystem` (read/list/create_root/create_exclusive/remove_file)
- [x] `launch_agent_store.py`: `LaunchAgentStore` (write create-only via atomic exclusive link, remove idempotent, discover parsed records), `DiscoveredLaunchAgent`, `default_launch_agents_root`, label validation (no `/`, `.`/`..`)
- [x] Exports via `platform/macos/__init__.py`
- [x] `tests/fakes.py`: `FakeFilesystem` (in-memory, failure injection)
- [x] `test_launch_agent_store.py`: write/refusal/cleanup, label rejection, remove idempotence, discovery (missing root, sorting, supported/invalid/partial, ignore non-plists, no mutation)
- [x] `make check` green, 208 tests, 100% coverage, file-size review

## Crawl Increment 7 — launchctl Adapter (DONE)
- [x] `launchctl.py`: `LaunchctlAction`, `LaunchctlResult`, `LaunchAgentStatus`, `LaunchAgentBackend` (install/uninstall/status/enable/disable/trigger via `ProcessRunner`, user `gui/<uid>` domain, `/bin/launchctl`)
- [x] Shared public `validate_label` in `launch_agent_store`; backend + store both use it
- [x] Exports via `platform/macos/__init__.py`
- [x] `tests/fakes.py`: `FakeProcessRunner` ordered `results` queue
- [x] `test_launchctl.py`: exact argv/env/cwd, storage-before-bootstrap ordering, retain-on-failure compensation, status mapping (True/False/None), label rejection
- [x] `tests/integration/test_launchctl.py`: `MACTASK_ALLOW_SYSTEM_TESTS=1` guard, unique UUID label, unconditional cleanup
- [x] `integration` pytest marker + `addopts -m 'not integration'`; `make integration` target
- [x] `make check` green, 243 unit tests, 100% coverage, file-size review, default-run skip verified

## Crawl Increment 8 — CLI (DONE)
- [x] Typer runtime dependency + `mactask` console-script entry point
- [x] `application/job_service.py`: managed job catalog (`JobService`, `JobNotFoundError`, `JobConflictError`, `default_job_catalog_root`)
- [x] `platform/macos/log_reader.py` + `application/log_service.py`: read-only stdout/stderr readers
- [x] `application/task_command_service.py`: shared `TaskCommandService` façade (12 operations)
- [x] `cli/` package: Typer app factory, 12 commands, plain-text renderers, exit codes 0/1/2
- [x] Unit tests: job service, log service, command service, CLI commands (CliRunner + fakes)
- [x] Docs: README CLI usage + exit codes; architecture/development doc updates
- [x] `make check` green, 328 tests, 100% coverage, file-size review; bumped 0.0.7 → 0.0.8

## Crawl Increment 9 — GUI Read/Discovery (DONE)

### Shared Foundation
- [x] Add PySide6 runtime dependency to pyproject.toml
- [x] Add pytest-qt development dependency
- [x] Add offscreen Qt test configuration (`qt_api = "pyside6"`, `QT_QPA_PLATFORM=offscreen` in tests/conftest.py)
- [x] Extract build_services() from cli/app.py into task_scheduler/bootstrap.py:build_services()
- [x] CLI build_services() imports the shared root
- [x] Add GUI entry point: task_scheduler/gui/app.py:main (`mactask-gui` script)
- [x] Tests proving CLI and GUI composition roots receive the same service graph (tests/unit/test_bootstrap.py + gui composition tests)

### Application-Service Work
- [x] Add DiscoveredInspectReport DTO (path, parsed, managed, status)
- [x] Add TaskCommandService.inspect_discovered(path) — root containment, read-only, never mutates
- [x] Pin classification display mapping: Managed/External/Invalid (invalid wins over managed)
- [x] Add presenters for classification and field display labels (pure Python, no Qt)
- [x] Unit tests: inspect_discovered() root containment, read-only behavior, missing root, malformed plist, invalid/no-label status, presentation formatting with DTO fixtures

### GUI — Main Window
- [x] Create src/task_scheduler/gui/ package structure (app.py, main_window.py, controllers/, models/, presenters/, widgets/)
- [x] Create QApplication entry point (gui/app.py)
- [x] Create two-pane main window: left list (QTreeView), right inspector
- [x] Top-level Refresh action (File menu, Cmd+R shortcut)
- [x] Empty state when no user LaunchAgents exist ("No tasks found.")
- [x] Error state when discovery fails (inspector error text + status bar, table emptied)

### GUI — List/Model
- [x] AgentTableModel: QAbstractTableModel mapping list[AgentListing]
- [x] Columns: name/label, command summary, schedule summary, classification, parse-support
- [x] Refresh populates rows from list_agents() via controller; selection preserved by path across refreshes (fallback row 0)

### GUI — Inspector
- [x] AgentInspector widget: read-only managed/external/invalid detail rendering
- [x] Overview section: name, label, classification, plist path, enabled state, loaded status
- [x] Command section: full command line, working directory
- [x] Schedule section: plain-language text; raw plist fields in Advanced
- [x] Environment section: configured values (if parsed)
- [x] Warnings section: unsupported keys and parser warnings (always visible for partial/invalid)
- [x] Advanced section: raw plist representation (read-only XML)
- [x] Display mapping lives in pure presenters, not widgets

### Widget Tests (pytest-qt)
- [x] Main window loads with fake/injected services (startup smoke)
- [x] Refresh renders discovered rows
- [x] Selecting managed/external/invalid agents updates the inspector
- [x] External/invalid jobs have no edit/lifecycle controls (read-only inspector only)
- [x] Warnings and raw plist details appear for partial/invalid jobs
- [x] Empty state and service-failure state render correctly

### Documentation
- [x] README.md: GUI availability, launch instructions, discovery scope, read-only external-job policy
- [x] docs/architecture.md: GUI package boundary and shared composition root
- [x] docs/development.md: PySide6/Qt test setup and headless test requirements
- [x] PROJECT.md: Increment 9 complete; next: 10
- [x] TODOS.md: mark 9 complete, record verification
- [x] SUMMARY.md: Increment 9 scope, service contract changes, test total, coverage, lint/mypy
- [x] PLAN.md: Increment 9 completed, focus moved to Increment 10
- [x] Version: 0.0.8 → 0.0.9

### Verification
- [x] `make check` green: 413 tests, 100% line coverage (whole package), ruff + mypy strict clean

## Crawl Increment 10 — GUI Job Creation, Edit, Save, and Validation (IN PROGRESS — plan approved, pinned decisions in PLAN.md)

### Application — Factory and Save Policy (JobService)
- [ ] `new_managed_job(name, command, schedule, *, job_id=None) -> JobDefinition`: schema_version=1, UUID (generated or injected), label `io.github.macos-task-scheduler.user.<slug>-<8-hex>`, enabled=True, working_directory=script.parent for PythonCommand only, default log paths under `~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/`; no directory creation, no file writes
- [ ] Label slug policy: lowercase ASCII, non-alphanumeric runs → `-`, edge dashes trimmed, blank → `task`
- [ ] `JobService.save(job) -> Path`: writes `<job.id>.json`, overwrites only the same immutable id, `JobConflictError` on a label owned by a different id; `import_job` stays create-only
- [ ] Tests: UUID generate/inject, label determinism + slug fallback, per-command-type working-directory default, log-path defaults, save new/existing/conflict/invalid label/immutable ID, no deployment side effects

### Application — In-Memory Facade (TaskCommandService)
- [ ] `new_managed_job(...)` delegating to the JobService factory
- [ ] `validate_job(job) -> JobDefinition` (re-validate via `model_validate`)
- [ ] `generate_plist_for(job) -> str` (validate first, PlistCodec, no temporary JSON)
- [ ] `save_managed_job(job) -> Path` (catalog only: no plist, no launchctl, no log directories)
- [ ] `detect_python(script: Path) -> PythonDetectionResult` (delegate to platform detection)
- [ ] `resolve_managed_job(label: str) -> JobDefinition` (JobNotFoundError when absent)
- [ ] Tests via FakeTaskWorld: each method, save catalog-only assertions (LaunchAgent root + process runner untouched), resolve-missing error
- [ ] `make check` green + 100% package coverage after the application layer

### GUI — Pure Editor Controller
- [ ] `gui/controllers/editor_controller.py`: Qt-free draft DTO (uuid, name, label + auto-label flag, enabled, command kind + fields, argument rows, time, weekdays, working dir + auto flag, env rows, stdout/stderr paths)
- [ ] Frozen outcomes: validate (job or field errors), preview (job + XML or errors), save (path + job or error), detect (candidates + recommendation or error); errors mapped to stable field names
- [ ] Retained draft UUID; auto defaults (label, script working dir, log paths) applied only while the corresponding fields remain automatic
- [ ] `tests/unit/gui/test_editor_controller.py`: DTO→domain conversion, field-error mapping, auto vs manual fields, preview gating, save non-deployment, detection outcomes

### GUI — Job Editor Dialog
- [ ] `gui/widgets/row_table.py`: generic add/remove row table (1 column for arguments, 2 for environment key/value)
- [ ] `gui/widgets/job_editor.py` (QDialog, stable objectNames): General (name, label, type selector), Command (stacked Python/Shell/Executable fields + argument table, no shell parsing), Schedule (time + weekday checkboxes + sleep/wake disclaimer), Working Directory (editable + recommendation), Environment (key/value table), Logging (optional stdout/stderr absolute paths + explanation), Advanced (immutable UUID + read-only XML preview)
- [ ] New Task: blank schedule, no command paths — draft invalid until required fields + time + ≥1 weekday
- [ ] Validate action + before-Save validation; field-level errors + summary; Save initially enabled, disabled only after a known-invalid result, re-enabled when the draft changes; preview only from the validated canonical job
- [ ] Python script selection triggers detection: candidates in priority order with source, selecting a candidate populates the interpreter field, detection failure informative, manual absolute interpreter always allowed
- [ ] `tests/unit/gui/test_job_editor.py`: all pinned widget scenarios (forms, argument rows, schedule validation, candidates, working directory, env add/remove, logging disabled by clearing, preview, Save toggle on invalid states, save through fakes only)

### GUI — Main Window Integration
- [ ] `new_task_action` + `edit_managed_task_action` in the File menu; editor controller constructed in the `gui/app.py` composition
- [ ] Edit enabled only for a selected managed row with a valid parsed label; resolves the catalog job by label; external/invalid rows stay read-only
- [ ] After successful save: refresh discovery preserving selection by path; no lifecycle calls
- [ ] Extend `tests/unit/gui/test_main_window.py`: New Task action, Edit gating by classification, save-then-refresh, no lifecycle/process calls

### Closeout
- [ ] `make check` + explicit whole-package 100% coverage + offscreen GUI import smoke
- [ ] README.md: creating, editing, validating, saving, Python detection, schedule limits, log defaults, "Save does not deploy"
- [ ] docs/architecture.md: draft/controller/service contracts and managed JSON lifecycle
- [ ] docs/development.md: editor test conventions, offscreen Qt, fake service setup
- [ ] PROJECT.md / TODOS.md / PLAN.md / SUMMARY.md updates
- [ ] Version 0.0.9 → 0.0.10 (registry + stale-reference grep), commit + push

## Crawl Increment 11 — GUI Installation and Lifecycle (PENDING)

### Application-Service Work — Lifecycle Contracts
- [ ] Add TaskCommandService.install(job: JobDefinition) -> InstallResult
- [ ] Add TaskCommandService.reinstall(label: str) -> InstallResult
- [ ] Install: save/import managed JSON, create deployment plist, bootstrap the agent
- [ ] Reinstall: resolve saved managed JSON, safely replace deployed plist, reload/bootstrap
- [ ] Uninstall: boot out LaunchAgent, remove matching managed catalog record after successful bootout
- [ ] Enable/Disable/Run Now/Status: remain label-based; GUI gating requires a managed selected agent
- [ ] Every lifecycle operation preserves ProcessResult

### Application-Service Work — Reinstall Transaction
- [ ] Resolve managed job and validate label
- [ ] Preserve or stage the existing plist safely
- [ ] Boot out the installed job if required
- [ ] Write the new generated plist
- [ ] Bootstrap the new plist
- [ ] If deployment fails, retain diagnostic artifacts and return actionable failure result
- [ ] Do not claim rollback succeeded unless verified
- [ ] Do not silently overwrite an existing plist
- [ ] Unit tests: install/reinstall validation, managed-only gating, replacement ordering, failure at each phase, catalog retention/removal, raw process output retention
- [ ] Add minimal store/backend capability for explicit replace/reload path + failure behavior tests

### GUI — Actions
- [ ] Enable Install, Reinstall, Uninstall, Enable, Disable, Run Now only when a managed task is selected
- [ ] Clearly distinguish: Saved but not installed; Installed and enabled; Installed and disabled; Status unknown
- [ ] Confirmation dialog for Uninstall and Reinstall (task name/label + scope)
- [ ] Operation-result dialog/panel: human-readable result, exit code, launchd output/error, "View technical details" expandable
- [ ] Worker/controller for blocking service calls; marshal result DTOs back to main thread
- [ ] Disable action buttons while an operation is in flight
- [ ] Refresh discovery and selected-agent status after successful lifecycle actions

### Widget/controller Tests
- [ ] Correct action availability by managed/installed/status state
- [ ] Confirmation flows
- [ ] Busy-state handling
- [ ] Successful result display and refresh
- [ ] Failure result display with stdout/stderr/exit code
- [ ] External/invalid task actions remain unavailable
- [ ] Worker completion/error propagation without calling real platform services

### Integration Tests
- [ ] Retain existing protected system integration tests
- [ ] Add real launchctl integration coverage for behavior fake tests cannot establish, guarded by MACTASK_ALLOW_SYSTEM_TESTS=1

### Documentation
- [ ] README.md: install, reinstall, uninstall, enable, disable, run-now workflow and user-only safety boundary
- [ ] docs/architecture.md: lifecycle worker boundary and explicit redeploy transaction
- [ ] docs/development.md: how to run opt-in integration tests and expected cleanup behavior
- [ ] PROJECT.md, TODOS.md, PLAN.md, SUMMARY.md
- [ ] Version: 0.0.10 → 0.0.11

## Crawl Increment 12 — GUI Diagnostics and Logs (PENDING)

### Application-Service Work
- [ ] Add TaskCommandService.test_job(job, *, detection=None) -> DirectTestResult
- [ ] Existing test(label) resolves saved managed job and invokes the same path
- [ ] For Python jobs, detect candidates before testing; pass detection into DirectTestService for interpreter-mismatch diagnostics
- [ ] Add TaskCommandService.compare_environment(job, terminal_environment) -> EnvironmentDifference
- [ ] Environment comparison receives os.environ copy from GUI layer; platform comparison remains pure
- [ ] Logs remain read-only through LogService
- [ ] Unit tests: draft and saved-job direct tests, Python detection via diagnostics, all diagnostic rule outcomes, environment comparison via GUI-process env mapping, logs (content, empty, missing, unreadable, unconfigured)

### GUI — Diagnostics/Logs Panel
- [ ] Test summary: pass/fail state, exit code, elapsed duration
- [ ] Diagnostics section: severity, title, explanation, suggested action
- [ ] Direct stdout and Direct stderr tabs
- [ ] Persisted logs: stdout/stderr tabs with Refresh button
- [ ] Environment comparison: terminal/app-only, scheduled-only, differing values
- [ ] Python recommendation: candidate list, selected interpreter, recommended change
- [ ] Accurate direct-test wording: "Test runs this command directly... does not prove launchd can run it on schedule"
- [ ] Do not render arbitrary raw environment values by default if they may contain secrets

### Widget Tests
- [ ] Direct-test wording and result rendering
- [ ] stdout/stderr tabs and empty output
- [ ] Diagnostic severity and suggested-action rendering
- [ ] Python recommendation display
- [ ] Environment-difference categories and disclosure text
- [ ] Persisted-log Refresh behavior
- [ ] Error states with fake readers/services

### Documentation
- [ ] README.md: test semantics, direct-test limitations, diagnostics, environment-comparison disclosure, logs, security guidance against storing secrets in job definitions
- [ ] docs/architecture.md: diagnostics/test façade contracts and presentation-safe environment comparison
- [ ] docs/development.md: diagnostic/log test fixtures and safety rules
- [ ] PROJECT.md, TODOS.md, PLAN.md, SUMMARY.md
- [ ] Version: 0.0.11 → 0.0.12

## Crawl Increment 13 — Packaging (PENDING)

### Implementation
- [ ] Add/verify GUI executable entry point: QApplication -> composition root -> main window -> event-loop exit code
- [ ] Add version-controlled PySide6 deployment configuration file (pyside6-deploy)
- [ ] Define: app display name, bundle name, GUI entry point, output location (ignored by Git), architecture, icon policy
- [ ] Add `make package` target that invokes the deployment configuration
- [ ] Add `make run-gui` target for development startup
- [ ] Generated app does not depend on source checkout or activated virtual environment
- [ ] Keep deployment artifacts out of source control

### Verification
- [ ] make check green
- [ ] Explicit coverage run
- [ ] make package succeeds
- [ ] Manual macOS smoke checklist:
  - [ ] Launch .app from Finder/open
  - [ ] Main window opens without Terminal or activated venv
  - [ ] Discovery loads safely
  - [ ] New Task opens
  - [ ] No lifecycle operation runs at app startup
  - [ ] App uses current-user LaunchAgent scope only
  - [ ] Fake/non-destructive path works
  - [ ] If real lifecycle manually tested, unique test-owned label with cleanup

### Documentation
- [ ] README.md: prerequisites, package command, artifact location, local architecture scope, launch instructions, explicit signing/notarization status
- [ ] docs/development.md: package build, cleanup, and bundle smoke-test procedure
- [ ] docs/architecture.md: GUI entry point and packaging boundary
- [ ] PROJECT.md: Crawl GUI/package state and next product-phase direction
- [ ] TODOS.md: mark packaging complete with artifact and smoke-check result
- [ ] PLAN.md: replace Crawl strategy with Walk-phase plan or mark Crawl complete
- [ ] SUMMARY.md: packaging implementation, verification outcome, artifact location, deferred distribution scope
- [ ] Version: 0.0.12 → 0.0.13
