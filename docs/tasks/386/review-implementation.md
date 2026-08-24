<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The implementation has one blocking project-isolation flaw and two meaningful correctness issues. The pinned oracle, strict gate handling, migrations, replay snapshot, target-relative selection, and #380 combined-tree compatibility otherwise appear coherent.

Evidence read from the diff: `raise ValueError("cannot derive target-relative merge paths")`

## Findings

- blocking: `app/routes/tm.py:247` — Project isolation is enforced only when `command_update is not None`. An oracle-only update such as `acceptance_manifest=[...]` or `acceptance_required=False`, with no command change, takes the `else` branch at line 257 and resolves the caller-supplied `project`/`scope` without comparing it to `caller_scope`. Thus an orchestrator scoped to project A can mutate the authoritative oracle metadata of a task in project B. Apply the caller-project restriction whenever `oracle_update` is true as well, and add a manifest-only/required-only cross-project regression test.

- suggestion: `app/tm.py:397` — Changing only `acceptance_command` on a task that already has an authoritative oracle follows the legacy branch at line 444. The command changes without incrementing the oracle revision or recording `updated_by`. The resulting admission combines a new command with stale revision/audit metadata. Treat command changes as oracle contract updates whenever `acceptance_oracle_json` represents an authoritative oracle; retain the legacy path only for command-only legacy tasks.

- suggestion: `app/workspace.py:1233` — A target mismatch sets `result`, but execution continues through target-worktree discovery and may run `git checkout target_branch` at line 1265 when the target has no separate worktree. Although the merge itself remains guarded, this violates the intended “no mutation on mismatch” behavior and can leave the primary checkout on another branch. Exit or guard the entire target-worktree/checkout block once the early target comparison fails.

## Verdict

NEEDS WORK — one blocking security/isolation defect.

## Author response after Round 1

- ACK blocking project isolation: `tm_update_task` now applies caller-project restriction whenever
  either the command or oracle metadata changes. A real manifest-only cross-project route probe
  returned 400 with no task API call.
- ACK command-only revision: `tm.update_task` now treats a command change as an oracle contract
  update whenever the stored revision is authoritative; a real probe observed revision 1→2 and the
  verified second actor.
- ACK early target mutation: an early target mismatch now returns immediately from inside the repo
  lock with typed recheck evidence; target worktree discovery/checkout is unreachable.
- Frozen test remains byte-identical to `b1af1b07`. Fix commit: `82b0d257`.
- Post-fix evidence: T386 32 passed; task/MCP/routes 160 passed; workspace 115 passed;
  `manifest_only_cross_project=blocked command_only_revision=2`.
- New `git merge-tree --write-tree main HEAD` → `b11e669ade16668f43a6b9a59fb3ceb6788f9923`;
  combined T386 + #380 receipts → `54 passed in 113.56s`.

## Round (2026-08-24T04:05:33Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All three prior findings are fixed. No new blocking bugs or meaningful suggestions found in the reviewed seams.

Evidence quote: `raise ValueError("acceptance_actor must come from a verified orchestrator")`

## Findings

- FIXED — project isolation: `app/routes/tm.py:242` now applies caller-project enforcement when either `command_update` or `oracle_update` is present.
- FIXED — authoritative revision audit: `app/tm.py:406-459` recognizes an existing versioned oracle and routes command-only changes through oracle reconstruction with `revision=previous_revision + 1` and verified actor metadata. Legacy command-only tasks retain the legacy path.
- FIXED — target mismatch mutation: `app/workspace.py:1233-1250` returns immediately under the repository lock before worktree-owner discovery or checkout.
- No new findings.

## Verdict

APPROVED.
