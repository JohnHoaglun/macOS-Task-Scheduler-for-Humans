# PLAN.md

## Current State
Crawl Increments 0–3 complete and pushed to `sched_dev_opencode` (commits through `95582a4`, version 0.0.3):
- **Increment 0:** project foundation (pyproject, Makefile, package structure, docs, tooling)
- **Increment 1:** Pydantic domain model (`JobDefinition`, `Command`, `Schedule`, `EnvironmentConfig`, `LoggingConfig`) + schema-versioned JSON persistence (`JsonJobRepository`)
- **Increment 2:** plist encoder (`PlistCodec.encode_dict/encode_bytes`) + golden fixtures
- **Increment 3:** plist reader (`parse_bytes/parse_path`, supported/partially_supported/invalid classification) + 14 fixtures + round-trip tests
- Verification at v0.0.3: 123 tests, 100% coverage, ruff + mypy strict clean

Current focus: **Crawl Increment 4 — Python Detection**.

## Blockers
None

## Strategy
Increment 4 adds Python-environment discovery in the macOS platform layer, with no GUI, CLI, `launchctl`, plist writes, task execution, or automatic shell-environment import.

### Pinned decisions (approved)
1. `PATH`-discovered `python3` **is** included as a candidate source in this increment.
2. A candidate qualifies only if it is an **absolute, regular, executable file** (`is_absolute()`, `is_file()`, `os.access(X_OK)`).
3. Environment differences use a **structured result**: `terminal_only`, `scheduled_only`, `different` (key → (terminal value, scheduled value)).

### API contract (pinned before implementation)
- New module: `src/task_scheduler/platform/macos/python_detection.py`; exports via `platform/macos/__init__.py`.
- Types (Pydantic, matching platform-model conventions):
  - `CandidateSource(StrEnum)`: `VENV = ".venv"`, `VENV_FALLBACK = "venv"`, `CURRENT = "current"`, `PATH = "path"`
  - `InterpreterCandidate(path: Path, source: CandidateSource)`
  - `PythonDetectionResult(script: Path, candidates: list[InterpreterCandidate], working_directory: Path | None)`
  - `EnvironmentDifference(terminal_only: dict[str, str], scheduled_only: dict[str, str], different: dict[str, tuple[str, str]])`
- Functions:
  - `detect_python(script, *, current_interpreter=None, path_lookup=None) -> PythonDetectionResult`
    - `current_interpreter` defaults to `Path(sys.executable)`; `path_lookup` defaults to `shutil.which` (injection keeps tests host-independent).
    - Candidate order: `<script parent>/.venv/bin/python`, `<script parent>/venv/bin/python`, current interpreter, `path_lookup("python3")`.
    - Nearby-venv candidates and the working-directory recommendation only apply when the script path is absolute and not a directory; current/PATH candidates still apply.
    - Deduplicate by exact path spelling; no symlink resolution/normalization.
  - `compare_environments(terminal: Mapping[str, str], scheduled: Mapping[str, str]) -> EnvironmentDifference`
    - Pure mapping comparison; never runs a shell, never logs values, never populates `EnvironmentConfig`.
- Working directory: recommendation only (`script.parent`); callers override; `JobDefinition` is never mutated.

### Tests
`tests/unit/platform/test_python_detection.py`, all under `tmp_path` (never the developer's real venvs/PATH):
- `.venv` present, `venv` present, both present (priority), none present
- missing interpreter, non-executable file rejected, symlink-to-executable accepted
- deduplication when the current interpreter equals a venv candidate
- relative script and directory script (no nearby candidates, no working directory; current/PATH still present)
- working-directory default and its absence for relative scripts
- `compare_environments`: terminal-only, scheduled-only, differing values, identical, mixed

### Exit criteria
- `make check` green (ruff, mypy strict, pytest) and coverage ≥ 90% on the new module (target 100%)
- All logic files < 500 lines
- Version bump 0.0.3 → 0.0.4 with docs in the final commit; push every commit
