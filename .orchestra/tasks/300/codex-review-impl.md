## Summary

The implementation is minimal and the default change itself is sound, but the committed evidence and RED oracle are not robust enough to approve the shared-runtime change.

Test attempted:

```text
env -u RAG_ONNX_THREADS /home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rag.py -q
```

Result:

```text
17 errors, 32 skipped in 2.52s
ModuleNotFoundError: No module named 'aiohttp'
```

No files were edited.

## Findings

suggestion: `docs/tasks/300/artifacts/benchmark-before.txt:1`, `benchmark-after.txt:1`, `search-quality.txt:1` — the recorded commands contain placeholders such as `<warm-model bounded benchmark>` and `<temporary vec.db index/search check>`. Therefore the benchmark methodology, warm-up boundary, heartbeat implementation, and search corpus cannot be reproduced or audited. Commit the exact executable command/script and raw output before relying on these measurements.

suggestion: `tests/test_rag.py:19-21` — the test asserts the imported configuration value, not the default. It fails whenever the supported explicit override sets `RAG_ONNX_THREADS` to anything other than `1`, making the suite dependent on the operator environment. Test the default in a subprocess with `RAG_ONNX_THREADS` removed, and separately verify that an explicit override remains supported.

suggestion: `docs/tasks/300/report.md:49-50` — the report claims focused tests cover rollback, scheduler coalescing, and request-return-before-backfill, but provides no exact test command or output for those contracts. The documented server interpreter currently cannot run even the new oracle because test setup imports missing `aiohttp`. Record a successful command/output from an environment containing both the application and RAG dependencies.

## Verdict

NEEDS WORK — no blocking crash, corruption, or security issue found in the one-line production change, but shared-runtime approval requires reproducible measurements and a meaningful environment-independent oracle.

## Round (2026-08-16T18:37:31Z)

## Round 2

## Summary

All three prior suggestions are fixed. The new oracle is environment-independent, override behavior is tested, and the benchmark is executable and reproducible.

However, two new evidence issues prevent approval.

## Findings

- FIXED — benchmark and quality commands are now executable via `docs/tasks/300/measure_benchmark.py`.
- FIXED — default and explicit override are tested separately in subprocesses.
- FIXED — the report records exact focused test commands and outputs.

suggestion: `docs/tasks/300/report.md:35-38` labels CPU as “CPU peak,” but `measure_benchmark.py:48-55` computes aggregate CPU time divided by elapsed wall time. There is no CPU sampling from which a peak could be derived. Rename it to average CPU or implement sampling.

suggestion: `docs/tasks/300/report.md:52-60` claims `50 passed` and `66 passed`, but both full-suite reruns in this review terminated before their summaries, around 28–29 RAG tests. The focused oracle does pass:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_rag.py -k 'background_onnx'
2 passed, 48 deselected in 14.61s
TEST_RC=0
```

Re-run and capture the complete full-suite result under bounded resource conditions, or document the current termination honestly.

## Verdict

NEEDS WORK — the production default and oracle look correct, but the report still overstates one metric and its full-suite verification could not be reproduced.

## Round (2026-08-16T18:43:50Z)

## Round 3

## Summary

Both Round 2 suggestions are FIXED. CPU is correctly labeled as an aggregate average, and the complete real RAG plus scheduler suite passes without skips.

## Findings

- FIXED — `cpu_avg_pct` and “CPU average” now match the benchmark calculation.
- FIXED — full server-interpreter verification completed successfully.
- No new findings.

Reviewed-diff quote: `parser.error("choose exactly one of --benchmark or --quality")`

Test command and output:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_rag_service.py tests/test_rag.py
66 passed in 56.08s
```

## Verdict

APPROVED.
