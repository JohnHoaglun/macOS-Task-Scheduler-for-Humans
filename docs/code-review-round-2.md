# Code Review — Round 2

- **Baseline:** v0.0.47, commit `6277a2e` (branch `sched_dev_opencode`)
- **Date:** 2026-09-21
- **Scope:** production code under `src/task_scheduler/` (82 files, ~14,200 lines). Tests were read only as evidence, not reviewed for their own quality.
- **Method:** full-file solo scan (platform → storage → domain → application → CLI → GUI), cross-checked against the durable CR-01…CR-21 record in `docs/code-review-findings.md` (all resolved in v0.0.44–v0.0.47; none re-reported here).
- **Verdict:** no high/critical items. **8 medium, 17 low.** No code was changed; nothing was committed.

## Findings

### Medium

#### R2-01 — External raw-edit label invariant enforced only by `assert` (logic/robustness)
- `commit_raw_external_edit`: label-change guard at `application/task_command_service.py:935-940`, `assert session.label is not None` at `:960`.
- Reachable: `open_external_edit_session` accepts plists with no usable `Label` (`task_command_service.py:795-810` → `label=None`, `loaded=None`) → `MainWindow._edit_external_listing` (`gui/main_window.py:438-439`) → `_open_raw_editor` (`gui/main_window.py:906-952`) → `ExternalControlWorker` (`gui/controllers/external_control_worker.py:87-93`).
- Consequence: saving a replacement that adds a new valid label hits the assert. Debug build: `AssertionError` is caught by the worker's `except Exception` and the GUI shows an **empty** error string (`str(AssertionError()) == ""`). Release/`-O`: the assert is compiled out, `session.loaded` is always `None` for a label-less session so the bootout/bootstrap branches are skipped, and the file is silently replaced with a new label — the "label cannot change" invariant is silently violated.
- Recommendation: raise `ValueError` explicitly when `session.label is None and new_label is not None` (the session cannot gain a label through a raw edit); drop the assert.

#### R2-02 — Worker exceptions swallowed silently; no log, no user feedback (logging/robustness)
- `gui/controllers/lifecycle_worker.py:31-34` and `gui/controllers/diagnostics_worker.py:31-34`: `except Exception: outcome = None`, no log statement.
- `MainWindow._on_lifecycle_finished` (`gui/main_window.py:1128-1129`) returns without any status message, dialog, or log when the outcome is not a `LifecycleOutcome`. A failed install/uninstall/run-now leaves the user with a re-enabled action and no explanation.
- Recommendation: log the exception (with traceback) in the worker before emitting `None`, and surface a minimal "operation failed; see log" status message in the window.

#### R2-03 — Synchronous launchctl fan-out on the GUI thread (logic/UX)
- `DiscoveryController.refresh` (`gui/controllers/discovery_controller.py:45-51`) calls `list_agents()` synchronously.
- `list_agents` (`application/task_command_service.py:262-288`) calls `_loaded_status` (`:249-260`) once per discovered agent — one `launchctl print` subprocess per agent — on the GUI thread (refresh button and post-operation refresh).
- Recommendation: move discovery refresh to a worker thread (the pattern already exists for lifecycle/diagnostics), or drop the per-agent launchd probe from listing and resolve it lazily.

#### R2-04 — One corrupt catalog file breaks the whole catalog (logic/robustness)
- `JobService.list_jobs` (`application/job_service.py:116-129`) propagates any `repository.load` failure; `find`/`resolve`/`transfer_conflicts`/`list_agents`/GUI listing all route through it. A single malformed `*.json` makes every managed task inaccessible.
- Recommendation: quarantine or skip the unreadable record with a surfaced diagnostic (analogous to the plist parse-status model used for external agents) instead of failing the listing.

#### R2-05 — No recovery path when bootout fails (logic/UX)
- `uninstall` (`application/task_command_service.py:584-591`; `platform/macos/launchctl.py:100-109`) and `reinstall` (`task_command_service.py:368-405`, abort at `:388-389`) both require a successful `launchctl bootout`.
- A job whose bootstrap failed at install time (never loaded) cannot be uninstalled or reinstalled by the app — `bootout` of an unloaded label fails — so recovery is manual deletion of the catalog JSON (and plist). Repeated failed reinstalls also accumulate `.staged.N` siblings.
- Recommendation: offer an explicit recovery path when bootout reports "not loaded" (e.g., allow plist+catalog removal without a successful bootout, or a force flag), and clean up the staged sibling on the failure branch.

