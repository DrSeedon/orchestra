<code-quality>
## Engineering & runtime environment

- **Cgroup & host limits**: on exit `137` / `SIGKILL`, check process cgroup `memory.max`, `memory.current` and `memory.events` alongside host RAM before blaming code; lower concurrency or footprint rather than altering cgroup/unit limits. Use `acquire_test_lock` / `release_test_lock` when serializing heavy shared-resource suites.
- **Single source of policy**: keep state and validation at the boundary they protect; optional telemetry or metadata failures must not break safe execution paths.
- **Data collection fidelity**: when collecting authorized external records, store complete raw fields first and apply business filtering at query/view time unless source/memory limits require narrowing (state coverage limits explicitly).
- **Contract & prompt tests**: test durable behavior, authorization, recovery and assembly contracts rather than pinning fragile editorial phrasing. Never weaken frozen acceptance tests; report defective frozen assertions with evidence.
</code-quality>
