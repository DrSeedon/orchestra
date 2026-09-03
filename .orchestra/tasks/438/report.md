# #438 implementation report

## Changes

- `app/backend_claude.py`: `compact_boundary` now reads `compact_metadata`, with snake_case `pre_tokens`/`post_tokens` first and camelCase fallback preserved.
- `app/session_turns.py`: critical threshold is 95%; orchestrators enter the same immediate path. When CLI reports a token threshold, it is converted to a percentage against `max_tokens` and reduced by a one-point safety margin, capped at 95%; missing/invalid CLI data falls back to 95%.
- `app/session.py`: the latest `auto_compact_threshold` is retained from context refresh; critical checks use the effective threshold. The compact prompt now requires every user message verbatim and in arrival order, and includes `/api/sessions/<name>/logs?scope=<scope>`.
- `tests/test_compact_gate_438.py`: five isolated regression checks for both metadata forms, orchestrator 96/94 behavior, CLI threshold adjustment, and the source-owned prompt requirement.
- `tests/test_session.py`: rewrote tests whose assertions encoded the new A contract; the kill-switch tests now assert the B fix for every role/runtime.

## Verification

Production sessions row count was read before and after the test command:

```text
sessions_before=594
sessions_after=594
```

Exact own-test command and output before the expanded session run:

```text
uv run pytest -q tests/test_compact_gate_438.py
.....                                                                    [100%]
5 passed in 2.21s

python3 -m py_compile app/backend_claude.py app/session_turns.py app/session.py tests/test_compact_gate_438.py
git diff --check
```

The baseline comparison used the same compact/context subset on `main` and this branch. `main` had `0` failures (`82 passed, 193 deselected`); this branch had six old contract tests red because they assert the replaced 99%/manual-orchestrator/three-message behavior. Exact branch-only node IDs:

```text
tests/test_session.py::TestAutoCompactKillSwitch::test_disabled_blocks_compaction_inside_the_window
tests/test_session.py::TestCompactPromptContract::test_prompt_preserves_recent_user_messages_verbatim
tests/test_session.py::TestPrecompactTimer::test_claude_deferred_context_preserves_known_compaction_behavior
tests/test_session.py::TestPrecompactTimer::test_claude_post_turn_keeps_orchestra_compaction
tests/test_session.py::TestPrecompactTimer::test_codex_post_turn_schedules_native_precompact_without_generic_handoff
tests/test_session.py::TestPrecompactTimer::test_critical_orchestrator_context_warns_once_outside_window
```
`tests/test_session.py` was explicitly authorized for these rewrites; no other test file was edited.

Classification, checked independently against each assertion:

- `TestAutoCompactKillSwitch::test_disabled_blocks_compaction_inside_the_window` — **B**: the switch was bypassed before threshold evaluation; production now checks it first.
- `TestCompactPromptContract::test_prompt_preserves_recent_user_messages_verbatim` — **A**: old three-message requirement replaced by all messages plus transcript link.
- `TestPrecompactTimer::test_claude_deferred_context_preserves_known_compaction_behavior` — **A**: 95% is now the immediate threshold instead of the old timer path.
- `TestPrecompactTimer::test_claude_post_turn_keeps_orchestra_compaction` — **A**: 95% now uses the immediate critical path.
- `TestPrecompactTimer::test_codex_post_turn_schedules_native_precompact_without_generic_handoff` — **A**: the global critical threshold changed from 99% to 95%, including native Codex compaction.
- `TestPrecompactTimer::test_critical_orchestrator_context_warns_once_outside_window` — **A**: orchestrators are now included at 95% and bypass the configured time window.
- Additional `TestAutoCompactKillSwitch::test_worker_path_is_untouched_by_the_switch` surfaced after the B fix — **A** under the explicit new rule that the switch applies regardless of role; it now expects a blocked worker path.

Python changes were checked only through tests. A service restart is required before the running service loads them; no restart was performed here.

## Pre-mortem checks

- Mixed/legacy compact metadata could regress one wire form → the parametrized boundary test exercises snake_case and camelCase and asserts the exact numbers and trigger.
- A missing or malformed CLI threshold could make every context look critical → the probe printed `95`, `89`, `95` for missing, `900000/1000000`, and malformed values respectively.
- The transcript link could omit the session scope → the prompt probe printed `True` for `/api/sessions/probe/logs?scope=/scope`.
- Existing tests could hide a changed failure set behind equal totals → the same subset was compared by node ID; six branch-only stale-contract nodes are listed above.
- The new tests could write the production database → the `sessions` count stayed `594` before and after; tests only construct sessions and mock background work.

## Review gate

- Author runtime: `gpt-5.6-luna` (live session metadata).
- Changed consumers: Claude stream-json protocol conversion; shared session context/compaction lifecycle; orchestrator/worker automatic compaction; compact handoff prompt.
- Named AC: T1 snake_case and camelCase boundary values; T2 orchestrator 96% triggers and 94% does not, CLI threshold lowers ours; T3 all user messages plus raw log endpoint.
- Named check/output: `uv run pytest -q tests/test_compact_gate_438.py` → `5 passed`.
- Route: `Review: none — Sol not authorized`; the changed session/protocol surface sets the high-risk floor, while the user did not authorize the required auxiliary Sol review.

## Mutation

The rewritten A tests were committed before mutating the production marker. The exact mutation command produced `1` for the production marker before mutation, `0` for that marker while the mutant held `CRITICAL_AUTO_COMPACT_PCT = 99`, and `1` after `mv ...bak` plus `touch` restored production. The selected tests produced `FFFFF.` and `mutation_rc=1`, so the changed-contract tests do redden when the 95% behavior is removed.

Final requested command and output (no `-x`):

```text
prod_db=/mnt/data/Projects/Python/orchestra/data/orchestra.db
printf 'sessions_before='; sqlite3 "$prod_db" 'SELECT count(*) FROM sessions;'
uv run pytest -q tests/test_session.py tests/test_compact_gate_438.py
sessions_before=594
........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 86%]
.................................                                        [100%]
249 passed in 7.39s
sessions_after=594
pytest_rc=0
```

Mutation marker output (marker owner: production `CRITICAL_AUTO_COMPACT_PCT = 95`):

```text
1
0
FFFFF.                                                                   [100%]
1
mutation_rc=1
```
