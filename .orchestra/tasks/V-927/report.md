# V-927 — temporary rules with auto-expiry

## What was built
- `app/temp_rules.py` — storage (SQLite table `temp_rules`, created lazily), rights, prompt block, notices.
- `app/routes/temp_rules.py` — `/api/temp-rules` (backend of the MCP tools; no dashboard UI, per owner).
- MCP tools (orchestrators only): `temp_rule_set`, `temp_rule_list`, `temp_rule_update`, `temp_rule_remove`.
- Prompt: block `<temporary-rules>` is appended last by `assemble_prompt` (after worker memory), rules sorted by `created_at, id`.
- Live sessions: `AgentSession.send` compares the block fingerprint every turn; a change re-uses the existing "role instructions were updated" injection (adds and removals/expiry alike).
- Expiry: `on_expire=remove` — rule is computed inactive once the deadline passes, nothing to clean. `on_expire=notify` — rule stays in force; one message to the author (`notified_at` in DB, survives restart, retried on failed delivery, re-armed by extending); author extends / keeps (`keep=true`) / removes.

## Rights
Only orchestrator sessions with a valid MCP proof. Own project (`project` empty = caller's scope) only. `project="*"` (all projects) only for `Orchestra-orchestrator` with scope = Orchestra root. Removing/updating follows the same check against the rule's project. Foreign project and global from others → 403 (tests `test_permissions`, `test_http_route_enforces_proof_and_scope`).

## Your first rule
After the restart, from `Orchestra-orchestrator`:

```
temp_rule_set(
  text="Модели воркеров: Sonnet на простые задачи, Opus на сложные; Luna только для второго мнения.",
  reason="До 20.10 идёт сжигание подписки Claude; решение владельца 17.10.",
  targets=["orchestrators"],
  mode="expires",
  expires_at="2026-10-20T07:00:00Z",
  project="*")
```
Use `mode="review"` for a one-time "time to review" notice with the rule still in force, `mode="permanent"` (no date) for a lasting one. Not entered into the live system.

Modes: `expires` = stored on_expire remove; `review` = notify; `permanent` = no date. `reason` is mandatory; the block shows mode/date/reason/author/creation date; the orchestrator-only module `orchestration.md` carries the usage paragraph (reaches orchestrator and sub-orchestrator, not workers; test `test_orchestrator_module_reaches_orchestrators_not_workers`).

## Checks
`uv run --frozen python -m pytest tests/test_temp_rules_v927.py tests/test_hot_apply.py tests/test_session.py tests/test_mcp_stdio.py tests/test_tool_scoping.py -q` → 433 passed (first version); after the reason/modes change: test_temp_rules_v927, test_routes_surface, test_default_pipeline, test_check_pipeline_manifest, test_hot_apply, test_mcp_stdio, test_tool_scoping → 256 passed. Mutation: forcing `rules_changed=False` in `AgentSession.send` reddens `test_live_session_gets_and_loses_rule`. Full suite not run. Not checked live: a real Claude/Codex session; the 60 s notice sweep in a running manager (skipped under pytest).
