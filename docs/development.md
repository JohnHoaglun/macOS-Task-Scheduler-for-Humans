# Development — macOS Task Scheduler for Humans

## Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

This installs the package in editable mode plus all development
dependencies (pytest, pytest-cov, ruff, mypy).

## Makefile Targets

All targets use `.venv/bin/python`, so create the virtual environment
first.

| Command | Description |
|---|---|
| `make test` | Run unit tests |
| `make lint` | Run Ruff lint checks |
| `make format` | Format the codebase with Ruff |
| `make typecheck` | Run mypy on the source package |
| `make check` | Run lint, typecheck, and tests (the completion gate) |
| `make run-gui` | Start the GUI through the venv (`python -m task_scheduler.gui.app`) |
| `make package` | Build the standalone macOS `.app` bundle into `dist/` |

## Running Tests with Coverage

```bash
pytest --cov=task_scheduler --cov-report=term-missing
```

The source package maintains 100% line coverage.

## GUI (PySide6) Test Setup

The GUI is tested with pytest-qt and runs fully headless:

* `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`, so no display
  server is required on the test machine.
* `pyproject.toml` pins `qt_api = "pyside6"` for pytest-qt.
* Widget tests use the `qtbot` fixture together with the same
  `FakeTaskWorld`/`FakeProcessRunner` fakes and `tmp_path` roots as the CLI
  tests; no test may touch `~/Library/LaunchAgents` or invoke real
  `launchctl`.
* `make check` runs the GUI tests on every change; line coverage of the
  whole package stays at 100%.
* Startup geometry is tested through the pure
  `gui.app.startup_window_size(QSize | None)` helper: it prefers `1280x900`
  and bounds it to a supplied usable display size. Do not assert platform
  window-manager geometry in headless tests.
* Diagnostics widget tests assert collapsed startup state, explicit toggle
  behavior, and rendering without auto-expansion; main-window tests assert
  the inspector's right-pane stretch priority.

## Editor Dialog Test Conventions

The job editor tests (Crawl Increment 10) follow the setup above and add:

* `qtbot.addWidget` keeps the window or dialog under test alive for the
  test's duration.
* Editor widgets carry stable `objectName`s (`editor-name`, `editor-save`,
  `editor-weekday-monday`, `editor-time` / `editor-time-{i}` for time rows,
  `timerow-add` / `timerow-remove` for the row controls,
  `editor-schedule-kind` for the Calendar/Interval selector,
  `editor-calendar-schedule` / `editor-interval-schedule` for the stacked
  schedule pages, `editor-interval-value` / `editor-interval-unit` for the
  duration field, `editor-run-at-load` for the login checkbox); tests
  resolve them through small `findChild` helper functions rather than
  index-based access, so layout changes do not break tests.
* `TimeRowEditor` connects `textEdited` (not `textChanged`) so programmatic
  `setText` during a load does not re-fire the draft-changed pipeline. The
  same principle covers the schedule controls: the interval value field
  connects `textEdited`, and the schedule-kind, interval-unit, and
  run-at-login controls connect `currentIndexChanged` / `toggled`;
  programmatic `setCurrentIndex` / `setChecked` during a load does not fire
  them, so the final preview refresh at the end of a load is authoritative.
  Interval preview tests therefore type into the field (select-all plus key
  clicks) so the draft-changed pipeline actually runs.
* `FakeTaskWorld` (`tests/fakes.py`) builds the full service graph on
  `tmp_path` roots: catalog and LaunchAgents store under temporary
  directories, with the real `JobService`, `LaunchAgentStore`, and
  `LaunchAgentBackend` (over a `FakeProcessRunner`), plus `PlistCodec`,
  `DirectTestService`, and `LogService` composed into a
  `TaskCommandService`. `world.manage(job)` seeds a managed job (catalog
  record plus plist); `world.store.write(job)` adds an external agent.
  `world.launch_runner.specs` records every launchctl invocation, so a
  test can assert that saving a draft invoked none — the non-deployment
  guarantee.
* Modal dialogs are tested by scheduling the close or save with
  `QTimer.singleShot(0, ...)` before triggering the action
  (`new_task_action.trigger()`, `edit_task_action.trigger()`). A
  synchronous `exec()` would deadlock under single-threaded pytest-qt;
  status-bar hints are awaited with `qtbot.waitUntil`.

## Lifecycle Test Conventions (Increment 11)

The lifecycle tests follow the GUI setup above and add:

* `FakeTaskWorld` seeds the three row kinds: `world.manage(job)` creates an
  installed managed job (catalog record plus plist),
  `world.store.write(job)` adds an external agent, and
  `world.jobs.import_job(job)` saves a catalog-only (not-installed) job.
