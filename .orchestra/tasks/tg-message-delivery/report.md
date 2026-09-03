# Report — reliable Telegram topic delivery

## Outcome

The missing-topic symptom was sender-side loss, not bad topic IDs or a currently dead proxy. Live evidence showed group flood errors, transient request timeouts, invalid Markdown entities, and a post-conversion 4096-unit overflow. The bridge now serializes all high-frequency message-producing operations per chat, preserves important messages with bounded retries, sheds non-important chatter before it builds backlog, and validates the final converted payload.

## Root cause evidence

- Orchestra journal, last 24 hours: 11 caught flood events plus 11 generic `SendMessage` flood failures, 7 `send_message` timeouts, 2 file timeouts, 2 result-image timeouts, 3 invalid entity URLs, and 1 message-too-long rejection.
- SQLite candidate outbound volume: 60 active minutes above 20 operations/minute and a maximum of 78/minute; Telegram directly returned 429s with `retry_after=3..40s`.
- Old concurrent limiter experiment: three same-chat callers started within `0.000014s`, `0.000010s`, and `0.000009s` despite a configured interval.
- Exact SQLite row `265954`: raw Markdown `3720` UTF-16 units became `5262` after conversion. The fixed path emits two payloads of `4057` and `1204` units.
- Current routing config: 25 primary topics and one mirror, with zero null/zero topic IDs.
- `telegram-bot-api`: active/running, PID 1535, `NRestarts=0`; both proxychains configs select `socks5 127.0.0.1 12345`; three clean proxy requests succeeded in `0.405s`, `0.413s`, and `0.419s`.

## Changes

- `app/tg_bridge.py`
  - per-chat lock, flood deadline, and 3.05s group / 1.05s private interval;
  - bounded important retries for 429, network, and server failures, with explicit ambiguous-delivery and final `LOST` logs;
  - every attempted Bot API request consumes a rate slot, including timeouts and rejected entity requests;
  - entity fallback uses a separate limited request; file retry recreates `FSInputFile`;
  - message, edit, photo, document, mirror, result-image, and topic-status paths use the common policy;
  - Markdown conversion precedes UTF-16 validation; multi-chunk output is sent without cross-chunk entities.
- `tests/test_tg_bridge.py`
  - 14 delivery regressions covering concurrency, chat independence, 429/network/entity retries, attempt accounting, final loss, non-important shedding, Markdown expansion, topic preservation, and file recreation.

## Tickets and acceptance evidence

- **T1 complete:** same-group calls serialize; different chats remain independent; retries retain `message_thread_id`; post-conversion chunks remain within 4096 UTF-16 units.
- **T2 complete:** high-frequency direct send/edit/media paths use the shared limiter; explicit file primary/mirror retries recreate file objects and preserve topic IDs.
- **T3 complete with baseline caveat:** focused suite and adversarial review pass. The repository-wide suite cannot go green in this worker environment for unrelated pre-existing test isolation/schema failures described below.

## Verification

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_tg_bridge.py
52 passed in 1.45s

PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_tg_bridge.py -q -p no:cacheprovider
52 passed in 1.70s

python -m compileall app/tg_bridge.py
passed

git diff --check
clean
```

Repository-wide attempts stopped on unrelated baseline failures:

```text
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q
1 failed, 418 passed
tests/test_mcp_stdio.py::test_list_agents_groups_by_parent
worker PARENT_NAME leaked into the test expectation

env -u WORKER_NAME -u WORKER_ROLE -u PARENT_NAME UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q
1 failed, 557 passed, 20 skipped
tests/test_session.py::TestStart::test_with_message_sets_running_then_idle
sqlite3.OperationalError: no such table: bg_jobs
```

Codex Round 1 found two rate-accounting blockers. Both were reproduced with failing tests, fixed, and independently re-reviewed. Round 2: **APPROVED**, no new blocking findings. Full record: `codex-review-impl.md`.

## Compatibility, risks, and operations

- No schema, environment, proxy, topic-map, or systemd changes.
- Important timeout retries are at-least-once and can duplicate a message if Telegram accepted the request but lost its response.
- Non-important tool/status/image traffic is intentionally omitted during bursts so it cannot crowd out agent/user messages.
- Topics in one supergroup correctly share its group quota, so important messages may be delayed under a real flood wait.
- No production Telegram message was sent, and no service was restarted. The fix is not live until this commit is merged and Orchestra is restarted by explicit user action.

## Tier-2 proposals from retro

- Make test fixtures clear Orchestra worker identity variables and initialize the `bg_jobs` schema explicitly.
- Add TTL/owner liveness handling for the shared test lock; the current lock is stale since 2026-07-01.

These are logged only and were not applied because they are outside this task.
