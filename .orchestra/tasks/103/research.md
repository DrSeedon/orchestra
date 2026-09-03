# #103 — Content-aware branch lifecycle guards

## Question

- **Context:** Orchestra squash-merges worker branches and later switches or deletes their worktrees. A worker may be based on the repository mainline or on a mutable parent worker branch.
- **Change under test:** replace commit-ancestry/count guards with a content-aware test and make the destructive `force` override truthful at the public API boundary.
- **Baseline:** `git rev-list <base>..HEAD --count`.
- **Deciding outcome:** after a squash merge, a branch with no remaining content contribution must be switchable/deletable; a branch whose content would still change its base must stay blocked.

## Hypotheses considered

### H1 — Exact endpoint tree equality is sufficient

`git diff --quiet <base> HEAD` (equivalently, equal endpoint tree IDs) safely identifies all branches whose work is already incorporated.

**Falsifier:** a base that advanced independently after incorporating the worker must produce a non-empty endpoint diff even though merging the worker would add no content.

### H2 — Patch identity is sufficient

`git cherry` / patch-id comparison safely recognizes squash-merged worker commits.

**Falsifier:** a multi-commit worker squashed into one base commit must still be reported as unmatched commits.

### H3 — An unsanitized three-way prospective merge is the correct content test

If `git merge-tree --write-tree <base> HEAD` succeeds and its resulting tree equals `<base>^{tree}`, the worker has no remaining content contribution. A different result tree or a conflict means the guard must block.

**Falsifier:** any experiment where real worker-only content produces the base tree, including through repository merge configuration.

### H4 — A prospective merge is safe after neutralizing custom merge behavior

Keep the ancestry fast path, but run `merge-tree` with `merge.default=text`, `merge.renormalize=false`, and every configured `merge.<driver>.driver` overridden to `false`.

**Falsifier:** a configured custom driver still executes or a real worker-only change still produces the base tree under those overrides.

## Experiment protocol (registered before execution)

All repositories are throwaway directories under `/tmp`; live worktrees are inspected read-only.

For each scenario record:

1. `rev-list <base>..HEAD --count`;
2. `diff --quiet <base> HEAD` exit status;
3. `git cherry <base> HEAD`;
4. `merge-tree --write-tree <base> HEAD` exit status and result tree;
5. `<base>^{tree}`;
6. expected guard decision.

Pass criteria:

- squash-merged one- and multi-commit branches → allow;
- genuinely unmerged worker content → block;
- base-only advancement after incorporation → allow;
- freshly created branch whose base later advances → allow;
- conflict/invalid base → fail closed with a visible error;
- detached worker HEAD → detector remains well-defined because it evaluates `HEAD`, while branch creation behavior is verified separately.
- a later base edit overlapping already-squashed worker content is recorded as a conservative limitation rather than reclassified after seeing the result.

## Findings

### F1 — `rev-list` answers an ancestry question, not a content question

**CONFIRMED — project source + official Git documentation + direct measurement.**

`switch_worktree_branch()` runs `git rev-list <from_ref>..HEAD --count` and blocks when the count is positive. `delete_session()` repeats the same guard. Git defines `A..B` as commits reachable from `B` excluding commits reachable from `A`; it does not compare resulting trees [1]. The checked-in call sites are:

- `app/workspace.py:991-1065` — `switch_worktree_branch`;
- `app/routes/sessions.py:596-651` — `delete_session`.

In the multi-commit squash experiment, `rev-list main..worker --count` returned `2` while the prospective merge tree equalled the `main` tree:

```text
squash_multi rev=2(rc=0) diff_rc=0
cherry=+ <sha>;+ <sha>; merge_rc=0 merge_eq_base=yes
```

This is the reported false positive: the commit objects are absent from `main`, but their cumulative content is present.

### F2 — exact endpoint diff/tree equality is a valid sufficient shortcut but an invalid complete detector

**REFUTED as the complete detector — synthetic measurement + live-state measurement.**

`git diff --quiet <base> HEAD` returns `0` for equal endpoints and `1` for any endpoint difference [2]. It recognizes the immediate squash case, but it also treats base-only advancement as “unmerged worker work”:

```text
squash_then_base_ahead rev=2 diff_rc=1 merge_rc=0 merge_eq_base=yes
fresh_branch_base_ahead rev=0 diff_rc=1 merge_rc=0 merge_eq_base=yes
```

