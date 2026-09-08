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
| **GUI (PySide6)** | Native macOS desktop interface | Implemented (Increments 9–12: discovery, job editor, lifecycle, diagnostics/logs) |
| **CLI (Typer)** | Terminal task management interface (`mactask`) | Implemented (Increment 8) |
| **Application Services** | Use cases, orchestration, coordination (`TaskCommandService` facade, `JobService`, `LogService`, `DirectTestService`) | Implemented (Increments 7–12) |
| **Domain** | Core model: Job, Schedule, Command, Environment | Implemented |
| **Platform Adapters** | macOS plist codec, LaunchAgent store, launchctl backend, log reader | Implemented |
| **launchd** | Underlying macOS scheduler (external) | Not part of the codebase |
| **Packaging** | PySide6 deployment → self-contained macOS `.app` bundle | Implemented (Increment 13) |

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

The schedule is a schema v2 discriminated variant: `CalendarSchedule`
(multiple `HH:MM` times × a weekday set, minute precision, `run_at_load`
additive only) or `IntervalSchedule` (minimum 60 seconds). Legacy v1 files —
a flat `schedule.time` plus `schedule.weekdays` — still read: the storage
layer migrates them to the v2 calendar variant on read, and every write is
v2. The domain model stays platform- and layout-agnostic; the migration is a
storage concern, and the plist translation of a multi-time calendar schedule
is the full weekday × time Cartesian product.

The pure `upcoming_occurrences(schedule, *, now, count)` domain calculator
(Increment 15) walks local dates from `now.date()` over configured weekdays
× sorted times, includes an occurrence exactly at `now`, and returns exactly
`count` naive local datetimes oldest first. It does no I/O, touches no
clock, and knows nothing about launchd; the GUI renders its output as the
estimated next-run preview. Its interval sibling,
`upcoming_interval_occurrences(schedule, *, now, count)` (Increment 17),
returns `now + seconds * i` for `i` in `1..count` — the first estimate is
exactly one interval after the application clock — and ignores
`run_at_load`. Because launchd's actual start anchor for `StartInterval` is
not exposed, the GUI renders this as an estimate with an explicit anchor
note, never as launchd's queue.

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

The draft's calendar schedule is `times: list[str]` — the raw visible
`HH:MM` rows, verbatim, in row order (a fresh draft holds one empty row) —
plus a `weekdays` set. The dialog renders the rows with the reusable
`TimeRowEditor` widget (`gui/widgets/time_row_editor.py`), which owns row
add/remove, keeps at least one row, and emits `rowsChanged`; it performs no
time parsing. All time validation, ascending sort, and duplicate collapse
happen in `CalendarSchedule`, which the controller builds from the raw rows;
a failed build maps to the `times` field with the domain's message.

The draft's schedule kind is `schedule_kind` (`"calendar"` | `"interval"`).
For interval jobs the draft additionally carries `interval_value` (the raw
visible whole number, verbatim — a fresh draft holds `"1"`) and
`interval_unit` (`seconds` / `minutes` / `hours` / `days`), plus the shared
`run_at_load` flag. The dialog renders the kind as a selector over two
stacked pages; the interval page performs only the single unit conversion,
and the controller hands the total seconds to `IntervalSchedule`, which
owns the minimum-60-seconds rule; a failed build maps to the `interval`
field. Switching kinds preserves each mode's values on the draft, and
`open_existing()` normalizes a stored interval to the largest exact unit
(days → hours → minutes → seconds) before it reaches the widgets.

**EditorController outcomes** keep the view exception-free. `validate()`,
`preview()`, and `save()` return frozen outcomes: `EditorOutcome` (`ok`,
`message`, `fields`), `PreviewOutcome` (adds the generated launchd plist
XML), and `SaveOutcome` (adds the persisted catalog path and final label).
Failures map to per-field errors keyed by stable field names — `name`,
`label`, `interpreter`, `script`, `shell_executable`, `executable`, `times`,
`weekdays`, `interval`, `working_directory`, `environment`, `stdout_path`,
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

## Diagnostics and Log Contracts (Increment 12)

