# #169 — Silent cross-project task mutation

## Question

- **Context:** task identity crosses MCP, FastAPI routes, SQLite task-manager helpers, worker/worktree lifecycle, Git commit linking, status transitions, and payments in a multi-project Orchestra instance where numeric `par` values repeat per project and legacy project ids may differ only by case.
- **Change under test:** canonicalize new project ids and make every read or mutation resolve a task only through an explicit project or an authoritative scope-derived project.
- **Baseline:** current code may derive a case-sensitive project from scope and then resolve a plain numeric task within it, while other callers may fall back to global numeric resolution.
- **Outcome:** an isolated database containing `Seedon#1/#2` and `seedon#1/#2` must never permit a read, write, commit link, status transition, merge follow-up, or payment operation to select the other namespace silently. New case-only namespaces must be rejected or reuse the existing canonical identity. Existing duplicate namespaces and their rows must remain unchanged.

## Hypotheses considered

### H1 — case-sensitive project creation is the primary duplicate-namespace cause

`api_create_task` loses authoritative scope on a scope conflict, and `ensure_project` compares project ids case-sensitively, so a case-only id can be inserted as a distinct namespace.

**Falsifier:** current schema or code already enforces case-insensitive uniqueness, or isolated reproduction cannot create both ids through the API helper.

### H2 — unsafe task resolution is broader than creation

Plain numeric references enter status, worker/worktree, merge-linking, commit-linking, or payment paths without an explicit project or authoritative scope, allowing a repeated `par` to resolve globally or under the wrong case-variant project.

**Falsifier:** a complete caller inventory shows every path supplies a verified project identity and all ambiguous/mismatched cases fail before any side effect.

### H3 — the observed wrong-target read is only a route-display defect

The task rows and mutation helpers are correctly isolated, but list/get formatting or scope mapping displays the wrong case-variant.

**Falsifier:** an isolated write through the same helper chain changes the wrong row, or a commit/payment link attaches to the wrong project task.

## Experiment protocol (defined before execution)

Use only a temporary/test SQLite database. Seed two projects, `Seedon` and `seedon`, each with `par` 1 and 2 and distinct marker fields. Exercise create/get/update plus every discovered link/status/payment caller.

Pass criteria:

1. Case-only project creation cannot add a third namespace or silently bind a conflicting scope.
2. Explicit project reads and writes affect exactly one marker row in that project.
3. A bare numeric reference without one authoritative project fails closed when duplicates exist.
4. Commit/worktree/worker/status/payment operations cannot attach a side effect to the other case-variant project.
5. The full entry-point inventory has no unclassified plain-number task resolver.

## Findings

### F1 — the duplicate namespace creation mechanism is reproduced

**CONFIRMED — current source plus isolated SQLite execution (evidence tiers 1 and 2).**

`tm_projects.id` is a binary `TEXT PRIMARY KEY`; there is no case-insensitive unique
constraint. `ensure_project()` tests `id = ?` exactly. `api_create_task()` detects that
the caller scope belongs to another exact id, but responds by setting `eff_scope=None`
and still creating/using the requested project. Thus a caller in the `seedon` scope that
passes `project="Seedon"` creates a second namespace rather than either reusing the
existing case-insensitive identity or rejecting the conflict [1][2].

Isolated execution on 2026-08-09 produced [E1]:

```text
created={par:"1", id:2, project:"Seedon"}
projects_after_case_only_create=
  Seedon prefix=SE1 scope=null
  seedon prefix=SEE scope=/isolated/seedon
```

The schema permits the pair and the API created it in one call. H1 is confirmed.

The same execution exposed a related prefix defect: `_generate_prefix()` resolves the
collision `SEE` as `SE1`, while `_parse_task_ref()` accepts letters only. The generated
reference failed as `ValueError: Cannot parse task ref: SE1-1` [2][E1]. This is not the
cross-write cause, but a cleanup/compatibility edge case.

The legacy-tolerant collision policy must distinguish explicit identity from an alias:

1. An exact explicit id that already exists remains addressable, even when another legacy
   case variant exists; this is the only non-migrating way to operate on either namespace.
