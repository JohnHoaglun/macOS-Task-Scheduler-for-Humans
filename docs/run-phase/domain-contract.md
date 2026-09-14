# Run Phase — Pinned Domain Contract (Increment 24)

This document pins the scope-aware domain contract before any Run-phase
implementation. Increments 25–28 implement against this contract; changing
it requires a new approved plan, not an in-flight edit.

## JobScope

A persisted, validated execution scope on the managed job definition.

```python
# domain/scope.py (increment 25)
class JobScope(str, Enum):
    MY_USER = "my_user"
    SYSTEM_SERVICE = "system_service"
```

- `JobDefinition.scope: JobScope` defaults to `MY_USER`.
- Serializes as the string value (`"my_user"` / `"system_service"`).
- A job's scope is **immutable after first save** (pinned decision 9):
  the storage layer rejects a `scope` value different from the persisted
  value on update; the editor refuses to change it on an existing job.
  Creating a system job from a user job is a future explicit
  clone-into-new-job flow, never a scope edit.

## Schema v3

- `SUPPORTED_SCHEMA_VERSION = 3` (up from 2).
- v2→v3 read-time migration in the storage layer only (same pattern as
  v1→v2): a v2 record gains `scope: "my_user"` on read. No GUI or plist
  compatibility shims.
- All writes are v3.
- Unknown future versions (≥ 4) are rejected on read, unchanged behavior.
- v3 JSON shape (system example; a My User job is identical except for
  `scope` and the label prefix):

```json
{
  "schema_version": 3,
  "name": "Nightly System Backup",
  "label": "io.github.macos-task-scheduler.system.nightly-backup-a1b2c3d4",
  "enabled": true,
  "scope": "system_service",
  "command": {
    "type": "executable",
    "executable": "/usr/local/bin/backup-tool",
    "arguments": ["--nightly"]
  },
  "schedule": {
    "kind": "calendar",
    "times": ["02:30:00"],
    "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    "run_at_load": false
  },
  "environment": { "variables": {} },
  "working_directory": "/usr/local/share/backup",
  "logging": {
    "stdout_path": null,
    "stderr_path": null
  }
}
```

System-scope constraints on the definition (enforced by domain validators
in increment 25, revalidated by the helper in increments 26–27):

- `environment.variables` must be empty (pinned decision 6).
- `logging.stdout_path` / `logging.stderr_path` must be `null` — paths are
  helper-derived at deploy time (pinned decision 8).
- Command paths (interpreter/executable/script), arguments, and
  `working_directory` must satisfy the strict approved-location policy
  (pinned decision 5). Domain validation in increment 25 enforces
  absoluteness; the helper enforces ownership, symlink, and mode rules at
  deploy time.

## Label policy

| Scope | Prefix | Introduced |
|---|---|---|
| `my_user` | `io.github.macos-task-scheduler.user.` | Crawl (existing, unchanged) |
| `system_service` | `io.github.macos-task-scheduler.system.` | Run (increment 25) |

- Same slug policy as existing user labels (lowercase ASCII, non-
  alphanumeric runs → `-`, edge dashes trimmed, blank → `task`, plus the
  existing 8-hex suffix).
- **Scope/label consistency is a domain invariant:** a `system_service`
  job's label must start with the system prefix and vice versa. The
  validator rejects mismatches at construction and on every load.
- The native helper accepts **only** the `.system.` prefix for privileged
  operations (pinned decision 2). A user label arriving at the helper is a
  protocol violation, rejected with a stable error code.
- Existing labels are never rewritten; no relabeling migration exists.

## Helper result models (Python side, increment 26)

```python
# application/system_helper_models.py (increment 26)
class HelperOperation(str, Enum):
    INSTALL = "install"
    REINSTALL = "reinstall"
    UNINSTALL = "uninstall"
    STATUS = "status"
    ENABLE = "enable"
    DISABLE = "disable"

class HelperOutcome(str, Enum):
    OK = "ok"
    REJECTED = "rejected"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class HelperResult:
    operation: HelperOperation
    outcome: HelperOutcome
    code: str                 # stable machine-readable code (see xpc-protocol.md)
    message: str               # bounded human-readable detail
    data: Mapping[str, str]    # approved metadata only; bounded size
```

- `SystemHelperClient` is a narrow port in the application layer:
  `capabilities() -> HelperCapabilities`, and one method per
  `HelperOperation` taking the canonical `JobDefinition` and returning a
  `HelperResult`. No method accepts a shell string, arbitrary path, plist
  bytes, or raw `launchctl` arguments.
- `TaskCommandService` routes lifecycle operations by job scope:
  `.user.` → existing user adapter (unchanged), `.system.` → helper client.
  Cross-scope routing is a programming error, not a runtime branch.
- `HelperResult.data` is approved metadata only (deployed path, loaded
  state, retention artifact names). Never raw `launchctl` output, never
  secret-bearing content, never unbounded (pinned decision 9 of the
  architecture contract).

## Capability gating

- `HelperCapabilities` reports the protocol version and the supported
  operation set. The Python client treats an unavailable helper (not
  registered, wrong protocol version, macOS < 13) as
  `outcome = UNAVAILABLE` with the stable code `helper_unavailable`.
- Until increment 26, the GUI presents system scope as **authorable but
  unavailable**: the editor shows the control, system-scope jobs cannot be
  saved or installed, and the disclosure text states the helper is not
  available on this system.