The real-state audit ran the repository’s actual `resolve_base_branch()` over all 69 non-archived sessions whose worktree directories still exist. Resolution succeeded for 69/69. Forty worktrees had zero commits in `<base>..HEAD` but a non-empty endpoint diff. Therefore the reporter’s `git diff --quiet main..branch` candidate would newly block 40 live configurations that the current ancestry fast path allows.

Raw live summary:

```text
existing=69 resolved=69 resolve_failed=0
rev_positive_tree_equal=0 rev_zero_tree_diff=40 rev_positive_tree_diff=19
```

### F3 — patch-id / `git cherry` does not recognize a multi-commit squash

**REFUTED — official Git documentation + direct measurement.**

`git cherry` compares individual patch-equivalent commits [3]. With two worker commits squashed into one base commit, the experiment marked both worker commits `+` (not applied), although the prospective merge was a no-op:

```text
cherry=+ 926dd1f...;+ 34c35cd...;
merge_rc=0 merge_eq_base=yes
```

It is appropriate for copied/rebased individual patches, not for Orchestra’s cumulative multi-commit squash.

### F4 — only a sanitized prospective merge is a safe content detector

**LIKELY — official Git plumbing/attributes contracts + synthetic matrix + live audit. No final Codex verdict exists because three review attempts failed at timeout/transport level.**

`git merge-tree --write-tree <base> HEAD` performs the same class of three-way content merge as `git merge`, including rename and directory/file conflict handling, without touching the worktree or index. On a clean merge it emits the prospective top-level tree OID; exit `1` means conflicts; other non-zero exits mean the merge could not run [4].

The first Codex review timed out before a verdict, but its partial trace found a blocking counterexample. A custom low-level merge driver may keep `%A` unchanged and exit successfully [5]. The reproduced repository had real conflicting worker content:

```text
normal_rc=1
custom_rc=0 custom_eq_base=yes
effective config: merge.default=keep; merge.keep.driver=true
```

Therefore H3 is **REFUTED**: unsanitized `merge-tree` can both execute repository-defined commands and falsely claim that real worker content is a no-op.

The tested mitigation is to neutralize custom merge behavior in the same `git merge-tree` invocation:

1. run the existing `rev-list` count and allow immediately when it is zero;
2. list effective `merge.<driver>.driver` keys with `git config`;
3. build `git -c merge.default=text -c merge.renormalize=false`, plus `-c <driver-key>=false` for every configured custom driver;
4. run the sanitized `merge-tree --write-tree <base> HEAD`;
5. allow only when exit status is `0` and its result tree equals `<base>^{tree}`;
6. treat exit `1` as remaining/conflicting worker content;
7. surface config, tree parsing, and other command failures instead of proceeding with `reset --hard`.

The same custom-driver repository then produced:

```text
unsafe_rc=0 unsafe_eq_base=yes
sanitized_rc=1 sanitized_eq_base=no
```

Git documents `text`, `binary`, and `union` as built-in merge drivers; custom drivers come from `merge.<driver>.driver`, receive `%O/%A/%B`, write the result through `%A`, and may declare success with exit zero [5]. Overriding every effective custom driver command with `false` makes any selected custom driver fail closed, while `merge.default=text` prevents a custom fallback and `merge.renormalize=false` prevents virtual filter conversions during this safety check.

Synthetic matrix, Git 2.51.0:

| Scenario | `rev-list` | endpoint diff rc | `git cherry` | merge rc | result tree = base | Decision |
|---|---:|---:|---|---:|---|---|
| two commits squash-merged | 2 | 0 | `+`, `+` | 0 | yes | allow |
| squash merged, then base-only commit | 2 | 1 | `+`, `+` | 0 | yes | allow |
| real worker-only commit | 1 | 1 | `+` | 0 | no | block |
| fresh branch, base advanced | 0 | 1 | empty | 0 | yes | allow on fast path |
| content-equal empty commit | 1 | 0 | `+` | 0 | yes | allow |
| both sides edit same new path differently | 1 | 1 | `+` | 1 | no | block |
| missing base ref | command error | 128 | error | 1 | no | visible error |
| nested parent squash | 2 | 0 | `+`, `+` | 0 | yes | allow |

