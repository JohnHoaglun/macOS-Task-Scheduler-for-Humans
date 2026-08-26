# SUMMARY.md

## Changelog

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
