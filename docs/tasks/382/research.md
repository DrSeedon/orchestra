# #382 — escaped/nested Codex MCP argv secret-masking failure

Date: 2026-08-23
Phase: 1 — research and synthetic experiment only
Risk: security / credential confidentiality / persistent multi-project logs

## Question

### Context

Orchestra converts Codex app-server notifications into `AgentEvent` strings, persists completed
events in SQLite, streams both completed and partial events over SSE, can render SQLite history
back into Claude/Codex native history, and mirrors displayed log rows into browser IndexedDB.

### Change under test

Determine why `app.secret_mask._NAMED` fails on the escaped, nested Codex MCP argv form even
though `db.add_log()` calls `mask_secrets()`, then define the smallest security boundary and
RED/mutation oracles that cover every downstream persistence/display copy.

### Baseline

The current flat JSON/TOML/shell cases in `tests/test_secret_mask.py` are green. The relevant
comparison is the production serializer path, where a Codex MCP tool argument is JSON-encoded
around a string that itself contains JSON argv.

### Deciding outcome

A future implementation is acceptable only when a synthetic canary with the exact nested shape:

1. is absent in full from every Orchestra persistent or streamed copy;
2. cannot be recovered from a stale browser IndexedDB mirror after the cache epoch changes;
3. is absent from all Orchestra-created native-history import/export objects; and
4. cannot be copied raw into conditional side sinks such as `tool_errors` or the DB-write failure
   journal path.

Provider-owned native rollout files are an upstream copy created before Orchestra receives the
event. They are separately classified below: #224 prevents the credential-bearing argv source,
while the already completed manual rollout cleanup is containment, not a `secret_mask` fix.

## Safety boundary used in this research

- No production SQLite row, Codex rollout, process argv, browser profile, environment file, or
  credential-bearing file was opened or scanned.
- No real credential value was read, copied, printed, committed, or embedded.
- Experiments used only `SYNTHETIC_382_CANARY_abcdefghijkl` and scratch in-memory/temporary state.
- The already reported manual DB/rollout cleanup and historical aggregate counts are treated only
  as containment evidence. They were not re-scanned or re-derived.
- No application/test file and no live state was mutated. The only repository changes in this
  phase are this research artifact and the worker's personal memory.

## Hypotheses considered

| ID | Hypothesis | Falsifier | Result |
|---|---|---|---|
| H1 | `add_log()` does not call the masker on the affected Codex event. | Trace the exact `mcpToolCall` event to `AgentSession._log` and observe a masker call before `INSERT`. | **REFUTED.** The exact event reaches `_log("tool", ...)`; `add_log()` calls `mask_secrets()` before its insert. |
| H2 | `_QUICK_WORDS` drops the event before `_NAMED` runs. | A synthetic key containing a declared secret word survives even though the prefilter condition is true. | **REFUTED.** The canary's key contains `TOKEN`; `_NAMED.search()` is false after serialization. |
| H3 | `_NAMED` handles escaped quotes in values but not the escaped closing quote after the key. | The three code points immediately after the serialized key are not accepted by `gap`; a flat form remains masked. | **CONFIRMED.** Production-shaped measurement returned `[92, 34, 58]` (`backslash`, `quote`, `colon`) and no match. |
| H4 | The DB is the only downstream copy, so fixing ingress alone closes the incident. | Find a live, history, browser, native, or side-table path that receives the same unmasked content independently. | **REFUTED.** Live broker, native rollout, history conversion, `tool_errors`, journal fallback, HTTP/SSE/TG display, DOM and IndexedDB are distinct copies/consumers. |
| H5 | An IndexedDB version bump or `deleteDatabase()` is the safest invalidation. | A second open tab blocks the upgrade/delete; a same-version read/write clear succeeds without versionchange. | **REFUTED.** This is both the recorded #364 failure and the behavior required by the IndexedDB specification.[7] |

## Findings

### F1 — the miss occurs before value parsing: the key terminator is escaped

**CONFIRMED — direct source trace plus production-shaped synthetic measurement (evidence tier 1).**

The exact producer chain is:

```text
Codex app-server mcpToolCall.arguments (dict containing an argv/config string)
  -> backend_codex._tool_arguments_json(): json.dumps(arguments)
  -> CodexBackend._tool_use(): parse, add _codex_item_id, json.dumps again
  -> AgentEvent.content
  -> AgentSession._handle_event -> _log("tool", content)
  -> db.add_log -> mask_secrets(content)
```

Code evidence:

- `app/backend_codex.py:283-287` JSON-serializes tool arguments.
- `app/backend_codex.py:1752-1760` routes `mcpToolCall` through that serializer.
- `app/backend_codex.py:2135-2155` parses the outer object, adds `_codex_item_id`, and serializes it
  again.
- `app/session.py:2009-2017` sends the resulting string to `_log("tool", ...)`.
- `app/db.py:1265-1299` invokes `mask_secrets()` before the `logs` insert.

