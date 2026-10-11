# V-815 — classify structured tool outcomes

## Evidence

Read the `seedon-orchestrator` tool-result record from `/home/kesha/orchestra/data/orchestra.db` in read-only mode, scoped to `/home/kesha/projects/seedon`. The unique matching `merge_worker` result for V-219 was log 639841 at `2026-10-11T08:10:48.371647+00:00`, with `tool_is_error=0`. Its structured text contains `error: None`, `review.comparison_error: ''`, `git.status: 'SUCCEEDED'`, `git.commits_merged: 1`, and `operation_state: 'SUCCEEDED'`. The browser regression uses those exact outcome fields and the original Python-dict text form; unrelated acceptance text and identifiers are omitted.

The dashboard treated any occurrence of `error` or `failed` in an Orchestra tool result as a failure. The Telegram path does not use that substring rule: `_result_mark` already follows stored `tool_is_error`. It did, however, mark a domain `PARTIAL` result successful when the transport flag was false.

## Change

`chat.js` now treats stored `tool_is_error` (SQLite rows return `0`/`1`) and structured `operation_state` values `FAILED`, `PARTIAL`, and `UNKNOWN` as failures. Other success metadata containing empty `error` fields stays green. Successful `merge_worker` results read `git.commits_merged` from structured text and display the count; the ordinary `Merged N commits` text form remains supported. The `send_message` result renderer no longer independently searches result prose for failure words.

`tg_bridge.py` keeps its existing authoritative error flag and also marks `FAILED`, `PARTIAL`, and `UNKNOWN` operation states as failures. A safe keyed state match handles the logged JSON/Python-dict forms without evaluating tool output.

## Verification

`uv run --frozen python -m pytest tests/test_frontend.py::test_orchestra_tool_result_uses_structured_outcome_not_error_words tests/test_tg_bridge.py -k 'result_mark' -q` — 2 passed, 224 deselected. The committed browser regression covers the real V-219 success excerpt (including error fields), another `error: None` result, `PARTIAL`, `FAILED`, and an MCP error flag. TG tests cover success metadata, partial state, and the explicit MCP error flag.

After committing the regression, temporarily restored the old substring expression. The committed browser test failed on the V-219 result at the expected `Merged` assertion (`❌ Tool failed: merge_worker`); after restoring structured classification, the focused command passed again.

`node --check app/static/js/chat.js`, `uv run --frozen python -m compileall -q app/tg_bridge.py tests/test_frontend.py tests/test_tg_bridge.py`, and `git diff --check` passed.

The pytest process imported `app` from this worktree: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-dashboard/app/__init__.py`.
