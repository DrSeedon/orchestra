# #171 — Ouroboros/Claudexor as a replacement for Orchestra's Claude/Codex backends

- **Research date:** 2026-08-10
- **Orchestra baseline:** `c9295ac607415d3009d4a18d7b66288dcebd2f4d`
- **Ouroboros inspected:** `2687666c071e1076be70f4dff80e67b38c6ae384` (release 6.93.1)
- **Claudexor inspected:** `56df2b0438d114a71f442f7f94f9a520eab6ddd3` (package/release 3.3.14)
- **Scope:** source/release/test/issue inspection and official current provider terms only. No install, login, token read, live account call, deployment, or restart was performed. The referenced Telegram image was unavailable; repository source and current provider documents are treated as authoritative.

## Executive answer

**No: Orchestra should not replace `backend_claude.py` or `backend_codex.py` with Ouroboros/Claudexor. It should also not adopt automatic cross-account quota rotation for subscription accounts without written provider approval.** Confidence: **HIGH** for the technical decision, **HIGH** for the OpenAI compliance blocker, and **MEDIUM-HIGH** for the Anthropic/Cursor compliance risk (the retrieved terms do not name every multi-account shape explicitly).

Claudexor is not an SDK/app-server transport broker. It is a second local orchestrator and control plane which starts a new `claude -p --output-format stream-json` or `codex exec --json` process for each run, normalizes those processes into its own run/thread/event model, owns credential-profile routing, journals, workspaces, review modes, and a bearer-authenticated `/v2` API [S8][S9][S10]. Ouroboros did not delete its integration code after adopting Claudexor: it added a pinned runtime manager, daemon supervisor, gateway, account UI/services, and durable delegated-run custody. A lexical measurement at the inspected commit finds 26 production Python/JSON files containing `claudexor` (23,961 lines total) and 24 test files (29,288 lines total); this is a coarse integration-surface measure, not code exclusively attributable to Claudexor [M1].

The semantic mismatch is blocking:

- Orchestra's Codex backend owns one persistent app-server process and resumable thread, uses `turn/steer` during an active turn, receives native item/MCP/collaboration notifications, and invokes native context compaction (`app/backend_codex.py:269-315,338-467,534-610,837-1377,1482-1526`) [S22]. Claudexor runs `codex exec`/`codex exec resume` once per turn; its schema explicitly says Codex exec has no message deltas, and no Claudexor control endpoint exposes `turn/steer` or manual thread compaction [S9][S10][M2].
- Orchestra's Claude backend is an official persistent `ClaudeSDKClient` with `query`, SDK control-channel interrupt, partial messages, direct MCP configuration, context usage, and SDK task/subagent events (`app/backend_claude.py:116-212,222-355,389-625`) [S21]. Claudexor spawns `claude -p` per run; its bidirectional stdin is for Claude's interactive control protocol, not arbitrary Orchestra mid-turn messages [S8][S10].
- Claudexor's durable thread abstraction is real and useful, but it serializes follow-up *turns*. It does not preserve Orchestra's send-during-active-turn semantics. Switching credential profile deliberately starts a fresh vendor session; continuity is reconstructed with a continuation packet rather than preserving the same native conversation [S11][S12]. That is acceptable for a one-shot delegated child, not transparently equivalent to a long-lived Orchestra worker.

The only defensible reuse is **design prior art**: per-identity session affinity, fresh-only quota evidence, explicit applied-route receipts, idempotent run-start custody, and failover only before any deliverable/workspace effect. Even those ideas must be separated from cross-account quota pooling.

## Question and acceptance bar

- **Context:** live self-hosted Orchestra, Python asyncio/FastAPI/MCP/SQLite, dozens of agents, official Claude Agent SDK and Codex app-server/CLI, subscription OAuth, long-lived sessions, worktrees, mid-turn steering, background resume, and fail-closed quota safety.
- **Change under test:** replace Orchestra's bespoke Claude/Codex backends wholly or partly with Ouroboros and its Claudexor integration.
- **Baseline:** current `app/backend_claude.py`, `app/backend_codex.py`, and the surrounding session/manager/quota/MCP lifecycle at `c9295ac` [S21][S22][S23][S24].
- **Decision outcomes:** full backend replacement; narrow account-transport/broker adapter; borrow bounded concepts; or no adoption.
- **Acceptance:** preserve native session/thread identity, ordered/lossless streaming and steering, MCP/tool semantics, retry/idempotency boundaries, quota safety, restart recovery, and token confidentiality while materially reducing maintained code. Credible ToS/account-ban, token-exfiltration, lost-turn, or session-corruption risk is blocking.

## Hypotheses and falsifiers

1. **Full replacement.** Claudexor exposes an equivalent persistent-session/event contract.
   **Falsifier:** either provider lacks native resumable identity, partial streaming, MCP/tool fidelity, mid-turn steering, manual compaction, or a lossless retry boundary.
2. **Transport-only adapter.** Claudexor can select/refresh/rotate OAuth accounts while Orchestra retains its backends.
   **Falsifier:** there is no secretless public credential-broker contract, refresh remains vendor-owned, profile selection is coupled to Claudexor-run processes, or rotation violates provider terms.
3. **Borrow ideas only.** The dependency is unsuitable, but bounded lifecycle ideas are valuable.
   **Falsifier:** adopting the runtime is demonstrably safer, terms-compatible, stable, and cheaper than copying only small verified invariants.
