# #361 — live activation boundary for typed `knowledge`

Date: 2026-08-25

Verified tree: `c885f10e53b369d0e9846a23c9801618ef0e6bb9` (the task branch and `main` were identical at research start).

Phase: 1 — research and scratch experiments only. The running service, live SQLite/WAL files,
live RAG corpus, canonical owner, projections, native sessions, and systemd unit were not changed.

## Question

- **Context:** current `main` contains the typed `KnowledgeService`, `TaskStore`, current/FTS
  projection, document-cutover state machine, HTTP route, MCP tool, and new prompt contract, but the
  live MCP call returns `knowledge_not_configured`.
- **Change under test:** the smallest reversible production activation that makes the MCP `knowledge`
  tool useful for every live project scope after a safe restart while legacy remains the active owner
  during shadow. The authorization was subsequently expanded to permit an explicit, separately gated
  generation 2→3 transition; projection deletion and `clear-session` remain forbidden.
- **Baseline:** the running service owns tasks/logs in `orchestra.db`, legacy search in `vec.db`, and
  hand-written Git Markdown; `app.main.lifespan` does not enter any IA owner.
- **Measurable outcome:** scoped MCP queries return typed items; no request can cross scope or mutate
  through read-only access; legacy task/search responses remain authoritative in shadow; canonical,
  projection, vector, prompt, privacy, rollback, and receipt heads are durable across restart; all
  native session IDs remain unchanged; no projection or historical source is deleted or rewritten.

## Hypotheses and falsifiers

| Hypothesis | Falsifier sought | Result |
|---|---|---|
| H1 — nesting the four existing context managers around `lifespan` is sufficient | HTTP handlers or their `to_thread` work do not observe a lifespan-set `ContextVar`; restart loses generation/receipts; projection activation changes a legacy reader | **REFUTED.** An actual minimal Uvicorn probe returned `handler=default, thread=default` while a child created inside lifespan saw `lifespan-value`. Cutover generation reset 2→1 on re-entry, and `app.routes.memory` switches owners whenever the projection module-global is non-null. |
| H2 — one process-global runtime owner plus explicit scope derivation is sufficient for shadow | shared mutable stores corrupt under concurrent task requests; persisted state cannot be reopened; scope IDs cannot form safe typed paths | **PARTLY SUPPORTED, not sufficient alone.** Module globals reach HTTP tasks, but forced concurrent `TaskStore` writes corrupted identity in 3/3 runs; current restart re-migration fails after one shadow write; 8/19 live task project IDs are not canonical slugs and two absolute IDs escape the configured root. |
| H3 — existing T2/T3b/T4/T7 tests already prove live activation | tests use real lifespan propagation, durable receipts, real import adapters, current production inventory, and live scope/auth boundaries | **REFUTED.** `58 passed`, but T2 sets the context in the caller task, T7 uses fake import/receipt callbacks, its inventory is pinned to an older commit and one project, and no test enters the owners from `app.main`. |
| H4 — staged runtime wiring plus persisted scope/state/receipt owners is the minimum safe path | a smaller wiring-only change can meet every named behavior oracle without changing legacy behavior or risking data/session loss | **LIKELY.** Every rejected smaller shortcut below violates at least one measured boundary. Phase 2 must freeze this as behavior-level RED oracles before implementation. |

## Short answer

The smallest **safe shadow activation is not a lifespan-only `with` block**. It is one bounded runtime
owner, installed before `manager.auto_resume_all()`, with five prerequisite repairs:

1. a persistent private state-root contract plus an immutable bootstrap snapshot that is loaded, not
   regenerated, on restart;
2. a durable scope registry mapping every resumable session scope to a canonical slug, derived by the
   HTTP server from the proof-bound session header rather than model payload;
3. a serialized/recoverable task shadow writer that cannot escape its root and cannot turn a
   post-legacy mirror failure into an unknown legacy outcome;
4. separate **shadow candidate** and **active legacy** read selection, so configuring the new
   projection does not silently replace `/api/memory/search` before parity;
5. persistent cutover/receipt state and a real Git-blob importer whose URI contract matches the
   inventory.

With those repairs, the reversible live step is: take one WAL-safe bootstrap snapshot → materialize
the candidate under the private state root → enter process-global knowledge/projection owners and a
request-visible task runtime → keep legacy task/RAG responses active → reconnect MCP processes at safe
turn boundaries through the normal restart path → run a real scoped `knowledge(query, text=...)` probe.
The later generation 2→3 command remains a separate explicit operation requiring the six persisted
gate receipts. Projection deletion has no valid operation at either generation.

