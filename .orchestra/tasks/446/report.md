# #446 report

## Diagnosis

The observed delivery was not Telegram bridge output. In the production database,
session `07233e67-502d-4c62-9f34-b37fbbdf8606` contains:

- `573931`, `2026-09-03T06:40:10.095127+00:00`, `status`, content beginning
  `RATE_LIMIT_RAW`;
- `573937`, `2026-09-03T06:40:19.080189+00:00`, `user_message`, origin `user`,
  subtype `http_send`, content beginning `[13:40] ⚡ RATE_LIMIT_RAW`.

The service journal records a dashboard SSE request at 13:40:05 and HTTP `POST
/api/sessions/Orchestra-orchestrator/send` at 13:40:07 and 13:40:19. The exact
user-facing path was therefore dashboard SSE → `chat.js:_renderStatusEntry`.
The Telegram bridge's `stream_logs` path already dropped the row because only
`_STATUS_RELIABLE` or `_STATUS_AS_ACTION` statuses can continue to delivery.

## Change

`app/status_policy.py` owns the class predicate: structured statuses whose label
ends in `_RAW` are internal telemetry. The SSE and history routes annotate status
payloads with `status_hidden`; `chat.js` passes the payload through the real
`addChatEntry` path and returns before creating a DOM node. The Telegram bridge
also asks the same predicate before its existing status delivery checks.

The `logs` row remains type `status` and its content is unchanged.

## Checks

- `./.venv/bin/python -m pytest -q tests/test_tg_bridge.py::TestTurnFoldStream tests/test_rate_limit_capture_441.py tests/test_logs_sync.py` → `42 passed`.
- `./.venv/bin/python -m pytest -q tests/test_frontend.py -k 'status or stream'` → `9 passed, 97 deselected`.
- Playwright targeted test `test_internal_telemetry_status_is_not_rendered_in_chat` → `1 passed`.
- `node --check app/static/js/chat.js`, `py_compile`, and `git diff --check` passed.

Mutation checks on the committed regression test:

- Predicate wiring changed to `if (false)` → `RC=1`, raw telemetry appeared in the DOM; restored, `grep` marker `1`, green repeat.
- `_renderStatusEntry` call removed from `addChatEntry` → `RC=1`, raw telemetry appeared in the DOM; restored, wiring marker `1`, green repeat.
- Telegram bridge status branch changed from `continue` to send → `RC=1`, raw telemetry appeared in `_tg_send_safe`; restored and green repeat.

The named acceptance command was run before adding the test and currently has five
unrelated missing #224 artifact failures (`tests/test_tg_bot_api_unit.py`); the
backend portion passed.

## Review

Luna review was run with the supplied PROJECT CONTEXT. It executed the targeted
checks and returned a quote, but no `## Verdict` section; recorded as `verdict not
available` under the review policy.
