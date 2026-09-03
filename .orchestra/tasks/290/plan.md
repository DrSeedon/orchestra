# #290 — Production-safe cross-runtime handoff

## Outcome

Replace the current optimistic native-history import / prose-summary switch with one
server-owned transaction. A switch is not visible as complete until the target has:

1. accepted a deterministic state packet under an explicitly untrusted transcript boundary;
2. passed a mechanically tools-disabled ingress checksum;
3. passed a separate, server-side capability check; and
4. fit the target's complete model-visible context budget.

The source session remains authoritative until an atomic database confirmation. There is one
bounded fallback candidate and no second retry. A failure or ambiguous recovery state blocks the
switch visibly; it never commits a fresh, amnesiac target.

This plan implements the recommendation accepted in
`docs/tasks/287/research.md`. It does not transfer or reconstruct hidden reasoning.

## Baseline and invariants

The current cross-runtime Claude/Codex paths in `AgentSession._change_model_locked()` render all
Orchestra logs into a target-native transcript, disconnect the source, then connect and commit the
target. Grok and other generic runtimes receive `_build_runtime_handoff()` prose. Same-provider
Codex resume preserves a native thread without checking the smaller target model's context window.
The Seedon canary in #287 demonstrated the unsafe boundary: `thread/resume` accepted the import,
the first turn reached `258400/258400`, and the subsequent fresh-thread retry lost the imported
state.

The replacement must preserve these invariants:

- `logs` remains the sole raw conversation source. The ledger stores a canonical packet and
  references into a frozen log snapshot, not a second transcript store.
- The packet is deterministic for the same session metadata, tracked project bytes, and log
  snapshot. Integrity hashes prove bytes, not authority.
- Current server/system input and tracked project documents are privileged. User/assistant text,
  old transcripts, tool arguments/results, and data returned by a raw-ref reader are untrusted
  data even if they contain strings such as `SYSTEM`, `AGENTS.md`, or XML role tags.
- `thinking`, `reasoning`, provider `encrypted_content`, and equivalent hidden state are omitted
  from the packet and are never returned by raw references.
- Completed historical side effects carry `repeat_policy="never"`; pending or ambiguous tool
  effects make the switch ineligible. A new explicit user instruction or a proven idempotency key
  is required to repeat an effect after the switch.
- While the lifecycle lock owns the switch, no user turn is accepted. Validation runs with no
  executable tools. Therefore no working user request or external side effect crosses the commit
  boundary twice.
- Network, auth, version, and unknown protocol failures are fail-loud. They are not interpreted as
  a history mismatch and do not spend the fallback.
- Cross-runtime fallback is exactly one smaller packet candidate. There is no automatic summary,
  full-transcript retry, or fresh empty target.

## Durable state and migration

Add a `runtime_handoffs` table in `app/db.py`; do not add required columns to `sessions` or rewrite
old rows. The table is an operation ledger, not a conversation mirror:

```text
handoff_id TEXT PRIMARY KEY
session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
idempotency_key TEXT NOT NULL
status TEXT NOT NULL
source_runtime TEXT NOT NULL
source_model TEXT NOT NULL
source_session_id TEXT
target_runtime TEXT NOT NULL
target_model TEXT NOT NULL
snapshot_log_id INTEGER NOT NULL
snapshot_sha256 TEXT NOT NULL
packet_json TEXT NOT NULL
packet_sha256 TEXT NOT NULL
preferred_mode TEXT NOT NULL
confirmed_attempt_no INTEGER
failure_code TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
confirmed_at TEXT
```

Each external target attempt lives in `runtime_handoff_attempts`, the sole owner of attempt state:

```text
handoff_id TEXT NOT NULL REFERENCES runtime_handoffs(handoff_id) ON DELETE CASCADE
attempt_no INTEGER NOT NULL CHECK (attempt_no IN (1, 2))
mode TEXT NOT NULL
status TEXT NOT NULL
cleanup_locator TEXT NOT NULL
target_session_id TEXT
candidate_sha256 TEXT NOT NULL
preflight_json TEXT
ingress_json TEXT
capability_json TEXT
error_code TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
retired_at TEXT
PRIMARY KEY (handoff_id, attempt_no)
```

