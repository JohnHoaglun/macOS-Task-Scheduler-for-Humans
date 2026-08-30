# Development — macOS Task Scheduler for Humans

## Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

This installs the package in editable mode plus all development
dependencies (pytest, pytest-cov, ruff, mypy).

## Makefile Targets

All targets use `.venv/bin/python`, so create the virtual environment
first.

| Command | Description |
|---|---|
| `make test` | Run unit tests |
| `make lint` | Run Ruff lint checks |
| `make format` | Format the codebase with Ruff |
| `make typecheck` | Run mypy on the source package |
| `make check` | Run lint, typecheck, and tests (the completion gate) |

## Running Tests with Coverage

```bash
pytest --cov=task_scheduler --cov-report=term-missing
```

The source package maintains 100% line coverage.

## GUI (PySide6) Test Setup

The GUI is tested with pytest-qt and runs fully headless:

* `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen`, so no display
  server is required on the test machine.
* `pyproject.toml` pins `qt_api = "pyside6"` for pytest-qt.
* Widget tests use the `qtbot` fixture together with the same
  `FakeTaskWorld`/`FakeProcessRunner` fakes and `tmp_path` roots as the CLI
  tests; no test may touch `~/Library/LaunchAgents` or invoke real
  `launchctl`.
* `make check` runs the GUI tests on every change; line coverage of the
  whole package stays at 100%.

## Current State

Crawl increments 0–9 establish:

- project/tooling foundation
- normalized job domain model with Pydantic validation
- schema-versioned JSON persistence (storage layer)
- LaunchAgent plist generation and parsing (macOS platform layer)
- LaunchAgent store (write, remove, discovery) in `~/Library/LaunchAgents`
- `launchctl` backend behind an injectable process runner
- application services: job service, log service, and the
  `TaskCommandService` facade
- `mactask` CLI (Typer): list, inspect, validate, generate, install,
  uninstall, enable, disable, status, run, test, logs
- read-only PySide6 GUI discovery browser (`mactask-gui`) over the shared
  `TaskCommandService` facade

Unit and GUI widget tests run against synthetic fakes and temporary
directories and never touch `~/Library/LaunchAgents` or invoke real
`launchctl`; GUI tests run headless via the offscreen Qt platform (see the
GUI test setup above). OS integration tests are gated behind
`MACTASK_ALLOW_SYSTEM_TESTS=1`.
