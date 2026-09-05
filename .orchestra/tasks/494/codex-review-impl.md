<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 Apparently a worktree becomes a sandbox if we stare at its `cwd` hard enough.

## Summary

Reviewed the exact pinned diff `cda2094...d02f2c4`, limited to the five changed files and direct consumers. No files were edited.

The focused command passed: `316 passed in 7.33s`. It covers the happy path but misses several isolation and cleanup failures.

Execution proof—exact implementation line: `source = (worktree / name).resolve()`.

## Findings

### blocking: Writable agents can escape the prepared worktree

**File:** [scripts/wf_adapters.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_adapters.py:254)

The default Codex path selects `danger-full-access`; Claude exposes its default shell tools, and Harness exposes `bash`. A worktree only changes `cwd`—it does not prevent commands using absolute paths or `git -C`. Agent input can therefore modify the shared checkout, sibling worktrees, workflow journals, or run `git push ...:main`, bypassing both archival and the “never merge into the shared branch” invariant. The isolation oracle only verifies that relative files differ between two worktrees; it never attempts an out-of-worktree write. Writable processes need filesystem confinement to the prepared worktree while retaining network access.

---

### blocking: Default Codex MCP loads the global user configuration

**File:** [scripts/wf_adapters.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_adapters.py:274)

When `mcp=True`, the adapter removes `--ignore-user-config` but never creates a per-call `CODEX_HOME` from `_load_scope_mcp_servers(cwd)`. Codex therefore loads unrelated profile-level MCP servers and their credentials, while the intended scope `.mcp.json` is not translated into Codex configuration at all. This defeats the existing MCP isolation contract and can expose foreign project tools/secrets to every default workflow call. Use a private one-shot `CODEX_HOME` containing only the scope servers and required authentication material.

---

### blocking: An agent commit prevents worktree and branch cleanup

**File:** [scripts/wf_run.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:783)

After an agent runs an ordinary `git commit`, `discard_prepared_worktree()` sees `HEAD != initial_head` and deliberately raises “ownership changed; preserving,” leaving both the worktree and `feat/...` branch behind. Nothing currently forbids commits, especially while the approved module insertion point is empty. Snapshot the committed changes, then restore the owned disposable branch to `initial_head` before calling the existing discard function, or otherwise make committed WIP a supported cleanup case.

---

### blocking: Ignored outputs are silently destroyed

**File:** [scripts/wf_run.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:292)

The archive inventory uses `git ls-files ... --exclude-standard`, so newly created files matching repository ignore rules are omitted. A requested artifact such as `data/result.json`, `*.log`, or another generated output can therefore exist only in the worktree and be deleted by the subsequent forced discard. This violates the requirement to archive changed files. The snapshot needs a baseline-aware filesystem comparison that can retain newly created ignored deliverables while excluding seeded secrets and disposable caches explicitly.

---

### blocking: Worktree setup failure is recorded as a paid unknown call

**File:** [scripts/wf_run.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:728)

`dispatched` is journaled before `_run_attempt()`, but `create_worktree()` now occurs inside that method and before provider invocation. If worktree creation fails—collision, disk error, invalid branch, setup failure—the journal contains only `dispatched`. Resume consequently classifies the call as `outcome_unknown`, consumes the entire dollar budget conservatively, and refuses to retry even though no provider ran. Preparation needs its own recoverable state; `dispatched` should remain immediately before the actual provider boundary.

---

### blocking: The standalone Harness entry point became writable without isolation

**File:** [app/harness/oneshot.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/app/harness/oneshot.py:18)

`run_oneshot()` now defaults to `tools_level="all"`, `network=True`, and `mcp=True`, while `main()` invokes it directly on caller-supplied `--cwd`. That executable path never creates or discards a prepared worktree, so invoking the existing module against a shared checkout writes directly into it. Route the CLI through the workflow isolation lifecycle or keep the standalone default non-writable unless an isolated workspace is supplied.

## Verdict

**❌ Needs work.** The #487 accounting and verification invariants remain intact on the tested happy path, but six blocking security, data-loss, and cleanup defects prevent approval.