Allowed live phases are `prepared`, `target_staged`, `ingress_validated`,
`capability_validated`, and `source_released`; terminal phases are `confirmed`, `failed`, and
`recovery_required`. A partial unique index permits at most one non-terminal handoff per session;
`UNIQUE(session_id, idempotency_key)` makes a caller retry return the original operation instead
of starting a second target.

An attempt row and deterministic `cleanup_locator` are committed before its external stage call.
The locator is an adapter-owned isolated home/path/tag from which every created native session can
be enumerated even if the process dies after the provider returns an id but before SQLite records
it. An adapter unable to provide such a locator is unsupported. Attempt 1 is primary and attempt 2
is the sole fallback; the table constraint plus allocator rejects attempt 3.

`confirm_runtime_handoff()` uses one `BEGIN IMMEDIATE` transaction to verify the expected source
model/runtime/session id and packet hash, update the `sessions` target fields, and mark the handoff
and selected attempt `confirmed`. The in-memory object changes only after this transaction commits.

Migration acceptance is run twice on a `sqlite3.Connection.backup()` copy of the live database.
The pre/post counts of sessions and logs must match, legacy sessions must load, and the second
`init_db()` must make no schema or data change. No backfill is performed.

Preparation first awaits both `_drain_persist()` and every outstanding `_log_futures` write. It
then performs one SQLite read/write transaction: re-read the source session metadata, select that
session's `MAX(logs.id)`, read exactly its rows through that id, classify all tool effects, build
the canonical packet from those rows plus already-captured tracked-document bytes, and insert the
`prepared` ledger row only when eligible. An outstanding/pending effect returns typed
`PreparationResult(ok=false, error_code="handoff_pending_effect", handoff_id=None)` and inserts no
live handoff row; an in-memory/DB source mismatch returns the corresponding typed failure by the
same rule. Project bytes and their git/blob hashes are captured before the transaction and stored
verbatim in an eligible packet, so a later filesystem change cannot silently change the prepared
candidate. A race oracle injects a delayed tool result through the log-drain barrier and proves it
is included in the same snapshot before eligibility is decided.

Safe rollback does not drop the table and does not restore the old optimistic switch. Runtime
handoff capabilities are disabled in `app/runtime_registry.py`, after which new cross-runtime
switches return a visible unsupported error while normal turns and already-confirmed sessions
continue. The additive table is retained for audit/recovery. Removing the table or reverting to
the old summary path is explicitly not an operational rollback.

## State packet v1

Create the packet builder and shared sanitizer in `app/runtime_history.py` (split to
`app/runtime_handoff.py` only if the existing file would otherwise mix backend orchestration with
serialization). Canonical JSON uses sorted keys, UTF-8, compact separators, fixed schema version,
and SHA-256 over the canonical bytes.

The packet contains:

- identity: Orchestra session/task/scope/branch and source/target runtime/model identifiers;
- authority receipts: hashes and origins for the current server system prompt and tracked project
  documents (`current_system_prompt` or `tracked_project_doc`, verified by Orchestra);
- task/objective and constraints with explicit provenance; transcript-derived material is never
  inserted into the privileged constraint list;
- decisions/facts/artifacts only where a typed server-owned record exists, otherwise an explicit
  `unknown` rather than model-written reconstruction;
- historical tool effects with stable call id, status, content hash, truncation metadata, and
  repeat policy; free-form tool arguments/result bodies are not model-visible;
- a bounded recent delta of role-preserving user/assistant messages labelled
  `authority="transcript_untrusted"`; it never promotes transcript text into a system, developer,
  or tracked-project channel;
- a frozen raw range `{session_id, min_log_id, max_log_id, snapshot_sha256}`;
- omissions, including hidden reasoning and redacted/truncated tool data;
- the expected target capability fingerprint and `reasoning.portable=false`.

The packet never cuts a historical effect pair: incomplete call/result state blocks preparation.
It reuses the existing single-owner limits and sanitization in `runtime_history.py`:
`TOOL_CALL_LIMIT`, `TOOL_RESULT_LIMIT`, `TOOL_NAME_LIMIT`, `TOOL_DETAIL_BUDGET`, and
`TOOL_VISIBLE_BUDGET`. User and assistant messages are not semantically summarized. If a complete
message block cannot fit, it becomes addressable only. The same secret masker runs over every
model-visible user/assistant string before packet hashing; bearer, API-key, PEM/private-key, and
base64 probes are covered independently from tool payloads.

