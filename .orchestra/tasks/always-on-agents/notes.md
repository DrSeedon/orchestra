# Always-on agents implementation

Source: helper task from parent, 2026-11-16. Scope: dedicated feat/always-on-agents
worktree only. No commit/push/restart/deploy authorized for helper.

## Work in progress
- Added online additive schema without changing SCHEMA_VERSION=3.
- Timers: atomic durable fires, no catch-up flood, cron timezone/DST handling.
- Inbox: deduplication, structured batch, coalesced wake and durable recovery.
- Delivery recovery: explicitly queued input unblocks waiting head even after Stop;
  stale orphaned copies repaired; lone stopped waiting head stays held.
- Outbox: per-target lease/pacing, quiet hours, ledger, retries and three transports.
- Deferred approvals: decision+event atomic; owner-only resolve route, expiry event.
- Dreaming: deterministic bounded curation and archive digests during idle time.

Transport semantics: external delivery is at-least-once after a crash between remote
acceptance and local acknowledgement. Webhooks carry stable Idempotency-Key. Said
ledger suppresses confirmed deliveries; it cannot promise remote exactly-once.

## R1 findings (464 collected; 459 passed, 5 failed)
- Frozen Codex transcripts require the original replay/turn-end-hold packet.
  New inbox batches remain structured; compatibility formatting is retained for legacy
  control/recovery packets unless a new inbox event is in the batch.
- Sweeper must schedule the resumed delivery tail rather than await its transport.
- Existing change_worker_model sent clean_handoff=False explicitly, violating its
  existing MCP payload contract. Omit the default field; explicit True still sent.
- None of the frozen tests were changed.

## R2 results
481 passed, 0 failed across the requested 11 suites. Manifest and instruction checks green.
Additional final review found a lease-recovery edge: a crashed final outbound attempt
could exceed max_attempts on restart. The dispatcher now fails an exhausted lease
without another transport call; a focused regression covers it. Operator GET inspection
requires login, while mutating requests retain CSRF.

## Final verification
- Branch: feat/always-on-agents; unchanged base HEAD: feeb3cc1299523e369d865efe4ae9b56597732f8.
- Helper did not commit, push, switch branches, edit main checkout or restart services.
- Python executable: /home/kesha/orchestra/.venv/bin/python
- Imported app: /home/kesha/orchestra-worktrees/always-on-agents/app/__init__.py
- Environment: PYTHONPATH=/home/kesha/orchestra-worktrees/always-on-agents ORCHESTRA_ALLOW_CLAUDE_ALL=1
- Final result: 482 passed, 0 failures, 0 skipped.
- scripts/check_pipeline_manifest.py --check: green; scripts/check_instruction_contract.py: green.
- git diff --check: green. Existing frozen tests unchanged.
- Exact changed/added files: [changed-files.txt](changed-files.txt).
- Machine-readable result/counts: [verification.json](verification.json).
- Full final output: tests-final.log; structured result: junit.xml (task directory).
- Main checkout and production DB were not used for tests; all test state is isolated.

### Per-suite counts
- tests.test_always_on_agents: 75
- tests.test_codex_orchestrator_turn_end_hold: 32
- tests.test_context_optimizations_v1104: 34
- tests.test_default_pipeline: 6
- tests.test_default_pipeline.TestDefaultBuildSystemPrompt: 5
- tests.test_default_pipeline.TestDefaultManifestLoads: 7
- tests.test_default_pipeline.TestDefaultModulesInline: 5
- tests.test_default_pipeline.TestDefaultRolesResolve: 18
- tests.test_default_pipeline.TestDefaultValidateSpawn: 8
- tests.test_default_pipeline.TestPremortemReachesWorkingRolesOnly: 3
- tests.test_default_pipeline.TestSubOrchestratorGetsKnowledgeModule: 1
- tests.test_default_pipeline.TestTelegramFormattingOwnership: 2
- tests.test_default_pipeline.TestUpstreamCharacterization: 5
- tests.test_default_pipeline.TestUserAnswerFormatOwnership: 2
- tests.test_delivery_head_of_line_block: 7
- tests.test_mcp_stdio: 141
- tests.test_message_delivery_receipts_380: 30
- tests.test_prompting: 6
- tests.test_prompting.TestBuildCodexSkillsIndex: 9
- tests.test_prompting.TestBuildSkillsIndex: 10
- tests.test_prompting.TestCodexProjectDocPreflight: 3
- tests.test_prompting.TestCodexProjectSkills: 9
- tests.test_prompting.TestHtmlArtifactsSkillInvariants: 3
- tests.test_prompting.TestRefreshWorkerMemory: 6
- tests.test_prompting.TestRoleIcons: 3
- tests.test_prompting.TestRolePromptModules: 6
- tests.test_tool_scoping: 13
- tests.test_v1160_steer_recovery: 26
- tests.test_v966_stuck_deliveries: 7

## Five primitives delivered
1. Native timers: follow_up or interval/5-field-cron schedules, ZoneInfo/DST,
   inbound auto-cancel, idempotency and atomic mailbox fire. Missed slots collapse
   into one wake. REST timers endpoints and set/list/cancel MCP tools.
2. Event inbox: optional enqueue idempotency preserving legacy int return,
   enqueue_event metadata, structured batches and single-flight wakes. Durable
   timer/approval/external events are retried after restart. Waiting receipt copies
   are rebuilt; an explicit queued tail clears the Stop hold and continues delivery.
3. Outbox: dashboard logs/broker, existing Telegram bridge and HTTPS webhook
   transport; ledger by key or normalized-content SHA-256, target pacing, quiet
   windows and urgent bypass, bounded retries and leased crash recovery. HTTPS
   pins a public DNS result, disables env proxies/redirects, carries a stable
   idempotency key, and never stores raw transport error URLs.
4. Deferred approvals: idempotent pending cards, owner-only resolution, atomic
   state + contextual mailbox event, cancellation and expiry. No tool action is
   executed by card resolution; the resumed agent receives the decision.
5. Dreaming: no provider/LLM imports, idle-only passes, full raw archives, bounded
   live memory with section headings/recent bullets/active task pointers; bounded
   rolling archived-session digests and source-hash run records.

## Compatibility and remaining boundaries
- New inbox packets use event-inbox wrapping. Existing native Codex steer-recovery
  and turn-end-hold packets preserve exact transcript formatting; mixed batches
  with new timer/approval/inbox_event input use structured formatting.
- Clean-handoff=False is omitted from change_worker_model's existing payload;
  clean_handoff=True still travels explicitly. This repairs a pre-existing
  assertion in the requested suite without weakening tests.
- Approval notifications through Outbox are optional and not enabled automatically;
  cards can be inspected/resolved through REST.
- Telegram outbox target is the registered scope/topic; dashboard target is the
  session name within scope. Only HTTPS public webhook targets are supported.
- Delivery can repeat after an external acceptance followed by a process crash;
  ledger deduplication covers confirmed sends, not an unknowable remote outcome.
- Live deployment, paid/provider probes, real Telegram/webhook sends and the full
  repository test runner were not run. Parent must review/commit/merge and activate.
