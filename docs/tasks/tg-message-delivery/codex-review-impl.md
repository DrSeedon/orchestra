# Codex implementation review — Telegram delivery

## Round 1

Verdict: **NOT READY**.

- `blocking: app/tg_bridge.py:_tg_call_safe` — an ambiguous network/server failure did not update `_tg_last_send`, so a retry could bypass the 3.05-second group interval.
- `blocking: app/tg_bridge.py:_tg_send_safe` — the no-entities fallback made a second immediate Bot API request inside one limiter slot.
- `suggestion: app/tg_bridge.py:send_message pretty path` — either classify the user-visible inter-agent message explicitly as important or make it non-important like ordinary tool chatter.
- `question: delivery state` — confirm whether per-chat dictionaries are intentionally lifecycle/config bounded.

## Resolution

- Count every Bot API attempt by updating `_tg_last_send` immediately before `await call()`. Added a regression test that proves an ambiguous timeout retry consumes the interval.
- Return an entity-rejection sentinel, then route the plain send through a second `_tg_call_safe()` invocation. Applied the same accounting to edit fallback and added a send timing regression test.
- Kept pretty `send_message` important and documented why: it is the user-visible inter-agent message implicated in this incident, not disposable tool diagnostics.
- Per-chat state is intentionally bounded by primary/mirror chat configuration for the current MVP and is cleared at bridge start/stop.

The first persistent-session resume attempt failed with `thread/resume failed: no rollout found`. A fresh read-only review was used rather than claiming continuity or approval without evidence.

## Round 2

Verdict: **APPROVED**.

- A: **FIXED** — every attempted request now consumes a rate slot.
- B: **FIXED** — entity send/edit fallbacks re-enter the common limiter.
- Prior suggestion: **addressed** in plan and implementation.
- New blocking findings: **none**.
- Non-blocking question retained: the local parsing-exception fallback from pretty `send_message` to `_send_expandable()` remains non-important. The primary path is important, so this rare fallback does not block the MVP fix.

Independent review verification:

```text
PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -q -p no:cacheprovider
52 passed in 1.70s

git diff --check
clean
```

Review session IDs: Round 1 `019f745c-b736-7e50-ae9c-d9e97a04ca3f`; independent Round 2 `019f7462-1220-7472-8dfb-ab6d98e328aa`.
