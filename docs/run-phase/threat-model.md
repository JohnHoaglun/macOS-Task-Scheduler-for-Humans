# Run Phase — Threat Model (Increment 24)

Security design for the Run phase, per spec §70. This is the governing
document for increments 24–29: every security control shipped must map to
a row in the attack-test matrix, and every row must name the increment
that verifies it.

## Scope and context

The Run phase adds system-level scheduled tasks (LaunchDaemons under
`/Library/LaunchDaemons`) managed through a native privileged helper,
while the PySide6 application and CLI stay unprivileged. The user
LaunchAgent path (Crawl + Walk) is unchanged and out of scope here.

## Assets

| Asset | Why it matters |
|---|---|
| Root execution surface | The helper runs as root; a compromise is a root compromise. |
| `/Library/LaunchDaemons` integrity | Arbitrary plist replacement = persistent root persistence. |
| Job definitions (canonical v3) | Root-executed command, paths, working directory. |
| Administrator authorization flow | The only human gate between intent and privileged effect. |
| System-service logs and artifacts | May contain sensitive output; must not become a read oracle. |
| Authoring catalog (per-user) | Source of intent; tampering could smuggle deployment attempts. |
| User data reachable by job commands | Indirectly protected by the strict path policy. |

## Threat actors

1. **Local malicious user** — has an account on the machine, wants
   persistence or privilege escalation. Can read the authoring catalog
   and invoke the app/CLI as themselves. Cannot read other users'
   protected files.
2. **Compromised application** — the Python app or its process is
   compromised at user privilege. Its entire reach into privileged
   effects must be the fixed helper protocol.
3. **Malicious job definition** — crafted JSON/plist content entering
   the catalog (import, hand-edit, or export/import transfer). Treated
   as untrusted input at every layer that consumes it.
4. **Network attacker** — out of scope for the first release: the
   application has no network surface, the helper listens only on a
   launchd-bound XPC endpoint, and nothing is exposed on a socket.
   Reassess if any future increment adds network access.

## Trust boundaries

```
┌────────────────────────── user (unprivileged) ─────────────────────────┐
│  PySide6 GUI / Typer CLI / authoring catalog / history database        │
│        │                                                              │
│        ▼  (B1) application → helper: NSXPC + OS authorization gate    │
│  ┌──────────────────────────────────────────────┐                    │
│  │  Native helper (root, launchd system context) │                   │
│  │    └ (B2) helper → filesystem/launchd:        │                   │
│  │        approved roots, regenerated plists,    │                   │
│  │        bounded metadata out                   │                   │
│  └──────────────────────────────────────────────┘                    │
└────────────────────────────────────────────────────────────────────────┘
```

- **B1 (app → helper):** authenticated XPC session, fixed seven-method
  protocol, per-request revalidation of the canonical definition,
  per-request OS authorization for mutations, replay-token hygiene.
  The sender (even a compromised app) can request only the six
  operations and only for definitions that pass helper-side validation.
- **B2 (helper → system):** helper writes only regenerated daemon plists
  under `/Library/LaunchDaemons` with the pinned label prefix, only to
  helper-derived log paths under the root-owned log root, and only
  `launchctl` operations on its own managed labels. Everything else is
  rejected before the privileged call.

## Invariants (the security claims)

- **I1 — No arbitrary root execution.** There is no code path, in the
  protocol or the helper, that executes a command chosen at runtime
  outside the validated canonical definition. No shell is ever invoked.
- **I2 — No arbitrary privileged file writes.** The helper creates or
  removes only files whose names it derives from the validated
  definition (label → plist path; jobId → log path). It never accepts a
  destination path from the client.
- **I3 — No cross-scope routing.** A `.system.` label never reaches the
  user adapter; a `.user.` label never reaches the helper. Scope and
  label prefix are a validated consistency pair at the domain layer and
  rechecked at B1.
- **I4 — Definition integrity at B1.** The helper regenerates the
  deployed plist from the revalidated canonical definition. A plist on
  disk at the deploy root is never copied, trusted, or partially merged.
- **I5 — Authorization cannot be bypassed.** Privileged mutation happens
  only behind the OS authorization flow; no un-gated privileged method
  exists in the protocol.
- **I6 — No secret exposure.** System jobs carry no environment
  variables; helper responses carry bounded metadata only; audit and
  error paths truncate and never include definition bodies or
  environment values.
- **I7 — No unattended privilege.** Every mutation is a deliberate,
  user-initiated, OS-authorized action; there is no auto-elevation, no
  background privileged work, and no network reach.

## Attack-test matrix

Each row: threat → mitigation → verification. "Verified in" names the
increment whose tests prove the row; `spike` = the increment-24
feasibility spike.

