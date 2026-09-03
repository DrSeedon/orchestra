# #406 — collision of task `par` between canonical and legacy

## Pre-fix inventory

The inventory was taken before any code or data mutation. `data/orchestra.db` was copied with
`sqlite3.Connection.backup()` into memory; every canonical `state.json` was then joined to its
legacy task by project and display number. The snapshot contained 693 legacy tasks, 684 canonical
tasks, 684 paired identities, and zero unresolved canonical project mappings.

There are **2 semantic collisions**, both in project `orchestra`:

| par | Older legacy task (keeps number) | Created | Newer canonical task (must move) | Created |
|---:|---|---|---|---|
| 398 | `knowledge(detail="summary")` returns full records; commit `915f352` | 2026-08-26 06:27:40 UTC | Fan: one tool, worker reuse, no accumulated reports | 2026-08-26 08:58:07 UTC |
| 399 | Extract structured facts from `token-efficiency.md` and `ox-alpha-harness-verdict.md`; commit `f0ff47f` exists in Git | 2026-08-26 08:20:37 UTC | Fan/barrier: one tool, reuse, no accumulated reports | 2026-08-26 09:00:56 UTC |

The newer canonical records have exact legacy mirrors at #404 and #405 respectively (same title
and description). At the first inventory watermark the maxima were legacy=408 and canonical=399.
While the fix was in progress, live #409 was allocated to `kb-promote-facts`; a later dry-run
therefore correctly proposed #410 and #411. Replacement numbers are never pinned in advance.

## Issuance fix

Canonical generation 3 now obtains `next_display_number` from the canonical task list. Before any
write, `app/tm.py` compares it with legacy `_next_par`; disagreement raises
`IdentityConflictError` and neither store is changed. On agreement, canonical allocates that exact
number and legacy receives it explicitly, with a second check inside the legacy write transaction.
A process lock serializes the compare/write sequence for concurrent task-create calls.

Regression oracle before implementation:

```text
1 failed, 1 passed
Failed: DID NOT RAISE IdentityConflictError
```

After implementation:

```text
2 passed
```

## Repair script

`scripts/repair_task_par_collisions.py` is dry-run by default. It prints the collision table and a
compressed, content-bound `SNAPSHOT_TOKEN`. `--apply` requires that token, opens
`BEGIN IMMEDIATE`, rereads both stores and task-directory occupancy, and refuses before any write
when the fresh snapshot differs.

For each collision the script:

1. keeps the older legacy task at its existing number;
2. moves the newer canonical task and its exact legacy mirror to the next free number after the
   current maxima of both stores;
3. restores the complete older task into canonical with its original timestamps, commits,
   acceptance data, worker binding, and deterministic source identity;
4. records replayable `task.display-renumbered` and `task.restored-from-legacy` events;
5. never deletes a canonical record and updates only `tm_tasks` in the legacy database.

The script is idempotent. Its event records also identify an interrupted canonical-first repair so
a later run can finish only the pending legacy move.

Actual stale-snapshot probe on copies of the live stores:

```text
INSERTED_BETWEEN_CALLS=#410
REFUSED: snapshot changed before --apply
- legacy added #410: 934 arrived between dry-run and apply
APPLY_RC=2
REFUSAL_LEFT_LEGACY_MIRRORS=[(928, 404), (929, 405)]
```

Actual repair plus create probe on copies of the live stores:

```text
APPLIED #398 -> #410
APPLIED #399 -> #411
CREATE_PAR=412
LEGACY_ROWS=[(412, 'post-repair unique allocation probe')]
CANONICAL_TITLE='post-repair unique allocation probe'
UNIQUE_BOTH=True
```

Live data was intentionally not mutated by the worker. The orchestrator will run dry-run and apply
after merge/restart under direct observation.

## Verification

- Focused task/canonical/repair suite: `33 passed in 3.04s`.
- Mutation of the primary counter comparison:
  `before=1 mutated=1 after=1 RED_RC=1 GREEN_RC=0`; the mutant wrote canonical state before the
  legacy refusal, and the frozen oracle detected the changed canonical head.
- Wider affected suite: `285 passed, 6 failed`; the identical six tests fail on an archived
  `main` tree as well (`6 failed`), so they are pre-existing and unrelated to this diff.
- Python compilation and `git diff --check`: clean.
- Ruff was unavailable in the environment (`Failed to spawn: ruff`).

## Review route

- Changed files/consumers: `app/tm.py` (route/MCP task creation), `app/ia/task_store.py`
  (canonical state and replay), the standalone repair script, and their frozen regression tests.
- Author metadata: Codex runtime, `gpt-5.6-sol` (`sessions.model` for `fix-par-collision`).
- Named AC: agreed counters create once in both stores; drift refuses without either write; stale
  dry-run refuses before mutation; old tasks retain #398/#399; newer tasks move without deletion;
  post-repair create is unique in both stores.
- Named checks/output: frozen issuance oracle `2 passed`; repair oracle `1 passed`; focused suite
  `33 passed`; mutation `RED_RC=1`, restored `GREEN_RC=0`; copy create `UNIQUE_BOTH=True`.
- Route: `none — Sol not authorized`. Persistence repair sets the high-risk floor, for which Luna
  is not a gate; the author is already Sol and no independent additional Sol run was authorized.
  Independence evidence is instead the two regression oracles committed red before their
  respective implementations, plus the orchestrator-owned live apply step.