* Discovery itself issues `launchctl print` calls, so
  `world.launch_runner.specs` is non-empty before any lifecycle action.
  Assert on the lifecycle invocation itself — e.g.
  `any(spec.argv[1] == "disable" for spec in world.launch_runner.specs)` —
  or take a baseline count before the action.
* Multi-phase transaction tests script ordered results through
  `FakeProcessRunner` (stage → bootout → backup → activate → bootstrap) and
  assert which staged/backup sibling artifacts are retained on each failure
  mode.
* `LifecycleController` is Qt-free: request verdicts, gating, and
  exception-safe execution are tested without an event loop. The
  production `QThread` path is exercised end-to-end by tests that wait with
  `qtbot.waitUntil` for the `finished` outcome.
* Main-window lifecycle tests keep the UI synchronous with a
  `_capture_lifecycle` helper: it patches `LifecycleResultDialog.exec`
  (class level) to record the outcome and patches `window._start_worker` to
  connect `finished` and run the worker inline. `QMessageBox.question` is
  patched at class level (three-argument lambda).
* `qtbot.waitUntil` callbacks must return a bool (not a list), and tests
  hold strong references to temporary widgets — a PySide object created and
  discarded inside one expression is garbage-collected while the event loop
  still needs it.

## Diagnostics/Log Test Conventions (Increment 12)

The diagnostics and log tests follow the GUI setup above and add:

* `FakeTaskWorld` takes a `test=ProcessResult(...)` keyword for the direct
  test outcome (default: a successful exit-0 run). Error states are
  produced by monkeypatching `world.services.test_job` (service failure) or
  `world.services.validate_job` (invalid job), and by pointing the job's
  `LoggingConfig` at files under `tmp_path`.
* Log fixtures cover the four stream states directly: write a file for
  content, create an empty file for the empty case, leave the path missing
  for `Log unavailable: log file not found: ...`, and leave the path unset
  for `Log path not configured.`.
* Main-window tests keep the worker synchronous with a
  `_run_tests_synchronously` helper that patches `window._start_test_worker`
  to connect `finished` and run the worker inline; dialog tests use the
  real `QThread` path and wait as described below.
* Thread-teardown safety: a `QThread` must be on its way out before the
  test ends, or PySide aborts at teardown. `waitUntil(not busy)` is not
  enough — `busy` clears on the worker thread before the main loop
  dispatches the queued `finished`/`thread.quit`. Instead, wait on the
  main-thread-rendered artifact (e.g. the panel summary changing) in the
  same queued-signal batch, or, when nothing renders (the close-guard test),
  add a short `qtbot.wait(...)` after the busy wait to flush the queued
  quit and `deleteLater`.
* Environment comparisons are tested with an explicitly supplied
  terminal-environment mapping — never the real `os.environ` — and assert
  on names/categories, not values.

## Python Detection Test Conventions (Increments 18 and 23)

* `detect_python` accepts an injected read-only filesystem view
  (`PythonDetectorFilesystem`); the detector unit tests use a dict-backed
  fake (`FakePythonDetectorFilesystem`: file mapping plus `executable`,
  `dirs`, and `unreadable` path sets) so synthetic projects — marker
  files, `[tool.uv]` / `[tool.poetry]` tables, unreadable or malformed
  `pyproject.toml` content — are deterministic strings and the tests never
  depend on the host's Python installation, PATH, or directory layout.
* All detector unit tests live in one module
  (`tests/unit/platform/test_python_detection.py`). Each detector's
  `detect(context)` is exercised in isolation via the
  `detect_context(script, fs, roots)` helper (which builds a
  `DetectionContext`), and a compact `_roots(pyenv=(), conda=(),
  homebrew=())` helper builds a `PythonDetectionRoots`. The pyenv, Conda,
  and Homebrew detectors read only the injected roots, so their tests pin
  every probe path through `PythonDetectionRoots` rather than a live home
  directory; a marker that is absent yields an empty
  `DetectorContribution()` (asserted verbatim).
* Non-fatal detection notes are asserted verbatim (detector kind plus
  exact message), in detector-execution order — including the per-detector
  "no usable … interpreter is available" notes for uv, Poetry, Pipenv,
  pyenv, and Conda.
* A small set of tests still drives the default
  `LocalPythonDetectorFilesystem` over real `tmp_path` files to cover the
  live reader itself (including its `read_text` error path).
* Job-editor tests keep using the canned `fake_detection` responder
  (now with an optional `notes` argument); presenter tests build
  `PythonDetectionResult` values directly with explicit `detectors` and
  `notes`.

## Expanded Diagnostics Test Conventions (Increment 19)

* `FakeTaskWorld` takes a `probes=FakeDiagnosticProbes()` keyword (forwarded
  to `TaskCommandService`); the fake records every
  `probe_protected_paths` / `probe_executable_architecture` call and
  returns the findings constructed by the test, so rule wiring is asserted
  alongside the exact probe-call arguments (the path tuple, the `machine`
  string).
