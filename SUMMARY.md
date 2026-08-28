# SUMMARY.md

## Changelog

### v0.0.8
- Crawl Increment 8: `mactask` CLI — Typer app with 12 commands (list, inspect, validate, generate, install, uninstall, enable, disable, status, run, test, logs) sharing the application-service layer with the future GUI
- `TaskCommandService` façade (12 operations) + `JobService` (app-owned JSON job catalog, create-only install conflict detection) + `LogService` (read-only stdout/stderr readers); `<job>` is always the exact managed launchd label resolved from the catalog
- Exit codes 0/1/2 (success / launchd failure / usage error), reports and plist XML to stdout, errors and diagnostics to stderr; all launchd interaction still via `LaunchAgentBackend` + `ProcessRunner`
- 85 new unit tests, 328 total, 100% coverage, ruff + mypy strict clean

### v0.0.7
- Crawl Increment 7: launchctl adapter — `LaunchAgentBackend` coordinates storage + launchctl for `install` (write then bootstrap), `uninstall` (bootout then remove), `status` (print → loaded True/False/None), `enable`, `disable`, `trigger` (kickstart -k), user `gui/<uid>` domain only via `/bin/launchctl` through `ProcessRunner`
- Structured lifecycle results (`LaunchctlResult`, `LaunchAgentStatus`) preserve exact `ProcessResult`; failed bootstrap/bootout retains the plist for diagnosis; shared public `validate_label` guards all raw-label entry points
- Protected integration tests behind the `integration` marker + `MACTASK_ALLOW_SYSTEM_TESTS=1` (unique UUID labels, unconditional cleanup); plain `pytest`/`make test`/`make check` never run them; `make integration` added
- 35 new unit tests, 243 total, 100% coverage, ruff + mypy strict clean

### v0.0.6
- Crawl Increment 6: LaunchAgent Storage — `LaunchAgentStore` writing (create-only, atomic exclusive-link so an existing plist is never overwritten), removing (idempotent), and discovering plists under `~/Library/LaunchAgents` (or an injected root)
- `LaunchAgentFilesystem` protocol + `LocalFilesystem`: all store file IO flows through the abstraction so unit tests never touch real user directories; discovery parses via the never-raising reader and reports supported/partially-supported/invalid plists without mutating them
- Store-boundary label validation (no path separators, no `.`/`..`) guards the raw-string `remove`/`destination_for` entry points
- `FakeFilesystem` test fake; 31 new tests, 208 total, 100% coverage, ruff + mypy strict clean

### v0.0.5
- Crawl Increment 5: Direct Test Runner — `ProcessRunner` port + `SubprocessRunner` (only subprocess caller, exact job environment, no timeout, structured launch failures, injectable clock), `DirectTestService` (argv via shared `command_argv`, no job mutation), `diagnostic_service` with 7 structured rules in deterministic order
- `command_argv` promoted to the domain as the single argv source of truth; `PlistCodec` refactored onto it
- `tests/fakes.py` with `FakeProcessRunner`/`FakeClock`; 37 new tests, 177 total, 100% coverage, ruff + mypy strict clean

### v0.0.4
- Crawl Increment 4: Python detection — `detect_python` finds candidate interpreters (`.venv`, `venv`, current interpreter, PATH-discovered `python3`) in priority order with executable-file qualification and spelling-based deduplication; `compare_environments` reports structured terminal/scheduled differences without ever capturing a shell
- Injectable `current_interpreter` and `path_lookup` keep tests host-independent (all `tmp_path`-based)
- 16 new tests; 140 total, 100% coverage, ruff + mypy strict clean

### v0.0.3
- Crawl Increment 2: plist encoder — `PlistCodec.encode_dict/encode_bytes` producing launchd XML plists from `JobDefinition` (Label, ProgramArguments, StartCalendarInterval, WorkingDirectory, EnvironmentVariables, StandardOutPath, StandardErrorPath, Disabled)
- Crawl Increment 3: plist reader — `parse_bytes/parse_path` classifying existing LaunchAgent plists as supported / partially_supported / invalid; never raises; raw dict always preserved
- Shared launchd representation pinned in `plist_models.py` (weekday mappings, SUPPORTED_KEYS, ParseSupport, ParsedLaunchAgent)
- Golden fixtures (JSON + plist bytes) and 14 reader fixtures added
- 123 tests, 100% coverage, ruff + mypy strict clean

### v0.0.2
- Integrated upstream repository (branch: sched_dev_opencode)
- Project files updated to reflect actual repo contents
- README.md and spec.md.md from upstream repo

### v0.0.1
- Created project "macOS Task Scheduler for Humans"
- Added initial PROJECT.md, PLAN.md, TODOS.md