2. With no exact match and exactly one casefold match, reuse the stored id rather than
   insert another spelling.
3. With no exact match and multiple casefold matches, fail as ambiguous; never choose one.
4. With no casefold match, create one deterministic canonical id for the new namespace.
5. Scope-only resolution continues to use the exact row bound to that scope. Existing ids
   are never renamed or merged by startup code.

Explicit project and authoritative scope are alternative authorities. This preserves the
existing supported cross-project `task_create(project=...)` workflow: when an explicit
project is supplied it selects that project, while scope is only eligible to bind a newly
created project if the scope is not already owned. API responses must return the resolved
stored project id so the caller can use the same authority for get/update.

### F2 — the public MCP/API identity contract splits list from get/update

**CONFIRMED — current source and isolated execution (evidence tiers 1 and 2).**

- MCP `task_list(project=...)` sends the explicit project and omits scope. The list route
  honors it exactly [3][4].
- MCP `task_get(par)` and `task_update(par, ...)` have no project argument. They always
  send `SCOPE`; the routes convert that scope to a project id [3][4].
- Therefore `task_list(project="Seedon")` returns `Seedon#1`, but subsequent
  `task_get("1")`/`task_update("1")` from scope `/home/kesha/projects/seedon` select
  `seedon#1`. This is a contract-level identity switch, not a display-only defect.

The isolated route-equivalent helper chain returned [E1]:

```text
scope_resolves_to=seedon
scoped_get={project:"seedon", par:"1", title:"LOWER ORIGINAL"}
scoped_update.updated=["title"]
after: seedon#1.title="LOWER MUTATED THROUGH SCOPED PUT"
       Seedon#1.title="UPPER CREATED"
```

H3 is refuted: the wrong row is mutated.

The raw HTTP helpers have a second unsafe mode. If both project and scope are absent,
`resolve_task_ref()` performs a global search. It rejects an already duplicated number,
but accepts and mutates a number that happens to be globally unique. An isolated `#99`
changed title with neither project nor scope [E4]. Mutation identity therefore depends
on unrelated future rows and is not fail-closed [2][3].

### F3 — ambiguity protection exists, but callers bypass it by supplying the wrong project

**CONFIRMED — current source plus isolated SQLite execution (evidence tiers 1 and 2).**

`get_task_by_par()` without a project loads two rows and raises when more than one exists.
In the duplicate fixture it raised verbatim [2][E1]:

```text
ValueError: Ambiguous task #1 — exists in projects: seedon, Seedon. Use project filter.
```

However, scope-based routes first resolve `/isolated/seedon` to exact project `seedon`
and pass that value into `resolve_task_ref()`. This intentionally narrows the query and
therefore bypasses the global ambiguity guard. The guard is correct for an unqualified
lookup, but it cannot detect that the caller obtained `#1` from an explicit `Seedon`
list. H2 is confirmed for the MCP/API read/update chain [2][3][4].

When a legacy prefixed ref is used, `resolve_task_ref(ref, project_id)` ignores the passed
project and lets the prefix select another project. After assigning the fixture's upper
project a parseable prefix `UPR`, both the link helper and the public update helper wrote
the upper task despite an explicit lower project [E1][E6]:

```text
link_commits_to_task("UPR-1", ..., project_id="seedon")
  -> {ok:true, added:1, task_id:2}  # task_id 2 belongs to Seedon
api_update_task("UPR-1", ..., project="seedon")
  -> Seedon task id 2 title changed; seedon task id 1 unchanged
```

Thus an explicit project currently constrains plain refs but not prefixed legacy refs.

### F4 — worker status paths are scope-pinned and CAS-protected, with one scope-drift hole

**CONFIRMED for spawn/switch/merge-next; LIKELY risk for scope migration — current source,
prior direct measurements, and isolated execution (evidence tiers 1 and 2).**

The normal worker lifecycle is already safer than the task MCP endpoints:

- spawn resolves `task_id` through `resolve_scoped_task_identity(session.scope, ref)`
  before worktree creation and later updates by immutable DB id/project/par/revision;