4. **No adoption.** Existing official integrations remain the only production-defensible route.
   **Falsifier:** the candidate has authoritative provider support or an equivalently compliant and materially stronger lifecycle/security contract.

## What Ouroboros actually integrated

### Version, release, license, and exact dependency

- Ouroboros HEAD was release 6.93.1, MIT, latest release published 2026-08-09. Its repository API reported `open_issues_count=80` and a push on 2026-08-10 [S1][S2]. GitHub's field includes pull requests, so it is not used as a quality score.
- Claudexor HEAD/package was 3.3.14, MIT, latest release published 2026-08-09. Its repository API reported `open_issues_count=30` and a push on 2026-08-09 [S3][S4]. Again, popularity/counts are not decision evidence.
- Ouroboros 6.93.1 does **not** consume Claudexor as a normal Python/npm library dependency. It pins a downloadable engine closure: Claudexor 3.3.13, build SHA `ce23f7abb22941b67910fd1033595dbda736f208`, control protocol major 3, exact archive URL, SHA-256 `70a431…c10846`, 20,705,255 bytes, Node 24.16.0, and entrypoint `claudexord.bundle.cjs` [S5]. The latest Claudexor release was already 3.3.14, so the inspected Ouroboros release was one patch behind its upstream's only-supported-latest policy [S4][S17].
- Ouroboros verifies archive size and SHA-256, downloads atomically, rejects path traversal/links/special files, verifies the packaged Node version, and probe-checks version/build SHA before promotion [S6]. This is stronger than an unpinned `npm install`; it is still a maintainer/release-account trust root unless the signed upstream manifest is independently verified.

### Architecture and wire contract

Ouroboros uses Claudexor as a **delegated execution substrate**, not as its primary conversational backend:

1. `claudexor_runtime.py` downloads and promotes the exact engine closure; `claudexor_daemon.py` runs an Ouroboros-owned daemon under a separate data/config root and best-effort patches `profileLimitAction=rotate` [S6][S7].
2. `gateways/claudexor.py` reads `control-api.json` plus a bearer token, rejects non-loopback descriptors, disables proxy inheritance, negotiates protocol major/version, then calls `/v2` for runs, artifacts, cancellation, quota, profiles, setup jobs, models, settings, and secrets [S7]. The token grants the entire `/v2` surface.
3. Ouroboros's gateway exposes `start_run/get_run/get_run_artifact/cancel_run`; it does **not** expose Claudexor thread creation/turns or run-event SSE. `delegate_wait` polls `GET run`, observes the durable sequence, and implements a second custody/idempotency/settlement layer around Claudexor [S7].
4. The delegated request pins one harness, requests subscription auth, selects a read-only or workspace-write mode, and treats requested isolation separately from proven applied isolation. Ouroboros explicitly warns that an in-place child would otherwise inherit the operator home containing the daemon token [S7].

Direct measurement [M1]:

```text
Ouroboros claudexor lexical files: production Python/JSON 26 files / 23,961 lines
Ouroboros claudexor lexical files: tests 24 files / 29,288 lines
Claudexor selected relevant production packages:
  harness-claude 3,057; harness-codex 3,121; orchestrator 20,736;
  daemon 7,105; control-api 10,440; secrets 162; schema 12,829; core 5,036 lines
Selected-package tests: 58,908 lines
```

These counts prove neither correctness nor bloat. They disprove the premise that using Claudexor eliminates integration ownership: Ouroboros owns a substantial compatibility, lifecycle, security, and custody layer around it.

## Reconstructed Claudexor contracts

### Process and provider adapters

- Claude: one CLI child per run using `claude -p --output-format stream-json`; native session continuation uses `--resume <id>`. The shared run loop owns spawn, stdin control frames, redacted stderr, cancel/reap, dropped-line counters, and exactly one terminal `completed` event [S8][S10].
- Codex: one CLI child per run using `codex exec --json`, or `codex exec resume <id> --json`. It is not Codex app-server. The adapter obtains the native thread id from exec JSON/transcript and normalizes events; Codex exec does not supply streaming message deltas [S9][S10].
- Cursor/OpenCode/raw-API are additional Claudexor harnesses, but adding provider breadth is not an Orchestra requirement and expands the trusted surface [S17]. Model lists are adapter/catalog driven and explicit unknown models fail closed; this is a sound contract but not a substitute for native app-server feature parity [S10].

### Account storage, OAuth, and refresh

- A credential profile is one of `config_dir_login`, `oauth_token`, or `api_key`, with a harness id, isolated locator or namespaced secret reference, and enabled state [S13].
- Claude `config_dir_login` uses a separate `CLAUDE_CONFIG_DIR`; Codex uses a separate `CODEX_HOME`. A profile may not alias the ordinary default native store. A resumed native session never crosses profiles [S11][S13].
- On Linux, vendor-native Claude OAuth credentials remain plaintext in that profile's vendor `.credentials.json` (documented as mode 0600); macOS uses a profile-keyed Keychain item. Codex login state remains in its vendor `auth.json`. Claudexor reads only allowlisted identity claims for display, but the vendor CLI owns authentication and token refresh [S13][S14].
- Claudexor does **not** provide a public “refresh and lend this OAuth credential to my existing SDK/app-server” API. Its direct Claude quota poll reads the current access token and calls Anthropic's `oauth/usage`; 401/403 becomes `auth_revoked`, other failures become unknown. It does not use the stored refresh token itself [S14]. Runs rely on the vendor CLI/profile store to refresh credentials.
- Managed `oauth_token`/API-key values use Claudexor's own `secrets.json`. It is JSON plaintext at rest, guarded by a private directory, `0600`, regular-file/symlink checks, exclusive temp creation, fsync, and atomic rename; there is intentionally no system-keychain backend [S15].

