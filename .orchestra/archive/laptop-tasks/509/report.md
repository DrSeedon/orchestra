# #509 — suppress Telegram service-event feedback

## Result

- The catch-all still writes `TG ingress fallback: ... type=<actual type>` for every unhandled update.
- For 18 requested service-message `ContentType` members, it returns immediately after that log. `_resolve_orch` and `_send_to_agent` are not called, so `forum_topic_edited` cannot wake an orchestrator.
- Unknown nonservice fields still use the #508 `model_extra` fallback and reach the agent with their actual field name and JSON.
- `forward_origin`, dedicated media handlers and serialization were not changed.

Installed aiogram 3.28.2 has all 18 requested enum members. Neither `Message` nor `ContentType`, nor the installed aiogram source, exposes a service-message predicate/group. The production classification therefore uses those verified `ContentType` members rather than free-form strings.

## Frozen oracle

Test-only commit `d0065d40` predates production commit `4403f7fb`.

```text
uv run pytest -q tests/test_tg_ingress_509.py
F. [100%]
1 failed, 1 passed in 10.25s
RC=1
```

- RED: `forum_topic_edited` was logged, then `_resolve_orch` and `_send_to_agent` were called.
- Baseline-green control: unknown nonservice `future_user_content` was delivered as `[future_user_content] {"body":"keep this"}`.

## Mutation

The committed membership condition was replaced with `if False`, then the file was restored from a one-use backup and `touch`ed.

```text
prod_marker_before=1
mutant_marker_before=0
prod_marker_during=0
mutant_marker_during=1
1 failed, 1 passed
mutation_red_rc=1
prod_marker_after=1
mutant_marker_after=0
2 passed
restored_green_rc=0
```

Requested paired counts: production marker before/after = `1/1`; mutant marker during/after = `1/0`. Removing the filter reddened only the service-event test; the unknown-content control stayed green.

## Verification

The exact requested command ran without `-x` three times:

```text
uv run pytest -q tests/test_tg_ingress_508.py tests/test_tg_ingress_509.py tests/test_tg_bridge.py
202 passed, 1 pre-existing subprocess teardown warning in 15.24s
202 passed, 1 pre-existing subprocess teardown warning in 13.30s
202 passed, 1 pre-existing subprocess teardown warning in 12.58s
```

`uv run python -m py_compile app/tg_bridge.py` → `RC=0`.

## Pre-mortem

- Service event is logged after the early return and disappears operationally → the service test requires the real type in `caplog` and also requires `_resolve_orch` not to run.
- Filter eats future user content → `future_user_content` control asserts one delivery with exact marker/JSON; it remains green under the no-filter mutation.
- #508 rich messages, forwarding or ordinary photos regress → the complete `tests/test_tg_ingress_508.py` passes in all three combined runs.
- Catch-all ordering or shared bridge behavior regresses → all 193 existing `tests/test_tg_bridge.py` cases are included in every combined run.

## Review

- Changed files/consumer: `app/tg_bridge.py` catch-all message delivery; `tests/test_tg_ingress_509.py` frozen oracle. Consumer is the shared production Telegram-to-orchestrator ingress.
- Author metadata: `gpt-5.6-sol`, confirmed by `list_agents` for task 509.
- Named AC: the exact three-file pytest command above → `202 passed` three times; service event logs without resolve/delivery, unknown nonservice content delivers.
- Route: message delivery is high risk, but a Sol run was explicitly not authorized. The assignment authorized one Luna pass.
- Independence: fresh `gpt-5.6-luna` reviewer artifact, different model from the Sol author.
- Verdict: ACK, zero findings. Evidence is the verified diff quote `_SERVICE_MESSAGE_TYPES = frozenset(` in `docs/tasks/509/codex-review-impl.md`.

