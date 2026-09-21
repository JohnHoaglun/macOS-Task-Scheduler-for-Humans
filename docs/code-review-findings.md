# Code Review Findings — Planning Input

Status: **all findings resolved (v0.0.44–v0.0.47); retained as a durable remediation record**
Date: **2026-09-20**
Baseline commit: **`78f1326`**
Branch: **`sched_dev_opencode`**
Project version at review time: **0.0.43**
Current remediation status (2026-09-21): **CR-01, CR-02, CR-10, CR-11, and CR-15 resolved in v0.0.44; CR-03, CR-04, CR-13, and CR-14 resolved in v0.0.45; CR-05, CR-06, CR-07, CR-18, CR-19, and CR-20 resolved in v0.0.46; CR-08, CR-09, CR-12, CR-16, CR-17, and CR-21 resolved in v0.0.47**

This document records the full set of findings from the code review so they can be planned, scoped, and implemented in a later cycle. It is intentionally written as a durable backlog, not as an active implementation plan.

---

## 1. Review scope and method

The review covered the full current codebase at the baseline commit, including:

- `domain`
- `application`
- `platform/macos`
- `storage`
- `gui`
- CLI / bootstrap
- packaging
- tests and build configuration

Method:

1. Eight parallel read-only review lanes were run across the major subsystems.
2. Findings were merged into a single ranked list.
3. High- and critical-severity items were then verified directly against source.
4. No code was modified during the review.

The result is a set of localized robustness, durability, shutdown, and process issues. The architecture itself is sound.

---

## 2. Executive summary

The codebase is structurally strong:

- clean layering
- strict typing
- large test suite
- high coverage
- good separation between GUI, controllers, services, and platform adapters

The important findings are mostly about **failure modes**, not core design:

- destructive external LaunchAgent operations can report success when a launchd step failed
- some shutdown paths do not track every active worker thread
- durable JSON writes are not atomic
- logging is robust in the happy path but not fully failure-tolerant
- some filesystem helpers imply stronger guarantees than the implementation provides
- the build does not mechanically enforce all quality gates

The highest-priority issue is external removal semantics: the app can delete a plist even when `launchctl bootout` fails, and the UI can still tell the user the agent was unloaded first.

---

## 3. Severity summary

| ID | Severity | Area | Finding |
|---|---:|---|---|
| CR-01 | Critical | External LaunchAgent control | `remove_external()` can delete the plist after a failed `bootout`, and the GUI can still report success |
| CR-02 | High | Shutdown / threading | `DirectTestDialog` worker threads are not included in `MainWindow` close-drain |
| CR-03 | High | Storage durability | JSON catalog/export writes are not atomic |
| CR-04 | High | Storage safety | Create-only JSON import/export has an `exists()`-then-write race |
| CR-05 | High | Logging / startup | Logging initialization failure can abort GUI startup |
| CR-06 | High | Logging / permissions | `chmod` failures on `app.log` are silently suppressed |
| CR-07 | High | Logging / retention | The 10 MB retention cap does not bound the active `app.log` |
| CR-08 | High | Filesystem | `create_exclusive()` uses a predictable temp path and weak pre-write checks |
| CR-09 | High | Filesystem | `replace_verified()` and `read_snapshot()` are weaker than their names imply |
| CR-10 | High | GUI correctness | Raw plist is rendered through `QTextEdit.setText()` and can be treated as rich text |
| CR-11 | High | Build process | `make check` does not enforce 100% coverage or the test/source ratio cap |
| CR-12 | High | Packaging | `pysidedeploy.spec` hardcodes developer-machine absolute paths |
| CR-13 | Medium | GUI controllers | `ImportController.commit()` can still raise `OSError` |
| CR-14 | Medium | GUI controllers | `HistoryController.history_for()` does not fully convert storage failures into safe outcomes |
| CR-15 | Medium | External control messaging | Disable/enable result messages can overstate what launchd actually did |
| CR-16 | Medium | Platform store | `quarantine_external()` does not use a snapshot-based verified move |
| CR-17 | Medium | GUI performance | Python interpreter detection runs synchronously on every script-path keystroke |
| CR-18 | Medium | Logging resilience | Log write failures fall back to `handleError()` and do not attempt stream recovery |
| CR-19 | Low | Logging API | `configure_logging()` is idempotent per handler, not per log path |
| CR-20 | Low | Product policy | Full configuration logging may include sensitive user data by design |
| CR-21 | Low | Build / packaging | `make package` is macOS/toolchain-specific |

---

