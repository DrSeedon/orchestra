# #302 — Telegram voice: `FileNotFoundError` after a successful download

## Verdict

The reproduced incident was not an upload-file race. The Telegram voice was copied and read
successfully; the bare `FileNotFoundError` came later, while `httpx` constructed its TLS transport
from a certifi path that had been deleted when another project replaced Orchestra's live virtual
environment.

This change is deliberately narrow. The running process now loads one Deepgram `SSLContext` at
module import and reuses it for every request. A real missing or unreadable audio file is returned
as `audio file unavailable: <Exception>: <detail>` before any HTTP client is created. HTTP/TLS
construction failures remain visible as `transcription service unavailable: ...`; no transcript
is synthesized. The service-environment authority boundary is tracked separately as #303.

## Forensic timeline (UTC)

- `08:09:47` — the current Orchestra service started under Python 3.12.
- `13:21:24.881` — session `research-typed-world-tools`, from a different project's worktree,
  ran `UV_PROJECT_ENVIRONMENT=/home/kesha/orchestra/.venv uv run --frozen ...`.
- `13:21:24.974` — `/home/kesha/orchestra/.venv` was recreated. Its resulting `pyvenv.cfg`
  identifies Python 3.11 and `prompt = dm-claude`, not Orchestra. `/proc/481449/maps` shows the
  service's previously loaded `.venv/lib/python3.12/...` shared objects as `(deleted)`.
- `14:04:55` — the earlier voice incident rendered the same `FileNotFoundError`; the next MCP
  call failed with `ModuleNotFoundError: No module named 'httpcore'`.
- `14:27:49` — forwarded voice `voice_20260816_142749_146202.oga` was copied from the local Bot
  API in 165 ms (239,699 bytes). The source path contained the bot token and is intentionally not
  reproduced here.
- `14:27:49`, `14:27:51`, `14:27:54` — all three Deepgram attempts failed with the exact
  `FileNotFoundError: [Errno 2] No such file or directory`; `handle_voice` completed in 4,680 ms
  and forwarded the explicit error.
- `14:29`–`14:31` — `search_memory`, `report_bug`, `task_create`, `list_agents`, and `bg_create`
  returned the same bare error, while authenticated loopback HTTP continued to work.

The error is reproduced exactly by replacing `certifi.where()` with a deleted path and then
constructing `httpx.AsyncClient`: `ssl.create_default_context(cafile=certifi.where())` raises the
same filename-less `FileNotFoundError`. Supplying an already-loaded `SSLContext` avoids that late
filesystem access.

## Exact media lifecycle

1. `handle_voice` resolves the session and `_register_media` reserves the message's position in
   the debounce buffer.
2. `_download_file` misses the media cache, invokes `_cleanup_uploads`, fetches Telegram metadata,
   copies the local Bot API file to `data/uploads`, saves the stable `file_unique_id → path` cache,
   and returns the path.
3. `transcribe_audio` misses the transcript cache, checks the API key, then performs
   `Path.stat()` and `Path.read_bytes()` synchronously before entering the HTTP retry loop.
4. Only the three `httpx.AsyncClient`/POST attempts failed. The successful local-copy log and the
   fact that the handler reached this loop rule out download failure and a transcription-open
   failure for this incident.
5. Uploads occupied about 85 MiB against the 1 GiB limit, and the incident window contains no
   `Uploads cleanup: deleted ...` line. Cleanup did not remove the file. The local-copy log also
   rules out a stale cache hit.
6. `transcribe_audio` returned the transport error; `handle_voice` passed it to `_resolve_media`,
   which filled the reserved buffer entry. `_flush_batch` then sent the text through
   `manager.send`. Forwarding copied that already-rendered text; it did not reopen or delete the
   `.oga` file.

The upload was manually recopied from the retained local Bot API source at `14:28:11` and the
same audio transcribed successfully in a fresh process. That recovery proves the audio and
Deepgram credentials were valid, but it is not used as evidence about the pre-recovery target's
later pathname state.