The current regex at `app/secret_mask.py:38-53` accepts, after a key, an optional literal quote
followed by `:` or `=`:

```text
(?P<gap>["']?\s*[:=]\s*)
```

It does not accept a backslash before that quote. After outer JSON serialization, the inner key
terminator is structurally `\":`, not `":`. The regex's escaped-quote logic at lines 42-43 applies
only after a match has already entered a quoted **value**; it cannot repair failure in `gap`.

Synthetic measurement (2026-08-23):

```text
codex tool event type= tool_use
canary survives mask= True
_NAMED finds any match= False
codepoints after key= [92, 34, 58]
serialization layers= 1
```

The direct inner JSON control produced `_NAMED=True`, removed the canary, and emitted a mask. The
same string nested once or twice in an outer JSON object produced `_NAMED=False` and left the full
canary unchanged. Therefore `add_log` is called correctly; the transformation returns its input
unchanged.

### F2 — the current suite proves flat forms, not the production producer shape

**CONFIRMED — test execution plus fixture inspection (evidence tier 1).**

Command:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_secret_mask.py -q
........................                                                 [100%]
24 passed in 6.02s
```

`tests/test_secret_mask.py:107-170` covers flat JSON, TOML, shell, URL/DSN/cookie, escaped quotes
inside a value, bearer and PEM. The DB test at lines 80-93 hand-writes a flat JSON fragment. None
constructs the string via `_tool_arguments_json()` plus `CodexBackend._tool_use()`. This is why the
suite is green while the production serializer is red.

Counter-evidence considered: the old Codex TOML-style form with an unquoted key and `=` remains
masked even when the value quotes are escaped. The load-bearing failing shape is specifically the
quoted inner JSON key, where escaping lands **between the key and separator**. The fix/oracle must
not be described as “all escaped argv fails.”

### F3 — there are two SQLite `logs` insert seams now, but both share the same faulty matcher

**CONFIRMED — mechanical completeness search (evidence tier 1).**

`rg -n 'INSERT INTO logs' app --glob '*.py'` returned:

```text
app/db.py:1289
app/initial_deliveries.py:206
```

The comment that `db.add_log` is the only insert is stale after #311. The second insert at
`app/initial_deliveries.py:191-209` also calls `mask_secrets()`, so it is not the cause of the
observed Codex event (which does use `add_log`), but it reproduces the same escaped-key miss for a
nested string arriving as an initial user delivery.

The `initial_deliveries.message` row is itself stored raw earlier at
`app/initial_deliveries.py:156-168`. That table is outside the exact Codex-output route but is an
adjacent plaintext persistence seam that must be named in any claim of global confidentiality.

### F4 — live SSE is an independent path and currently fails on the same shape

**CONFIRMED — source trace plus synthetic measurement (evidence tier 1).**

`AgentSession._handle_event()` sends `stream`, `subagent_stream`, Codex `tool_stream`, `tool_patch`,
`turn_diff`, and subagent events to `live_broker.publish()` without `add_log`
(`app/session.py:1937-1992`). `LiveBroker.publish()` calls the same `mask_secrets()` before both the
subscriber queue and `_accum` replay buffer (`app/live_broker.py:42-67`).

Synthetic results:

```text
broker immediate canary_survives= True
broker replay canary_survives= True
```

Thus the second seam exists and is placed correctly, but shares the same matcher defect. A test of
only the immediate queue is insufficient: moving masking after `_accum` would make current
subscribers safe while leaving late subscribers exposed.

There is a second, independent live-stream defect: masking is applied to each partial payload
before concatenation. If the key, separator, or value is divided across two `publish()` calls,
neither chunk contains a complete match; the first chunk may already have been delivered before
the second proves that it was secret material. Because the grammar has unbounded key/value
lengths, no fixed trailing look-behind window can prove a prefix safe. Under #382's blocking rule,
Phase 2 must either buffer a complete logical live event and redact before first delivery, or
fail closed by withholding arbitrary partial content until its completed DB event arrives.
Per-chunk masking alone cannot be the accepted design.

### F5 — completed-log display paths do not redact on egress

**CONFIRMED — source trace (evidence tier 2: primary source code).**

The four DB getters return stored `content` unchanged:

- `get_logs` — `app/db.py:1732-1750`;
- `get_log` — `app/db.py:1752-1758`;
- `get_logs_before` — `app/db.py:1760-1798`;
- `get_logs_sync` — `app/db.py:1809-1853`.

They feed:

- SSE initial history and DB polling (`app/routes/sessions.py:484-531`);
- REST history, mirror sync, and full-row fetch (`app/routes/sessions.py:536-575`);
- Telegram's direct DB poll (`app/tg_bridge.py:3133-3155`);
- browser DOM rendering (`app/static/js/app.js:1077-1104`, `2383`);
- browser IndexedDB writers (`app/static/js/app.js:658-687`, `2298-2306`, `2322-2328`).

Ingress correctness is still mandatory because raw DB persistence is itself blocking. An egress
mask is defense in depth for missed/legacy rows, not a substitute for the DB RED oracle.

### F6 — conditional side sinks can create additional plaintext copies

**CONFIRMED — source trace (evidence tier 2).**

1. A failed tool result is copied to `tool_errors.error_text` before the main log write
   (`app/session.py:1969-1982`; `app/db.py:2165-2186`). No masker is called. The reliability
   analytics API returns the latest raw error and `analytics.js` renders it
   (`app/usage_analytics.py:518-582`; `app/static/js/analytics.js:480-488`).
2. If `add_log` fails, the completion callback logs the **original** `content` (first 200 chars) to
   the service journal, not the masked candidate (`app/session.py:4463-4484`). This is a new
   persistent plaintext copy exactly when the primary persistence path is unhealthy.
3. Initial-delivery requests store their original `message` in `initial_deliveries` before the
   separately masked `logs` insert (`app/initial_deliveries.py:156-168`, `191-209`).
4. `sessions.last_summary` is persisted without the canonical masker. It is not reached directly
   by the affected tool-result event, but a model-produced summary can repeat log text. The legacy
   `_build_runtime_handoff()` at `app/session.py:2830-2865` also consumes user/assistant log text
   from `get_logs()` without `runtime_history._sanitize()`.
5. RAG is a derived SQLite copy only for `user_message` and `text`, not for the affected
   `tool`/`tool_result` row (`app/rag.py:547-598`). It stores plaintext chunks in `log_chunks` and
   `fts_logs` (`app/rag.py:512-533`). Therefore the exact incident row is excluded, but a user or
   assistant repetition of the escaped form can be duplicated there.

These paths are why “mask at the single logs insert” is no longer a complete system invariant.
Under the task's global rule, every Orchestra-created persistent copy named here is in scope even
when it is adjacent to, rather than directly reached by, the original Codex tool event. Provider-
owned native rollout storage remains the separately stated upstream boundary.

### F7 — native-history import/export has a second, weaker named-secret regex

**CONFIRMED — source trace plus synthetic measurement (evidence tier 1).**

`runtime_history._sanitize()` uses `_NAMED_SECRET` at `app/runtime_history.py:187-212`, independent
of `app.secret_mask._NAMED`. It likewise requires the quote immediately after the key and therefore
misses `\"KEY\":`.

