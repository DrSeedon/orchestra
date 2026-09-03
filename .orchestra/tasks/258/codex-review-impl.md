# Codex implementation review

Review was run by the delegated Luna implementer against the production diff in its worktree.
The parent recovered the complete artifact from `/tmp/codex-review-258-impl.md`, verified the
quoted executable line against the merged file, and did not spend a third round because no code
changed after Round 2.

## Attempt log

- Preflight 1: tool refused the request before starting Codex (`context must include
  caller-supplied task instructions and PROJECT CONTEXT`); no round.
- Round 1: completed with two P2 findings.
- Resume preflight: same tool-side context refusal; no round.
- Round 2: completed after the runtime-isolation fix; `APPROVED` with executable evidence.

## Round 1

The pidfd signaling boundary is substantially safer, but normal configurations can prevent valid managed processes from being terminated, and the orphan identity map still admits incomplete identities.

Full review comments:

- [P2] Normalize only the candidate runtime executable — /home/kesha/orchestra/worktrees/home-kesha-orchestra/impl-258-pidfd/app/backend_jsonrpc.py:370-373
  When either configured runtime executable is absent or malformed, constructing `expected` raises and `_runtime_argv` rejects every candidate, including a valid process for the other runtime. For example, a Codex teardown fails whenever the default Grok path is missing, so the verified orphan remains alive; resolve only the executable(s) in `allowed`, independently per candidate.

- [P2] Exclude incomplete identities from orphan_pids — /home/kesha/orchestra/worktrees/home-kesha-orchestra/impl-258-pidfd/app/manager.py:2318-2320
  Rows with a valid `cli_pid` but missing or zero `cli_started_at` are currently returned as `OrphanProcessIdentity(..., started_at=0)`, violating the requirement that this map contain only coherent identity pairs. The sweep then treats the entry as known, closes its descriptor, and invokes a termination path that must refuse it; filter these rows out when building the map.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round 2 (2026-08-13T08:45:54Z)

Re-review status:

- FIXED — runtime configuration isolation. Evidence: `except (OSError, ValueError, TypeError): continue` independently skips an unavailable configured runtime.
- FIXED — zero `cli_started_at` handling is intentional per clarified frozen plan; it reaches the shared PID-specific ERROR refusal.
- NEW BUG — none.

Verdict: **APPROVED**. No blockers remain.