## Frozen regression evidence

The two regressions were committed before the implementation (`fc38bb6d`):

```text
PYTHONDONTWRITEBYTECODE=1 <python3.12-venv>/bin/python -m pytest -q tests/test_transcription.py
FF                                                                       [100%]
2 failed in 4.18s
```

- `test_transcription_survives_certifi_path_removed_after_import` uses real `httpx` client
  construction after `certifi.where()` is redirected to a deleted path. Before the fix, all three
  attempts returned the incident's bare `FileNotFoundError`; after the fix, the pinned context
  reaches the mocked Deepgram response.
- `test_missing_audio_is_classified_before_http_client_creation` supplies a nonexistent `.oga`
  and an HTTP client that must never be constructed. Before the fix, `Path.stat()` escaped as an
  exception; after the fix, it returns a specific input-file error.

Focused and relevant regression run after the change:

```text
PYTHONDONTWRITEBYTECODE=1 <python3.12-venv>/bin/python -m pytest -q \
  tests/test_tg_bridge.py tests/test_transcription.py tests/test_voice_input.py
199 passed in 15.03s
```

Mutation probes targeted each load-bearing clause independently:

- `_DEEPGRAM_SSL_CONTEXT → True`: marker `1` before and `1` after restore; the certifi-path
  regression failed `1 failed in 4.46s`, then passed after restore (`1 passed in 4.25s`).
- `except OSError → except PermissionError`: marker `1` before and `1` after restore; the
  missing-audio regression failed `1 failed in 4.15s`, then both frozen regressions passed after
  restore (`2 passed in 3.77s`).

A separate constructor-failure probe returned exactly `('', 'transcription service unavailable:
FileNotFoundError: [Errno 2] No such file or directory')`, proving that a genuine service/TLS
failure is still visible and is no longer confused with input-file loss.

## Review decision gate

- Changed production file: `app/transcription.py`.
- Direct consumers: Telegram `handle_voice`/`handle_video_note` in `app/tg_bridge.py` and the
  dashboard `/api/transcribe` route in `app/routes/tg.py`.
- Author metadata: `gpt-5.6-sol`, Codex runtime (`sessions.id =
  b88fdec8-ae90-4b57-8fa5-ab7563dbbf33`).
- Named AC: pinned reusable SSL context survives late certifi-path deletion; missing input is
  classified before HTTP; service/TLS failures remain explicit; no invented transcript; no
  staging/cleanup change; no deploy/restart.
- Strong oracle: the frozen two-test RED above plus the 199-test consumer run.
- Route: mandatory targeted Sol review because this is shared runtime/message delivery. The
  reviewer artifact is `docs/tasks/302/codex-review-impl.md`.
- Result: one Sol round, `APPROVED`, with no blocking findings or suggestions. The review's
  implementation quote was verified against `app/transcription.py` after the artifact completed.
- Independence: the author and mandatory reviewer are both Sol/Codex.
  `cross-family verdict unavailable — Claude weekly quota 100%`. Provenance:
  Orchestra-orchestrator live `/api/usage`
  check at `2026-08-16T14:50:26Z`; `weekly_all=100%`, reset
  `2026-08-18T07:00:00Z`, extra usage disabled. No substitute Sol/Luna pass was run.

## Pre-mortem verification

- Late CA-path deletion under concurrency: 32 clients constructed successfully from the one
  pinned context after `certifi.where()` was changed to a deleted path.
- Genuine missing audio: the frozen regression passed and proves HTTP client construction is not
  reached.
- Existing transcript-cache behavior: a missing path with a cached transcript still returned the
  cached text, preserving the established cache-first contract.
- Downstream consumers: the 199-test Telegram/transcription/dashboard-adjacent suite passed.
- Genuine HTTP/SSL construction failure: the explicit constructor-failure probe returned an empty
  transcript plus `transcription service unavailable: FileNotFoundError: ...`; it did not invent
  transcript text or misclassify the source audio.