Consumers include:

- `render_claude_history()` and `render_codex_history()` via `_normalize_history`
  (`app/runtime_history.py:911-1080`, `1095-1279`);
- runtime handoff recent messages and metadata (`app/runtime_history.py:274-380`);
- operator-authorized raw-event resolution (`app/runtime_history.py:561-613`);
- handoff packets persisted as `runtime_handoffs.packet_json` after construction.

Synthetic results from one raw nested row:

```text
claude import canary_survives= True
codex import canary_survives= True
handoff export canary_survives= True
```

This is a second owner of the same security rule. Fixing only `_NAMED` stops new main-log rows but
does not protect legacy/manual rows passed to native history or handoff export. Cosmetic wording
of the replacement does not matter; one canonical structural recognizer should own the rule.

### F8 — Codex native rollout is upstream of Orchestra masking

**CONFIRMED for path existence; LIKELY for exact provider write ordering (source code plus supplied
containment evidence).**

`CodexBackend` locates the current provider rollout under its managed
`$CODEX_HOME/sessions/**/*<thread>.jsonl` (`app/backend_codex.py:2178-2194`). The app-server owns
that file and emits the notification from which Orchestra later creates `AgentEvent.content`.
Therefore `mask_secrets()` cannot prevent the provider-native copy: it runs after the event is
received.

For the exact incident, the permanent prevention already belongs to #224: MCP credential values
must not be placed in process argv. The operator-reported manual rollout cleanup removes an old
copy but does not prove `_NAMED` or downstream client caches are fixed. A generic requirement that
arbitrary command output never appear in provider-native history would require disabling or
rewriting provider persistence and is outside this seam; no such architecture change is proposed
without separate authorization.

### F9 — browser IndexedDB preserves any raw row independently of later DB cleanup

**CONFIRMED — source trace and #364 supplied operational evidence (evidence tier 1/2).**

The browser opens database `orchestra`, version 1, with `logs` and `meta` stores
(`app/static/js/app.js:559-601`). Rows arrive through two writers:

- periodic `/api/logs/sync` (`app/static/js/app.js:618-689`);
- history-page `_storePut()` after REST fetch (`app/static/js/app.js:2296-2328`).

`_storeRead()` can render those rows before any network response (`app/static/js/app.js:714-731`,
`2350-2384`). Server-side cleanup therefore does not invalidate an already mirrored row. The only
existing clear occurs when local watermark is greater than the server's global max id; content
cleanup that preserves ids does not trigger it (`app/static/js/app.js:660-667`).

The supplied #364 evidence rejects two tempting fixes:

