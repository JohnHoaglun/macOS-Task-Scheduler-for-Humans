# SUMMARY.md

## Changelog

### v0.0.12
- Crawl Increment 12: GUI Diagnostics and Logs — `mactask-gui` direct-test entry points for the selected managed task (Diagnostics > Test) and for the job editor's currently validated draft (Test Draft; validates first, persists nothing — no catalog record, plist, or lifecycle side effect)
- Job-based façade contracts: `TaskCommandService.test_job(job, *, detection=None)` (works for unsaved drafts; Python jobs carry detection into interpreter-mismatch diagnostics; `test(label)` resolves and delegates), `compare_environment(job, terminal_environment)`, `read_logs_for(job)` with `read_logs(label)` delegating, and `gui_environment()` in the composition layer
- `DirectTestResult` (immutable, never persisted) with `ProcessResult` + structured `Diagnostic` list (severity, code, title, description, suggested action); the panel labels the direct test accurately — it does not prove launchd can run the job on schedule
- Shared `DiagnosticLogsPanel` (test summary, diagnostics list, direct stdout/stderr tabs, persisted stdout/stderr tabs with Refresh, environment comparison, Python recommendation) hosted by the main window (below the inspector) and by the modal `DirectTestDialog` for the editor; distinct log states — configured with content, empty, missing/unreadable (`Log unavailable: <reason>`), unconfigured
- Presentation-safe environment comparison: `bootstrap.gui_environment()` snapshots `os.environ` once (the GUI never reads it), the platform comparison stays pure on supplied mappings, and the panel renders difference categories and variable names only — never raw values
- Qt-free `DiagnosticsController` (single-slot `request_test` → `RequestVerdict` ACCEPTED/BUSY/INVALID_JOB, exception-safe `execute()`, busy reset in `finish()`, synchronous `read_logs`/`compare_environment` re-reads) + `DiagnosticsWorker` QObject on a `QThread`; main window owns the selection/stale-result guard and busy gating; Test Draft is draft-only
- 90 new tests, 766 total, 100% line coverage across the whole package, ruff + mypy strict clean

### v0.0.11
- Crawl Increment 11: GUI Installation and Lifecycle — `mactask-gui` Lifecycle menu (Install, Reinstall…, Uninstall…, Enable, Disable, Run Now) over the shared `TaskCommandService`, with managed-only gating at both the service and the GUI (saved rows: Install only; installed managed rows: the other five; external/invalid/unselected: none) and Reinstall/Uninstall confirmations naming the task, exact label, and current-user LaunchAgents scope
- Unified `TaskListing` DTO: `list_agents()` merges discovered plists (discovery order, managed rows carrying the canonical catalog job) with catalog-only saved jobs (sorted by label, shown as `Saved, not installed`); presenter/inspector pinned state strings — `Installed, configured enabled (loaded)`, `Installed, configured enabled (not loaded)`, `Installed, configured disabled (loaded)`, `Installed, configured disabled (not loaded)`, `Status unknown`
- Staged reinstall transaction: unique create-exclusive `.staged.N` sibling → bootout → `.backup.N` preservation of the deployed plist → atomic activation → bootstrap; per-phase `InstallPhase` records, completed-phase tracking, and `retained_artifacts` on failure (the transaction never claims a rollback); `install(job)` skips the catalog import for the same job id and refuses an existing plist (`FileExistsError` — use reinstall); uninstall removes the plist and catalog record only after a successful bootout
- Qt-free `LifecycleController` (gating, single-slot busy, `RequestVerdict` ACCEPTED/BUSY/NOT_MANAGED/NOT_ALLOWED, exception-safe `execute()`, `is_success` = no error and process exit 0) + `LifecycleWorker` QObject on a `QThread` marshaling the immutable `LifecycleOutcome`; main window dispatches via queued connection, refreshes on success preserving selection by label, and shows the result dialog (headline, exit code, raw stdout/stderr, expandable technical details with phase results and retained artifacts)
- 132 new tests, 676 total, 100% line coverage across the whole package, ruff + mypy strict clean

