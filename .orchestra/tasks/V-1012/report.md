# V-1012 — MultiCode hub account selection

**Scope:** read-only investigation of the installed T3 bundle, its exposed MCP/HTTP surfaces, and public documentation. No provider calls or threads were launched. Source references below are original embedded sources from `/usr/lib/node_modules/t3/dist/binCli-jI3XdqnK.mjs.map`. A search of all 1,730 embedded source files for account-pool, active/in-use, readable, refill, rotation, lease, failover, quota-window, and related selection terms found the usage adapters described below but no request-routing selector. Process inspection identified `<hub-auth-dir>/<hub-auth-service>` and its DLL/PDB, but no source project; filtering strings from the app DLL surfaced `active_id`, which does not reveal its selection logic. The routing configuration/implementation behind the relay was therefore not available as readable source, so behavior not established by those sources is marked unknown.

## What the installed T3 code establishes

The installed bundle is a T3 Code server. Its source map contains 1,730 embedded source files. In `../../../packages/contracts/src/providerUsageLimits.ts:84–87`, the contract explicitly defines a usage-source account as one “the account itself is not something this environment can run turns on.” The `../src/usage/UsageLimitSources.ts:1–6` module describes the feature as reading quota from places where the environment cannot run turns, including a CLIProxyAPI hub. T3's public [Usage and Subscription Limits documentation](https://github.com/pingdotgg/t3code/blob/main/docs/user/usage.md#connect-a-cliproxyapi-hub) says the hub connection supplies usage information and that the provider must be configured separately to route agent requests.

For the Claude Hub relay, the embedded source `../src/usage/hubRelay.ts:56–64` accepts, per provider, an `active_id` and an `ids` account list. The mapper at lines 175–192 marks an account active using only this equality:

```ts
active: report.active_id === account.id,
```

The installed T3 code therefore **displays the relay's active marker; it does not choose the credential**. The endpoint it polls is a read-only `GET` to `/relay/limits` (`hubRelay.ts:202–211`). It receives per-account quota windows and an `active_id`; no scheduling rule, provider-call failover code, or account pinning code was found in the 1,730-source bundle. T3 also has a separate CLIProxyAPI usage reader (`../src/usage/cliproxyApi.ts:128–155`) that lists auth files and probes their usage; this is likewise a usage reader, not the request router.

## Live read-only snapshot

At about 2026-10-22 04:14 UTC, `GET http://127.0.0.1:8080/relay/limits` on the hub host returned 10 Claude, 4 Codex, and 2 Grok entries and one `active_id` for each provider. The one-based row positions in the returned list were Claude **6** (Claude Max 20x), Codex **3** (ChatGPT Pro), and Grok **1** (plan not reported). These are point-in-time values only; the endpoint does not explain why those IDs are marked active or how/when they change. Account IDs and email addresses were not copied into this report.

The forwarded T3 MCP endpoint at `http://127.0.0.1:14606/mcp` accepted the supplied OAuth token for `initialize` and `tools/list` (89 tools). It exposed no pool-account usage or routing operation. `t3_thread_configure` accepts `modelSelection.provider`, `instanceId`, `model`, `options`, and `routingMode`; it exposes provider/model configuration, not an account ID from the relay's pool.

## Selection, switching, and stickiness

