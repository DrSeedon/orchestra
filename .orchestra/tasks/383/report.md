#383 — acceptance command recovery through `task_update`

## Implementation

- `app/tm.py`: `update_task` and `api_update_task` accept an optional
  `acceptance_command`, normalize it, update it in the existing transaction, and report the field
  in `updated`. An acceptance-only change returns only `par`, `project`, and `updated`; combined
  status/price updates retain their established metadata.
- `app/routes/tm.py`: REST update accepts a non-empty command. Omitted, empty, or whitespace-only
  text remains an omission for compatibility. `clear_acceptance_command=true` is the explicit
  clear operation and is mutually exclusive with a non-empty replacement.
- Privileged REST updates derive the project from the proof-bound MCP session scope and reject
  mismatched explicit `project` or `scope` selectors. Dashboard-cookie calls retain their existing
  project/scope resolution.
- `app/mcp_stdio.py`: MCP exposes the same replacement/clear contract and keeps the existing
  orchestrator-only acceptance privilege used by `task_create`.
- The route and MCP layers do not issue SQLite statements; they use `api_update_task` →
  `update_task`. No live DB mutation, deploy, or restart was performed.

## Clearing contract

`acceptance_command=""` remains “not provided,” matching the existing MCP convention for text
fields and protecting old callers. Clearing requires the separate boolean
`clear_acceptance_command=true`. A request cannot both clear and provide a non-empty replacement.

## Final acceptance evidence

- `uv run pytest -q tests/test_tm.py tests/test_acceptance.py tests/test_mcp_proof.py`
  → `46 passed in 38.61s`.
- `uv run pytest -q tests/test_mcp_stdio.py tests/test_merge_test_gate.py tests/test_routes_surface.py`
  → `129 passed in 20.61s`.
- Focused post-review command covering all new cases
  → `11 passed in 11.96s`.
- Reviewer-owned command:
  `uv run pytest -q tests/test_mcp_proof.py tests/test_tm.py -k 'acceptance_command or proof'`
  → `13 passed, 23 deselected in 11.61s`.
- `uv run python -m compileall -q app/routes/tm.py app/tm.py app/mcp_stdio.py`
  and `git diff --check` → exit 0.
- `ruff` was unavailable in the environment (`Failed to spawn: ruff`).

Coverage maps to every requested AC: REST/MCP replacement, omission stability, explicit clearing,
one revision/timestamp transition, minimal acceptance-only response, combined-response compatibility,
invalid-create → public-update → merge resolver correction, task/scope rejection, proof-bound project
authorization, and the existing merge/route suites.

## Review decision gate

- Changed files/consumers: `app/routes/tm.py` (REST clients), `app/tm.py` (task API and YouGile sync
  trigger), `app/mcp_stdio.py` (MCP callers), focused task/MCP/proof/merge tests, and this report.
- Author model/runtime: `gpt-5.6-sol` on Codex runtime, from the live agent registry.
- Named AC: all bullet points in the task request, including scope rejection, resolver use, and
  omission-safe clearing.
- Oracle: exact commands and observed outputs above. The new tests are deterministic but were added
  with the implementation, so they are not an independent pre-existing oracle.
- Route: direct Sol review. The externally consumed REST/MCP contract and merge-acceptance control
  set the high-risk floor. Reviewer and author use the same model family, so model-level independence
  was unavailable; the review used a fresh bounded session, then a same-session evidence-backed
  follow-up after fixes.

## Pre-mortem / self-review

- Legacy empty strings erase a command → omission tests prove command, revision, and timestamp stay
  unchanged; explicit clear is a separate boolean.
- Duplicate task numbers allow a cross-project acceptance rewrite → core scope tests and the real
  proof-bound foreign-project test prove rejection with unchanged command/revision.
- One logical replacement increments twice or leaves time stale → core test asserts exactly
  `sync_revision + 1` and changed `updated_at`.
- Merge recovery evaluates the stale invalid command → integration starts with a failing command,
  updates through the public route, and observes the corrected passing command in the resolver.
- A worker or spoofed session weakens acceptance → MCP-role and MCP-proof tests reject both paths.
- Acceptance-only responses leak command/task data, or combined updates lose existing status fields
  → exact-key and combined-response tests cover both directions.

## Codex implementation review

Round 1 returned one blocking project-boundary finding and one combined-response suggestion. The
wrapper labeled the job failed because that response lacked a `## Verdict` section and separately
failed zero-token accounting; the substantive review and cited code were present, so the round
counts. Both findings were verified and fixed. Round 2 independently ran 13 focused tests, marked
P1/P2 fixed, found no new bug, and returned `APPROVED`.

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

The changed line `params = {"project": project} if project else ({"scope": SCOPE} if SCOPE else None)` leaves a merge-gate authorization bypass across project scope. Combined updates also break the existing response contract.

Full review comments:

- [P1] Bind acceptance updates to the caller's project — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-task-acceptance-update/app/mcp_stdio.py:2093-2094
  blocking: `app/mcp_stdio.py:2093` — `params = {"project": project} if project else ({"scope": SCOPE} if SCOPE else None)` lets an orchestrator supply any project, and the REST route resolves that caller-controlled selector without binding it to the authenticated MCP proof. When task numbers and a project name are known, this permits changing another project's merge acceptance command, violating the required project boundary; derive or validate the project against the caller's authoritative scope.

- [P2] Preserve status metadata for combined updates — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-task-acceptance-update/app/tm.py:1015-1016
  suggestion: `app/tm.py:1015` — `if "acceptance_command" in result["changed"]:` returns the minimal acceptance-only response even when the same request also changes status or price. Existing callers performing a combined update then lose the established `old_status`, `new_status`, `price_rub`, and `paid_rub` fields, despite those values being related to their requested changes; use the minimal response only when acceptance_command is the sole changed field.

> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens

## Round (2026-08-23T17:29:36Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- P1 — FIXED. Acceptance updates derive the project from the proof-bound session scope and reject mismatched explicit selectors.
- P2 — FIXED. Minimal responses are limited to acceptance-only changes; combined updates retain status/payment metadata.
- NEW BUG — None found.

Focused tests: `13 passed, 23 deselected in 11.61s`.

Evidence from changed code: `caller_scope = str((caller or {}).get("scope") or "").strip()`

## Verdict

APPROVED.