## 4. Planning constraints to preserve

Any future cycle that implements these fixes should keep the existing product and quality invariants:

- log full configuration content without redaction
- keep `app.log` user-only
- keep log retention bounded by `10 MB` and `14 days`
- keep worker threads parentless where required by the current lifetime model
- do not introduce `QThread.wait()` in close paths
- keep close behavior responsive and cancellation-oriented
- keep `mypy --strict` clean
- keep `ruff` clean
- keep test coverage at `100%`
- keep the test/source ratio at or below `75%`

The last constraint matters because several fixes will require new tests. The plan for the next cycle should explicitly account for test-budget impact.

---

## 5. Detailed findings

### CR-01 — Critical — `remove_external()` can delete a plist after `bootout` fails

**Severity:** Critical  
**Confidence:** High, source-verified  
**Area:** external LaunchAgent control

#### Current behavior

`remove_external()` attempts to unload a loaded external LaunchAgent before deleting its plist.

Relevant code:

- `src/task_scheduler/application/task_command_service.py:1206-1261`

If the agent is loaded, the service calls `launchctl bootout`. If that command fails, the failure is recorded internally, but the method continues and still deletes the source plist.

The GUI then presents the operation as successful.

Relevant GUI code:

- `src/task_scheduler/gui/main_window.py:700-702`
- `src/task_scheduler/gui/main_window.py:761-768`

The “It was unloaded first.” message is driven by the pre-operation loaded flag, not by whether bootout actually succeeded.

#### Why this matters

If `bootout` fails, launchd may still have the agent loaded or running, but the app can still:

- delete the plist
- tell the user the operation succeeded
- tell the user the agent was unloaded first

That creates an inconsistent and potentially dangerous state.

#### Desired behavior

- If the agent is loaded and `bootout` fails, do **not** delete the source plist.
- Return an explicit partial-failure outcome.
- Show a user-visible error in the GUI.
- Do not claim the agent was unloaded unless that phase actually succeeded.
- Preserve the backup and any retained artifacts for recovery.

#### Recommended tests

- failed `bootout` during remove:
  - source plist remains
  - result is not success
  - GUI does not say “It was unloaded first.”
- successful `bootout` during remove:
  - source plist is removed
  - result is success
- remove after successful `bootout` but failed file deletion:
  - source remains
  - failure is surfaced

#### Planning notes

This is the top-priority fix.

It is likely a small-to-medium change, but it changes user-facing failure semantics, so it needs careful outcome modeling.

---

### CR-02 — High — `DirectTestDialog` worker threads are not part of `MainWindow` close-drain

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** shutdown / threading

#### Current behavior

`DirectTestDialog` creates worker `QThread`s and tracks them in class-level state.

Relevant code:

- `src/task_scheduler/gui/widgets/direct_test_dialog.py:42-43`
- `src/task_scheduler/gui/widgets/direct_test_dialog.py:82-92`
- `src/task_scheduler/gui/widgets/direct_test_dialog.py:123-128`

`MainWindow` close-drain only tracks its own worker threads:

- `src/task_scheduler/gui/main_window.py:1200-1256`

The dialog is shown modally from the job editor:

- `src/task_scheduler/gui/widgets/job_editor.py:742-743`

If the user closes the dialog while the worker is still running, the thread can remain active while the main window or application shuts down.

#### Why this matters

This is a lifetime gap. A diagnostics worker can outlive the dialog and potentially the main window, which creates shutdown races and missed signal delivery.

#### Desired behavior

Either:

1. include `DirectTestDialog` worker threads in the same close-drain mechanism used by `MainWindow`, or
2. make the dialog wait/cancel its worker before it allows close to complete.

The better long-term design is probably a shared active-worker registry used by the whole GUI shutdown path.

#### Recommended tests

- start a direct test
- close the direct-test dialog before the worker finishes
- close the main window
- assert that no untracked worker thread remains active after shutdown completes

#### Planning notes

This is a shutdown-safety issue. It should be planned together with the broader worker-lifetime rules.

---

### CR-03 — High — JSON catalog/export writes are not atomic

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** storage durability

#### Current behavior

Catalog and export JSON writes use direct `Path.write_text()` calls.

Relevant code:

- `src/task_scheduler/storage/json_repository.py:51-55`

This is used by:

- catalog save:
  - `src/task_scheduler/application/job_service.py:204-216`
- catalog import:
  - `src/task_scheduler/application/job_service.py:188-202`
- managed JSON export:
  - `src/task_scheduler/application/task_command_service.py:471-482`

