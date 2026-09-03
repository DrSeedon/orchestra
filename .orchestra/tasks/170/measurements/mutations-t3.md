# T3 — managed Codex isolation before/after and mutations

## Behavioral before

The worker (`is_orchestrator=False`) fake app-server command lacked
`features.multi_agent=false`; the behavioral assertion failed:
`1 failed in 4.46s`.

## Behavioral after

Every Orchestra-created `CodexBackend` command includes native
`features.multi_agent=false`. Independently, the Orchestra MCP config retains
`spawn_worker`, and the default full-cycle role retains `can_spawn=["*"]`.

Repeated worker connect + MCP capability tests:

```text
2 passed in 4.15s
2 passed in 3.97s
2 passed in 4.04s
```

The manifest delegation assertion separately passed (`1 passed, 46
deselected in 3.98s`).

## Independent mutations

| ID | Mutation | Behavioral red evidence |
|---|---|---|
| M1 | restore `if self._is_orchestrator` around native disable | worker connect: `1 failed in 4.29s` |
| M2 | remove `spawn_worker` from Orchestra enabled tools | MCP capability: `1 failed in 3.92s` |

Both mutations were restored in-command with a post-restore marker count of
`1`. Native isolation and supported Orchestra delegation therefore have
independent evidence.