The live config audit covered 22 unique repositories represented by the 69 extant worktrees. Two repositories define a custom `merge.keepincoming.driver`, proving this is not merely a synthetic concern.

The read-only live audit skipped eight dirty worktrees before the sanitized content detector, then evaluated the remaining real repository states. It found four currently live false positives where `rev-list` is positive but the sanitized merge of `HEAD` into the resolved base produces the base tree unchanged:

```text
existing=69 dirty_skipped=8
fast_allow_rev_zero=44 content_allow_sanitized_merge_noop=4
block_tree_changes=9 block_conflict=4 error=0
```

One of the four content-no-op cases is in a repository with the custom driver; the sanitized overrides retained the correct allow result without trusting that driver. No switch, reset, checkout, delete, or ref update was run in those live worktrees. `merge-tree` did not touch their worktrees or indexes [4].

### F5 — the direct Orchestra merge reset works, but mutable parent bases recreate the bug

**CONFIRMED — actual `merge_worktree_to_main()` execution + nested squash experiment.**

The direct function experiment squash-merged one worker commit and then measured identical target and worker HEADs:

```text
{'ok': True, 'commits_merged': 1, 'branch': 'task-1/worker', ...}
main=9a05af78... worker=9a05af78... rev=0
```

That result comes from `_reset_worktree_to_ref()` after a successful merge (`app/workspace.py:642-660, 908-911`).

The protection fails again when `base_branch_strategy: parent` is involved:

1. child is squash-merged into parent and reset to the parent tip;
2. parent is squash-merged into main and the mutable parent ref is reset to the new main tip;
3. child still points at the pre-squash parent commit while its persisted base ref now points at the unrelated squash commit.

Measured result:

```text
nested_parent_squash rev=2 diff_rc=0
cherry=+ <sha>;+ <sha>; merge_rc=0 merge_eq_base=yes
```

This explains why the earlier “reset worker after merge” fix does not solve nested lifecycle reuse.

### F6 — the third guard in `delete_session` is affected

**CONFIRMED — direct route-function execution against the nested squash repository.**

With a clean child worktree whose prospective merge into its persisted `parent` base is a no-op, the current route returned:

```text
{'status': 400,
 'body': '{"error":"worker has 2 unmerged commit(s). merge_worker first (or force=true)"}',
 'remove_called': 0}
```

Thus `kill_worker(force=False)` is falsely blocked after squash. Unlike branch switching, `kill_worker(force=True)` is already present in the MCP signature and reaches the route.

### F7 — the switch error advertises an override absent from the public switch API

**CONFIRMED — project source inspection.**

- `switch_worktree_branch(..., force=False)` exists and its error says `pass force=True`;
- `app/routes/sessions.py:switch_branch` does not read or forward `force`;
- `app/mcp_stdio.py:switch_worker_branch` has no `force` parameter;
- `kill_worker` already exposes the same kind of explicit override end-to-end.

Exposing `force: bool = False` through both switch layers is preferable to deleting the message: the chosen no-op detector deliberately fails closed on ambiguous later overlapping edits, so operators need an explicit, auditable escape hatch. `force` must continue to bypass only the committed-content guard; a dirty tree remains blocked.

### F8 — edge cases

**CONFIRMED where measured; otherwise tied to the existing resolver contract.**

- **Missing `from_ref`:** `resolve_base_branch()` verifies a local branch before the detector (`app/workspace.py:173-237`); the raw missing-ref experiment failed visibly. Detector command failures must also fail closed.
- **Fresh branch/base advanced:** measured `rev=0`, endpoint diff `1`, prospective merge equal to base. The ancestry fast path allows it.
- **Detached HEAD:** the current function was executed from a detached temp worktree; it created `task-103/detached` with `HEAD == parent`. The detector can safely address `HEAD` without requiring a current branch name.
- **Non-main parent base:** all comparisons use the resolved/persisted `from_ref`; the nested `parent` experiment passed without hard-coded `main`.
- **Conflict:** measured `merge-tree` exit `1`; the guard must block.
- **Unrelated histories:** official `merge-tree` behavior is to error unless explicitly allowed [4]. The detector should not use `--allow-unrelated-histories`; it must fail closed. Orchestra’s successful unrelated-history merge path already resets the worker ref afterward.
- **Content-equal but hash-diverged empty commit:** measured as a merge no-op and allowed. This matches the requested content, rather than commit-metadata, safety contract.