#### Why this matters

A crash, power loss, or disk error during the write can leave a truncated JSON file. For the catalog, that is especially bad because it is the core persistence file.

#### Desired behavior

Use a durable write pattern:

1. write to a temporary file in the same directory
2. `fsync` the file
3. atomically replace the destination
4. optionally `fsync` the directory

#### Recommended tests

- simulate failure between temp write and replace:
  - original destination remains intact
- verify exported JSON is atomically replaced on success
- verify catalog save is atomic across overwrite scenarios

#### Planning notes

This is a classic durability fix and should be paired with the create-only race fix.

#### Resolution (v0.0.45)

Resolved. `JsonJobRepository.save()` now writes a same-directory temporary file, `flush()`es and `fsync()`s it, and publishes with `os.replace()`. A failed publish leaves the original destination intact and removes the temporary file. `JsonJobRepository.save_new()` adds the create-only durable variant used by import/export.

---

### CR-04 — High — Create-only JSON import/export has a TOCTOU gap

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** storage safety

#### Current behavior

Create-only flows check `exists()` first and then write.

Relevant code:

- `src/task_scheduler/application/job_service.py:188-202`
- `src/task_scheduler/application/task_command_service.py:471-482`

#### Why this matters

Two concurrent processes can both pass the existence check, and one can overwrite the other. This is most relevant for duplicate imports or exports.

#### Desired behavior

Use an exclusive-create primitive, for example:

- `os.open(..., O_CREAT | O_EXCL)`

or an equivalent app-level lock, and re-check conflicts immediately before the durable write.

#### Recommended tests

- concurrent import of the same UUID/label:
  - exactly one succeeds
- concurrent export to the same destination:
  - exactly one succeeds
- create-only semantics remain intact after the atomic-write change

#### Planning notes

This should be implemented in the same cycle as CR-03 because both are about durable JSON persistence.

#### Resolution (v0.0.45)

Resolved. `JobService.import_job()` now holds an exclusive `fcntl.flock` on `<catalog-root>/.catalog.lock` while re-checking conflicts and publishing through `JsonJobRepository.save_new()`, and `TaskCommandService.export_managed_json()` publishes through `save_new()`. The create-only `os.link()` publish removes the `exists()`-then-write gap: an existing destination raises `FileExistsError` (mapped to `JobConflictError` in catalog import) instead of being overwritten.

---

### CR-05 — High — Logging initialization failure can abort GUI startup

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** logging / startup

#### Current behavior

GUI startup calls logging setup before `QApplication` is created.

Relevant code:

- `src/task_scheduler/gui/app.py:73`
- `src/task_scheduler/application/app_logging.py:237-252`
- `src/task_scheduler/application/app_logging.py:151-161`

If the log directory or `app.log` cannot be created or opened, startup can fail.

#### Why this matters

A local permissions or filesystem problem in the log path should not make the entire GUI unusable.

#### Desired behavior

- isolate logging initialization in a failure-tolerant path
- fall back to stderr or a null handler if file logging cannot start
- surface a startup warning or diagnostics message instead of aborting

#### Recommended tests

- log directory not writable
- `app.log` cannot be opened
- GUI startup still succeeds with degraded logging

#### Planning notes

This is likely a small fix with high reliability value.

#### Resolution (v0.0.46)

Resolved. `configure_logging()` isolates directory/file setup failures, returns the intended log path, installs a tagged structured JSONL stderr fallback handler, and emits one structured `app.logging_degraded` warning. GUI and CLI startup no longer abort when file logging cannot start; `logging_degraded_reason()` exposes the stable degraded category.

---

### CR-06 — High — `chmod` failures on `app.log` are silently suppressed

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** logging / permissions

#### Current behavior

The app is intended to keep `app.log` user-only, but `chmod` failures are swallowed.

Relevant code:

- `src/task_scheduler/application/app_logging.py:159-160`
- `src/task_scheduler/application/app_logging.py:188-189`
- `src/task_scheduler/application/app_logging.py:193-194`

#### Why this matters

If `chmod` fails, the log may remain accessible to other local users while the app continues as if logging is secure.

#### Desired behavior

- verify permissions after creation and rollover
- emit a structured warning if the active log is not `0600`
- treat persistent permission failure as a logging fault, not a silent no-op

#### Recommended tests

- force `chmod` failure
- assert a warning is emitted
- assert the app does not silently continue with insecure logging state

#### Planning notes

This is a small fix, but it matters because log contents include full configuration values.

#### Resolution (v0.0.46)