**Finding:** a transport-only adapter is not available. Taking only account selection would require a new upstream API that returns either credential-store paths or credential material, then changing Orchestra to restart a provider process on the selected identity. The former couples Orchestra to Claudexor's private filesystem layout; the latter expands token exposure. **Confidence: CONFIRMED** — source/API inspection, evidence tier 2 [S7][S13][S14][S15].

### Rotation, failover, affinity, and retries

- Rotation is opt-in (`fail|ask|rotate`). Only fresh quota snapshots can trigger proactive headroom rotation; missing/stale usage is not a breach [S12]. This is fail-open with respect to missing quota, unlike Orchestra's worker admission, where unknown/stale weekly quota is refused (`app/quota_gate.py:24-40,201-248,272-355`) [S24].
- Rotation stays within the same credential kind and a configured/ready profile pool. Reactive rotation requires a typed vendor limit and no deliverable; it creates a **new** vendor session with `resume_session_id=null` [S12]. This is a sound anti-duplicate rule for one-shot work, but it cannot transparently continue the same native session.
- Claudexor's thread is the durable source of truth; vendor sessions are per-(thread,harness,profile) lane caches. A lane switch uses a continuation packet, while an in-lane turn may use native resume. Per-thread turn submission is serialized, one run per thread is active, and unrelated/threadless work can run concurrently under global limits [S11].
- Start/turn mutations are idempotent by client/key/request bytes and reject key reuse with a different request. Run SSE supports a durable sequence cursor/`Last-Event-ID`; malformed cursors fail typed [S16]. Ouroboros nevertheless adds a second durable “record request before POST / distinguish definite from unknown / replay same body+key” custody layer, evidence that the API alone does not remove host-side exactly-once responsibility [S7].

### Streaming, tools, MCP, interaction, and context

- Claudexor normalizes `started`, thinking/message, tool call/result, interaction, file/patch, usage/quota, error/status, context, and completed events. It counts unknown/unparsed CLI output and guarantees one terminal completion [S10].
- Claude can produce deltas and interactive control requests; Codex exec explicitly has no message deltas. MCP server definitions can be injected into each run, but this is per-process configuration, not Orchestra's persistent MCP subprocess/session contract [S8][S9][S10].
- Claudexor recognizes Claude compaction boundaries and typed context exhaustion, and it can synthesize a continuation packet for a new lane/session. Source search found no `/v2` operation that asks a live native conversation to compact; “compact” control hits are event/projection language only [M2]. This is not equivalent to Orchestra's native Codex `thread/compact/start` or its structured Claude handoff/restart with queued-message retention (`app/session.py:1494-1745`) [S22][S23].
- A new Claudexor thread turn submitted while another is active is serialized as the next run. It is not forwarded as `turn/steer`/`ClaudeSDKClient.query` to the active provider process [S11][M2].

### Observability and deployment

- The daemon journals commands/events, exposes run snapshots and resumable SSE, records route/profile/quota and local attempt telemetry, and publishes control problems. This is materially stronger than treating a CLI exit code as the whole result [S10][S16][S17].
- It adds a Node daemon, Unix socket/named pipe, loopback HTTP server, bearer token, control descriptor, journal/config/run trees, vendor CLI child processes, and another version/protocol/update lifecycle [S16][S17]. Only the latest Claudexor release is supported [S17].
- Direct npm installation is `npm install -g claudexor`; the inspected top-level package manifests contain no `preinstall`/`install`/`postinstall`/`prepare` lifecycle hook, while the documented optional harness/plugin installers deliberately mutate user-global CLI/MCP wiring [S17][S35][M5]. Ouroboros instead downloads the pinned prebuilt engine closure and does not execute npm installation as part of its integration [S5][S6]. Neither path removes transitive/package-release trust.
- Claudexor states that it collects no remote analytics/crash reporting, but the daemon may poll vendor quota endpoints and the app may check public release manifests on foreground; vendor CLIs/model routes remain outbound network actors [S17]. Local “telemetry” files contain run evidence and may contain operationally sensitive prompts/results even though the project redacts known secret shapes.

## Security audit

