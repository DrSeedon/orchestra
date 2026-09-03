## Summary

Apparently a deterministic filename was expected to make `/tmp` transactional. 🧨 The diff has three blocking data-loss/deadlock races and one rollback-contract issue. I did not rerun tests, as requested; the reported 186 targeted and 1288 full-suite passes do not exercise these failure modes.

## Findings

### blocking: Store the flock in a protected, persistent location

**File:** `app/workspace.py:138-145`

A stable pathname does not guarantee a stable lock inode. The predictable `/tmp` entry can be pre-created as a FIFO or symlink, causing `open(..., "a")` to block or fail, and it can be unlinked by same-user/root cleanup while held. A subsequent process then creates and locks a different inode, allowing create/merge/switch/remove to mutate one repository concurrently. Put the lock inside the resolved Git common directory, or another protected directory whose entries cannot be replaced during operation.

### blocking: Do not infer branch ownership from every nonzero `show-ref`

**File:** `app/workspace.py:402`

`branch_created = ref_check.returncode != 0` treats both “missing” and operational errors as proof that this call owns the branch. If `show-ref` returns 128 transiently—or another Git process creates the branch after this check—`worktree add -b` can fail and lines 424–428 then execute `git branch -D`, deleting a pre-existing branch. Only return code 1 means absent, and cleanup must delete through an expected-value/CAS check proving this invocation created the ref.

### blocking: Restore target refs with compare-and-swap semantics

**File:** `app/workspace.py:1280-1287`

Rollback unconditionally rewinds an existing target to `target_head` or deletes a target believed to be new. The repository flock is advisory and is not honored by worker or human Git commands: a concurrent ref advance is therefore overwritten, while a branch created after the initial absence check is deleted. Use `git update-ref` with an expected current object ID and report `rollback_failed` when ownership cannot be proven.

### suggestion: Preserve the exact previous lifecycle on rollback

**File:** `app/routes/sessions.py:835`

`old_lifecycle["base_branch"]` substitutes `from_ref` when the stored value is empty, so a busy target or any other successfully rolled-back failure still changes durable session state. Preserve the raw prior value for restoration and use the resolved `from_ref` only for the Git operation.

## Verdict

**❌ Incorrect — reject T1 until the blocking findings are addressed.**

Continuous lock coverage and write-ahead quarantine are structurally improved, task updates are success-only, and failure payloads remain consumable by the current MCP parser. However, the lock inode and ref-cleanup logic still permit deadlock or branch loss under adversarial concurrency—rather like installing one sturdy door while leaving three copies of the key in `/tmp`.

## Round (2026-08-01T08:21:46Z)

## Summary

Three prior findings are fixed: the lock location/security, strict `show-ref` handling, and exact lifecycle restoration. OID-based CAS prevents ref rewinds, but it still misses checkout-ownership races. Four blocking issues remain; claimed 191 tests were not rerun.

## Findings

### blocking: Do not delete refs that may be checked out elsewhere

**File:** `app/workspace.py:455-457`  
**Also:** `app/workspace.py:496-499`, `app/workspace.py:1363-1369`

CAS proves only that the OID is unchanged. Another process can check out the created branch after the earlier busy check without changing its OID; cleanup then deletes the branch beneath that worktree. In the switch path this can return a normal rollback, so the route removes quarantine despite corrupting the concurrent worktree. Preserve the ref when ownership is uncertain and return `rollback_failed`.

### blocking: Do not retire a branch after another worktree can claim it

**File:** `app/workspace.py:1502-1507`

After detaching, another process can check out `original_branch` while it still points to `original_head`. The CAS then succeeds and rewinds the branch under that worktree, leaving it inconsistent and potentially dropping forced, unmerged commits. The safe flat solution is to retain the old branch rather than mutate it after releasing checkout ownership.

### blocking: Validate same-branch state before reporting success

**File:** `app/workspace.py:1289-1290`

A concurrent `update-ref` can advance `new_branch` between the initial status check and this return. Because HEAD is symbolic, the worktree then points at the new OID while its index/files remain at `original_head`, yet the route records a successful switch and activates the task. Require `target_head == original_head` and a final clean-status check; otherwise quarantine.

### blocking: Distinguish detached HEAD from inspection failure

**File:** `app/workspace.py:1260-1263`

Only the documented detached-HEAD return code should produce `original_branch=""`; every other `symbolic-ref` failure must abort before mutation. A transient inspection error currently gets treated as detached, so rollback can deliberately detach at `original_head`, declare success, and let the route restore a lifecycle claiming the old named branch.