- explicit branch switch and merge `next_task_id` use the same scope resolver and
  conditional update;
- missing/unmapped scope and mismatched prefix fail before Git [2][5].

Task #93 measured that task ownership follows caller `session.scope`, not `repo_path`:
6/8 live cross-repo task sessions existed only in the caller-scope project, none only in
the repo project. The present task must preserve that decision; a worker's Git repository
is not its task namespace [8].

The remaining drift hole is `db.change_scope()`. On a `tm_projects.scope` collision it
deliberately moves the session while leaving both project mappings in place and preserves
the session's plain `task_id`. The existing test requires this behavior [7]. In an isolated
two-project fixture, the same stored plain ref changed identity [E3]:

```text
before: scope=/isolated/old, task_id="1" -> task db id=1, project=old-project
change_scope -> {ok:true, tm_project_migrated:false}
after:  scope=/isolated/new, task_id="1" -> task db id=2, project=new-project
```

This is not on the routine worker spawn path and `change_scope` requires an idle,
worker-free orchestrator. It is still an identity transition that must either reject the
project collision or clear/revalidate the stored task association before the new scope is
published.

### F5 — current merge commit linking is worker-project scoped; its lower-level helper is not fail-closed

**CONFIRMED — current source plus isolated helper execution (evidence tiers 1 and 2).**

`workspace._parse_merged_commits()` extracts refs from the commits. After Git succeeds,
`execute_merge_session()` resolves the worker row's scope to `project_id` and passes that
id to every `link_commits_to_task()` call. If the scope has no project it records a failed
link and performs no task write [5][6]. Both normal squash and the unrelated-history
cherry-pick fallback rebuild the final subject with `_build_squash_message()`, which
normalizes discovered prefixes to `#N`. The current merge path is therefore constrained
to the worker's scope project [6].

Two holes remain:

1. `link_commits_to_task()` permits an empty project and falls back to global resolution.
   It is public Python API and existing tests call it that way; a globally unique number
   can therefore be linked without authoritative project context [2]. No production app
   caller currently omits the project.
2. A parseable legacy prefix overrides a non-empty `project_id`, demonstrated in F3.
   This bypass is reachable through task get/update, but the current merge builders
   normalize it away before link dispatch.

The current merge route is not a demonstrated cross-link. The lower-level contract is
still unsafe and should be tightened at `resolve_task_ref`/`link_commits_to_task`: when an
authoritative project is passed, both plain and prefixed refs must resolve inside it or
fail, and mutation/link helpers must not accept missing authority. Merge tests must prove
that the existing worker-project restriction remains true when both projects have the
same `par`.

### F6 — direct payments are client-project scoped, but wrong task resolution can trigger a wrong-project allocation

**CONFIRMED — current source plus isolated SQLite execution (evidence tiers 1 and 2).**

Direct receive/status/history paths resolve an explicit client id or derive a client from
scope. Allocation SQL always filters tasks through `tm_clients.project_id`; it never
resolves a task by plain `par`. Once the correct client is selected, equal task numbers in
another project cannot receive that payment [2][3]. An explicitly supplied client wins
over scope, which is an explicit cross-project identity rather than a silent numeric
selection; this policy should remain explicit in the API response/tests.

There is nevertheless a payment-impacting cross-write: `api_update_task(status="done")`
resolves the task first and then calls `auto_deduct_prepayment(task_id)`. In the duplicate
fixture, 70 units of prepayment belonging to lower `seedon` were allocated when an
upper-task-intended plain `#1` update was routed through lower scope [E2]:

```text
Seedon#1: status=new, paid_rub=0       # unchanged
seedon#1: status=done, paid_rub=70     # wrong selected task
allocation: payment_id=1, task_id=1, amount_rub=70
```

Fixing task identity before mutation prevents this indirect financial side effect. Direct
payment SQL does not need a numeric-task resolver rewrite.

### F7 — live legacy duplicates are broader than the reported Seedon pair and cannot be safely inferred from `par`

**CONFIRMED — live SQLite opened with `sqlite3 -readonly` on 2026-08-09 (evidence tier 1).**

No live write was executed. The database contains two case-variant groups [E5]:

```text
canonical_key  variants  ids
orchestra      2         Orchestra | orchestra
seedon         2         Seedon | seedon

duplicate pars:
Orchestra/orchestra: 1
Seedon/seedon:        2
```

For Seedon, lowercase `seedon` owns scope `/home/kesha/projects/seedon`; uppercase
`Seedon` has no scope. The upper rows have ids 188/189, `sync_revision=0`, no commits,
no payment allocations, and no `worker_session_id`. That reduces cleanup risk but does
not prove deletion is correct [E5]. In particular, the same-number rows are unrelated:

```text
Seedon#1 = "Демо AI-диспетчера для GROOM"
seedon#1 = "Посадочная /ai-dispetcher/: убрать гигантские иллюстрации..."
Seedon#2 = "Проверить ИТ-отсрочку и уведомления военкомата"
seedon#2 = "Требование СФР №240126032309..."
```

Upper `Seedon#2` has the same title as lowercase `seedon#102`, while `Seedon#1` has no
exact-title match in the query. These are leads for human cleanup, not sufficient proof
for automatic migration or deletion. The code fix must tolerate these rows in place.

### F8 — ancillary paths are either internal-id safe or fail loudly

**CONFIRMED — current source and live configuration (evidence tiers 1 and 2).**

- YouGile runtime sync receives the global integer `tm_tasks.id` after the task mutation;
  it does not re-resolve a SQLite task by `par`. The historical import script does call
  `get_task_by_par(par)` globally, but duplicate numbers raise rather than silently select.
- Usage analytics joins `turn_usage.scope` to `tm_projects.scope` and then matches the
  plain task number. Scope-less legacy uppercase projects therefore do not steal costs
  from the lowercase scoped project.
- All live `tm_projects` rows currently have `yougile_enabled=0`; the external mirror is
  not an active path for the reported case [E5].

These are not blocking changes for #169, but the YouGile import should use its explicit
`PROJECT_ID` if it is maintained in future.

## Complete identity/path map

| Operation | Entry path | Current authority | Result with `Seedon`/`seedon` duplicate |
|---|---|---|---|
| create | MCP `task_create` → POST `/api/tm/tasks` → `api_create_task` | explicit `project`; scope is opportunistic binding | creates a case-only namespace after dropping conflicting scope — unsafe |
| list | MCP/HTTP GET `/api/tm/tasks` | explicit project wins; else scope | exact explicit `Seedon` and scoped `seedon` return different lists |
| get | MCP `task_get` → GET `/tasks/{par}` | scope only in MCP; global fallback in raw API | selects scoped lowercase row; unqualified duplicate fails, unqualified unique succeeds |
| update | MCP `task_update` → PUT `/tasks/{par}` → `api_update_task` | scope only in MCP; global fallback in raw API | can mutate unrelated lowercase row; `done` may also allocate prepayment |
| spawn worker | `spawn_worker` → session create → manager | authoritative caller/session scope | scope-pinned identity + revision CAS; no global fallback |
| switch worker | `switch_worker_branch` → session route | worker's persisted scope | scope-pinned identity + CAS; safe unless scope identity itself drifted |
| merge + next | durable merge op → `execute_merge_session` | pinned worker row scope | next task is prevalidated before Git and CAS-updated after switch |
| Git commit link | workspace commit parser → merge route → `link_commits_to_task` | worker row scope project is passed | current merge path is safe and normalizes to plain refs; lower-level empty/prefixed helper contracts are unsafe |
| payment receive/status/history | payment MCP/route → client → project-filtered SQL | explicit client or client derived from scope | no numeric ambiguity; wrong task update can indirectly allocate prepayment |
| scope migration | change-scope route → `db.change_scope` | target scope after move | preserved plain task id can silently change project on target-scope collision |
| dashboard | scope list + scope detail | current selected scope | internally consistent; does not reproduce explicit-list/MCP split |

## Safe cleanup proposal (separate from the code fix)

Do not put cleanup into startup schema migration and do not update the live `Seedon`
rows as part of #169. After the code fix is deployed:

1. Take a consistent SQLite backup with `sqlite3.Connection.backup` (not `cp`, because
   live WAL pages may contain current rows).
2. Run a read-only/dry-run audit that emits every casefold group and, per task, all foreign
   references: sessions, `git_commits`, payment allocations, sync log, YouGile id, matching
   title/description, repository `docs/tasks`, branch/commit references, and agent-message
   provenance.
3. Produce a human-approved mapping ledger keyed by immutable source task DB id. Equal
   `par` is explicitly not evidence. Each row must choose one action: keep as distinct,
   map to a proven existing canonical task, or move to the canonical project under a new
   non-conflicting `par`.
4. Apply only that ledger in one explicit maintenance transaction after another backup.
   Preserve a before snapshot, rewrite all dependent foreign keys/metadata, run
   `PRAGMA foreign_key_check`, payment sanity checks, and row-count/hash comparisons, then
   remove a legacy project only if it is proven empty.
5. Dry-run output and the approved ledger belong in a later cleanup task. The code fix
   must work while `Seedon`/`seedon` and `Orchestra`/`orchestra` still coexist.

## Counter-evidence

- Global bare-number resolution already fails when the same `par` exists in at least two
  projects. The defect is not “always take first row”; it is lost/mismatched authority
  before the resolver, plus prefixed refs overriding passed authority [2][E1].
- Spawn, switch, and merge-next were hardened in #93 with scope-derived immutable task
  identity and revision CAS. Replacing their authority with `repo_path` would regress a
  measured cross-repository workflow [5][8].
- Merge commit linking already supplies the worker scope's project for the normal path,
  missing project is surfaced as a failed link, and both merge strategies normalize
  prefixes to `#N`. No current merge cross-link was reproduced. The fix should tighten
  the common resolver and preserve this invariant, not redesign merge orchestration [5][6].
- Payment allocation SQL is already project-bounded through a client. No isolated direct
  payment crossed from the selected client's project to another project's equal `par`
  [2][E2].
- The live upper Seedon rows currently have no linked commits, payments, worker ids, or
  sync revisions. This makes a later cleanup plausible, but title evidence is incomplete
  and does not justify automatic deletion [E5].

## Affected files, risks, and edge cases

### Blocking code surface

- `app/tm.py` — canonical/casefold project lookup; creation conflict handling; resolver
  contract requiring an explicit project for mutations; prefixed-ref/project consistency;
  commit-link enforcement.
- `app/routes/tm.py` — accept explicit project for get/update; require explicit project or
  a mapped authoritative scope; ensure list/get/update share one identity rule.
- `app/mcp_stdio.py` — add optional explicit project to `task_get`/`task_update` and pass it
  consistently; keep scope fallback when project is absent.
- `app/db.py` — prevent new case-only project ids without rewriting legacy rows; reject or
  quarantine scope moves that would change task authority.
- `app/routes/sessions.py` — likely no production rewrite beyond using the tightened link
  helper, but integration tests must prove worker-scope commit linking and next-task status.

### Tests required in later phases

- `tests/test_tm.py`: legacy `Seedon`/`seedon` fixture; create canonicalization; explicit
  exact project; ambiguous casefold alias; global-unqualified mutation rejection; prefixed
  ref cannot escape a passed project; direct payment stays client-project scoped.
- `tests/test_api.py`: list/get/update identity continuity; missing identity fails before
  mutation; spawn/switch/merge-next with duplicate `par`; commit link attaches only to the
  worker-scope project; scope-change collision does not retain a drifting task association.
- `tests/test_mcp_stdio.py`: `project` propagation on get/update and scope fallback.
- `tests/test_db.py`: new project-case guard with legacy duplicates already present, plus
  scope migration behavior.

Mutation checks must remove each load-bearing constraint separately: exact-only project
lookup, explicit project propagation, prefix/project validation, and worker project passed
to commit linking. Each fixture must give the competing project the same `par` and distinct
markers so no fallback clue can keep the test green.

### Compatibility and risk

- Existing case-variant ids must remain addressable by exact explicit id or exact scope.
  A non-exact case-insensitive alias that matches more than one legacy id must fail as
  ambiguous; silently choosing either would violate the task.