Resolved. `app.log` is enforced to `0600` after creation, rollover, and recovery. `chmod` or `stat` verification failure raises a structured logging fault, removes the file handler, activates the stderr fallback, and records `log-permissions-unavailable` through `logging_degraded_reason()`.

---

### CR-07 — High — The 10 MB retention cap does not bound the active `app.log`

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** logging / retention

#### Current behavior

Retention pruning counts the active `app.log` toward the 10 MB total, but only deletes dated archives.

Relevant code:

- `src/task_scheduler/application/app_logging.py:109-139`

If the active file is already oversized and there are no archives, nothing is removed.

#### Why this matters

The documented retention guarantee is not fully enforced for the active file.

#### Desired behavior

- if the active file alone exceeds the cap, force rollover or truncation
- make retention enforcement verify the final total, not just delete old archives
- handle rollover failure explicitly

#### Recommended tests

- pre-existing active `app.log` larger than 10 MB with no archives
- assert retention action reduces the footprint
- rollover failure case:
  - failure is surfaced or logged structurally

#### Planning notes

This is a correctness fix for an existing product invariant.

#### Resolution (v0.0.46)

Resolved. Retention now applies to the active `app.log` as well as dated archives. An oversized active file is rolled over under the normal archive naming convention before aggregate `10 MiB` / `14 day` pruning, and rollover failure is reported through the structured degraded-logging path.

---

### CR-08 — High — `create_exclusive()` uses a predictable temp path and weak pre-write checks

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** filesystem safety

#### Current behavior

The exclusive-create helper builds a predictable temporary path and writes to it before linking.

Relevant code:

- `src/task_scheduler/platform/macos/filesystem.py:88-94`

The temp name is derived from the destination and PID.

#### Why this matters

A predictable temp path is weaker than the “exclusive” name implies. If a local actor can place a symlink or file at that path first, the write can be redirected.

#### Desired behavior

- create the temp file with `O_CREAT | O_EXCL | O_WRONLY`
- use an unpredictable suffix
- verify the created file is a regular file
- set permissions explicitly
- `fsync` before publish

#### Recommended tests

- pre-existing symlink at temp path
- pre-existing regular file at temp path
- verify permissions on created temp file
- verify failure is raised instead of following an existing path

#### Planning notes

Real-world risk is lower in a user-owned directory, but this is still a design-safety mismatch.

#### Resolution (v0.0.47)

Resolved. `create_exclusive()` now writes through a new `_write_private_file()` helper: an unpredictable temp name (`.{pid}.{secrets.token_hex(8)}.tmp`) opened with `O_CREAT | O_EXCL | O_WRONLY` (plus `O_NOFOLLOW` where available), so a pre-created symlink or file at the path cannot be followed or overwritten. The file is verified to be a regular file via `fstat` before writing, created `0600`, fully written, and `fsync`ed before its path is returned for publish; the owned temp is removed on any failure.

---

### CR-09 — High — `replace_verified()` and `read_snapshot()` are weaker than their names imply

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** filesystem semantics

#### Current behavior

`replace_verified()` reads and compares a snapshot, then replaces the destination.

Relevant code:

- `src/task_scheduler/platform/macos/filesystem.py:124-137`

This is still check-then-act, not an atomic compare-and-swap.

`read_snapshot()` reads bytes and stats the path separately:

- `src/task_scheduler/platform/macos/filesystem.py:111-122`

#### Why this matters

The API names suggest stronger guarantees than the implementation actually provides.

#### Desired behavior

Choose one of two directions:

1. **Strengthen the implementation**
   - add locking or an OS-level atomic mechanism
   - make verified replacement truly race-free

or

2. **Align the API with reality**
   - rename or document the helpers as best-effort
   - stop treating them as atomic guarantees

#### Recommended tests

- concurrent modification between snapshot and replace
- verify either:
  - the race is now prevented, or
  - the limitation is explicitly documented and tested

#### Planning notes

This is partly a design decision, not just a bug fix.

#### Resolution (v0.0.47)

Resolved (direction 2 — align the API with reality — plus a descriptor-coherent read). `read_snapshot()` now derives the bytes, SHA-256, and `st_dev`/`st_ino`/`st_size` identity from a single open file descriptor, so a path swapped between `stat` and read cannot mix identity and payload from different files (symlinks and non-regular files raise `ValueError`; a missing path raises `FileNotFoundError`). `replace_verified()` and `remove_verified()` are documented and tested as best-effort re-checks, not compare-and-swap: they re-read and compare immediately before the atomic publish but hold no lock, so a concurrent non-cooperating writer is not excluded; drift raises `SourceChangedError`.

