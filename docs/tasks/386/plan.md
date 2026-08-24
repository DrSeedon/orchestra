# #386 — Plan: target-aware merge admission for vertical RED tickets

Phase 2 only. This plan freezes RED tests and does not change `app/`, run a live merge, or touch
the running #380 branches.

## Outcome

A child implementing one vertical ticket may merge into its pinned nested integration target even
when that target already contains RED tests for later tickets. The platform must still reject:

- the same candidate when targeting `main`;
- any new server-mapped regression outside the ticket selector;
- missing, skipped, deselected-only, collection-error, or timed-out ticket evidence;
- candidate mutation of a frozen oracle input;
- worker-selected/narrowed test metadata;
- a target branch whose head moved after admission tests.

Failure-set subtraction is explicitly out of scope. The ordinary final-only chain remains the
fallback when positive frozen evidence cannot be produced.

## Chosen authoritative oracle source

Use a **task acceptance revision** as the sole authority, then copy one immutable snapshot into the
merge operation before any test selection.

Why this is the smallest source:

- `tm_tasks.acceptance_command` already exists, is task-scoped, and its HTTP/MCP mutation path is
  already restricted to a proof-bearing orchestrator in the same project.
- Parent-supplied merge metadata would duplicate the task command/manifest on every merge request,
  enlarge `merge_worker`, and create two mutable owners with no durable revision relationship.
- Spawn-time child metadata becomes stale when a RED oracle is re-frozen or corrected; making it
  authoritative would require stopping/re-spawning a valid child solely to update acceptance.
- A task revision can be updated by the task giver, audited once, and pinned into every operation;
  the child cannot select or narrow it.

### Task record contract

Keep `acceptance_command` as the command owner for backward compatibility. Add one canonical JSON
column, `acceptance_oracle_json`, rather than parallel loose columns:

```json
{
  "version": 1,
  "required": true,
  "revision": 7,
  "manifest_paths": [
    "pyproject.toml",
    "tests"
  ],
  "updated_at": "2026-08-24T00:00:00+00:00",
  "updated_by": {
    "session_id": "...",
    "name": "Orchestra-orchestrator",
    "role": "orchestrator",
    "scope": "/home/kesha/orchestra"
  }
}
```

Rules:

1. `required=true` requires a non-empty valid `acceptance_command` and a sorted, duplicate-free
   list of normalized repo-relative tracked roots. The server-mandated minimum is the complete
   target `tests/` tree plus the active pytest configuration file; explicit extra files may cover
   helpers outside `tests/`. No globs, arbitrary directories, absolute paths, `..`, or
   candidate-supplied fields. An attempted narrower manifest is invalid, not partial coverage.
2. Command, `required`, or manifest change is one atomic oracle update and increments
   `revision` exactly once. Title/status/assignee/sync changes do not change this revision.
3. `updated_by` is derived from the verified caller session/proof, never accepted from request JSON.
4. The command, manifest, revision, actor, and timestamp share the existing orchestrator-only and
   project-scope checks on create, update, and clear. A worker cannot create, update, clear, or
   narrow any part of the bundle; forged actor fields are ignored and the verified caller is stored.
5. Legacy tasks retain `{}` / `required=false`. For a nested behavioral slice, the server-derived
   target-relative diff plus a non-main target raises the floor to `required=true`; a missing bundle
   is a typed refusal, not a skip. Docs-only/final-only flows retain existing behavior.

### Operation snapshot contract

Add one `merge_operations.accepted_admission_json` column. Before inserting the operation:

1. resolve effective target = explicit request target, else accepted session base branch;
2. resolve and pin the exact target branch head SHA;
3. load the authoritative task oracle revision;
4. expand every manifest path from the pinned target tree into `{path, mode, blob}`;
5. compute
   `oracle_hash = sha256(canonical_json(source, task_id, revision, target_sha, command, expanded_manifest))`;
6. atomically store target branch/SHA plus the complete oracle snapshot in the operation row.

`accepted_admission_json` is server-produced and never part of the caller request hash. The runner
uses only this copy; it never re-reads a mutable task command.

Before executing the ticket command, recursively expand the pinned target `tests/` tree and compare
candidate HEAD/tree and working-tree bytes/modes for every entry with the target. Also reject any
candidate addition/removal anywhere below `tests/`, and any target-relative addition/change of a
root/ancestor `conftest.py` or pytest configuration name (`pytest.toml`, `.pytest.toml`,
`pytest.ini`, `.pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`) outside the manifest. A
mismatch returns `ORACLE_INPUT_MUTATED` before subprocess execution.