The GUI's diagnostics and logs path (test a managed task or a validated
draft, view structured diagnostics, persisted logs, environment comparison,
and Python interpreter recommendations) extends the façade with job-based
contracts so both entry points — the selected managed task in the main
window and the currently validated draft in the job editor — share one
code path.

**Façade contracts.** `TaskCommandService.test_job(job, *, detection=None)`
runs the given job's command directly (Mode A) through the injected
`ProcessRunner`, evaluates the structured diagnostics, and returns an
immutable `DirectTestResult` (`process: ProcessResult`,
`diagnostics: list[Diagnostic]`) — which is never persisted into the job.
It works for validated, unsaved drafts as well as saved jobs; the CLI's
`test(label)` resolves the label through the catalog and delegates. For
Python jobs the caller passes a `PythonDetectionResult` so
interpreter-mismatch diagnostics are available.
`compare_environment(job, terminal_environment)` validates the job and
delegates to the pure platform comparison of the supplied mappings.
`read_logs_for(job)` reads the job's configured stdout/stderr files
(read-only, via `LogService`) and returns `JobLogs` (two `LogStream`s:
`path` is `None` when unconfigured; otherwise exactly one of `content` —
possibly empty — or `error` — missing/unreadable — is set); `read_logs(label)`
resolves and delegates.

**Controller / worker split.** `DiagnosticsController`
(`gui/controllers/diagnostics_controller.py`) imports no Qt. It vets a
`request_test(job)` into a `RequestVerdict` (`ACCEPTED` / `BUSY` /
`INVALID_JOB`), holds exactly one accepted request, and `execute()` runs the
test through the service, converting every exception into an error
`TestOutcome`; the busy state is always cleared by `finish()`. It also
answers the synchronous `read_logs(job)` / `compare_environment(job)`
re-reads (used by the panel's Refresh). `DiagnosticsWorker`
(`gui/controllers/diagnostics_worker.py`) is the Qt half: a QObject moved
onto a `QThread`, invoked via queued connection, that calls `execute()`
then `finish()` and emits the immutable `TestOutcome` back to the main
thread — the same pattern as the lifecycle worker, never on the UI thread.

**Presentation-safe environment comparison.** The GUI itself never reads
`os.environ`. The composition layer (`bootstrap.gui_environment()`) takes a
snapshot `dict(os.environ)` once and hands it to the diagnostics controller;
the platform comparison function is pure, comparing the two supplied
mappings and returning `EnvironmentDifference` (`terminal_only`,
`scheduled_only`, and `different`, whose values are never logged or
persisted by that module). Presentation is name-only: the panel renders
difference categories and variable names, not raw values, because a GUI
process environment cannot be assumed safe to display.

**Entry points.** The main window's Diagnostics menu **Test** action is
gated to a selected managed task and owns the selection/stale-result guard
(a late `TestOutcome` for a different label is ignored); the busy state
disables the action while a test is in flight. The job editor's **Test
Draft** button validates the current draft (field errors otherwise), builds
the job in memory, and opens the modal `DirectTestDialog`
(`gui/widgets/direct_test_dialog.py`) hosting the shared
`DiagnosticLogsPanel` — persisting nothing. Both host the same
`DiagnosticLogsPanel` (`gui/widgets/diagnostic_logs_panel.py`) with the
test summary, diagnostics list, direct stdout/stderr tabs, persisted
stdout/stderr tabs plus Refresh (synchronous re-read), the environment
comparison, and the Python recommendation group.

## Python Environment Detectors (Increment 18)

`platform/macos/python_detection.py` finds candidate Python interpreters
for a selected script behind a detector registry. Detection is read-only
and local: no `uv`/`poetry`/shell invocation, no symlink resolution, no
path normalization — paths are reported exactly as given, and candidates
are recommendations only.

**Contracts.** `DetectorKind` is a `StrEnum` (`core`, `uv`, `poetry`);
`DetectionNote` is a frozen `(detector, message)` model;
`PythonDetectionResult` carries `notes: list[DetectionNote]` alongside the
candidates. A detection run is described by the frozen `DetectionContext`
(`script`, `current_interpreter`, `path_lookup`, `filesystem`), where
`filesystem` is the `PythonDetectorFilesystem` read-only protocol
(`exists`, `is_file`, `is_dir`, `is_executable`, `read_text`; never
raises) with the live implementation
`LocalPythonDetectorFilesystem`. Each `PythonEnvironmentDetector`
exposes `kind` and `detect(context) -> DetectorContribution`
(`candidates: tuple[tuple[Path, CandidateSource], ...]`,
`notes: tuple[DetectionNote, ...]`). `default_python_detectors()` fixes
the registry order: core, uv, Poetry. `detect_python(script, *,
current_interpreter=None, path_lookup=None, filesystem=None)` runs the
registry and merges the contributions; the working-directory rule is
unchanged (script parent when the script is absolute and not a directory).

**Detectors.** The core detector keeps the legacy discovery and order:
`.venv/bin/python` beside the script, `venv/bin/python`, the current
interpreter, then `python3` from the injected PATH lookup — each
acceptance requires an absolute regular file with execute permission.
The uv and Poetry detectors locate the **nearest** project root by
walking the ancestors of the script's parent (skipped entirely for
relative or directory scripts): uv marks a root with a `uv.lock` file or
a `[tool.uv]` table in `pyproject.toml`; Poetry with `poetry.lock` or
`[tool.poetry]`. Only `<root>/.venv/bin/python` is then considered, and
it carries `source = CandidateSource.VENV` — `CandidateSource` gained no
values; ecosystem attribution lives solely in `detectors`.

