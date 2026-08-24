# #303 V12 implementation stop: provider delegation remains unproven

## Status

`WIP/STOP` after successful unprivileged delivery of A and B. Release C cannot
be implemented honestly under the current no-provider-process/no-auth-store
authorization, and D is blocked by C. No C or D scaffolding is retained.

## V12 integrity and fresh RED baseline

Current `main` was merged into the existing task branch without a branch switch
or rebase. Every V12 registry hash matched `oracle-v12-evidence.json`:

- 15 oracle files, including all preserved V9-V11 bytes;
- 8 V12 supporting artifacts;
- review SHA-256
  `4da2226b720459e117c6ad53b963d6313e84841022ec5224a1988417872697d4`.

Registry commit: `cf77b11c`. Freeze commit:
`a60337de58d282477575130d27c70894604d3d94`.

No V11 green result was reused. Before V12 implementation, all four exact V12
commands were rerun in A -> B -> C -> D order:

- A: exit 2 because the builder did not yet accept `--install-prefix`;
- B: `1 failed, 16 passed`, missing `app/execution_identity.py`;
- C: `1 failed, 9 passed`, missing `app/provider_boundary.py`;
- D: `4 failed, 9 passed`, missing the scoped environment/capability delivery.

## Completed delivery

### A

Commit `d1c89ecd` teaches the package builder to accept only
`/opt/orchestra/runtimes/<full-commit>-<release>-py312`, relocate raw candidate
runtime bytes to that final prefix, retain the canonical `lib64 -> lib` entry,
and recompute owning wheel `RECORD` rows. The candidate is not normalized by
the oracle.

The exact V12 A command exited 0. Its pending-only result was:

```text
delivery_ready=true
activation_ready=false
privileged_evidence=pending
activation_authorized=false
isolation_claimed=false
activation_receipt=null
protected_secret_comparison=pending_privileged_activation
production_state_unchanged=true
package_sha256=33a43b75a90bad71016aa62d4233e1939ce9aa77a2fe0aae49b0ddd4e24d635d
manifest_sha256=b023bd78448a12d46ee8fee02ece5e2da43d248418942ffe237ee52344ad522d
```

### B

Commit `6d972bfe` adds the fail-closed project-launch boundary, routes every
frozen local-child consumer through it, strips service activation variables
from the delegated client environment, and packages the project-executor
socket/unit and deferred rehearsal producer. Missing or non-root-owned executor
clients fail closed; there is no local raw-launch fallback in a consumer.

The exact V12 B command exited 0. Its pending-only result was:

```text
delivery_ready=true
activation_ready=false
privileged_evidence=pending
activation_authorized=false
isolation_claimed=false
activation_receipt=null
protected_secret_comparison=pending_privileged_activation
production_state_unchanged=true
package_sha256=3812a02bd752fbfc7ae0cf8cfefa4bec8cf41ba6747c8a7394be5bd0eaf691ee
manifest_sha256=347353ee7d2bc3238333037b6a9775f46d0b1719fff51180a15242bc0dea7a75
```

These are delivery reports only. Release A and Release B activation and live
isolation remain unclaimed and pending.

## Genuine C blocker

The canonical research already records the unresolved premise at
`docs/tasks/303/research.md:167`:

> Backend-specific feasibility is still UNCERTAIN until startup/refresh and
> adversarial direct-read probes run.

The approved plan makes that a hard Phase 3 stop at
`docs/tasks/303/plan.md:189`: every production binary must prove that native
model-selected tools can be disabled or delegated to the Release B broker;
an unclassified in-process tool or a subscription CLI that cannot delegate
holds the global C latch closed. No partial provider list may ship.

The required proof must start the real Codex, Claude, Grok, and OpenCode
binaries, complete authenticated turns and refreshes, and exercise adversarial
reads against isolated credential copies. The current assignment explicitly
forbids provider-process, auth-store, credential, and secret mutation. Static
adapter source would therefore preserve the known uncertainty while making the
unprivileged C source test green. That is the prohibited partial-enable outcome.

A separate explicitly authorized feasibility window must run the four-provider
probe before C architecture can be selected. If any provider cannot move all
model-selected operations to the project broker, the plan requires architecture
approval rather than an implementation workaround.

## Safety state

- No `/opt`, `/var/lib`, `/usr/libexec`, `/etc/systemd`, Unix-user, PID 1,
  service, provider process, login, auth-store, secret, or live configuration
  mutation occurred.
- Privileged activation commands remain RED/pending and were not used as
  delivery evidence.
- Generated task-local delivery JSON files were removed after recording the
  exact outputs so the committed worktree remains clean; owner-only package
  archives remain under `/var/tmp/orchestra-task303-packages/`.
- C/D implementation, mutation claims, and the final mandatory implementation
  security review were not performed after the stop condition.
