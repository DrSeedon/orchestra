# #315 — discussion board for user and orchestrator

The recommendations below are defaults for user discussion. PLAN READY means architecture/discussion
ready only; they do not claim that the candidate architecture has been implemented or behaviorally
evaluated.

| Choice | Recommended default | Alternative | Irreversible / operational consequence | Evidence that would reverse it |
|---|---|---|---|---|
| 1. Physical arrangement | One logical typed namespace/data plane; Git canonical bodies, SQLite current projection, FTS/vector derived | Fully separate task and KB stores, or OpenViking wholesale | A namespace gives one resolver/head vocabulary; contracts remain separate. Choosing separate independent stores creates future identity/link migration | replay shows cross-domain contention, privacy leak, or measurable operational coupling that separate stores avoid without dual truth |
| 2. Fact schema strictness | Strict minimum: stable_id, fact_key, status, valid-time, provenance, confidence, canonical head | Flexible Markdown blocks with later typing | Rejecting a promotion at write time may slow authoring; flexible input keeps today’s orphan/source-link failures | blinded promotion audit shows strict schema loses more valid findings than it prevents, with a deterministic repair path |
| 3. Promotion and supersession authority | Evidence-backed write API; same-key conflict requires explicit supersedes or disputed; similarity only suggests candidates | Human reviewer approval for every supersession | API/CAS is deterministic but places responsibility on validator; reviewer gate adds latency and coordination | any accepted corpus contains a false current/superseded choice despite complete evidence and CAS; or legal policy requires human signoff |
| 4. Task store sequencing | Implement #299 task canonical/projection boundary first, then reuse it for knowledge links | Implement both behind separate projections, or knowledge first | #299 first settles stable ID/#N/head/merge semantics; it delays fact retrieval but avoids two incompatible migration seams | #299 user decision on lease/global #N remains unresolved, while a typed-fact pilot can prove value without task identity changes |
| 5. Session memory | Immutable session/cold history; explicit promotion only after evidence validation | Automatic extraction of all session memories into current facts | Safe provenance and privacy cost more writes; auto extraction risks source-less/collateral facts | a frozen promotion audit shows automatic extraction has zero false promotion and complete provenance across all allowed memory classes |
| 6. Private data and retention | Classify fields; keep private fields out of prompt/FTS/vector; use private Git or separately governed encrypted store; tombstone is not legal erase | Keep sensitive values in canonical Git with access controls only | Separate private store increases operational complexity; keeping values in Git can make legal purge/history rewrite unavoidable | documented legal policy plus secret-scan/restore measurements show private Git is acceptable and purge procedure is approved |
| 7. Progressive delivery | One typed agent tool returns structured summary/record/evidence payload levels with heads/debt; cold archives only through evidence refs | Separate query/promotion tools, direct files/SQLite/vector, or generated human summaries | One owner and machine payloads minimize branches and dual truth; direct storage access makes stale fallback indistinguishable from canon | frozen tasks show one tool loses required evidence or materially increases agent failure/tool calls |
| 8. Rollout and rollback | Fresh frozen manifest, shadow dual-read, replay parity, projection cutover, forward rollback/rebuild; no live service mutation during research | Direct cutover after migration script | Shadow mode costs storage/time; direct cutover risks loss of task/fact identity and stale projections | parity or rollback rehearsal fails; then keep old facade and redesign migration before any write |
| 9. Existing documents and agent cutover | After corrected T3b plus T4–T6, classify every legacy document; structured Git JSON/registry is canonical, historical Markdown is byte-preserved cold evidence/archive, and no README/topic/human projection is generated | Keep/generated Markdown or SQLite as co-master, or rewrite evidence into new records | A single agent-only owner removes duplicate output and truth paths but requires alias manifests, prompt delivery checks and reversible compatibility | byte-preserving inventory, shadow parity or assembled-prompt checks cannot cover the corpus/runtimes, so retain legacy owner and redesign before cutover |

## Immediate user decisions

