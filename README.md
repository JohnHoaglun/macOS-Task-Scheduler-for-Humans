# macOS Task Scheduler for Humans

A human-friendly macOS task scheduler built on top of Apple's `launchd`.

The goal of this project is to make scheduled jobs easier to create, understand, test, and troubleshoot without requiring users to manually write plist files or memorize `launchctl` commands.

The application is being built primarily in Python and will eventually provide both a graphical desktop interface and a command-line interface.

## Why This Project Exists

macOS uses `launchd` for scheduled and background tasks. It is powerful, but the configuration model can be difficult to work with directly.

Creating even a simple scheduled task can require understanding:

* LaunchAgent plist structure
* `ProgramArguments`
* `StartCalendarInterval`
* working directories
* environment variables
* stdout and stderr paths
* `launchctl`
* execution context
* macOS permissions

Python applications add another common problem:

> A script works perfectly from Terminal but fails when it runs as a scheduled task.

This often happens because a scheduled process does not inherit the same environment as an interactive shell.

Common causes include:

* the wrong Python interpreter
* a virtual environment not being used
* a different `PATH`
* missing environment variables
* relative file paths
* an unexpected working directory
* unavailable dependencies
* filesystem or macOS permission restrictions

**macOS Task Scheduler for Humans** is intended to make those differences visible and understandable.

## Product Direction

The application is not intended to be a generic plist editor.

Instead, it models the user's intent:

```text
Run this Python script
Monday through Friday
at 7:30 AM
using this virtual environment
and save stdout/stderr here.
```

The application then translates that definition into the appropriate macOS `launchd` configuration.

The core design is:

```text
Human intent
     ↓
Job Definition
     ↓
Validation
     ↓
LaunchAgent configuration
     ↓
launchd
```

Advanced users will still be able to inspect the generated plist and underlying launchd configuration.

## Development Phases

Development follows a **Crawl → Walk → Run** model.

### Crawl

The initial release focuses on user-level LaunchAgents.

Planned capabilities include:

* discover existing user LaunchAgents
* visualize common LaunchAgent configurations
* create scheduled tasks
* run Python scripts
* run shell scripts or commands
* run arbitrary executables
* schedule a task at a specific time on selected days
* detect common Python virtual environments
* configure the working directory
* configure environment variables
* automatically capture stdout and stderr
* test a task before installing it
* install, enable, disable, trigger, and remove managed LaunchAgents
* provide useful diagnostics when a task fails

The first implementation increments focus only on the core architecture:

1. project foundation
2. domain model and JSON persistence
3. plist generation
4. plist parsing

These initial increments do **not** modify the user's LaunchAgents or invoke `launchctl`.

### Walk

The Walk phase will expand scheduling, diagnostics, Python environment detection, execution history, job importing, and task visualization.

Potential features include:

* multiple execution times
* interval schedules
* run-at-login
* additional Python environment detection
* richer diagnostics
* execution history
* next-run previews
* importing existing LaunchAgents as managed jobs

### Run

The Run phase will add support for system-level scheduled tasks that can execute even when the user is not logged in.

This will likely introduce a small native macOS component for ServiceManagement and privileged operations while keeping the main application architecture Python-based.

The GUI itself will not run as root.

## Architecture

The domain model is the application's source of truth.

A plist is considered a macOS deployment representation, not the primary application database.

```text
GUI                         CLI
 │                           │
 └──────── Application ──────┘
              │
            Domain
              │
        Platform adapters
              │
            launchd
```

The project is intentionally structured so that:

* GUI logic does not manipulate plist files directly
* GUI logic does not invoke `launchctl` directly
* CLI and GUI use the same application services
* macOS-specific behavior is isolated behind platform components
* most application logic can be unit tested without modifying the local Mac

## Technology Stack

Current technology decisions:

* Python 3.12+
* Pydantic 2.x
* Typer (CLI)
* PySide6 / Qt Widgets (GUI)
* `plistlib`
* pytest
* pytest-cov
* pytest-qt
* Ruff
* mypy

The project intentionally avoids introducing a web backend or JavaScript frontend unless a future requirement makes one necessary.

## Repository Structure

The initial structure is expected to resemble:

```text
src/
└── task_scheduler/
    ├── application/
    ├── cli/
    ├── domain/
    ├── gui/
    ├── platform/
    │   └── macos/
    └── storage/

tests/
├── unit/
├── fixtures/
└── golden/

docs/
├── architecture.md
└── development.md
```

The GUI layer will be added incrementally.

## Development Requirements

### Python

Python 3.12 or later is required.

Check your version with:

```bash
python3 --version
```

### Create a Virtual Environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade packaging tools:

```bash
python -m pip install --upgrade pip
```

Install the project and development dependencies:

```bash
pip install -e ".[dev]"
```

The exact dependency installation command may evolve as the project configuration is finalized.

## Development Commands

The repository provides standard `make` targets.

### Run unit tests

```bash
make test
```

### Run lint checks

```bash
make lint
```

### Format the code

```bash
make format
```

### Run static type checks

```bash
make typecheck
```

### Run the standard verification suite

```bash
make check
```

`make check` is the standard completion gate for development work.

A feature should not be considered complete unless it passes.

## Running Tests Directly

Tests can also be run with pytest:

```bash
pytest
```

With coverage:

```bash
pytest --cov=task_scheduler --cov-report=term-missing
```

The source package maintains 100% line coverage, enforced with every change.

Tests should focus on meaningful behavioral coverage rather than increasing coverage numbers artificially.

## Testing Safety

Unit tests must not:

* modify `~/Library/LaunchAgents`
* modify `/Library/LaunchAgents`
* modify `/Library/LaunchDaemons`
* invoke `launchctl`
* depend on the current user's actual scheduled jobs
* depend on installed Python environments outside the test fixtures

Operating-system integration tests will be introduced separately and will require an explicit opt-in before making changes to the local machine.

A normal:

```bash
pytest
```

or:

```bash
make test
```

must always be safe to run.

## Coding Guidelines

This project is intended to work well with both human developers and AI coding agents.

### Module Size

Logic-heavy Python source files must remain under:

```text
500 lines
```

At approximately 400–450 lines, the module should be reviewed for decomposition.

The goal is not to create 499-line modules. Prefer smaller, focused components.

### Function Size

Functions should generally remain below approximately 50 lines.

Functions exceeding approximately 75 lines should be reviewed for possible decomposition.

### Separation of Responsibilities

Avoid generic dumping-ground modules such as:

```text
utils.py
helpers.py
common.py
misc.py
```

Prefer modules with explicit responsibilities.

### Type Hints

Public application functions and methods should use type annotations.

### Tests

Changes that introduce application logic should include corresponding tests.

### Platform Side Effects

Operating-system interactions must be isolated behind dedicated platform abstractions.

Future GUI components must not directly:

```python
subprocess.run(...)
```

or write LaunchAgent plist files.

## Command-Line Interface

The `mactask` command manages jobs through the same application services
the future GUI will use:

```bash
mactask list
mactask inspect <job>
mactask validate <file.json>
mactask generate <file.json>
mactask install <file.json>
mactask uninstall <job>
mactask enable <job>
mactask disable <job>
mactask status <job>
mactask run <job>
mactask test <job>
mactask logs <job>
```

`<job>` is the exact launchd label of a managed job, resolved from the
application's JSON job catalog. `install` is create-only: it fails if a
managed job with the same label already exists. `validate` and `generate`
take a job definition JSON file; `generate` prints the LaunchAgent plist
XML without writing anything.

Exit codes:

* `0` — success
* `1` — launchd operation failed (bootstrap, bootout, print, kickstart, ...)
* `2` — usage error: invalid label, invalid or unreadable JSON, conflicting
  job, missing log configuration, or unknown job

Reports and generated plist XML go to stdout; errors and diagnostics go to
stderr.

## Graphical Interface

A discovery GUI with a job editor and lifecycle controls is available
(Crawl Increments 9–11).

Launch it from the repository root with the virtual environment active:

```bash
mactask-gui
```

The main window lists every LaunchAgent discovered under
`~/Library/LaunchAgents` — application-managed jobs, external agents created
by other software, and malformed or unsupported plists — plus managed jobs
saved in the task catalog but not yet installed (shown with the state
**Saved, not installed**), and inspects the selected agent in a read-only
detail panel:

* Overview: name, label, classification, source plist path, state, enabled
  state, launchd load status
* Command: full command line and working directory
* Schedule: plain-language schedule text
* Environment: configured environment variables
* Warnings: parser warnings and unsupported plist keys
* Advanced: the raw plist (XML)

