## Summary

Focused tests passed:

`pytest -q tests/test_tm.py tests/test_api.py::TestTaskProjectIdentity tests/test_mcp_stdio.py::test_task_create_omits_project_to_use_callers_scope tests/test_mcp_stdio.py::test_task_create_returns_fields_needed_by_dashboard_card`

Result: `33 passed in 25.35s`

The transaction correctly uses `BEGIN IMMEDIATE`, validates and inserts through the same connection, and rolls back on failure. Legacy unscoped rows remain readable and updatable. One silent project-misrouting case remains.

## Findings

blocking: [app/tm.py:882] Explicit project IDs can be silently interpreted as another project’s scope.

`get_project_by_scope(conn, project_id)` runs before `resolve_project_id(conn, project_id)`. If one registered project’s ID equals another project’s scope, `task_create(project=...)` creates the task under the scope owner, while `task_get` and `task_update` interpret the same value as the exact project ID through `_resolve_task_project_id`. This breaks the stated “scope or id” contract and can silently associate a task with the wrong project. Exact ID and scope matches should either be disambiguated explicitly or an ambiguous token should fail closed. Add a collision test covering create, get, and update consistency.

suggestion: [tests/test_mcp_stdio.py:451] The mixed-version safety claim is not regression-tested.

The test proves that new MCP omits `project`, but not that the old required-field route rejects that payload before calling `api_create_task`. The report’s HTTP 422 reasoning is sound from the diff, but a narrow compatibility test using the former required `TmTaskCreate.project` schema would lock down the “no blank ghost under new-MCP/old-route” contract.

## Verdict

CHANGES REQUESTED — one blocking silent misrouting hazard.

## Round (2026-08-13T06:51:39Z)

## Summary

Round 1 fixes are correct. Focused re-review found no new blocking or suggestion-level issues.

Test command:

`pytest -q tests/test_tm.py tests/test_api.py::TestTaskProjectIdentity tests/test_mcp_stdio.py::test_task_create_omits_project_to_use_callers_scope tests/test_mcp_stdio.py::test_task_create_returns_fields_needed_by_dashboard_card tests/test_mcp_stdio.py::test_task_get_and_update_prefer_explicit_project_over_scope`

Result: `35 passed in 34.40s`

## Findings

- FIXED — blocking: ID/scope collisions now use `resolve_project_selector` consistently and fail closed across create, list, get, and update. The behavioral test verifies no creation or mutation occurs.
- FIXED — suggestion: the captured new-MCP payload is validated against the former required-project schema and raises `ValidationError` before handler execution.
- No new findings.

## Verdict

APPROVED.