The user approved project-scoped stable IDs + preserved project #N, private/secret fields outside
ordinary Git/prompt/FTS/vector, and deterministic evidence-backed promotion with explicit
supersedes/disputed plus a human gate for conflicts/sensitive classes. These choices no longer remain
open; each ticket's separately frozen behavioral oracle is still mandatory.

Even after these choices, Phase 3 remains blocked until every ticket has a behavior-specific RED oracle
designed and frozen. The smoke probes in acceptance/ are only missing-seam diagnostics.

## User correction — agent-only knowledge boundary (2026-08-24)

The earlier T7 choice that generated README/topic Markdown is superseded. The user wants no
human-readable generated output: optimize for agents and maximum simplicity. Merged T3 currently passes
its frozen suite (`18 passed`) but conflicts with this decision in measured, exact ways:

- `KnowledgeService._write_topic_documents()` is called at initialization and new-topic promotion (2
  call sites); the base two-topic registry generates 3 Markdown files, and adding one topic generates 4;
- the frozen T3 contract owns 2 Markdown layout paths (`README.md`, `topic.md`), and its oracle has 2
  behavior assertions requiring those outputs;
- current inventory to retain rather than regenerate is 1,281 `docs/tasks/**/*.md`, 20 `docs/kb/*.md`,
  3 session-archive Markdown files, 23 pipeline prompt Markdown files, 2 Codex skill Markdown files plus
  TODO.md/CLAUDE.md/AGENTS.md.

T3b preserves T3's evidence/idempotency/conflict/valid-time semantics but removes every Markdown/human
projection write. One agent-facing `knowledge` tool/API owns promotion, query and evidence import with
structured progressive payloads (`summary`, `record`, `evidence`). Missing canonical truth fails closed;
caller-supplied file paths, SQLite payloads or vector hits can never serve as an alternate truth path.
T4 is stopped until this corrective oracle and implementation are merged.

## User decision — final T7 boundary (corrected 2026-08-24)

T7 occurs only after corrected T3b and the T4–T6 core data plane are implemented and verified. Canonical task state,
events and evidence references are structured Git records (JSON), not arbitrary Markdown. Typed fact
and fact-event records follow the same rule. Existing `docs/tasks/*.md` research/plan/review/report
bodies remain immutable evidence or human documentation; migration adds typed references and aliases
without rewriting their historical bytes or Git lineage.

Existing documents are inventoried and assigned exactly one migration class:

- canonical structured record/index — task/fact/event/evidence-ref/resource/skill identity owned by JSON;
- immutable evidence/cold archive — existing `docs/tasks/*.md`, `docs/kb/*.md`, measurements, review
  artifacts, session archives and retired TODO history retained at their paths and addressed by typed
  evidence URI + commit/blob/anchor;
- active skill/resource source — hand-authored instruction source tracked by content hash, not generated;
- derived machine projection — SQLite current/FTS/vector state rebuilt from canonical JSON and never
  queried by agents as an independent truth path.

Active TODO/instruction/prompt/skill sources are classified deliberately, not bulk-promoted: an active
instruction becomes a typed `skill`/`resource` record pointing to its owning source and content hash;
assembled prompts are delivery projections. Agents must use typed `orch://` task/evidence/fact IDs and
the single typed knowledge tool, and must never read files, SQLite or vector hits as independent truth.

No README, topic Markdown, HTML/text summary or other human projection is generated. Cutover is
legacy→shadow→canonical. SQLite stays a rebuildable hot projection/compatibility layer and
is not destructively removed until shadow parity, privacy, rollback rehearsal, all-runtime assembled
prompt verification and live cutover receipts pass. Rollback changes the active owner/generation and
replays forward; it does not rewrite historical evidence or delete newer canonical events.

## Explicit non-decisions

- OpenViking is a mechanism reference, not a dependency decision.
- Vector backend/reranker/embedding tuning is not reopened; #256 localized the seam earlier.
- #298 model routing remains deferred and is not part of this information architecture.
- YouGile/payments are removal work under #299/#309, not migration targets.
