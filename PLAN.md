# PLAN.md

## Current State
Crawl Increments 0–5 complete and pushed to `sched_dev_opencode` (commits through `924c0da`, version 0.0.5):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model + schema-versioned JSON persistence
- **Increment 2:** plist encoder (`PlistCodec`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`) + fixtures + round-trip tests
- **Increment 4:** Python detection (`detect_python`, `compare_environments`) + tests
- **Increment 5:** Direct test runner (`SubprocessRunner`, `DirectTestService`, `evaluate_diagnostics`) + tests
- Verification at v0.0.5: 177 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 6 — LaunchAgent Storage** (IN PROGRESS).

## Blockers
None

## Strategy
Persist and list user LaunchAgent plists under `~/Library/LaunchAgents` only, through a
filesystem abstraction so tests never touch the real user directory. Spec Increment 6
(lines 1811–1831): implement `write plist`, `remove plist`, `discover plist`; target only
`~/Library/LaunchAgents`; use filesystem abstraction; do not modify `/Library`.

### Pinned decisions (approved)
1. **Write is create-only:** refuse an existing `<label>.plist` with `FileExistsError`;
   no overwrite and no backup in this increment.
2. **Discovery returns parsed records only** (`path` + `ParsedLaunchAgent`);
   ownership classification (Managed/Imported/External) is deferred to the
   discovery-service increment.
3. **Remove is idempotent:** `True` when a plist was removed, `False` when absent.
4. **Label safety at the store boundary:** domain labels only forbid whitespace, so the
   store rejects labels containing `/` (or `os.sep`) and the literals `.`/`..` with
   `ValueError` — no path traversal is possible from a stored label.
5. **Atomic exclusive write:** serialize via `PlistCodec`, write a sibling temporary file,
   then `os.link` onto the destination (atomic, and `EEXIST` if the destination already
   exists — no overwrite even under a race); temporary file is always cleaned up.
6. **All file IO flows through the filesystem abstraction** (`read_plist_bytes`,
   `list_plist_files`, `create_root`, `create_exclusive`, `remove_file`); discovery
   parses via `ParsedLaunchAgent.parse_bytes` on bytes read through the abstraction,
   so a `FakeFilesystem` can inject read failures.
7. **Discovery:** missing root → empty list (no creation); only direct-child `*.plist`
   regular files, sorted by filename; malformed/unsupported plists stay visible via
   `ParsedLaunchAgent.status` and never raise; no rewrite, import, classification, or
   `launchctl` action.
8. **Remove resolves only the derived managed destination** (`<root>/<label>.plist`);
   no arbitrary caller-supplied paths; no `launchctl` unload/disable until Increment 7.

### API contract (pinned before implementation)
- `src/task_scheduler/platform/macos/filesystem.py`:
  - `LaunchAgentFilesystem` (Protocol): `read_plist_bytes(path) -> bytes`,
    `list_plist_files(root) -> list[Path]` (sorted), `create_root(root) -> None`
    (`mkdir(parents=True, exist_ok=True)`), `create_exclusive(destination, payload) -> None`
    (raises `FileExistsError` if destination exists), `remove_file(path) -> bool`
    (`FileNotFoundError` → `False`).
  - `LocalFilesystem` — production implementation of that protocol.
- `src/task_scheduler/platform/macos/launch_agent_store.py`:
  - `default_launch_agents_root() -> Path` = `Path.home() / "Library" / "LaunchAgents"`.
  - `DiscoveredLaunchAgent(path: Path, parsed: ParsedLaunchAgent)` (frozen dataclass).
  - `LaunchAgentStore(root=None, filesystem=None, codec=None)` — defaults:
    `default_launch_agents_root()`, `LocalFilesystem`, `PlistCodec`.
  - `write(job: JobDefinition) -> Path` — validates label, `create_root`,
    `create_exclusive` with `codec.encode_bytes(job)`; returns destination.
  - `remove(label: str) -> bool` — validates label, removes derived destination.
  - `discover() -> list[DiscoveredLaunchAgent]` — as pinned above.
  - Re-exported via `platform/macos/__init__.py`.

### Tests
- `tests/fakes.py`: `FakeFilesystem` (in-memory; records calls; injectable
  `create_error`; simulates existing files / missing root) for failure injection.
- `tests/unit/platform/test_launch_agent_store.py` (real `tmp_path` roots; host-independent):
  - default root computation (no IO); custom root + injected fs/codec honored.
  - write: creates root, destination `<root>/<label>.plist`, bytes ==
    `PlistCodec().encode_bytes(job)`, parseable back to the same job.
  - write refused on existing destination (content byte-identical afterwards, no stray
    temp siblings); failing `create_exclusive` leaves no temp files and propagates.
  - label validation: `/` (or `os.sep`) and `.`/`..` rejected with `ValueError`
    before any filesystem effect.
  - remove: success `True` + file gone; missing file `False`; missing root `False`;
    label validation applies.
  - discover: missing root → `[]` (root not created); filename sorting; supported /
    invalid / partially-supported plists all reported without raising; non-plist files
    and subdirectories ignored; discovery never mutates file bytes.
  - fake-filesystem tests: store forwards correct paths/payloads and surfaces fs errors.
- No test invokes `launchctl`, touches the real `~/Library/LaunchAgents`, or reads
  `/Library`; `tmp_path` only (README Testing Safety).

### Exit criteria
- `make check` green; coverage target 100% (≥90% floor) on new modules
- All logic files < 500 lines
- No unit test touches real user LaunchAgent directories
- Version bump 0.0.5 → 0.0.6 with docs in the final commit; push every commit
