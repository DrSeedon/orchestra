# #430 T2 blocker — Luna positive control stopped at call 1/9

The mandatory positive-control gate failed on its first `append` step. Calibration and main were not started (`0` matching artifacts for each).

## Measured outcome

- background job exit: `1`;
- calls attempted: `1/9`;
- controller bucket: `process_error`;
- model outcome: `not_graded`;
- tool calls: `0`;
- resumed session: `false`;
- production DB trace: `write_syscalls=0`, `read_syscalls=0` for `orchestra.db`, `-wal`, `-shm`;
- T2 acceptance remains red: exit `1` (`phase3-t2-after-run.txt`).

The native Codex JSONL gives the real cause before any model output:

```text
invalid_request_error / invalid_json_schema / status 400
Invalid schema for response_format 'codex_output_schema':
In context=('properties', 'state_patch'), 'additionalProperties' is required to be supplied and to be false.
```

The stderr line about models-manager refresh timeout is secondary; the JSONL contains the provider/API rejection and `turn.failed`.

## Why this is not a provider/model result

The call reached schema validation but no model response. It belongs to benchmark/request configuration, not provider availability and not model error. The runner's coarse `process_error` bucket preserved separation but should gain an explicit `request_schema_error` classifier before any future run.

## Required decision

Adding `additionalProperties:false` to an otherwise open `state_patch` object makes it unable to carry state. A usable strict schema needs a fixed patch representation (for example, a strict `operations` array) plus controller normalization to the already frozen internal merge patch. That changes the model-visible protocol and therefore requires a re-closed spec/oracle before the positive control can be run again.

No retry, calibration, main, free-route substitution, or Sol call was made.

## Authorized resolution

The orchestrator clarified that Appendix A.4 uses ordinary text with a fenced JSON block, not provider Structured Outputs. Strict-schema v1 is excluded permanently. Revision `6dd0691a` freezes the exact text protocol and separate `malformed_output` bucket; one replacement 9-call gate is authorized, with no automatic second revision.