The mandatory tree covers ticket tests, fixtures/helpers, and `tests/**/conftest.py`; explicit
entries cover imported helpers outside `tests/`. Protected discovery/config names close the
candidate-added-input gap. The operation result records the expanded manifest hash, not an
unbounded duplicate of its contents.

## Target-aware regression contract

`merge_test_gate.changed_paths` and `evaluate_test_gate` receive the pinned target branch/SHA from
the operation. They do not discover `main`/`master` internally.

- Nested merge: `git diff --name-only <pinned-target-sha>...<pinned-worker-head>`.
- Main merge: the pinned target is `main`, so behavior remains `main...candidate`.
- Untracked candidate files remain included exactly as today.
- `select_tests()` remains server-owned and whole-file mapped; neither task selector nor candidate
  metadata can remove a mapped file.
- Ticket acceptance must be exactly `PASSED` with a non-empty selected execution. Empty command,
  `SKIPPED`, exit 5/deselected-only, collection error, timeout, invalid command, or OS failure never
  authorizes the nested behavioral path.
- The mapped regression gate remains independent. `FAILED`, `INCONCLUSIVE`, or `SKIPPED` cannot be
  waived by a green ticket selector in this special path.

No target baseline test run and no target/candidate failure-set comparison is added.

## Locked target recheck

Extend `workspace.merge_worktree_to_main` with `expected_target_head`. Inside the existing
`repo_mutation_lock`, compare the resolved target ref with the pinned SHA before expensive work,
then **re-check it again after merge precheck and immediately before squash/cherry-pick can mutate
the index or target commit**. Both comparisons use the same expected SHA.

Mismatch returns a typed non-mutating result (`TARGET_HEAD_CHANGED`) containing expected/actual
SHAs. It must not checkout, stage, merge, commit, reset, or update either ref. A matching target
continues through the current merge path. `execute_merge_session` passes the pinned SHA; no layer
may resolve a fresh head and silently replace it.

## Structured result contract

Every terminal merge operation, including refusals before execution, includes:

```json
{
  "admission": {
    "target": {"branch": "integration", "sha": "..."},
    "oracle": {
      "source": "task",
      "task_id": "386",
      "revision": 7,
      "ref": "<target sha>",
      "hash": "<sha256>",
      "status": "passed|failed|inconclusive|missing|mutated"
    },
    "mapped_files": ["tests/test_widget.py"],
    "target_recheck": {
      "expected": "...",
      "actual": "...",
      "matched": true
    }
  }
}
```

The full acceptance subprocess result stays under the existing `acceptance` key. The mapped pytest
result stays under `test_gate`. The compact admission object is the stable audit index that ties
them to the pinned inputs.

## Real-Git RED fixture

The unique test file builds a temporary repository graph for every case:

```text
main M ── integration I (adds frozen T1+T2 RED + oracle inputs)
                 ├── candidate C (implements T1 only)
                 ├── broken B (implements T1 + breaks mapped regression)
                 ├── mutated U (implements T1 + mutates oracle helper)
                 └── final F (implements T1+T2 for final-only fallback)
```

- `I`: ticket T1 and T2 are RED.
- `C`: ticket T1 is green; T2 remains RED; the mapped non-ticket regression is green.
- `B`: ticket T1 is green and the mapped non-ticket regression is RED.
- `U`: ticket T1 code exists but a frozen helper differs from `I`.
- `F`: both ticket tests and mapped regressions are green for the main/final-only shoulder.
- Fixture-only files provide a deselected-only command, a collection error, and a bounded timeout;
  they are unchanged from `main`, so they do not contaminate the final-only mapped set.

All Git writes and merge rehearsals are confined to pytest `tmp_path`; no provider, production DB,
live worktree, or #380 branch is touched.

## Tickets

### T1 — Atomically admit one target-aware vertical merge

