# MCP proof lifecycle

- `app/manager._make_mcp_config()` runs while a live backend can still be using
  the previous MCP env. `issue_mcp_proof()` therefore must reuse the in-memory
  proof for an existing session; replacing it creates a 403 until the deferred
  backend restart. The map resets with the server process, which is the only
  proof rotation point after this fix.
- `tests/test_message_delivery_receipts_380.py::test_t380_r6_http_auth_conflict_rollback_and_name_ambiguity_are_known`
  covers 403 rejection for a proof from another session and proofless requests.
- The shell may export `ORCHESTRA_TASK_PREFIX=V-`; the shared test isolation fixture
  clears it and VPS-prefix tests opt in explicitly. Otherwise legacy numeric task refs
  in manager fixtures fail resolution as `V-<number>` tasks.