| Surface | Verified behavior | Residual risk / verdict |
|---|---|---|
| Managed secrets | `secrets.json` plaintext JSON, private dir, `0600`, no symlink, atomic/fsync write [S15]. | **BLOCKING for direct token-broker use.** Permissions protect against other Unix users, not same-UID processes, backups, disk theft, or a compromised agent. No at-rest encryption/keychain path. |
| Vendor OAuth stores | Separate Claude config dirs/Codex homes; native CLI owns refresh. Linux Claude credential file and Codex `auth.json` are plaintext vendor stores; macOS Claude can use Keychain [S13][S14]. | Similar inherent risk to current CLI use, multiplied by number of accounts and copies. Claudexor does not remove token custody from the host. |
| Daemon bearer | Random token in owner-controlled `0600` file; regular-file/link/owner checks; entire `/v2` surface uses timing-safe bearer comparison [S16]. | Token is a local root capability: start/cancel runs, read artifacts, mutate settings/secrets. Any same-UID process or unconfined agent that can read the operator home can control the daemon. |
| Network exposure | HTTP defaults to `127.0.0.1`, requires loopback Host/Origin plus bearer; Ouroboros additionally rejects non-loopback descriptor values and uses `trust_env=False` [S7][S16]. | Good SSRF/token-exfiltration mitigations. Claudexor's generic pointer reader accepts its recorded host, so an embedding host should retain Ouroboros's explicit loopback validation. There is no TLS because the boundary is local. |
| Child environment | Central denylist scrubs provider secrets/base URLs, and `clean` mode allowlists runtime/proxy variables before adding one selected credential [S18]. | Strong mitigation, but `mirror_native` remains a mode; HOME/config-dir and mounted files still define the real blast radius. Environment scrubbing is not filesystem confinement. |
| RCE/tool execution | The product intentionally spawns coding CLIs/MCP tools and can apply patches. Delegated modes can request OS confinement; direct/in-place runs may be unrestricted [S10][S17]. | A stolen bearer or prompt injection reaches a high-power local execution service. Treat daemon token protection and OS confinement as production-critical, not “localhost is safe.” |
| Network denial | `web: off` is a tool policy, not OS network isolation; issue #118 reports traffic with `web: off` and remains open [S20]. | **BLOCKING** if Orchestra would interpret it as egress isolation. Use an OS/network sandbox for that claim. |
| Supply chain | MIT; release assets include checksums/SBOM/evidence. Ouroboros pins URL/hash/size/build/protocol/Node and safe-extracts [S2][S4][S5][S6]. | Better than floating npm. Still adds a large third-party executable trust root. Claudexor supports only latest; Ouroboros was one patch behind. Rapid releases increase review/update load. |
| Install hooks | No lifecycle-hook key was found in inspected Claudexor package manifests; explicit harness/plugin install commands can change global host/MCP configuration [S17][S35][M5]. | Lower automatic install-script risk at this commit, not a dependency-tree audit. Any live install still expands executable supply-chain and configuration-mutation scope. |
| Update availability | Current issue #155 reports 3.3.13 runtime replacement stopped a healthy daemon before the successor failed; issue remains open even though 3.3.14 contains related fixes [S19]. | **BLOCKING for unattended production replacement** until a proven successor-before-retire/rollback invariant and soak exist. |
| Telemetry/privacy | Project says no remote telemetry; quota/update/vendor calls are disclosed; local artifacts are retained [S17]. | Claim is source/document based, not packet-capture verified. Retention/backup access still needs an Orchestra threat model. |

No concrete SSRF or arbitrary remote unauthenticated RCE was found in the inspected paths. That is not a proof of absence. The main security regression for Orchestra would be adding a same-UID bearer-capability daemon and duplicating credential/session state without eliminating the current lifecycle layer.

## Current issues as counter-evidence

The following were open on 2026-08-10 and touch the exact blocking invariants; they are not treated as timeless defects or proof that all current code paths fail:

- Claudexor #155: healthy daemon retired before successor startup failed, leaving no daemon [S19].
- Claudexor #121: one exhausted route could make the harness unavailable despite an alternative route [S19].
- Claudexor #119: cancellation reported success/discarded partial output in the reported path [S19].
- Claudexor #118: `web: off` did not provide network isolation [S20].
- Ouroboros #160: task SSE may stop at `cancel_requested` and omit the authoritative cancelled envelope [S20].
- Ouroboros #167: delegated-run recovery health gate can delay collection and re-recorded custody can lose `project_id` [S20].

The source contains substantial tests: 43 orchestrator, 18 control-api, 16 daemon, 14 Claude-harness, and 10 Codex-harness `*.test.ts` files; inspected cases cover profile rotation, same-profile resume, idempotency conflicts, durable restart, terminal uniqueness, token redaction, and unsafe paths [M3]. Ouroboros has three `test_claudexor*.py` modules covering runtime delivery/daemon/platform smoke [M3]. **None was executed**, because this task forbids installation and live environment mutation. Therefore test presence is corroborating design evidence, not a green runtime result.

## Provider terms and subscription risk

This section is a technical compliance assessment, not legal advice. Only current official provider sources are used.

### Anthropic

- Ordinary use is supported: Anthropic explicitly sells Max with Claude Code access and documents Claude Code as a subscription terminal workflow [S25]. Its current Agent SDK notice says the proposed separation of `claude -p`/Agent SDK billing was paused and, for now, Agent SDK, `claude -p`, and third-party app usage still draw from the subscription limit [S26]. This product-specific documentation is the relevant explicit permission for ordinary third-party Agent SDK/`claude -p` use.
- Consumer terms prohibit sharing account credentials, prohibit automated/non-human access unless explicitly permitted, prohibit bypassing protective measures, and describe subscription technical limitations [S27]. The official product docs above supply explicit permission for the ordinary Claude Code/Agent SDK channel; they do not grant permission to pool several personal subscriptions and automatically switch when one technical limit is reached.
- Anthropic now offers usage bundles as its documented paid continuation beyond included limits [S28]. Automatic rotation to another personal account specifically on a quota threshold is therefore **LIKELY** to be viewed as bypassing a technical/protective limit, even if every account belongs to one person. Written approval is required before production use. Confidence **MEDIUM-HIGH**: primary terms plus product docs, but no clause retrieved says the exact words “multiple accounts owned by one person.”

### OpenAI / Codex