**Merging and notes.** A path found by several detectors appears once, at
its first-discovered position, with its exact spelling and original
source kept; `InterpreterCandidate.detectors` (default
`(DetectorKind.CORE,)`) records every discovering detector in registry
order. Notes never raise: a project root without a usable
`<root>/.venv/bin/python` yields a per-ecosystem "no usable `.venv`
interpreter is available" note; an unreadable or unparseable
`pyproject.toml` yields one parse-failure note per detector per walk and
never cancels a lock-file marker or stops the walk. Merged notes stay in
detector-execution order with exact duplicates removed.

**Recommendation.** The project-affine anchor is the first candidate
whose source is `VENV` or `VENV_FALLBACK` (an ecosystem `.venv`
candidate qualifies via its source). That policy is the shared pure
helper `project_environment_candidate(detection)`, used by both
`diagnostic_service._rule_interpreter_mismatch` and the diagnostics
presenter; nothing is applied automatically.

## Expanded Diagnostics Engine (Increment 19)

The flat Increment-12 list is retained verbatim (`evaluate_diagnostics`,
its seven legacy codes and order — plus `executable_not_found_runtime`,
inserted after `permission_denied` and suppressed when the static
missing-executable rule fires) and extended with a source-grouped report
engine.

**Model (`application/diagnostic_models.py`).** `Diagnostic` gains
`evidence_state: EvidenceState | None` (`CONFIRMED`, `NOT_PROVABLE`,
`UNAVAILABLE` — `UNAVAILABLE` means the rule was silent, not that
evidence was checked). `DiagnosticSource` names a finding's origin
(preflight / direct test / python environment / lifecycle / logs / plist),
and the frozen `DiagnosticGroup` / `DiagnosticReport` (`.all` flattens in
group order) carry the findings. The six frozen typed contexts —
`PreflightContext`, `DirectTestContext`, `PythonEnvironmentContext`,
`LifecycleContext`, `LogContext`, `InspectionContext` (union
`DiagnosticContext`) — are the engine's only inputs.

**Engine (`application/diagnostic_service.py`).**
`evaluate_diagnostic_report(*contexts)` is pure, accepts contexts in any
order, and emits groups in a pinned order (preflight, direct test,
lifecycle, logs, python environment, plist) with empty groups omitted.
New rules: `executable_not_found_runtime` (ERROR, direct test), broadened
`module_not_found` patterns (code unchanged), `log_path_unreadable`
(WARNING, logs), `bootstrap_failure` (ERROR, lifecycle — the
`InstallResult` bootstrap phase only), `malformed_plist` and
`invalid_plist_label` (ERROR, plist), `protected_path` (WARNING,
preflight, `NOT_PROVABLE`), and `architecture_mismatch` (WARNING,
preflight, `CONFIRMED`).

