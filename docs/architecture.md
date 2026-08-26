# Architecture — macOS Task Scheduler for Humans

## Dependency Direction

The project follows a strict dependency flow:

```
Presentation
    ↓
Application
    ↓
Domain
    ↓
Platform abstractions
```

Each layer may depend on the layer below it, but never on layers above it. No layer depends on a sibling or a layer it sits above.

## Architectural Layers

| Layer | Purpose | Status |
|---|---|---|
| **GUI (PySide6)** | Native macOS desktop interface | Planned for future |
| **CLI (Typer)** | Terminal task management interface | Planned for future |
| **Application Services** | Use cases, orchestration, coordination | Planned for future |
| **Domain** | Core model: Job, Schedule, Command, Environment | Core — this cycle |
| **Platform Adapters** | macOS plist, launchctl, filesystem operations | Platform-specific — this cycle |
| **launchd** | Underlying macOS scheduler (external) | Not part of the codebase |

## Domain Model

The domain is the anchor of the entire system. It defines the fundamental concepts:

- **Job** — a schedulable unit of work with an associated command and environment.
- **Schedule** — recurrence rules that determine when a job runs.
- **Command** — the executable, its arguments, working directory, and environment variables.
- **Environment** — key-value pairs injected into the job's process context.

These domain types carry no platform-specific knowledge. They exist to represent the user's intent: "run this command, with this environment, on this schedule."

## Persistence Strategy

**The domain model is the application's source of truth. Plist files are macOS deployment representations.**

Managed jobs are persisted as human-readable, schema-versioned JSON files
(see the `storage/` layer). On macOS, the same domain model is translated
to the launchd LaunchAgent plist format by the platform layer
(`platform/macos/`). The domain never knows about plist keys, JSON layout,
or XML structure.

A future cycle adds installation of plists into `~/Library/LaunchAgents`
and `launchctl` interaction; this cycle performs no such operations.

This cycle includes the Domain, Storage (persistence layer), and macOS plist Platform components. GUI, CLI, and Application Services layers will be added in subsequent cycles once the foundation is stable.

## No launchd Operations This Cycle

This cycle establishes the model, persistence, and platform adapter interfaces. No actual `launchctl load/unload` or plist file system writes are performed at runtime. The storage layer validates and serializes; it does not invoke the scheduler.
