# T5 recovery/privacy oracle evidence

Date: 2026-08-25. No production, application-test, live database, service, provider, model, eval or
review call was made while freezing this oracle.

## Current production trace

- `SessionManager.remove` disconnects/removes the worktree, calls the existing SQLite-row
  `archive_session`, then drops the in-memory object; it does not commit structured session history
  (`app/manager.py:1165-1194`).
- `/api/sessions/{name}/compact` calls `AgentSession.compact` directly, while the current history API
  returns only `session_id_history` (`app/routes/sessions.py:1112-1134`).
- Current rollback switches a native `session_id` from that bounded list and persists it; it does not
  validate a pack, canonical body checksum or projection head (`app/routes/sessions.py:1137-1165`).
- Successful Claude compaction appends session/runtime/model/time/context metadata to a ten-entry list,
  persists the summary and returns it (`app/session.py:2887-2911`).
- `app/ia/recovery.py`, `scripts/ia_pack.py` and `scripts/ia_replay.py` are absent from the current tree
  (`git cat-file -e HEAD:<path>` returned 128 for all three).

## Frozen selection and controls

The oracle contains four invariant controls and seven behavior nodes. Controls pin ten T1–T4
contract/record hashes; construct a real `AgentSession` registered in a real `SessionManager` with
three nonempty messages; validate five canonical records including tombstone/historical/disputed and
three retention states; and complete a nonempty five-object reference pack/restore twice with alternate
object order and additive metadata.

Control command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py::test_t5_control_fixture_hash_denominators_and_t1_t4_compatibility_are_frozen docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py::test_t5_control_real_session_manager_and_nonempty_messages_are_reachable docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py::test_t5_control_canonical_state_privacy_and_projection_shapes_are_valid docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py::test_t5_control_reference_pack_restore_is_nonempty_order_independent_and_atomic -q
```

Exact output:

```text
....                                                                     [100%]
4 passed in 0.37s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t5_recovery_privacy_behavior.py -q
```

Exact summary and exit:

```text
....FFFFFFF                                                              [100%]
7 failed, 4 passed in 0.34s
exit 1
```

Every behavior node fails inside `_load_t5_api` with
`#315 T5 missing behavior: cannot import app.ia.recovery: No module named 'app.ia.recovery'`.
Collection and all controls succeed; this is the missing recovery boundary, not an existence/path
smoke.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t5_recovery_privacy_behavior.py` | `6ea24f15ab5a395e9b964cd8346fca5ea3203dd17a931cc1719aa5b3ef6b1b24` | `9fb6335ddfb072a6b0ce33a7f8cc396d5c7d95b8` |
| `fixtures/t5_recovery_contract.json` | `a614f49fed845a507201ab62368b086b80c36b38c1c0b418bef5f130c1fe4d6c` | `cc50928337770982da7d2898d1a8e8507be8ef37` |
| `fixtures/t5_recovery_records.json` | `c3dd9ddebcd6b6b49aa8db82f3672df05179ec14d3274d1d052f23ac439af1a9` | `7ff481bb89674dc9c9f0ba8cb5eed7a0678b060e` |
