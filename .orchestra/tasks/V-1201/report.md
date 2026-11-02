# V-1201 — Codex model switch context overflow

## Cause and fix

The blocked switch followed the same-runtime Codex retarget path. Its preflight compared the active thread's runtime-reported current token count with `ModelSpec.context_length`, which is a conservative fallback. Codex's own `retarget_model()` preserves a larger telemetry-reported window when source and target share that fallback. The preflight therefore rejected a context that the target runtime was configured to retain.

`context_window_after_retarget()` now owns that transition rule. Both Codex retarget and the session preflight use it. The fix does not relax the context guard: switching to a Codex model with a different, smaller fallback still checks against that smaller target and blocks before retargeting or persisting. The source model, session id, backend and saved session remain untouched on this refusal.

Protected local trace details, including the owner-reported timestamp and local state correlation, are in `.orchestra/private/V-1201/trace.md`. The exact UI response was not present as a structured row in the local journal; the trace records that limit and correlates the owner report with the stored session state and local Codex model metadata.

## Regression coverage

A synthetic Terra→Sol case uses 350001 active tokens and a 700000 runtime window; it now succeeds in place and retains the session and window. A synthetic Terra→Spark case with a narrower target still returns `handoff_context_overflow` without calling retarget or saving. These figures are independent synthetic inputs.

## Checks

- `uv run --frozen python -m pytest tests/test_session.py -k 'other_builtin_model_switches_retarget_in_place or in_place_switch_respects_target_context_window' -q` — 7 passed, 245 deselected.
- `uv run --frozen python -m pytest tests/test_backend_codex.py -k 'retarget_model_keeps_thread' -q` — 1 passed, 108 deselected.
- `uv run --frozen python -m pytest tests/test_session.py -q` — 252 passed.
- No live session, provider, database write, credential read, or service restart was used.
