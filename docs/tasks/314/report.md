# #314 implementation report

## Scope and data fact

Release A adds conservative pre-calibration enforcement for new worker provider turns and
Usage Analytics quota visibility. Orchestrator sessions are server-role exempt; mid-turn,
submitted, and in-flight operations remain unchanged. The read-only live-shaped check in
`data-facts.md` found no `quota_controller_*` tables and therefore no shadow decision counts,
binding constraints, or answer for today's Codex wave; the API now exposes that gap as
`no_shadow_telemetry` rather than inventing zeroes.

## Implemented

- `app/quota_controller.py`: fresh-known adaptive gate, static-denial preservation, hot disable,
  server-owned Luna Fast status, Sol suppression only from fresh `codex:primary`, and redacted
  history/bucket cards.
- `app/session.py` / `app/quota_gate.py`: real-session server-role/task-class/tier propagation,
  explicit `adaptive_quota_hold` instead of false direct-send success, queued hold retry, and
  unconditional lifecycle-lock release.
- `app/manager.py`: new worker/review Sol sessions route to Luna Fast when the fresh Codex lane
  is tight; missing telemetry leaves the requested lane unchanged.
- `app/mcp_stdio.py`: omitted `codex_review` model is now server-owned `gpt-5.6-luna`.
- `app/routes/system.py`, `app/static/js/analytics.js`, and CSS from the implementation commit:
  analytics endpoint/panel show utilization, q95, inflight, guard, reserve/headroom, runway,
  enforcement state, shadow counts/history, Luna default, and Sol suppression reason without
  prompts, secrets, or high-cardinality IDs.

The earlier generic Fast-off rule is superseded by
`docs/tasks/314/policy-correction.md`; #291 evidence and frozen oracles are unchanged.

## Verification

Exact scoped suites:

```text
uv run python -m pytest -q docs/tasks/314/oracles/test_t314_enforcement.py docs/tasks/314/oracles/test_t314_session_integration.py docs/tasks/314/oracles/test_t314_analytics.py
24 passed in 1.27s
uv run python -m pytest -q tests/test_t314_analytics_browser.py
3 passed in 8.10s
uv run python -m pytest -q tests/test_mcp_stdio.py
96 passed in 10.10s
uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py
21 passed
```

The relevant regression run supplied by the parent completed `769 passed, 12 skipped`.
The all-files collection command separately stops at the pre-existing
`tests/test_system_chat_entry.py` import of `_goto_dashboard_or_skip`, absent from the
current `tests/test_frontend.py`; no #314 test is implicated.

Mutation evidence:

- replacing the Luna review default with Sol → `test_codex_review_default_is_server_owned_luna_fast`
  failed (`rc=1`);
- replacing both fresh `codex:primary` checks with Grok → enforcement status oracle failed
  (`rc=1`);
- making session admission trust the mutable `task_class` field → real-session spoof oracle
  failed (`rc=1`).

After each mutation the original file was restored and touched; `git diff --check` is clean.
`git diff --exit-code f1a5460b24eb91b7408d11b0ecaa93bbdbb2571b -- docs/tasks/291/oracles` exits 0.

## Review

Sol review artifact: `docs/tasks/314/codex-review-impl.md`. Rounds 1–3 are preserved; round 3
ends `REJECT` on the then-unfixed Sol review default. The orchestrator explicitly authorized
the two post-round-3 surgical fixes and mechanical evidence above, with no fourth Sol round.
The artifact records this distinction and the exact green commands; it is not represented as a
new reviewer approval.

## Safety and rollout

`ORCHESTRA_ADAPTIVE_ENFORCEMENT=0|false|off|no` immediately returns to static behavior. No
deployment, restart, or production mutation was performed. No T5 calibrated enforcement enable
path or feature flag was added.