- OpenAI explicitly supports signing the Codex CLI into a ChatGPT account and says usage limits apply. On reaching the limit, documented options are credits, upgrade, or waiting for reset [S29].
- The current EEA/UK consumer Terms prohibit sharing account credentials and “circumventing any rate limits or restrictions” or bypassing protective measures [S30]. The business Services Agreement is even more explicit about not configuring services to avoid Usage Limits, but the consumer terms already decide this individual-subscription case [S31].
- Rotating to a second ChatGPT subscription because the first hit quota matches the prohibited purpose regardless of whether Claudexor uses the official Codex CLI. **BLOCKING / HIGH confidence.** Invoking an official client does not legalize the host's quota-circumvention policy.

### Cursor

- Cursor officially documents non-interactive CLI/script use, so ordinary scripted use is supported [S32]. Current pricing says that after included use the user can purchase additional usage or upgrade [S33].
- The retrieved current Terms require account security and forbid lending/selling the service, but do not expressly name self-owned multi-account rotation or rate-limit circumvention in the inspected restriction list [S34]. Thus “definitely prohibited” is not supported by the fetched primary text; “safe” is also unsupported. Automatic quota-triggered pooling conflicts with the documented paid continuation path and needs written authorization. **UNCERTAIN / MEDIUM confidence.**

**Compliance decision:** keep one explicitly authorized provider identity per Orchestra worker/session, follow vendor-native limit/credit/upgrade paths, and fail closed on exhausted/unknown quota. Do not implement cross-account automatic rotation from Claudexor or copy that feature.

## Capability comparison matrix

| Capability | Orchestra baseline | Claudexor/Ouroboros | Replacement result |
|---|---|---|---|
| Provider process | Persistent Claude SDK client; persistent Codex app-server per worker [S21][S22] | New `claude -p`/`codex exec` child per run [S8][S9] | **No parity** |
| Native identity | Claude session UUID / Codex thread id persisted and resumed [S21][S22][S23] | Native session cached per thread+harness+profile lane [S11] | Partial; different owner |
| Mid-turn input | Claude SDK `query`; Codex `turn/steer`; failed inject retained in queue [S21][S22][S23] | New serialized follow-up turn; no steer endpoint [S11][M2] | **Blocking gap** |
| Partial text stream | Both backends map partial/native stream [S21][S22] | Claude deltas; Codex exec explicitly no deltas [S10] | **Blocking UX/event gap** |
| Tool/MCP events | Native MCP startup/progress, tool, approval, collaboration/subagent mapping [S21][S22] | Normalized generic tool/MCP events from per-run CLI [S10] | Lossy/non-equivalent |
| MCP lifecycle | Orchestra merges user/scope/instance config; persistent runtime owns MCP [S21][S22] | MCP config injected for each child run [S8][S9] | Different failure/restart semantics |
| Interrupt/cancel | SDK/app-server acknowledgement; disconnect on no acknowledgement [S21][S22][S23] | Abort/reap run process; exactly-one completion intended [S10] | Comparable goal, different boundary |
| Manual compaction | Native Codex compact; structured Claude handoff/restart; queued-message fence [S22][S23] | Observes context signals; continuation packet; no control compact [S10][S11][M2] | **Blocking gap** |
| Session/profile affinity | Session row/config determines identity; resume transcript checks [S21][S23] | Strong `(thread,harness,profile)` lane; never resume across profile [S11][S13] | Claudexor idea is useful |
| Rotation | Orchestra quota gates start; no silent account switching [S24] | Fresh headroom/reactive typed-limit rotation; new session [S12] | Technically bounded, compliance-blocked |
| Unknown quota | Fail closed for workers [S24] | Missing/stale is not a breach and therefore remains eligible [S12] | **Safety regression** |
| Idempotent start | Session queue restores messages on send failure [S23] | Durable idempotency keys and conflicts; Ouroboros adds custody [S7][S16] | Claudexor stronger for one-shot starts |
| Concurrency | Dozens of independent persistent sessions/worktrees [S23] | One active run/thread plus global daemon concurrency [S11] | Requires new capacity model |
| Restart/background resume | SQLite hydration/manager auto-resume/background jobs remain Orchestra-owned [S23] | Daemon journal/run recovery, separate state tree [S16] | Duplicate state machines |
| Worktrees | Orchestra creates/owns worker worktree and merge lifecycle [S23] | Claudexor supports in-place or its own isolated worktree [S11] | Ownership conflict; cannot replace manager |
| Telegram/steering/auto-report | Orchestra session/manager/TG/MCP concerns [S23] | Not provided by backend adapter | Cannot replace |
| Observability | AgentEvents, SQLite logs, quota and session status [S21][S22][S23][S24] | Durable run artifacts, typed events, route receipts, SSE [S10][S16] | Useful, but another data plane |
| Secrets | Existing vendor stores/profile config dirs [S21][S22] | Vendor stores plus plaintext managed secret file and daemon bearer [S13][S15][S16] | Larger attack surface |
| Deployment | Python service plus official SDK/CLI/app-server [S21][S22] | Adds pinned Node engine/daemon/control API/journal/update protocol [S5][S16][S17] | More operations, not less |
| Model support | Runtime registry plus native provider capability [S21][S22] | Dynamic/manifest harness catalogs; Claude/Codex/Cursor/OpenCode/raw [S10][S17] | Breadth gain, semantic loss |
| License | Orchestra project terms unchanged | Ouroboros and Claudexor MIT [S1][S3] | No copyleft blocker |

### What it could and could not replace

**Could replace, if deliberately introduced as a separate optional subsystem:** a one-shot delegated-job runner with its own workspace, durable idempotent start, route receipt, and artifact collection. That is the shape Ouroboros actually uses [S7]. It is not the user request's backend replacement.

