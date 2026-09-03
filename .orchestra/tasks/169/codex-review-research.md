# #169 — adversarial research self-review

## Status

**external verdict unavailable**

The required external `codex_review` attempt did not start a Sol review. Exact gate error:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy). Stop/model change remain available.
```

No quota bypass, Claude fallback, production restart, or second external model was used.
The findings below are a strict adversarial self-review of the code/path map and isolated
measurements. They are **not** a Codex approval or external verdict.

## Material checked

- `docs/tasks/169/research.md`
- project creation and task resolution in `app/tm.py`/`app/db.py`
- task/payment HTTP and MCP parameter propagation
- worker spawn/switch/merge-next identity pinning
- both merge strategies and commit-ref normalization
- isolated `Seedon`/`seedon` create/get/update/link/status/payment reproductions
- live SQLite read-only duplicate/foreign-reference inventory

## Findings

### R1

`blocking: research F5 — the first draft overstated prefixed commit-link reachability.`

Both normal squash and unrelated-history cherry-pick build the final commit subject with
`_build_squash_message()`, which normalizes prefix refs to `#N`. The only production
`link_commits_to_task()` caller passes the worker scope project. Therefore no current merge
cross-link was reproduced. The lower-level resolver still permits an empty project and
lets a parseable prefix override a supplied project, but the prefix bypass is presently
reachable through task get/update rather than the merge builder.

**Resolution:** corrected F3/F5, the path map, counter-evidence, and conclusions. The
research now says current merge linking is project-scoped and requires preservation tests;
it does not claim a live merge exploit.

### R2

`blocking: canonicalization policy — blindly casefolding every lookup would silently merge legacy namespaces.`

A fix that always returns the first case-insensitive match would violate the explicit
requirement not to merge existing `Seedon`/`seedon`. A direct case-insensitive unique index
also cannot be installed while live duplicates exist.

**Resolution:** research now specifies a legacy-tolerant policy: exact explicit id remains
exact; a sole non-exact casefold match reuses the stored id; multiple non-exact matches fail
ambiguous; only genuinely new ids are stored canonically; scope lookup remains exact. No
startup rewrite is allowed.

### R3

`blocking: payment impact — distinguish direct payment routing from status-triggered allocation.`

Direct payment allocation selects tasks through the explicit/derived client's
`project_id`; equal `par` in another project cannot receive it. The reproduced financial
cross-write occurs after the wrong task is selected by `api_update_task(...status="done")`,
which then calls `auto_deduct_prepayment()` for that internal task id. An explicit client
that differs from scope is explicit cross-project authority, not a silent numeric choice.

**Resolution:** research makes this distinction and does not propose rewriting allocation
SQL. Later tests must cover both: direct payment stays within client project, while a task
mutation cannot select the foreign same-`par` row and trigger prepayment there.

### R4

`blocking: status paths — do not regress the scope-pinned CAS lifecycle introduced by #93.`

Spawn, switch, and merge-next resolve through `session.scope`, capture immutable DB task
id/project/par/revision, and conditionally update after their lifecycle commit points.
`repo_path` is intentionally not task authority. Their normal status path does not use the
unsafe global resolver.

**Resolution:** the proposed surface is additive: preserve these paths, test them with
case-variant duplicate pars, and tighten shared task/link helpers without moving authority
to the worker repository.

### R5

`suggestion: change_scope is a real identity-drift reproducer but adjacent to the reported MCP split.`

On a target project-scope collision, `change_scope()` deliberately moves the session and
preserves plain `task_id`; the same ref then resolves to the target project's task. This is
measured, but scope change is an explicit orchestrator relocation and is not the source of
the live `task_list(project)`/scoped-get mismatch.

**Disposition:** keep it as an affected edge/risk. Phase 2 should choose the smallest
fail-closed behavior (reject the project collision or clear/revalidate task association),
not redesign scope migration.

### R6

`blocking: existing Seedon rows — absence of foreign references is not proof of safe deletion.`

The read-only snapshot showed upper task ids 188/189 with revision 0 and no commits,
payment allocations, worker session, or sync rows. Yet same-number lowercase tasks are
unrelated, and title matching is incomplete. Live state can also change after the snapshot.

**Resolution:** no automatic cleanup. Code fix first; later cleanup starts from a
`sqlite3.Connection.backup`, re-audits under maintenance control, uses a human-approved
mapping keyed by immutable DB id, and verifies every dependent reference. `Seedon` rows
remain untouched in #169.

### R7

`question: should explicit project conflict with caller scope be rejected?`

Existing MCP design intentionally allows cross-project `task_create(project=...)`, while
scope is used as a fallback/binding hint. Requiring project to equal scope would break that
supported workflow and contradict #93 cross-repository measurements.

**Disposition:** explicit project and authoritative scope are alternative identities.
Explicit project wins when supplied and the resolved stored project id is returned;
scope-only operations use the bound project. Missing authority and non-exact aliases that
match multiple legacy variants fail closed.

### R8

`suggestion: generated prefixes containing digits are unparseable, but this is not the #169 cross-write cause.`

The duplicate-create fixture generated `SE1`, while task-ref parsers accept only letters.
This should be kept as an edge case or fixed incidentally only if the project resolver work
touches prefix generation. It must not expand Phase 3 into a prefix redesign.

## Self-review disposition

After correcting R1 and making R2/R3/R4/R6 explicit, no unresolved contradiction remains
in the Phase 1 conclusions:

- case-sensitive create behavior is reproduced;
- list/get/update authority mismatch and wrong-row mutation are reproduced;
- status-triggered wrong-project prepayment is reproduced;
- current worker lifecycle and merge linking are scope-project constrained and must remain so;
- lower-level prefix/missing-project helpers are not fail-closed;
- existing legacy rows require a separate evidence-led cleanup.

This disposition is a self-review result only. **External Sol/Codex verdict remains
unavailable.**