1. bumping the IndexedDB version is blocked by another open tab;
2. starting cleanup from `open().onsuccess` through the shared `_storeTx`/open promise deadlocks.

The first is also normative IndexedDB behavior: an upgrade cannot proceed until other clients
close, while overlapping same-version read/write transactions are serialized.[7]

## Persistence/display inventory

| Copy / consumer | Persistent? | Exact affected Codex event reaches it? | Existing protection | Current synthetic result / status |
|---|---:|---:|---|---|
| Codex provider rollout JSONL | Yes | Yes, before Orchestra conversion | #224 removes credentials from managed argv; filesystem permissions | Upstream of `mask_secrets`; old copy handled only by manual containment |
| `LiveBroker` subscriber queue | Ephemeral display | Yes for stream/tool-stream forms | `mask_secrets` before enqueue | **RAW survives** nested form |
| `LiveBroker._accum` replay | Process-memory replay | Yes for `stream` | Same call before accumulation | **RAW survives** nested form |
| SQLite `logs` through `db.add_log` | Yes | Yes for completed tool/tool_result | `mask_secrets` before insert | **RAW survives** nested form |
| SQLite `logs` through initial delivery | Yes | No for the incident; same form possible as user input | Same `mask_secrets` | Same matcher fails; second insert invalidates “one insert” claim |
| SQLite `initial_deliveries.message` | Yes | No | None | Adjacent raw input copy |
| SQLite `tool_errors.error_text` | Yes | Only when result is marked error | None | Raw side copy; displayed in analytics |
| systemd/service journal on log-write failure | Yes | Yes if DB write fails | None on original callback content | Raw first 200 chars possible |
| REST `/logs`, `/logs/sync`, `/api/logs/{id}` | Network display | Yes from DB | Trusts ingress; no egress mask | Raw if DB row is raw |
| SSE initial/DB rows | Network display | Yes from DB | Trusts ingress | Raw if DB row is raw |
| Telegram DB poll | External display/history | Yes from DB | Trusts ingress | Raw if DB row is raw |
| Browser DOM / OS notification consumers | In-memory/display (OS may retain notifications) | Yes from SSE/REST | Trusts server content | Raw if upstream raw |
| Browser IndexedDB `logs` | Yes, browser-local | Yes from sync/history REST | No content epoch | Raw remains after server cleanup |
| Claude/Codex history import objects | Becomes provider-native persistence | Yes for DB snapshot | `_NAMED_SECRET` in `_sanitize` | **RAW survives** nested form |
| Runtime handoff packet/event export | SQLite packet + network/model input | Tool rows by hash/ref; user/text/events by sanitized content | `_sanitize` | **RAW survives** when content is exported/resolved |
| `sessions.last_summary` / legacy handoff summary | Yes / model input | Not directly for tool result; possible repetition | No canonical mask | Adjacent raw-copy risk |
| RAG `log_chunks` / `fts_logs` | Yes, derived | Not for tool/tool_result; yes for repeated user/text | Trusts `logs` | Conditional adjacent raw-copy risk |

## Safe browser cache invalidation design

### Required mechanism: content-security epoch, same IndexedDB version

Use an application-owned strictly monotonically increasing `LOG_CONTENT_EPOCH`, separate from the
IndexedDB schema version. The highest epoch ever accepted is a floor: rollback to a lower epoch
must fail closed rather than repopulate the mirror.

1. Keep `indexedDB.open("orchestra", 1)`. Do not invoke a versionchange and do not delete the
   database as the primary mechanism.
2. Put the current content epoch in the initial dashboard HTML and in every log-bearing server
   response/handshake (`/api/logs/sync`, REST history, SSE `__session`). A new page therefore knows
   the required epoch before its first mirror read; a long-lived page learns later changes.
3. After `open().onsuccess` assigns the raw `IDBDatabase`, run a **dedicated direct** `readwrite`
   transaction spanning `logs` and `meta`. Do not call the shared `_storeTx` from the unresolved
   `_storeOpen` promise. Read `meta.log_content_epoch`; on mismatch, execute `logs.clear()`, clear
   stale mirror metadata, and write the new epoch in that same transaction.
4. Resolve the store-ready barrier only after that transaction's `oncomplete`. No `_storeRead`,
   `_storePut`, or render may run before the barrier.
5. Serialize **all** epoch transitions and row writes behind one client-side promise/mutex. For a
   response/handshake epoch `R` and highest accepted epoch `H`: `R < H` is discarded without any
   write; `R == H` may write; `R > H` atomically clears `logs`/stale metadata, commits `R` as the
   new floor, and only then writes rows labelled `R`. A delayed epoch-N response completing after
   an epoch-N+1 clear therefore cannot roll metadata back or repopulate old rows.
6. Apply the same ordering rule to `_storeSync`, REST `_storePut`, and SSE events. Reset in-memory
   chat content and refetch only from a response at the accepted epoch.
7. Notify sibling new-code tabs with `BroadcastChannel`; each closes/reopens its connection behind
   the same barrier. A `storage`-event fallback can request reload, but is not the data-erasure
   oracle.