- A case-insensitive unique index cannot be installed directly while the live duplicates
  exist. The guard must be additive and legacy-tolerant (application lookup and/or an
  insert trigger), with no automatic row rewrite.
- Raw HTTP clients that omitted both project and scope will change from “works while number
  is globally unique” to a 4xx. That is the intended fail-closed compatibility break.
- MCP/Python runtime changes touch shared identity paths and require Codex implementation
  review plus isolated DB/API/merge mutation tests before merge.

## Baseline regression check

The targeted current-code suite remained green after the investigation [E7]:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_tm.py tests/test_manager.py tests/test_api.py \
  -k 'task_identity or task_assignment or duplicate_task or same_par or merge_revision_change or switch_persistence or switch_failure'
..........                                                               [100%]
10 passed, 269 deselected in 7.33s
```

This is counter-evidence against a blanket claim that all lifecycle paths are unsafe; it
does not cover the reproduced case-variant MCP contract and therefore does not refute F1-F3/F6.

## Sources

1. **[Primary source, tier 2]** `app/db.py:132-190` — task/project/client/payment schema;
   `tm_projects.id` binary primary key and exact unique scope.
2. **[Primary source, tier 2]** `app/tm.py:49-154, 292-407, 436-651, 840-1081` — project
   creation, task resolution/mutation/linking, and payment implementation.
3. **[Primary source, tier 2]** `app/routes/tm.py:15-154` — public task/payment HTTP
   request models and scope/project/client resolution.
4. **[Primary source, tier 2]** `app/mcp_stdio.py:1605-1705` — MCP task/payment parameter
   propagation.
5. **[Primary source, tier 2]** `app/manager.py:641-647, 762-790` and
   `app/routes/sessions.py:856-1168, 1208-1378` — worker task prevalidation, merge, switch,
   status update, and commit-link call sites.
6. **[Primary source, tier 2]** `app/workspace.py:864-893, 1489-1546` and
   `app/merge_operations.py:949-1000, 1058-1128` — commit-ref extraction and durable merge
   execution.
7. **[Primary source, tier 2]** `app/db.py:814-859` and `tests/test_db.py:1059-1074` —
   current scope-collision migration contract.
8. **[Prior direct measurement, tier 1; rechecked against current code]**
   `docs/tasks/93/research.md:233-259`, `docs/tasks/93/report.md:9-16` — caller scope is the
   authoritative task project and task updates are CAS-pinned.
9. **[E1, direct measurement, tier 1]** isolated temporary DB, current code, 2026-08-09:
   case-only create; scoped get/update; global ambiguity; prefixed commit-link escape; explicit
   client selection. Raw distinguishing outputs are quoted in F1-F3.
10. **[E2, direct measurement, tier 1]** isolated temporary DB, current code, 2026-08-09:
    wrong scoped `status=done` selected lower task and allocated 70 units of lower-project
    prepayment; raw rows quoted in F6.
11. **[E3, direct measurement, tier 1]** isolated temporary DB, current code, 2026-08-09:
    `change_scope` collision changed stored plain `#1` identity from task id 1/project old to
    task id 2/project new.
12. **[E4, direct measurement, tier 1]** isolated temporary DB, current code, 2026-08-09:
    unqualified globally unique `#99` was read and mutated successfully.
13. **[E5, direct measurement, tier 1]** live `/home/kesha/orchestra/data/orchestra.db`
    opened only with `sqlite3 -readonly`, 2026-08-09: two casefold duplicate project groups,
    three same-`par` collisions total, and no side effects on upper `Seedon` tasks. No live
    PUT/POST or SQLite write was performed.
14. **[E6, direct measurement, tier 1]** isolated temporary DB, current code, 2026-08-09:
    `api_update_task("UPR-1", project="seedon")` changed only the upper `Seedon` task,
    proving that a parseable prefix overrides an explicit project in the public mutation
    helper.
15. **[E7, direct measurement, tier 1]** targeted current-code pytest run, 2026-08-09:
    `10 passed, 269 deselected in 7.33s`; exact command and output are recorded above.
