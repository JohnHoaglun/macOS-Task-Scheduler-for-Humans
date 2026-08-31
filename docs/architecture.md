# Architecture — macOS Task Scheduler for Humans

## Dependency Direction

The project follows a strict dependency flow:

```
Presentation
    ↓
Application
    ↓
Domain
    ↓
Platform abstractions
```

Each layer may depend on the layer below it, but never on layers above it. No layer depends on a sibling or a layer it sits above.

## Architectural Layers

| Layer | Purpose | Status |
|---|---|---|
| **GUI (PySide6)** | Native macOS desktop interface | Implemented (Increments 9–11: discovery, job editor, lifecycle) |
| **CLI (Typer)** | Terminal task management interface (`mactask`) | Implemented (Increment 8) |
| **Application Services** | Use cases, orchestration, coordination (`TaskCommandService` facade, `JobService`, `LogService`) | Implemented (Increments 7–10) |
| **Domain** | Core model: Job, Schedule, Command, Environment | Implemented |
| **Platform Adapters** | macOS plist codec, LaunchAgent store, launchctl backend, log reader | Implemented |
| **launchd** | Underlying macOS scheduler (external) | Not part of the codebase |

## Domain Model

The domain is the anchor of the entire system. It defines the fundamental concepts:

- **Job** — a schedulable unit of work with an associated command and environment.
- **Schedule** — recurrence rules that determine when a job runs.
- **Command** — the executable, its arguments, working directory, and environment variables.
- **Environment** — key-value pairs injected into the job's process context.

These domain types carry no platform-specific knowledge. They exist to represent the user's intent: "run this command, with this environment, on this schedule."

## Persistence Strategy

**The domain model is the application's source of truth. Plist files are macOS deployment representations.**

Managed jobs are persisted as human-readable, schema-versioned JSON files
(see the `storage/` layer). On macOS, the same domain model is translated
to the launchd LaunchAgent plist format by the platform layer
(`platform/macos/`). The domain never knows about plist keys, JSON layout,
or XML structure.

The application services layer (Increments 7–11) adds the `TaskCommandService`
facade, which both the `mactask` CLI and the GUI call. It coordinates
`JobService` (catalog resolution and conflict checks), `LogService`, the
`LaunchAgentStore` (plist writes/removals, staging siblings, and discovery
in `~/Library/LaunchAgents`), and the `LaunchAgentBackend` (all `launchctl`
invocations, including the bootout/bootstrap phases of the reinstall
transaction).

## Platform Boundaries

All `launchctl` argument vectors and LaunchAgent plist writes stay inside
`platform/macos/`. Application and presentation layers never build
`launchctl` commands or touch plist files directly. Process execution is
injected (a `ProcessRunner` protocol), so the entire stack is unit-testable
without invoking real `launchctl` or touching the live filesystem.

## GUI Package Boundary and Shared Composition Root

The GUI lives in `src/task_scheduler/gui/` and is the only place PySide6 is
imported. UI views are kept thin:

```text
gui/
├── app.py              # QApplication entry point (mactask-gui)
├── main_window.py      # two-pane window: agent table + inspector
├── controllers/        # pure-Python bridges to TaskCommandService (no Qt)
├── models/             # QAbstractTableModel adapters
├── presenters/         # pure-Python display mapping (no Qt, no services)
└── widgets/            # detail panels, row tables, and the job editor dialog
```

* Controllers own service calls and convert failures into plain error
  strings; presenters own every domain-to-string mapping; widgets only lay
  out and display. Neither controllers nor presenters import PySide6.
* Both entry points share one composition root:
  `task_scheduler.bootstrap.build_services()` builds the identical service
  graph (repository, job service, store, backend, codec, test service, log
  service) for the `mactask` CLI and the `mactask-gui` entry point, so CLI
  and GUI behavior cannot drift.
* The GUI's read path calls `list_agents()` (discovered plists plus
  catalog-only saved jobs) and `inspect_discovered()`, and the in-memory
  editor methods (`validate_job`, `generate_plist_for`, `save_managed_job`,
  `detect_python`, `resolve_managed_job`). Save is non-deploying
  (Increment 10): it writes the job's catalog JSON only — no plist write,
  no `launchctl`, no log directory creation.
* The GUI's lifecycle path (Increment 11) runs only through
  `LifecycleController` → `LifecycleWorker` → `TaskCommandService`
  (`install`, `reinstall`, `uninstall`, `enable`, `disable`, `run_now`).
  The service methods are managed-only: each validates the raw label and
  resolves it through the job catalog before touching the backend, so the
  GUI can never act on an external agent's label.
* Import boundary (current): the GUI may import `application/` and
  `domain/` freely; controllers and presenters additionally import
  `platform.macos` types (the Python interpreter detection result and the
  LaunchAgent parse/status types); widgets import no `platform/`, `cli/`,
  or `storage/` modules. Nothing under `gui/` imports `subprocess` or
  `os.environ`.

## Editor Contracts (Increment 10)

The GUI job editor creates, edits, validates, and saves managed jobs
through `EditorController` (`gui/controllers/editor_controller.py`), a
Qt-free bridge over `TaskCommandService` that the `JobEditor` dialog
(`gui/widgets/job_editor.py`) drives.