Why this is compatible with #364:

- no database version bump, so another tab does not block an upgrade;
- no `deleteDatabase()` while another connection is open;
- no recursive wait through `_storeTx` while `_storeOpen` is unresolved;
- same-version overlapping read/write transactions serialize by specification, clear+epoch update
  commit atomically, and the application ordering barrier prevents stale network completions from
  undoing that database ordering.[7]

### Current-rollout limitation and safe one-time procedure

A tab running code from before the epoch mechanism cannot receive a future `BroadcastChannel`
listener retroactively and can retain already-rendered text in memory or rewrite its old mirror.
No same-version code loaded in another tab can mechanically make that old page's in-memory copy
unreachable. For this first security rollout, the hard gate must therefore be operational,
explicit, and a precondition of the stated cache guarantee:

1. stop/finish all open dashboard tabs for the origin;
2. deploy the server + new client code and complete the already planned server/native containment;
3. open one fresh tab, let the same-version epoch transaction complete, then verify with a
   synthetic browser fixture that no stale row is present before chat rendering;
4. only then reopen additional tabs.

The acceptance evidence for this one-time gate is operator confirmation that every pre-feature
dashboard tab for the origin was closed before the reset, followed by a fresh-page synthetic
IndexedDB probe. Without that confirmation, the claim “stale browser copies are unreachable” must
remain **UNCERTAIN** and deployment is blocked.

`Clear-Site-Data: "storage"` from a dedicated one-shot HTTPS response may be used after old tabs
are closed as defense in depth: the W3C algorithm includes IndexedDB, local/session storage and
service workers.[6] It is **not** the primary oracle because the storage directive itself deletes
IndexedDB databases, active contexts can race/rewrite, and it clears more UI state than the log
mirror. `"executionContexts"` also cannot be relied upon: the W3C draft defines it, but Firefox
removed support and current Chromium source does not expose it in the same data-type enum.[6][8][9]

## RED and mutation oracle design

No tests were added in Phase 1. These are the required Phase 2 RED tickets/oracles.

### O1 — exact Codex producer serialization

- File: `tests/test_secret_mask.py`
- Test: `test_t382_codex_nested_mcp_argv_is_masked_after_real_serializer`
- Construct the inner MCP argv JSON with `json.dumps`, pass it as a value inside a synthetic Codex
  MCP argument dict, then use `_tool_arguments_json()` and `CodexBackend._tool_use()`.
- Assert the complete canary is absent, a mask is present, `_codex_item_id` and unrelated argv
  text remain, and both one- and two-layer nested variants are covered.
- Current RED: canary survives; `_NAMED.search()` is false.
- Mutation: restore today's `gap` or remove handling for a backslash-escaped key terminator. The
  test must return red. A flat hand-written string is not an acceptable substitute.

### O2 — all main SQLite ingress seams

- File: `tests/test_secret_mask.py` plus `tests/test_initial_deliveries.py` if the global seam is
  retained.
- Tests: `test_t382_add_log_masks_nested_codex_event_in_raw_sqlite` and
  `test_t382_initial_delivery_direct_insert_uses_same_canonical_mask`.
- Query the scratch SQLite tables directly, not through an egress masker. Assert no full canary in
  `logs.content`.
- Separately decide whether `initial_deliveries.message` is allowed to retain secrets. Under the
  stated blocking rule it is not; then its raw column needs its own RED test or a documented
  encrypted/omitted representation.
- Mutations: no-op `content = mask_secrets(content)` in each insert independently. Each mutation
  must turn its own test red.

### O3 — live queue and replay

- File: `tests/test_secret_mask.py`
- Parameterize every arbitrary-content live branch from `AgentSession._handle_event`:
  `stream`, `subagent_stream`, `thinking_stream`, `tool_stream`, `tool_patch`, `turn_diff`, and
  `subagent_event`. A broker-level invariant test may cover their shared sink, but wiring tests
  must prove every branch actually reaches that invariant.
- For each logical stream class, split the synthetic key/separator/value at every boundary around
  the escaped key terminator and across multiple `publish()` calls. Assert no immediate subscriber
  receives a raw prefix that later becomes part of the full canary, and late replay contains no
  full canary.
- The accepted implementation must buffer to a known logical completion or withhold partial
  content. A fixed-size suffix buffer is not sufficient for the unbounded grammar.
- Mutations:
  1. remove broker masking — immediate and replay tests red;
  2. move masking after `_accum` — immediate may stay green, replay must turn red;
  3. restore current `_NAMED` — all nested cases red;
  4. flush the first chunk before logical completion — the split-boundary test must turn red;
  5. bypass the shared sink from any one event branch — that branch's wiring test must turn red.

### O4 — side-table and failure-journal copies

