# PLAN.md

## Current State
Crawl Increments 0–9 complete and pushed to `sched_dev_opencode` (version 0.0.9):
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
- Verification at v0.0.9: 413 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 10 — GUI Job Creation, Edit, Save, and Validation** (PENDING); Increments 11–13 (GUI lifecycle, diagnostics/logs, packaging) planned below.

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

### Requirements
- Add **Install**, **Reinstall**, **Uninstall**, **Enable**, **Disable**, and **Run Now** actions for managed jobs.
- Keep **Reinstall** explicit. It applies saved managed JSON changes to a previously installed LaunchAgent.
- Show clear success/failure results, including action, exit code, stdout, stderr, and useful next actions.
- Disable destructive lifecycle actions for external or invalid discovered jobs.
- Restrict operations to user LaunchAgents only.
- Keep all `launchctl` interaction behind `TaskCommandService`, `LaunchAgentBackend`, and `ProcessRunner`.
- Run potentially blocking operations outside the Qt event loop.

### Application-Service Work

**Pinned lifecycle contracts:**
```python
TaskCommandService.install(job: JobDefinition) -> InstallResult
TaskCommandService.reinstall(label: str) -> InstallResult
```

- **Install:** save/import managed JSON, create deployment plist, bootstrap the agent.
- **Reinstall:** resolve the saved managed JSON, safely replace its deployed plist, and reload/bootstrap.
- **Uninstall:** boot out the LaunchAgent and remove only the matching managed catalog record after successful bootout.
- **Enable/Disable/Run Now/Status:** remain label-based but GUI gating requires a managed selected agent.
- Every lifecycle operation preserves the underlying `ProcessResult`.

**Reinstall transaction semantics:**
1. Resolve managed job and validate label.
2. Preserve or stage the existing plist safely.
3. Boot out the installed job if required.
4. Write the new generated plist.
5. Bootstrap the new plist.
6. If deployment fails, retain diagnostic artifacts and return an actionable failure result.
7. Do not claim rollback succeeded unless it is verified.
8. Do not silently overwrite an existing plist.

Add only the minimal store/backend capability needed for the explicit replace/reload path, with tests for its failure behavior.

### GUI Design

- Enable actions only when a managed task is selected.
- Clearly distinguish: Saved but not installed; Installed and enabled; Installed and disabled; Status unknown.
- Confirm Uninstall and Reinstall, with task name/label and scope stated plainly.
- Operation-result dialog/panel containing:
  - Human-readable action result.
  - Exit code.
  - Launchd output/error details.
  - "View technical details" expandable section.
- Run each service call in a worker/controller operation layer. Marshal result DTOs back to the main thread.
- Disable duplicate action buttons while an operation is in flight.
- Refresh discovery and selected-agent status after successful lifecycle actions.

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

Retain existing protected system integration tests. Add real launchctl integration coverage only for behavior that fake-backed tests cannot establish, guarded by `MACTASK_ALLOW_SYSTEM_TESTS=1`.

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
