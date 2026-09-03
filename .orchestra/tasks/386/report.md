# #386 — Phase 3 report: target-aware merge admission

Date: 2026-08-24

## Outcome

Implemented the single atomic T1 from the approved plan. A nested behavioral worker merge now uses
an authoritative task-owned acceptance revision, a pinned target SHA, an immutable target oracle
manifest, and a separately server-derived target-relative mapped regression gate. No target
baseline/failure-set subtraction was added.

The implementation branch remained a parallel descendant of pre-#380 main as instructed. Git's
three-way merge was conflict-free, and the combined tree passed both #386 and all #380 receipt
oracles.

## What changed

- `app/db.py`
  - Adds `tm_tasks.acceptance_oracle_json` and
    `merge_operations.accepted_admission_json` with `{}` defaults.
  - Repairs the legacy `tm_tasks` unique-index recreation with named columns/defaults so existing
    commands, oracle JSON, and priority survive schema drift.
  - Adds old-schema additive migration for both JSON columns without disturbing #380's
    `message_deliveries` schema/migration.
- `app/tm.py`
  - Validates canonical task manifests and proof-derived audit actors.
  - Stores versioned `{required, revision, manifest_paths, updated_at, updated_by}` metadata.
  - Changes command/required/manifest atomically and increments the oracle revision once; ordinary
    task updates do not. Command-only changes on an authoritative oracle also revise/audit it;
    legacy command-only tasks retain legacy behavior.
- `app/routes/tm.py`, `app/mcp_stdio.py`
  - Expose oracle manifest/required/clear fields only through orchestrator-authorized paths.
  - Derive actor identity from the bound session proof; forged actor payloads are not accepted.
  - Enforce caller-project isolation for create, update, clear, command-only, and metadata-only
    changes.
- `app/acceptance.py`
  - Pins command/revision/target plus recursively expanded target `tests/` blobs/modes and pytest
    config into a SHA-256 contract.
  - Compares candidate HEAD and dirty working bytes/modes, rejects test-tree additions/removals and
    protected `conftest.py`/pytest-config additions before subprocess execution.
  - Classifies missing, mutated, skipped, deselected-only, collection-error, and timeout evidence as
    non-authorizing.
- `app/merge_operations.py`
  - Resolves explicit target or accepted base target and pins target/oracle before runner start.
  - Persists the snapshot in the operation record; replay never mixes newer task/target state.
  - Uses the stored SHA for oracle evaluation, mapped selection, and merge execution.
  - Requires positive oracle evidence for the nested behavioral path and independently blocks every
    non-authorizing mapped result.
  - Records compact target/oracle/mapped/recheck evidence on success and refusal.
  - Preserves #383/#384 legacy empty-operation acceptance behavior and explicit no-oracle final-only
    behavior as distinct cases.
- `app/merge_test_gate.py`
  - Accepts pinned target ref/SHA and computes `target_sha...HEAD` paths; default callers retain
    current main/master discovery.
  - Returns mapped files and target identity in structured output.
- `app/workspace.py`, `app/routes/sessions.py`
  - Pass and verify `expected_target_head` under the repository mutation lock.
  - Early mismatch returns immediately before target owner discovery/checkout; a second check after
    merge precheck stops squash/cherry-pick if the ref moved late.
- `tests/test_merge_target_oracle_386.py`
  - Unchanged byte-for-byte from frozen RED commit `b1af1b07`.

Implementation commits: `f971b572` and review-fix `82b0d257`. The repository's eventual worker
squash keeps the delivered task atomic.

## Ticket completion

### T1 — Atomically admit one target-aware vertical merge

DONE. All 32 frozen controls are green. They cover task authority/audit, old/fresh/recreated schema,
operation replay, exact target fallback/pinning, immutable inputs, nested/main/mapped behavior,
non-authorizing oracle/gate outcomes, early/late target movement, structured result evidence, and
the final-only shoulder.

## Verification

### Frozen ticket oracle

```text
uv run --frozen python -m pytest -q tests/test_merge_target_oracle_386.py -k 'test_t386_t1_'
32 passed in 54.10s

final post-mutation repeat:
32 passed in 56.63s
```