- Files: `tests/test_secret_mask.py`, `tests/test_usage_analytics.py` as appropriate.
- Tests:
  - failed tool result reaches `tool_errors`; direct scratch SQL and analytics JSON contain no
    full canary;
  - force `add_log` to raise and capture the logger; journal message contains no full canary.
- Mutations: pass raw `event.content` to `tool_error_add`; log original callback content on write
  failure. Each must turn its test red.

### O5 — egress defense for a deliberately raw legacy row

- Files: `tests/test_logs_sync.py`, route tests, and a focused TG consumer test.
- Seed one scratch `logs` row by direct SQL with the synthetic nested form (this deliberately
  bypasses ingress). Assert `get_logs`, `get_logs_before`, `get_log`, `get_logs_sync`, REST, SSE
  initial/DB polling, and the TG formatted output never contain the full canary.
- This does not satisfy O2: raw SQLite persistence must still be red.
- Ownership: one `db.py` row-sanitization helper is the canonical completed-log egress boundary;
  every getter (`get_logs`, `get_logs_before`, `get_log`, `get_logs_sync`, and the history snapshot
  getter where applicable) must call it. REST/SSE/TG tests are wiring tests, not duplicate masking
  implementations.
- Mutation: make the canonical helper a no-op; the getter oracle must fail. Separately bypass the
  helper in each getter; that getter's wiring test must fail. Do not demand independent masking in
  REST/SSE/TG consumers when their canonical DB boundary is intact.

### O6 — native history import and handoff export

- Files: `tests/test_native_history_import.py`, `tests/test_runtime_history.py`.
- Feed raw synthetic rows directly to `render_claude_history`, `render_codex_history`,
  `build_runtime_state_packet`, and `resolve_runtime_handoff_events`; recursively serialize each
  result and assert no full canary.
- Assert hashes/reference ids remain stable where content is intentionally represented only by a
  hash.
- Mutation: replace the canonical recognizer with today's `_NAMED_SECRET`; all escaped/nested
  cases must turn red.

### O6b — every secondary Orchestra persistent sink named by the inventory

- Files: focused tests for `app/initial_deliveries.py`, `app/session.py`, `app/rag.py`, and runtime
  handoff persistence.
- Direct-storage assertions, using only synthetic input:
  1. `initial_deliveries.message` contains no full canary. Phase 2 must choose an explicit
     fail-closed behavior: reject a secret-shaped durable task or persist a masked/encrypted
     representation; silently retaining plaintext is not an option.
  2. `sessions.last_summary` contains no full canary after both Claude-summary and native-Codex
     summary/handoff paths.
  3. `RagMemory.index_log()` produces neither `log_chunks.text` nor `fts_logs.text` containing the
     full canary when a user/text row repeats the nested form.
  4. the actual `runtime_handoffs.packet_json` SQLite column contains no full canary after packet
     preparation, not merely in the in-memory builder result.
- Mutate each sink's canonical masking/rejection independently; only its direct-storage oracle
  should turn red. These tests close F6's global confidentiality inventory rather than extending
  the provider-owned rollout boundary.

### O7 — IndexedDB epoch, two tabs, no pre-render read

- File: new focused Playwright test (for example `tests/test_log_cache_security.py`), using the
  existing isolated dashboard fixture and synthetic rows only.
- Scenarios:
  1. create database `orchestra` version 1 with an old epoch and canary row; load the new client;
     assert the canary is absent from IndexedDB and DOM before history rendering;
  2. keep a second page's version-1 connection open; new page completes invalidation without
     `blocked` or timeout;
  3. abort the invalidation transaction; epoch must not advance while the canary remains;
  4. trigger a later epoch change; both new-code tabs clear/refetch;
  5. delay an epoch-N REST/sync response, accept and clear on epoch N+1, then release N; the old
     response must be discarded and must not lower metadata or put rows;
  6. interleave `_storeSync`, `_storePut`, and SSE at N/N+1 to prove they share one ordering
     barrier;
  7. reload and confirm the stale canary cannot reappear.
- Mutations:
  - omit `logs.clear()` — canary remains;
  - write epoch without clearing in the same transaction — canary remains under a current marker;
  - resolve store-ready before transaction completion — DOM reads canary;
  - bump IndexedDB version — the second-tab scenario reports `blocked`/times out;
  - call `_storeTx` through the unresolved open promise — readiness test times out, reproducing
    #364's deadlock;
  - accept `R != H` without distinguishing lower/higher epochs — delayed N repopulates after N+1;
  - let any writer bypass the epoch ordering barrier — its interleaving case repopulates stale
    content;
  - omit sibling notification — the second tab retains/render stale content.
- Operational acceptance for the first rollout is intentionally not faked by Playwright: record
  operator confirmation that all pre-feature tabs were closed. Without it, report the old-tab
  erasure guarantee as unproven and block rollout.

### O8 — source prevention for provider-native rollout

- Existing #224 tests remain the oracle: managed Codex argv contains no MCP env/value fragments,
  and MCP configuration is read from the private managed config.
