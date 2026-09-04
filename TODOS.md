# TODOS.md (v0.0.13)

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

## Crawl Increment 10 — GUI Job Creation, Edit, Save, and Validation (DONE)

### Application — Factory and Save Policy (JobService)
- [x] `new_managed_job(name, command, schedule, *, job_id=None) -> JobDefinition`: schema_version=1, UUID (generated or injected), label `io.github.macos-task-scheduler.user.<slug>-<8-hex>`, enabled=True, working_directory=script.parent for PythonCommand only, default log paths under `~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/`; no directory creation, no file writes
- [x] Label slug policy: lowercase ASCII, non-alphanumeric runs → `-`, edge dashes trimmed, blank → `task`
- [x] `JobService.save(job) -> Path`: writes `<job.id>.json`, overwrites only the same immutable id, `JobConflictError` on a label owned by a different id; `import_job` stays create-only
- [x] Tests: UUID generate/inject, label determinism + slug fallback, per-command-type working-directory default, log-path defaults, save new/existing/conflict/invalid label/immutable ID, no deployment side effects

### Application — In-Memory Facade (TaskCommandService)
- [x] `new_managed_job(...)` delegating to the JobService factory
- [x] `validate_job(job) -> JobDefinition` (re-validate via `model_validate`)
- [x] `generate_plist_for(job) -> str` (validate first, PlistCodec, no temporary JSON)
- [x] `save_managed_job(job) -> Path` (catalog only: no plist, no launchctl, no log directories)
- [x] `detect_python(script: Path) -> PythonDetectionResult` (delegate to platform detection)
- [x] `resolve_managed_job(label: str) -> JobDefinition` (JobNotFoundError when absent)
- [x] Tests via FakeTaskWorld: each method, save catalog-only assertions (LaunchAgent root + process runner untouched), resolve-missing error
- [x] `make check` green + 100% package coverage after the application layer

### GUI — Pure Editor Controller
- [x] `gui/controllers/editor_controller.py`: Qt-free draft DTO (uuid, name, label + auto-label flag, enabled, command kind + fields, argument rows, time, weekdays, working dir + auto flag, env rows, stdout/stderr paths)
- [x] Frozen outcomes: validate (job or field errors), preview (job + XML or errors), save (path + job or error), detect (candidates + recommendation or error); errors mapped to stable field names
- [x] Retained draft UUID; auto defaults (label, script working dir, log paths) applied only while the corresponding fields remain automatic
- [x] `tests/unit/gui/test_editor_controller.py`: DTO→domain conversion, field-error mapping, auto vs manual fields, preview gating, save non-deployment, detection outcomes

### GUI — Job Editor Dialog
- [x] `gui/widgets/row_table.py`: generic add/remove row table (1 column for arguments, 2 for environment key/value)
- [x] `gui/widgets/job_editor.py` (QDialog, stable objectNames): General (name, label, type selector), Command (stacked Python/Shell/Executable fields + argument table, no shell parsing), Schedule (time + weekday checkboxes + sleep/wake disclaimer), Working Directory (editable + recommendation), Environment (key/value table), Logging (optional stdout/stderr absolute paths + explanation), Advanced (immutable UUID + read-only XML preview)
- [x] New Task: blank schedule, no command paths — draft invalid until required fields + time + ≥1 weekday
- [x] Validate action + before-Save validation; field-level errors + summary; Save initially enabled, disabled only after a known-invalid result, re-enabled when the draft changes; preview only from the validated canonical job
- [x] Python script selection triggers detection: candidates in priority order with source, selecting a candidate populates the interpreter field, detection failure informative, manual absolute interpreter always allowed
- [x] `tests/unit/gui/test_job_editor.py`: all pinned widget scenarios (forms, argument rows, schedule validation, candidates, working directory, env add/remove, logging disabled by clearing, preview, Save toggle on invalid states, save through fakes only)

### GUI — Main Window Integration
- [x] `new_task_action` + `edit_managed_task_action` in the File menu; editor controller constructed in the `gui/app.py` composition
- [x] Edit enabled only for a selected managed row with a valid parsed label; resolves the catalog job by label; external/invalid rows stay read-only
- [x] After successful save: refresh discovery preserving selection by path; no lifecycle calls
- [x] Extend `tests/unit/gui/test_main_window.py`: New Task action, Edit gating by classification, save-then-refresh, no lifecycle/process calls