| # | Threat | Mitigation (pinned) | Verification |
|---|---|---|---|
| T1 | Client (or compromised app) invokes a generic command / arbitrary method on the helper | Protocol surface is exactly seven methods (xpc-protocol.md); NSXPC rejects undeclared selectors | spike: live undeclared-selector rejection; inc 26: fake-client + protocol-surface unit tests |
| T2 | Request replays a previously authorized privileged operation | Fresh `requestToken` per request; helper rejects reuse with `replay_rejected` | inc 26: replay unit tests against helper-side token store |
| T3 | Stale or wrong-protocol client drives the helper | `protocolVersion` pinned 1; capability discovery + per-request check; mismatch → `unsupported_protocol_version` / `helper_unavailable` | inc 26: version-mismatch tests both directions |
| T4 | Cross-scope routing: system label routed to user adapter (or vice versa) | Scope/label consistency invariant (domain validator); service routes by scope; label prefix recheck at B1 | inc 25: domain/validator tests; inc 27: routing tests (no crossing) |
| T5 | User label (`.user.`) smuggled into the helper | Helper accepts only the `.system.` prefix; `label_not_system` rejection | inc 26: rejection tests; inc 27: composition gate |
| T6 | Definition smuggles system scope with a user label (or mixed scope) | `scope_not_system` + consistency validator at domain and B1 | inc 25 + inc 26 rejection tests |
| T7 | Definition carries environment variables (secrets or injection) | System scope forbids non-empty `environment.variables` (domain + B1 revalidation) | inc 25: domain validator tests; inc 26: `definition_invalid` tests |
| T8 | Definition carries custom log paths (privileged write/read oracle) | System scope forbids non-null log paths; helper derives log paths from `jobId` only | inc 25: validator tests; inc 27: path-derivation tests |
| T9 | Symlink/path attack: command path or working directory is a symlink into user space | Strict approved-location policy: absolute, non-symlink, root-owned, non-group/world-writable, approved roots; `path_policy_violation` | inc 27: opt-in symlink/traversal integration tests (tmp roots) |
| T10 | Label injection/escape: crafted label writes outside the deploy root | Label validation (existing `validate_label` rules) + helper derives the path from the label under the fixed root + create-exclusive writes | inc 27: label-escape tests |
| T11 | Arbitrary plist replacement: attacker swaps a daemon plist on disk | Helper never copies/merges on-disk plists; reinstall regenerates from the revalidated definition; ownership/mode check before replace (I4) | inc 27: tampered-plist replacement tests |
| T12 | Catalog tampering to trigger deployment of a malicious definition | Helper revalidates the full canonical definition at B1; catalog is never read by the helper; deployment requires per-operation OS authorization (I4, I5) | inc 26: canonical-payload validation tests; inc 27: authorization tests |
| T13 | External plist import becomes privileged deployment authority | Imports remain catalog-only and My-User-only; no import operation crosses B1 (architecture contract 10) | inc 25: import regression (scope forced `my_user`) |
| T14 | Direct Test / Test Draft used as privileged execution | Test/Test Draft disabled for system scope; no test operation exists in the protocol (pinned decision 7) | inc 28: GUI/CLI gating tests |
| T15 | Helper used as a read oracle for protected files | No read operation in the protocol; responses carry bounded approved metadata only (I6) | spike: surface check; inc 26: response-shape unit tests |
| T16 | Log/artifact disclosure | Helper-derived root-owned log paths; bounded output reads; no raw output in `HelperResult.data` | inc 27: log-path and bounded-read tests |
| T17 | Unattended or background privilege gain | No auto-elevation, no background privileged work, no network surface (I7) | design review at each increment closeout |
| T18 | Misleading state ("installed", "running") for system jobs | Scope-aware truthful wording; `status` returns helper-observed state only | inc 28: wording/gating tests |

## Residual risks and follow-ups

- **SMAppService registration requirements** (bundle identity, signing,
  entitlements) are environment-dependent; the feasibility spike
  records observed behavior, and increment 26 implements against the
  production bundle produced in increment 29.
- **Keychain/secrets:** explicitly deferred (architecture contract 11,
  spec §71). Until the separate design lands, system jobs simply have no
  environment variables, which removes the primary secret channel.
- **Multi-user administration:** the authoring catalog remains
  per-user (pinned decision 4). A shared administrator catalog is a
  future increment, not a current surface.
- **Helper update/rollback:** covered by the update strategy decision in
  increment 29; the helper version is reported in capabilities so the
  client can refuse a mismatched helper.

## Review status

Approved as part of the Run-phase plan (2026-09-09). Increment 24
deliverables (this document set + feasibility spike) do not enable any
system-deployment functionality; they exist so increments 25–29 can be
built against pinned, testable security claims.
