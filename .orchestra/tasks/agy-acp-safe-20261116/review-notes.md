# Permanent CTO review — 2026-11-16

Scope: isolated branch only, no production changes or live provider/account access.
Original implementer finished; no concurrent source writer. Parent owns independent
Astra review. This file records concrete findings and changes during acceptance.

- Fixed real gap: AgentSession.compact now accepts explicit provenance for consumer
  ACP; automatic/unattributed compaction returns before reservation/network. Only an
  authenticated operator cookie can authorize the HTTP compact route for this runtime.
  The two summary/ack sends carry that authorization. Consumer compact uses one attempt,
  never the generic three-attempt retry loop; errors retain the old session identity.
- Added visible is_error on failed ACP tool updates; a later end_turn still controls
  success, so recovered tool failures remain visible without poisoning a good turn.
- Refuse a duplicate session/new ID instead of silently sharing another conversation.
- Runtime environment fixes BROWSER=/usr/bin/true, GEMINI_HOME=canonical .gemini and
  AGY_ACP_FORCE_FILE_STORAGE=1. No copying/settings rewrite or login attempt added.
- New test collection R1 failed because import path omitted tests package. Corrected
  that fixture import once; R2 7 passed, expanded semantic coverage 36 passed.
- Frozen test files are unchanged. Pure SQLite/protobuf assertions are reused directly
  from the legacy module with a synthetic profile fixture, including WAL/read-only URI,
  invalid paths, boundary values and latest corrupt/oversize metadata. No old assertion
  was weakened and missing billed-token semantics remain unknown.
- t3-bg --info returned HTTP401 in this harness; no provider configuration changed.
  All child processes are awaited in the active turn; no unobserved background work.

- Strengthened HTTP smoke to exercise the actual operator send route and full
  AgentSession event handler/SSE, with synthetic cookie verification. No custom
  /stand/prompt endpoint remains. Two fixture-only fixes: ensure-backend must assign
  s._backend, and real chat SSE emits text/status rather than raw backend turn_end.
  Final focused smoke PASS; rejected anonymous send now gets HTTP403 before dispatch.
- Tool text content/rawInput/rawOutput are preserved with existing redaction; failed
  results have is_error=True. New failure test asserts actual content and raw output.
- Latest unchanged legacy suite: 15 failed, 18 passed, 79 errors (5.28s); this remains
  RED. The extra changed expectation is implicit manual compact authorization, which
  now deliberately requires authenticated operator provenance. No old tests edited.

## Independent Astra R1 findings and final response
- R1 baseline was implementation.diff SHA256 44d6eb19bd1a428884583bd3b5682386e0dfdd5e13ce17d21c128c94b4b7d392.
- P1 immediate cancel: fixed callback + explicit interrupt settlement, zero-sleep test.
- P1 durable ban: structured payload classified before redaction; fixed safe incident
  persisted via existing circuit-breaker, only synthetic storage in tests.
- P2 chunk history: stream deltas + one assembled final; actual AgentSession handler test.
- P2 tools: actual text/raw output, remembered name/ID, is_error and nonterminal progress.
- P2 local refusal: AcpSessionError does not close healthy shared profile; sibling tested.
- HTTP acceptance: real POST send, actual AgentSession event loop and GET SSE/usage.
- Audit: sqlite3.connect URI/path/PathLike denied before production open; child-hook
  inheritance is not claimed. Kernel network isolation covers the controlled fake.
- Legacy login: refused before subprocess/account-file side effects. Permission and
  config metadata update cases and cancellation-time cost now tested.
- Adjacent compact/mailbox bundle hit its 60s bound with no completed result; no retry
  loop or test weakening. Final process inspection found no runner/fake survivors.
