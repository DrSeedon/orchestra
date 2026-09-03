# research-ox-alpha — personal memory

- Before a live OpenRouter harness evaluation, check `MemAvailable` and credential presence
  before even fetching metadata; the #283 protocol correctly stopped at 3,666,888 KiB (<4 GiB)
  with no HTTP attempt.
- `HarnessBackend.connect()` creates `data/harness-sessions`; a read-only production-shaped
  reproduction must isolate the session store in process memory or an explicitly permitted
  fixture path before connecting.
