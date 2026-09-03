# #332 Phase 2 plan — remove one confirmed unreachable JS helper

## Scope and decision

The only planned production change is removing the obsolete 12-line
`deleteOrchestrator` function from `app/static/js/app.js:1646-1657`. The surviving production
UX is `initTabContextMenu` → `openDeleteOrchModal(name, scope)` → `#delete-orch-confirm`,
which issues `DELETE /api/orchestrators/{name}` and reloads the orchestrator list. The route,
template modal, and surviving helper are not being changed.

Proxy scripts remain UNKNOWN/KEEP for this plan and are out of scope. No model/review call is
made, per the explicit user instruction. The main checkout has unrelated image-history work in
the same `app.js`; Phase 3 must coordinate the one-line-range removal against that work before
touching production code.

## Files

Planned implementation file (Phase 3 only):

- `app/static/js/app.js` — delete only `deleteOrchestrator` at lines 1646-1657.

Frozen acceptance oracle (already committed, immutable):

- `docs/tasks/332/acceptance/test_t1_delete_orchestrator_dead_code.py`.

Do not touch: `app/routes/system.py`, `app/templates/dashboard.html`, proxy scripts, tests or
test configuration outside the named acceptance oracle, pipelines, unrelated image-history code,
or any runtime/provider files.

## Tickets

### T1 — Remove unreachable `deleteOrchestrator` helper

- Files: `app/static/js/app.js:1646-1657` only; acceptance oracle at
  `docs/tasks/332/acceptance/test_t1_delete_orchestrator_dead_code.py`.
- Test: `python3 -m pytest -q docs/tasks/332/acceptance/test_t1_delete_orchestrator_dead_code.py`
  — committed RED in `d79b3f96` (`#332: freeze deleteOrchestrator red oracle`).
- AC: the named command is green after the 12-line function is removed. It must prove all of:
  - production JS/templates contain no direct `deleteOrchestrator` caller, DOM/event handler,
    fetch reference, or string-dispatch name;
  - the current deletion UX remains wired through `openDeleteOrchModal`, the delete modal, and
    the `/api/orchestrators/${name}` DELETE request;
  - a compound mutant using `window['delete' + 'Orchestrator']`, a computed property, or a
    string-dispatch map is rejected by the same absence oracle;
  - all five normal dashboard JS assets parse with `node --check`, load in the existing order,
    and template inline handlers resolve to definitions.
- RED observed after commit `d79b3f96`: `F..`, `1 failed, 2 passed`; first failing assertion:
  `AssertionError: legacy deleteOrchestrator must have no production declaration/caller/string`
  at `docs/tasks/332/acceptance/test_t1_delete_orchestrator_dead_code.py:32`.
- Positive control: `initTabContextMenu` calls `openDeleteOrchModal(name, scope)`;
  `#delete-orch-confirm` remains in `dashboard.html`; the helper retains the DELETE request
  and `loadOrchestrators()` path.
- Compound-control probe (scratch strings, no production mutation): direct declaration,
  computed property (`window['delete' + 'Orchestrator']`), and string-dispatch map were all
  reported `CAUGHT`; output `COMPOUND_MUTATION_CONTROLS_OK`.
- blocked-by: none.

## Review/verification gate

Review is skipped because the user explicitly prohibited model/review calls. The plan relies on
the frozen named RED oracle, its two green positive/smoke controls, and the independent scratch
compound-mutation control. No implementation or plan review artifact is claimed.