`resolve_runtime_handoff_events()` is a server-side resolver, and the read-only HTTP `POST` route
around it is operator-only: authenticated dashboard cookie plus CSRF, never the inherited internal bearer
token, MCP, or a target-runtime tool catalog. It resolves at most 32 ids from the frozen range,
rejects cross-session, post-snapshot, unreferenced, and hidden-reasoning rows, re-runs the shared
sanitizer, and applies the existing 256,000-character total visible budget. Output remains labelled
untrusted. This makes the authority boundary mechanical: neither raw tool-result prose nor a forged
`SYSTEM`/repo instruction has a path into a model-visible staging manifest or executable target
session. A future model-self-fetch feature would require a mandatory pre-execution taint/approval
gate and is outside #290; an instruction telling the model not to obey raw text is insufficient.

The frozen T1/T4 oracles plant a marker-writing instruction only in a tool result, assert that it
is absent from the exact staging manifest, and the isolated adapter canary verifies that a neutral
post-commit turn cannot create that marker. The normal-profile positive control proves the marker
tool itself would work if the planted instruction had crossed the boundary.

Optional model synthesis is not on the normal path. It may run only after a mechanical reason
(`schema_mismatch`, `oversized_delta`, `unsupported_ingress`, or `ambiguous_typed_state`), in a
fresh stateless process with tools/MCP/files disabled and strict JSON output. Its output is
advisory and cannot change authority provenance, effect status/repeat policy, raw snapshot hashes,
or the canonical packet. If a runtime cannot prove that isolation mechanically, synthesis is
unsupported rather than prompt-enforced.

## Total-context preflight

Preflight runs before source disconnect and before target process creation. Each backend adapter
must build one immutable `ModelVisibleManifest` from the exact configuration object it will pass to
the staging factory. The manifest contains separately serialized current system/developer prompt,
tracked project bytes, runtime-generated project-doc instruction, discovered scope/user MCP schemas,
optional generated skill index, packet, bounded recent delta, validation profile, canary, and any
other model-visible adapter field. The preflight and `stage_handoff()` receive the same manifest
object and configuration hash; the backend factory may not rediscover or append input afterwards.
Component-isolation tests overflow every component independently. This prevents a hand-maintained
estimator from drifting from Codex project-doc/skills discovery, Claude project inheritance, or
Grok's composed MCP set.

For a cross-runtime packet, UTF-8 byte length of this complete manifest is the conservative token
upper bound. For same-provider native resume, use the last provider-reported total context plus the
upper bound of target-only manifest additions. Missing native context telemetry makes native resume
ineligible; it does not guess from a percent.

The effective window is the smaller of `ModelSpec.context_length` and the runtime-reported window.
A difference is recorded in the preflight receipt. The shared reserve formula, owned in one module,
is:

```text
output_reserve    = min(64_000, floor(effective_window / 4))
reasoning_reserve = min(32_000, floor(effective_window / 8))
next_user_reserve = 4_096
fits = candidate_upper_tokens + output_reserve + reasoning_reserve
       + next_user_reserve <= effective_window
```

The receipt records each component, counting method, effective window, runtime/model versions,
candidate hash, and decision. A non-fit primary candidate may spend the one fallback attempt on the
packet without the recent delta. A non-fit fallback returns `handoff_context_overflow`; the source
model, native id, backend, and session row remain unchanged.

## Validation, capability, commit, and recovery

Each target adapter exposes two distinct operations:

1. `stage_handoff(...)` starts or resumes a target in a version-pinned validation profile with no
   MCP, dynamic, shell, browser, computer, web, file, or other executable tool surface. The model
   must return the packet schema version and exact packet checksum. A prompt that merely says
   "do not use tools" is not a control.
2. `check_handoff_capabilities(...)` is a server/protocol inspection, not a model assertion. It
   verifies runtime and SDK/CLI versions, selected model, effective context window, project/system
   hashes, the normal post-commit tool fingerprint, operator-only raw-ref route isolation, and the
   receipt proving the validation tool surface was empty.

The coordinator-facing signatures are fixed for implementation and tests:

```text
AgentSession._prepare_runtime_handoff(target_model, *, idempotency_key, project_docs)
BackendLike.build_handoff_manifest(prepared, *, validation_profile) -> ModelVisibleManifest
preflight_runtime_handoff(manifest, *, native_context_tokens) -> PreflightReceipt
stage_preflighted_handoff(adapter, prepared, attempt, *, native_context_tokens)
    -> PreflightedTarget  # stages the identical manifest object it counted
AgentSession._run_handoff_ingress_canary(staged, *, packet,
    expected_packet_sha256) -> IngressReceipt
AgentSession._verify_handoff_capabilities(staged, *,
    expected_fingerprint) -> CapabilityReceipt
AgentSession._confirm_runtime_handoff(prepared, attempt, staged) -> None
```

Receipts are accepted only when checksum/fingerprint/configuration hash equal the prepared expected
values, `ok=true`, and `tools_enabled=false`. Awaiting a check is not validation; negative receipt
fixtures must retain the source and skip confirmation.

The installed Codex 0.146.0 schema exposes `additionalContext.kind="untrusted"` but no universal
disable-all-tools field. Therefore the Codex ticket has a stop condition: a version-pinned profile
must mechanically demonstrate an empty model-visible tool surface. The isolated test includes a
positive control in the normal profile and a denied marker-writing attempt in the validation
profile. If that cannot be proven, Codex handoff support stays disabled; no instruction-based
substitute is accepted. Claude and Grok have the same mechanical proof requirement.

Sequence under the session lifecycle lock:

1. drain pending session/log writes and freeze the atomic DB snapshot; a typed ineligible result
   returns immediately with no live handoff, otherwise create/idempotently load `prepared`;
2. assert the successful preparation receipt is eligible (defence in depth; it never carries a
   nonzero pending-effect count);
3. build the adapter manifest and run total-context preflight on that exact object;
4. allocate attempt 1 with its deterministic cleanup locator, then stage target tools-disabled;
   persist the returned target id and `target_staged`;
5. verify checksum and persist `ingress_validated`;
6. perform the separate capability check and persist `capability_validated`;
7. disconnect the idle source and persist `source_released`;
8. atomically update `sessions` and ledger to `confirmed`;
9. resume the validated target id with the normal, capability-matched tool profile and activate it.

Only positively structured context/schema/ingress incompatibility can allocate attempt 2, whose
candidate is packet-only and whose cleanup locator is persisted before the fresh target stage.
Network/auth/unknown/free-prose errors fail immediately. A second incompatibility cannot allocate
attempt 3; it marks `failed`, enumerates and retires both cleanup locators, leaves the source
authoritative, and returns a visible stable error code.

Startup recovery scans non-terminal rows before auto-resume:

- through `capability_validated`: enumerate and discard every attempt through its persisted cleanup
  locator, mark `failed`, and resume the unchanged source;
- `source_released` while `sessions` still names the source: reconnect that exact source id and mark
  `failed`; if reconnection cannot be proven, mark `recovery_required` and reject sends;
- `confirmed` with matching target fields: resume the target normally;
- any source/target/hash mismatch: `recovery_required`, no automatic retry or inferred winner.

No validation turn carries a working user request, and the lifecycle lock prevents a concurrent
send from being accepted. Thus recovery never replays a user turn or an external effect.

## User-visible contract

The change-model response and dashboard distinguish:

- `packet`: checksum and capability accepted, target committed;
- `fallback_packet`: the sole smaller candidate was used, with reason;
- `blocked`: stable error code (`handoff_context_overflow`, `handoff_pending_effect`,
  `handoff_capability_unsupported`, `handoff_ingress_rejected`, `handoff_recovery_required`, or
  transport/auth error), source retained;
- omissions: hidden reasoning omitted, tool payloads redacted/truncated, and transcript/raw refs
  untrusted.

The UI never says "full history transferred". It says that server-owned state and an addressable,
sanitized snapshot were validated, and names any omission/fallback. Existing `runtime_handoff`
remains only for legacy lost-transcript recovery outside the new switch transaction; it is not a
success path for #290.

## Tickets

### T1 — Freeze a deterministic packet and scoped raw references

- Files: `app/db.py`, `app/session.py`, `app/runtime_history.py` (or one new
  `app/runtime_handoff.py`), `app/auth.py`, `app/routes/sessions.py`,
  `tests/test_runtime_handoff_v2.py`, focused DB/auth/route tests.
