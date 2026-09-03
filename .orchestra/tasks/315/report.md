# #315 — final typed information architecture report

Date: 2026-08-25
Verified tree: `c2ea45fa0c8fce41c942a37f78204ebd1def3699`

## Verdict

The seven-ticket architecture is merged and its frozen current-main behavior is green. The final
non-superseded gate is `118 passed, 1 deselected`; the one deselection is the permanently superseded
T3 S11 assertion that required generated Markdown. T7 itself is `16 passed`.

This is a code-and-oracle verdict, not a live migration claim. No Orchestra service restart, live
database/corpus migration, or live shadow/canonical cutover was performed. Existing agents must not be
described as uniformly running the new prompt/tool contract yet.

## Original problem

Orchestra had several overlapping authorities: task state in SQLite, knowledge in hand-written
Markdown, semantic results in FTS/vector/RAG, session history in runtime-specific archives, and agent
instructions that sent different runtimes to those stores directly. A stale projection or file could
therefore look authoritative; task/fact/evidence identity and provenance were not one typed contract;
merge cleanup was not bound to one durable receipt; and a prompt-source edit could leave one runtime's
assembled prompt stale.

The target was one agent-facing typed data plane without erasing historical evidence:

- canonical task, fact, evidence-reference and session state/events are structured Git JSON;
- one `knowledge` tool owns canonical knowledge/evidence access;
- SQLite current rows, FTS and vector indexes are content-bound, rebuildable projections;
- old Markdown remains addressable evidence, but never becomes a second current truth;
- legacy → shadow → canonical ownership changes are generation-bound and reversible.

## Final architecture in agent terms

### Identity and canonical owners

- `app.ia.namespace.build_uri/parse_uri` owns typed `orch://` addresses
  (`app/ia/namespace.py:103,136`).
- `app.ia.schema` validates typed records, privacy projection and canonical bytes
  (`app/ia/schema.py:426-494`). Private values are excluded before prompt/FTS/vector payloads.
- `app.ia.task_store.TaskStore` owns Git-canonical task state/events/evidence links; `app.tm` keeps the
  stable task facade and selects legacy/shadow/canonical mode through `ia_task_store_mode`
  (`app/ia/task_store.py:308`, `app/tm.py:1325`). Project-scoped `#N` remains the display reference;
  stable IDs are the identity.
- `app.ia.knowledge.KnowledgeService` owns fact registry, evidence-backed promotion, explicit
  superseded/disputed/rejected state and canonical query (`app/ia/knowledge.py:165,811,898`). The real
  agent chain is MCP `knowledge` → `POST /api/knowledge` → `knowledge_api`
  (`app/mcp_stdio.py:2685`, `app/main.py:439`).
- `app.ia.recovery` plus `AgentSession.commit_archive` and
  `SessionManager.commit_session_archive` own immutable session archive-before-extraction semantics
  (`app/ia/recovery.py:271`, `app/session.py:2913`, `app/manager.py:1165`). Pack validation/restore and
  replay/rollback live in `scripts/ia_pack.py:275,357` and `scripts/ia_replay.py:107,149`.
- `app.ia.merge_receipts` binds the verified target, task, evidence, heads and acceptance revision
  before finalization/cleanup (`app/ia/merge_receipts.py:90-427`; consumers in
  `app/routes/sessions.py:1577-1980` and `app/merge_operations.py:185-198,1706-1722`).

### One knowledge tool, progressive payloads

Fresh MCP processes expose exactly one knowledge reader: `knowledge`. Its detail levels are
`summary < record < evidence`; direct file/SQLite/vector operations are rejected. The old
`search_memory` Python callable remains for in-process compatibility, but it is no longer decorated or
registered as an MCP tool (`app/mcp_stdio.py:2685-2708`).

Fresh-process registry measurement under `ORCHESTRA_ROLE=orchestrator`:

| Access mode | Tool count | `knowledge` | `search_memory` |
|---|---:|---:|---:|
| full | 41 | 1 | 0 |
| reducer | 4 | 1 | 0 |
| read-only | 14 | 1 | 0 |

### Projections are not truth and are not deleted

`app.ia.projections` keeps `canonical_head`, `projection_head` and `indexed_head` separate and returns
visible debt (`app/ia/projections.py:393-529`). If SQLite content/head is stale or a projection write
fails, the current canonical record remains available through canonical fallback. Vector/index failure
adds debt; it cannot manufacture a canonical result.

SQLite, FTS and vector remain useful hot/query projections and compatibility surfaces. They are not
deleted by #315. T7 only exposes a guarded deletion callback; forged parity with unequal normalized
heads is rejected before that callback can run. Keeping projections makes rebuild, rollback and old
reader compatibility possible while canonical JSON remains the authority.

### Historical Markdown

The T7 frozen inventory covers 1,505 paths at source commit
`34fb2350a8224f2991dbe722afc29070daf02bee`:

- 1,346 immutable evidence/cold-archive paths (`docs/tasks`, `docs/kb`, session archives and the
  historical TODO source);
- 159 active instruction/resource sources (pipeline prompts/skills, worker memory, `CLAUDE.md` and
  `pipeline.yaml`).

Each row binds path, class, Git blob, SHA-256, size and deterministic typed alias. Historical Markdown
is byte/path-preserved cold evidence addressed by `orch://`; it is not regenerated, bulk rewritten, or
queried as current truth. Active prompt/skill source remains hand-authored Git source; assembled prompts
and native skill homes are delivery projections.

### Reversible migration and cutover

`scripts.ia_document_inventory.inventory_api` builds the source-commit manifest
(`scripts/ia_document_inventory.py:142`). `scripts.ia_migrate_documents.migration_api` is the
administrative adapter into `app.ia.cutover.cutover_api`
(`scripts/ia_migrate_documents.py:11`, `app/ia/cutover.py:262,574`). There is no startup caller: a live
operator must explicitly configure `document_cutover_mode` and execute the sequence.

The state machine is:

1. generation 1: legacy owner;
2. generation 2: legacy remains active, canonical is the shadow owner; identical retry is idempotent;
3. generation 3: canonical owner only after parity, privacy, rollback, prompt-delivery,
   live-cutover and rebuildable-projection gates verify;
4. generation 4: rollback restores legacy ownership using the expected generation while preserving
   canonical events.

Each transition writes a deterministic verified JSON receipt with from/to owner and generation,
inventory head, canonical/projection/indexed heads and prompt-delivery head
(`app/ia/cutover.py:338-405,408-570`).

## Ticket-by-ticket current-main evidence

The symbol probe imported the frozen public contracts from current main; it checked behavior owners,
classes/methods, adapters and exceptions rather than relying on commit titles.

| Ticket | Current owner/surface | Focused result |
|---|---|---:|
| T1 | namespace + schema/privacy | `21 passed in 0.10s` |
| T2 | `TaskStore` + real `app.tm` facade | `21 passed in 0.85s` |
| T3 | evidence/events/knowledge; S11 permanently superseded | `17 passed, 1 deselected in 0.25s` |
| T3b | one agent API, JSON-only output, no storage fallback | `9 passed in 0.80s` |
| T4 | projection owner, separate heads/debt/fallback | `12 passed in 0.79s` |
| T5 | session recovery, pack validation, replay/privacy | `11 passed in 0.38s` |
| T6 | durable merge receipt before finalization/cleanup | `11 passed in 2.98s` |
| T7 | inventory, runtime delivery, cutover/rollback | `16 passed in 1.56s` |

Public-symbol probe results: T1 12, T2 24, T3 18, T3b 5, T4 12, T5 13, T6 10 and T7 5
required symbols all present.

## Verification commands

### Exact T7

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py -q
................                                                         [100%]
16 passed in 1.56s
```

### Combined non-superseded T1–T7

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t1_namespace_behavior.py docs/tasks/315/acceptance/test_t2_task_behavior.py docs/tasks/315/acceptance/test_t3_promotion_behavior.py docs/tasks/315/acceptance/test_t3b_agent_only_knowledge_behavior_v2.py docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py docs/tasks/315/acceptance/test_t7_prompt_document_cutover_behavior.py --deselect 'docs/tasks/315/acceptance/test_t3_promotion_behavior.py::test_t3_exact_promotion_scenario[S11]' -q
........................................................................ [ 61%]
..............................................                           [100%]
118 passed, 1 deselected in 4.87s
```

### Prompt assembly

```text
uv run python -m pytest tests/test_default_pipeline.py -q
131 passed in 2.44s
```

T7 additionally assembles 20 real runtime×role prompts through the Claude, Codex, Grok and Harness
consumers and verifies both Claude/Codex native skill homes.

### MCP compatibility

```text
ORCHESTRA_ROLE=orchestrator uv run python -m pytest tests/test_mcp_stdio.py tests/test_search_deadline.py tests/test_reducer_role.py -q
125 passed in 4.84s
```

This retains the non-agent `search_memory` compatibility callable and its deadline behavior while the
fresh MCP registry exposes only `knowledge` as the agent reader.

### Frozen hashes

| T7 artifact | SHA-256 |
|---|---|
| behavior oracle | `2d5ea2f9a751a9489a95bc31f63cad1f0ce490cb8c9883224497ed2bfff1b2f0` |
| contract | `404b1ad09d49d3f40c99ad196bcaccad220cadb0012239bc746580d0f4f72362` |
| records | `b193804bd2466711c785dc12fca5f26b96833eebd3f8e472fa159307228850b0` |
| 1,505-path inventory | `1f65c67eea34c615ef18d68e9c9fe2b9de68e8819b5dc2284022b9c67d52e51f` |