### v0.0.10
- Crawl Increment 10: GUI Job Creation, Edit, Save, and Validation — `mactask-gui` File > New Task... (Cmd+N) and File > Edit Managed Task... open the modal `JobEditor` dialog: Identity (auto-derived managed label, manually editable), Command (Python/Shell/Executable pages with argument row tables and a detected-interpreter row — script edits run `detect_python`, candidates show as `path (source)` with a Use button that also fills a blank working directory), Schedule (HH:MM + weekday checkboxes + the launchd sleep/wake note), Environment, Advanced (working directory + optional stdout/stderr log paths, default root `~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/`), and a read-only plist preview
- Qt-free `EditorController` over a mutable `JobDraft` DTO (stable UUID, label-touched flag) returning frozen `EditorOutcome`/`PreviewOutcome`/`SaveOutcome` with field errors keyed by stable field names; `JobService.new_managed_job` factory (deterministic label/working-dir/log defaults, no writes) + `JobService.save` (immutable-ID overwrite, label-conflict rejection)
- Save policy: Save initially enabled, disabled only after a known-invalid result, re-enabled on any draft change; invalid drafts never persist; save is non-deploying (catalog JSON only — no plist, no launchctl, no log directories); Edit gated to selected managed rows resolved by label, with status-bar hints for unparseable listings and catalog misses; post-save refresh preserves selection by path
- Generic `RowTable` widget (add/remove rows, single `rowsChanged` signal); main-window actions refresh on save with no lifecycle calls; docs (README/architecture/development) cover the editor contracts, GUI boundary, and offscreen Qt test conventions
- 131 new unit tests, 544 total, 100% line coverage across the whole package, ruff + mypy strict clean

### Planning: Crawl Increment 10 Detail (approved)
- Pinned product decisions: managed label policy (`io.github.macos-task-scheduler.user.<slug>-<8-hex>` of the job UUID), draft UUID retained for the draft's lifetime, logging expressed via cleared stdout/stderr paths (no toggle), Save validates on click and disables only after a known-invalid result, Edit limited to the selected Managed discovery row resolved by label, New Task opens with a blank schedule and no command paths
- Application surface: `JobService.new_managed_job` (factory with deterministic label/working-dir/log defaults, no directory creation) + `JobService.save` (immutable-ID overwrite, label-conflict rejection); `TaskCommandService` in-memory `validate_job` / `generate_plist_for` / `save_managed_job` (catalog-only, non-deploying) / `detect_python` / `resolve_managed_job`
- GUI: Qt-free `EditorController` with a draft DTO and frozen outcomes; `JobEditor` dialog with seven sections (argument/environment row tables, stacked command forms, sleep/wake disclaimer, plist preview); main-window New Task and Edit Managed Task actions with managed-only gating
- Execution: micro-slice subagent tasks with on-disk verification; 0.0.9 → 0.0.10 at closeout

### v0.0.9
- Crawl Increment 9: GUI Read/Discovery — PySide6 read-only discovery browser (`mactask-gui`): two-pane main window (agent table + read-only inspector) over the shared application services
- Shared composition root extracted to `task_scheduler.bootstrap.build_services()`; the `mactask` CLI and the `mactask-gui` entry point wire the identical service graph
- `TaskCommandService.inspect_discovered(path)` (root containment, read-only, never mutates) + `DiscoveredInspectReport` DTO (path, parsed, managed, status)
- GUI package boundary: PySide6 imported only inside `gui/`; pure presenters own all display mapping, a pure-Python `DiscoveryController` bridges to the service and converts failures to error text; the GUI never imports `cli/`, `platform/`, `storage/`, `subprocess`, or `os.environ`
- Read-only external-job policy: Managed/External/Invalid classification (invalid wins); external and invalid agents render in Overview/Command/Schedule/Environment/Warnings/Advanced (raw plist) with no edit or lifecycle controls; selection preserved across refreshes, empty state and discovery-failure states
- PySide6 6.11.2 + pytest-qt; headless widget tests (`QT_QPA_PLATFORM=offscreen`, `qt_api = "pyside6"`); 85 new tests, 413 total, 100% line coverage across the whole package, ruff + mypy strict clean

### Planning: Crawl Increments 9–13 (GUI + Packaging)
- Detailed implementation plan written to PLAN.md covering 5 increments:
  - **Increment 9:** GUI Read/Discovery — PySide6 main window, discover/list/inspect external and managed LaunchAgents, read-only external-job policy
  - **Increment 10:** GUI Job Creation/Edit/Save/Validate — new task forms (Python/Shell/Executable), Python venv detection, schedule/time/weekdays, draft validation, managed catalog save/update (non-deploying save, explicit reinstall)
  - **Increment 11:** GUI Installation/Lifecycle — install, reinstall, uninstall, enable, disable, run now; managed-only gating; worker/controller for blocking operations; explicit redeploy transaction
  - **Increment 12:** GUI Diagnostics and Logs — direct-test (Mode A), structured diagnostics, stdout/stderr viewer, persisted logs, environment comparison, Python interpreter recommendation
  - **Increment 13:** Packaging — pyside6-deploy local .app bundle, make package/run-gui targets, manual macOS smoke checklist
- Pinned decisions: save is non-deploying; environment comparison uses GUI process env; packaging targets current machine architecture only
- Shared foundation before Increment 9: add PySide6 + pytest-qt, extract composition root to task_scheduler/bootstrap/build_services(), add GUI entry point

