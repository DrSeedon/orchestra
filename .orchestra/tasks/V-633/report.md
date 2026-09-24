# V-633: MCP model changes preserve handoff history

## Findings

`fa3e993d` (23.08, “Allow fresh model switches without handoff”) added a `fresh=True` MCP payload and `_change_model_fresh_locked`. Its regression test recorded the case `quota-exhausted-claude-session` → Codex and explicitly required no history handoff. A later correction, `c70bb37e` (#V-599, 20.09), changed the tool description to promise native continuation and runtime handoff but left `fresh=True` in its request.

Both normal paths are already implemented and tested. `_change_model_locked` chooses in-place retarget/native resume for a same-runtime switch and `_change_runtime_chat_locked` for runtime changes. `tests/test_session.py` verifies preserved Codex session id and nonempty `chat_history_v1`; production reports supplied by the task confirm native same-family switches and nine `chat_history_v1` transfers of about 63.5K characters. The defect was the MCP entry point selecting the fresh path despite dashboard requests omitting that field.

## Changes

- MCP posts `{scope, model, via: "mcp"}`; the existing `via` field selects the agent model-access gate, and the tool has no fresh option. It reports `history_transfer.mode`, includes `chars` for `chat_history_v1`, and surfaces API refusal errors.
- Removed the now-unused fresh model-switch implementation and route parameter handling. The dashboard still submits `{model, scope}` and now renders both native and `chat_history_v1` transfer modes.
- Corrected the V-599 knowledge entry and updated `CHANGELOG.md`.
- Added tests for the MCP payload, transfer-mode reporting, and visible error code/reason; retained the existing session tests for native and cross-runtime transfer.

## Verification

Using `/home/kesha/orchestra/.venv/bin/python -m pytest`:

- `tests/test_mcp_stdio.py tests/test_change_model_unloaded.py tests/test_session.py` — **383 passed**.
- `tests/test_frontend.py::test_model_picker_preserves_same_runtime_dialog_and_surfaces_transfer_result` — **1 passed**.
- Imported app path: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-model-handoff/app/__init__.py`.
- `git diff --check` — clean.

An initial full run including all of `tests/test_frontend.py` hit 102 browser-fixture setup errors. Its Uvicorn subprocess entered `app.main` lifespan, which called `migrate_v621()` on the worktree catalog; that migration added `/home/kesha/orchestra` to `include_scopes`, causing the worktree to aggregate both catalogs and encounter duplicate tag `polus`. The migration also created and committed `c963aa26` in the worktree. Reverted it with `git revert c963aa26` (`cb197f25`); `git diff main...HEAD` now contains only V-633 files. The changed static frontend test passes directly; the browser fixture remains unverified in this checkout layout.

## Remaining uncertainty

The behavior is verified with mocked backends and the existing chat-history unit test; no live CLI provider or production database was used, per task boundaries. No Orchestra restart was performed.
