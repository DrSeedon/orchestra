# V-1058 — voice word confidence

Implemented in `app/transcription.py`. The shared transcription result now marks
words with `confidence < 0.65` as `слово[?]` and adds exactly one short Russian
header when any word is marked. Telegram's existing `handle_voice` passes this
text through to agent delivery; dashboard transcription shares the same result.
Confident transcripts remain byte-for-byte unchanged. Punctuation, case and
whitespace are retained when `punctuated_word` tokens align with the transcript.
If Smart Format combines spoken words into an entity and alignment fails, the
formatter uses the provider's full word sequence, retaining every marker instead
of guessing which span of the formatted entity is uncertain.

Threshold rationale: Deepgram's [word-confidence documentation](https://developers.deepgram.com/docs/confidence)
recommends about 0.65 for high-precision error detection. This is a documented
initial cutoff, not a measurement on the owner's audio. Raising it catches more
errors but also marks more correct words. A high confidence score is still no
guarantee of correctness. The same documentation says confidence does not expose
the second-best word; no extra alternatives are available through this signal.
The Nova-3 request and its parameters are unchanged; no second request, new
provider, model switch or extra charge was introduced.

Cache format stays `dict[str, str]`: new entries contain the readable annotated
text; old strings load unchanged. Cache hits require neither an API key nor a
readable audio file, do not add a second header, and do not add another cost
record. Existing strings cannot gain word confidence retroactively, so old cached
transcripts remain unmarked. Missing word scores are left unknown, without
inventing confidence. Existing retry, input-error and cost-accounting paths remain.

Added persisted Deepgram-shaped JSON fixtures (`high.json`, `low.json`, plus a
legacy cache) and pytest coverage in `tests/test_transcription.py`, with an actual
`handle_voice` delivery test in `tests/test_tg_bridge.py`. Fixtures are synthetic
saved response examples, not private recordings or measured production samples.
Updated `CHANGELOG.md`.

## Verification on the hub

- Required command attempted:
  `uv run --frozen python -m pytest tests/test_transcription.py tests/test_tg_bridge.py tests/test_voice_input.py -q`
  — exit **127**: `uv: not found on the hub and not inside a Mutagen-synced project (cannot forward via on-remote)`.
- Available fallback: Python **3.12.3**; `pytest`, `pytest_asyncio`, `httpx` and the
  rest of `app` are absent from this private copy. No packages were installed.
- Ran `PYTHONDONTWRITEBYTECODE=1 python3 .orchestra/tasks/V-1058/offline_check.py`
  — **13 tests passed**. This stdlib-only fallback executes the actual
  transcription module with HTTP/TLS construction and accounting stubs. It checks
  high/low responses, exact request count and parameters, cost arguments,
  persisted/reloaded mixed old/new cache, cache hits without key/audio, strict
  threshold boundary, absent scores, repeated words, punctuation, Smart Format
  fallback, empty transcript, missing audio, upstream errors and corrupt-cache
  recovery. It also executes the real `handle_voice` body extracted via AST with
  its boundary dependencies mocked; the complete aiogram module was not imported.
  This is **not** the required uv/pytest run and does not validate real TLS,
  aiogram initialization, SQLite accounting or dashboard routing.
- Logs: `offline-check.log`, `required-check.log`, `review-check.log`.
- No real Deepgram, Telegram or other provider calls; no live database or service
  was used. No restart, deployment or Git operation was performed.

Imported module:
`<hub-copy>/app/transcription.py`.
Imported `app` is a namespace package here (`app/__init__.py` was not supplied),
whose absolute search path is
`<hub-copy>/app`.

## Commands for the orchestrator in the complete checkout

```sh
uv run --frozen python -c 'import app; print(app.__file__)'
uv run --frozen python -m pytest tests/test_transcription.py tests/test_tg_bridge.py tests/test_voice_input.py -q
uv run --frozen python scripts/run_tests.py
```

Required targeted pytest and full-suite checks remain unrun. Python behavior on
the VPS changes only after the normal service lifecycle; code on disk does not
prove that a running service has loaded it.