- Test: `tests/test_runtime_handoff_v2.py -k 'test_t1_'` — re-frozen RED in
  `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`.
- RED: `AssertionError: no durable pending/confirmed handoff ledger exists`.
- AC: the named test is green; migration succeeds twice on a `Connection.backup()` copy of the
  live DB with unchanged session/log counts and legacy reads; preparation drains pending log writes
  before one SQLite snapshot/insert transaction; the same snapshot renders identical canonical
  bytes/hash; both privileged origins are present, hidden reasoning never appears, and malicious
  transcript text remains only untrusted; bearer/private-key probes in user, assistant, and tool
  rows are redacted before hashing; the operator-only ref route rejects inherited internal bearer
  and cookie-without-CSRF, accepts operator cookie+CSRF, is absent from the MCP tool list, rejects
  cross-session/post-snapshot/hidden rows, and enforces 32 ids plus the shared 256,000-character
  budget; an idempotency-key collision returns the same handoff; attempt rows own both cleanup
  locators and reject attempt 3.
- blocked-by: none.

### T2 — Ship one fail-closed Codex target path

- Files: `app/session.py`, `app/backend_protocol.py`, `app/backend_codex.py`,
  `app/runtime_registry.py`, `app/db.py`, `app/routes/sessions.py`, `app/static/js/app.js`,
  `tests/test_runtime_handoff_v2.py`, focused Codex/session/route tests.
- Test: `tests/test_runtime_handoff_v2.py -k 'test_t2_'` — re-frozen RED in
  `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`.
- RED: `assert True is False` at the overflow decision.
- AC: the named test is green; Claude/Grok→Codex uses only packet + bounded recent delta, then at
  most packet-only fallback; source disconnect occurs after ingress and capability receipts;
  validation profile passes a positive-control/denied-side-effect isolation test or Codex support
  remains explicitly disabled; the exact adapter manifest is shared by preflight and staging, and
  independent system/project/MCP/skills/packet/delta/canary overflow fixtures reject; 0.146.0
  schema/version drift fails loud; structured classification keeps auth/network/prose errors out of
  fallback; attempt 3 is impossible and all cleanup locators survive recovery; injected SQLite
  failure proves session/ledger confirmation rolls back together; crash decisions for every phase
  are fail-closed; response/UI expose receipt, omissions, fallback, and source-retained failures.
- blocked-by: T1.

### T3 — Ship the Claude target through the same transaction

- Files: `app/session.py`, `app/backend_claude.py`, `app/backend_protocol.py`,
  `app/runtime_registry.py`, `app/static/js/app.js`, `tests/test_runtime_handoff_v2.py`, focused
  Claude/session tests.
- Test: `tests/test_runtime_handoff_v2.py -k 'test_t3_'` — re-frozen RED in
  `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`.
- RED: `Expected mock to have been awaited once. Awaited 0 times.` for ingress validation.
- AC: the named test is green; Claude 2.1.197 / SDK 0.2.114 staging proves a mechanically empty
  validation tool surface and exact checksum; separate capability receipt covers the normal tool
  fingerprint and proves the operator-only raw-ref route is absent from that catalog; validation
  and capability precede source disconnect;
  wrong checksum, `tools_enabled=true`, false capability, fingerprint mismatch, or configuration
  mismatch retain source and skip confirmation; version mismatch, auth/network error, fallback
  exhaustion, and restart recover per the shared coordinator; ordinary non-handoff Claude resume
  remains byte-for-byte on its existing path.
- blocked-by: T2.

### T4 — Enable Grok only after it proves the same ingress contract

- Files: `app/session.py`, `app/backend_grok.py`, `app/backend_protocol.py`,
  `app/runtime_registry.py`, `app/static/js/app.js`, `tests/test_runtime_handoff_v2.py`, focused Grok
  tests and isolated canary artifact under `docs/tasks/290/`.
- Test: `tests/test_runtime_handoff_v2.py -k 'test_t4_'` — re-frozen RED in
  `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`.