## Measurement protocol and immutable boundaries

All database measurements used `sqlite3.Connection.backup()` from `mode=ro` source connections. `/tmp`
is `tmpfs`, so the backups and projection probes were placed on `/mnt/data`. Both backups returned
`PRAGMA quick_check=ok`. Scratch was never used as truth and is removed after the measurements are
recorded here.

| Live boundary at backup time | Measured value |
|---|---:|
| `orchestra.db` source/backup | 592,637,952 bytes; WAL 4.0 MiB |
| `vec.db` source/backup | 742,531,072 bytes; WAL 8.4 MiB |
| task projects / task rows | 19 / 670 |
| stored sessions / native session contexts | 522 / 495 |
| resumable native sessions / distinct resumable scopes | 72 / 18 |
| resumable scopes mapped by `tm_projects.scope` | 13; 5 are unmapped |
| nonempty log scopes / log rows / content bytes | 18 / 180,729 / 488,108,606 |
| filesystem session scopes | 21 distinct; 20 exist; 18 are Git work trees |
| current vector file/log scope coverage | 13 / 10 scopes |
| current-main Orchestra frozen-source inventory | 1,508 paths, 19,045,346 bytes: 1,348 cold evidence + 160 active sources |
| old T7 inventory | 1,505 paths, 19,020,144 bytes at `34fb2350a8224f2991dbe722afc29070daf02bee` |

Five currently resumable scopes have no task-project mapping: `Aperant`,
`Claude-Code-Game-Master`, `games`, `DefaultProjectUnity`, and `/mnt/data/media`. Historical session
rows additionally include unsafe/non-project scopes such as `/tmp` and a missing `/test/scope`.
Therefore “all scopes” cannot mean “recursively scan every string ever stored in `sessions.scope`.”
Activation needs a positive scope registry; unmapped roots must be registered or fail closed.

## Required fact table