**Could provide as read-only inputs:** quota snapshots and profile readiness. Even this needs provider authorization for multiple-account use and a fail-closed adapter around missing/stale data. It does not require surrendering session execution to Claudexor.

**Cannot replace:** Orchestra's persistent Claude/Codex transports, active-turn injection/steering, native event fidelity, manual compaction, `AgentSession` queue/lifecycle, SQLite recovery, worktree/merge lifecycle, MCP and agent-to-agent semantics, Telegram delivery, background jobs, or quota admission policy [S21][S22][S23][S24].

## Alternative-hypothesis verdicts

1. **Full backend replacement — REFUTED (HIGH).** Both process and wire semantics fail the acceptance bar. Replacing roughly 2,152 backend lines would leave at least 9,239 lines of measured surrounding session/manager/quota/MCP/routes/background lifecycle and add a new daemon/control adapter [M4].
2. **Transport-only account adapter — REFUTED for current public API (HIGH).** Claudexor owns config-dir selection inside its run adapters and does not expose a secretless credential lease/refresh API. Automatic quota rotation is independently compliance-blocked [S12][S13][S14][S30].
3. **Borrow ideas only — CONFIRMED (HIGH).** Reusable invariants: same-profile native resume, explicit fresh/packet continuity, fresh-only headroom evidence, typed route receipt, replay of the exact request/key after ambiguous start, and no reactive retry after a deliverable [S7][S11][S12]. Borrow invariants, not the runtime or cross-account rotation policy.
4. **No runtime adoption now — CONFIRMED (HIGH).** It has the lowest ToS, token, state-corruption, and operational risk while preserving official native provider contracts. Re-evaluate only if Claudexor exposes a provider-authorized, secretless account service and a persistent app-server/Agent-SDK transport with parity tests.

## Integration complexity and migration risk

These are engineering estimates, not measured delivery times; confidence **LOW-MEDIUM**. Assumptions: one experienced engineer, no provider changes, current feature set retained, and production soak required.

| Option | Estimated effort | Main work | Risk |
|---|---:|---|---|
| Full replacement | 32–55 engineer-days + 2–4 weeks soak | Python `/v2`+SSE client, daemon supervision/update, AgentEvent mapper, session/thread migration, steering/compaction substitutes, recovery and security tests | **Very high**; still cannot meet native semantic parity without upstream changes |
| Transport-only broker | 15–25 engineer-days plus upstream API work | New secretless profile lease contract, identity fencing, restart/migration, fail-closed quota adapter | **High**, and ToS approval is a prerequisite |
| Optional delegated runner | 10–20 engineer-days + soak | Ouroboros-like custody, artifact/containment checks, worktree ownership, operational runbook | **Medium-high**; duplicates an orchestrator and is outside the replacement goal |
| Borrow one invariant | 3–8 engineer-days per bounded change | e.g. exact start idempotency or profile-affinity receipts in existing code | **Low-medium** when tested independently |
| No adoption | 0 migration days | Keep current providers; continue targeted backend simplification | **Lowest** |

Estimate decomposition (low/high engineer-days): full replacement = control client/SSE 5/8 + event and feature parity 7/12 + session/thread migration 7/12 + daemon/update/security 5/8 + failure injection/migration preparation 8/15 = **32/55**; transport broker = upstream lease contract 4/7 + provider-process/profile fencing 4/6 + quota/security policy 3/5 + tests/migration 4/7 = **15/25**; delegated runner = control/supervision 3/5 + start custody 2/4 + workspace containment 2/4 + event tests/runbook 3/7 = **10/20**. These are work-breakdown estimates from the source-visible contracts, not benchmark results; provider/upstream delays are excluded.

The estimates exclude legal review and written provider authorization. No maintainability saving is credible until the candidate deletes more lifecycle/state code than its adapter/supervisor/security boundary introduces; current source evidence points the other way.

## Safe read-only sandbox spike (only if the decision is revisited)

No provider login or token is necessary for a useful first spike. Use a fixture/mock `/v2` server and recorded public event schemas in a disposable directory; do not install Claudexor into the live environment.

Acceptance criteria:

1. No network request to Anthropic/OpenAI/Cursor, no real credential/config directory, and a test that fails if the adapter reads outside the fixture root.
2. Reject every non-loopback descriptor before constructing an authenticated request; bearer never appears in child env, log, exception, or stored fixture.
3. Protocol-major handshake fails closed; same idempotency key+same body replays one run; same key+different body is a typed conflict; induced lost response produces no duplicate.
4. SSE reconnect from a durable cursor produces every event exactly once and one terminal event; cancellation race retains the authoritative terminal envelope.
5. Map `started/message/tool_call/tool_result/usage/error/completed` to `AgentEvent` and record every unsupported native event; no silent drop.
6. A contract test demonstrates the known gaps: Codex has no text deltas, send-during-run queues a new turn rather than steering, and no manual compact operation exists.
7. A native session id can resume only on the same harness/profile lane; a profile change must surface `fresh/packet` continuity and may never be labeled native resume.
8. Produce measured adapter LoC, dependency/process count, failure injection results, and a deletion budget against current backends. Pass only if removed production code exceeds added integration code **and** all semantic blockers have an upstream solution.
9. Any real-account follow-up requires written provider approval specifically covering automated multi-account quota-triggered switching. Without it, stop after fixtures.

Estimated fixture-only spike: 3–5 engineer-days. It can validate the control protocol; it cannot validate provider compliance, native session fidelity, or real token refresh.

