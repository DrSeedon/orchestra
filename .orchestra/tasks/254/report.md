# #254 — restore the three red tests in main

## Diagnosis

Both failures in `test_limit_wake.py` were stale test doubles, not production defects.
`TurnManager` is constructed in production only as `TurnManager(self)` by `AgentSession`;
`AgentSession` has required `name` and `scope` dataclass fields and a concrete `_log` method.
The two local `_Session` doubles predated the mailbox seam and omitted that mandatory surface.
They also reached the real `mailbox.claim`, although the tests are about limit wake scheduling.

The Codex native-history canary was slow, not hung. A focused run with its functional budget
returned all three exact semantic markers and passed in 32.35 seconds (34.95 seconds wall time).
The full suite's blanket `--timeout=30` killed it before its explicit phase limits could decide:
180 seconds for connect and 600 seconds for the response.

## Fix

- The limit-wake doubles now declare `name` and `scope`, and `mailbox.claim` is isolated to an
  empty result so those tests exercise only their intended wake path. `_log` is not added as a
  permissive stub: with the mailbox dependency isolated, reaching error logging is itself a test
  failure instead of being hidden.
- The live native-history canary overrides pytest's blanket wall-clock limit with an 840-second
  backstop, longer than its explicit phase limits combined. Disconnect now has its own 30-second
  bound, so teardown cannot hang.