| owner / seam | current configured? | process / task locality | state path | write set | read consumers | rollback | failure mode | test oracle | live activation step |
|---|---|---|---|---|---|---|---|---|---|
| `app.main.lifespan` | **No IA owner.** It only includes the route. | One Uvicorn process; lifespan runs in a sibling task to HTTP. | Live cwd `/mnt/data/Projects/Python/orchestra`; no IA path. | DB initialization, resume/recovery/background services; no typed state. | All HTTP routes and manager startup. | Normal lifespan teardown/restart. | A lifespan `ContextVar` does not reach requests. | Minimal Uvicorn probe: child inside lifespan=`lifespan-value`; HTTP handler and its thread=`default`. | Install a process runtime before `auto_resume_all`; do not rely on a lifespan-only task context. |
| `app.tm.ia_task_store_mode` | Surface exists; production is legacy because context is unset. | `ContextVar`; visible only to the setting task and copied children/threads. | Caller-supplied canonical root + task projection DB. | At entry, snapshots every task table and migrates; in shadow, legacy write first, then canonical files/projection. | TM HTTP routes, MCP task tools, merge/session callers through `app.tm`. | Context reset restores routing only; it cannot undo a committed legacy write. | HTTP does not see lifespan context; candidate failure after the legacy commit leaves drift; re-entry fails after shadow writes. | Uvicorn probe; injected mirror failure left `legacy.writes=1`; same-manifest restart raised `manifest replay would overwrite newer canonical state`. | Replace the ContextVar-only owner with a request-visible process runtime, a lock/outbox, and load-existing bootstrap semantics. |
| `TaskStore` | Not live. | Mutable object; no lock. TM routes call it from concurrent `asyncio.to_thread` workers. | `canonical_root/{manifests,projects/**}` + `projection_path`. | Whole-generation state/event writes; `_write_states` deletes unwanted `state.json`; task projection executes full-table `DELETE`. | `app.tm`, knowledge evidence resolver, current projection. | `replay(head=...)` works inside one store; startup migration is not a state loader. | Unsafe project paths, noncanonical URIs, restart failure, concurrent duplicate identities. | Live snapshot: 8/19 project IDs invalid slugs; 3 tasks resolve outside root. Forced two-thread create: both callers reported success but store was corrupt in 3/3 runs. | Canonical project registry + path-containment check + serialized CAS + durable bootstrap/state loader. |
| `KnowledgeService` / `_ACTIVE_SERVICE` | **No**; live query returns 503. | Module-global service reaches all HTTP tasks; methods have no lock. Current single-worker route calls are synchronous after JSON parse. | None live. Constructor requires a registry path and creates `canonical_root/registry.json`. | Registry, fact events/facts, archive index/evidence refs. | `/api/knowledge`, current projection, cutover adapter. | Context manager restores the previous pointer; filesystem mutations remain. | Empty registry permits text projection queries but topic query resolves zero topics; multi-worker/direct-thread writers are unsynchronized. | Scratch empty registry: text query returned a valid empty envelope; topic query raised `TopicResolutionError`. | Create one private runtime-owned registry and service, serialize mutations, and expose a read-only health/state probe. |
| `app.ia.projections` / `_ACTIVE_PROJECTION` | **No**; legacy RAG is active. | Module-global, hence HTTP-visible. Synchronous SQLite operations run on the event loop in both routes. | No new projection path live; existing legacy DB is `data/vec.db`. | `current_records`, FTS5, meta head; `rebuild_legacy` also writes/deletes full-content JSON under the canonical root. | Generic `knowledge(text=...)`; `/api/memory/search` and `/reindex`. | Context reset restores pointer; DB and imported JSON persist. Existing vector DB is retained. | Merely configuring it switches legacy memory reads to the candidate; repeated full replacement bloats SQLite; full-content legacy import can copy secret candidates. | 65,031 Orchestra task+file+log records: 13.027 s then 36.041 s, DB 757,227,520→835,424,256 bytes, peak RSS about 1.36 GiB, rows/FTS/head exact. | Configure candidate projection for `knowledge` first; keep memory route on RAG until the persisted owner is generation 3. No delete/VACUUM in activation. |
| `SQLiteProjectionBackend` | Code only. | One connection per call; no explicit busy timeout. | Caller path. | Atomic transaction with `DELETE` of current+FTS then reinsert and meta-head update. | `query_current`. | Rebuild from canonical records. | Large full replacement, file bloat, and event-loop blocking. | No-log 2,178-row rebuild: 2.029–2.248 s; full Orchestra log layer above; first full `quick_check=ok`. | Execute rebuild before traffic or in a bounded worker; atomically publish only a completed candidate DB. |
| Existing RAG/vector owner | **Yes**, `RAG_ENABLED=true`. | Main-process singleton; one read and one write executor. | `/mnt/data/Projects/Python/orchestra/data/vec.db`; source logs in `orchestra.db`. | Async incremental file/log rows and vectors. | Legacy `/api/memory/search`. | Retain/rebuild; no deletion needed. | Only 13 file scopes and 10 log scopes are represented; there is no typed `indexed_head` adapter. | WAL-safe backup counts by project; live process environment reports `RAG_ENABLED=true`. | Keep it active in shadow; add a content-bound indexed-head/debt adapter before generation 3. |
| `/api/knowledge` route | Registered but service unavailable. | HTTP request task; calls synchronous owner after `await request.json()`. | None. | `promote` and `import_evidence` can mutate despite one generic POST route. | MCP `knowledge`. | HTTP errors only. | It does not derive scope, check MCP proof/role, or restrict mutation; internal-token callers may supply any project and `cross_project`. | Source trace `routes/knowledge.py:24-47`; missing project scratch query returned a successful unscoped empty result. | Resolve the proof-bound session from headers, inject its canonical project ID, authorize operation/cross-project server-side, reject conflicting payload scope. |
| MCP `knowledge` | Fresh MCP exposes it in full, reducer, and read-only modes. | One MCP subprocess per backend; `SCOPE` and session ID are process env. | None. | Forwards any `operation`; the access-mode allowlist cannot distinguish query from promote/import. | Every connected agent. | Reconnect backend, preserving native thread. | It forwards generic payload unchanged and omits `SCOPE`; a read-only/reducer agent can request a mutating operation. | Captured request with `SCOPE=/mnt/.../orchestra`: body contained only `payload.text`, no project ID. | Send no caller-owned project ID; let the server derive it. Split read/mutate authorization despite one tool name. |
| Query payload contract | Partially configured in code. | Request-local. | None. | None for query; projection may repair on read. | Agents following the memory-search prompt. | N/A. | Generic `payload.query` is rejected; only `text` selects current projection. | Scratch: `query` → `PromotionValidationError: query contains unsupported fields`; `text` → valid envelope. | Normalize `query` to `text` once, or expose a typed argument schema that names `text`; duplicate/conflicting keys fail. |
| Scope/project identity | TM route has a resolver; knowledge route has none. | DB mapping plus MCP env. | `tm_projects` in `orchestra.db`; no typed project registry. | Current task migration embeds raw `tm_projects.id` into URI/path. | Task tools, future typed records/search. | Legacy scope strings remain. | 8/19 IDs violate lowercase slug syntax; absolute IDs can escape the root; 5/18 resumable scopes are unmapped. `_legacy_project_id(scope)` creates a different hashed ID from task identity. | Full live manifest/path probe and resumable-scope join. | Persist a normalized scope→canonical-slug→legacy-project mapping; require root containment and exact one-to-one resolution. |
| Document inventory | Script exists; no live invocation. | Per administrative process. | Reads a pinned Git tree; frozen fixture in `docs/tasks/315`. | Returns JSON only. | Cutover shadow importer. | Rerun at a different pinned head produces a new manifest. | `_PROJECT_ID` is hardcoded to `orchestra`; current main has 3 more entries than the frozen fixture; aliases do not match the real importer for cold evidence. | Current-main reproduction: 1,508 entries / 19,045,346 bytes / manifest `sha256:4767…9426`. | Generate one manifest per registered Git scope using its canonical project ID; pin commit+blob+size+SHA and store the accepted manifest. |
| `KnowledgeService.import_evidence` | Callable only after service configuration. | Shared service. | Canonical `projects/<project>/evidence` + `archive-index.json`. | Evidence-reference JSON and index. | Agent evidence detail and cutover. | Exact replay is a no-op; no removal path is needed for shadow rollback when root is generation-owned. | It validates only the *current working file* digest and merely regex-checks `git_commit`; T7 cold alias lacks task identity and is rejected by `parse_uri`. | Scratch accepted `git_commit=000…000` and stored it; frozen alias failed `evidence canonical_uri is invalid`. | Verify commit→tree→blob bytes, add/align a cold-evidence URI contract, and make the cutover adapter send the real `source` shape. |
| Document cutover / `_ACTIVE_CUTOVER` | **No** production configurator/caller. | `ContextVar`; generation and receipts list are memory-only. | Caller canonical root; receipt writer is injected. | Imported document JSON + callback receipts. | Administrative script; no HTTP/MCP owner. | Generation 3→4 only in the same context. | Restart resets generation 2→1; same receipt ID gets a new `created_at`, so strict durable replay conflicts. | Scratch first shadow reached generation 2; re-entry reported generation 1 and failed durable same-ID retry. | Persist state+receipt ledger, load/validate it before serving, and make receipt bytes idempotent. |
| Prompt assembly/delivery | Source is current; live fleet is mixed. | Reassembled per session; native runtime applies at connect or injected turn. | Pipeline Git files + stored `sessions.system_prompt/prompt_overlay`. | Prompt DB row updates after successful injection. | Claude/Codex/Grok/Harness sessions. | Legacy/custom full prompt is intentionally preserved when component ownership is unknown. | Fresh assembly is correct, but 55/72 resumable sessions have `prompt_overlay IS NULL` and no knowledge anchor, so restart preserves their old full prompt. | Five roles: all 6 anchors, zero forbidden directives; live backup: 17 current vs 55 stale-null-overlay resumable prompts. | Migrate only reconstructable legacy prompts to an owned overlay, preserve true operator overrides, then reconnect/reinject without clearing native session IDs. |
| State-directory / DB owner | DBs configured by cwd defaults; `STATE_DIRECTORY` is absent live. | Paths resolve at module import. | Live `orchestra.db` and `vec.db` are under repo `data/`; generic state fallback is `/home/maxim/.local/state/orchestra`. | Existing DB/RAG writes. No IA root exists in any candidate location. | Entire service. | WAL backup + explicit path switch. | `data/` is ignored by Git, so JSON written there cannot honestly be “Git canonical”; systemd template and live unit disagree on `StateDirectory`. | `systemctl show/cat`, filtered `/proc/$pid/environ`, `git check-ignore -v data/ia`. | One fail-loud private state-root resolver; if generation 3 requires Git canonical, use a dedicated Git repository/commit owner rather than ignored `data/`. |
| Restart/reconnect | Safe restart path is active. | Process generation plus persisted session rows/native IDs. | `orchestra.db`, systemd FD store, provider-native session IDs. | Drains persistence, hands over adoptable CLIs, resumes rows. | All agents. | Failed preflight/signal path reopens gates and rolls back handover. | Adopted CLI/MCP stays stale until a turn boundary; stale full prompts may remain; restart alone does not configure IA. | `routes/system.py:2315-2518`, `manager.py:2181-2303`, `session.py:960-1028`; 495 native contexts measured. | Use `/api/restart`; never call `clear-session`. Release/reconnect stale MCP only at safe boundaries, preserving `session_id`. |
| Receipt persistence / Git owner | Merge receipts exist elsewhere; IA cutover has no production writer or Git commit owner. | In-memory cutover context plus plain filesystem callbacks. | None live. | Plain JSON writes; no `git add/commit` in IA modules. | Cutover gates and future operators. | In-memory replay/rollback only. | A generation-3 claim would not be restart-durable or Git-canonical. | No IA state dirs exist; search found Git commands only for reading frozen evidence, not committing canonical JSON. | Add an atomic durable receipt/state ledger and a real Git transaction owner before allowing generation 3. |

