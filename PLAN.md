# PLAN.md

## Current State
Crawl Increments 0–7 complete and pushed to `sched_dev_opencode` (commits through `a8a3e27`, version 0.0.7):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model + schema-versioned JSON persistence
- **Increment 2:** plist encoder (`PlistCodec`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`) + fixtures + round-trip tests
- **Increment 4:** Python detection (`detect_python`, `compare_environments`) + tests
- **Increment 5:** Direct test runner (`SubprocessRunner`, `DirectTestService`, `evaluate_diagnostics`) + tests
- **Increment 6:** LaunchAgent storage (`LaunchAgentStore` write/remove/discover + `LaunchAgentFilesystem`) + tests
- **Increment 7:** launchctl adapter (`LaunchAgentBackend` install/uninstall/status/enable/disable/trigger) + protected integration tests
- Verification at v0.0.7: 243 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 8 — CLI** (IN PROGRESS).

## Blockers
None

## Strategy
First-class Typer CLI (`mactask`) so a developer completes the primary job lifecycle entirely
from Terminal (spec lines 1856–1873, 1051–1089). The CLI is a presentation layer: it parses
arguments, calls one application façade method, renders the returned result, and selects the
exit code. All OS side effects flow through platform abstractions (`ProcessRunner`,
`LaunchAgentStore`, `LaunchAgentBackend`, `PlistCodec`) so unit tests never invoke real
`/bin/launchctl` or touch the real `~/Library/LaunchAgents`.

### Pinned decisions (approved)
1. **`<job>` identity = exact managed launchd label**, resolved from the application-owned
   JSON catalog. `inspect`/`test`/`logs` need the full `JobDefinition` (plist re-parse loses
   the id/name), so the catalog is the source of truth.
2. **Managed catalog:** `~/Library/Application Support/macOS Task Scheduler for Humans/jobs/<uuid>.json`
   (spec lines 1319–1326). One file per managed job, keyed by job id. Root and repository are
   injectable. JSON is the persisted source of truth; the plist is the deployment artifact.
3. **`install` is create-only:** import to catalog first (raises `JobConflictError` when the
   id already exists), then `backend.install` (raises `FileExistsError` when the plist
   exists). No overwrite/update semantics this increment.
4. **`generate` emits the XML plist to stdout** — pure, no filesystem side effects.
5. **`logs` reads both streams:** full read of the configured stdout+stderr with stream
   headings; unconfigured/missing/unreadable → clear error text and exit 2. No tail/follow.
6. **`test` = direct test (Mode A)** via `DirectTestService`; **`run` = launchd trigger** via
   `backend.trigger` (`kickstart -k`). Never conflated.
7. **Exit codes:** 0 success; 1 lifecycle/direct-test/process failure; 2 invalid input,
   validation error, unsafe/unknown label, create-only conflict, missing log data. Errors go
   to stderr; reports and generated XML go to stdout.
8. **Shared façade:** `TaskCommandService` orchestrates every command; the future GUI
   (Increments 9–12) calls the same service (spec 230–248, 1089, 2542–2550).
9. **`list`/`inspect` cover all user LaunchAgents discovered** under the root, annotated with
   parse-support status, warnings, and a managed flag cross-referenced with the catalog.
10. **Label safety:** every raw-label façade method validates via the shared `validate_label`
    before any runner call; unsafe label → exit 2.

### API contract (pinned before implementation)
- `src/task_scheduler/application/job_service.py`:
  - `JobNotFoundError(label)`, `JobConflictError(label, path)` (Exception subclasses)
  - `default_job_catalog_root() -> Path`
  - `JobService(root=None, *, repository=None)`: `root` property,
    `list_jobs() -> list[JobDefinition]` (sorted by label; missing root → `[]`;
    direct-child `*.json` files only), `find(label) -> JobDefinition | None`,
    `resolve(label) -> JobDefinition` (raises `JobNotFoundError`),
    `import_job(job) -> Path` (raises `JobConflictError`), `remove(job_id) -> bool` (idempotent)
- `src/task_scheduler/platform/macos/log_reader.py`:
  - `LogReadResult(content, error)` model; `LogReader` protocol; `LocalLogReader`
    (never raises: `FileNotFoundError` → not-found error; other `OSError`/
    `UnicodeDecodeError` → read error)
- `src/task_scheduler/application/log_service.py`:
  - `LogStream(name, path, content, error)`, `JobLogs(stdout, stderr)` models
  - `LogService(reader=None).read(job) -> JobLogs` (never raises; unconfigured stream = `path` None)
- `src/task_scheduler/application/task_command_service.py`:
  - DTOs: `AgentListing(path, parsed, managed)`, `InspectReport(job, plist, status)`,
    `InstallResult(job, plist_path, process)`, `UninstallResult(label, process, catalog_removed)`
  - `TaskCommandService(repository, jobs, store, backend, codec, test, logs)`:
    `list_agents`, `inspect`, `validate_json`, `generate_plist`, `install_json`,
    `uninstall`, `enable`, `disable`, `status`, `run_now`, `test`, `read_logs`
  - `uninstall`: validate → catalog `find` (tolerant) → `backend.uninstall` → remove the
    catalog record only on exit 0
- `src/task_scheduler/cli/{__init__,app,render}.py`: `create_app(services)` Typer factory
  (12 commands, closures over the injected `TaskCommandService`), production
  `build_services()`, `main()` entry point; `render.py` plain-text renderers + exit-code
  constants
- `pyproject.toml`: `typer` runtime dependency; `[project.scripts] mactask = "task_scheduler.cli.app:main"`

### Tests
- `tests/unit/application/test_job_service.py` (tmp_path roots): missing root, sorted job
  listing, non-`.json` skipped, find/resolve hit/miss, import (create + conflict),
  remove present/absent
- `tests/unit/application/test_log_service.py` (reader + service): unconfigured, existing
  (empty + non-empty), missing file, unreadable (directory path), non-UTF-8 content
- `tests/unit/application/test_task_command_service.py`: `list_agents` managed flag,
  `inspect` (catalog + plist parse + status), `validate_json`/`generate_plist`,
  `install_json` (catalog + plist + bootstrap ordering, conflicts), `uninstall` (catalog
  removal only on success), lifecycle delegation, label rejection, `test`/`read_logs`
  resolution errors
- `tests/unit/cli/` (Typer `CliRunner` against `create_app` with fakes): all 12 commands —
  output, exit codes (0/1/2), invalid JSON, unknown label, unsafe label, install conflict,
  lifecycle failure, direct-test launch failure + diagnostics rendering, logs
  unconfigured/missing states
- No CLI test touches the real `~/Library/LaunchAgents`, real log directories, or
  `/bin/launchctl`; plain `pytest` still excludes integration tests

### Exit criteria
- `make check` green; 100% coverage on new modules
- All logic files < 500 lines (decomposition review at 400–450)
- CLI imports no `LaunchAgentStore`/`LaunchAgentBackend`/`SubprocessRunner` outside the
  `build_services()` composition root
- `mactask --help` lists all 12 commands; exit-code contract verified in tests
- Version bump 0.0.7 → 0.0.8 with docs in the final commit; push every commit
