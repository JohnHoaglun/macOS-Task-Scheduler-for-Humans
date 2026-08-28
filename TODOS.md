# TODOS.md (v0.0.8)

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

## Crawl Increment 9 — GUI Read/Discovery (PENDING)
- [ ] PySide6 main window
- [ ] Discover, list, inspect, visualize

## Crawl Increment 10 — GUI Job Creation (PENDING)
- [ ] New Task, Edit, Save, Validate
- [ ] Python, Shell, Executable forms
- [ ] Schedule: specific time + weekdays

## Crawl Increment 11 — GUI Installation (PENDING)
- [ ] Install, Uninstall, Enable, Disable, Run Now

## Crawl Increment 12 — GUI Diagnostics and Logs (PENDING)
- [ ] Test, stdout/stderr viewer, diagnostics, env comparison

## Crawl Increment 13 — Packaging (PENDING)
- [ ] macOS .app bundle via PySide6 deployment