- Files: `app/db.py` (`tm_tasks.acceptance_oracle_json`,
  `merge_operations.accepted_admission_json`, additive migrations and the named-column
  `tm_tasks` recreation path); `app/tm.py` (`create_task`, `update_task` atomic revision);
  `app/routes/tm.py` (proof-derived actor and project checks on create/update/clear);
  `app/mcp_stdio.py` (orchestrator-only bundle fields); `app/acceptance.py` (pin/verify/execute);
  `app/merge_operations.py` (effective target/oracle snapshot before runner, fail-closed
  composition, replay, normalized admission evidence); `app/merge_test_gate.py` (pinned
  target-relative mapping/evidence); `app/workspace.py` (early and post-precheck target compare);
  `app/routes/sessions.py` (pinned target wiring); `tests/test_merge_target_oracle_386.py`
  (`test_t386_t1_*`, immutable after RED commit).
- Test: `uv run --frozen python -m pytest -q tests/test_merge_target_oracle_386.py -k 'test_t386_t1_'`
  — committed RED in `b1af1b07`.
- RED assertion: `AssertionError: #386 missing behavior: tm.create_task lacks
  ['acceptance_actor', 'acceptance_manifest', 'acceptance_required']`.
- AC: the exact command is green and all 32 cases pass. Mechanically, it proves:
  - task revision/actor atomicity and worker/unauthorized/cross-project/create/update/clear/forged
    authority controls;
  - fresh/legacy/recreated schema preservation, malformed JSON refusal, and operation replay pinned
    to its original task revision/target;
  - complete target `tests/` tree/config expansion, manifest-narrowing refusal, committed and dirty
    byte/mode mutation refusal, and added `conftest.py`/pytest-config refusal before execution;
  - missing/`SKIPPED`/deselected-only/collection-error/timeout ticket outcomes never authorize;
  - explicit and base-branch target pinning before runner, nested pass, main partial-slice reject,
    independent mapped-regression reject, and candidate selector metadata ignored;
  - operation-level fail-closed composition for every oracle/mapped non-authorizing status with no
    executor call and structured refusal evidence;
  - stored target SHA reaches oracle, mapped gate, and merge execution after the branch moves;
  - early and post-precheck target moves reject without squash/cherry-pick/ref mutation;
  - matching target commits in the temp graph and records `matched=true`;
  - final-only main merge stays available with no ticket oracle when all mapped tests are green;
  - successful and refused terminal results retain target SHA, oracle source/revision/ref/hash/status,
    mapped files, and target recheck.
- blocked-by: none

## Compatibility and migration

- Existing tasks with only `acceptance_command` keep current optional acceptance behavior unless
  the server-derived nested-behavioral floor applies. They do not acquire a fabricated revision.
- Schema migration adds both JSON columns with `{}` defaults, preserves legacy rows, and changes
  the `tm_tasks` autoindex-repair path to named columns so a non-empty oracle bundle survives table
  recreation. Malformed non-empty JSON is fail-closed before operation runner creation.
- Existing main merges retain main-relative selection.
- Existing docs-only merges and final-only chains remain available.
- Existing merge operation replay returns the snapshot stored with that operation; it never mixes a
  newer task revision or target head into an older operation ID. An old operation row gains `{}`
  admission metadata without losing its identity/result.
- Do not change #380 branch refs, worktrees, tests, or task metadata during implementation.

## Not in scope

- Failure-set subtraction or baseline-result caching.
- Worker-provided selectors, markers, manifests, or merge metadata.
- General import-graph discovery outside the mandatory target `tests/` tree, explicit extra inputs,
  and protected pytest discovery/config filenames.
- Refactoring the current mapped-test policy, batching, live-probe policy, or diff budget.
- Deploy, restart, or live merge.

## Frozen RED evidence

Frozen oracle commit: `b1af1b07a19da73f5f62e14bafdd317ea743b0b8`.

Earlier RED commits `dd86a8f9`, `a2fd2d65`, and `47380a67` are superseded by review-driven
re-freezes and are excluded from implementation replay. The final test file is the only Phase-2
executable change. It collected cleanly; its one vertical-ticket command failed for missing behavior
rather than an import/collection error:

```text
$ uv run --frozen python -m pytest -q tests/test_merge_target_oracle_386.py -k 'test_t386_t1_'
exit 1
FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF [100%]
32 failed in 45.70s
AssertionError: #386 missing behavior: tm.create_task lacks
['acceptance_actor', 'acceptance_manifest', 'acceptance_required']
```

No `uv.lock` change occurred. Git objects/worktrees created by the tests lived only below pytest
`tmp_path`; no live merge or #380 mutation occurred.
