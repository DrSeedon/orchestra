# OpenCode consumer inventory

Date: 2026-07-28 (Asia/Krasnoyarsk)

This inventory was taken before changing model routing. All databases were
opened read-only. Host addresses, bearer values, API keys, and other
credentials are intentionally omitted.

## Scope and decision rule

The inspected deployment set is:

1. the active local Orchestra service;
2. the only remote Orchestra deployment named in the infrastructure registry,
   `SeedonRuInfra / orchestra-test`;
3. repository deployment manifests and runtime-plugin configuration;
4. the live model-proxy response used by the remote deployment.

An OpenCode consumer means at least one of:

- a persisted session or usage row with runtime `opencode`;
- a running `opencode serve` process;
- a currently advertised model explicitly mapped to `opencode`;
- an enabled runtime plugin or deployment configuration that selects
  OpenCode.

## Local deployment

### Process and configuration

Sanitized process-environment probe:

```text
ORCHESTRA_RUNTIME_PLUGINS=(unset)
ANTHROPIC_BASE_URL=(unset)
UPSTREAM_API=(unset)
```

The active service is `orchestra.service`. No Docker container with
`orchestra` or `opencode` in its name/image was running. `opencode` 1.17.6 is
installed, but `pgrep -af 'opencode serve'` returned only the probe command
itself: there was no OpenCode daemon.

### Live model registry

Raw sanitized `GET http://127.0.0.1:8888/api/models` projection:

```json
{
  "count": 12,
  "models": [
    {"id":"claude-fable-5[1m]","runtime":"claude","provider":"anthropic"},
    {"id":"claude-opus-5[1m]","runtime":"claude","provider":"anthropic"},
    {"id":"claude-sonnet-5[1m]","runtime":"claude","provider":"anthropic"},
    {"id":"claude-haiku-4-5","runtime":"claude","provider":"anthropic"},
    {"id":"gpt-5.3-codex-spark","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.6-sol","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.6-terra","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.6-luna","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.5","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.4","runtime":"codex","provider":"openai"},
    {"id":"gpt-5.4-mini","runtime":"codex","provider":"openai"},
    {"id":"grok-4.5","runtime":"grok","provider":"x-ai"}
  ]
}
```

There is no local advertised OpenCode model.

### Live SQLite

Aggregate read-only query:

```sql
SELECT COUNT(*) total,
       SUM(finished_at IS NULL) unfinished,
       SUM(finished_at IS NOT NULL) finished,
       SUM(backend_type='opencode') opencode
FROM sessions;

SELECT COUNT(*) total,
       SUM(runtime='opencode') opencode
FROM turn_usage;
```

Raw result:

```text
sessions:   total=339  unfinished=91  finished=248  opencode=0
turn_usage: total=799  opencode=0
logs joined to sessions.backend_type='opencode': 0
```

The distinct persisted session models are current Claude/Codex/Grok models
plus the legacy exact id `claude-sonnet-4-6`. That legacy row is unfinished
and idle, so removal of prefix inference must retain an explicit compatibility
route to the Claude runtime.

## Registered remote deployment: `SeedonRuInfra / orchestra-test`

### Running implementation

The registered host runs `orchestra-test.service` from
`/home/orchestra-test/orchestra` on loopback port 18001. It is a deployed copy,
not a Git checkout. Its model router is the enterprise harness generation:

```python
def _infer_backend(model_id: str) -> str:
    return "harness"
```

The host has no `opencode` executable, no `opencode serve` process, no
OpenCode-named container, and no configured runtime plugin:

```text
ORCHESTRA_RUNTIME_PLUGINS=(unset)
ANTHROPIC_BASE_URL=configured
UPSTREAM_API=(unset)
```

Its read-only SQLite has no `turn_usage` table and contains two unfinished idle
sessions:

```text
model                              backend_type  lifecycle   status  count
claude-sonnet-4-6                  harness       unfinished  idle    1
deepseek/deepseek-v4-flash         harness       unfinished  idle    1
```

Therefore the live remote DeepSeek consumer uses `harness`, not OpenCode.

### Live proxy response

The remote service is proxy-connected. A credential-preserving probe reused
the running process environment but emitted only model metadata. Raw sanitized
`/v1/models` response:

```json
[
  {
    "context_length": 1048576,
    "id": "deepseek/deepseek-v4-flash",
    "pricing": {
      "completion": "0.000000196000",
      "prompt": "0.000000098000"
    }
  },
  {
    "context_length": 1048576,
    "id": "deepseek/deepseek-v4-pro",
    "pricing": {
      "completion": "0.000000870000",
      "prompt": "0.000000435000"
    }
  }
]
```

The response contains neither `runtime`/`backend` nor `provider`. In the
current public code these two exact IDs would have acquired OpenCode solely
through `_infer_backend()`'s catch-all. They are therefore the two real
inferred routes that must be migrated to an exact reviewed mapping before the
catch-all is removed. No other inferred proxy model was observed.

## Manifests, plugins, and documentation

- `.env` has no runtime-plugin or model-endpoint override.
- `.env.example` contains only a commented
  `ORCHESTRA_RUNTIME_PLUGINS=my_package.orchestra_runtime` example.
- No repository module outside `app/runtime_registry.py` calls
  `register_runtime()`.
- `deploy/orchestra.service.template` and `docker-compose.yml` do not select an
  OpenCode model or plugin.
- The repository documents OpenCode as the prior arbitrary-provider path and
  includes its adapter/tests, but documentation is not evidence of a running
  consumer.
- The separate `orchestra-enterprise` checkout and the registered remote
  deployment currently route all proxy models to their own `harness` runtime.

## Verdict

**CONFIRMED for the inspected deployment set:** OpenCode has no current
session, usage row, daemon, explicitly mapped live model, or configured
runtime plugin.

**CONFIRMED migration requirement:** the registered remote proxy currently
advertises exactly two DeepSeek IDs without routing metadata. In this codebase
they depended on the OpenCode catch-all, so both need exact reviewed
`opencode` mappings. Arbitrary future proxy IDs must fail unless the payload
provides `runtime`/`backend` and `provider`, or code adds another reviewed
exact mapping.

**Not proved globally:** absence of OpenCode consumers in unregistered,
offline, or privately modified deployments. The dynamic loader means a
one-time zero can never prove future absence.

The adapter can be considered unused and eligible for a separate deletion
decision only after an observation period shows all of the following for
every registered deployment:

1. deployment inventory is complete and each deployment reports its model
   registry plus runtime-plugin list;
2. no explicit model has `runtime=opencode`;
3. no session/log/usage row records OpenCode during the period;
4. no proxy refresh is rejected for missing routing metadata.

Instrumenting and retaining those four observations for one full deployment
cycle would turn “no known consumer” into evidence suitable for a deletion
ticket. This task keeps the adapter.
