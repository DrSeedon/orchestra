## Summary

Exact line read: “The four cases below are independent compact historical patch excerpts.”

## Case K2

- blocking: none.
- suggestion: Run admission before `manager.create_session` to avoid leaving an uninitialized session when unknown telemetry is rejected.
- verdict: `PASS`

## Case M7

- blocking: none.
- suggestion: none.
- verdict: `PASS`

## Case Q4

- blocking: Important messages are dropped after three failed attempts (`return None`). Persistent `RetryAfter`, network, or server failures can therefore lose messages despite the contract requiring delivery.
- suggestion: none.
- verdict: `BLOCK`

## Case T9

- blocking: none.
- suggestion: none.
- verdict: `PASS`

## Verdict

`BLOCK` — Case Q4 violates the important-message delivery contract.