Each agent is classified as **Managed** (managed by this application's job
catalog), **External** (a valid plist outside the catalog), or **Invalid**
(malformed or unsupported). The Refresh action (File menu, `Cmd+R`) re-runs
discovery; the selected agent is preserved across refreshes when possible.

The File menu also offers **New Task...** (`Cmd+N`) and **Edit Managed
Task...**. Both open a modal editor dialog for a managed job:

* **New Task** starts blank — no command paths and no schedule — and is
  invalid until the name, the command fields of the selected kind, a valid
  `HH:MM` time, and at least one weekday are filled in.
* **Edit Managed Task** works only for a selected row classified as
  **Managed**, and resolves the catalog job by its launchd label. A
  selection that cannot be parsed, or a label missing from the catalog,
  surfaces as a status-bar hint instead of opening the dialog.

The dialog is a scrollable form with the following sections:

* **Identity** — the job name and the managed label. The label is
  auto-derived as `io.github.macos-task-scheduler.user.<slug>-<8-hex>` (the
  name slug plus the first 8 hex characters of the job's UUID); it stays
  manually editable and is validated like any other field.
* **Command** — a Python / Shell / Executable selector with a page per
  kind, each with a row table of arguments. On the Python page, editing
  the script path runs interpreter detection: candidates are listed as
  `path (source)` (sources: `.venv`, `venv`, `current`, `path`), and the
  **Use** button fills the interpreter field — and the working directory
  while it is blank — from the detection result. Informative notes cover
  the idle and no-match cases.
* **Schedule** — an `HH:MM` time and seven weekday checkboxes, plus a note
  on launchd behavior: if the Mac is asleep at the scheduled time it is
  not woken, and missed runs are not retried.
* **Environment** — key/value rows for the job's environment variables.
* **Advanced** — the working directory and optional stdout/stderr log
  paths; leave a path empty to disable that stream. The default log root
  for managed jobs is
  `~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/`.
* **Preview** — the generated plist XML, read-only.

**Validate**, **Preview**, **Save**, and **Close** act on the draft. Save
validates before writing anything; it starts enabled, is disabled after a
known-invalid result, and is re-enabled by any subsequent draft change. An
invalid draft is never persisted.

**Save does not deploy.** Saving a new or edited task writes or overwrites
the job's catalog JSON only — same immutable job id, and a label conflict
with a different managed job is rejected. It writes no plist, invokes no
`launchctl`, and creates no log directories. A saved task appears in the
main list with the state **Saved, not installed** until it is deployed with
**Install** (see the Lifecycle section below).

**Lifecycle controls.** The Lifecycle menu deploys and manages the selected
managed task:

* **Install** — imports the saved task into the catalog (skipped when the
  same job id is already saved), writes its LaunchAgent plist, and
  bootstraps it into launchd. Available only for rows in the
  **Saved, not installed** state.
* **Reinstall...** — re-applies the task's current catalog definition
  through an explicit staged transaction.
* **Uninstall...** — boots the task out of launchd, removes its plist, and
  removes its catalog record; the task then leaves the list.
* **Enable** / **Disable** — set launchd's enable state for the task
  without touching its definition.
* **Run Now** — asks launchd to start the task immediately
  (`kickstart -k`).

Availability depends on the selection: a **Saved, not installed** row
offers **Install** only; an installed managed row offers the other five
actions; external, invalid, or unselected rows offer none. While an
operation is running, all six lifecycle actions (and New Task / Edit
Managed Task) are disabled.

**Reinstall** and **Uninstall** ask for confirmation first, naming the
task and its exact label and noting that the operation affects the current
user's LaunchAgents only.

Reinstall is an explicit staged transaction: the freshly generated plist is
written as a uniquely named staged sibling file, the label is booted out,
the deployed plist is preserved as a uniquely named backup sibling, the
staged plist is atomically activated, and the label is bootstrapped. If a
phase fails, the artifacts that phase could not clean up are kept in place
for diagnosis — the transaction never claims a rollback — and the result
dialog's technical details list every attempted phase, the phases that
completed, and any retained artifacts. A successful reinstall removes the
backup and retains nothing.

The **State** column and the inspector's Overview show the task's state:
**Saved, not installed** for catalog-only jobs;
**Installed, configured enabled (loaded)**,
**Installed, configured enabled (not loaded)**,
**Installed, configured disabled (loaded)**, and
**Installed, configured disabled (not loaded)** for installed jobs, where
"configured" is the job's definition and "loaded" is launchd's actual load
state; **Status unknown** when either side cannot be determined. The table
column shows the configured part only; the full combined state is in the
inspector.

After a successful operation the list refreshes and a result dialog shows
the headline (succeeded/failed), the launchd exit code, the raw stdout and
stderr (when any), and an expandable technical-details pane.

**User-only safety boundary:** every lifecycle operation applies to the
current user's LaunchAgents in `~/Library/LaunchAgents` (launchd domain
`gui/<uid>`) and nothing else. The confirmations state this explicitly, and
the application services refuse lifecycle operations for any label that is
not a managed catalog job.

