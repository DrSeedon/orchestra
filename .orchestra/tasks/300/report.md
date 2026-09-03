# #300 — bounded RAG backfill CPU

## RED oracle

`tests/test_rag.py::test_background_onnx_default_is_single_thread` was added before the
production edit and failed on the current code:

```text
E       assert 2 == 1
E        +  where 2 = rag.RAG_ONNX_THREADS
1 failed in 4.49s
```

The failure reproduces the live finding: the shared ONNX session was allowed two intra-op
CPU lanes inside the Uvicorn process. The existing scheduler already keeps this work out of
the request coroutine: `schedule_backfill()` creates a task, and `rag.run()` sends indexing to
the single-worker write executor. The same path already provides per-scope deduplication,
slice deadlines, progress/failure logs, and transactional rollback in `index_file`/`index_log`.

## Change

The safe default for `RAG_ONNX_THREADS` is now `1` instead of `2`; an operator can still raise
it explicitly after measuring the latency budget. `.env.example` documents the one-lane default.
Write concurrency remains bounded at `ThreadPoolExecutor(max_workers=1)`, while search keeps its
separate read executor. No request route was made to await indexing.

## Bounded warm-model measurement

The exact executable probe is `docs/tasks/300/measure_benchmark.py`; it loads the model before
timing, runs embedding in an executor while a 10-ms asyncio heartbeat samples loop delay, and
records CPU from `/proc/self/stat` plus `getloadavg()[0]`. Commands and raw stdout are kept in
`docs/tasks/300/artifacts/benchmark-{before,after}.txt`. Both runs returned one 1024-dimensional
vector (`RC=0`). Host load was not idle, so these are comparative rather than absolute host
capacity numbers.

| setting | elapsed | CPU average | load peak (1m) | heartbeat max | completed |
|---|---:|---:|---:|---:|---:|
| `RAG_ONNX_THREADS=2` (before) | 0.123 s | 203.8% | 5.10 | 2.05 ms | 1/1 |
| `RAG_ONNX_THREADS=1` (after) | 0.169 s | 94.9% | 5.01 | 6.25 ms | 1/1 |

The expected trade-off is explicit: CPU contention roughly halves, while this tiny workload
takes longer. The post-change quality/completion command is the same script with `--quality`; raw
stdout is in `docs/tasks/300/artifacts/search-quality.txt`. It indexed two documents and searched
for one sentinel; it returned `alpha.md` (the expected document), with `indexed_chunks=2` and
`search_completed=True`.

## Verification after dependency recovery

The server interpreter was restored with the application's runtime and RAG dependencies before
the post-review run. CPU is an aggregate process average over the bounded embedding interval;
the load and heartbeat columns are maxima of their samples. The real RAG layer passed, rather
than being silently skipped:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_rag.py
50 passed in 56.11s

/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_rag_service.py tests/test_rag.py
66 passed in 60.27s (0:01:00)
```

## Failure/rollback and delivery

No new failure path was needed: `_run_scheduled_backfill()` logs start/end/failure and removes
failed tasks so they can be rescheduled; `index_file` and `index_log` use one transaction and
rollback on exceptions. Existing focused tests cover these contracts, including scheduler
coalescing and request-return-before-backfill.

No deploy or restart was performed.

## Review gate

Targeted Sol review of the committed diff returned `APPROVED` in Round 3. Round 2's requests
for executable benchmark evidence, an environment-independent default oracle, and exact test
output were fixed and rechecked. The final review command was:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_rag_service.py tests/test_rag.py
66 passed in 56.08s
```
