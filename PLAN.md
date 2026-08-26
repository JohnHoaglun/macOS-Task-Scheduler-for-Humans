# PLAN.md

## Current State
Crawl Increments 0–4 complete and pushed to `sched_dev_opencode` (commits through `64172e2`, version 0.0.4):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model + schema-versioned JSON persistence
- **Increment 2:** plist encoder (`PlistCodec`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`) + fixtures + round-trip tests
- **Increment 4:** Python detection (`detect_python`, `compare_environments`) + tests
- Verification at v0.0.4: 140 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 5 — Direct Test Runner**.

## Blockers
None

## Strategy
Direct Test (Mode A): execute a job's exact argv with its explicit environment and working
directory, capture exit code/stdout/stderr/duration, and produce structured diagnostics.
No timeout, no launchd, no LaunchAgent writes, no shell-environment capture, no CLI/GUI.

### Pinned decisions (approved)
1. **Environment:** the process receives exactly `job.environment.variables` (no inherited env).
2. **Timeout:** none in this increment; no timeout/cancellation API.
3. **Launch failures:** missing executable / permission / OS error return a structured
   `ProcessResult` with `exit_code=None` + `launch_failure` (machine-readable kind);
   services never leak `OSError`; no synthetic exit codes.
4. **Diagnostics:** all seven specified rules, structured as
   `severity`/`code`/`title`/`description`/`suggested_action`.
5. **PATH-dependence rule:** `JobDefinition` absolute-path validation stays; the rule is
   evaluated defensively at the `CommandSpec`/argv boundary (malformed imported inputs).

### API contract (pinned before implementation)
- `src/task_scheduler/platform/macos/process_runner.py` (exports via platform `__init__`):
  - `LaunchFailureKind(StrEnum)`: `NOT_FOUND`, `PERMISSION_DENIED`, `OS_ERROR`
  - `ProcessLaunchFailure(kind, message)`
  - `CommandSpec(argv: list[str], environment: dict[str, str] = {}, working_directory: Path | None = None)`
  - `ProcessResult(exit_code: int | None, stdout: str, stderr: str, duration: timedelta, launch_failure: ProcessLaunchFailure | None)`
  - `ProcessRunner` protocol: `run(spec: CommandSpec) -> ProcessResult`
  - `SubprocessRunner(clock=None)` — only code allowed to call `subprocess`;
    `check=False`, `capture_output=True`, `text=True`, exact `env`, no timeout;
    clock injectable for deterministic durations; `FileNotFoundError`→NOT_FOUND,
    `PermissionError`→PERMISSION_DENIED, `OSError`→OS_ERROR.
- `src/task_scheduler/domain/command.py`: public `command_argv(command: Command) -> list[str]`
  (python: `[interpreter, script, *args]`; shell/executable: `[executable, *args]`);
  `PlistCodec` refactored to use it — one argv source of truth.
- `src/task_scheduler/application/` (new package):
  - `test_service.py`: `DirectTestService(runner: ProcessRunner)` with
    `run(job: JobDefinition, *, detection: PythonDetectionResult | None = None) -> DirectTestResult`
    (`process: ProcessResult`, `diagnostics: list[Diagnostic]`);
    never mutates the job, never writes log paths, never calls subprocess.
  - `diagnostic_service.py`: `DiagnosticSeverity` (`ERROR`/`WARNING`/`INFO`),
    `Diagnostic(severity, code, title, description, suggested_action)`,
    `evaluate_diagnostics(job=None, *, process=None, spec=None, detection=None) -> list[Diagnostic]`
    — pure, deterministic rule order:
    1. `executable_missing` (ERROR): command executable/interpreter not a file
    2. `script_missing` (ERROR): Python script not a file
    3. `working_directory_missing` (ERROR): configured wd not a directory
    4. `permission_denied` (ERROR): executable exists but not `X_OK`, or process launch
       failed with `PERMISSION_DENIED`
    5. `relative_executable` (WARNING): `spec.argv[0]` not absolute (defensive, spec level)
    6. `interpreter_mismatch` (WARNING): Python job interpreter differs from first
       `.venv`/`venv` detection candidate
    7. `module_not_found` (WARNING): `ModuleNotFoundError` in process stderr

### Tests
- `tests/fakes.py`: reusable `FakeProcessRunner` (records specs, scripted result) and
  `FakeClock` (deterministic monotonic); `pythonpath` extended to `["src", "tests"]`.
- `tests/unit/platform/test_process_runner.py`: exit code, stdout/stderr capture, exact
  env, cwd, injected-clock duration, NOT_FOUND/PERMISSION_DENIED/OS_ERROR failures.
- `tests/unit/application/test_test_service.py`: argv per command kind, exact env/cwd
  forwarding, result propagation, empty diagnostics for a healthy tmp_path job,
  interpreter-mismatch via injected detection, job not mutated.
- `tests/unit/application/test_diagnostic_service.py`: positive + negative for every rule.
- Host independence: `tmp_path` only; no `launchctl`, no LaunchAgent dirs, no developer
  Python env (runner tests use `/bin/echo`, `/usr/bin/false`, `/bin/pwd`, `/usr/bin/env`).

### Exit criteria
- `make check` green; coverage target 100% (≥90% floor) on new modules
- All logic files < 500 lines
- Version bump 0.0.4 → 0.0.5 with docs in the final commit; push every commit