- Add only a structural synthetic assertion if the current tests do not use the complete
  `_codex_command()` output. Do not start a live provider or inspect real rollout content.
- Mutation: reintroduce an MCP env override in `_mcp_config_args()`; the argv test must fail.

### Focused commands planned for Phase 2/3

```text
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_secret_mask.py -q
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_native_history_import.py tests/test_runtime_history.py -q
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_logs_sync.py tests/test_initial_deliveries.py -q
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_log_cache_security.py -q
```

Each named test must be committed RED in Phase 2 and must fail on the missing confidentiality
behavior, not on import, collection, provider availability, or a live credential dependency.

## Recommended implementation boundary for planning

This is not an implementation plan; it bounds what Phase 2 must decide.

1. Make `app.secret_mask` the canonical structural masker for flat and escaped/nested named
   values. Preserve the fast prefilter as a proven superset.
2. Reuse that canonical recognizer in `runtime_history` instead of maintaining the weaker
   `_NAMED_SECRET` rule. Replacement wording/tail fidelity is non-essential; parse safety and no
   full plaintext are essential.
3. Apply the canonical masker before every in-scope persistent ingress (`logs`, conditional
   `tool_errors`, summaries, handoff packets, RAG-derived text, failure journal, and durable initial
   deliveries via explicit reject/mask/encrypt semantics).
4. Do not treat per-chunk broker masking as sufficient. Buffer each arbitrary-content live event
   to a known completion or withhold partial content; then redact before queue/accumulation.
5. Add one canonical `db.py` egress helper for deliberately raw legacy rows without weakening the
   raw-SQL ingress oracle; keep REST/SSE/TG as wiring consumers.
6. Introduce the ordered same-version browser log-content epoch and the one-time old-tab rollout
   gate.
7. Keep #224's private-file argv prevention as the native-rollout control; do not invent a vault
   integration or rewrite provider history as part of #382.

## Counter-evidence and limitations

- Flat JSON/TOML/shell tests all pass; the defect is not a total masker failure.
- Escaped quotes **inside a matched value** are already handled. The failure is the escaped key
  terminator before `:`.
- The historical old Codex TOML argv form with an unquoted key and `=` is masked in the synthetic
  control. The affected nested JSON form must stay the explicit oracle.
- Fixing `app.secret_mask._NAMED` alone stops the measured `add_log`/broker failure but leaves
  `runtime_history._NAMED_SECRET`, side tables, journal fallback, and browser stale copies open.
- An egress-only mask can make the UI look safe while raw SQLite remains; O2 prevents that false
  green.
- `Clear-Site-Data: "storage"` is useful defense in depth but too broad and internally based on
  origin storage deletion. It is not accepted as the multi-tab oracle.
- A pre-feature tab cannot be taught the new epoch protocol without reload. This is why the first
  rollout needs an explicit operator-confirmed close/reopen gate even though future epoch changes
  are automatic; without that evidence, old-tab erasure is not claimed.
- No empirical browser test was run in Phase 1 because the requested phase forbids app/test/live
  mutation. The cache design is therefore **LIKELY** until the two-tab RED oracle is committed and
  observed.
- No production completeness scan was performed. The operator's existing DB/rollout cleanup may
  have missed a browser, side table, RAG repetition, or journal copy; this document does not claim
  otherwise.

## Affected files and risks for later phases

Potential code surface (no changes in Phase 1):

- `app/secret_mask.py` — escaped structural grammar and canonical ownership;
- `app/runtime_history.py` — remove/route the duplicate named-secret recognizer;
- `app/db.py` — `logs` egress defense and `tool_errors` ingress;
- `app/initial_deliveries.py` — second `logs` insert and raw delivery payload decision;
- `app/live_broker.py` — pre-queue/pre-accum invariant;
- `app/session.py` — raw failure logger and legacy history summary;
- `app/routes/sessions.py` — cache epoch on log-bearing responses/SSE handshake;
- `app/static/js/app.js` — atomic same-version epoch barrier and sibling notification;
- `app/usage_analytics.py` / analytics frontend — consumer regression only;
- tests listed in O1-O8.

Main edge cases:

- zero, one, and multiple JSON escape layers;
- quoted key with spaces before `:` and escaped quoted value;
- escaped quote inside the credential value;
- unrelated content after the nested value must remain readable;
- fast prefilter must remain a superset;
- no partial masker may corrupt outer JSON enough to break tool-card parsing (cosmetic inner argv
  fidelity is not required);
- split SSE chunks are a blocking defect of per-chunk matching, not an accepted limitation;
  partial content must be buffered to logical completion or withheld;
- same-version IndexedDB invalidation must commit clear+epoch atomically and cannot render before
  completion, and lower-epoch delayed responses must be discarded behind a shared ordering
  barrier;
- old tabs, in-flight old responses, and crash between rollout steps;
- secondary stores must not become a new plaintext owner.

## Conclusions

