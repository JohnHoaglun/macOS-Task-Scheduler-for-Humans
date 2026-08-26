# macOS Task Scheduler for Humans

## Application Build Specification

**Working name:** macOS Task Scheduler for Humans  
**Primary platform:** macOS  
**Primary language:** Python 3.12+  
**GUI:** PySide6 / Qt Widgets  
**CLI:** Typer  
**Testing:** pytest  
**Initial execution model:** Per-user `LaunchAgent`  
**Long-term execution model:** User `LaunchAgent` + privileged/system `LaunchDaemon` support  
**Project intent:** Open source  
**Primary development workflow:** AI-assisted/vibe coding using OpenCode or equivalent coding agents

---

# 1. Executive Summary

macOS Task Scheduler for Humans is a graphical and command-line utility that makes Apple's `launchd` scheduling system understandable and usable without requiring the user to manually author property-list files or memorize `launchctl` commands.

The application should allow users to:

- discover existing scheduled user jobs;
    
- understand what those jobs do;
    
- create new scheduled jobs through a graphical interface;
    
- schedule jobs for specific times on selected days;
    
- run Python scripts, shell scripts/commands, and executables;
    
- detect common Python execution environments;
    
- identify differences between interactive-shell execution and scheduled execution;
    
- generate valid LaunchAgent plist files;
    
- install, remove, reload, enable, disable, and test jobs;
    
- capture stdout and stderr automatically;
    
- troubleshoot failed scheduled executions;
    
- expose advanced `launchd` configuration without requiring it for ordinary use.
    

The product should serve two audiences simultaneously:

1. technical users who want a faster, safer interface to `launchd`;
    
2. users who know little about plist files or `launchd` and simply want to schedule something.
    

The application must therefore use plain language in the primary interface while preserving access to native launchd concepts in an Advanced view.

---

# 2. Problem Statement

macOS supports scheduled and background execution primarily through `launchd`.

Although powerful, `launchd` is difficult for ordinary users and unnecessarily cumbersome even for experienced developers.

Creating a scheduled task typically requires understanding:

- plist structure;
    
- LaunchAgent locations;
    
- launchd labels;
    
- `ProgramArguments`;
    
- `StartCalendarInterval`;
    
- `WorkingDirectory`;
    
- environment variables;
    
- stdout/stderr paths;
    
- `launchctl` commands;
    
- bootstrap domains;
    
- job state;
    
- filesystem permissions;
    
- execution context;
    
- macOS privacy restrictions.
    

A particularly confusing problem occurs with Python applications.

A Python script may execute correctly from Terminal but fail under cron or launchd because the scheduled process does not automatically inherit the developer's interactive shell environment.

Common causes include:

- different `PATH`;
    
- incorrect Python interpreter;
    
- virtual environment not activated;
    
- relative paths;
    
- missing working directory;
    
- environment variables not present;
    
- shell initialization scripts not executed;
    
- Homebrew tools not available on the scheduler's PATH;
    
- dependency installed in one Python environment but not another;
    
- filesystem or privacy permissions.
    

The user generally experiences this as:

> "It works when I run it manually, but nothing happens when it is scheduled."

The product should make that failure mode diagnosable.

---

# 3. Product Rationale

The product should not be designed primarily as a plist editor.

A plist editor exposes implementation details.

Instead, the product should provide a **task scheduling domain model** that happens to generate launchd configuration.

The conceptual workflow should be:

```text
Human intent
     ↓
Task Definition
     ↓
Validation
     ↓
macOS Scheduling Model
     ↓
Generated plist
     ↓
launchctl / launchd
```

A user should think:

> Run this Python script Monday through Friday at 7:00 AM.

The application should translate that into launchd configuration.

Users who want to understand the translation should be able to inspect it.

---

# 4. Product Principles

## 4.1 Human-first

Prefer:

```text
Run every Monday, Wednesday, and Friday at 7:30 AM
```

over:

```text
StartCalendarInterval
Hour = 7
Minute = 30
Weekday = ...
```

Native terminology belongs in Advanced views.

---

## 4.2 Safe by default

The application should not modify arbitrary third-party LaunchAgents without deliberate user action.

Discovered jobs must be classified as:

```text
Managed
Imported
External
System / Vendor
```

Unknown and vendor jobs default to read-only.

---

## 4.3 Explain failures

A failure message such as:

```text
Process exited with code 1
```

is insufficient.

Prefer:

```text
Python executable:
/usr/bin/python3

Your selected project appears to use:
/Users/me/project/.venv/bin/python

The scheduled task may be using the wrong Python environment.
```

---

## 4.4 One core, multiple interfaces

GUI and CLI must use the same core application services.

Do not independently implement scheduling logic in each interface.

```text
              ┌─────────────┐
              │ PySide6 GUI │
              └──────┬──────┘
                     │
                     ↓
               Application API
                     ↑
                     │
              ┌──────┴──────┐
              │  Typer CLI  │
              └─────────────┘
```

---

## 4.5 Testability before convenience

