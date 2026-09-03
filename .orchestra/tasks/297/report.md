# #297 — semantic silent-turn marker in the backend lifecycle

## Contract

`[[ORCHESTRA:SILENT_TURN]]` is a protocol marker, not user-facing output. A turn is
semantically silent only when it succeeded and its last typed assistant/model `text` event
is exactly that string. Tool telemetry before it remains in `_turn_logs`, but cannot make the
turn reportable. Whitespace, prefix, suffix, and failed turns remain ordinary auto-reports.

The marker is still recorded in the immutable turn log. For a fan child, `fire_auto_report`
continues to call `record_terminal(..., require_drained_scope=...)` and delivers the normal
final manifest to the reducer/parent; the marker is not used as a child summary or manifest
body. Outside a fan, no `on_idle` callback is scheduled, so there is no parent wake and no
undelivered auto-report record.

## Implementation

- `app/turn_markers.py` owns the marker and the exact semantic predicates.
- `AgentSession._last_text_output` is reset at each turn and updated only by typed `text`
  events; formatted tool entries never overwrite it.
- `TurnManager.fire_auto_report` uses that typed value and keeps fan terminalization ahead of
  the suppression gate.
- Telegram reuses the same text predicate; the old `TG_SILENT_TURN_MARKER` name remains an
  import-compatible alias.

## Evidence

RED before the implementation: the exact marker with a successful parented turn awaited
`on_idle`; the manager-path check also created an undelivered record. After implementation:

- `uv run pytest -q tests/test_session.py -k 'auto_report' tests/test_auto_report_undelivered.py -k 'auto_report' tests/test_fan_enable.py::test_impl5_exact_silent_marker_completes_fan_without_manifest_noise`
  → **23 passed, 203 deselected**
- `uv run pytest -q tests/test_session.py -k 'auto_report'` → **15 passed, 201 deselected**
- `uv run pytest -q tests/test_session.py -k 'exact_silent_marker or tool_logs_before_exact_final_marker'`
  → **2 passed, 219 deselected**; the typed-event oracle also exercises `_handle_event`.
- `uv run pytest -q tests/test_auto_report_undelivered.py::test_silent_marker_auto_report_leaves_no_record`
  → **1 passed**
- `uv run pytest -q tests/test_fan_enable.py` → **10 passed**
- `uv run pytest -q tests/test_fan_barrier_gates.py tests/test_fan_barrier.py` → **29 passed**
- `uv run pytest -q tests/test_tg_bridge.py -k 'silent_marker or silent_turn'` → **7 passed, 181 deselected**

On the original task branch the two requested fan files did not exist, so their equivalent
suites were used. After rebasing onto current main, both files were present. The first fresh
run exposed two test-double compatibility failures (`_Child` had no `_last_text_output`),
resolved with a `getattr(..., None)` fallback; no production object loses the field because
`AgentSession` initializes it. The requested fan files then passed **9 tests**, the existing
fan suites passed **39 tests**, and `tests/test_session.py` reached **100%**. The combined
requested command was also launched on this base; its output reached the final 100% line.

Mutation: replacing the shared predicate body with `return False  # MUTATION` made the
exact-marker session oracle fail (**2 failed**) and made the no-undelivered-record oracle fail
(**1 failed**). Each mutation started from a fresh backup; after restoration `touch` was run and
`grep -c '# MUTATION' app/turn_markers.py` returned **0**.