| Question | Finding |
|---|---|
| Which account is picked for a new run? Least-used, round-robin, 5-hour/weekly priority, or plan weighting? | **Unknown for this deployment.** The inspected T3 code consumes `active_id` after selection. Neither the active snapshot nor quota percentages disclose the selector. The Claude Max/Pro and Codex Pro/Pro Lite plan labels are usage metadata in this code path, not a selection rule. |
| When does it switch? Threshold, 429, auth error, or reset? | **Unknown for this deployment.** T3's relay adapter reports an account's `error`/`rejected` status and quota windows; it does not choose a replacement. `hubRelay.ts:79–90` says a provider-rejected credential is no longer routed by the hub, but that message is status interpretation, not the selection algorithm. Its 429 handling refers specifically to a **limits check** being retried, not a generation request. No threshold for switching was found. |
| Is selection sticky per run or thread? Can it change mid-thread? | **Unknown for this deployment.** The active marker is provider-wide in the relay response; the T3 mapping contains no thread/run binding. This does not prove the relay itself lacks stickiness. |
| What happens to conversation state/cache if it changes mid-thread? | **Unknown for this deployment.** T3 retains the thread conversation, but the inspected integration does not transfer provider-side session state or cache between pool accounts. The upstream CLIProxyAPI issue below documents a real cross-account state failure in one Codex Responses API setup; it cannot establish the behavior of this relay. |
| Can a worker pick/pin the pool account? | **No pool-account selector was exposed by the inspected MCP/API contract.** A client can configure a T3 provider instance (`instanceId`) and provider/model on a thread, but the usage-source contract says those listed accounts are not runnable provider instances in that environment. Whether the underlying hub accepts a private account-pinning header or setting is unknown. |

## Display labels

- **“Readable” / “N of N readable”:** the relay payload contains `creds_loaded`. T3 maps `creds_loaded: false` to a probe-failed snapshot with “This hub account is signed out” (`hubRelay.ts:114–121`). The exact UI phrase “readable” and its counting rule were not present in the T3 bundle; whether it means only `creds_loaded` or includes other checks is unknown.
- **“Refill in”:** the payload reports quota-window `used_pct`, `resets_at`, and optional `window_minutes` (`hubRelay.ts:25–32`). The T3 usage page describes reset/refill countdowns from provider-reported reset times and explains that weekly exhaustion can limit the session window's pooled contribution. The code does not define a separate hub-specific “refill in” rule.
- **“1 reset · expires in”:** T3's shared contract calls these banked Codex reset credits: they are provider-granted credits, distinct from the ordinary quota windows, and `nextExpiresAt` carries the next credit expiry (`providerUsageLimits.ts:31–40`). The relay maps `reset_credits.available`, `next_id`, and `next_expires_at` into that structure (`hubRelay.ts:34–38`, `155–164`). Thus a displayed count of one and expiry countdown correspond to one reported credit and its next reported expiry, not a 5-hour/weekly refill. Exact wording may depend on the UI version.
- **“in use”:** T3 maps `active_id === account.id` to `active: true` (`hubRelay.ts:175–192`). The code does not define whether the relay's active ID means last used, default, pinned, or currently serving an in-flight request.

## Public routing references and limits

The T3 [public usage page](https://github.com/pingdotgg/t3code/blob/main/docs/user/usage.md#connect-a-cliproxyapi-hub) directly distinguishes pooled quota display from request routing. Web searches for `<hub-vendor> MultiCode T3 Code hub accounts`, `site:<hub-vendor>.org MultiCode hub pool accounts`, and `T3 Code hub subscription account rotation readable refill in` returned no public <hub-vendor>/MultiCode documentation defining this deployment's selection or failover behavior; the relevant result was T3's usage documentation.

For comparison only, current upstream [CLIProxyAPI configuration docs](https://github.com/router-for-me/CLIProxyAPIDocs/blob/main/docs/en/configuration/basic.md) list `round-robin` as the default selector, `fill-first` as an alternative, and `session-affinity: false` by default; their comments say failover is enabled when a bound auth becomes unavailable. The upstream [session-affinity discussion](https://github.com/router-for-me/CLIProxyAPI/issues/2594) says affinity keeps detected sessions on one credential while available and rebinds on unavailability. These settings are **not attributed to the live MultiCode relay**: the T3 package has a CLIProxyAPI usage-reader adapter, but the live `<hub-auth-service>` service and its routing configuration were not available in source form, and the observed `/relay/limits` contract alone does not identify its scheduler or configuration.

## Implications for our hub workers

Workers can select a T3 provider/instance and model through thread configuration, but the exposed interface does not let them pin one of the relay's pool accounts. Treat `active_id` as a live status snapshot, not an allocation guarantee; T3 preserves thread history, while continuity of an account-bound provider session/cache across a relay-side switch remains unverified.