1. **Root cause: CONFIRMED.** Codex serializes an MCP argument object around an argv/config string,
   producing `backslash + quote + colon` after the inner secret key. `_NAMED.gap` permits a quote
   but not its escape prefix, so the matcher never reaches the value. `add_log` calls the masker;
   the masker returns the original string.
2. **Blast radius: CONFIRMED for Orchestra downstream paths.** The same canonical failure affects
   DB ingress and live broker; a duplicate weak regex affects native-history import/export; raw DB
   rows flow unchanged to REST/SSE/TG/DOM/IndexedDB; split partials evade per-chunk matching; and
   conditional/derived side sinks can create additional copies.
3. **Containment vs fix: CONFIRMED.** Manual DB/rollout cleanup removes known old copies but neither
   repairs the matcher nor invalidates existing browser IndexedDB. It is evidence of incident
   containment only.
4. **Cache design: LIKELY pending browser RED.** A strictly ordered content epoch cleared by an
   atomic same-version `logs+meta` transaction avoids both rejected #364 paths and rejects delayed
   lower-epoch responses. The first rollout still requires operator-confirmed closure of all
   pre-feature tabs; future epoch changes can coordinate new-code tabs.

## Adversarial review outcome

Two Sol rounds (the prose ceiling) were run because this is a secrets/security surface without a
strong existing oracle. Round 1 confirmed the serializer-to-`_NAMED` root cause and raised four
blocking gaps. All four were verified against current code and accepted into this revision:

1. split partial chunks bypass per-chunk masking -> O3 now requires logical buffering/withholding
   and split-boundary RED cases;
2. delayed lower-epoch responses could repopulate after a higher-epoch clear -> the cache protocol
   now has a highest-observed floor and one serialized barrier for every writer;
3. live branch coverage was incomplete -> O3 now names all seven arbitrary-content branches and
   their wiring checks;
4. secondary persistent sinks lacked direct oracles -> O6b now covers initial deliveries,
   summaries, RAG plaintext tables, and the persisted handoff packet.

Both suggestions were also accepted: O5 names the canonical DB egress owner, and the one-time
pre-feature-tab gate is explicitly operational rather than falsely claimed as mechanically
provable. Round 2 marked all four blockers and both suggestions `FIXED` and returned `APPROVED`.
The evidence criterion is satisfied by the reviewer's verbatim line “A fixed-size suffix buffer is
not sufficient for the unbounded grammar.” at this document's O3. Review evidence:
`docs/tasks/382/review-research.md`.

## Review decision gate

- Changed artifacts: this research document and personal worker memory only; no executable file.
- Consumers of the conclusions: Phase 2 tickets for secret masking, history conversion, log
  egress/side sinks, and browser cache invalidation.
- Author runtime: Codex. The exact author model identifier is not exposed in the worker-visible
  session metadata, so it is not used to lower risk.
- Exact AC: the four deciding outcomes under `Question`, using only the synthetic canary.
- Existing named check: `/home/kesha/orchestra/.venv/bin/python -m pytest
  tests/test_secret_mask.py -q` -> `24 passed in 6.02s`; it is not a strong oracle because it omits
  the production serializer and browser cache.
- Route: direct Sol review. Security/secrets is a high-risk floor and no strong independent
  deterministic oracle exists yet.

## Sources

1. `app/secret_mask.py`, `app/backend_codex.py`, `app/session.py`, `app/db.py`,
   `app/live_broker.py` — current primary source code, inspected 2026-08-23.
2. `app/runtime_history.py`, `app/routes/sessions.py`, `app/static/js/app.js`,
   `app/tg_bridge.py`, `app/usage_analytics.py`, `app/rag.py`, `app/initial_deliveries.py` — current
   persistence/display source code, inspected 2026-08-23.
3. Synthetic producer/mask/DB/broker/history experiment recorded in this session, 2026-08-23;
   no production data used.
4. `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_secret_mask.py -q` — 24 passed,
   6.02 s, 2026-08-23.
5. `docs/tasks/224/research.md:193-232` and `docs/tasks/224/report.md:98-109` — historical aggregate
   and prior limits; values were not opened or reproduced in #382.
6. [W3C Clear Site Data](https://www.w3.org/TR/clear-site-data/) — `storage` and
   `executionContexts` algorithms (primary specification).
7. [W3C Indexed Database API 3.0](https://www.w3.org/TR/IndexedDB/) — multi-client upgrade blocking
   and read/write transaction serialization (primary specification).
8. [Mozilla Firefox 68 release notes](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Releases/68)
   — official record that Firefox removed `executionContexts` support.
9. [Chromium `clear_site_data_utils.h`](https://chromium.googlesource.com/chromium/src/+/9c20cc8998db965d14380e3d9bc0c70cc1e52cf7/content/public/browser/clear_site_data_utils.h)
   — current official source enum for implemented clear-site-data types; used only as
   counter-evidence against relying on `executionContexts`.
10. User-supplied #382/#364 project context — manual DB/rollout containment and the two rejected
    IndexedDB approaches. No live artifacts were read.