**Platform probes (`platform/macos/diagnostic_probes.py`).**
`probe_protected_paths(paths, *, home=None)` is pure path arithmetic over
roots (home's Desktop/Documents/Downloads/Movies/Music/Pictures,
home/Library/Mobile Documents, and /Users/Shared);
`probe_executable_architecture(executable, *, machine=None)` performs a
bounded Mach-O header read of at most 32 bytes — the magic is read
big-endian, so the little-endian `FAT_CIGAM` (0xBEBAFECA) dispatches to a
little-endian entry read, and only the first `fat_arch` entry is
parseable within the 32-byte window — and compares cputypes against
`platform.machine()`. The `DiagnosticProbes` protocol with its
`LocalDiagnosticProbes` implementation is injectable; probes never raise.

**Façade and surfacing.** `TaskCommandService` takes an optional `probes`
parameter and exposes `diagnostic_report_for(job, *, detection=None,
logs=None)`, `log_diagnostics_for(job, logs)`,
`lifecycle_diagnostics(label, action, result)`, and
`inspection_diagnostics(path, parsed)` — each returns the single group's
findings (empty tuple = silent). `DirectTestResult` gains
`report: DiagnosticReport` (default empty report; the legacy `diagnostics`
list is retained). GUI presentation: the presenter's `SOURCE_TITLES`
(human group titles), `format_evidence`, `format_diagnostic_block`
(parenthesized evidence suffix when set), `format_report`
(`== <title> ==` headings; "No diagnostics." when empty), and
`format_log_diagnostics` / `format_lifecycle_diagnostics` (a single
section, or `""` when empty); the diagnostics panel renders the grouped
report and appends the logs group; the lifecycle result dialog carries a
Diagnostics group hidden when there are no findings; the inspector's
`show_agent(*, diagnostics=())` appends a `plist diagnostics:` block to
the warnings. CLI: `inspect` appends a `diagnostics:` section when the
plist parse is not fully supported, and a failed `install` bootstrap
appends the lifecycle diagnostics to stderr; `test` rendering is
unchanged.

## Application-Observed Execution History (Increment 20)

The execution-history system is a metadata-only, append-only audit of what
the application itself observed.  It deliberately records nothing beyond the
metadata captured at application-service boundaries and never infers
scheduled executions from launchd state.

**Port/adapter split.** `application/history_models.py` owns the models:
`HistoryEventKind` (`direct_test`, `manual_run`, `status_observation`,
`diagnostic_result`), `HistoryOutcome` (`success`, `failure`, `observed`),
the frozen `HistoryEvent` dataclass (`created_at`, `job_id`, `label`,
`kind`, `outcome`, `exit_code`, `duration_seconds`, `loaded`,
`diagnostic_codes`), and the `HistoryRepository` Protocol port (`append` is
best-effort and never raises; `read` converts storage failures into a safe
`HistoryReadResult`, never exceptions).  The storage adapter
`storage/execution_history_repository.py` (`ExecutionHistoryRepository`)
implements the port with stdlib `sqlite3`.

**Table schema.** The append-only table `execution_history` has columns:
`id INTEGER PRIMARY KEY AUTOINCREMENT`, `created_at TEXT` (UTC ISO-8601),
`job_id TEXT` (UUID), `label TEXT`, `kind TEXT`, `outcome TEXT`,
`exit_code INTEGER` (NULL), `duration_seconds REAL` (NULL), `loaded
INTEGER` (NULL/0/1), `diagnostic_codes TEXT` (JSON array).  An index on
`(job_id, id)` supports efficient per-job reads.  The repository exposes no
UPDATE or DELETE — once appended, an event is immutable.
`default_history_path()` returns the database path beside the job catalog
(sibling of `jobs/`, in Application Support).