### suggestion: Do not suppress partial worktree-removal failures

**File:** `app/workspace.py:491-499`

A nonzero `git worktree remove` can delete the directory but fail while removing administrative metadata. Checking only `wt_path.exists()` then suppresses that failure and deletes the branch, leaving a registered worktree referencing a missing ref. Require a zero result or verify that the Git worktree registration is gone before deleting the branch.

### suggestion: Clean up a target created before source resolution fails

**File:** `app/workspace.py:1292-1298`

If `target_created` is true and the second `from_ref` resolution fails, the function returns a normal failure while retaining the newly created target. Use the already captured `target_head` as `from_head`, or preserve the branch under an explicit `rollback_failed` result.

## Verdict

**❌ Incorrect — reject T1.**

Locking, write-ahead quarantine, cancellation containment, detached success flow, task-update gating, and MCP compatibility are substantially improved. Checkout ownership remains outside the CAS contract, though—apparently a branch can have perfect paperwork while another worktree drives it away. 🚗

## Round (2026-08-01T08:42:58Z)

## Summary

All Round-2 findings are resolved: checkout ownership is preserved, original refs are retained, same-branch switches are rejected, detached HEAD is distinguished correctly, and cleanup verifies Git’s registry. No remaining blocking data-loss or cancellation race found. The claimed 197 tests were not rerun.

## Findings

### suggestion: Do not report an unobservable target as successfully committed

**File:** `app/workspace.py:1143-1155` · **Confidence:** 0.98

If the final `rev-parse` fails or the target disappears concurrently, `target_after` remains empty but `target_changed` becomes true. An existing successful result is still returned as `ok=True`, `state="merged"`, and `commit_point="target_committed"`. Use `state="partial"` and `commit_point="unknown"` when the mandatory final snapshot cannot be obtained.

### suggestion: Reserve `rolled_back` for verified restoration

**File:** `app/workspace.py:1163-1165` · **Confidence:** 0.96

`mutation_started` is set before even reading the pre-mutation HEAD, and an existing `state="restore_failed"` is overwritten by this generic classification. Consequently, failures before mutation or failures restoring the original checkout can both claim `commit_point="rolled_back"`. Preserve known restoration failures as `partial/unknown`, and set the flag at the first actual mutation.

### suggestion: Avoid quarantining a clean branch-creation failure

**File:** `app/workspace.py:1567-1570` · **Confidence:** 0.97

When `_create_branch_ref` fails operationally and the target remains absent, `target_created` and `target_existed` are both false. This branch nevertheless interprets return code 1 as a changed existing target, producing `rollback_failed` after Git state was restored exactly. Apply this check only when `target_existed`; an absent never-created target is a normal rollback.

### question: Is the public repository lock expected to wrap existing helpers?

**File:** `app/workspace.py:158-166` · **Confidence:** 0.91

Each mutation helper already acquires this lock using a fresh file descriptor. If #115 uses `with repo_mutation_lock(repo): create_worktree(...)`, Linux `flock` can block against the caller’s own lock indefinitely. If composition is intended, the lock needs reentrancy or locked internal variants; otherwise document that it must not wrap these helpers.

## Verdict

**✅ Correct — approve T1 with the suggestions above.**

The remaining issues affect outcome precision and unnecessary quarantine, not repository safety. The refs finally stay where they belong; only the typed receipt occasionally claims delivery before checking the mailbox. 📬

## Round (2026-08-01T08:54:59Z)

## Summary

The final pass is annoyingly clean. ✅ All Round-3 items are fixed:

- **FIXED:** failed final target snapshots return `ok=false`, `partial/unknown`, and an error.
- **FIXED:** `rolled_back` requires verified unchanged ref and clean target; restoration failures remain `partial/unknown`.
- **FIXED:** absent-target creation failures restore normally without false quarantine.
- **FIXED:** non-reentrant lock usage is explicitly documented.
- **FIXED:** typed receipts remain additive, conflict paths are NUL-delimited, and required snapshots appear on every return path.

Tests were not run, as requested.

## Findings

No blocking, suggestion, or question findings in the supplied hunks.

## Verdict

**APPROVED.**

No concrete data-loss, deadlock, checkout-ownership, rollback, cancellation, or typed-outcome bug remains. The merge receipt finally behaves like a receipt instead of speculative fiction. 🧾
