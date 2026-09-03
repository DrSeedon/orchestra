# T4 projection-head oracle evidence

Date: 2026-08-25. No production, application-test, database, service, provider, model, eval or
review call was made while freezing this oracle.

## Current production trace

- The sole typed agent boundary is `mcp_stdio.knowledge` → `POST /api/knowledge` →
  `knowledge.knowledge_api` (`app/mcp_stdio.py:2682-2703`, `app/routes/knowledge.py:24-35`).
- Current typed query accepts topic/status fields and returns canonical fact items, but it has no
  joined task/fact text query or `indexed_head` (`app/ia/knowledge.py:928-946`).
- The compatibility memory route currently calls `rag_service.search` directly and returns only
  `results` plus `index` (`app/routes/memory.py:30-52`). The reindex route directly schedules legacy
  backfill (`app/routes/memory.py:55-72`).
- `rag_service.search` delegates to `app.rag` and `index_status` reports only pending-file count and
  indexing state (`app/rag_service.py:123-141`, `app/rag_service.py:190-198`).
- The legacy RAG SQLite schema stores file/log chunks and FTS/vector tables without canonical,
  projection or indexed heads (`app/rag.py:345-399`); its query returns raw file/log content and can
  check a source path during reads (`app/rag.py:697-754`).
- TaskStore already detects projection payload/head mismatch against canonical JSON
  (`app/ia/task_store.py:546-560`), providing the compatibility behavior T4 must preserve and extend.

## Frozen selection and controls

The file contains exactly four invariant control nodes and seven behavior nodes. The controls pin
all eight T1–T3b contract/records fixture hashes, exercise the real existing agent query chain,
materialize nonempty real TaskStore/fact state plus one file and one log, and prove the valid-alternate
and forged-payload detectors are non-vacuous.

Control command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py::test_t4_control_fixture_hash_denominators_and_t1_t3b_compatibility_are_frozen docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py::test_t4_control_existing_agent_query_reaches_t3b_owner docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py::test_t4_control_real_task_fact_and_legacy_fixture_are_nonempty docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py::test_t4_control_valid_alternate_and_compound_mutant_detectors_are_material -q
```

Exact output:

```text
....                                                                     [100%]
4 passed in 0.64s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior.py -q
```

Exact summary and exit:

```text
....FFFFFFF                                                              [100%]
7 failed, 4 passed in 1.01s
exit 1
```

Every behavior node fails inside `_load_t4_api` with
`#315 T4 missing behavior: cannot import app.ia.projections: No module named 'app.ia.projections'`.
Collection succeeds and all controls pass; this is the missing T4 production boundary, not a path or
collection smoke.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t4_projection_heads_behavior.py` | `bfb8fde280cc9c7bb9ee04b000ff7db8f47be5bcdefe2ebf20e0a02bd57e4012` | `5e59ba622f22b0564fb14106796ca0acced2cfc5` |
| `fixtures/t4_projection_contract.json` | `4bdde5097329694d3ac51c09c6bfa5a62a2dc4b2e3db6980de7d9cbf773669ad` | `3e461bd859f3d7cbd8b7eb5633a57104bcb1028b` |
| `fixtures/t4_projection_records.json` | `d5ab3845b4490715d3fb481e6bb28c1b1ac000a047bbe409e1b2fb93573cca8c` | `63fe7bf29541031da68cfc58dce70ec7eb8b117b` |