Frozen input check:

```text
git diff --quiet b1af1b07 -- tests/test_merge_target_oracle_386.py
exit 0
```

### Current-branch compatibility

```text
tests/test_tm.py tests/test_acceptance.py tests/test_mcp_proof.py
tests/test_mcp_stdio.py tests/test_routes_surface.py
160 passed in 71.67s

tests/test_merge_operations.py tests/test_merge_branch_drift.py tests/test_merge_test_gate.py
66 passed in 56.55s

tests/test_workspace.py
115 passed in 127.32s
```

Additional real-code probe after review fixes:

```text
manifest_only_cross_project=blocked command_only_revision=2
```

### #380/current-main three-way compatibility

Implementation-head check:

```text
git merge-tree --write-tree main HEAD
b11e669ade16668f43a6b9a59fb3ceb6788f9923
exit 0
```

From an archive of that exact combined tree:

```text
tests/test_merge_target_oracle_386.py + tests/test_message_delivery_receipts_380.py
54 passed in 113.56s

tests/test_tm.py tests/test_acceptance.py tests/test_mcp_proof.py
tests/test_mcp_stdio.py tests/test_routes_surface.py
160 passed in 57.43s

tests/test_merge_operations.py tests/test_merge_branch_drift.py tests/test_merge_test_gate.py
66 passed in 40.72s

tests/test_workspace.py
115 passed in 57.91s
```

A flat full-suite run was intentionally not used because this repository contains explicitly marked
live-provider probes. All task-required and changed-consumer compatibility suites were run without
provider, live merge, deploy, or restart.

## Mutation evidence

Each mutation was applied alone to a green focused oracle, returned non-zero, was rolled back with
mtime refresh, and the same test then returned green:

| Mutation | Named oracle result |
|---|---|
| Hardcode `main` instead of pinned target | nested-target test RED; green after rollback |
| Remove early and post-precheck target checks | late-target-move test RED; green after rollback |
| Trust candidate selector metadata | candidate-subset test RED; green after rollback |
| Skip `tests/oracle_helper.py` manifest verification | immutable-input test RED before subprocess; green after rollback |
| Allow `SKIPPED` required oracle | operation fail-closed test RED; green after rollback |
| Ignore mapped failure | operation fail-closed test RED; green after rollback |

The first partial target-check mutant was excluded: it left the post-precheck check active and the
oracle correctly stayed green. The corrected compound mutant disabled every target check and was
caught.

## Pre-mortem and checks

1. **Parallel #380 schema/route edits conflict or get overwritten.** Check: Git merge-tree exit 0
   plus combined #380 receipt `22/22` inside the 54-test run.
2. **Legacy #383/#384 rows bypass or are over-blocked by the new snapshot.** Check: existing
   acceptance/merge suites, including restored empty-snapshot dynamic acceptance, are green.
3. **Target moves after selection but before commit.** Check: early and post-precheck real-Git
   controls plus the remove-all-rechecks mutation.
4. **Candidate weakens oracle inputs or narrows mapped tests.** Check: recursive manifest controls,
   dirty/mode/config cases, candidate-selector control, and both relevant mutations.
5. **New oracle requirement breaks final-only/main merges.** Check: explicit no-oracle final-only
   operation reaches executor only after mapped tests pass.

## Compatibility, breaking changes, and TODO

- Breaking changes: none intended. New task/MCP fields are optional; old operations/commands retain
  their prior paths. Nested behavioral merges without a required authoritative bundle now fail
  closed by design.
- Data migration: additive, with explicit legacy/recreation/replay coverage.
- Deployment/restart/live merge: not performed.
- TODO: no implementation TODO. The owner must merge the branch; the final conflict gate is rerun on
  the final documentation commit before DONE.

## Review

Direct Sol implementation review, two executable rounds. Round 1 found one blocking project-scope
bypass and two correctness issues; all were verified and fixed. Round 2: `APPROVED`, no new
findings. Evidence: `docs/tasks/386/review-implementation.md`.