Right now the disposable worktree is a fenced garden with an absolute-path gate and a branch-shaped padlock. 🔓

## Round (2026-09-05T03:35:07Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 The deadlock is gone; cancellation merely leaves the furniture behind now.

## Summary

Reviewed exact snapshot `d062f4f...eb9fda9`. The focused suite passed: `321 passed in 6.98s`.

Execution proof—exact implementation line: `self.budget.dispatched_calls -= 1`.

| Prior finding | Disposition |
|---|---|
| 1. Absolute-path escape | **ACCEPTED RISK** — explicit cwd/worktree trust boundary |
| 2. Global Codex MCP config | **FIXED** |
| 3. Commit prevents cleanup | **FIXED** |
| 4. Ignored outputs lost | **FIXED** |
| 5. Setup recorded as dispatched | **FIXED** |
| 6. Standalone Harness writable | **FIXED** |

## Findings

### blocking: Cancellation can orphan a successfully created worktree

**File:** `scripts/wf_run.py:769-775` | **Confidence:** 0.98

`asyncio.to_thread()` cancellation does not stop a function already executing in its worker thread. If the workflow task is cancelled while `create_worktree()` runs, the await raises before assigning `prepared`, so the exception handler sees `prepared is None` and cannot discard anything. The thread can then finish successfully, leaving its worktree and branch behind; resume retries the deterministic name and repeatedly hits “worktree already exists.” Keep the thread task handle, shield or await its eventual result after cancellation, and discard the returned worktree before propagating cancellation.

---

### blocking: Cancellation during snapshot skips reset and discard

**File:** `scripts/wf_run.py:847-853` | **Confidence:** 0.97

If a background job is cancelled while `_snapshot_worktree()` is running, `CancelledError` bypasses `except Exception` and exits the `finally` block before `_reset_prepared_worktree()` and `discard_prepared_worktree()` execute. Large archives make this window realistic during restarts or job cancellation. Cleanup must be cancellation-safe so snapshot completion or failure always proceeds to reset and discard before cancellation is re-raised.

## Verdict

**❌ Needs work.** The six previous findings are resolved or explicitly accepted, and the normal plus parallel paths pass. The two remaining cancellation paths still leak branches/worktrees and can make the workflow permanently non-resumable.

The worktree now cleans up perfectly—as long as nobody interrupts the cleanup. 🧹

## Round (2026-09-05T03:39:31Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

😏 One cancellation now waits politely; the second still pulls the floor out from under it.

## Summary

Reviewed exact snapshot `d062f4f...5e2fdec`. Focused suite: `323 passed in 7.40s`.

Execution proof—exact implementation line: `if not prepare_task.cancelled() and prepare_task.exception() is None:`.

| Prior finding | Disposition |
|---|---|
| Cancellation during worktree creation | **STILL BROKEN** under repeated cancellation; single cancellation is fixed |
| Cancellation during snapshot cleanup | **STILL BROKEN** under repeated cancellation; single cancellation is fixed |

## Findings

### blocking: Repeated cancellation bypasses both protected waits

**File:** [scripts/wf_run.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/wf-run-engine/scripts/wf_run.py:809) and `:898` | **Confidence:** 0.99

After catching the first `CancelledError`, both paths wait using unshielded `asyncio.gather(...)`. A second `task.cancel()` cancels that gather and marks the inner task cancelled while its `to_thread` function continues. During preparation, the late worktree result is lost and neither cleanup nor reservation release runs; during cleanup, cancellation propagates before reset/discard completes. The frozen tests issue only one cancellation. A direct semantic probe reproduced `inner_cancelled=True thread_finished=False`, followed by the worker thread completing afterward. Continue shielding or repeatedly drain the inner task through subsequent cancellations, then propagate cancellation only after its true outcome is handled.

## Verdict

**❌ Needs work.** Both original seams are fixed for one cancellation but remain blocking under repeated cancellation, which can still leak worktrees and branches. This is the third and final executable review round.

The janitor survives one fire alarm; the second one steals the mop. 🧹