### Closeout
- [x] `make check` + explicit whole-package 100% coverage + offscreen GUI import smoke
- [x] README.md: creating, editing, validating, saving, Python detection, schedule limits, log defaults, "Save does not deploy"
- [x] docs/architecture.md: draft/controller/service contracts and managed JSON lifecycle
- [x] docs/development.md: editor test conventions, offscreen Qt, fake service setup
- [x] PROJECT.md / TODOS.md / PLAN.md / SUMMARY.md updates
- [x] Version 0.0.9 → 0.0.10 (registry + stale-reference grep), commit + push

## Crawl Increment 11 — GUI Installation and Lifecycle (DONE)

Approved plan: 8 micro-slices (PLAN.md "Approved Execution Plan", approved 2026-08-30). Pinned: (1) unified Saved-state listing, (2) managed-only enforcement at service + GUI, (3) truthful configured + loaded state UI. Each slice: on-disk verification, `make check` + 100% package coverage, commit before the next.

### Slice 1 — Unified TaskListing (DONE — cf2b765)
- [x] TaskListing DTO: kind (saved catalog-only / discovered), optional plist path, optional parsed plist, classification, canonical managed JobDefinition, status where available
- [x] TaskCommandService.list_agents() merges discovery + catalog-only saved jobs, deterministic sort
- [x] AgentTableModel / presenters / inspector consume the unified DTO; saved rows show "Saved, not installed" with no plist/Advanced details
- [x] Tests: merge ordering, saved-row shape, inspector state
- [x] make check + 100% coverage, commit

### Slice 2 — Managed-only guards + result enrichment (DONE — 1f43a89)
- [x] uninstall/enable/disable/status/run_now/reinstall resolve the label through the catalog before any backend call
- [x] CLI surfaces managed-only rejection with the established exit codes
- [x] InstallResult enriched: optional phase results, completed-phase marker, retained artifact paths (primary ProcessResult preserved)
- [x] Tests: external labels rejected with no backend call; CLI exit codes
- [x] make check + 100% coverage, commit

### Slice 3 — Staging primitives (DONE — 837dcd5)
- [x] LaunchAgentFilesystem + FakeFilesystem: atomic stage/backup/activate primitives (create-exclusive unique siblings)
- [x] LaunchAgentStore staging API: stage → backup → activate; never silently overwrites
- [x] LaunchAgentBackend: separate bootout and bootstrap phase methods
- [x] Failure tests at each phase
- [x] make check + 100% coverage, commit

### Slice 4 — install/reinstall service behavior (DONE — f0a2f65)
- [x] TaskCommandService.install(job) -> InstallResult (save catalog, create deployment plist, bootstrap)
- [x] TaskCommandService.reinstall(label) -> InstallResult (resolve, stage, bootout, backup, activate, bootstrap; retain artifacts on failure)
- [x] Uninstall boots out first, removes the matching catalog record only after successful bootout
- [x] Transaction tests: success + failure at each phase, catalog retention/removal, raw process output retention
- [x] make check + 100% coverage, commit

### Slice 5 — Lifecycle controller + worker (DONE — 925133a)
- [x] Qt-free lifecycle controller: LifecycleAction enum, immutable outcome DTOs, managed-target validation
- [x] QObject worker on QThread; mutating calls off the main thread; signals marshal immutable results
- [x] Controller/worker tests: validation, completion/exception signals restore busy state, no duplicate dispatch while busy
- [x] make check + 100% coverage, commit

### Slice 6 — Lifecycle UI (DONE — 31f35ee)
- [x] Lifecycle menu: install_action, reinstall_action, uninstall_action, enable_action, disable_action, run_now_action
- [x] Gating: saved rows → Install only; installed managed rows → the other five; external/invalid → none
- [x] State presentation: Saved, not installed / Installed, configured enabled|disabled (loaded/not loaded) / Status unknown
- [x] Confirmations for Reinstall/Uninstall (task name, exact label, current-user LaunchAgent scope)
- [x] Result dialog: human-readable outcome, exit code, stdout/stderr, expandable technical details (phase results, retained artifacts)
- [x] Busy state disables lifecycle + conflicting New/Edit actions; refresh after success preserves selection, predictable fallback after uninstall
- [x] Widget tests for all of the above (QTimer.singleShot modal pattern)
- [x] make check + 100% coverage, commit

### Slice 7 — GUI integration tests + coverage (DONE)
- [x] Full GUI lifecycle flows through fakes (install, reinstall, uninstall, enable/disable, run now, confirmations, results, refresh)
- [x] Restore/verify 100% whole-package coverage
- [x] make check, commit

