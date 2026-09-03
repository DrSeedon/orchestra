# #102 — Concurrent local Bot API probe

## Protocol fixed before measurement

Context from #99: the old startup sync launched about 30 concurrent
`editForumTopic` calls. Seventeen calls timed out at `+4.989…+4.992s` and one more
at `+9.991s` under the five-second outer timeout. This directly proves that
concurrency around 30 mutations is unsafe through the deployed local Bot API/proxy.

The #102 delivery architecture can have at most the primary text dispatcher and
isolated image dispatcher awaiting Bot API work concurrently for one chat. The
bounded probe therefore starts three small `sendMessage` requests simultaneously,
alternating two existing topics in the same group:

- record start offsets, completion duration, HTTP result, and `retry_after`;
- pass only if all three return HTTP 200 in under five seconds;
- bulk-delete every accepted probe message;
- do not ramp above three: #99 already measured the unsafe high-concurrency side,
  and intentionally reproducing 30 mutating calls would risk another channel stall.

This can validate low concurrency for small sends. It cannot prove that three
simultaneous uploads are safe, so the implementation must retain one image worker
per chat and stagger request starts through the shared rate authority.

## Result

All three requests started within `6.3ms`:

| # | Topic slot | Start offset | Duration | Result |
|---|---:|---:|---:|---|
| 1 | 1 | 0.0585s | 0.2961s | HTTP 200 |
| 2 | 2 | 0.0644s | 0.5403s | HTTP 200 |
| 3 | 1 | 0.0648s | 0.3099s | HTTP 200 |

Wall duration including bulk cleanup was `0.9244s`; `deleteMessages` removed all
three probes with HTTP 200.

**Outcome:** concurrency 3 is confirmed for small `sendMessage` requests on the
deployed path. Concurrency around 30 mutating topic edits is refuted by #99. Media
concurrency above the existing single image worker remains unmeasured and must not be
introduced.
