# TODOS.md (v0.0.6)

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

## Crawl Increment 7 — launchctl Adapter (PENDING)
- [ ] install, uninstall, status, enable, disable, trigger
- [ ] ProcessRunner abstraction
- [ ] Integration tests with MACTASK_ALLOW_SYSTEM_TESTS=1

## Crawl Increment 8 — CLI (PENDING)
- [ ] mactask list/inspect/validate/generate/install/uninstall/enable/disable/status/test/run/logs

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