## Counter-evidence

- The current checked-out `send_message` auto-switch and `merge_worker(next_task_id=...)` paths already call `switch_worktree_branch(..., force=True)`. Therefore the checked-in detector cannot directly block those two internal paths. The explicit `switch_worker_branch` path (still prescribed by `pipelines/tasks-pm/prompts/roles/base-orchestrator.md`) and `kill_worker(force=False)` are conclusively affected. The exact reporter sequence may have run older in-memory route code or included an explicit switch; this research did not restart or mutate the live service, so that detail remains **UNCERTAIN** and does not invalidate the shared guard defect.
- A base may squash the worker and later edit the same lines again. The measured prospective merge then conflicts (`merge_rc=1`) even though the worker was historically incorporated. Without durable merge provenance, current Git state cannot distinguish that history from genuinely conflicting unmerged work. The detector should conservatively block and require public `force=True`.
- Unsanitized `merge-tree` is unsafe in repositories with custom merge drivers: a driver that leaves `%A` intact and exits zero produced the base tree despite real conflicting worker content. This counterexample was surfaced by the timed-out Codex round and independently reproduced. The plan must include both driver neutralization and a regression test.
- `merge-tree --write-tree` creates a top-level tree object in the object database [4], although it does not touch the index or worktree. The `rev-list == 0` fast path avoids this work for ordinary ancestor cases; Git garbage collection handles unreachable plumbing objects.

## Affected files, risks, edge cases

- `app/workspace.py`
  - add one shared content-status helper;
  - replace the switch guard;
  - preserve dirty-tree blocking and `force` semantics;
  - make all Git command failures visible.
- `app/routes/sessions.py`
  - reuse the same helper in `delete_session`;
  - forward a validated boolean `force` from `switch_branch`;
  - do not change the already-forced atomic merge/send paths.
- `app/mcp_stdio.py`
  - expose and forward `force: bool = False` for `switch_worker_branch`.
- `tests/test_workspace.py`
  - cover nested/multi-commit squash, real unmerged content, base advancement, conflict/error, and detached HEAD as proportionate.
- `tests/test_api.py`
  - cover kill after squash, kill with real content, switch force transport, and the existing auto-switch contract.
- `tests/test_mcp_stdio.py`
  - cover default/explicit switch force JSON.

Primary risk: a false “merged” decision would make the following `reset --hard` discard committed work. The helper must allow only an ancestry-safe case or a clean prospective merge whose tree is exactly the base tree. Conflicts, malformed output, missing refs, and command failures must block.

The current switch dirty-tree check also ignores a non-zero `git status` return code and inspects only stdout (`app/workspace.py:999-1006`). Because that failure would otherwise fall through to `reset --hard`, the switch ticket must make this adjacent guard fail closed.

Out of scope: changing merge strategy, refactoring lifecycle locking, changing `branch_wip_status`, or touching `app/tg_bridge.py`.

## Sources

1. [Git `rev-list` documentation](https://git-scm.com/docs/git-rev-list) — primary source; range semantics and `--count`.
2. [Git diff options](https://git-scm.com/docs/diff-options) — primary source; `--quiet` / `--exit-code` statuses.
3. [Git `cherry` documentation](https://git-scm.com/docs/git-cherry/2.0.5.html) — primary source; per-commit patch equivalence.
4. [Git `merge-tree` documentation](https://git-scm.com/docs/git-merge-tree/2.43.0.html) — primary source; three-way merge behavior, result tree, conflicts, and no worktree/index mutation.
5. [Git `gitattributes` documentation](https://git-scm.com/docs/gitattributes/2.11.4) — primary source; built-in/custom merge drivers, `%O/%A/%B`, `merge.default`, and custom-driver exit contract.

## Reproduction locations

The measured throwaway repositories remain under:

- `/tmp/orchestra-103-git-frm1zW`
- `/tmp/orchestra-103-parent-8VWtuW`
- `/tmp/orchestra-103-orchestra-merge-*`
- `/tmp/orchestra-103-overlap-aI1aNc`
- `/tmp/orchestra-103-driver-tysYi9`
- `/tmp/orchestra-103-sanitized-dTcu7V`
