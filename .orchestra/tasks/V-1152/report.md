# V-1152 — protected-work local Luna delegation

## Outcome
Implemented the approved narrow route and aligned the prompt owners. No providers, paid calls, restarts or services were used.

## Code (admission)
- `app/models.py`: `LOCAL_LUNA_MODEL = "gpt-6-luna"`; `ensure_spawn_allowed(model_id, *, billing, model_reason="")` admits native Luna only on subscription billing with a non-empty string `model_reason`. All other native models (incl. legacy Luna `gpt-5.6-luna`, Sol, Astra, Spark, Claude, Grok, Harness) and `api_credit`/invalid billing behave as before. Catalog `agents` flag, hub-configuration check and the refusal text (now naming the allowed route and the idle-restart blocker) remain. `validate_model_reason` returns the stripped reason for Luna (optional there, so manual selection is unchanged); the refusal for a missing reason comes from `ensure_spawn_allowed`.
- Callers inspected (all `ensure_spawn_allowed` users): `manager.create_session` (only when `parent_name` is set; roots keep the dashboard path) and `routes/sessions.change_model` (`via=mcp`) now pass the reason; `mcp_stdio._normalize_dynamic_task` does not, so dynamic workflows stay closed and the hub no-adapter rule is untouched. `scripts/wf_adapters` is not modified.
- Later gates unchanged: spawn-time `get_worker_admission`/`require_worker_admission` (codex, non-orchestrator), and `session.py` delivery/held/queued re-admission via `session_requires_quota`. `model_reason` persists via `session_model_reasons` and is restored in `manager` reload.

## Prompts
- `model-routing`: single owner of the route (conditions, what it does not admit, no automatic fallback, restart-readiness blocker, reuse of idle Luna).
- `orchestration` Step 0.5 + acceptance rule: replaced the "inspect everything yourself" clause with the delegation split; evidence must be what the report names/executor preserved.
- `roles/orchestrator.md`: one sentence of role focus; `artifact-reading` keeps the read-in-full lesson and says what the artifact is now (concise complete report; raw material only for a discrepancy).
- `roles/sub-orchestrator.md`: compact-complete upward report. `worker-lifecycle`: assignment-side evidence contract. `report-format` (reaches `worker` roles, which do not get routing/lifecycle modules): executor-side report contract.
- Model review stays frozen; nothing was renamed as review.

## Tests actually run (provisioned uv 0.11.28, default .venv, project conftest)
- Integration control `tests/test_local_luna_integration.py` (real `SessionManager`, real SQLite, fake provider backend; hub backend, hub pool and hub upload raise if touched): a native Luna worker is created with a reason through the real spawn path and ordinary-worker quota admission; `session_model_reasons` holds the reason; a fresh manager `_load_from_db` restores model, reason, `codex` runtime and non-orchestrator role; with the gate closed, `preflight_delivery_admission` and `send` raise `QuotaGateError` and neither `_ensure_backend` (provider start) nor backend `send` is awaited; once open, `send` reaches the fake backend exactly once. A closed gate at spawn leaves no session or DB row. The hub was never touched.
- `tests/test_local_luna_route.py` (admission matrix, change-model route, dynamic-workflow closure), `tests/test_local_delegation_prompts.py` (full current body of each owner module appears exactly once in roles declaring it and zero times elsewhere, so an emptied body under a kept tag fails; English check; static assembly), plus `test_model_gates.py`, `test_models.py`, `test_toggle_live_agent.py`, `test_hub_model_reason.py`: **116 passed** with process-local synthetic `GIT_AUTHOR_*`/`GIT_COMMITTER_*` (no global git config); the earlier git-identity failure is gone.
- Prompt consistency: the top-level "all ordinary workers use the hub" sentence now points to the protected-work exception, and the closing sentence names the refused native models (Astra, Sol, Claude, Spark, Grok, Harness).
- Raw logs: ignored `.orchestra/private/V-1152/` (originals kept); copies moved from the previously tracked `private-verbatim/` into `.orchestra/tasks/V-1152/private-evidence/`, which a task-local `.gitignore` excludes (not force-added). sha256: run1 `c658c421…5b6f`, run2 `a21d0e65…c540`, run3 `cf6eb409…66ff9`, run4 `ac6e525f…d4e0` (full values: `sha256sum` on the files; contents unchanged by the move). Old `private-verbatim/run*.log` paths are deleted.

## Not run / limits
- `tests/test_agent_hub_routing.py` (imports `scripts/wf_adapters`, absent from this partial checkout; its diff is now empty/unchanged) and the wf adapter path: parent runs on the host.
- Not run: full suite, `scripts/check_instruction_contract.py` (CLAUDE.md symlink and `.orchestra/kb` absent), mutation check, CI. `AGENTS.md` unchanged (16356 bytes).
- Activation: Python guard needs the owner's idle watcher; no live Luna or real provider was started.
- Final cleanup: the assembly test now requires a non-empty body (no length floor). Short targeted rerun with process-local synthetic git identity is recorded below.
- Targeted rerun (test_local_delegation_prompts, test_local_luna_route, test_local_luna_integration): 27 passed.