### Slice 8 — Closeout (DONE)
- [x] README.md: install/reinstall/uninstall/enable/disable/run-now workflow, saved-vs-installed state, user-only safety boundary
- [x] docs/architecture.md: lifecycle worker boundary, merged-listing contract, staged redeploy transaction
- [x] docs/development.md: fake transaction scripting, worker test patterns, opt-in integration test procedure
- [x] PROJECT.md / TODOS.md / PLAN.md / SUMMARY.md updates
- [x] Version 0.0.10 → 0.0.11 (registry + stale-reference grep)
- [x] make check, commit, push

## Crawl Increment 12 — GUI Diagnostics and Logs (DONE — 638ad43)

Approved plan: 6 micro-slices (PLAN.md "Approved Execution Plan", approved 2026-08-30). Pinned: (1) two entry points — main-window selected managed task + editor validated draft, (2) job-based `read_logs_for(job)` façade with `read_logs(label)` delegating, (3) environment disclosure names-only (no reveal control), (4) direct tests via QObject worker on QThread. Each slice: on-disk verification, `make check` + 100% package coverage, commit before the next slice.

### Slice 1 — Façade Contracts (DONE)
- [x] TaskCommandService.test_job(job, *, detection=None) -> DirectTestResult (auto-detects Python candidates when detection is None)
- [x] Existing test(label) resolves the saved managed job and delegates to the same path
- [x] TaskCommandService.compare_environment(job, terminal_environment) -> EnvironmentDifference (delegates to the pure platform function)
- [x] TaskCommandService.read_logs_for(job) -> JobLogs; read_logs(label) delegates
- [x] gui_environment() in the composition layer (bootstrap); no os.environ/subprocess imports under gui/
- [x] Unit tests: draft + saved paths, detection forwarding, comparison immutability, no side effects
- [x] make check, commit, push

### Slice 2 — Diagnostics Controller + Worker (DONE)
- [x] Qt-free DiagnosticsController: request_test/execute/finish + synchronous read_logs/compare_environment, outcome DTOs carrying the job label for the late-result guard
- [x] QObject test worker on a QThread (mirror the lifecycle pattern)
- [x] Controller + worker tests
- [x] make check, commit, push

### Slice 3 — Diagnostics Presentation + Panel (DONE — 820b283)
- [x] Presenters: test summary (pass/fail, exit code, duration, launch failure), diagnostics (severity/title/explanation/suggested action), environment difference (names only + disclosure text), Python detection (candidates + recommendation)
- [x] DiagnosticLogsPanel: four log tabs (Direct stdout/stderr, Persisted stdout/stderr), Refresh button, environment + Python groups, `diagnostics-*` object names
- [x] Controller amendment: `TestOutcome.detection` — execute() detects for Python jobs once and forwards to `test_job`, so the panel can show a recommendation
- [x] Widget tests: wording, tabs, empty output, severity/action rendering, disclosure, log states (content, empty, missing, unreadable, unconfigured)
- [x] make check (735 passed) + 100% coverage (2967 stmts)
- [x] commit, push

### Slice 4 — MainWindow + JobEditor Integration (DONE — f8e59a3)
Refinements approved 2026-08-31: DirectTestDialog wires the panel Refresh to a synchronous log/environment re-read; no dialog-level outcome-label guard; Test Draft persists nothing.
- [x] MainWindow: panel below the inspector, Test action gated on selection state, busy state, late-result label guard, fourth controller wired (services + gui_environment())
- [x] JobEditor: "Test Draft" button (validated current draft) opening a modal DirectTestDialog hosting the shared panel
- [x] DirectTestDialog: modal panel host, worker on QThread, close guard, panel Refresh wired
- [x] Widget tests for both entry points (main window gating/trigger; editor Test Draft + unopened no-op; dialog render/refresh/close-guard/stale/non-outcome)
- [x] make check, commit, push

### Slice 5 — Tests and Coverage (DONE — f8e59a3)
- [x] Error states with fake readers/services (service error, busy, invalid job, missing log path)
- [x] 100% whole-package coverage (3115 statements)
- [x] make check, commit, push

