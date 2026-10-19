# V-970: reopen Sol for agent use

The agent-only model gate now lists Astra alone. Sol has `default_agents=True`, enabling model availability through the existing shared gate used by MCP spawn, MCP model changes through REST, dynamic-workflow normalization, dashboard model metadata, and the internal Codex reviewer model resolver. Existing explicit agent-disabled flags remain independently honored. The checkout's persisted `model_flags` had no Sol entry, so the new default applies without data migration.

Prompt routing records `owner decision, 2026-10-19: Sol is open to agents again; Astra stays manual-only`; Luna remains default and Sol is for heavy Codex work. The dynamic-workflow and Spark guidance no longer claim Sol is blocked.

The current database's persisted `model_flags` had no Sol entry, so `default_agents=True` takes effect without changing database state. Historical V-739/V-720 changelog entries that describe their then-current policy remain historical records; the active model-routing and dynamic-workflow prompt modules no longer say Sol is blocked.

Verification: `uv run --frozen python -m pytest tests/test_models.py tests/test_model_gates.py tests/test_dynamic_workflows.py tests/test_mcp_stdio.py tests/test_mcp_codex_review.py tests/test_model_registry_503.py -q` — `209 passed in 11.03s`; `uv run --frozen python -m pytest tests/test_dynamic_workflows.py::test_workflow_module_reaches_launching_roles -q` — `3 passed in 2.70s`; `uv run --frozen python -m pytest tests/test_codex_review_sandbox.py -q` — `12 passed in 6.07s`. The imported app module was `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn/app/__init__.py`.

Python changes require an Orchestra restart; none was performed.