---

### CR-10 — High — Raw plist is rendered through `QTextEdit.setText()`

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** GUI correctness

#### Current behavior

The agent inspector inserts raw plist content into a `QTextEdit` using `setText()`.

Relevant code:

- `src/task_scheduler/gui/widgets/agent_inspector.py:182`
- `src/task_scheduler/gui/widgets/agent_inspector.py:246`

Other raw-content views use a plain-text pattern.

#### Why this matters

`QTextEdit` can interpret content as rich text in some cases. Raw plist content should be displayed as plain text.

#### Desired behavior

- use `QPlainTextEdit.setPlainText()`, or
- force plain-text behavior explicitly in the current widget

#### Recommended tests

- render plist content containing XML/HTML-like strings
- assert the view behaves as plain text
- assert no rich-text formatting is applied

#### Planning notes

This is a small, low-risk correctness fix.

---

### CR-11 — High — `make check` does not enforce 100% coverage or the test/source ratio cap

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** build process

#### Current behavior

`make check` runs lint, type checking, and tests, but not coverage or the test/source ratio gate.

Relevant code:

- `Makefile:5-6`
- `Makefile:21`
- `pyproject.toml:37-51`

#### Why this matters

The project currently meets the gates, but nothing mechanically prevents regression.

#### Desired behavior

Add and wire in:

- a coverage target with `fail_under=100`
- a test/source ratio target that fails above `75%`
- include both in `make check`

#### Recommended tests

- confirm `make check` fails when coverage drops below 100%
- confirm `make check` fails when the ratio exceeds 75%
- confirm normal green path still passes

#### Planning notes

This is a high-value process fix and is cheap relative to the risk it prevents.

---

### CR-12 — High — `pysidedeploy.spec` hardcodes developer-machine paths

**Severity:** High  
**Confidence:** High, source-verified  
**Area:** packaging

#### Current behavior

The packaging spec contains absolute paths to the local environment.

Relevant code:

- `pysidedeploy.spec:19`
- `pysidedeploy.spec:24`

#### Why this matters

Packaging is not portable to another machine, user, venv, or Python patch version.

#### Desired behavior

- make the spec relative or dynamically generated
- remove hardcoded absolute paths
- validate packaging from a clean checkout

#### Recommended tests

- run packaging in a clean environment
- verify the spec no longer depends on machine-specific paths

#### Planning notes

This is less urgent than correctness issues, but it blocks portable release work.

#### Resolution (v0.0.47)

Resolved. `pysidedeploy.spec` no longer contains developer-machine absolute paths: the `icon` and `python_path` entries are left empty and resolved at deploy time, and `make package` copies the spec into a transient, gitignored `deployment/` copy so `pyside6-deploy -f` never mutates the tracked spec. Packaging now runs from a clean checkout.

---

### CR-13 — Medium — `ImportController.commit()` can still raise `OSError`

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** GUI controllers

#### Current behavior

`ImportController.commit()` catches `ValueError` and `JobConflictError`, but not `OSError`.

Relevant code:

- `src/task_scheduler/gui/controllers/import_controller.py:76-89`

The underlying commit path can still perform filesystem writes:

- `src/task_scheduler/application/job_service.py:188-202`

#### Why this matters

A disk failure during import can escape as an unhandled GUI exception.

#### Desired behavior

- catch `OSError`
- return an `ImportCommitOutcome` with an error message

#### Recommended tests

- force `OSError` during commit
- assert no exception escapes
- assert GUI-visible error outcome is returned

#### Planning notes

This is a small controller hardening fix.

#### Resolution (v0.0.45)

Resolved. `ImportController.commit()` catches `OSError` as well as `ValueError` and `JobConflictError`, returning `ImportCommitOutcome.error` with the stable storage-failure message.

---

### CR-14 — Medium — `HistoryController.history_for()` does not fully convert storage failures into safe outcomes

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** GUI controllers

#### Current behavior

The history controller only catches `JobNotFoundError`.

Relevant code:

- `src/task_scheduler/gui/controllers/history_controller.py:38-46`

The underlying service can still raise storage or OS errors:

- `src/task_scheduler/application/task_command_service.py:238-245`

#### Why this matters

History view failures can become unhandled GUI exceptions.

#### Desired behavior

- catch storage/OS failures
- return a `HistoryOutcome` with an error field

#### Recommended tests

- force repository failure
- assert controller returns safe error outcome
- assert GUI does not crash

#### Planning notes

