# T2 — runtime quota telemetry before/after and mutations

## Behavioral before

Current Codex turn with Claude cache `5h=88%, 7d=100%` and Codex cache
`primary=33%, secondary=44%` produced:

```text
turn ended (...) | 5h:88% 7d:100%
```

The behavioral test expected `Codex 5h:33% Codex 7d:44%` and failed:
`1 failed in 5.15s`.

## Behavioral after

Targeted DB/log/runtime subset: `13 passed in 6.14s`. Runtime formatting is:

```text
Claude → | Claude 5h:88% Claude 7d:100%
Sol    → | Codex 5h:33% Codex 7d:44%
Spark  → | Spark 5h:9% Spark 7d:10%
```

Stale Claude/Sol/Spark caches return no suffix. The turn-end integration test
asserts one `_cached_quota_snapshot("codex", "gpt-5.6-sol")` call feeds both
DB `quota_primary_pct=33` and visible `Codex 5h:33%`.

Async turn-end nodes repeated:

```text
2 passed in 5.12s
2 passed in 4.65s
2 passed in 4.63s
```

## Independent mutations

| ID | Mutation | Behavioral red evidence |
|---|---|---|
| M1 | Codex selector reads Claude `_usage_cache` | runtime formatter: `1 failed in 4.38s` |
| M2 | Spark skips nested `spark` bucket | runtime formatter: `1 failed in 4.36s` |
| M3 | TTL stale rejection removed | stale matrix: `3 failed in 4.77s` |

Each file was restored in the same command; marker count after restore was `1`.
The change only selects/prints cached telemetry and does not call or modify
admission/readiness.