**JobDraft** is the mutable draft DTO for one in-flight job. It carries the
job's `UUID` for its lifetime — `open_new()` generates a fresh id, and
`open_existing()` inherits the stored job's id — plus a `label_touched`
flag. While the flag is false the label is auto-derived from the name as
`io.github.macos-task-scheduler.user.<slug>-<8-hex>` (the name slug plus
the first 8 hex characters of the job id, via `managed_label`); an explicit
label edit sets the flag and stops the derivation. Nothing in a draft is
persisted until a save.

**EditorController outcomes** keep the view exception-free. `validate()`,
`preview()`, and `save()` return frozen outcomes: `EditorOutcome` (`ok`,
`message`, `fields`), `PreviewOutcome` (adds the generated launchd plist
XML), and `SaveOutcome` (adds the persisted catalog path and final label).
Failures map to per-field errors keyed by stable field names — `name`,
`label`, `interpreter`, `script`, `shell_executable`, `executable`, `time`,
`weekdays`, `working_directory`, `environment`, `stdout_path`,
`stderr_path`, with a `job` key for whole-job failures — so the dialog can
display errors independently of widget layout. `save()` validates before
persisting; a catalog conflict and a write failure also become outcomes
rather than exceptions.

**JobService factory and save policy.** `JobService.new_managed_job()`
builds the in-memory `JobDefinition` for a new managed job — label from
`managed_label`, default stdout/stderr paths under
`default_job_logs_root() / <job-id>/` — and persists nothing.
`JobService.save()` is the catalog's update path: it overwrites the record
for the job's own immutable id, and raises `JobConflictError` when a
different managed job already claims the label.
`TaskCommandService.save_managed_job()` re-validates and delegates to
`save()`, so a save is catalog JSON only — no plist write, no `launchctl`,
no log directory creation.

**Managed JSON lifecycle.** Each managed job's catalog file is
`<job-id>.json` directly under the catalog root. Saving from the editor is
non-deploying: it writes or overwrites that catalog file only. Deploying a
saved change (plist write and launchd load) is the lifecycle commands'
job (Increment 11, below).

## Lifecycle Contracts (Increment 11)

The GUI Lifecycle menu (install, reinstall, uninstall, enable, disable, run
now) bridges to `TaskCommandService` through a two-part contract: a Qt-free
controller that owns all gating and busy-state logic, and a small QObject
worker that executes the accepted request off the main thread.

**Unified listing contract.** `TaskCommandService.list_agents()` returns
one frozen `TaskListing` per row: a `DISCOVERED` row for each plist under
`~/Library/LaunchAgents` (discovery order, carrying the parse and — for
managed labels — the canonical catalog job) and a `SAVED` row for each
catalog job with no deployed plist (sorted by label, carrying no path or
parse). CLI and GUI consume this single DTO, so the "saved, not installed"
state is one service-level fact, not a view detail.

**Managed-only guards.** Every lifecycle method on `TaskCommandService`
(`reinstall`, `uninstall`, `enable`, `disable`, `status`, `run_now`)
validates the raw label and resolves it through the job catalog before
touching the backend; an unknown or unmanaged label raises instead of
reaching `launchctl`. `install(job)` skips the catalog import when the same
job id is already saved (installing a saved row) and raises
`FileExistsError` when the plist already exists — re-applying an installed
job is `reinstall`'s job.

**Controller / worker split.** `LifecycleController`
(`gui/controllers/lifecycle_controller.py`) imports no Qt. It answers
`enabled_actions(listing)` (saved rows: install only; installed managed
rows: the other five; anything else: none), vets each request
synchronously into a `RequestVerdict` (`ACCEPTED` / `BUSY` / `NOT_MANAGED`
/ `NOT_ALLOWED`), and holds exactly one accepted request. `execute()` runs
the request and converts every service exception into an error outcome; the
busy state is always cleared by `finish()`. `LifecycleWorker`
(`gui/controllers/lifecycle_worker.py`) is the Qt half: a QObject moved
onto a `QThread`, invoked via queued connection, that calls `execute()`
then `finish()` and emits the immutable `LifecycleOutcome` (action, label,
structured result or error) back to the main thread. Success means a
non-error outcome whose process exited 0 — a structured result with a
nonzero (or missing) exit code is a failure even though no exception was
raised.

**Staged reinstall transaction.** `reinstall(label)` never overwrites the
deployed plist in place. It (1) stages the freshly generated plist as a
create-exclusive uniquely named sibling (`.staged.N`), (2) boots the label
out, (3) preserves the deployed plist as a uniquely named backup sibling
(`.backup.N`), (4) atomically activates the staged plist, and (5)
bootstraps. Each `launchctl` phase is recorded (`InstallPhase`), completed
phases are tracked, and any artifact a failed phase could not clean up is
reported in `InstallResult.retained_artifacts` — the transaction never
claims a rollback. The primary result is always the last phase's
`ProcessResult`. Uninstall is the inverse order: bootout first, plist and
catalog record removed only on success.