This should be planned with the other controller hardening items.

#### Resolution (v0.0.45)

Resolved. `HistoryController.history_for()` catches `OSError` as well as `JobNotFoundError`, returning `HistoryOutcome.error` with the stable storage-failure message.

---

### CR-15 — Medium — External disable/enable result messages can overstate what launchd actually did

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** external control messaging

#### Current behavior

The service records which phases completed, but the GUI message is driven by the pre-operation loaded flag.

Relevant code:

- disable:
  - `src/task_scheduler/application/task_command_service.py:1047-1085`
- enable:
  - `src/task_scheduler/application/task_command_service.py:1117-1157`
- GUI messaging:
  - `src/task_scheduler/gui/main_window.py:746-760`

#### Why this matters

If `bootout` or `bootstrap` fails, the UI can still imply the runtime state changed.

#### Desired behavior

- choose user-facing messages from:
  - `completed_phases`, or
  - a post-operation status read

#### Recommended tests

- disable with failed bootout
- enable with failed bootstrap
- assert messages do not claim the launchd step succeeded

#### Planning notes

This is closely related to CR-01 and should be designed with the same outcome model.

---

### CR-16 — Medium — `quarantine_external()` does not use a snapshot-based verified move

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** platform store

#### Current behavior

`quarantine_external()` re-reads the source and moves it without the same snapshot/verified discipline used elsewhere.

Relevant code:

- `src/task_scheduler/platform/macos/launch_agent_store.py:243-264`

#### Why this matters

Concurrent modification can make the quarantine operation less trustworthy.

#### Desired behavior

- snapshot the source once
- use verified replace/remove or equivalent locking
- keep quarantine semantics consistent with the rest of the store

#### Recommended tests

- concurrent source modification during quarantine
- verify either safe failure or correct quarantine behavior

#### Planning notes

This belongs in the platform-hardening cycle.

#### Resolution (v0.0.47)

Resolved. `quarantine_external()` now takes a `snapshot: SourceSnapshot` and writes the quarantined file from `snapshot.payload` (never re-reading the source) via `create_exclusive()`, then removes the source only through a best-effort verified remove (`remove_verified(path, snapshot)`). On drift the source is left intact and the quarantine candidate is deleted, so no orphan artifact is left behind.

---

### CR-17 — Medium — Python interpreter detection runs synchronously on every script-path keystroke

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** GUI performance

#### Current behavior

The job editor connects `textChanged` to detection logic.

Relevant code:

- `src/task_scheduler/gui/widgets/job_editor.py:169`
- `src/task_scheduler/gui/widgets/job_editor.py:274-301`

Detection can perform filesystem probes and `shutil.which()` lookups:

- `src/task_scheduler/platform/macos/python_detection.py:222-287`

#### Why this matters

Typing a path on a slow filesystem or network volume can make the editor feel laggy.

#### Desired behavior

- debounce detection, or
- run it only on browse selection / edit-ended, or
- move it to a cancellable worker

#### Recommended tests

- rapid typing in the script-path field
- assert detection is not executed synchronously per keystroke
- verify final value still triggers detection

#### Planning notes

This is a UX/performance improvement rather than a safety fix.

#### Resolution (v0.0.47)

Resolved (debounce, no new `QThread`). The job editor's script-path `textChanged` now routes through a single-shot `QTimer` (`_SCRIPT_DETECTION_DEBOUNCE_MS = 300`, injectable via a `detection_debounce_ms` constructor argument). Rapid typing coalesces into one final detection; a blank path cancels the pending detection immediately; the final value still triggers exactly one detection. Detection remains synchronous on the GUI thread (no worker added) but is no longer executed per keystroke.

---

### CR-18 — Medium — Log write failures fall back to `handleError()` and do not attempt stream recovery

**Severity:** Medium  
**Confidence:** High, source-verified  
**Area:** logging resilience

#### Current behavior

On write failure, the handler uses the default `handleError()` path and does not try to reopen the stream.

Relevant code:

- `src/task_scheduler/application/app_logging.py:212-220`

#### Why this matters

After a transient disk failure, logging may stop working for the rest of the process lifetime.

#### Desired behavior

- add recovery/reopen logic, or
- explicitly mark the handler disabled and emit a structured failure event

#### Recommended tests

- simulate write failure
- assert either recovery succeeds or the failure is structurally reported
- assert no noisy default traceback behavior

#### Planning notes

This is a resilience improvement for the logging subsystem.

#### Resolution (v0.0.46)

