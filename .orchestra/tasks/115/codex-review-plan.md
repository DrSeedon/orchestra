## Summary

🧯 “Durable” is doing suspiciously heavy lifting before the durable boundaries are actually specified. The plan respects the forbidden-file boundary, reuses #93’s `repo_mutation_lock`/`MergeOutcome`, preserves exact conflict paths, keeps conflict resolution on the worker branch, and defines a strong no-empty-error contract.

However, five safety gaps can still duplicate mutations, merge the wrong session, or expose quarantined worker refs. I also retain the architecture dissent against calling the HTTP route as an internal service: it is callable, as existing tests demonstrate, but cannot enforce the operation’s pinned identity.

No tests were run; this was a plan-only review.

## Findings

### blocking: Deduplicate after the original operation becomes terminal

[docs/tasks/115/plan.md:61](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:61)

If the MCP process dies after POST, the caller loses its generated key. The plan only maps a new key to a canonical **active** operation. If the original operation completes before the next call—especially as `PARTIAL + REACHED`—there is no active row, so the new key can start another merge. Add server-side lookup/refusal for matching terminal or unknown operations using the pinned session/request/worker fingerprint, with an AC covering “response lost → MCP dies → operation becomes terminal → retry with new key”.

---

### blocking: Pin the session identity across the internal route adapter

[docs/tasks/115/plan.md:81](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:81)

The current handler resolves the worker by `(name, scope)` before taking its session lock in [app/routes/sessions.py:675](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/app/routes/sessions.py:675). Between operation acceptance and runner execution, that name can be removed and recreated, causing the durable operation to merge a different session than its stored `session_id/branch/head`. A pre-call check still has a TOCTOU race, while taking the lock externally would nest the handler’s non-reentrant lock. #93 must expose an internal entry point accepting the pinned session identity/fingerprint, or #115 must revise its no-route-change boundary.

---

### blocking: Make destructive reconcile depend on #93-T4

[docs/tasks/115/plan.md:274](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:274)

T2 explicitly claims no dependency on #93-T4, although the plan itself says T4 supplies the common delivery gate after reconcile. If the process dies after quarantine/ref mutation, locks disappear; without T4, non-HTTP delivery paths can resume the worker on the reset/quarantined branch and create newer work before recovery completes. That reopens the exact worker-work preservation risk T2 is intended to close. T2 must be blocked by #93-T4, with an AC covering restart followed by every fresh-delivery path.

---

### blocking: Define authoritative scope provenance for manual commits

[docs/tasks/115/plan.md:151](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:151)

Ancestry and commit contents prove repository membership, not the caller’s Orchestra scope or task project—research already establishes that scopes can operate on other repositories. For recovery by raw target SHA, choosing the wrong scope can pass the timestamp/ref checks and link the commit to a same-number task in another project. Name the authoritative provenance source and exact validation function; historical entries without operation records or retained caller evidence must fail closed rather than accept a supplied scope.

---

### blocking: Cover the existing-old-MCP deployment window

[docs/tasks/115/plan.md:229](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:229)

The AC only covers a new MCP against an old server. Already-running MCP subprocesses retain the old implementation and continue calling the legacy mutating endpoint while the server remains unrestarted; the plan intentionally leaves that endpoint operational. Therefore the rolling deployment does not globally fail closed. Add an explicit rollout gate that prevents legacy internal-token merge calls during version skew, or prove and test that all MCP subprocesses are atomically replaced before the operation endpoint becomes active.

---

### suggestion: Specify the Git/SQLite crash barrier for ref reset

[docs/tasks/115/plan.md:259](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:259)

The restart AC only covers failure after a persisted stage. A process can die after the worker reset succeeds but before its stage is stored; the next finalize sees neither the old expected head nor durable completion and cannot converge as promised. Add barriers immediately before and after backup creation, ref movement, and progress persistence, plus read-after-crash rules that recognize the intended target head without issuing another reset. The verified backup must remain the recovery authority for every ambiguous state.

---

### suggestion: Make operation arbitration an explicit SQLite CAS contract

[docs/tasks/115/plan.md:67](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:67)

The plan states uniqueness and transitions but does not pin the enforcing schema or claim functions. Specify `operation_id` uniqueness, a partial unique index for one `PENDING/RUNNING` row per session, atomic insert-or-read behavior, and `UPDATE … WHERE state='PENDING'` ownership claiming with `rowcount == 1`. Add a test using separate SQLite connections/process owners; twenty coroutines against one in-process service do not validate durable arbitration.

---

### suggestion: Add an executable recovery generator and scope-level RAG batch

[docs/tasks/115/plan.md:276](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:276)

T3 lists only generated JSON/Markdown outputs, although its AC requires deterministic regeneration and later application. The 32 SHA inputs are not enumerated in `research.md`, and existing `backfill_scope()` serializes work but does not coalesce repeated calls by scope. Name a generator/input artifact and a batch prepare/finalize function whose AC proves one RAG call per scope across all entries; otherwise the claimed reproducibility and deduplicated five-scope recovery depend on undocumented manual steps.

## Verdict