## Explicit answers to the required probes

### ContextVar lifespan propagation to HTTP tasks

**REFUTED.** In a minimal real Uvicorn server, the lifespan task set a `ContextVar` to
`lifespan-value`. A child task created inside lifespan inherited it, but an HTTP handler returned the
default, and `asyncio.to_thread` called by that handler also returned the default. Therefore wrapping
`tm.ia_task_store_mode` or `document_cutover_mode` around `yield` does not activate HTTP traffic.

### Module-global service concurrency

Module globals do propagate to HTTP, which makes them the correct reachability seam, but they are not
a concurrency policy. The live unit has one Uvicorn worker and the knowledge route does no await while
inside the synchronous owner, so current HTTP knowledge calls are serialized by the event loop. TM
routes deliberately use concurrent threads. With a barrier after both `TaskStore` writers accepted the
same head, two creates both returned success in 3/3 runs and each run ended with duplicate active
display identity. A process-global runtime therefore needs a lock/CAS/outbox; a naked module global is
unsafe.

### Multi-scope project ID derivation

Current knowledge requests have no derivation. Of 18 resumable scopes, 13 map to a task project and 5
do not. Of 19 task project IDs, 8 are not typed slugs. Two absolute project IDs cause three task paths
to resolve outside the supplied canonical root. A separate canonical project registry is mandatory;
neither raw scope path nor raw `tm_projects.id` is safe.