Resolved. A write/flush/rollover failure performs one guarded recovery: close the stream best-effort, reopen it, reapply and reverify `0600`, then retry the already-rendered event once. A permanent failure disables the file handler, activates the stderr fallback, and records `log-write-failed` instead of using the default `Handler.handleError()` traceback path.

---

### CR-19 — Low — `configure_logging()` is idempotent per handler, not per log path

**Severity:** Low  
**Confidence:** High, source-verified  
**Area:** logging API

#### Current behavior

If a handler already exists, `configure_logging()` returns early even if called with a different log path.

Relevant code:

- `src/task_scheduler/application/app_logging.py:237-252`

#### Why this matters

This is a subtle API trap, even if the current app only calls it once.

#### Desired behavior

- make the idempotency semantics explicit, or
- make the function path-aware

#### Recommended tests

- call with handler already present and a different path
- assert documented behavior

#### Planning notes

Low urgency, but easy to clean up if touching logging.

#### Resolution (v0.0.46)

Resolved. `configure_logging()` is path-aware: the same path is idempotent, a different path replaces only the tagged application handler, and unrelated root handlers are preserved. A failed replacement leaves a previous healthy handler active.

---

### CR-20 — Low — Full configuration logging may include sensitive user data by design

**Severity:** Low  
**Confidence:** High, source-verified  
**Area:** product policy

#### Current behavior

The app logs full configuration values without redaction.

Relevant code:

- `src/task_scheduler/application/app_logging.py:255-277`

#### Why this matters

This is an intentional product decision, but it means environment values or other config fields may contain sensitive data.

#### Desired behavior

- keep the current behavior if the product decision stands
- explicitly document the policy and user-facing implications

#### Planning notes

No code change is required unless the product decision changes.

#### Resolution (v0.0.46)

Resolved by documentation. The approved product decision to log full configuration content without redaction is recorded in README and architecture documentation, including the user-facing implication that the stderr fallback can expose configuration values in terminal output while file logging is degraded.

---

### CR-21 — Low — `make package` is macOS/toolchain-specific

**Severity:** Low  
**Confidence:** High, source-verified  
**Area:** build / packaging

#### Current behavior

The packaging target depends on macOS-specific tools and local toolchain layout.

Relevant code:

- `Makefile:27-39`

#### Why this matters

This is expected for a macOS app, but it means packaging is not portable by design.

#### Desired behavior

- document the platform/toolchain assumptions
- optionally make paths less machine-specific

#### Planning notes

This is mostly a documentation/portability note.

#### Resolution (v0.0.47)

Resolved. `make package` now runs a preflight check that fails fast when the platform is not Darwin or when `pyside6-deploy`, `plutil`, or `codesign` are missing, and the platform/toolchain assumptions are documented. Packaging remains macOS-specific by design, but the dependency on a specific local toolchain layout is now explicit and validated before any packaging work begins.

---

## 6. Strengths to preserve

These areas worked well and should not be disturbed unnecessarily:

- clean layering between GUI, application, platform, and storage
- single production composition root
- strict static typing
- large and meaningful test suite
- 100% coverage at review time
- good controller/widget separation
- careful worker-thread lifetime handling for main-window-owned workers
- structured JSONL logging as a foundation
- external LaunchAgent edits already use staging, backups, snapshots, and drift checks in many places

The fixes below should be made **inside** this architecture, not by replacing it.

---

## 7. Recommended planning cycles

### Cycle A — Safety, shutdown, and process gates

This is the recommended next cycle.

Goal: fix the highest-impact user-facing and process risks first.

Include:

- **CR-11** — add mechanical coverage/ratio gates
- **CR-01** — fix external removal after failed bootout
- **CR-15** — fix disable/enable result messaging
- **CR-02** — include direct-test worker threads in shutdown
- **CR-10** — render raw plist as plain text

Why this grouping works:

- it protects user data and launchd state first
- it fixes shutdown safety
- it adds process gates early so later cycles are less likely to regress
- it includes at least one small, quick correctness fix

Suggested order within Cycle A:

1. CR-11
2. CR-01
3. CR-15
4. CR-02
5. CR-10

---

### Cycle B — Durable storage and logging robustness

Goal: make persistence and logging reliable under failure conditions.

**Completed in v0.0.45 and v0.0.46:** CR-03, CR-04, CR-05, CR-06, CR-07, CR-13, CR-14, and CR-18. No Cycle B items remain.

Include:

