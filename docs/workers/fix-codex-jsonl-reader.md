# #284 Codex JSONL reader

> Superseded by #307/#319 where noted: an oversized record is not safely discardable when its
> envelope is unknown.

## Evidence

- `CODEX_STREAM_LIMIT` remains 16 MiB; oversized readline errors are recognized by their two CPython limit messages.
- A poisoned record larger than the cap is discarded in bounded 64 KiB chunks; a following `turn/completed` is still parsed.
- A non-limit `ValueError` is re-raised. EOF/process exit after a reader failure rejects pending requests and emits `reader_failure` turn-end metadata.
- Codex listener/connect/restart paths clear `RUNNING` when no active turn remains and schedule queued messages for delivery.
- `uv run pytest -q tests/test_backend_codex.py tests/test_session.py tests/test_session_id_guard.py` → `315 passed`.
- Relevant async regressions repeated three times → `5 passed` each run.
- `git diff --check` → clean.

## Pre-mortem checks

- Oversized record with a valid terminal record after it → synthetic backend reader test.
- Oversized record ending in EOF/exit 0 → synthetic `reader_failure` turn-end test.
- Non-oversize reader failure → explicit `ValueError` propagation test.
- Listener/connect failure with queued input → session lifecycle tests verify `IDLE` and queue flush.

## Memory

`asyncio.StreamReader.readline()` may consume an oversized line before raising the “separator found” variant; discard logic must distinguish that case from the “separator not found” variant or it will drop the next valid record.

## #307 durable correction

- Exact COG replay on Codex CLI 0.149.0: default stdio `thread/resume` response `id=2` was
  23,159,303 B for a 49,984,790 B rollout containing seven generated images. The lost frame was the
  required response, so discard-and-continue cannot recover request correlation.
- `initialize.capabilities.experimentalApi=true` plus `thread/resume(excludeTurns=true)` reduced the
  same response to 5,104 B, retained thread id/status/runtime metadata, and returned `turns=[]`.
  Without the capability the server returns `-32600`.
- A blank 120 s compact failure was a local deadline: app-server emitted started notifications,
  completed ~15 s after the deadline, and a later same-thread compact succeeded. Compact errors must
  name acknowledgement/completion/lifecycle phase and preserve the exception class.
- Main mitigations: `b11ba9be` (metadata-only resume, terminal poisoned transport, timeout phase) and
  `db8708aa` (bounded cleanup and queued-message preservation).