#### R2-06 — qFatal no longer aborts (logging/robustness)
- `install_qt_message_handler` (`gui/qt_message_logging.py:37-39,47`) logs `QtFatalMsg` at CRITICAL and returns normally; `qInstallMessageHandler` replaces Qt's default handler, which aborts on fatal. The module docstring (`:3-6`) documents capturing qFatal but not the suppressed abort.
- After a fatal Qt error the process continues in an undefined state, logged but unrecovered.
- Recommendation: on `QtFatalMsg`, log, flush, and abort (Qt's documented handler contract), or document the deliberate deviation.

#### R2-07 — Unbounded execution-history growth (logging/data growth)
- `status()` records a `STATUS_OBSERVATION` event on every call (`application/task_command_service.py:603-617`); `run_now` does likewise.
- The SQLite history store (`storage/execution_history_repository.py`) is append-only with **no retention, rotation, or pruning** anywhere; reads are capped at 100 rows but the database file grows without bound for the life of the app.
- Recommendation: add a retention policy (e.g., cap rows per job or prune by age on open) or document the expected size profile and add a size guard.

#### R2-08 — Unbounded synchronous log reads (logic/performance)
- `LocalLogReader.read` (`platform/macos/log_reader.py:39-45`) reads the entire file, no size cap.
- Callers: GUI `direct_test_dialog._render_logs` (`gui/widgets/direct_test_dialog.py:124-127`, synchronous on the GUI thread on every manual refresh) and the diagnostics path; CLI `logs` command (`cli/app.py:247-261`) and `format_stream` (`cli/render.py:179-190`) dump the full content to the terminal.
- A long-lived job's stderr can be arbitrarily large; reads stall the GUI and flood the terminal.
- Recommendation: cap the read (tail the last N KB) or read off-thread in the GUI.

### Low

#### R2-09 — Dead telemetry API (logging)
- `emit_event` (`application/app_logging.py:444`) and `emit_error` (`:469`) are only referenced from tests; production code never emits structured telemetry events.
- Recommendation: wire them into real operation boundaries or delete them.

#### R2-10 — Subprocess has no timeout and no explicit encoding (logic/design note)
- `SubprocessRunner.run` (`platform/macos/process_runner.py:71-72,81-88`): no timeout (documented "by design"), `text=True` without explicit encoding (locale-dependent decode).
- A hung `launchctl` blocks the worker indefinitely; the close drain waits until its deadline and then exits while the worker thread is still running (orphaned).
- Recommendation: document the hang expectation explicitly at the call sites and consider a generous timeout with a diagnostic on expiry.

#### R2-11 — `save()` skips the catalog lock (logic)
- `JobService.save` (`application/job_service.py:210-222`) performs the label-conflict check without the `_catalog_lock` that `import_job` holds (`:199-208`). Concurrent duplicate-label writes can both pass the check.
- Practical risk is low (single-user app) but the two write paths are inconsistent.
- Recommendation: hold the lock in `save` as well.

#### R2-12 — History append silently drops write failures (logging)
- `ExecutionHistoryRepository.append` (`storage/execution_history_repository.py:114-115`) swallows `(sqlite3.Error, OSError)` with `pass` — no log, and no `_unavailable` flag (contrast with the constructor, `:76-77`, which sets it).
- Recommendation: at minimum log the failure once; consider marking the repository unavailable on persistent errors so the UI can show degraded history.

#### R2-13 — Crash hooks cover Python only; dialog thread invariant is latent (logging/robustness)
- `install_crash_hooks` (`application/app_logging.py:510-573`) installs `sys.excepthook` + `sys.unraisablehook` only; no `faulthandler`/signal handlers, so a native crash leaves no log or dialog.
- The `on_crash` callback (`gui/app.py:51-57`) creates a `QMessageBox` on whatever thread the uncaught exception propagated on. Today all three workers catch `Exception` in their slots, so it only fires on the GUI thread; a `BaseException` or a future worker without a catch would show a modal from a non-GUI thread (undefined behavior).
- Recommendation: register `faulthandler` for core dumps to the log, and make the crash dialog explicitly GUI-thread-marshaled.

#### R2-14 — Inconsistent CLI exception containment and exit codes (logging/UX)
- `cli/app.py`: `list` (`:70-78`) and `test` (`:234-245`) have no containment at all (traceback on catalog corruption, `OSError`, invalid label); `inspect` (`:80-90`) catches only `JobNotFoundError`; `validate` (`:92-104`), `generate` (`:106-117`), `install` (`:133-134`) map **any** `Exception` to "invalid job definition" (masking e.g. a file deleted between `exists=True` and read); `import` (`:304`) and `import-json` (`:339`) exit 2 with an **empty** stderr message via `_fail("")`; `logs` (`:258-261`) exits with `EXIT_USAGE` (2) on a log-read failure, which is an operational error, not a usage error.
- Recommendation: adopt the narrow `JobNotFoundError`/`ValueError`/`OSError` containment used by the lifecycle commands everywhere; reserve exit 2 for usage; use a non-empty message for the acknowledgement prompt path.

#### R2-15 — Broad `except Exception` around `plistlib.loads`; inconsistent catch style (logic)
- `commit_raw_external_edit` (`application/task_command_service.py:924-927`) converts any exception from `plistlib.loads` into "not a valid plist", masking non-parse faults (e.g. memory errors).
- Catch style varies across equivalent paths: `JsonTransferController` uses broad `except Exception` (`gui/controllers/json_transfer_controller.py:67,95`) while the CLI import uses narrow `(ValueError, OSError)` (`cli/app.py:297`).
- Recommendation: catch the parse-specific exceptions (`plistlib.InvalidFileException` / `ValueError`) and normalize the controller/CLI catch sets.

#### R2-16 — Symlink containment inconsistent across filesystem paths (security, low risk)
- `read_plist_bytes` (`platform/macos/filesystem.py:91-92`) and `list_plist_files` (`:94-97`, `is_file()` follows symlinks) follow symlinks, while `read_snapshot` (`:154-169`, `O_NOFOLLOW`, ELOOP surfaced) rejects them.
- A symlinked plist is therefore discovered and readable, but the edit path refuses it. Risk is low (the user owns `~/Library/LaunchAgents`) but the security model is inconsistent.
- Recommendation: decide one policy (reject symlinks everywhere, or allow them everywhere with documentation) and apply it at the discovery layer.

#### R2-17 — `bootstrap_path` does not check Label/path consistency (logic)
- `LaunchAgentBackend.bootstrap_path` (`platform/macos/launchctl.py:126-136`) validates the path is under the LaunchAgent root but never verifies the plist's `Label` key matches the `label` argument. All reachable flows happen to pass consistent values; the API does not enforce it.
- Recommendation: parse the staged plist and require `Label == label` before bootstrapping.

#### R2-18 — Incorrect docstring; interpreter detection re-runs after every editor open (logic/minor)
- `gui/widgets/job_editor.py:647` claims "setText never re-triggers the change slots", but `_load_draft`'s `setText` calls (`:651-661`) re-fire the `textChanged`-connected interpreter detection; the 300 ms debounce (CR-17) suppresses typing storms, not the one post-open probe, which runs a PATH check on the GUI thread.
- Recommendation: fix the docstring and either block signals during `_load_draft` or defer the post-open detection to the event loop.

#### R2-19 — GUI/CLI display inconsistencies (UX)
- `format_schedule_value` uses `%H:%M:%S` (`gui/presenters/agent_presenter.py:153`) while the CLI renders `%H:%M`; the domain forbids seconds, so the GUI always shows a trailing `:00`.
- `format_command` (`agent_presenter.py:127-137`) and `import_preview_dialog.py:138` join argv with plain spaces (no quoting), while the search haystack (`gui/models/agent_table_model.py:61`) and `shell_safe_command` (`agent_presenter.py:145`) quote with `shlex.quote`.
- Recommendation: use one time format and one command-rendering helper across GUI and CLI.

#### R2-20 — `HistoryTableModel.header` missing bounds check (logic)
- `gui/models/history_table_model.py:50-53` indexes `COLUMNS[section]` unchecked; `AgentTableModel.headerData` guards it (`gui/models/agent_table_model.py:97-100`). An out-of-range section query would raise `IndexError` in Qt's header path.
- Recommendation: mirror the bounds check.

#### R2-21 — Filter recompute cost on the GUI thread (performance)
- `AgentFilterProxyModel.filterAcceptsRow` (`gui/models/agent_filter_proxy_model.py:82-108`) does six `data()` role reads per row per filter pass; each non-DisplayRole read re-runs `dimensions(listing)` (`gui/models/agent_table_model.py:115`) and the search-text role re-quotes the full argv (`:61`) per row per pass — O(rows × args) on the GUI thread for every search keystroke and combobox change.
- Recommendation: cache the per-row search text/dimensions in the source model (or a side table) invalidated by `set_agents`.

#### R2-22 — External import commits the preview snapshot without re-reading the source (logic, documented)
- `import_external_plist` (`application/task_command_service.py:445-467`) commits the preview-time parsed snapshot; the source plist may drift between preview and commit. Documented in the docstring, and lower risk than raw edit (which does drift-check at `:949-953`), but the two external paths have different drift semantics.
- Recommendation: re-snapshot and compare at commit, or state the snapshot-only semantics in the user-facing import preview.

#### R2-23 — `_open_raw_editor` does synchronous file IO and base64 round-trip on the GUI thread (performance, trivial)
- `gui/main_window.py:906-918`: `read_bytes()` + UTF-8 decode or base64-encode of the whole plist on the GUI thread. Trivial for typical plist sizes, but it is the only synchronous read in that flow.
- Recommendation: fold into the worker-based open path if that flow is ever reworked.

#### R2-24 — `backup_external` creates an empty backup sibling when the source vanished (logic, dead path)
- `platform/macos/launch_agent_store.py:196-211`: `FileNotFoundError` → `payload = b""` → an empty `.backup.N` file. The method is production-dead (tests only; the live path uses `backup_external_from_snapshot`, `:227-242`, which writes the snapshot payload and cannot be empty). Already documented in `PLAN.md:1673`.
- Recommendation: delete the dead method or make it fail instead of writing an empty artifact.

#### R2-25 — CLI installs full app logging and crash hooks (logging, cross-ref CR-20)
- `cli/app.py:354-362`: `configure_logging()` + `install_crash_hooks()` run for every CLI invocation. When file logging is degraded, the JSONL stderr fallback can interleave with command output (documented product decision via CR-20; the CLI-specific consequence is that piped output is no longer machine-stable in that state).
- Recommendation: consider a quieter CLI profile (file log only, no stderr fallback) or document the degraded-output caveat in the CLI help.

## Checked and cleared (no finding)

- Calendar-time round-trip through the editor; user-input label bypass into `save_managed_job` (`validate_job` is enforced at the service boundary); `ImportController` catch set (narrow, correct).
- `_on_test_draft` → `build_job` unhandled-exception concern: `validate()` wraps the identical construction and is always called first on the same thread, so the failure mode is unreachable.
- Discovery refresh does **not** amplify history: `_loaded_status` is explicitly an unrecorded read (`task_command_service.py:249-260`); only explicit `status()`/`run_now()` calls record events.
- No periodic GUI timer drives status refresh — all history writes are user-initiated.
- `backup_external_from_snapshot` writes the snapshot payload (no empty-backup defect in the live path).
- `ExternalControlWorker` marshals raw-edit commit on a worker thread and surfaces the exception object to the UI (better than the lifecycle/diagnostics workers; see R2-02).

## Out of scope / not changed

- No fixes were made; this is a review deliverable only.
- Test-suite quality, packaging, and documentation accuracy were not part of this round.
- Nothing was committed (per AGENTS.md, commits require an explicit request).