**Read-only external-job policy:** the GUI discovers and displays external
and invalid agents but never modifies them. No edit, install, enable,
disable, or removal controls exist for agents the application does not
manage.

## Current Status

The project is currently in the **Crawl** phase.

Current implementation scope:

* repository/tooling foundation
* normalized job domain model
* schema-versioned JSON persistence
* LaunchAgent plist generation
* LaunchAgent plist parsing
* LaunchAgent store (write, remove, discovery in `~/Library/LaunchAgents`)
* `launchctl` backend (bootstrap, bootout, print, kickstart, enable, disable)
* application services (job service, log service, task command service)
* `mactask` CLI (list, inspect, validate, generate, install, uninstall,
  enable, disable, status, run, test, logs)
* read-only PySide6 GUI discovery browser (`mactask-gui`) with
  managed/external/invalid classification and detail inspector
* GUI job editor (`mactask-gui`): New Task / Edit Managed Task dialog with
  validation, plist preview, and catalog-only save
* GUI lifecycle controls (`mactask-gui`): install, reinstall, uninstall,
  enable, disable, and run now; saved (not-installed) jobs listed with the
  managed jobs; staged reinstall transaction with retained artifacts

Not yet implemented:

* GUI diagnostics and logs (Crawl Increment 12)
* Python virtual-environment detection
* LaunchDaemon support
* privileged helpers
* signing/notarization

## Initial Scheduling Model

The first scheduling model intentionally remains simple.

A task may run at:

* one specific time
* on one or more selected weekdays

For example:

```text
07:30

Monday
Wednesday
Friday
```

More advanced scheduling will be added incrementally after the core implementation is stable.

## Supported Task Types

The initial domain model supports:

### Python

An explicit Python interpreter, script, and arguments.

Example:

```text
/Users/example/project/.venv/bin/python
/Users/example/project/main.py
--mode
daily
```

### Shell

An explicit shell executable and arguments.

Example:

```text
/bin/zsh
/Users/example/scripts/backup.sh
```

### Executable

An arbitrary executable and argument list.

Example:

```text
/opt/homebrew/bin/some-tool
--sync
```

Absolute paths are preferred so scheduled execution does not unexpectedly depend on an interactive shell's `PATH`.

## JSON Job Definitions

Managed jobs will use a schema-versioned, human-readable JSON representation.

Conceptually:

```json
{
  "schema_version": 1,
  "name": "Daily Backup",
  "label": "io.github.macos-task-scheduler.user.daily-backup",
  "enabled": true,
  "command": {
    "type": "python",
    "interpreter": "/Users/example/project/.venv/bin/python",
    "script": "/Users/example/project/main.py",
    "arguments": []
  },
  "schedule": {
    "time": "07:30",
    "weekdays": [
      "monday",
      "wednesday",
      "friday"
    ]
  },
  "environment": {
    "variables": {}
  },
  "working_directory": "/Users/example/project"
}
```

The exact schema may evolve while the initial domain model is being implemented.

## Open Source

This project is intended to be open source.

The initial licensing choice is MIT unless changed before the first public release.

## Contributing

The project is still in its foundational stage.

Before submitting changes:

```bash
make check
```

must pass.

Changes should:

* remain focused
* include appropriate tests
* preserve architectural boundaries
* avoid unnecessary dependencies
* avoid large modules
* avoid mixing UI, domain, persistence, and operating-system logic

More detailed contribution guidance may be added as the project matures.

## License

MIT