* The preflight path tuple derives from the job (executable, script,
  working directory); the default `make_job()` fixture yields exactly two
  paths because its working directory is `None`.
* Mach-O fixtures are struct-packed byte buffers written to `tmp_path`
  files: the four magic bytes are always packed big-endian (a
  little-endian fat holds 0xBEBAFECA as the bytes BE BA FE CA), while the
  `nfat` count and entry fields follow the file's own endianness. The
  probe's 32-byte read bound is exercised by fixture length: only the
  first `fat_arch` entry of a multi-arch fat reaches the parser, and a
  file shorter than one full entry after the magic and count is silent.
* Report assertions build `DiagnosticReport` / `DiagnosticGroup` values
  directly (or monkeypatch a façade method) and pin the pinned group
  order, empty-group omission, and the evidence-suffixed rendering wording
  verbatim; GUI tests assert the exact pane/dialog text, including the
  `== <title> ==` headings and the "No diagnostics." states.

## Execution-History Test Conventions (Increment 20)

Service tests use the real temp-rooted repository wired into
`FakeTaskWorld` (`tmp_path / "history.sqlite3"`) — there is no fake
repository for history at the service layer.  Storage tests use `tmp_path`
directly.  Event fixtures pass explicit `created_at` values (tz-aware UTC);
tests never assert wall-clock values, only UTC-ness of service-stamped
events.  The corrupt-database fixture writes garbage bytes to a `.sqlite3`
path before construction to exercise the unavailable-error path.  Unit
tests never touch the host database (the real
`~/Library/Application Support` location).

## Import Test Conventions (Increment 21)

* External plist fixtures live under a temporary `~/Library/LaunchAgents`
  root (e.g. `tmp_path / "Library" / "LaunchAgents"`) so discovery resolves
  them through the normal `LaunchAgentStore` path without touching the live
  system directory.
* A source-byte-preservation assertion reads the fixture file's bytes before
  the import commit and re-reads them after, asserting exact equality —
  confirming the source plist is never modified.
* The no-launchctl-call-log gate uses `FakeTaskWorld.launch_runner.specs`
  to assert the import path issued zero `launchctl` invocations;
  `world.launch_runner.specs` is empty after `import_external_plist` or the
  CLI import command, regardless of outcome.
* The catalogue-only boundary is verified by asserting that the LaunchAgents
  root contains no new files after a successful import commit, and that the
  only new filesystem artifact is the single expected catalog JSON file
  (named by the regenerated job id).
* Acknowledgement-gate tests cover: (a) a fully supported plist imports
  directly without a flag/checkbox; (b) a partially supported plist with
  the acknowledgement flag/checkbox commits successfully; (c) a partially
  supported plist without acknowledgement raises `ValueError` (CLI exits
  2, GUI dialog stays open with Import disabled); (d) an `INVALID` or
  no-job parse raises `ValueError` with no write; (e) a duplicate label
  raises `JobConflictError` with no write.
* Composition gates assert: source plist bytes unchanged, the catalog change
  is exactly one new `.json` file, the LaunchAgents root is absent/new, and
  all call logs (launchctl + direct-test) are empty.

## Opt-in System Integration Tests

The `tests/integration/` tests exercise the real
`~/Library/LaunchAgents` directory and `/bin/launchctl`. They are excluded
from every default run (the `integration` marker in `pyproject.toml`
addopts) and skip unless the environment variable is set:

```bash
MACTASK_ALLOW_SYSTEM_TESTS=1 make integration
```

Each test job uses a unique UUID-based label, and cleanup is unconditional
in fixture teardown, touching only the test-owned plist. Plain `pytest`,
`make test`, and `make check` never run them.

## Packaging (Increment 13)

The standalone `.app` bundle is built with PySide6's
`pyside6-deploy` (Nuitka standalone mode) and re-signed with the current
user's ad-hoc identity.

### Build Process

```bash
make package
```

This runs `.venv/bin/pyside6-deploy -c pysidedeploy.spec -f`, which:

1. Installs Nuitka==4.1.1 into a temporary Python environment
2. Compiles `src/task_scheduler/gui/app.py` into a standalone `.app`
3. Copies the bundle to `dist/macOS Task Scheduler for Humans.app`
4. Rewrites `pysidedeploy.spec` with the resolved modules/plugins

The Makefile then post-processes the generated `Contents/Info.plist` to set
the correct `CFBundleIdentifier`/`CFBundleName`/`CFBundleDisplayName` values
(Nuitka defaults to the executable stem `app`), and re-signs:

```bash
codesign --force --sign - "dist/macOS Task Scheduler for Humans.app"
```

(`deployment/` and `dist/` are Git-ignored.)

### Bundle Smoke Test

