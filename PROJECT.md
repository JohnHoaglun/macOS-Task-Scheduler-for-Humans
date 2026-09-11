# macOS Task Scheduler for Humans

## Purpose
A human-friendly macOS task scheduler built on top of Apple's `launchd`. The goal is to make scheduled jobs easier to create, understand, test, and troubleshoot without requiring users to manually write plist files or memorize `launchctl` commands.

## Architecture
- **Language:** Python 3.12+
- **GUI:** PySide6 / Qt Widgets
- **CLI:** Typer
- **Testing:** pytest + pytest-cov
- **Linting:** Ruff + mypy
- **Domain Model:** Pydantic 2.x
- **plist handling:** Python standard library `plistlib`
- **Platform:** macOS (user LaunchAgents; system LaunchDaemons planned for Run phase on macOS 13+)
- **Packaging:** PySide6 deployment tooling → macOS `.app` bundle

### Architectural Layers
```
GUI (PySide6)          CLI (Typer)
        └──────── Application Services
                       Domain (Job/Schedule/Command/Environment)
              Platform Adapters (macOS plist/launchctl/filesystem)
                       launchd
```

## Status
**Version:** 0.0.26
**Phase:** Run (planned). In progress (approved 2026-09-10, target v0.0.27): task-table header fix (`headerData`) and a narrow, safety-gated direct in-place edit of external user LaunchAgents (supported plists only, label read-only, remains External, two-step confirmation, backup retained on success) — a scoped amendment to the read-only-external policy, documented in the README/architecture docs. Walk complete: all 23 increments shipped (Crawl 0–13; Walk 14–23 at v0.0.23). Run phase plan approved 2026-09-09: increments 24–29 covering Run architecture/threat model/helper contract (24), scope-aware managed-job model (25), native Swift XPC helper + authenticated IPC (26), system LaunchDaemon lifecycle (27), system-service UX/CLI (28), and release security/distribution (29). Next increment: 24. The main GUI starts at an adaptive `1280x900` size bounded to usable display space, and Diagnostics, Persisted logs, and Python interpreter details begin collapsed so Overview is readable (v0.0.26). Increments 14 (schema-v2 schedule variants + v1→v2 migration), 15 (next-run preview), 16 (multi-time calendar authoring), 17 (interval and login triggers), 18 (Python environment detectors), and 19 (expanded diagnostics: typed diagnostic models, report engine with pinned group order, platform probes for protected paths and Mach-O architecture, GUI/CLI diagnostics surfacing) are complete (v0.0.19). Increment 20 (application-observed execution history: append-only sqlite3 history, service-boundary event recording, `mactask history`, GUI history panel) is complete (v0.0.20); increment 21 (external plist import) is complete (v0.0.21); increment 22 (Walk UX + catalog-only managed-JSON transfer: filterable/badged/empty-state task list, GUI/CLI `export-json`/`import-json` with identity-preserving create-only transfer and v1→v2 migration, and a platform-isolated Finder reveal) is complete (v0.0.22). Increment 23 (the four Python ecosystem detectors deferred from increment 18: pyenv, Conda, Pipenv, and Homebrew Python) is complete (v0.0.23).

## Repository
Source of truth: https://github.com/JohnHoaglun/macOS-Task-Scheduler-for-Humans/tree/sched_dev_opencode
Branch: `sched_dev_opencode`

## Credentials
N/A - no credentials required
