# T4 v2 corrected setup evidence

Date: 2026-08-25. No production, application-test, database, service, provider, model, eval or
review call was made while correcting this oracle.

## Supersession

Worker commit `863c7bd9e152f9dc8da948038d007d02c020eab7` (main equivalent `020f32f1`)
is permanently superseded and excluded. V1 remains byte-identical. Its first behavior created
`tmp_path/alternate`, then passed the distinct nonexistent `tmp_path/alternate-mode` into the T3
helper; that helper writes `registry-input.json` before it creates its canonical subdirectory. The
intended implementation therefore reached 10/11 and failed before projection code with
`FileNotFoundError`.

V2 creates `alternate-mode` before calling V1's unchanged behavior. A fifth invariant control creates
an isolated alternate root, materializes the real T2 TaskStore fixture, enters the T3 knowledge mode,
promotes and queries one fact, and proves both `registry-input.json` and canonical `registry.json`
exist. This control does not import `app.ia.projections`, so it is green both before and after T4.

## Controls

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py::test_t4_v2_control_supersession_and_v1_bytes_are_frozen docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py::test_t4_v2_control_fixture_hash_denominators_and_compatibility_are_frozen docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py::test_t4_v2_control_existing_agent_query_reaches_t3b_owner docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py::test_t4_v2_control_real_task_fact_and_legacy_fixture_are_nonempty docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py::test_t4_v2_control_alternate_fixture_path_and_mutant_detectors_execute -q
```

Exact output:

```text
.....                                                                    [100%]
5 passed in 0.69s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t4_projection_heads_behavior_v2.py -q
```

Exact summary and exit:

```text
.....FFFFFFF                                                             [100%]
7 failed, 5 passed in 0.70s
exit 1
```

All seven behavior nodes fail inside V1's behavior loader on the absent production boundary:
`#315 T4 missing behavior: cannot import app.ia.projections: No module named 'app.ia.projections'`.
Collection and all five controls succeed. The alternate setup is therefore no longer hidden behind
the expected T4 RED.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t4_projection_heads_behavior_v2.py` | `8ef3a3f315f83acce4ddf8aec6886c6f7c73c36be4c31214b3d77d8380b212d5` | `ef259322b9081959a1a35d34ecab0789c25e4019` |
| `fixtures/t4_projection_contract_v2.json` | `a31380c64543aececc8a079553341ebdd5956ebe620a5359f60de4c3eab919ce` | `3309af1f4acb427d5777ad0ec5d6412d87e5c235` |
| reused `fixtures/t4_projection_records.json` | `d5ab3845b4490715d3fb481e6bb28c1b1ac000a047bbe409e1b2fb93573cca8c` | `63fe7bf29541031da68cfc58dce70ec7eb8b117b` |

`git diff --exit-code HEAD --` against the V1 test, contract, records and evidence returned exit 0.