To verify the generated bundle:

```bash
open "dist/macOS Task Scheduler for Humans.app"
```

The app should open without Terminal, Terminal, or an activated venv,
discover LaunchAgents safely, and show the main window. The bundle runs
without PATH, venv, or source-checkout dependencies — it is self-contained.

## Managed JSON Transfer Test Conventions (Increment 22)

* Strict-decode tests build explicit JSON strings and assert the exact
  `StrictJsonDecodeError` message for: malformed JSON (non-object top level,
  unclosed braces), unsupported schema version, and unknown fields at every
  accepted level (top-level, command by type, schedule by kind, environment,
  logging).  v1 payloads (`schema_version: 1` with `schedule.time` +
  `schedule.weekdays`) parse without error and are migrated to v2 by
  `JsonJobRepository.load_text()` inside the strict path.  Tests assert that
  the permissive `validate_json()` path remains unchanged.
* Transfer-conflict tests use `FakeTaskWorld` with seeded catalog records:
  a duplicate-UUID record and a duplicate-label record that exercise both
  `id_conflict_path` and `label_conflict_path` independently, together, and
  neither.  The commit-time conflict gate is verified by confirming that a
  conflict introduced between `preview_managed_json_import` and
  `import_managed_json` raises `JobConflictError` with no write.
* CLI `export-json`/`import-json` tests drive the commands through
  `CliRunner` + `FakeTaskWorld`.  Exit-code gates: `0` for success (verify
  the summary line on stdout), `2` for not-found/ambiguous label, existing
  destination, decode failure, and id/label conflict.  Create-only and
  no-deploy gates use `world.launch_runner.specs` (zero launchctl calls),
  catalog-only boundary assertions (exactly one new catalog JSON file, no
  plist, no log directory, source bytes unchanged), and identity-preservation
  assertions (imported job's `id` matches the exported file).
* The finder adapter is tested with `FakeFinderRevealer` injected into
  `FakeTaskWorld`: success (returns `None`), non-zero exit code, and launch
  failure paths; tests assert that `FakeTaskWorld` records zero Finder
  calls during normal test runs and that `reveal_path` returns a stable
  "path does not exist" message for absent targets.
* GUI proxy/badge tests use `qtbot` on the offscreen platform.  The
  `AgentFilterProxyModel` is tested by feeding `AgentTableModel` with
  known listings and asserting filter outcomes against typed roles
  (`ROLE_STATE`, `ROLE_INSTALLED`, `ROLE_ENABLED`, `ROLE_LOADED`,
  `ROLE_COMMAND`, `ROLE_SEARCH_TEXT`) rather than display strings.  The
  pure badge presenter is tested with explicit `TaskListing` fixtures for
  every state value.
* The CLI `export-json` command is also tested with `FakeTaskWorld` to
  confirm that `world.launch_runner.specs` and `world.launch_runner.specs`
  for direct tests and Finder reveal calls remain empty — the transfer path
  never invokes the process runner.

## Current State

Crawl increments 0–13 establish:

- project/tooling foundation
- normalized job domain model with Pydantic validation
- schema-versioned JSON persistence (storage layer)
- LaunchAgent plist generation and parsing (macOS platform layer)
- LaunchAgent store (write, remove, discovery) in `~/Library/LaunchAgents`
- `launchctl` backend behind an injectable process runner
- application services: job service, log service, and the
  `TaskCommandService` facade
- `mactask` CLI (Typer): list, inspect, validate, generate, install,
  uninstall, enable, disable, status, run, test, logs
- read-only PySide6 GUI discovery browser (`mactask-gui`) over the shared
  `TaskCommandService` facade
- GUI job editor (`mactask-gui`): New Task / Edit Managed Task dialog with
  validation, plist preview, and catalog-only save
- GUI lifecycle controls (`mactask-gui`): install, reinstall, uninstall,
  enable, disable, run now over a Qt-free controller and `QThread` worker;
  saved jobs listed as `Saved, not installed`; staged reinstall transaction
  with retained artifacts on failure
- GUI diagnostics and logs (`mactask-gui`): direct tests of managed tasks
  and validated editor drafts (job-based façade contracts, `Test Draft`
  persists nothing), structured diagnostics, direct/persisted stdout/stderr
  with Refresh, name-only environment comparison, Python recommendations
- Standalone macOS `.app` bundle (`make package`): Nuitka standalone build,
  post-process `Info.plist` identity, ad-hoc re-sign, self-contained no-venv
  launch with Discovery, editor, lifecycle, and diagnostics

Unit and GUI widget tests run against synthetic fakes and temporary
directories and never touch `~/Library/LaunchAgents` or invoke real
`launchctl`; GUI tests run headless via the offscreen Qt platform (see the
GUI test setup above). Opt-in system integration tests are described in the
section above.
