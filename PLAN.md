# PLAN.md

## Current State
Crawl Increments 0–6 complete and pushed to `sched_dev_opencode` (commits through `6d4bc5e`, version 0.0.6):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model + schema-versioned JSON persistence
- **Increment 2:** plist encoder (`PlistCodec`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`) + fixtures + round-trip tests
- **Increment 4:** Python detection (`detect_python`, `compare_environments`) + tests
- **Increment 5:** Direct test runner (`SubprocessRunner`, `DirectTestService`, `evaluate_diagnostics`) + tests
- **Increment 6:** LaunchAgent storage (`LaunchAgentStore` write/remove/discover + `LaunchAgentFilesystem`) + tests
- Verification at v0.0.6: 208 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 7 — launchctl Adapter** (IN PROGRESS).

## Blockers
None

## Strategy
User-domain LaunchAgent lifecycle through `launchctl`: `install`, `uninstall`, `status`,
`enable`, `disable`, `trigger` (spec lines 1833–1852). Every command goes through
`ProcessRunner`; unit tests use fake `launchctl` results; real behavior lives in
protected integration tests (`MACTASK_ALLOW_SYSTEM_TESTS=1`, unique UUID labels,
teardown cleanup).

### Pinned decisions (approved)
1. **User domain only:** target `gui/<uid>`; `uid` injectable, defaults to `os.getuid()`.
   Never target `/Library`, system domains, or LaunchDaemons in this increment.
2. **Absolute `/bin/launchctl`** with the exact empty `CommandSpec.environment`
   (no inherited `PATH` — launchctl itself needs none).
3. **Commands:** install `bootstrap gui/<uid> <path>`; uninstall `bootout gui/<uid>/<label>`;
   status `print gui/<uid>/<label>`; enable `enable gui/<uid>/<label>`;
   disable `disable gui/<uid>/<label>`; trigger `kickstart -k gui/<uid>/<label>`.
4. **Structured results, no exceptions:** lifecycle ops return `LaunchctlResult(action,
   process)` preserving the exact `ProcessResult` (non-zero exits and launch failures
   included); only label validation and storage conflicts raise.
5. **Backend coordinates storage + launchctl:** `install(job)` = `store.write(job)` then
   `bootstrap` the derived path; `uninstall(label)` = `bootout` first, then
   `store.remove(label)` only on a successful (exit 0) bootout.
6. **Failure compensation: retain state for diagnosis** — failed bootstrap keeps its
   newly written plist; failed bootout keeps its plist; no rollback/re-bootstrap.
7. **Status mapping:** `loaded=True` only on completed exit 0; `loaded=False` on non-zero
   completion; `loaded=None` (unknown) when the process never launched — launch
   failures are never silently reported as unloaded.
8. **`JobDefinition.enabled` is not mutated** by any lifecycle operation; plist state
   and runtime launchd state remain distinct.
9. **Label safety:** public `validate_label(label)` (shared, now exported from
   `launch_agent_store`) guards every raw-label backend method and the store; the
   backend never accepts arbitrary plist paths.

### API contract (pinned before implementation)
- `src/task_scheduler/platform/macos/launchctl.py`:
  - `LAUNCHCTL_PATH = "/bin/launchctl"`
  - `LaunchctlAction(StrEnum)`: `INSTALL`, `UNINSTALL`, `STATUS`, `ENABLE`, `DISABLE`, `TRIGGER`
  - `LaunchctlResult(action: LaunchctlAction, process: ProcessResult)` (frozen dataclass)
  - `LaunchAgentStatus(loaded: bool | None, process: ProcessResult)` (frozen dataclass)
  - `LaunchAgentBackend(store: LaunchAgentStore, runner: ProcessRunner, *, uid: int | None = None)`
    with `domain -> str` and the six operations above; every raw-label method validates
    its label before any runner call.
- `src/task_scheduler/platform/macos/launch_agent_store.py`: `validate_label(label: str) -> None`
  becomes the public shared guard (store methods now call it).
- Exports via `platform/macos/__init__.py`.
- `tests/fakes.py`: `FakeProcessRunner` gains an ordered `results=[...]` queue (popped
  per call; sticky last result afterwards) while keeping the single-`result` behavior.
- `tests/integration/test_launchctl.py`: `pytestmark = pytest.mark.integration`; skips
  unless `MACTASK_ALLOW_SYSTEM_TESTS=1`; unique label
  `io.github.mactaskscheduler.test.<uuid>`; real `LaunchAgentStore`/`SubprocessRunner`;
  unconditional `yield`/`finally` cleanup (best-effort `uninstall` + `store.remove`);
  only the test-owned plist is ever touched.
- Tooling: `integration` marker registered in `pyproject.toml`; `addopts` gains
  `-m 'not integration'` (plain `pytest`/`make test`/`make check` exclude it);
  `make integration` runs `pytest -m integration` (still skips without the env opt-in).

### Tests
- `tests/unit/platform/test_launchctl.py` (fakes only, no real launchctl, tmp_path roots):
  - exact argv + empty environment + no cwd for all six actions; injected uid.
  - default uid = `os.getuid()` in the domain string.
  - install writes through the store before bootstrap (plist exists, argv has derived path).
  - storage conflict (`FileExistsError`) stops before any runner call.
  - bootstrap failure retains the plist; bootout failure retains the plist;
    successful uninstall bootouts before removing.
  - success / non-zero / launch-failure results preserved on every action.
  - status maps exit 0 → True, non-zero → False, launch failure → None.
  - raw-label methods reject unsafe labels before any runner call.
- Integration (opt-in only): full lifecycle round-trip with a harmless `/bin/echo`
  job (install → status loaded → disable/enable → trigger → uninstall → status
  unloaded) and structured-failure uninstall of a never-installed label.
- Default-run safety: `pytest -m integration` without the env var skips; plain
  `pytest` never collects integration tests.

### Exit criteria
- `make check` green; coverage target 100% (≥90% floor) on new modules
- All logic files < 500 lines
- No unit test invokes `/bin/launchctl` or touches the real user LaunchAgents directory
- Plain `pytest` / `make test` / `make check` never run integration tests
- Version bump 0.0.6 → 0.0.7 with docs in the final commit; push every commit
