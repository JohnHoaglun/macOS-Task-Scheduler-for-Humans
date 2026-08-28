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
| **GUI (PySide6)** | Native macOS desktop interface | Planned (next: Increment 9) |
| **CLI (Typer)** | Terminal task management interface (`mactask`) | Implemented (Increment 8) |
| **Application Services** | Use cases, orchestration, coordination (`TaskCommandService` facade, `JobService`, `LogService`) | Implemented (Increments 7–8) |
| **Domain** | Core model: Job, Schedule, Command, Environment | Implemented |
| **Platform Adapters** | macOS plist codec, LaunchAgent store, launchctl backend, log reader | Implemented |
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

The application services layer (Increments 7–8) adds the `TaskCommandService`
facade, which both the `mactask` CLI and the future GUI call. It coordinates
`JobService` (catalog resolution and conflict checks), `LogService`, the
`LaunchAgentStore` (plist writes/removals and discovery in
`~/Library/LaunchAgents`), and the `LaunchAgentBackend` (all `launchctl`
invocations).

## Platform Boundaries

All `launchctl` argument vectors and LaunchAgent plist writes stay inside
`platform/macos/`. Application and presentation layers never build
`launchctl` commands or touch plist files directly. Process execution is
injected (a `ProcessRunner` protocol), so the entire stack is unit-testable
without invoking real `launchctl` or touching the live filesystem.
