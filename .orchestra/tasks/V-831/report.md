# V-831 — live tool-call writing, thinking, running tools and shell output in the chat

## What the runtimes actually give (measured 13.10.2026)

- **Claude CLI 2.1.293 / claude-agent-sdk 0.2.164.** A real `--include-partial-messages` capture
  (`capture/stream.jsonl`, haiku, one Bash heredoc of 8 439 chars) contained `content_block_start`
  with `{"type":"tool_use","id","name"}` and then **1 207 `input_json_delta` events** for that one call.
  Feeding the capture through the new `ClaudeBackend._convert` (`check_capture.py`, log
  `check_capture.log`) reassembles exactly the final `ToolUseBlock.input` (`equal_to_final: True`).
- **Thinking text can be absent.** In the same capture every `thinking_delta` had `"thinking": ""`
  plus a growing `estimated_tokens` (50, 200, 250, 300…); the final thinking block is empty too.
  Orchestra's Opus sessions do store short non-empty thinking (DB, 117–267 chars), so both shapes
  occur. Empty deltas with an estimate become a `thinking_stream` with `estimated_tokens`
  (label «Рассуждает прямо сейчас · ~N токенов»); text deltas stream as text.
- **Shell output.** The CLI runs every Bash call that lasts more than a few seconds as a task
  (`TaskStartedMessage`, `task_type=local_bash`, with `tool_use_id`) — foreground calls too, not
  only `run_in_background` (DB rows for my own foreground calls, e.g. `Emit lines slowly…`,
  id `brj5s07aj`). The running command's stdout/stderr **is** the file
  `/tmp/claude-<uid>/<cwd-slug>/<session>/tasks/<task_id>.output` (a `cat` of it from inside the
  command failed with `input file is output file`); the CLI deletes it after a foreground call.
  So ordinary Bash output is available too, once the task is announced (~2–3 s after start).
  Commands shorter than that have no task and show only the timer until their result.
- **Codex app-server 0.160.0** (`codex-notifications.txt`, from `generate-json-schema`): no
  tool-argument delta exists. Deltas are agent message, reasoning text/summary, plan, command and
  file-change output, `fileChange/patchUpdated`, process/exec output and realtime audio. Orchestra
  already streams all relevant ones, so nothing was added for Codex; its tool cards get the new
  running clock like any other card.

## Implementation

- `app/backend_claude.py` — `_convert` tracks open content blocks by
  `(parent_tool_use_id, index)` (reset on `message_start`): tool blocks yield `tool_input_stream`
  (empty content on start, then JSON fragments) with `tool_use_id/tool_name/short_name`; thinking
  blocks yield `thinking_stream` with a per-block `item_id`. Sub-agent partials keep `subagent_id`.
- `app/session.py` — these types go to the broker only (sub-agent ones as `subagent_stream` with
  `event_type`); `_sync_live_activity` retires replay state when the persisted row appears
  (`tool_use`, `thinking`/`text`, `tool_result`, `turn_end`) and starts/stops the output tail on
  `subagent_start`/`subagent_end` of `local_bash`; `_disconnect_backend` stops all tails.
- `app/task_output_tail.py` — polls the task file each second, publishes new bytes (incremental
  UTF-8 decoding, ≤64 KB per poll, late attach starts from the last 16 KB) as `tool_stream`;
  stops when cancelled, when the file is gone >10 s, never found in 30 s, or after 6 h. Ids are
  validated before globbing.
- `app/live_broker.py` — keeps a capped tail of each open block (tool input 64 KB, thinking 32 KB,
  output 16 KB) and replays it with `replace: true` to a newly connected client; tool-input
  payloads carry the server-side `chars` and `elapsed_ms` (browser clock skew does not matter).
  `coalesce()` merges adjacent deltas of the same block; the SSE loop applies it per ~100 ms tick.
  Queue depth raised 256 → 1024 so a 1 200-delta call is not dropped on a slow tick.
- Frontend: `app/static/js/live-activity.js` (incremental JSON-argument decoder, writing card,
  running clock with Bash timeout — default 2:00, cap 10:00, none for `run_in_background`, task
  output routing); hooks in `chat.js`/`app.js`; CSS with reduced-motion fallbacks.
- **Pre-existing bug fixed:** the background-task clock (`_startSubagentClock`) was started on a
  detached card, its first tick saw `isConnected === false` and removed the clock immediately —
  that is why the owner's screenshot showed no sign of life. The clock now lives in the header,
  stops only after the card has been in the DOM and left it, and is not started for start rows
  older than 6 h. It shows the Bash call's timeout when the task is a foreground call.

## Checks

- `uv run --frozen python -m pytest tests/test_session.py tests/test_secret_mask.py tests/test_live_broker.py tests/test_backend_stream.py tests/test_live_tool_activity_831.py tests/test_static_js_globals.py tests/test_subagent_clock.py tests/test_backend_claude.py tests/test_subagents.py tests/test_subagent_routes.py tests/test_sigterm_sse_shutdown_v630.py -q`
  (results in the DONE message). New tests: conversion of `input_json_delta`/`thinking_delta`
  (incl. omitted thinking), broker-only routing with `_log`/DB writes not called, final row still
  persisted, replay/tail/end/clear, coalescing order, real file tail with a split UTF-8 char,
  path-trick rejection, tail lifecycle on task start/end, the JS decoder for chunk sizes 1…N,
  timeouts and labels, and the clock-at-birth regression (mutation: restoring the old check
  reddens it).
- Two old tests asserted the previous contract «thinking/input_json deltas are dropped»; they
  were replaced by the new behaviour tests in `tests/test_backend_stream.py`.
- **Live run** (`live_demo.py`, own temp DB, pytest-guarded env, TG bridge refused to start):
  the real capture replayed at 35 ms/delta through `ClaudeBackend._convert → AgentSession →
  broker → SSE → browser`, then a real shell process writing a task output file. Screens:
  `screens/1-writing-call.png` (card «Команда · пишет вызов», 3 318 симв · 181 симв/с · 0:18,
  decoded heredoc), `screens/2-running-bash-card.png` («идёт 0:11 из 2:00» + live output),
  `screens/2-running-task-card.png` (task card «идёт 0:06 из 2:00»), `screens/3-finished.png`
  (clock and live cards gone). Persisted rows after the run: `tool 1, tool_result 1, text 1,
  subagent_start 1, subagent_end 1` — no partial rows.

## Limits

- Python changes need an Orchestra restart; the JS/CSS part alone shows clocks but no live data.
- Bash calls shorter than the CLI's task threshold get the timer only (no task file announced).
- Sub-agent live arguments/thinking appear inside the sub-agent accordion and are not replayed on
  reconnect.
