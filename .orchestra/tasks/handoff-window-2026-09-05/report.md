# Codex handoff window — companion to packet fix #507

Confirmed locally: the carried Codex config requests model_context_window=872000.
Its native models_cache entry for Astra and Sol has context_window=272000,
max_context_window=872000 and effective_context_window_percent=95.
The pre-connect handoff manifest nevertheless used the hardcoded 258400 fallback.

The Codex manifest now resolves an explicitly configured window against the exact model's
catalog maximum and effective percentage: min(872000,872000)*95//100 = 828400.
Absent/invalid metadata keeps the existing fallback; no startup is blocked by this lookup.
Live/observed runtime state takes precedence. A cold resume descriptor is not treated as
telemetry merely because it already contains a thread id.
No tokenizer dependency or bytes/4 approximation was added; reserves and overflow guards remain.

Validation: 169 tests passed across test_codex_handoff_window, test_backend_codex,
test_runtime_handoff_v2 and test_runtime_handoff_recovery, with NOTIFY_SOCKET removed,
MemoryMax=2G and nice=15. The fixture that assumes a small target must run with isolated
CODEX_HOME, not inherit the laptop's deliberately enlarged context configuration.
Frozen acceptance code was not changed. Two existing Starlette cookie deprecation warnings.

Read-only combined check on handoff 1112dbe9-af1b-5f8d-9b9e-e9a09d4170e6 using the
in-progress #507 packet builder (no service or database write):
- Source: 32,006 log rows; system prompt 99,289 bytes.
- Model-visible packet: 3,648,964 → 113,553 serialized UTF-8 bytes.
- Warm manifest candidate upper bound: 245,341; budget: 728,304; headroom: 482,963.
- Recent-message component: 93,785, retained; fits=True without cold fallback.
- Tool effects: 15,975 bytes; bounded refs: 2,019 bytes; raw history remains in SQLite.
The script uses a small placeholder MCP configuration, so this is a packet/window regression
reproduction, not a complete live-target proof or exact provider token count.

This branch only changes backend_codex.py and adds focused tests. Packet projection,
deduplication and ledger integrity changes belong to the already-running fix-handoff-packet
worker. Both fixes are needed for this large historical session.
No model switch, service restart, main merge or VPS deployment was performed.
