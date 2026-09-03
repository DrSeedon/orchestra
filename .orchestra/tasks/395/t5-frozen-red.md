# T5 frozen RED replay

Command:

```text
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python -m pytest -q tests/test_task_create_idempotency_395.py --timeout=30
```

Output:

```text
FFFFFFFF                                                                 [100%]
FAILED tests/test_task_create_idempotency_395.py::test_t5_same_key_concurrent_calls_create_one_durable_task
FAILED tests/test_task_create_idempotency_395.py::test_t5_same_key_different_body_is_conflict_without_second_task
FAILED tests/test_task_create_idempotency_395.py::test_t5_retry_after_active_commit_replays_while_mirror_is_failed
FAILED tests/test_task_create_idempotency_395.py::test_t5_mcp_reuses_request_key_and_exposes_status_lookup
FAILED tests/test_task_create_idempotency_395.py::test_t5_http_fallback_generation_validation_and_status_authorization
FAILED tests/test_task_create_idempotency_395.py::test_t5_canonical_http_replay_conflict_and_pending_crash_recovery
FAILED tests/test_task_create_idempotency_395.py::test_t5_pending_without_active_task_returns_retry_after_instead_of_waiting
FAILED tests/test_task_create_idempotency_395.py::test_t5_canonical_store_recovers_same_deterministic_request_identity
8 failed in 13.75s
```

RC: `1`
