# #255 retrospective concurrency table

Cutoff: `2026-08-23T13:54:29.852026+00:00`. Concurrency is reconstructed from native rollout `task_started→task_complete` intervals joined to `turn_usage.event_id`, ordered and overlapped by `ts`; it is exact inside the complete-rollout cohort and a lower bound for all attempts. Session/process counts are never substituted for active turns.

| UTC start interval | active Codex turns | observable process snapshot/boundary | model / effort / tier / task class | TTFT median/p90 (n), s | final median/p90, s | tool rounds median | input/output median | host load/CPU/RSS | proxy endpoint + counters | provider error/rate evidence | negative/control traffic | source |
|---|---:|---|---|---:|---:|---:|---:|---|---|---|---|---|
| 2026-07-26T04:54:50.539Z → 2026-08-23T12:53:51.972Z | 1 (n=329, exact 1–1) | not sampled synchronously | {'gpt-5.6-sol': 327, 'gpt-5.3-codex-spark': 1, 'gpt-5.6-luna': 1} / {'xhigh': 244, 'high': 83, 'unobserved': 2} / tier unobserved / roles {'full-cycle': 195, 'worker': 40, 'orchestrator': 94} | 9.273/35.575 (n=329) | 108.517/798.140 | 4 | 1008292/2928 | not sampled synchronously | historical counters unavailable; current manager began 2026-08-23 | 58/329 terminal errors; quota [0.0, 100.0] | output median/p90 2928/22758; tokens/s median 28.296 | `turns.csv`, `bucket-summary.json` |
| 2026-07-26T05:10:56.314Z → 2026-08-23T13:50:14.575Z | 2-4 (n=609, exact 2–4) | #111 task-creation boundary 2026-08-01 06:49 UTC: 62 Codex-related processes / 109 sessions while exact active turns=4 | {'gpt-5.6-sol': 607, 'gpt-5.6-luna': 2} / {'high': 188, 'xhigh': 414, 'unobserved': 7} / tier unobserved / roles {'worker': 117, 'full-cycle': 358, 'orchestrator': 134} | 10.917/39.187 (n=609) | 123.528/1053.817 | 4 | 941680/3009 | #111 task snapshot: RSS 3.4 GiB, swap 10 GiB, load up to 13; no CPU attribution | historical counters unavailable; current manager began 2026-08-23 | 35/609 terminal errors; quota [0.0, 100.0] | output median/p90 3009/26367; tokens/s median 27.904 | `turns.csv`, `bucket-summary.json` |
| 2026-07-26T07:30:08.494Z → 2026-08-23T13:46:19.704Z | 5-9 (n=320, exact 5–9) | #111 second snapshot 2026-08-01 06:56 UTC: 16 native + 16 Node + 17 helpers = 49 processes while exact active turns=8 | {'gpt-5.6-sol': 319, 'gpt-5.6-luna': 1} / {'high': 129, 'xhigh': 190, 'unobserved': 1} / tier unobserved / roles {'worker': 72, 'full-cycle': 202, 'orchestrator': 46} | 10.697/27.802 (n=320) | 164.660/1110.835 | 6.000 | 1172374/4767 | #111: load 3.53/2.75/4.22, RSS 3.324 GiB, swap 11 GiB; no CPU attribution | historical counters unavailable; current manager began 2026-08-23 | 2/320 terminal errors; quota [2.0, 100.0] | output median/p90 4767/30937; tokens/s median 29.516 | `turns.csv`, `bucket-summary.json` |
| 2026-07-28T09:47:14.628Z → 2026-08-01T08:30:44.352Z | 10-19 (n=22, exact 10–12) | not sampled synchronously; first Aug-01 exact active=10 starts 13 min after the 49-process/active=8 snapshot | {'gpt-5.6-sol': 22} / {'high': 12, 'xhigh': 10} / tier unobserved / roles {'worker': 8, 'full-cycle': 12, 'orchestrator': 2} | 11.684/18.372 (n=22) | 415.173/1532.883 | 22.000 | 1949378/13740 | not sampled synchronously | historical counters unavailable; current manager began 2026-08-23 | 0/22 terminal errors; quota [18.0, 56.0] | output median/p90 13740/42178; tokens/s median 32.107 | `turns.csv`, `bucket-summary.json` |
| not observed | 20+ (n=0, exact None–None) | no exact active-turn intervals | — | —/— (n=0) | —/— | — | —/— | not sampled synchronously | historical counters unavailable; current manager began 2026-08-23 | 0/0 terminal errors; quota [None, None] | — | `turns.csv`, `bucket-summary.json` |

## Coverage and boundaries

- Codex usage rows: 1333; exact rollout task_started→task_complete intervals: 1280; usage rows without a complete local rollout interval: 53.
- DB `codex turn=... started` markers are diagnostic only, not interval starts: n=1122, lag vs rollout start median/p90/max=0.006/0.043/13507.561 s. Delayed replay after restart makes DB-marker intervals invalid.
- Rollout scan: 1275 files / 1930818343 bytes; turns with rollout data: 1314; TTFT rows are shown per bucket.
- `tier` is not stored in historical `turn_usage` or `turn_context`; it is marked unobserved. Current managed config is Standard, but that fact is not projected backward.
- Task class is the persisted Orchestra role plus task-id presence; prompt semantics are not reconstructed.

## Current proxy-manager counter snapshot (not historical join evidence)

```json
{
  "active_connections": 22,
  "captured_at": "2026-08-23T14:15:52.572785+00:00",
  "max_connections": 512,
  "process": {
    "load_15m": 21.49,
    "load_1m": 5.39,
    "load_5m": 21.89,
    "pid": 2597651,
    "rss_mib": 24.1
  },
  "proxy_endpoint": "127.0.0.1:12339",
  "rejected_connections": 0,
  "route_accepted": 4206,
  "route_active": 22,
  "route_failed": 0,
  "selected_route": "contabo",
  "semantic": true,
  "semantic_latency_ms": 1780,
  "semantic_status": 401,
  "uptime_seconds": 4944
}
```

The manager counters reset on process restart and have no time series; they cannot be joined to July/August turns.

## Retained Orchestra journal boundary

```json
{
  "first_ts": "2026-08-23T11:14:41.683373+00:00",
  "journal_lines": 198793,
  "journal_rc": 0,
  "last_ts": "2026-08-23T13:54:21.487818+00:00",
  "usage_fetch_failure_active_distribution": {
    "0": 21,
    "1": 1,
    "2": 6,
    "3": 1
  },
  "usage_fetch_failure_bursts": [
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T11:15:11+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T11:15:27+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T11:15:28+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 1,
      "ts": "2026-08-23T11:15:38+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:18:46+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:18:47+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:18:49+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:18:50+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:18:52+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:19:52+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:21:52+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:21:59+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:04+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:10+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:11+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:12+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:13+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:22:29+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:23:52+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T11:23:53+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T12:51:30+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T12:51:32+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T12:51:33+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T12:51:34+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 0,
      "ts": "2026-08-23T12:51:35+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T12:53:58+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T12:54:00+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 2,
      "ts": "2026-08-23T12:54:05+00:00"
    },
    {
      "distinct_failures": 1,
      "exact_active_turns": 3,
      "ts": "2026-08-23T12:54:15+00:00"
    }
  ],
  "usage_fetch_failure_seconds": 29
}
```