**Service-boundary recording rule.** `TaskCommandService` records at the
boundaries of `test_job`, `run_now`, and successful `status` façade calls:
two events per direct test (a `DIRECT_TEST` event then a
`DIAGNOSTIC_RESULT` event), one `MANUAL_RUN` per Run Now, one
`STATUS_OBSERVATION` per status check.  Unsaved drafts and lifecycle
operations record nothing.  Recording happens after the normal result is
produced and never modifies results.

**Best-effort writes.** A failed append never changes the operation's
result; the failure is discoverable only via history queries, which report
the safe unavailable state.

**Read path.** Both `mactask history` (CLI) and the GUI History panel go
through the same service façade `history(label, *, limit=50)` (default 50,
maximum 100), so CLI and GUI behave identically.

**Metadata-only stance (decision 8).** Events carry structured metadata
only — never raw output, environment values, or free text.

## External Plist Import (Increment 21)

The import pipeline bridges external, unmanaged LaunchAgent plists into the
application's managed job catalog without touching the source file or deploying
a plist to launchd.

**Reader → preview → commit flow.**
`TaskCommandService.preview_external_plist(path)` parses the plist read-only
via `PlistCodec.parse_path` and returns a frozen
`ExternalPlistImportPreview` DTO: the source path, a `JobDefinition` candidate (with
the parser's transient UUID carried but **not** used as the durable identity),
verbatim warnings, verbatim unsupported keys, and a
`requires_acknowledgement` flag.  The candidate is never persisted directly;
the commit path builds a fresh copy.

`TaskCommandService.import_external_plist(preview, *, acknowledge_partial)`
regenerates the durable identity (`uuid4()`), re-stamps the schema version on
a copy of the candidate, and delegates to `JobService.import_job`.  The
`requires_acknowledgement` flag gates the call — raising `ValueError` when
set and the caller did not pass `acknowledge_partial=True`.

**Fresh-ID commit.** The parser's transient UUID is never the durable identity.
`import_job` always generates a new `uuid4()` for the committed `JobDefinition`'s
`id` field.  The original label from the source plist is preserved verbatim.

**Catalog-only boundary.** The import commit writes **only** the managed JSON
catalog record.  No LaunchAgent plist is written, no log directories are
created, and `launchctl` is never invoked.  An imported job appears as
**Saved, not installed** until the user explicitly deploys it via the install
lifecycle path.

**Create-only semantics.** `JobService.import_job` is strictly create: it
raises `FileExistsError` when the destination catalog JSON already exists for
the new job id, and raises `JobConflictError` when a **different** managed
record already claims the same label.  Existing catalog records are never
overwritten by import.

**Label-conflict guard.** A duplicate label — i.e. another managed job that
already owns the label the import candidate would use — is rejected with
`JobConflictError` before any write occurs.

**Acknowledgement gate.** A partially supported plist (one that yields
warnings or unsupported keys) requires explicit acknowledgement before the
import can commit: a checkbox in the GUI dialog (`import-acknowledge`), or
the `--acknowledge-partial` CLI flag.  Without acknowledgement, the service
raises and no write occurs.

## Packaging Boundary (Increment 13)

The application runtime has no packaging logic. The `.app` bundle is built
by `pyside6-deploy` (Nuitka standalone mode) using a version-controlled
`pysidedeploy.spec` config at the repository root. The Makefile target
`make package` invokes the deploy tool and then post-processes the generated
`Contents/Info.plist` to set the Launch Services identity fields
(`CFBundleIdentifier` → `io.github.macos-task-scheduler`,
`CFBundleName`/`CFBundleDisplayName` → `macOS Task Scheduler for Humans`)
and re-signs with the current user's ad-hoc identity:

```bash
codesign --force --sign - "dist/macOS Task Scheduler for Humans.app"
```

This post-processing step is the only exception to the "spec-only deployment
fixes" decision — it is build tooling (never runtime code), required because
Nuitka derives the bundle identifier from the `app.py` stem.

The resulting bundle at `dist/macOS Task Scheduler for Humans.app` is fully
self-contained: all Qt frameworks, plugins, Python extensions, and the
compiled entry point are packaged inside. It requires no source checkout,
no activated venv, and no PATH setup to run.