- **CR-03** — atomic JSON writes
- **CR-04** — exclusive create-only JSON operations
- **CR-05** — failure-tolerant logging startup
- **CR-06** — verify and warn on log permissions
- **CR-07** — enforce retention for the active log file
- **CR-18** — improve log write failure handling
- **CR-13** — harden import commit error handling
- **CR-14** — harden history controller error handling

Why this grouping works:

- all of these are about behavior when the happy path fails
- they touch overlapping areas
- they can be planned as one “durability and failure tolerance” theme

Suggested order within Cycle B:

1. CR-03
2. CR-04
3. CR-05
4. CR-06
5. CR-07
6. CR-18
7. CR-13
8. CR-14

---

### Cycle C — Platform hardening, packaging, and UX polish

Goal: close the remaining design-consistency, packaging, and performance gaps.

Include:

- **CR-08** — safer exclusive temp-file creation
- **CR-09** — align or strengthen verified filesystem operations
- **CR-16** — snapshot-based quarantine
- **CR-12** — portable packaging spec
- **CR-17** — debounce or defer Python detection
- **CR-19** — clarify logging idempotency semantics
- **CR-20** — document full-config logging policy
- **CR-21** — document packaging platform assumptions

**Completed in v0.0.46:** CR-19 and CR-20. **Completed in v0.0.47:** CR-08, CR-09, CR-12, CR-16, CR-17, and CR-21. No Cycle C items remain.

Why this grouping works:

- these are important, but less urgent than user-data and shutdown safety
- some require design decisions before implementation
- they fit well into a hardening/polish cycle

Suggested order within Cycle C:

1. CR-08
2. CR-09
3. CR-16
4. CR-12
5. CR-17
6. CR-19
7. CR-20
8. CR-21

---

## 8. Open design decisions

These should be decided before implementation in the next cycle.

### 8.1 External removal failure semantics

Decision needed:

- should a failed `bootout` always abort removal, or should there be an explicit “force remove” path?

Recommended default:

- abort on failed `bootout`
- no silent force-remove

---

### 8.2 Worker-thread shutdown architecture

Decision needed:

- should the GUI use:
  - a shared active-worker registry, or
  - dialog-local draining coordinated by `MainWindow`?

Recommended default:

- shared active-worker registry

---

### 8.3 Durable write strategy

Decision needed:

- should atomic writes live:
  - in `JsonJobRepository` only, or
  - in a shared storage utility used by all JSON persistence paths?

Recommended default:

- shared storage utility

---

### 8.4 Verified filesystem semantics

Decision needed:

- should the filesystem helpers:
  - be strengthened to true atomic/locked semantics, or
  - be renamed/documented as best-effort?

Recommended default:

- strengthen where feasible, otherwise align names and docs with actual behavior

---

### 8.5 Active log retention behavior

Decision needed:

- if the active `app.log` is oversized, should the app:
  - force immediate rollover, or
  - truncate the active file?

Recommended default:

- force rollover first, with truncation only as a last resort

---

### 8.6 Packaging portability target

Decision needed:

- should packaging be:
  - developer-machine only, or
  - clean-checkout portable?

Recommended default:

- clean-checkout portable

---

## 9. Suggested next-cycle entry point

If the next cycle is kept tight, start with this slice:

1. **CR-11** — make `make check` enforce coverage and ratio
2. **CR-01** — stop external removal after failed bootout
3. **CR-15** — make disable/enable messages reflect actual phase success
4. **CR-02** — include direct-test threads in shutdown drain
5. **CR-10** — render raw plist as plain text

That gives a next cycle that is:

- high-value
- mostly small-to-medium sized
- focused on user trust and shutdown safety
- easy to verify with targeted tests

---

## 10. Suggested verification strategy for the next cycle

For each implemented item, the cycle should verify:

- targeted unit tests
- integration tests where behavior crosses layers
- no regression in:
  - `ruff`
  - `mypy --strict`
  - full test suite
  - 100% coverage
  - test/source ratio

For the highest-risk items, explicitly add tests for:

- failed `launchctl` steps
- shutdown with active workers
- atomic write failure
- log permission failure
- oversized active log
- concurrent create-only writes

---

## 11. Documentation status

As of v0.0.47, every finding in this document is resolved (CR-01–CR-21 across v0.0.44–v0.0.47); the planning notes below are retained for reference.

This file was originally the planning input for the next cycle.

It is **not** yet:

- an approved `PLAN.md`
- a `TODOS.md` task board
- an implementation commit

Next step when ready:

- promote the chosen cycle into `PLAN.md`
- break the chosen items into `TODOS.md`
- start implementation only after that planning pass is complete