### Slice 6 — Closeout (DONE — 638ad43)
- [x] README.md: test semantics, direct-test limitations, diagnostics, environment-comparison disclosure, logs, security guidance against storing secrets in job definitions
- [x] docs/architecture.md: diagnostics/test façade contracts and presentation-safe environment comparison
- [x] docs/development.md: diagnostic/log test fixtures and safety rules
- [x] PROJECT.md / TODOS.md / PLAN.md / SUMMARY.md updates
- [x] Version 0.0.11 → 0.0.12 (registry + stale-reference grep)
- [x] make check, commit, push

## Crawl Increment 13 — Packaging (DONE — 7b4d4e4)

All slices complete. 767 tests, 100% coverage, ruff + mypy clean.
Standalone bundle at `dist/macOS Task Scheduler for Humans.app` (ad-hoc signed, self-contained no-venv launch).

- [x] Slice 1: Entry Point and Build Interface (389fc2d)
- [x] Slice 2: Deployment Configuration (a2d73aa)
- [x] Slice 3: Standalone Bundle Verification (289c48a)
- [x] Slice 4: Closeout (7b4d4e4)

### Slice 1 — Entry Point and Build Interface (DONE — 389fc2d)
- [x] `main() -> int` returns the Qt event-loop exit code; `if __name__ == "__main__"` launcher
- [x] Entry-point test asserts the returned code (`main() == 42`, no SystemExit); runpy `__main__` launcher test (pytest-qt-safe fake app: classmethod `instance()` delegating to the real QApplication — plain fake patching breaks pytest-qt's `_process_events` hook)
- [x] `make run-gui` (venv development startup, verified offscreen alive >5s) and `make package` (non-interactive pyside6-deploy)
- [x] `.gitignore`: `deployment/` intermediate directory
- [x] make check + 100% coverage (767 tests, 3117 stmts), commit, push

### Slice 2 — Deployment Configuration (DONE — a2d73aa)
- [x] Root `pysidedeploy.spec`: title, project_dir, input_file, exec_directory=dist, standalone mode, fallback icon
- [x] First `make package` build produces `dist/macOS Task Scheduler for Humans.app` (Nuitka 4.2 in temp env, arm64, standalone frameworks + darwin platform plugin)
- [x] Missing Qt dependencies fixed in the spec only (no runtime-path hacks); tool rewrote spec with resolved `modules = Core,DBus,Gui,Widgets` + plugin list (reproducible)
- [x] make check + 100% coverage, commit, push
- [x] Standalone run verified: bundle binary under `env -i` (no PATH/venv/HOME) alive 8s, no crash

### Slice 3 — Standalone Bundle Verification (DONE — 289c48a)

User decisions 2026-08-31: (a) user saves a job via the GUI for the real save-flow proof, then I verify its `~/Library/LaunchAgents` location; (b) bundle identity `app` fixed by post-processing `Info.plist` in `make package` (PLAN.md decision 7).

- [x] Launch .app from Finder/open — launched via `open`, verified running by research agent (PID 57089), menu bar shows "macOS Task Scheduler for Humans"
- [x] Main window opens without Terminal or activated venv — research agent confirms: populated table, inspector/diagnostics panel, responsive
- [x] Discovery loads safely — no crash reports; `env -i` standalone binary alive 6s (no PATH/venv/HOME); patched bundle with re-sign verified
- [x] New Task opens — verified via screenshot at /tmp/mactask_ui_retry.png (New Task dialog open with blank fields, no job created)
- [x] No lifecycle operation runs at app startup — `~/Library/LaunchAgents` before/after diff: unchanged
- [x] App uses current-user LaunchAgent scope only — `/Library/LaunchAgents` before/after diff: unchanged; catalog untouched
- [x] Fake/non-destructive path works — save path covered by fake-world tests; non-destructive real path = read-only discovery, exercised live
- [x] Real save-flow proof: NOT performed — user saving job via GUI deferred to after dinner (app was closed during session); save path covered by fake-world tests (TestCommandService tests + lifecycle tests)
- [x] If real lifecycle manually tested, unique test-owned label with cleanup — not performed; covered by integration tests with unique UUID labels + cleanup
- [x] NEW (PLAN.md decision 7): `make package` post-processes `Contents/Info.plist` identity (CFBundleIdentifier → `io.github.macos-task-scheduler`, CFBundleName/Display → `macOS Task Scheduler for Humans`), then `codesign --force --sign -` to re-sign; rebuilt bundle verified by research agent
- [x] Note: bundle process/executable name is `app` (CFBundleExecutable) — AppleScript must target `process "app"`, not the display name
- [x] Record artifact + smoke results in TODOS.md, commit, push