Operating-system interactions must sit behind interfaces that can be substituted with fakes during tests.

Most tests must run without modifying:

```text
~/Library/LaunchAgents
```

and without invoking real `launchctl` operations.

---

# 5. Technology Decisions

## 5.1 Python

Target:

```text
Python >= 3.12
```

Do not depend on Apple's system Python.

Development occurs inside a project virtual environment.

---

## 5.2 PySide6

Use:

```text
PySide6
Qt Widgets
```

rather than QML for the initial application.

Qt for Python is the official Python binding for Qt and supports Python 3.10+; Qt recommends use of a virtual environment. ([Qt Documentation](https://doc.qt.io/qtforpython-6/gettingstarted.html?utm_source=chatgpt.com "Getting Started - Qt for Python"))

Qt Widgets are preferred because the application consists primarily of:

- tables;
    
- forms;
    
- inspectors;
    
- dialogs;
    
- logs;
    
- navigation panes;
    
- configuration panels.
    

---

## 5.3 Packaging

Use:

```text
pyside6-deploy
```

as the initial packaging approach.

Qt documents `pyside6-deploy` as its deployment utility and supports creation of a macOS `.app` bundle. ([Qt Documentation](https://doc.qt.io/qtforpython-6.8/deployment/index.html?utm_source=chatgpt.com "Deployment - Qt for Python"))

A usable `.app` bundle is part of the Crawl definition of done.

---

## 5.4 Domain Models

Use:

```text
Pydantic
```

for persistent/configuration models where validation and serialization are valuable.

Ordinary dataclasses may be used for small internal transient structures.

---

## 5.5 plist handling

Use the Python standard library:

```python
plistlib
```

Never construct plist XML manually using string concatenation.

---

## 5.6 CLI

Use:

```text
Typer
```

The CLI is a first-class application interface.

It is not merely a debugging utility.

---

## 5.7 Persistence

Use a normalized internal job definition.

Initially store application-created job definitions as human-readable JSON.

Do **not** make the generated plist the application database.

Conceptually:

```text
job.json
   ↓
Job model
   ↓
plist generator
   ↓
installed plist
```

Later versions may introduce SQLite for execution history and metadata.

---

# 6. Architectural Boundaries

The application should contain four major architectural layers.

```text
┌─────────────────────────────────────┐
│ Presentation                        │
│                                     │
│ PySide6 GUI          Typer CLI      │
├─────────────────────────────────────┤
│ Application Services                │
│                                     │
│ create / validate / install / test  │
├─────────────────────────────────────┤
│ Domain                              │
│                                     │
│ Job / Schedule / Environment        │
├─────────────────────────────────────┤
│ Platform                            │
│                                     │
│ plist / launchctl / filesystem      │
└─────────────────────────────────────┘
```

Dependencies flow downward.

The Domain layer must not import PySide6.

---

# 7. Repository Structure

Recommended initial structure:

```text
macos-task-scheduler/
│
├── pyproject.toml
├── README.md
├── LICENSE
├── Makefile
├── .gitignore
├── ruff.toml
│
├── src/
│   └── task_scheduler/
│       │
│       ├── __init__.py
│       ├── version.py
│       │
│       ├── domain/
│       │   ├── job.py
│       │   ├── schedule.py
│       │   ├── command.py
│       │   ├── environment.py
│       │   └── errors.py
│       │
│       ├── application/
│       │   ├── job_service.py
│       │   ├── discovery_service.py
│       │   ├── validation_service.py
│       │   ├── test_service.py
│       │   └── diagnostic_service.py
│       │
│       ├── platform/
│       │   └── macos/
│       │       ├── plist_codec.py
│       │       ├── launchctl.py
│       │       ├── launch_agent_store.py
│       │       ├── process_runner.py
│       │       ├── python_detector.py
│       │       └── shell_environment.py
│       │
│       ├── storage/
│       │   ├── job_repository.py
│       │   └── json_repository.py
│       │
│       ├── cli/
│       │   ├── app.py
│       │   └── commands/
│       │
│       └── gui/
│           ├── app.py
│           ├── main_window.py
│           ├── models/
│           ├── widgets/
│           ├── dialogs/
│           └── controllers/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
│
├── scripts/
│
└── docs/
    ├── architecture.md
    ├── development.md
    ├── launchd-notes.md
    └── troubleshooting.md
```

This structure may evolve, but architectural separation should remain.

---

# 8. Code Size and Agent Guardrails

These requirements exist specifically to make AI-assisted development safer and more accurate.

## 8.1 File size

No logic-heavy Python source file may exceed:

```text
500 lines
```

At approximately:

```text
400–450 lines
```

the coding agent should evaluate whether the module needs decomposition.

The 500-line constraint is not permission to create 499-line monoliths.

---

## 8.2 Function size

Target:

```text
< 50 lines per function
```

Exceptions are allowed when splitting would make the code less understandable.

Functions exceeding 75 lines should be treated as a refactoring signal.

---

## 8.3 Responsibility

Each module should have one primary responsibility.

Forbidden examples:

```text
main_window.py
    generates plists
    executes launchctl
    parses Python environments
    manages files
```

Instead:

```text
main_window.py
    invokes services
```

---

## 8.4 UI isolation

Qt widgets must not execute:

```python
subprocess.run(...)
```

directly.

Qt widgets must not directly write LaunchAgent plist files.

The GUI calls application services.

---

## 8.5 Process isolation

Raw subprocess execution should exist in one process abstraction.

Example:

```python
class ProcessRunner(Protocol):
    def run(self, command: CommandSpec) -> ProcessResult:
        ...
```

Production:

```text
SubprocessRunner
```

Tests:

```text
FakeProcessRunner
```

---

## 8.6 Filesystem isolation

Filesystem-changing behavior should similarly be testable through narrowly scoped components.

---

## 8.7 Type hints

All public application code must contain type annotations.

Run static type checking during validation.

---

## 8.8 Formatting and linting

Use:

```text
ruff
```

for formatting/linting.

Use:

```text
mypy
```

or an equivalent static type checker.

---

## 8.9 Tests are part of the change

Any change adding application logic must add or modify tests in the same change.

A coding agent should not consider the task complete merely because the GUI appears to work.

---

# 9. Core Domain Model

The initial conceptual model should include:

```python
JobDefinition
JobCommand
Schedule
ScheduleTime
EnvironmentConfig
LoggingConfig
JobMetadata
```

Example concept:

```text
JobDefinition
│
├── id
├── name
├── label
├── enabled
├── command
├── schedule
├── environment
├── working_directory
├── logging
└── metadata
```

---

# 10. Command Types

Crawl supports three command types.

## Python

```text
Python script
```

Fields:

```text
script path
Python interpreter
arguments
working directory
environment
```

---

## Shell

```text
Shell script or shell command
```

Prefer explicit executable semantics.

Avoid relying unnecessarily on:

```text
/bin/zsh -c "..."
```

when an executable plus argument list can be represented directly.

---

## Executable

Example:

```text
/usr/local/bin/myutility
```

with explicit argument list.

---

# 11. Scheduling Model — Crawl

Crawl intentionally supports a narrow scheduling model.

Users may select:

```text
Time
Days of Week
```

Example:

```text
07:30 AM

Mon ✓
Tue ✓
Wed ✓
Thu ✓
Fri ✓
Sat
Sun
```

Support:

- one specific time;
    
- one or more selected weekdays.
    

The data model should be extensible enough to support multiple execution times later.

Do not add generalized cron-expression support in Crawl.

---

# 12. Sleep / Missed Schedule Explanation

The interface should explicitly educate the user about scheduling behavior.

Where practical, display:

```text
Scheduled:
Tuesday at 2:00 AM

Mac sleep may affect the exact execution time.
```

Do not promise exact wake behavior unless the system is configured to provide it.

The user should be able to inspect:

```text
Expected schedule
Last observed execution
Current job state
```

in later phases.

---

# 13. Python Environment Detection — Crawl

When a user selects:

```text
/Users/me/projects/foo/main.py
```

search for common environments near the script.

Check, initially:

```text
./.venv/bin/python
./venv/bin/python
```

Then consider:

```text
current interpreter
PATH-discovered python3
```

Present findings to the user.

Example:

```text
Detected Python environment

✓ /Users/me/projects/foo/.venv/bin/python

Other interpreters:

  /opt/homebrew/bin/python3
  /usr/bin/python3
```

Do not attempt full Poetry, Conda, pyenv, uv, Pipenv, etc. detection during early Crawl.

These can be added incrementally.

---

# 14. Working Directory

For a selected script:

```text
/Users/me/projects/foo/main.py
```

default:

```text
WorkingDirectory =
/Users/me/projects/foo
```

Allow override.

Never assume a launchd task starts in the project directory.

---

# 15. Environment Variables — Crawl

Do not capture the entire interactive shell environment automatically.

Provide a comparison mechanism.

Example:

```text
Environment differences

PATH
Terminal:
  /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

Scheduled:
  /usr/bin:/bin

[Import PATH]
```

Environment variables are explicitly added to the job definition.

Crawl does not attempt secret management.

The documentation should warn against storing sensitive API keys or passwords directly in job definitions or plist files.

---

# 16. Logging

Logging is enabled by default.

Suggested path:

```text
~/Library/Logs/macOS Task Scheduler for Humans/<job-id>/
```

Files:

```text
stdout.log
stderr.log
```

The generated LaunchAgent should configure appropriate launchd output paths.

The GUI should display both streams.

---

# 17. Discovery

Crawl scans:

```text
~/Library/LaunchAgents/
```

Each discovered plist is parsed.

Jobs should be classified.

Possible classifications:

```text
Managed
Recognized
External
Invalid
```

Initially:

- Managed jobs are editable.
    
- External jobs are viewable.
    
- External jobs default to read-only.
    
- Unsupported plist keys should be preserved conceptually where practical but not silently rewritten.
    

---

# 18. Import Strategy

Crawl does **not** need full arbitrary LaunchAgent editing.

The first behavior is:

```text
discover
parse
visualize
```

An external job may later support:

```text
Import as managed copy
```

before editing.

This prevents the application from accidentally damaging third-party configuration.

---

# 19. Generated plist

The plist generator should take only a validated domain object.

Conceptually:

```python
plist = encode_launch_agent(job)
```

It should not accept arbitrary GUI state.

The reverse direction should also exist:

```python
job = decode_launch_agent(plist)
```

but it may return:

```text
fully_supported
partially_supported
unsupported
```

metadata.

---

# 20. macOS Platform Adapter

Define a launchd abstraction.

Conceptually:

```python
class SchedulerBackend(Protocol):
    def discover(self) -> list[ScheduledJob]:
        ...

    def install(self, job: JobDefinition) -> None:
        ...

    def uninstall(self, job_id: str) -> None:
        ...

    def enable(self, job_id: str) -> None:
        ...

    def disable(self, job_id: str) -> None:
        ...

    def status(self, job_id: str) -> JobStatus:
        ...

    def trigger(self, job_id: str) -> TriggerResult:
        ...
```

Crawl implementation:

```text
LaunchAgentBackend
```

Run may introduce:

```text
ServiceManagementBackend
```

without changing the rest of the application.

Apple documents `SMAppService` as the modern macOS 13+ mechanism for controlling application helper executables registered as LoginItems, LaunchAgents and LaunchDaemons. ([Apple Developer](https://developer.apple.com/documentation/servicemanagement/smappservice?utm_source=chatgpt.com "SMAppService | Apple Developer Documentation"))

---

# 21. CLI Requirements

Initial CLI name can be temporary.

Example:

```text
mactask
```

Crawl commands:

```text
mactask list

mactask inspect <job>

mactask validate <job.json>

mactask generate <job.json>

mactask install <job.json>

mactask uninstall <job>

mactask enable <job>

mactask disable <job>

mactask status <job>

mactask test <job>

mactask run <job>

mactask logs <job>
```

The GUI must call the same services used by these commands.

---

# 22. Test Run Modes

Eventually provide two distinct execution tests.

## Mode A — Direct Test

Execute the configured job command with:

- exact executable;
    
- exact arguments;
    
- configured environment;
    
- configured working directory.
    

Capture:

```text
stdout
stderr
exit code
execution duration
```

This mode is fast and diagnostic.

---

## Mode B — launchd Test

Install or update the actual LaunchAgent and ask launchd to execute it.

Then inspect:

- launchctl state;
    
- stdout;
    
- stderr;
    
- process result where observable.
    

This tests the real scheduler environment.

Implement Mode A first.

Implement Mode B later in Crawl or early Walk.

---

# 23. Diagnostic Engine

Diagnostics should be rule-based and testable.

Examples:

### Interpreter mismatch

```text
Configured:
/usr/bin/python3

Detected project interpreter:
/Users/me/project/.venv/bin/python

Likely Python environment mismatch.
```

### Missing executable

```text
Configured executable does not exist.
```

### Missing working directory

```text
Working directory no longer exists.
```

### Relative executable

```text
"python3" depends on PATH resolution.

Use an absolute interpreter path.
```

### Missing script

```text
The configured script could not be found.
```

### Permission problem

```text
The executable is not executable by the current user.
```

### Module failure

Given stderr:

```text
ModuleNotFoundError
```

recommend checking the interpreter/environment.

Diagnostics must return structured data:

```text
severity
code
title
description
suggested_action
```

not GUI-specific strings alone.

---

# 24. GUI — Crawl

Recommended main window:

```text
┌─────────────────────────────────────────────────────────────┐
│ macOS Task Scheduler for Humans                     + Task │
├──────────────────────┬──────────────────────────────────────┤
│ Tasks                │ Task Details                         │
│                      │                                      │
│ Daily Backup         │ Name                                 │
│ Weather Update       │ Daily Backup                         │
│ Data Cleanup         │                                      │
│                      │ Program                              │
│                      │ /Users/me/scripts/backup.py          │
│                      │                                      │
│                      │ Schedule                             │
│                      │ Mon Tue Wed Thu Fri   07:30          │
│                      │                                      │
│                      │ Status                               │
│                      │ Enabled                              │
│                      │                                      │
│                      │ [Test] [Save] [Install]              │
└──────────────────────┴──────────────────────────────────────┘
```

---

# 25. GUI Sections

Suggested editor tabs:

```text
General
Schedule
Environment
Logs
Advanced
```

## General

```text
Name
Task type
Script/executable
Arguments
Working directory
Python interpreter
```

## Schedule

```text
Execution time
Days of week
Schedule explanation
```

## Environment

```text
Configured variables
Detected PATH differences
Add / remove
```

## Logs

```text
stdout
stderr
Refresh
Reveal in Finder
```

## Advanced

```text
launchd label
generated plist
raw launchd status
ownership classification
```

---

# 26. Source of Truth

For an application-created job:

```text
JSON Job Definition
```

is the application source of truth.

Generated plist is a deployment artifact.

Example storage:

```text
~/Library/Application Support/
    macOS Task Scheduler for Humans/
        jobs/
            <uuid>.json
```

Logs:

```text
~/Library/Logs/
    macOS Task Scheduler for Humans/
```

---

# 27. JSON Export

All managed jobs should be exportable.

Example conceptual representation:

```json
{
  "schema_version": 1,
  "name": "Daily Backup",
  "type": "python",
  "command": {
    "script": "/Users/me/scripts/backup.py",
    "interpreter": "/Users/me/scripts/.venv/bin/python"
  },
  "schedule": {
    "time": "07:30",
    "weekdays": [
      "monday",
      "wednesday",
      "friday"
    ]
  }
}
```

Use schema versioning from the beginning.

---

# 28. Test Strategy

Testing is mandatory at multiple levels.

```text
Unit
 ↓
Component
 ↓
Integration
 ↓
Manual macOS smoke test
```

---

# 29. Unit Test Harness

Use:

```text
pytest
pytest-cov
```

Recommended optional additions:

```text
pytest-mock
hypothesis
```

The unit suite must run without changing the user's machine.

Target:

```text
< 10 seconds initially
```

for the core unit suite where practical.

---

# 30. Required Test Fakes

Create reusable test doubles.

Examples:

```text
FakeProcessRunner
FakeSchedulerBackend
FakeJobRepository
FakeFilesystem
FakeEnvironmentProvider
FakeClock
```

Avoid excessive use of global monkeypatching when dependency injection provides a cleaner solution.

---

# 31. Golden plist Tests

Maintain representative inputs under:

```text
tests/golden/
```

Example:

```text
weekday_python_job.json
weekday_python_job.plist
```

Test:

```text
JSON
 ↓
Job model
 ↓
plist encoder
 ↓
expected normalized plist
```

Prefer structural plist comparison rather than textual XML comparison.

---

# 32. Round-trip Tests

Where supported:

```text
Job
 ↓
plist
 ↓
Job
```

must preserve the modeled information.

Do not require arbitrary external plist files to round-trip perfectly during Crawl.

---

# 33. Schedule Tests

Test every weekday.

Test combinations.

Examples:

```text
Monday only
Monday-Friday
Saturday-Sunday
Mon/Wed/Fri
all days
```

Test boundary times:

```text
00:00
23:59
```

Test invalid:

```text
24:00
-1
empty weekdays
```

---

# 34. Python Detection Tests

Fixtures should model:

```text
project/.venv/bin/python
project/venv/bin/python
no virtual environment
missing interpreter
multiple candidates
```

No test should depend on the developer's actual Python installations.

---

# 35. Diagnostic Tests

Every diagnostic rule must have at least:

```text
positive test
negative test
```

Example:

```text
wrong interpreter → warning
matching interpreter → no warning
```

---

# 36. Integration Tests

Integration tests may invoke macOS behavior.

Mark them:

```python
@pytest.mark.integration
```

Do not run them as part of ordinary unit testing unless explicitly requested.

Run:

```text
pytest -m integration
```

Integration tests must use uniquely named jobs, e.g.:

```text
io.github.mactaskscheduler.test.<uuid>
```

They must remove test LaunchAgents during teardown.

---

# 37. Dangerous Integration Test Guard

Tests that modify the real LaunchAgent directory must require an explicit environment variable.

Example:

```text
MACTASK_ALLOW_SYSTEM_TESTS=1
```

Without it:

```text
skip
```

Never allow a standard:

```text
pytest
```

command to unexpectedly install LaunchAgents.

---

# 38. Standard Developer Commands

Provide:

```text
make test
make lint
make format
make typecheck
make integration
make package
make check
```

`make check` should perform:

```text
format check
lint
typecheck
unit tests
```

A coding agent should run:

```text
make check
```

before declaring a feature complete.

---

# 39. Crawl / Walk / Run Strategy

The project should increase complexity progressively.

The phases are product maturity stages.

Inside each phase, work should still occur as small vertical increments.

---

# 40. CRAWL

## Goal

Create a useful, reliable per-user scheduler that solves the primary problem:

> Schedule a Python script, shell command/script, or executable at a specific time on selected days without manually writing a plist.

---

# 41. Crawl Increment 0 — Project Foundation

Deliver:

- repository;
    
- Python environment;
    
- pyproject configuration;
    
- package structure;
    
- pytest;
    
- Ruff;
    
- mypy;
    
- Makefile;
    
- GitHub-friendly README;
    
- license;
    
- CI-ready `make check`.
    

Acceptance:

```text
make check
```

passes.

No scheduler code yet.

---

# 42. Crawl Increment 1 — Domain Model

Implement:

```text
JobDefinition
Command
Schedule
Environment
Logging
```

Implement JSON serialization.

Tests cover:

- valid jobs;
    
- invalid jobs;
    
- schema version;
    
- round trip JSON.
    

No plist implementation yet.

---

# 43. Crawl Increment 2 — plist Generator

Implement:

```text
JobDefinition → LaunchAgent plist
```

Support:

- Label;
    
- ProgramArguments;
    
- WorkingDirectory;
    
- EnvironmentVariables;
    
- StartCalendarInterval;
    
- StandardOutPath;
    
- StandardErrorPath.
    

Add golden tests.

Acceptance:

Known job definitions generate structurally correct expected plists.

---

# 44. Crawl Increment 3 — plist Reader

Implement basic LaunchAgent parsing.

Classify:

```text
supported
partially supported
invalid
```

Do not attempt to edit every possible launchd plist.

Tests use fixture plists.

---

# 45. Crawl Increment 4 — Python Detection

Implement:

```text
.venv
venv
current interpreter
```

Add working-directory detection.

Add environment comparison.

No GUI dependency.

---

# 46. Crawl Increment 5 — Direct Test Runner

Implement direct task testing.

Return:

```text
exit code
stdout
stderr
duration
```

Add diagnostic rules.

This is the first point at which the application can answer:

> Why does this Python job fail?

---

# 47. Crawl Increment 6 — LaunchAgent Storage

Implement:

```text
write plist
remove plist
discover plist
```

Initially target only:

```text
~/Library/LaunchAgents
```

Use filesystem abstraction.

Do not modify `/Library`.

---

# 48. Crawl Increment 7 — launchctl Adapter

Implement the scheduler backend.

Capabilities:

```text
install
uninstall
status
enable
disable
trigger
```

All command invocation goes through `ProcessRunner`.

Unit tests use fake launchctl output.

Real behavior goes into protected integration tests.

---

# 49. Crawl Increment 8 — CLI

Implement first-class CLI.

A developer should now be able to complete the primary lifecycle entirely from Terminal.

Example:

```text
mactask validate job.json
mactask install job.json
mactask status my-job
mactask test my-job
mactask logs my-job
mactask uninstall my-job
```

This establishes the core before GUI complexity is added.

---

# 50. Crawl Increment 9 — GUI Read/Discovery

Build PySide6 main window.

Initially:

```text
discover
list
inspect
visualize
```

Do not edit arbitrary external jobs.

The GUI should now make existing LaunchAgents understandable.

---

# 51. Crawl Increment 10 — GUI Job Creation

Add:

```text
New Task
Edit Managed Task
Save
Validate
```

Forms support:

```text
Python
Shell
Executable
```

Schedule supports:

```text
specific time
selected weekdays
```

---

# 52. Crawl Increment 11 — GUI Installation

Add:

```text
Install
Uninstall
Enable
Disable
Run Now
```

Display operation failures clearly.

---

# 53. Crawl Increment 12 — GUI Diagnostics and Logs

Add:

```text
Test
stdout
stderr
diagnostics
environment comparison
Python interpreter recommendation
```

This completes the primary product experience.

---

# 54. Crawl Increment 13 — Packaging

Produce:

```text
macOS Task Scheduler for Humans.app
```

Use PySide6 deployment tooling initially. Qt documents `pyside6-deploy` for desktop deployment, including creation of a macOS `.app`. ([Qt Documentation](https://doc.qt.io/qtforpython-6.8/deployment/index.html?utm_source=chatgpt.com "Deployment - Qt for Python"))

Local use is sufficient.

Crawl does not require public notarized distribution.

---

# 55. Crawl Definition of Done

A user can:

1. launch the `.app`;
    
2. see existing user LaunchAgents;
    
3. inspect their schedules and commands;
    
4. create a task;
    
5. choose Python, shell, or executable;
    
6. select a particular time;
    
7. select weekdays;
    
8. have a Python virtual environment detected;
    
9. see/set working directory;
    
10. configure environment variables;
    
11. test execution directly;
    
12. receive useful diagnostics;
    
13. generate a plist;
    
14. install the LaunchAgent;
    
15. enable/disable it;
    
16. trigger it;
    
17. see stdout/stderr;
    
18. uninstall it safely.
    

Unit tests pass.

No logic-heavy Python module exceeds 500 lines.

---

# 56. WALK

## Goal

Turn the working scheduler into a strong troubleshooting and management product.

---

# 57. Walk Scheduling Improvements

Add:

```text
multiple times per day
daily
interval-based schedules where appropriate
run at login
```

Potential future launchd triggers may include:

```text
WatchPaths
QueueDirectories
KeepAlive
```

Each trigger is added separately with tests.

Do not build a generic property-list editor.

---

# 58. Walk Python Improvements

Add detection for selected popular ecosystems incrementally.

Candidates:

```text
uv
pyenv
Poetry
Conda
Pipenv
Homebrew Python
```

Each detector should implement a common interface.

No giant `detect_everything()` function.

---

# 59. Walk Execution History

Introduce SQLite.

Track application-observed events such as:

```text
test execution
manual trigger
observed last state
diagnostic result
```

Do not claim perfect historical execution data unless the application can prove it.

---

# 60. Walk Diagnostics

Expand rule engine for:

- PATH failures;
    
- missing executable;
    
- missing working directory;
    
- Python import failure;
    
- permission denied;
    
- malformed plist;
    
- launchctl registration failure;
    
- invalid label;
    
- inaccessible log path;
    
- protected-folder/macOS privacy problems;
    
- executable architecture problems where detectable.
    

---

# 61. Walk Job Import

Allow:

```text
Import as Managed Job
```

External plist:

```text
read
 ↓
normalize supported settings
 ↓
warn about unsupported settings
 ↓
create application JSON
```

Never silently discard unsupported configuration.

---

# 62. Walk Next-Run Visualization

Calculate and display estimated upcoming schedule occurrences.

Example:

```text
Next scheduled times

Wed Aug 26  07:30
Thu Aug 27  07:30
Fri Aug 28  07:30
```

Label this as an application-derived schedule preview rather than claiming it is launchd's internal queue.

---

# 63. Walk UX

Add:

- search;
    
- filters;
    
- enabled/disabled status;
    
- validation badges;
    
- status indicators;
    
- better empty states;
    
- safer destructive-action dialogs;
    
- Reveal plist in Finder;
    
- Reveal logs in Finder;
    
- copy command;
    
- copy plist;
    
- export JSON;
    
- import JSON.
    

---

# 64. Walk Definition of Done

The application is useful not only for creating scheduled tasks but also for answering:

> What scheduled jobs exist?

> What will this job run?

> Which Python is it using?

> When should it run?

> Why didn't it work?

> What does launchd currently think about it?

---

# 65. RUN

## Goal

Support production-quality macOS scheduling including jobs that need to execute when the user is not logged in.

This requires a meaningful architecture change at the macOS boundary but should **not** require rewriting the domain/application layers.

---

# 66. LaunchDaemons

User LaunchAgents operate in a user context.

For jobs that must run independently of an interactive login, introduce system-level LaunchDaemon support.

System jobs live conceptually under:

```text
/Library/LaunchDaemons
```

Do not make the entire PySide6 application run as root.

---

# 67. ServiceManagement Direction

Modern macOS provides `SMAppService` for application helpers. Apple states that on macOS 13+, `SMAppService` can register and control LoginItems, LaunchAgents and LaunchDaemons associated with an application bundle. ([Apple Developer](https://developer.apple.com/documentation/servicemanagement/smappservice?utm_source=chatgpt.com "SMAppService | Apple Developer Documentation"))

Because `SMAppService` is a native macOS API, Run may introduce a small native Swift/Objective-C component while retaining Python for the application's main functionality.

Conceptually:

```text
PySide6 Application
       │
       │ narrow IPC API
       ↓
Native macOS Helper
       │
       ↓
ServiceManagement
       │
       ↓
LaunchDaemon
```

---

# 68. Privileged Architecture

The native/privileged helper must expose narrowly scoped operations.

Example:

```text
install approved daemon definition
remove managed daemon
query managed daemon
enable/disable managed daemon
```

It should **not** expose arbitrary:

```text
execute command as root
```

functionality.

The privilege boundary must be treated as a security boundary.

---

# 69. System Job UI

Add job scope:

```text
Run as:

● My User
  Runs in my login session

○ System Service
  Can run when no user is logged in
  Administrator authorization required
```

Explain the behavioral difference.

---

# 70. Run Security Work

Before enabling system jobs:

- perform threat modeling;
    
- validate all paths;
    
- validate job ownership;
    
- prevent arbitrary plist replacement;
    
- prevent command injection;
    
- constrain privileged helper IPC;
    
- test symlink/path attacks;
    
- review permissions;
    
- review secrets handling.
    

---

# 71. Secrets

Run may introduce macOS Keychain integration.

Avoid storing secrets in:

```text
job JSON
plist
logs
```

where possible.

Secret handling requires a separate design specification before implementation.

---

# 72. Signing and Notarization

Run should include:

- stable bundle identifier;
    
- Developer ID signing;
    
- hardened runtime where appropriate;
    
- helper signing;
    
- notarization;
    
- release packaging;
    
- update strategy.
    

Crawl does not need this complexity.

---

# 73. Run Definition of Done

The application supports:

```text
User scheduled task
System scheduled task
```

and can reliably install and manage both through the appropriate macOS architecture.

A system task may execute even with no interactive user logged in.

The Python domain model and scheduling UI remain largely unchanged.

---

# 74. Features Explicitly Deferred

Do not build these during early Crawl:

- remote scheduling;
    
- cloud synchronization;
    
- Windows support;
    
- Linux support;
    
- arbitrary cron expression parser;
    
- full graphical plist editor;
    
- LaunchDaemon support;
    
- root GUI;
    
- Keychain integration;
    
- execution analytics dashboard;
    
- job marketplace;
    
- plug-in ecosystem;
    
- HTTP server;
    
- Flask/FastAPI backend;
    
- React/Electron frontend;
    
- automatic software updates;
    
- App Store distribution.
    

These can be reconsidered after the core product proves useful.

---

# 75. Application Non-Goals

The application is not intended to:

- replace launchd;
    
- create another scheduling daemon;
    
- maintain a Python background server;
    
- run continuously merely to detect schedule times;
    
- convert the Mac into a remote job runner;
    
- expose every launchd setting in the main UI;
    
- hide what launchd is doing.
    

The system scheduler remains:

```text
launchd
```

The application manages and explains it.

---

# 76. Agent Development Workflow

Every OpenCode feature request should follow this pattern.

## Step 1 — Understand

Read:

```text
relevant domain module
relevant service
relevant tests
```

Avoid loading unrelated large portions of the repository.

---

## Step 2 — Plan the smallest change

Identify:

```text
model change
service change
platform change
UI/CLI change
tests
```

Do not combine unrelated refactors.

---

## Step 3 — Write tests

Add or modify tests describing expected behavior.

---

## Step 4 — Implement

Make the smallest implementation satisfying the behavior.

---

## Step 5 — Verify

Run:

```text
make check
```

---

## Step 6 — Integration verification

Only when platform behavior changes:

```text
make integration
```

with required safety opt-in.

---

## Step 7 — Review file size

Before completing a task:

```text
confirm modified Python files < 500 lines
```

Refactor if necessary.

---

# 77. Agent Prompt Guardrail

Include the following in the repository's agent instructions:

> Do not bypass application-layer abstractions in order to implement a feature quickly. GUI components must not directly manipulate LaunchAgent files or invoke launchctl. CLI components must not independently implement scheduling logic. All operating-system side effects must pass through platform abstractions designed for substitution during tests.

And:

> Never modify third-party LaunchAgent files during automated testing.

And:

> Never introduce a Python source module containing application logic over 500 lines. Prefer focused modules and explicit interfaces.

And:

> A feature is incomplete until `make check` passes.

---

# 78. Recommended Initial Build Sequence

The coding agent should build in this exact conceptual order:

```text
1. Repository/tooling
        ↓
2. Domain model
        ↓
3. JSON persistence
        ↓
4. Schedule model
        ↓
5. plist generation
        ↓
6. plist parsing
        ↓
7. Python/environment detection
        ↓
8. Direct execution/test harness
        ↓
9. Diagnostics
        ↓
10. LaunchAgent filesystem management
        ↓
11. launchctl adapter
        ↓
12. CLI
        ↓
13. GUI discovery
        ↓
14. GUI creation/editing
        ↓
15. GUI execution/status
        ↓
16. GUI logs/diagnostics
        ↓
17. macOS app packaging
```

Do not start by building the complete GUI.

The GUI should sit on top of proven application behavior.

---

# 79. First Usable Milestones

## Milestone A — Model

```text
JSON → validated JobDefinition
```

## Milestone B — Generate

```text
JobDefinition → correct plist
```

## Milestone C — Diagnose

```text
Python script → environment analysis
```

## Milestone D — Test

```text
JobDefinition → controlled direct execution
```

## Milestone E — Schedule

```text
JobDefinition → real LaunchAgent
```

## Milestone F — CLI Product

```text
Complete workflow from Terminal
```

## Milestone G — GUI Product

```text
Complete workflow without Terminal
```

## Milestone H — Packaged Product

```text
double-clickable .app
```

Each milestone must leave the repository usable and tested.

---

# 80. Architectural Success Criteria

The architecture is successful if the following future changes can happen without major rewrites:

```text
PySide6 → different UI
```

without replacing domain logic.

```text
launchctl backend → ServiceManagement helper
```

without replacing UI or job models.

```text
JSON repository → SQLite
```

without replacing scheduling logic.

```text
Python detector → additional environment detectors
```

without altering unrelated modules.

```text
single execution time → richer schedule
```

without replacing job storage.

---

# 81. Product Success Criteria

The application succeeds when a user can create a scheduled Python utility without needing to understand:

```text
plist XML
launchctl syntax
shell initialization behavior
```

while still making those implementation details visible when useful.

The defining experience should be:

```text
Choose program
     ↓
Choose schedule
     ↓
Test
     ↓
Understand problems
     ↓
Install
     ↓
See logs/status
```

instead of:

```text
Search the web
     ↓
copy plist example
     ↓
modify XML
     ↓
launchctl fails
     ↓
try another command
     ↓
script silently fails
     ↓
debug PATH for an hour
```

---

# 82. Final Product Direction

The Crawl release should remain intentionally modest:

> **A reliable graphical scheduler for user-level macOS tasks, with unusually good Python diagnostics.**

The Walk release becomes:

> **A comprehensive human interface and troubleshooting tool for user-level launchd jobs.**

The Run release becomes:

> **A production-quality macOS scheduling manager supporting both logged-in user tasks and unattended system tasks through a secure native privilege boundary.**

This progression keeps early development primarily Python-based and straightforward while preserving a clean path toward the native macOS functionality required for unattended execution.

