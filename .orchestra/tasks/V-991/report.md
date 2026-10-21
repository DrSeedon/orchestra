# V-991 — Sol closed to agents again

Owner decision 2026-10-21: GPT-6.1 Sol is selectable only by the owner in the dashboard, like Astra. Trigger: five Sol workers burned the Codex 5h window 0→100% in ~75 min.

Change: reverted the code/test/prompt parts of V-970 (e52a9793d). `MANUAL_ONLY_MODEL_IDS` again contains `gpt-6.1-sol` (`app/models.py`), which forces `agents=False` regardless of stored flags; `ensure_spawn_allowed` (manager.create_session, `/change_model` with via=mcp) and the MCP `dynamic_workflow`/`spawn_worker` checks refuse it. `codex_review` docstring and the model-routing / dynamic-workflows prompts say Sol is manual-only (owner decision 2026-10-21, no quote). No other place advertises Sol to agents (rg over app/).

Tests: both arms in tests/test_model_gates.py (agent spawn/change-model refused; `test_sol_is_dashboard_selectable_but_closed_to_agents`, `test_owner_dashboard_change_model_allows_sol`), tests/test_models.py (manual-only even if stored flags allow), tests/test_dynamic_workflows.py, tests/test_mcp_codex_review.py. Reverting the fix reddens them. `uv run --frozen python -m pytest tests/test_model_gates.py tests/test_models.py tests/test_dynamic_workflows.py tests/test_mcp_codex_review.py tests/test_codex_review_sandbox.py tests/test_mcp_stdio.py -q` → 218 passed.

Running Sol sessions: the gate runs only at spawn and at MCP change-model (`ensure_spawn_allowed` call sites: manager.py:657, routes/sessions.py:1949, mcp_stdio.py:3479). Already-running or resumed Sol workers keep running on Sol untouched; nothing was changed in other projects. They stop being Sol only if the owner/orchestrator switches them (dashboard change_model to another model still works).

Restart: required (app/** Python).