### Generic `query` versus required `text`

`payload.query` is not an alias. It is rejected as an unsupported field. Only the presence of `text`
or `record_types` selects `projections.query_current`. This is directly inconsistent with the generic
MCP payload and the memory-search instruction’s wording. Normalize once at the API/tool boundary.

### Empty initial registry

No registry file or IA root exists live. A valid empty registry lets generic text projection queries
run, including an unscoped query that currently returns a successful empty result. Topic query cannot
resolve anything. Empty bootstrap is acceptable only as a health state, not proof that knowledge is
useful; the first accepted scope/task/evidence import and topic registry must be part of shadow parity.

### TaskStore shadow snapshot drift

Entry snapshots the entire legacy task database once. Current shadow mutations commit legacy first and
candidate second. A simulated candidate filesystem failure left the legacy mutation committed and then
raised. Existing tests can surface a mismatch on a later read but do not persist repair debt or reconcile
it. A restart re-snapshot does not repair it: the existing manifest rejects both a newer canonical head
and a new cutoff manifest.

### Byte-preserved Git evidence import

The inventory reader correctly verifies commit/tree/blob/size/SHA bytes. The real importer does not:
it reads the current working path, accepts any 40-hex `git_commit`, and has an incompatible URI/payload
contract. Scratch stored an all-zero Git commit successfully. The T7 fake importer hides both defects.
Shadow must connect the verified Git bytes directly to the stored reference and never copy or rewrite
the historical body.

### Projection rebuild cost

Predeclared pass criteria were exact input/current/FTS counts, exact head, and `quick_check=ok`. A
2,178-record task+Orchestra-document build took 2.029 and 2.248 seconds. A production-shaped Orchestra
scope build with 670 tasks, 1,508 files and 62,853 logs (65,031 records) took 13.027 seconds on a fresh
DB and 36.041 seconds on replacement; the DB grew 757,227,520→835,424,256 bytes and peak RSS was
1,392,024/1,390,392 KiB. Load averages were 2.47→2.60 and 2.70→2.54 respectively. One earlier bounded
attempt was killed before output and is excluded. Full all-scope cost is **unmeasured** because scope
identity is not yet defined; extrapolation is not an oracle.

