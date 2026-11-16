# Antigravity: isolated persistent ACP prototype

Status: mock-only, not activated in production. Provider enablement, real profiles,
account data and no-credit settings were not changed. No real `agy` execution is
part of verification. Consumer-plan deployment is unresolved: current [Google FAQ](https://antigravity.google/docs/faq)
says third-party application wrappers are unsupported under consumer plans, and
[additional terms, section 6](https://antigravity.google/terms) restrict third-party
access. Official [ACP editor support](https://antigravity.google/docs/ide/extensions/acp/)
does not establish permission for an Orchestra server relay. Offline success cannot
predict account eligibility, internal CLI requests or suspension risk.

## Runtime ownership

`app/antigravity_acp.py` owns one persistent stdio JSON-RPC process for each resolved
canonical profile HOME. All backend instances share that owner and one turn lock.
A lifetime nonblocking flock refuses another application process using that profile;
it does not silently start a second daemon. Individual backend disconnect does not
close the shared process. Application shutdown closes all profiles and their exact
owned process groups.

`connect()` only registers the profile. An explicit user prompt starts the process,
initializes ACP v1 as **Orchestra**, optionally authenticates once with the advertised
personal OAuth method, creates/resumes an independent session, selects the requested
advertised model, then submits one prompt. ACP configOptions are preferred; the
legacy models/session-set-model surface remains supported. No unadvertised model,
paid API, auth method or provider fallback is selected. Unsupported resume fails
without creating a new conversation. This shared multi-session process is our design;
T3's installed source demonstrates a persistent process per session runtime, not a
proven account-wide singleton.

Role instructions travel as first-turn content because ACP v1 does not guarantee a
system-instruction setter. They are not written to a shared profile agent file.
MCP stdio servers and environment values travel in the session setup request. Client
filesystem/terminal capabilities are not advertised, and ACP permission requests are
cancelled. Current implementation supports stdio MCP configuration only. Delta chunks stream live;
one assembled final text is persisted. Tool progress/results retain names, IDs and
actual content; only terminal completed/failed updates become tool results.

## Passive observation and credentials

Readiness, usage API polls, forced refresh and background usage collection never run
version/models/quota commands and never call the network-capable egress verifier.
Live quota stays unknown unless there is a separately obtained observation. Reading
an existing observation never updates its timestamp. Model availability is cached
only from ACP session metadata returned during an explicit turn. Local conversation
SQLite history is historical use, not remaining live quota.

Each canonical profile uses `--gemini-dir <HOME>/.gemini --app-data-dir antigravity-acp`.
Python only checks credential-file presence in that ACP directory; it does not read,
deserialize, copy, refresh or harvest OAuth tokens. Before starting, the profile must
already have explicit `useG1Credits: false` in its ACP settings and `useAiCredits:
false` in common user settings. The adapter refuses missing/permissive settings and
never rewrites them. No automatic migration from legacy per-session HOMEs exists.
The old `scripts/antigravity-login.sh` validation flow is not compatible with the
retired active probe API; it is not an activation procedure for this backend.
No login/account remediation was attempted or authorized here. The retired utility
now refuses before launching a CLI or creating an authentication directory.
Runtime BROWSER is a no-op and canonical file storage is explicit.

## Dispatch and failure boundaries

Only server-authored user provenance may submit consumer ACP input. Agent messages,
cron/timer events, dreaming, retry/auto-continuation and unattributed internal backend
sends are rejected at execution boundaries. Native timer events remain durable and do
not load/wake an Antigravity recipient. Other provider and worker admission policies
are unchanged. Current dreaming code is deterministic local memory curation and has
no model dispatch.

Transport/auth RPC errors, invalid/oversized streams, daemon death and deadlines latch the profile
closed. Already submitted prompts are never replayed and the daemon is never
implicitly restarted. Session-local absent-model/unsupported-resume refusals leave
healthy siblings alive. Definite account/ToS bans persist through the existing provider
circuit-breaker with a fixed safe reason. Operator-only manual compact carries
authenticated user provenance through its summary/ack and uses one attempt.
Cancellation sends session/cancel, holds the profile lock until
the prompt settles, and closes the profile if acknowledgement does not arrive within
two seconds. Cancelling a queued turn never cancels another session. Raw RPC error
bodies and stderr are not published. Missing token/cost telemetry remains unaccounted;
context usage is accepted only from ACP usage_update semantics. USD cumulative cost
is converted to per-turn deltas with a session-owned baseline, including failed turns.
A resumed session with no known baseline first establishes one without charging its
historical total again. Credits are never converted to USD. Standard ACP context
counts do not supply billed input/output/cache totals; these stay explicitly unknown.

## Reproduce offline checks

On the isolated remote worktree, using the existing repository virtual environment:

```sh
scripts/run_antigravity_offline.sh tests/test_antigravity_acp.py tests/test_antigravity_acp_review.py tests/test_always_on_agents.py tests/test_runtime_registry.py tests/test_usage_contract.py -q
scripts/run_antigravity_offline.sh --instructions
```

The wrapper needs passwordless sudo for an ephemeral network namespace. It leaves
production networking untouched, enables loopback only, drops back to kesha with an
empty environment, and runs nice=10. Python audit guards additionally reject external
DNS/connections, any executable except the exact fake peer, production checkout/data
and private-home access, including native sqlite3.connect URI/path checks. The fake
is controlled code, not a filesystem sandbox, and does not inherit Python audit hooks.
The interpreter's existing `.venv` is read-only input.
Failure to establish isolation aborts verification; there is no live fallback.

The mock HTTP stand runs on 127.0.0.1:18889 inside that namespace, uses independent
SQLite, actual Orchestra POST send, AgentSession event handling, usage/chat SSE routers and
the real backend adapter, with synthetic operator authorization. It
replaces the production lifespan with a short-lived test lifespan; Telegram, cron,
bootstrap and automatic recovery are not started. The stand is stopped after testing.
It is not an assertion that the full production bootstrap was exercised.

Evidence, including red legacy acceptance results, is under
`.orchestra/tasks/agy-acp-safe-20261116/`. Existing frozen tests were not weakened or
rewritten; legacy NDJSON/token-copy expectations still require a reviewed migration
before merge readiness.

## Interface alternatives

- [Direct ACP](https://antigravity.google/docs/cli/acp/) exposes official CLI sessions,
  streamed updates, model metadata and cancellation. It fits the technical adapter;
  protocol support does not resolve consumer-plan authorization.
- [Continuous stream-json CLI](https://antigravity.google/docs/cli/headless) is a
  technical multi-turn alternative. It was not implemented alongside ACP.
- [Official Antigravity Python SDK](https://antigravity.google/docs/sdk/overview)
  manages agent state/tools with a compiled runtime. Documented API-key, Enterprise
  ADC and local-model auth do not establish a personal Pro OAuth replacement. Calling
  it merely a wrapper around the installed agy CLI is inaccurate.
- [Google GenAI SDK](https://ai.google.dev/gemini-api/docs/libraries) targets programmatic
  Gemini/Vertex APIs with separate auth, quotas and billing. It is not an authorized
  automatic fallback. No API route, key, subscription or billing change was added.