The core direction is sound, but the lost-key terminal case, unpinned route adapter, missing delivery-gate dependency, unproven scope identity, and incomplete rolling-deploy story violate the preservation-first contract. Right now the safety case is like a backup ref without the ref name: comforting until the exact moment it matters.

REQUEST_CHANGES

## Round (2026-08-01T08:57:24Z)

## Summary

🧷 The plan now has actual safety rails instead of motivational signage. Five prior findings are fully resolved; three retain narrow gaps.

| Prior finding | Status |
|---|---|
| Lost-key dedupe | Partially resolved; unsafe resolution escape hatch remains |
| Pinned internal adapter | Resolved |
| #93-T4 dependency | Resolved |
| Historical provenance | Resolved |
| Rolling deployment | Resolved |
| Ref-reset crash recovery | Mostly resolved; branch identity missing |
| SQLite arbitration | Resolved; retry liveness regression introduced |
| Recovery generator/RAG batch | Mostly resolved; evidence must be frozen earlier |

The #116 envelope integration is consistent, all 32 SHAs are present, conflict instructions remain worker-only, and dependencies are acyclic. No tests were run because this is plan-only.

## Findings

### blocking: Define who may resolve `PARTIAL/UNKNOWN` and with what proof

[docs/tasks/115/plan.md:95](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:95)

An “explicit non-mutating resolution record” removes the session gate, but the plan defines neither its evidence requirements nor its state transition. Clearing an `UNKNOWN` whose commit actually landed would permit another merge and defeat the lost-key protection. Only evidence-backed reconcile should set `resolved_at`, or the plan must define typed resolution outcomes proving `NOT_REACHED` or finalized `REACHED`, with CAS and audit ACs.

---

### blocking: Include symbolic branch identity in crash recovery

[docs/tasks/115/plan.md:256](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:256)

The normal CAS requires exact branch and HEAD, but recovery from `RESETTING` checks only the OID. If the worktree is switched to another clean branch pointing at `intended_target`, recovery can incorrectly record `RESET_DONE` and persist lifecycle state for the wrong branch. Require `current_branch == expected_worker_branch` alongside every HEAD comparison; any detached or different symbolic HEAD must remain quarantined `UNKNOWN`.

---

### suggestion: Do not permanently dedupe retryable pre-commit failures

[docs/tasks/115/plan.md:90](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:90)

The permanent unique fingerprint and terminal-equivalence rule cache failures whose corrective change does not alter worker branch/head/task: `BUSY` becoming idle, target dirtiness being cleaned, or the target branch advancing. A new key would keep returning the stale failure indefinitely. Restrict terminal dedupe to outcomes that may have mutated state, or include the relevant target/status snapshot and allow a new operation after a verified `FAILED + NOT_REACHED`.

---

### suggestion: Freeze retained-log evidence before implementing T1/T2

[docs/tasks/115/plan.md:282](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:282)

The plan pins the SHAs now but postpones collecting source log IDs until T3, after T1 and T2. Because retained logs are not immutable, the authoritative evidence may disappear before the generator runs, at which point its correct behavior is to reject entries. Populate and track `recovery-input.json` before waiting on implementation dependencies, then let T3 consume it read-only.

## Verdict

The major architecture is now coherent, but an undefined `UNKNOWN` release path and incomplete branch CAS can still permit duplicate mutation or corrupt lifecycle/ref identity. A quarantine with an undocumented release lever is still just a door marked “please don’t.”

REQUEST_CHANGES

## Round (2026-08-01T09:04:26Z)

## Summary

🧾 Three rounds later, the safety model finally has fewer escape hatches than a submarine. All Round 2 blocking findings are resolved:

- `PARTIAL/UNKNOWN` resolution is evidence-backed, typed, audited, and CAS-protected.
- Reset recovery verifies symbolic branch and OID.
- Retryable `NOT_REACHED` outcomes are no longer permanently deduplicated.
- T0 freezes historical evidence before log pruning.
- Earlier concerns around pinned execution, #93-T4, provenance, rolling deployment, SQLite arbitration, and batch RAG recovery remain resolved.
- The route-as-service architecture dissent is preserved: that approach remains unsafe, and the plan now correctly avoids it through `execute_merge_session(...)`.

The forbidden-file boundary is intact. Dependencies are acyclic: T0 is independent; `#93-T2 → #116-T7 → T1 → T2 → T3`, with T4 branching from T1. No blocking safety gap remains.

## Findings

### suggestion: Define the terminal semantics of `rag.status=NOT_READY`

[docs/tasks/115/plan.md:428](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-merge/docs/tasks/115/plan.md:428)

The mapping records `NOT_READY` but does not specify whether a commit-reaching operation becomes `PARTIAL`, whether it holds the session gate, or which retry/finalize action follows. Pin that mapping in the AC—or cite a #116 guarantee of durable later execution—so an implementation cannot report `SUCCEEDED` while no RAG job was accepted. This is a consistency/liveness issue, not a worker-work safety blocker.

## Verdict

No crash, corruption, security, duplicate-mutation, or worker-work-loss path remains in the plan. The remaining RAG status ambiguity can be settled during implementation without reopening the merge safety architecture—the submarine may still need a label maker, but it no longer leaks.

APPROVE