### Restart idempotence and receipt persistence

Both are absent. `ia_task_store_mode` tries to migrate on every entry and cannot reopen after a shadow
write. `document_cutover_mode` always constructs generation 1 and does not load receipts. A strict
same-ID receipt writer rejected the second-process shadow retry because `created_at` changed. Durable
state and idempotent receipt bytes are prerequisites, not post-cutover cleanup.

### Canonical / SQLite / vector fallback

The current projection algorithm is canonical-first: it computes canonical records before consulting
SQLite; stale/mismatched SQLite is repaired or results are returned with `source=canonical-fallback` and
debt. Vector callback output can contribute only `indexed_head`/debt and never supplies result items.
If canonical data is missing, the function fails before either projection can win. The focused T4
oracles for stale, forged, vector-failure, projection-write-failure, and missing-canonical behavior are
green. The activation danger is earlier: globally configuring projection makes the legacy memory route
choose it before shadow parity.

### Secrets exclusion

The current Git inventory is allowlisted and does not select the one tracked sensitive-looking filename;
`.env`, credentials, caches, `.git`, and arbitrary untracked roots are outside its classifiers. However,
the selected current-main corpus has 93 files matching the schema’s broad secret detector and 8 files
matching the narrower token-shape scan; these may be examples, but they cannot be declared safe without
classification. The WAL backup has 340 log rows matching the narrow shapes. `db.add_log` masks current
inserts, but `rebuild_legacy` does not re-mask/validate reads and copies full content into canonical JSON.
Therefore shadow import must store byte-bound cold references, project only privacy-classified public
payloads, and fail closed on unresolved matches; it must not recursively import `/tmp` or arbitrary
session roots.

## Counter-evidence

- The merged architecture is not empty scaffolding: fresh prompt assembly contains all six anchors for
  all five roles, the MCP registry exposes one `knowledge` tool, and the focused T2/T3b/T4/T7 suite is
  `58 passed in 2.69s`.
- `TaskStore.replay` can reproduce older/forward heads inside one initialized store. This supports the
  design but does not provide restart-time owner loading.
- `SQLiteProjectionBackend.replace_current` committed exact rows/head and passed `quick_check`; the
  problem is activation sequencing/cost, not an inability to build a projection.
- The normal restart path preserves provider-native IDs and even adopts eligible live CLI processes.
  The prohibition on `clear-session` is compatible with activation.
- Existing `db.add_log` and live SSE already mask secret-like values at their write/delivery seams. The
  remaining risk is historical/raw re-import, not a claim that every current log insert leaks.

## Rejected shortcuts

1. **Wrap all contexts in `app.main.lifespan`.** Rejected by the Uvicorn ContextVar measurement and
   cutover restart reset.
2. **Configure only `KnowledgeService` with an empty registry.** The tool becomes healthy but returns no
   topic knowledge; generic text still lacks a projection and scope.
3. **Configure `projection_mode` globally and call it shadow.** This immediately diverts legacy memory
   reads, violating “legacy active owner,” and an empty candidate returns false absence.
4. **Run `ia_task_store_mode(shadow)` directly on the live snapshot.** It can write outside the root,
   corrupt under concurrency, drift after a mirror failure, and fail on the next restart.
5. **Trust the T7 frozen inventory/import harness.** It is one-project, three entries stale relative to
   current main, accepts a fake importer, and never persists its receipt in the positive test.
6. **Use raw scope strings as project IDs.** They violate URI grammar, leak paths, create mismatched task
   versus legacy IDs, and include historical `/tmp`/missing roots.
7. **Let agents supply `project_id`/`cross_project`.** The shared internal token and generic tool make
   that an authorization bypass; scope must be server-derived from the proof-bound session.
8. **Import current working files and trust the declared commit.** Directly refuted by the accepted
   all-zero commit.
9. **Restart or reconnect by clearing sessions.** Forbidden and unnecessary; the normal restart and
   `restart-cli` preserve native IDs.
10. **Delete SQLite/FTS/vector after canonical activation.** The architecture and current code require
    them as rebuildable projections; deletion remains outside the operation set.

## Minimum staged activation and later canonical gate

### Shadow generation 2

1. Resolve one private runtime state root (`STATE_DIRECTORY`, otherwise a fail-loud XDG fallback) and
   create only new generation-owned paths. Record the live DB/vec paths and the pinned Git heads.
