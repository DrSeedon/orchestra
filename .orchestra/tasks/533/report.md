# #533 — CI red tests

Imported modules: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-red-tests/app/__init__.py`, `app/mcp_stdio.py`, `app/session_hibernate.py`.

| Test | Diagnosis | Change | Evidence |
|---|---|---|---|
| `test_merge_ref_gate.py::test_unknown_leading_ref_is_still_refused_before_git` (renamed) | законно устарел тест | Expect merge success under `979c4631`; assert durable `finalization.unresolved_task_refs` warning | Focused test passed; full file included in `38 passed` run |
| `test_message_provenance_review_433.py::test_review_live_mcp_receipt_persists_agent_principal` | устарел тест/fixture | Add the manager lock seam required by current route | Full provenance file passed in `38 passed` run |
| `test_review_receipt_migration_436.py::test_apply_writes_the_full_receipt_row_for_every_declared_column` | сломан код | Migration `_receipt()` now supplies `production_path_heads_json`, `requested_by_session_id`, `requested_by_worker` | Mutation removing defaults → `NOT NULL constraint failed: review_receipts.production_path_heads_json`; restored test passed |
| `test_search_deadline.py::test_timeout_busy_stale_tell_agent_to_stop_waiting[transport_timeout-*]` | устарел тест | Assert grep fallback mechanics, not exact argv quoting | Full search-deadline file passed in `38 passed` run |
| `test_search_deadline.py::test_timeout_busy_stale_tell_agent_to_stop_waiting[search_busy-*]` | устарел тест | Same behavioral assertion | Full search-deadline file passed in `38 passed` run |
| `test_search_deadline.py::test_timeout_busy_stale_tell_agent_to_stop_waiting[search_stale-*]` | устарел тест | Same behavioral assertion | Full search-deadline file passed in `38 passed` run |
| `test_audit0901_session.py::test_heartbeat_dead_process_recovery_publishes` | CI-only test isolation | Pin process-liveness capability seam instead of global registry state | Full audit session file passed in `38 passed` run |
| `test_audit0901_session.py::test_heartbeat_zombie_without_backend_publishes` | CI-only test isolation | Pin persistent/event-stream capability seam | Full audit session file passed in `38 passed` run |
| `test_orphan_pid_identity.py::test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd` | CI-only missing external CLI | Pin matcher binaries to `/bin/true` and `/bin/false` | Full orphan file passed in `38 passed` run |
| `test_orphan_pid_identity.py::test_t1_unverifiable_candidate_does_not_abort_later_orphan_cleanup` | CI-only missing external CLI | Pin Codex matcher binary to `/bin/true` | Full orphan file passed in `38 passed` run |
| `test_runtime_handoff_v2.py::test_t3_claude_target_commits_only_after_canary_and_capability_receipts` | CI-only missing credentials | Fixture creates isolated Claude config with fake credentials | Full handoff file: `39 passed, 2 warnings` |
| `test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress0-capability0-handoff_ingress_rejected]` | CI-only missing credentials | Same hermetic fixture | Full handoff file passed |
| `test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress1-capability1-handoff_ingress_rejected]` | CI-only missing credentials | Same hermetic fixture | Full handoff file passed |
| `test_runtime_handoff_v2.py::test_t3_invalid_receipt_never_disconnects_or_confirms[ingress2-capability2-handoff_capability_unsupported]` | CI-only missing credentials | Same hermetic fixture | Full handoff file passed |
| `test_mcp_stdio.py::test_file_first_memory_tool_surface_keeps_only_search_fallback` (renamed) | законно устарел тест; CI also lacks `rg` | Remove special-status requirement and retain the core no-legacy-`knowledge` surface check; fallback behavior remains covered by `test_disabled_rag_names_the_flag` | Full MCP file: `118 passed` |

Commands:

- `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_merge_ref_gate.py tests/test_message_provenance_review_433.py tests/test_review_receipt_migration_436.py tests/test_search_deadline.py tests/test_audit0901_session.py tests/test_orphan_pid_identity.py` → `38 passed in 16.40s`.
- `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py` → `39 passed, 2 warnings in 10.86s`.
- `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_mcp_stdio.py` → `118 passed in 20.55s`.
- Luna `gpt5.6luna` implementation review → APPROVE, no blockers; receipt: `codex-review-impl.md`.

Review gate inputs: changed production consumer is `scripts/migrate_review_receipts.py::_receipt` → `_apply_receipts` → `review_receipts` schema; author model/runtime is the current Codex session; AC is successful apply for every current NOT NULL receipt column; named migration test output is above. Persistence/migration routed to one Luna pass. Suggestions were checked: RAG-disabled fallback already has a hermetic test, and the merge test now asserts unresolved metadata.
