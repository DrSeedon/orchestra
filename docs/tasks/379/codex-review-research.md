<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

No blockers. The four load-bearing conclusions are supported by the reviewed artifact, named code seams, and the reproducer.

I reran:

```bash
/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python \
  docs/tasks/379/socket_stand.py
```

Observed: queue `350 → 0` with fresh `HTTP/1.1 200 OK`; uvloop inherited only the inheritable listener; leaked holder caused `EADDRINUSE`; rebind succeeded after holder exit; executor shutdown requested at 50 ms waited 504.1 ms.

Exact artifact sentence not present in the request:

> «Queue здесь следствие правильного `FlushPending=no` при неправильной длительности окна без acceptor.»

## Findings

- suggestion: `docs/tasks/379/research.md:114-116` — The executor probe proves that uvloop can keep the loop alive while waiting past the requested shutdown timeout, but it does not connect that wait to the production PID’s actual blocking executor work. The later `LIKELY` label is appropriate; keep “Это объясняет, как” explicitly framed as a viable mechanism, not incident attribution.

- suggestion: `docs/tasks/379/research.md:177-195` — The reproducer establishes FD inheritance, rebind failure, and successful acceptance on a queued listener in separate arms. It does not run a new Uvicorn acceptor while a leaked child simultaneously holds another duplicate of that same listener. The conclusion is consistent with socket semantics and the production 200/302 evidence, but Phase 2’s regression oracle should combine those conditions to make “does not block service-only acceptance” mechanically direct.

- question: `docs/tasks/379/research.md:223-229` — The future constraints preserve the named #230/#237 properties at the architectural level: queue retention, no socket/service recycle for normal restart, all-or-none preparation, admission ordering, same CLI process, and end-effect verification. Before implementation, will the plan also require proving that cleanup of session-owned supervisor tasks cannot close adopted stdin/stdout or mutate the handed-over CLI lifecycle? The risk is recognized at lines 272-276, but it is not yet expressed as a named oracle.

## Verdict

Completed — no blocking causal hole.

The confidence calibration is sound:

- `Recv-Q` as symptom: confirmed by the queue stand and later successful acceptance.
- Old supervisor non-exit as immediate cause: confirmed; the exact waiter correctly remains uncertain.
- uvloop FD inheritance and rebind barrier: confirmed; service-only attribution is adequately refuted, with the combined-oracle improvement noted above.
- Service-only “did nothing”: categorically refuted by PID 1191988 serving 200/302 before the full cycle.

No files were modified.