## Counter-evidence and limitations

- Claudexor has strong, explicit engineering invariants: fsync-before-ack journals, idempotency conflicts, same-profile session affinity, child-env scrubbing, loopback bearer auth, durable SSE cursors, exact terminal-event handling, and a large test corpus [S10][S11][S12][S15][S16][S18]. These argue against dismissing it as a toy.
- Ouroboros's pin/verification/containment/custody layer is careful and directly addresses lost-start and token-exfiltration classes [S5][S6][S7]. This supports using it as prior art for delegated jobs.
- Official Anthropic and Cursor documents explicitly support third-party/non-interactive CLI use; ordinary automation is not itself the problem [S26][S32]. The blocker is quota-triggered pooling and the backend semantic mismatch.
- A source-only review cannot measure runtime latency, daemon crash rate, or real provider event loss. Tests were not executed and no tokens/accounts were touched. This lowers confidence in operational claims, not in source-visible protocol differences.
- Current open issues may be fixed after the inspected commits. Only latest is supported, and the projects release rapidly; any future decision needs a fresh pin/issue/terms audit.

## Adversarial second opinion

The required external Codex/Sol review was attempted against this artifact, but Orchestra's readiness gate rejected the worker turn with `weekly_quota_upgrade_required: ... does not provide worker-weekly-v1`. Per task constraint, no alternate backend or bypass was used. **External verdict unavailable.** A strict Sol self-review is recorded in `docs/tasks/171/codex-review-research.md`.

That review found no unsupported blocker in the recommendation. It did find three traceability weaknesses and they were corrected before finalization: the migration ranges now have an explicit work-breakdown derivation, the exact Ouroboros source that enables `profileLimitAction=rotate` is linked below, and package-lifecycle hook inspection is explicit. The review also retained the lower confidence and written-approval requirement for Anthropic/Cursor rather than upgrading an inference into a legal fact.

## Final decision

**Adopt none of Ouroboros/Claudexor as an Orchestra backend or account-rotation runtime now.** Keep official Claude Agent SDK and Codex app-server transports. If maintenance reduction is the objective, refactor the common `BackendLike`/event plumbing inside Orchestra while preserving the provider-native control channels.

Borrow only these bounded ideas after separate tickets and tests:

1. make provider identity an explicit immutable lane for native session resume;
2. persist the exact outbound request plus an idempotency key before any ambiguous start;
3. record requested vs applied auth/model/profile as a typed receipt;
4. prevent any failover retry after a deliverable or workspace side effect;
5. retain fail-closed quota behavior on unknown/stale observations.

Do **not** borrow automatic cross-account rotation. If a future business need remains, seek written authorization from each provider first, then perform the fixture-only spike above. **Overall confidence: HIGH** — load-bearing technical findings are direct source evidence and the compliance decision rests on current primary provider documents.

## Measurements

- **[M1] Integration surface:** `rg -l -i claudexor <ouroboros>/ouroboros --glob '*.py' --glob '*.json' | xargs wc -l`; same for tests. Measured 2026-08-10 at `2687666c`.
- **[M2] Contract absence:** `rg -n 'compact|turn/steer|mid.?turn' packages/control-api packages/daemon packages/orchestrator packages/schema`; inspected hits were context events/projections and turn serialization, not a steer/manual-compact control operation. Absence claims are limited to inspected commit/API source.
- **[M3] Test inventory:** `find packages/<component>/src -name '*.test.ts'`; selected test names inspected with `rg` for rotation, idempotency, resume, SSE, permissions, and secret redaction. Tests not run.
- **[M4] Orchestra size:** `wc -l app/backend_claude.py app/backend_codex.py app/session.py app/manager.py app/quota_gate.py app/mcp_stdio.py app/routes/sessions.py app/bg_jobs.py` → backends 2,152 lines; listed surrounding lifecycle 9,239 lines; total 11,391. Size is maintenance-surface evidence, not a quality metric.
- **[M5] Install hooks:** `rg -n '"(preinstall|install|postinstall|prepare)"' <claudexor> --glob package.json` returned no matches at `56df2b0`. Root scripts and README install/update commands were then inspected manually. Transitive dependency manifests were not audited.

## Sources

Evidence tier: **T1** direct measurement; **T2** primary source/code/official terms; **T3** issue report (counter-evidence, not independently reproduced).