- RED: `Expected mock to have been awaited once. Awaited 0 times.` for ingress validation.
- AC: the named test is green; an isolated pinned Grok process records raw request/response evidence
  for checksum, mechanical no-tools proof, and capability receipt; if any seam is absent, registry
  capability remains unsupported and the switch returns `handoff_capability_unsupported` with the
  source untouched; `_build_runtime_handoff()` is not called, the staged checksum belongs to the
  canonical packet, and a packet built from a real marker-bearing tool-result row is passed through
  `GrokBackend.build_handoff_manifest()` with the marker absent from its exact components; if
  enabled, fallback and recovery behavior is identical to T2/T3.
- blocked-by: T2.

### T5 — Preflight same-provider native resume and complete end-to-end acceptance

- Files: `app/session.py`, `app/runtime_registry.py`, provider backends as required,
  `tests/test_runtime_handoff_v2.py`, `tests/test_native_history_import.py`, final canary artifacts
  and `CHANGELOG.md`.
- Test: `tests/test_runtime_handoff_v2.py -k 'test_t5_'` — re-frozen RED in
  `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`.
- RED: `assert True is False` at the smaller-window decision.
- AC: the named test is green; same-provider native resume is attempted only with a complete
  preflight receipt; Sol→Spark at 132,343 reported tokens against the 128,000 target window rejects
  before disconnect; an eligible Sol→Luna/Claude-model/Grok-model canary resumes the same native id
  and recalls a UUID present only before the switch; a cross-runtime canary in both directions
  recalls a UUID present only in a prior `tool_result` and absent from current prompt/packet summary;
  pending/unknown side-effect fixtures block; primary incompatibility uses one fallback and a second
  failure stays on source; long-history and crash-phase canaries are behavioral, not file-existence
  checks. `CHANGELOG.md` documents the capability/version tripwires and safe rollback.
- blocked-by: T3, T4.

## Verification matrix

Focused commands are run after each ticket. Before final merge, with the global test lock and
explicit orchestrator permission, run the project suite once. Independent runtime canaries use
disposable workers and isolated homes; no live project session is modified.

Required negative controls:

- mutate one packet byte after hashing → ingress checksum rejects;
- promote a transcript sentence to privileged constraint → authority test rejects;
- expose one hidden-reasoning row through raw refs or authenticate the route with an inherited
  internal bearer → operator-only reader test rejects;
- put a marker-write instruction only in a raw tool result → exact staging manifest omits it and a
  neutral post-commit canary leaves the marker absent; normal-profile positive control can write it;
- enable one executable validation tool and ask for a temp marker write → isolation test rejects and
  marker remains absent; normal-profile positive control must create the safe marker;
- disconnect source before capability receipt → ordering test rejects;
- commit session without confirming ledger, and the inverse → transaction test rejects;
- permit a second fallback → attempt-count test rejects;
- remove native total-context preflight → Sol→Spark test rejects;
- restart at every persisted live phase → exactly one recovery outcome from the table above.

## Not in scope

- No transfer, storage, or reconstruction of hidden chain-of-thought/reasoning.
- No arbitrary provider-transcript-to-provider-transcript converter and no forged rollout files.
- No agent-authored summary tool, autonomous self-switch, deferred wake state machine, or
  instruction-only safety boundary.
- No unbounded raw replay and no claim that a byte hash makes transcript data authoritative.
- No cache until post-implementation measurements show packet rendering or preflight needs one.
- No production restart, live-session experiment, or adapter enablement during implementation
  without the orchestrator's explicit gate.

## Phase 2 RED evidence

The initial five-test snapshot `36b3b2c2d0b172dcd1fb617ec6cb278543aa58b8` was rejected by
independent review and is excluded from implementation evidence. The intermediate RED snapshot
`efaceb78c5f11a90ff68009d53c8d6073564fe55` was also rejected and is excluded. The final revision
is re-frozen at `a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c`; implementation must compare the oracle file
byte-for-byte to this commit.

Command:

```bash
uv run --active python -m pytest tests/test_runtime_handoff_v2.py -q
```

Result: exit 1, `39 failed in 11.38s`. All failures reach assertions for missing schema, seams, or
behavior; there are no import, collection, fixture, or setup errors. Parametrization covers ten
model-visible manifest components, identity-preserving manifest staging, six fallback
classifications, eight recovery states, three invalid validation/capability receipts, route-level
operator/CSRF/internal-token isolation, the two-attempt ceiling, atomic-confirm rollback, pending
effects, and same-provider smaller-window refusal.