### v0.0.8
- Crawl Increment 8: `mactask` CLI — Typer app with 12 commands (list, inspect, validate, generate, install, uninstall, enable, disable, status, run, test, logs) sharing the application-service layer with the future GUI
- `TaskCommandService` façade (12 operations) + `JobService` (app-owned JSON job catalog, create-only install conflict detection) + `LogService` (read-only stdout/stderr readers); `<job>` is always the exact managed launchd label resolved from the catalog
- Exit codes 0/1/2 (success / launchd failure / usage error), reports and plist XML to stdout, errors and diagnostics to stderr; all launchd interaction still via `LaunchAgentBackend` + `ProcessRunner`
- 85 new unit tests, 328 total, 100% coverage, ruff + mypy strict clean

### v0.0.7
- Crawl Increment 7: launchctl adapter — `LaunchAgentBackend` coordinates storage + launchctl for `install` (write then bootstrap), `uninstall` (bootout then remove), `status` (print → loaded True/False/None), `enable`, `disable`, `trigger` (kickstart -k), user `gui/<uid>` domain only via `/bin/launchctl` through `ProcessRunner`
- Structured lifecycle results (`LaunchctlResult`, `LaunchAgentStatus`) preserve exact `ProcessResult`; failed bootstrap/bootout retains the plist for diagnosis; shared public `validate_label` guards all raw-label entry points
- Protected integration tests behind the `integration` marker + `MACTASK_ALLOW_SYSTEM_TESTS=1` (unique UUID labels, unconditional cleanup); plain `pytest`/`make test`/`make check` never run them; `make integration` added
- 35 new unit tests, 243 total, 100% coverage, ruff + mypy strict clean

### v0.0.6
- Crawl Increment 6: LaunchAgent Storage — `LaunchAgentStore` writing (create-only, atomic exclusive-link so an existing plist is never overwritten), removing (idempotent), and discovering plists under `~/Library/LaunchAgents` (or an injected root)
- `LaunchAgentFilesystem` protocol + `LocalFilesystem`: all store file IO flows through the abstraction so unit tests never touch real user directories; discovery parses via the never-raising reader and reports supported/partially-supported/invalid plists without mutating them
- Store-boundary label validation (no path separators, no `.`/`..`) guards the raw-string `remove`/`destination_for` entry points
- `FakeFilesystem` test fake; 31 new tests, 208 total, 100% coverage, ruff + mypy strict clean

### v0.0.5
- Crawl Increment 5: Direct Test Runner — `ProcessRunner` port + `SubprocessRunner` (only subprocess caller, exact job environment, no timeout, structured launch failures, injectable clock), `DirectTestService` (argv via shared `command_argv`, no job mutation), `diagnostic_service` with 7 structured rules in deterministic order
- `command_argv` promoted to the domain as the single argv source of truth; `PlistCodec` refactored onto it
- `tests/fakes.py` with `FakeProcessRunner`/`FakeClock`; 37 new tests, 177 total, 100% coverage, ruff + mypy strict clean

### v0.0.4
- Crawl Increment 4: Python detection — `detect_python` finds candidate interpreters (`.venv`, `venv`, current interpreter, PATH-discovered `python3`) in priority order with executable-file qualification and spelling-based deduplication; `compare_environments` reports structured terminal/scheduled differences without ever capturing a shell
- Injectable `current_interpreter` and `path_lookup` keep tests host-independent (all `tmp_path`-based)
- 16 new tests; 140 total, 100% coverage, ruff + mypy strict clean

### v0.0.3
- Crawl Increment 2: plist encoder — `PlistCodec.encode_dict/encode_bytes` producing launchd XML plists from `JobDefinition` (Label, ProgramArguments, StartCalendarInterval, WorkingDirectory, EnvironmentVariables, StandardOutPath, StandardErrorPath, Disabled)
- Crawl Increment 3: plist reader — `parse_bytes/parse_path` classifying existing LaunchAgent plists as supported / partially_supported / invalid; never raises; raw dict always preserved
- Shared launchd representation pinned in `plist_models.py` (weekday mappings, SUPPORTED_KEYS, ParseSupport, ParsedLaunchAgent)
- Golden fixtures (JSON + plist bytes) and 14 reader fixtures added
- 123 tests, 100% coverage, ruff + mypy strict clean

### v0.0.2
- Integrated upstream repository (branch: sched_dev_opencode)
- Project files updated to reflect actual repo contents
- README.md and spec.md.md from upstream repo

### v0.0.1
- Created project "macOS Task Scheduler for Humans"
- Added initial PROJECT.md, PLAN.md, TODOS.md