1. **[S1, T2]** [Ouroboros repository at inspected commit](https://github.com/razzant/ouroboros/tree/2687666c071e1076be70f4dff80e67b38c6ae384) and [MIT license](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/LICENSE).
2. **[S2, T2]** [Ouroboros v6.93.1 release](https://github.com/razzant/ouroboros/releases/tag/v6.93.1).
3. **[S3, T2]** [Claudexor repository at inspected commit](https://github.com/razzant/claudexor/tree/56df2b0438d114a71f442f7f94f9a520eab6ddd3) and [MIT license](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/LICENSE).
4. **[S4, T2]** [Claudexor v3.3.14 release](https://github.com/razzant/claudexor/releases/tag/v3.3.14).
5. **[S5, T2]** [Ouroboros Claudexor runtime pin](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/claudexor_runtime_pin.json#L1-L44).
6. **[S6, T2]** [Ouroboros runtime download/verification/extraction](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/claudexor_runtime.py#L280-L418), [probe and safe extraction](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/claudexor_runtime.py#L1052-L1126).
7. **[S7, T2]** [Ouroboros Claudexor gateway/token boundary](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/gateways/claudexor.py#L1-L251), [gateway operations](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/gateways/claudexor.py#L338-L600), [rotation provisioning](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/claudexor_daemon.py#L409-L430), [delegated request and custody](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/tools/delegate.py#L670-L1058), [polling wait](https://github.com/razzant/ouroboros/blob/2687666c071e1076be70f4dff80e67b38c6ae384/ouroboros/tools/delegate.py#L1188-L1348).
8. **[S8, T2]** [Claudexor Claude harness adapter](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/harness-claude/src/index.ts#L665-L980).
9. **[S9, T2]** [Claudexor Codex harness adapter](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/harness-codex/src/index.ts#L230-L320), [run/auth path](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/harness-codex/src/index.ts#L640-L895).
10. **[S10, T2]** [Harness run/event schema](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/schema/src/harness.ts#L550-L714), [normalized events/context](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/schema/src/harness.ts#L794-L1061), [shared CLI run loop](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/core/src/runloop.ts#L7-L269).
11. **[S11, T2]** [Claudexor thread/session/lane contract](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/schema/src/thread.ts#L13-L208), [continuity disclosure](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/schema/src/thread.ts#L271-L390), [thread turn serialization](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/control-api/src/thread-turn-routes.ts#L223-L448).
12. **[S12, T2]** [Claudexor profile headroom/rotation](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/orchestrator/src/credential-profile-rotation.ts#L1-L143), [proactive/reactive rotation](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/orchestrator/src/credential-profile-rotation.ts#L243-L500).
13. **[S13, T2]** [Credential-profile schema](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/schema/src/credential-profile.ts#L1-L94), [Claude profile routing](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/harness-claude/src/profile.ts#L9-L190), [Codex profile routing](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/harness-codex/src/profile.ts#L31-L191).
14. **[S14, T2]** [Claudexor Claude OAuth usage reader](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/cli/src/claude-oauth-usage.ts#L20-L125), [usage request and absence semantics](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/cli/src/claude-oauth-usage.ts#L202-L330).
15. **[S15, T2]** [Claudexor plaintext 0600 secret store](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/secrets/src/index.ts#L20-L130).
16. **[S16, T2]** [Daemon token storage/validation](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/daemon/src/token.ts#L26-L207), [control server bind/auth](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/control-api/src/daemon-server.ts#L474-L598), [run SSE cursor](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/control-api/src/daemon-server.ts#L1628-L1638).
17. **[S17, T2]** [Claudexor README: architecture/install/privacy](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/README.md), [security policy](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/SECURITY.md).
18. **[S18, T2]** [Harness child environment scrubbing](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/packages/core/src/env-scope.ts#L3-L159).
19. **[S19, T3]** Claudexor issues [#155](https://github.com/razzant/claudexor/issues/155), [#121](https://github.com/razzant/claudexor/issues/121), [#119](https://github.com/razzant/claudexor/issues/119).
20. **[S20, T3]** Claudexor [#118](https://github.com/razzant/claudexor/issues/118); Ouroboros [#160](https://github.com/razzant/ouroboros/issues/160), [#167](https://github.com/razzant/ouroboros/issues/167).
21. **[S21, T2]** Orchestra `app/backend_claude.py` at `c9295ac`: official SDK client, resume, MCP, query/interrupt/context/event conversion (`L116-L625`).
22. **[S22, T2]** Orchestra `app/backend_codex.py` at `c9295ac`: persistent app-server, thread resume, native steer/compact, MCP/collaboration event mapping (`L269-L1526`).
23. **[S23, T2]** Orchestra `app/session.py`/`app/manager.py` at `c9295ac`: queue retention, quota-gated send/flush, reconnect, compaction, persistence, worktree and auto-resume lifecycle.
24. **[S24, T2]** Orchestra `app/quota_gate.py` at `c9295ac`: five-minute freshness, 95% weekly gate, unknown/stale fail closed (`L15-L40,L201-L355`).
25. **[S25, T2]** Anthropic, [What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan) (current 2026-08-10).
26. **[S26, T2]** Anthropic, [Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) — current pause notice and explicit third-party/`claude -p` treatment.
27. **[S27, T2]** Anthropic, [Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms) (effective 2025-10-08, fetched 2026-08-10).
28. **[S28, T2]** Anthropic, [Buy usage bundles](https://support.claude.com/en/articles/14246112-buy-usage-bundles) (2026-05-18).
29. **[S29, T2]** OpenAI, [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-codex-and-chatgpt-plan-usage-limits) (fetched 2026-08-10).
30. **[S30, T2]** OpenAI, [Europe Terms of Use](https://openai.com/policies/terms-of-use/) (fetched 2026-08-10).
31. **[S31, T2]** OpenAI, [Services Agreement](https://openai.com/policies/services-agreement/) (current official business terms; corroborating, not substituted for consumer terms).
32. **[S32, T2]** Cursor, [Using the CLI](https://docs.cursor.com/en/cli/using) — official non-interactive/script use.
33. **[S33, T2]** Cursor, [Models & Pricing](https://docs.cursor.com/account/pricing) — documented over-limit options.
34. **[S34, T2]** Cursor, [Terms of Service](https://cursor.com/terms-of-service) (last updated 2026-01-13, fetched 2026-08-10).
35. **[S35, T2]** Claudexor [package scripts](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/package.json#L1-L55) and [documented install/update paths](https://github.com/razzant/claudexor/blob/56df2b0438d114a71f442f7f94f9a520eab6ddd3/README.md#L82-L180).
