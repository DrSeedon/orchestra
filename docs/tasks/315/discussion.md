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
| 7. Progressive delivery | Compact hot topic registry, warm typed facts, cold evidence/session details; heads and debt in every result | Load all Markdown/log context or adopt OpenViking L0/L1/L2 wholesale | Requires summary/projection generation and fallback; avoids prompt bloat and stale silent misses | A/B/A/B frozen workload shows no reduction in tool calls/footprint or causes task-success loss larger than accepted budget |
| 8. Rollout and rollback | Fresh frozen manifest, shadow dual-read, replay parity, projection cutover, forward rollback/rebuild; no live service mutation during research | Direct cutover after migration script | Shadow mode costs storage/time; direct cutover risks loss of task/fact identity and stale projections | parity or rollback rehearsal fails; then keep old facade and redesign migration before any write |

## Immediate user decisions

The only choices that block Phase 3 implementation are (a) contiguous global #N versus disjoint
project-scoped leases, (b) private fields outside Git versus private Git policy, and (c) whether any
supersession requires human approval. The proposed plan assumes project-scoped stable IDs + preserved
project #N, classified private fields with no secret in indexes, and deterministic evidence-backed
promotion with explicit supersedes/disputed.

Even after these choices, Phase 3 remains blocked until every ticket has a behavior-specific RED oracle
designed and frozen. The smoke probes in acceptance/ are only missing-seam diagnostics.

## Explicit non-decisions

- OpenViking is a mechanism reference, not a dependency decision.
- Vector backend/reranker/embedding tuning is not reopened; #256 localized the seam earlier.
- #298 model routing remains deferred and is not part of this information architecture.
- YouGile/payments are removal work under #299/#309, not migration targets.