`test_t7_control_frozen_inventory_and_t1_t6_hashes_are_exact` also verifies all 21 pinned T1–T6
test/contract/record hashes and every frozen Git blob: `1 passed in 0.21s`.

Final hygiene: `git diff --check` → exit 0 with no output.

## Mutation and failure coverage

The 118-node gate covers namespace confusion/private-field leakage; task facade/store disconnection;
source-less or conflicting fact promotion; generated human output; direct file/SQLite/vector and route
wiring bypass; stale/forged projection heads; extraction failure; partial pack write; privacy leakage;
tombstone/rollback loss; duplicate archive/event/receipt; cleanup before receipt; and secondary RAG
masking.

T7's seven compound mutants specifically prove rejection of:

1. Markdown + JSON dual truth;
2. a source-only prompt patch while one runtime assembly stays stale;
3. forged zero-mismatch parity followed by SQLite deletion;
4. rewritten historical bytes with a simultaneously updated alias;
5. SQLite/vector fallback hiding canonical failure;
6. a legacy reader bypassing the typed API;
7. rollback against the wrong generation.

The valid alternate reverses inventory order, adds safe metadata and wraps prompts with harmless layout
text without changing normalized ownership, heads or delivery.

## Breaking and compatibility surface

- Breaking for newly connected agents: `search_memory` is no longer an MCP tool. Use `knowledge` with
  `summary`, `record` or `evidence` and typed `orch://` references.
- Non-breaking in-process compatibility: `app.mcp_stdio.search_memory` remains callable and its
  timeout/debt behavior remains tested.
- Task tool names and legacy facade response shapes remain available; canonical receipt fields are
  additive.
- SQLite/FTS/vector are retained. No live tables or indexes were deleted.
- Historical Markdown paths and bytes remain valid evidence references; they are no longer current
  authority.
- No user-facing Markdown/HTML summary generator was introduced by the data plane.

## Live-state boundary

| Surface | State now | Required action | Evidence / non-claim |
|---|---|---|---|
| Git implementation and frozen oracles | **MERGED CODE** | none | current tree `c2ea45fa`; all named gates green |
| Fresh MCP process | **MERGED CODE, verified in scratch** | reconnect each existing agent (or restart Orchestra to reconnect them in bulk) | fresh full/reducer/read-only registries: `knowledge=1`, `search_memory=0` |
| Existing verifier MCP process | **NOT YET ACTIVE** | agent reconnect | this live session received the new instructions but has no callable `knowledge` tool |
| Pipeline prompt/skill sources | **MERGED CODE** | fresh assembly/re-injection; reconnect is the deterministic full refresh | 131 prompt tests + T7 20-runtime×role assembly green; no claim every live session refreshed |
| FastAPI/task/session/merge wiring from T1–T6 | **NOT YET ACTIVE in the running service** | explicit Orchestra restart | Python routes/modules are memory-resident; no restart was performed here |
| Existing SQLite task rows and legacy corpus | **NOT EXECUTED** | operator runs frozen inventory, then explicit shadow generation | all migration tests used isolated temporary roots; no live DB was opened or changed |
| Canonical owner switch | **NOT EXECUTED** | inspect shadow parity/privacy/rollback/prompt/live receipts, then explicitly request generation 2→3 | no startup caller invokes `migration_api` or `cutover_api` |
| Live cutover/rollback receipts | **NOT EXECUTED** | produced only by an explicit live transition | current evidence is scratch-oracle output, not a production receipt |
| SQLite/FTS/vector removal | **NOT EXECUTED and not required** | retain/rebuild as projections | deletion is gated; #315 does not authorize destructive removal |

The safe activation order is: restart Orchestra to load main-process Python → reconnect agents so their
MCP/native skills are fresh → build and inspect the live frozen inventory → run legacy→shadow only →
verify all gate receipts → explicitly authorize canonical generation 3. A failed cutover stays on legacy;
after canonical activation, rollback requires the exact current generation and emits generation 4.

## Remaining decisions

No information-architecture decision remains open. One operational user decision remains: choose the
maintenance window and explicitly authorize the service restart/agent reconnect and, separately, the
live shadow→canonical cutover after reviewing its receipts. This report does not grant either action.

## Review

Review: none — provider/model/eval/review calls were explicitly forbidden. The changed artifact in this
finalization is this report; its consumers are the task owner and future operators. Evidence is the
pre-existing frozen acceptance suite, current-main symbol probe, fresh-process MCP registry probe and
the exact command outputs above.

The historical `docs/kb/information-architecture-synthesis.md` was not rewritten: T7 now classifies it
as immutable cold evidence, so changing it would violate the final boundary. Canonical promotion could
not be performed from this still-live pre-reconnect session because its MCP registry lacks the new
`knowledge` tool.
