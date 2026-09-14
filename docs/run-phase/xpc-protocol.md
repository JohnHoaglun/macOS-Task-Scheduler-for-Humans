# Run Phase — XPC Protocol Specification (Increment 24)

This document pins the native-helper IPC contract. The Swift feasibility
spike (see `feasibility-spike.md`) implements this protocol; increment 26
implements the production helper against it.

## Transport

- **Mechanism:** `NSXPCConnection` to a helper executable registered and
  managed through `SMAppService.daemon` (macOS 13+, pinned decision 11).
- **Privilege model:** the main application (PySide6) is never root
  (pinned decision 11; spec §66). The helper is the only privileged
  process; it performs its work under the launchd system context
  established by SMAppService.
- **Session model:** one short-lived XPC session per operation. The client
  connects, performs capability discovery and one operation, and
  invalidates the connection. No long-lived privileged socket.

## Protocol surface (exactly this, nothing else)

```swift
protocol SchedulerHelperXPCProtocol {
    func capabilities(reply: @escaping (HelperCapabilities) -> Void)
    func install(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
    func reinstall(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
    func uninstall(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
    func status(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
    func enable(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
    func disable(request: HelperRequest, reply: @escaping (HelperResult) -> Void)
}
```

- Seven methods, total. This set is the narrow-boundary claim (spec §68).
  The protocol contains **no** generic command method and no method that
  accepts a shell string, arbitrary path, arbitrary plist bytes, or raw
  `launchctl` arguments (architecture contract 5).
- Compile-time property: a client linked against this protocol cannot
  invoke anything else.
- Runtime property: `NSXPCConnection` rejects selectors not declared in
  the exported interface. The spike proves this with a live rejection
  check (a client attempts an undeclared `executeCommand:` selector and
  the connection faults without executing anything).

## Message schemas

All messages are NSCoding objects with fixed fields. Unknown fields in a
request are a protocol violation (the helper rejects; the client never
sends them).

### `HelperRequest`

| Field | Type | Pinned rule |
|---|---|---|
| `protocolVersion` | `Int` | Must equal 1 (this specification). Helper rejects other values with `unsupported_protocol_version`. |
| `operation` | `String` | One of `install`, `reinstall`, `uninstall`, `status`, `enable`, `disable`. Must match the invoked method; mismatch → `operation_mismatch`. |
| `jobId` | `String` | Immutable UUID of the managed job. Correlates every request to the managed identity (architecture contract 6). |
| `label` | `String` | Managed label; must start with `io.github.macos-task-scheduler.system.` (pinned decision 2). |
| `definition` | JSON-compatible object | The canonical v3 `JobDefinition` serialization from the authoring catalog. The helper **revalidates** it (scope, label prefix, empty environment, null log paths, strict paths) and never trusts the sender (architecture contract 7). |
| `requestToken` | `String` | Fresh random token per request. The helper records recent tokens and rejects a reused one within the session window with `replay_rejected`. |
| `clientPid` | `Int` | Caller PID, included for audit metadata only — not an authorization input. |

### `HelperResult`

| Field | Type | Pinned rule |
|---|---|---|
| `operation` | `String` | Echo of the requested operation. |
| `outcome` | `String` | `ok`, `rejected`, `unauthorized`, or `unavailable`. |
| `code` | `String` | Stable machine-readable code (taxonomy below). |
| `message` | `String` | Bounded human-readable detail (≤ 512 chars, single-line, no raw OS output beyond a truncated bounded excerpt). |
| `data` | JSON object | Approved metadata only: `deployed_path`, `loaded`, `artifact_paths` (bounded list). Never raw `launchctl` output, never environment values, never log contents (architecture contract 9). |

### `HelperCapabilities`

| Field | Type | Pinned rule |
|---|---|---|
| `protocolVersion` | `Int` | 1. |
| `helperIdentifier` | `String` | `io.github.macos-task-scheduler.helper` (stable). |
| `operations` | array of `String` | Exactly the six pinned operations, in pinned order: `install`, `reinstall`, `uninstall`, `status`, `enable`, `disable`. |
| `macOSVersion` | `String` | Host OS version for diagnostics only. |
| `helperVersion` | `String` | Helper build version. |

## Capability discovery

1. The Python client calls `capabilities()` immediately after connecting
   and before any operation.
2. It verifies `protocolVersion == 1` and that `operations` equals the
   pinned set. Any mismatch → the client classifies the helper as
   `UNAVAILABLE` and surfaces the stable refusal text. No operation is
   attempted against a mismatched helper.
3. The helper performs the same check per request (`protocolVersion`
   field), so a stale or upgraded client cannot drive it blindly.

## Authorization

- Every mutating operation (`install`, `reinstall`, `uninstall`,
  `enable`, `disable`) requires the OS administrator-authorization flow
  before the helper performs privileged work (pinned decision 10).
  `status` is read-only and performs no privileged mutation.
- Authorization is enforced by the OS at the helper boundary (the
  privileged operation is gated), not by an app-level flag. A client
  cannot bypass it by calling a different method, because no un-gated
  privileged method exists in the protocol.
- The helper logs every authorized operation (jobId, label, operation,
  timestamp, outcome) to its own bounded audit log; the log contains no
  environment values or definition bodies.

## Stable error code taxonomy

| Code | Meaning | Trigger |
|---|---|---|
| `ok` | Operation completed. | — |
| `unsupported_protocol_version` | Request or helper protocol version not 1. | Any version mismatch. |
| `operation_mismatch` | `request.operation` differs from the invoked method. | Client bug. |
| `label_not_system` | Label missing or not under the `.system.` prefix. | Architecture contract 4. |
| `scope_not_system` | `definition.scope` is not `system_service`. | Architecture contract 4. |
| `definition_invalid` | Canonical definition fails helper-side revalidation (schema v3, empty environment, null log paths, strict path fields). | Architecture contract 7. |
| `path_policy_violation` | A command/working-directory path fails the approved-location policy (traversal, symlink, non-root-owned, group/world-writable, outside approved roots). | Pinned decision 5. |
| `conflicting_label` | A different job already owns the label at the deploy root. | Store safety. |
| `replay_rejected` | `requestToken` was already used in the session window. | Replay hygiene. |
| `unauthorized` | The OS authorization flow was declined or unavailable. | Pinned decision 10. |
| `helper_unavailable` | (Python side) Helper not registered, wrong protocol, or macOS < 13. | Capability gating. |
| `internal` | Unexpected helper failure. Detail is truncated and bounded. | Last resort. |

## Non-goals of the protocol (pinned)

- No `execute`/`run`/`trigger` operation (no Run Now — pinned decision 3).
- No arbitrary file read/write/copy operations.
- No environment-variable pass-through (pinned decision 6).
- No custom log-path selection (pinned decision 8).
- No plist import/interpretation operations — the helper consumes only
  the canonical v3 definition; external plists never cross this boundary
  (architecture contract 10).
- No secret/keychain operations (architecture contract 11).

## Python-side conformance (increment 26)

The Python client port (`SystemHelperClient`) mirrors this contract 1:1
and is exercised by `FakeSystemHelper` in `tests/fakes.py`. The fakes
record every request and assert the pinned invariants (label prefix,
protocol version, token freshness, no out-of-set operations) so the
contract is enforced in unit tests without a live helper.
