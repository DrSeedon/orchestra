# information-architecture-synthesis

## Установлено

- Один логический typed namespace/data plane с разными record contracts лучше отражает Orchestra: Git/task/evidence остаются canonical, SQLite current/FTS и vector являются content-bound projections с разными head receipts · docs/tasks/315/research.md §§1,4; docs/tasks/256/research.md §§3,6; 2026-08-24, #315
- Current task owner is app/db.py tm_* schema + app/tm.py business writers; current KB/evidence owner is Git Markdown; typed fact promotion has no production owner yet · docs/tasks/315/research.md §1; app/db.py:309-383; app/tm.py:295-525; 2026-08-24, #315
- Stable task UUID/ULID plus preserved project-scoped #N is required; one global MAX+1 or four-hex hash is unsafe across contours · docs/kb/task-storage-architecture.md; docs/tasks/299/research.md §§4,10; 2026-08-24, #315
- Every promoted fact needs fact_key, status, valid-time, provenance and explicit supersedes/disputed; TTL creates validation debt and never deletes history · docs/kb/knowledge-base-architecture.md; docs/tasks/315/schema.md; 2026-08-24, #315
- Canonical/projection/indexed heads must be distinct; stale current projection requires direct canonical fallback while vector/log backfill remains asynchronous · docs/tasks/256/research.md §6.4; app/rag_service.py:190-201; docs/tasks/315/state-machines.md; 2026-08-24, #315
- Historical #256/#299/#309 measurements are baselines, not future constants: #256 had 545 freshness debt and exact/current/rejected R@5 33.3%/33.3%/50.0%; #299 later recheck changed linked hashes from 486 to 489 during continued writes; #309 route/UI telemetry remained unmeasured · docs/tasks/256/eval/structure.raw.json; docs/tasks/299/research.md; docs/tasks/309/metrics.md; 2026-08-24, #315
- The six files in docs/tasks/315/acceptance/test_smoke_t*.py are existence-only missing-seam probes; they are not behavioral RED oracles and cannot satisfy ticket acceptance · docs/tasks/315/acceptance/README.md; 2026-08-24, #315
- OpenViking mechanisms transferable selectively are typed URI, content/index separation, progressive loading, explicit session archive, manifest/checksum pack validation, scoped privacy and metrics; official docs do not measure Orchestra benefit · docs/tasks/315/openviking-comparison.md; https://docs.openviking.ai/en/concepts/01-architecture; 2026-08-24, #315

## Отвергнуто

- Markdown-only prompt contract as complete current-state system · #256 measured 7/12 source-link coverage, one unlisted topic, 545 missing/stale files and stale contradiction 1/6 · 2026-08-24, #315
- One shapeless JSONL/Markdown or DB-only canonical store · #299/#295 require Git review/recovery plus separate task/fact lifecycles and identify append-only merge hotspot · 2026-08-24, #315
- Graph-first or automatic LLM compression/dedup/supersession as canonical fact authority · #256 counter-evidence and OpenViking's own compressor/async semantics require deterministic evidence-backed promotion · 2026-08-24, #315
- OpenViking wholesale adoption or atomic backup assumption · official docs describe standalone service and live/non-atomic backup; official issue #3875 reports restore-overwrite failure · https://github.com/volcengine/OpenViking/issues/3875; 2026-08-24, #315
- YouGile/payments migration into the namespace · user-approved #299/#309 cleanup decision is DELETE, not migrate · docs/tasks/309/research.md; 2026-08-24, #315

## Пробелы

- Stable fact-key vocabulary, legal private-field/purge policy and contiguous global #N decision remain open · schema/retention/lease approval not supplied; 2026-08-24, user + orchestrator
- Candidate architecture answer utility, promotion recall and A/B/A/B prompt/tool/time effect remain unmeasured · implementation and model/eval calls were explicitly prohibited · 2026-08-24, #315
- Exact OpenViking version-sensitive semantics must be rechecked before implementation · current docs/repo are active and changed through v0.4.16 on 2026-08-21 · 2026-08-24, #315

## Источники

- docs/tasks/315/research.md — joined current-state matrix, evidence, counter-evidence and recommendation
- docs/tasks/315/openviking-comparison.md — official mechanism table and transfer verdicts
- docs/tasks/315/schema.md — concrete URI/record schema and no-dual-truth rule
- docs/tasks/315/state-machines.md — lifecycle, projection, merge, session, pack and rollback contracts
- docs/tasks/315/discussion.md — user/orchestrator decision board
- docs/tasks/315/plan.md — architecture/discussion plan, smoke diagnostics and behavioral-oracle entry gate