2. Build a scope registry for all 18 resumable scopes. Each entry binds normalized scope, canonical
   lowercase slug, optional legacy task project, repository root/head, and privacy/import policy.
3. Take one WAL-safe task/log snapshot. Persist its cutoff/source head/manifest once. Before any write,
   reject path escape, duplicate canonical slug, invalid URI, unmapped live scope, and unresolved secret
   candidates.
4. Materialize candidate task/evidence/current projections off to the side. Serialize task shadow writes
   and persist mirror debt/outbox; legacy remains the response owner.
5. Configure the module-global knowledge/projection runtime for `/api/knowledge`, but make legacy memory
   routing consult persisted active owner and remain on RAG during shadow.
6. Persist a generation-2 receipt whose bytes are replay-idempotent. Restart via `/api/restart`, keep all
   `session_id` values, and reconnect stale MCP processes at turn boundaries.
7. From a real MCP process, query with generic `query` normalized to `text`; server derives project scope.
   Repeat mechanically across the scope registry and prove zero cross-scope rows.

### Canonical generation 3 (authorized later, still gated)

Generation 3 is impossible until persisted `shadow_parity`, `privacy`, `rollback`, `prompt_delivery`,
`live_cutover`, and rebuildable `projection` receipts all bind the same inventory/canonical/projection/
indexed/prompt heads. The transition must atomically persist active owner and its receipt, then survive a
restart and a real MCP query. SQLite/FTS/vector and historical Markdown remain present. Rollback emits a
new generation and switches owner; it does not delete canonical history. No implementation may expose a
projection-delete parameter or call `clear-session`.

## Affected files, risks, and Phase 2 oracle targets

- `app/main.py` — runtime construction order and shutdown.
- New or existing IA runtime/state owner under `app/ia/` — state-root resolution, scope registry,
  persistent generation/receipts, locks/outbox, and load-existing behavior.
- `app/tm.py`, `app/ia/task_store.py` — request-visible shadow owner, canonical project mapping,
  root containment, concurrency and restart reconciliation.
- `app/routes/knowledge.py`, `app/mcp_stdio.py`, `app/mcp_proof.py` — proof-bound server scope,
  query/text normalization, operation authorization, cross-project policy.
- `app/ia/knowledge.py`, `app/ia/projections.py`, `app/routes/memory.py` — real Git import adapter,
  candidate versus active read selection, bounded rebuild, canonical/SQLite/vector debt.
- `app/ia/cutover.py`, `scripts/ia_document_inventory.py`, `scripts/ia_migrate_documents.py` — per-scope
  inventory, durable state/receipts, restart idempotence.
- `app/manager.py`, `app/session.py` — prompt-overlay migration and safe MCP reconnect without native
  session loss.
- `deploy/orchestra.service*` — converge the `StateDirectory` contract; no restart until the behavior
  oracle and shadow preflight are green.

Phase 2 must end in a committed RED behavior oracle that exercises the real `app.main` activation without
starting TG, proves HTTP/task scope propagation, runs two concurrent task mutations, restarts the runtime
twice, checks byte-identical receipts and Git evidence, verifies legacy shadow responses, checks every
registered scope, and proves all native session IDs unchanged. The current synthetic suite stays as a
regression check but is not that oracle.

## Confidence per finding

| Finding | Confidence and evidence tier |
|---|---|
| Lifespan ContextVar wiring cannot activate HTTP | **CONFIRMED** — direct minimal-Uvicorn measurement plus Uvicorn-shaped task/thread path. |
| Current service is unconfigured | **CONFIRMED** — two real MCP calls returned `knowledge_not_configured`; `app.main` has no owner entry. |
| Current task snapshot is unsafe to materialize | **CONFIRMED** — WAL-backup manifest/path measurement found invalid IDs and root escape; no live write was attempted. |
| TaskStore needs serialization/recovery | **CONFIRMED** — 3/3 forced concurrent scratch corruptions plus source showing no lock. |
| Scope derivation/auth is missing | **CONFIRMED** — captured real MCP wrapper body and HTTP source trace. |
| Frozen Git evidence adapter is not real | **CONFIRMED** — scratch accepted a bogus commit and rejected the frozen cold alias against production importer. |
| Restart/receipt idempotence is missing | **CONFIRMED** — direct scratch re-entry failures plus source-owned in-memory defaults. |
| Projection rebuild is operationally material | **CONFIRMED for Orchestra scope** — two completed exact full rebuilds; **UNCERTAIN for all scopes** because canonical scope identity is unresolved. |
| Proposed staged runtime is the smallest safe design | **LIKELY** — every strictly smaller shortcut has a measured falsifier; no implementation oracle exists yet. |
| Generation 3 can be safe after these repairs | **UNCERTAIN** — authorized but not yet implemented or rehearsed against live shadow receipts. |

## Mechanical review and tests

Model/provider/eval/review calls were explicitly forbidden, so no reviewer was invoked. The review route
is mechanical completeness: every requested probe appears above; all factual claims cite current source
or exact scratch/live-backup measurements; counter-evidence and rejected shortcuts are explicit.

```text
/mnt/data/Projects/Python/orchestra/.venv/bin/python -m pytest \
  docs/tasks/315/acceptance/test_t2_task_behavior.py \
  docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py \
  docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py \
  docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q
..........................................................               [100%]
58 passed in 2.69s
```

An attempted `UV_NO_SYNC=1 uv run ...` created an empty worktree venv and failed at collection setup with
`No module named pytest`; it is not a RED behavior result and is excluded. The successful command uses
the live service interpreter without starting `app.main` or TG.

## Sources opened in this phase

All sources are local primary source or direct measurement (evidence tiers 1–2):

1. `app/main.py:340-395,419-439` — lifespan ordering and route inclusion.
2. `app/tm.py:1233-1717`; `app/routes/tm.py:42-60,82-240` — legacy aliases, ContextVar owner,
   snapshot, dual-write order, route threads, and task scope resolver.
3. `app/ia/task_store.py:160-305,308-544,650-805,1217-1249` — manifest identity/pathing,
   full projection replacement, generation commits, and replay.
4. `app/ia/knowledge.py:165-181,603-798,801-989`; `app/ia/events.py:52-145` — registry,
   fact/evidence writes, module-global owner, payload dispatch, and event persistence.
5. `app/ia/projections.py:103-272,275-585,588-739`; `app/routes/memory.py:31-108` — current/FTS,
   fallback/debt, legacy import, and memory owner switch.
6. `app/ia/cutover.py:23-56,116-226,229-405,408-597`; `scripts/ia_document_inventory.py:20-194`;
   `scripts/ia_migrate_documents.py:1-16` — prompt/inventory gates, in-memory generation, receipts,
   Git byte reader and administrative adapter.
7. `app/mcp_stdio.py:39-55,85-109,337-345,504-527,2684-2705`; `app/routes/knowledge.py:24-47`;
   `app/mcp_proof.py:29-66` — MCP scope/session headers, access modes, HTTP forwarding and missing
   knowledge authorization.
8. `app/pipeline.py:568-601`; `app/manager.py:325-355,1744-1867,2181-2303,2419-2529`;
   `app/session.py:960-1028,1219-1284`; `app/backend_codex.py:2763-2790` — assembled prompts,
   legacy overlay preservation, restart resume and MCP reconnect.
9. `app/db.py:15-41,1578-1612`; `app/rag_service.py:19-80,123-198`; `app/rag.py:27-63` — live DB/RAG
   paths, masking, singleton and vector scope boundary.
10. `deploy/orchestra.service:27-65`, `deploy/orchestra.service.template:5-20`, live `systemctl cat/show`
    and filtered `/proc/3798207/environ` — actual interpreter/cwd and absent `STATE_DIRECTORY`.
11. `docs/tasks/315/report.md`, its T2/T3b/T4/T7 acceptance files/fixtures, and
    `docs/kb/knowledge-base-architecture.md` — cold design/test evidence checked against current code,
    not treated as independent truth.
12. WAL-safe backup, Uvicorn, scope/path, payload, concurrency, Git-import, cutover-restart, prompt,
    secret-shape and projection-cost commands executed in this session; exact results are recorded above.

## Validation debt

- No typed `knowledge` promotion was attempted: the live service is unconfigured, and Phase 1 forbids
  mutating live state. The research artifact becomes immutable Git evidence when committed; canonical
  promotion is deferred to the verified shadow runtime.
- Full all-scope projection time/RSS is unmeasured until the scope registry defines the correct corpus.
- The 8 file and 340 log secret-shape matches were not opened or classified as real versus examples;
  unresolved matches remain a fail-closed privacy debt.
- No live restart, agent reconnect, shadow write, generation 3, rollback, or projection deletion was
  performed in this phase.
