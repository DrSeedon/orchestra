# Task #95 — Grok Build as a third Orchestra runtime — RESEARCH

**Date:** 2026-07-27 · **CLI:** grok 0.2.112 (9bbd559437) · **Model:** grok-4.5 (`grok-4.5-build`)
**Method:** live experiments on the installed CLI via proxy `http://127.0.0.1:12343`. Every claim below is
either a terminal observation this session or a fetched source. Article claims that did NOT reproduce are
marked REFUTED.

---

## Verdict: ВСТРАИВАЕТСЯ (integrates)

Grok Build exposes exactly the surface our architecture needs, and it is **closer to our model than Codex**:

- **Persistent bidirectional stdio process** — `grok agent stdio` speaks **ACP (Agent Client Protocol),
  JSON-RPC 2.0 over stdio**. One long-lived process owns a resumable session; `session/prompt` drives a
  turn, notifications stream events. This is the direct analog of `codex app-server --stdio`. CONFIRMED by
  running it.
- **Session persistence across process death** — `session/load` restored a session from a *previous*
  process and the model correctly recalled the prior turn's content. CONFIRMED by experiment.
- **MCP over stdio works** — our real `app/mcp_stdio.py` connected (`status=ready`, **38 tools**) and the
  model **actually called `orchestra__list_agents` end-to-end**. CONFIRMED by experiment.
- **Autonomous permissions** — `--always-approve` / ACP `permission-mode: bypassPermissions` = our
  bypassPermissions. CONFIRMED (help + README).
- **Instructions** — reads `AGENTS.md` **and** `CLAUDE.md` natively, and `.claude/skills/` natively.
  CONFIRMED (`grok inspect` discovered both live).

**~~The one hard constraint: 10,000-character instruction cap~~ — REFUTED in Phase 2.** The README claims it;
the runtime does not enforce it. A 62 077-char AGENTS.md was read in full via both headless and ACP (see F5).
Our CLAUDE.md passes whole; the existing `sync_agents_md` mirror needs no Grok-specific variant.

**Cost telemetry is exact and trustworthy** (corrected during self-review — see §Review status): the runtime
emits `costUsdTicks` in units of **1e-10 USD**, and it reconciles to **zero residual** across 3 independent
turns with `((input−cachedRead)·$2 + cachedRead·$0.30 + output·$6)/1e6`. Better than Codex, where we scrape
rollout files. Terminal quota-exhaustion event shape is **UNCERTAIN** — could not force-exhaust SuperGrok
to observe it.

---

## Question (framed)

- **Context:** Orchestra runs agents as persistent backends implementing `BackendLike`
  (`connect/send/events/interrupt/disconnect` + `session_id`). Claude = SDK session; Codex = app-server
  JSON-RPC thread. Both resumable across restart, both expose our MCP.
- **Change under test:** add Grok Build as a third backend.
- **Baseline:** `CodexBackend` (`app/backend_codex.py`) — the closest analog.
- **Measurable outcome:** does `grok` provide (1) a persistent stdio process, (2) resumable sessions,
  (3) a streamable event set mappable to `AgentEvent`, (4) our stdio MCP, (5) AGENTS.md, (6) autonomous
  permissions, (7) usable usage/quota telemetry? If (1) OR (4) is missing → integration is stillborn.

## Hypotheses considered

- **H1 (leading):** Grok is a per-invocation headless CLI only (`grok -p ... --output-format json`), no
  persistent process → would NOT fit; each turn = cold process, no mid-turn steering, cache lost.
  **Falsifier:** find a long-lived stdio/socket agent mode. → **REFUTED:** `grok agent stdio` is a
  persistent ACP process; `agent serve` is a WebSocket server; `agent leader` is a shared backend.
- **H2:** Grok cannot host our stdio MCP → worker useless (can't report/merge). **Falsifier:** connect
  `app/mcp_stdio.py` and observe a tool call. → **REFUTED:** connected, 38 tools, live `list_agents` call.
- **H3 (confirmed):** Grok implements standard ACP with x.ai extensions, so it maps to `BackendLike`
  roughly like Codex maps to app-server JSON-RPC. → **CONFIRMED.**

---

## Findings (atomic, evidence-tagged)

### F1 — Persistent stdio agent exists (`grok agent stdio`, ACP). CONFIRMED (measurement)
`grok agent --help` lists subcommands: `stdio` ("Run the agent over stdio"), `headless`, `serve`
(WebSocket, default bind `127.0.0.1:2419`), `leader` (shared backend). Sending
`{"method":"initialize","params":{"protocolVersion":1,...}}` to `grok agent stdio` returns a JSON-RPC
result with `agentCapabilities: { loadSession:true, promptCapabilities:{embeddedContext:true},
mcpCapabilities:{http:true,sse:true} }`. This is **[Agent Client Protocol](https://agentclientprotocol.com)**
— a published standard with official SDKs (Python `agent-client-protocol-python`, Rust, Go, TS, Kotlin).
Evidence tier: direct measurement + primary README §"ACP Protocol Reference".

**Implication for `BackendLike`:** map like Codex —
- `connect()` → spawn `grok agent stdio`, `initialize` → `session/new` (or `session/load` if resuming).
- `send()` → `session/prompt` (request; **blocks until turn end**, result carries `stopReason` + usage).
- `events()` → consume `session/update` notifications until `_x.ai/session/prompt_complete` / the
  `session/prompt` result returns.
- `interrupt()` → ACP `session/cancel` (standard prompt-turn cancellation).
- `session_id` → the ACP `sessionId` (UUIDv7).
- `compact_context()` → `session/prompt` of the `compact` slash-command, or the `[session]
  auto_compact_threshold_percent` runs automatically at 85%.

### F2 — Sessions persist to disk and resume across process restart. CONFIRMED (measurement)
- `session/new` returned `sessionId=019fa3ea-...`; on disk under
  `~/.grok/sessions/<url-encoded-cwd>/<sessionId>/` with `events.jsonl`, `updates.jsonl`,
  `chat_history.jsonl`, `system_prompt.txt`, `summary.json`, `rewind_points.jsonl`.
- Killed that process. A **new** `grok agent stdio` process + `session/load {sessionId, cwd}` succeeded
  (`result` had `models`,`_meta`), and prompting "what word did I ask for last time?" → the model answered
  **"PONG"** (the prior process's content). Session store is cwd-scoped, like Codex threads.
- `grok sessions list` (run in that cwd) shows the session with a generated summary title.
- README §"Agent stdio (ACP)": "The agent persists all session updates automatically. Clients can reconnect
  and load previous sessions by ID." Evidence tier: measurement + primary source.

**Implication:** store the `sessionId` in `sessions.session_id` exactly like Codex thread id; on
`auto_resume_all`, reconnect + `session/load`. Note: session key is **(cwd, sessionId)** — resume must pass
the same worktree cwd.

### F3 — Event stream maps cleanly to `AgentEvent`. CONFIRMED (measurement)
Real dump of one turn (attached: `event-dump.json`). ACP notification → `AgentEvent`:

| ACP `session/update.sessionUpdate` (or x.ai notif) | payload | → AgentEvent |
|---|---|---|
| `agent_thought_chunk` | `content.text` delta, `_meta.totalTokens` | `thinking_stream` |
| `agent_message_chunk` | `content.text` delta | `stream` |
| `tool_call` / `tool_call_update` | `title`, `status`, `kind`, `content` | `tool_use` / `tool_result` |
| `user_message_chunk` | echo of our prompt | (ignore) |
| `available_commands_update` | slash cmds | (ignore/status) |
| `_x.ai/session_notification` + `turn_completed` | **`usage{inputTokens,outputTokens,cachedReadTokens,reasoningTokens,totalTokens,costUsdTicks,modelCalls}`**, `stop_reason` | `turn_end` (usage/context) |
| `_x.ai/session/prompt_complete` | `stopReason`, `agentResult` | turn boundary |
| `session/prompt` **result** | `stopReason: "end_turn"`, `_meta.usage{...}`, `_meta.totalTokens` | `turn_end` |
| `_x.ai/mcp/server_status` | `name,status,reason,detail` | `warning`/`status` (MCP health) |
| `_x.ai/mcp_initialized` | `mcpToolCount` | `status` |
| ACP `error` / `session/request_permission` (server→client request) | — | `error` / auto-answer |

- **Context tracking:** every chunk carries `_meta.totalTokens` (live occupied window), and
  `turn_completed.usage.totalTokens` at turn end. Window = **500000** (`totalContextTokens` in
  `initialize`/`session/new`). `context_pct = totalTokens / 500000`. This is *better* than Codex — no
  rollout-file scraping needed; usage is inline in the stream.
- **Turn model:** `session/prompt` is a **request that blocks until the turn completes** (result carries
  `stopReason`). So unlike Codex's `turn/start`+separate completion notification, Grok gives a synchronous
  turn boundary AND a `prompt_complete` notification. `send()` should fire-and-not-await, letting `events()`
  drive to completion (the request future resolves at `turn_end`).
- Evidence tier: direct measurement (76-event dump, 2 turns).

### F4 — Our stdio MCP connects; model calls Orchestra tools. CONFIRMED (measurement)
`session/new` with `mcpServers:[{name:"orchestra", type:"stdio",
command:"<venv>/python", args:["<repo>/app/mcp_stdio.py"], env:[PYTHONPATH, INTERNAL_TOKEN, ORCHESTRA_URL,
ORCHESTRA_ROLE, WORKER_NAME]}]` →
- `_x.ai/mcp/server_status name=orchestra status=ready`
- `_x.ai/mcp_initialized mcpToolCount=38`
- Prompt "call list_agents" → model emitted `tool_call use_tool` → `orchestra__list_agents` →
  `status=completed`.

**Gotcha found (and root-caused):** first attempt used `command=python -m app.mcp_stdio` and failed with
`handshake failed: connection closed: initialize response`. Cause: `-m app.mcp_stdio` needs cwd at repo root
or `PYTHONPATH`; ACP launches the MCP subprocess in the **session cwd** (the worktree), not the repo. Orchestra
already solves this: `app/runtime_env.py` uses **absolute** `MCP_STDIO_CMD = [sys.executable,
<abs>/mcp_stdio.py]` + `MCP_BASE_ENV={PYTHONPATH: repo_root, HTTPS_PROXY, INTERNAL_TOKEN}`. Reuse that verbatim.

**Behavioral note:** Grok does **not** expose all 38 MCP tools directly to the model. It wraps them behind a
`search_tool` → `use_tool` meta-layer (model searches the tool catalog, then invokes). Tools still work; the
event titles are `search_tool` / `use_tool` / `orchestra__<tool>`. Our event mapper must recognize the
`use_tool` → `orchestra__<name>` shape to surface tool_use/tool_result correctly.

- MCP config also accepts `type:"http"` and `type:"sse"` (`mcpCapabilities.http/sse=true`).
- Grok additionally auto-loads Claude-compat MCP from `~/.claude.json` and `.mcp.json`, and (observed) it
  slurped the user's global `~/.claude` websearch/pandoc MCP servers. **Security flag:** it echoed the
  websearch server's `OPENROUTER_API_KEY` in the `_x.ai/mcp/servers_updated` notification. For managed
  workers we must launch with a clean/overridden MCP set (and ideally `GROK_HOME` isolation) so unrelated
  global MCP servers and their secrets don't leak into worker sessions.
- Evidence tier: direct measurement.

### F5 — AGENTS.md + CLAUDE.md + skills read natively. Instruction cap: **REFUTED** (Phase-2 measurement)

> **CORRECTION (Phase 2).** The "10,000-character cap" below came from the bundled README and was the
> single biggest constraint in this research. I tested it and **it does not exist in v0.2.112.**
>
> Probe: an `AGENTS.md` of **62 077 chars / 115 669 bytes** with markers at chars 10119, 20123, 30127,
> 45089, 60118. The model listed **all five markers**, in **both** the headless (`-p`) and the **ACP**
> path (the one we integrate through). `grok inspect` reported ~28 917 tokens for that file — consistent
> with the whole thing being loaded. No truncation warning appeared anywhere in the event stream.
> An earlier 11 142-char probe with markers straddling the supposed boundary (chars 4913/5319/9853/10357)
> likewise showed all four.
>
> **Consequence:** our 19 252-char (28 580-byte) `CLAUDE.md` is delivered **whole**. The planned
> "slim Grok AGENTS.md generator" ticket is **unnecessary** — the existing byte-for-byte
> `workspace.sync_agents_md` mirror is sufficient as-is. One less moving part, and no section-priority
> decision needs to be escalated.
>
> **Lesson (second one this task):** the vendor's own bundled README was wrong. Both times I was burned
> this task, it was by a *document* — first secondary articles on the cached rate, then primary vendor
> docs on the cap. Both were caught by cheap probes. Measure the runtime, not the manual.

Original (README-derived, now superseded on the cap):
- `grok inspect` in a dir with a local `AGENTS.md` listed **both** `~/.claude/CLAUDE.md (global) [claude]`
  and `AGENTS.md (project)` under "Project Instructions", with token counts. It also listed **65 skills**,
  many tagged `[claude]`, i.e. it reads `~/.claude/skills/` and `.claude/skills/` directly (unlike Codex,
  which needs our generated skill index).
- README §AGENTS.md: recognized names `AGENTS.md, AGENT.md, Agents.md, CLAUDE.md, Claude.md`; deeper files
  win on conflict; gitignored files skipped; **"Each file is capped at 10,000 characters (truncated with a
  warning if exceeded)."**
- **Consequence:** `CLAUDE.md` ≈ 28.6 KB → truncated to 10K. Codex's cap is 32 KiB; Grok's is smaller. The
  existing "keep CLAUDE.md compact" grail is now *more* binding for Grok. Mitigation: ship a slim
  Grok-scoped `AGENTS.md` (worktree-injected, <10K) with the worker-critical rules, same pattern as the
  Codex `AGENTS.md` mirror (`workspace.sync_agents_md`).
- Evidence tier: measurement + primary README.

### F6 — Permissions & sandbox = autonomous-capable. CONFIRMED (help + primary)
- `--always-approve` "Auto-approve all tool executions"; ACP `--permission-mode` values:
  `default, acceptEdits, auto, dontAsk, bypassPermissions, plan`. `bypassPermissions` = our worker mode.
- Config `[features] support_permission=false` disables prompts globally. Current user config already has
  `[ui] permission_mode="always-approve"`.
- Optional OS sandbox: `--sandbox {off(default),read-only,workspace,strict,...}`; Linux Landlock (kernel
  ≥5.13), irreversible once applied, events → `~/.grok/sandbox-events.jsonl`. For our worktree workers,
  `off` (default) matches Codex's `danger-full-access`; `workspace` (write only CWD+/tmp) is available if we
  want defense-in-depth.
- Server→client `session/request_permission` requests appear when not always-approved; our reader must
  auto-answer `{outcome:{outcome:"selected",optionId:"allow"}}` or (preferably) run always-approve so they
  never fire — mirrors Codex's `approvalPolicy=never` + reject-unexpected-requests logic.
- Evidence tier: `--help` + README §Sandbox.

### F7 — Usage/cost telemetry inline and EXACT; quota-exhaustion shape UNCERTAIN. CONFIRMED + UNCERTAIN
- **Per-turn usage** (from `turn_completed` / `session/prompt` result `_meta.usage`):
  `inputTokens, outputTokens, cachedReadTokens, reasoningTokens, totalTokens, modelCalls, apiDurationMs,
  costUsdTicks`. Measured example: `input=22810, cached=5376, output=99, reasoning=93, total=22909,
  costUsdTicks=370748000`. CONFIRMED.
- **`costUsdTicks` is EXACT and usable.** CORRECTED during self-review — my first pass asserted a "9.7× gap"
  and called the field unreliable. That was **my own unit error**: the tick is **1e-10 USD**, not 1e-9.
  At 1e-10 the runtime figure reconciles to **zero residual** against the rate card, on **3 independent
  turns** spanning light and heavy cache:

  | turn | input | cachedRead | output | `costUsdTicks`·1e-10 | computed | delta |
  |---|---|---|---|---|---|---|
  | ping | 22810 | 5376 | 99 | $0.0370748 | $0.0370748 | **0.0000** |
  | resume | 23020 | 22784 | 61 | $0.0076732 | $0.0076732 | **0.0000** |
  | mcp tool | 73980 | 51584 | 837 | $0.0652892 | $0.0652892 | **0.0000** |

  Exact formula (solved from the residual, then validated on the other two turns):

  ```
  cost_usd = ((inputTokens - cachedReadTokens) * 2.00
              + cachedReadTokens              * 0.30
              + outputTokens                  * 6.00) / 1e6
  ```

  Two sub-findings fall out of the exact fit:
  - **True cached rate is $0.30/M, not $0.50/M.** The secondary sources (apidog/OpenRouter/felloai) all say
    $0.50 cached; the runtime says $0.30 and the arithmetic closes exactly at $0.30 on all three turns.
    **The articles are wrong; the runtime is right.** Use $0.30.
  - **`reasoningTokens` is a subset of `outputTokens`, not billed on top** (93 ≤ 99; adding it would break
    the exact fit). Do not double-count it.

  **Decision (revised):** consume `costUsdTicks · 1e-10` directly as turn cost, and keep the token formula
  as a cross-check/fallback. This is *better* telemetry than Codex, where we scrape rollout JSONL for usage.
  Evidence tier: direct measurement, n=3, exact.
- **Terminal quota exhaustion:** README has **no** rate-limit/usage-limit event documentation, and I could
  not force-exhaust SuperGrok to observe the real shape. ACP surfaces failures via the `error` channel and
  `stop_reason`; a quota error would most likely arrive as an ACP `error` notification or a non-`end_turn`
  `stopReason`. **UNCERTAIN — must be probed empirically during implementation** (or by watching for the
  first natural 429), same lesson as the Codex "terminal limit in the error handler" grail. Do not hardcode
  a pattern guessed from memory.
- Rate-limit "willRetry"-style transient events: not observed; unknown. UNCERTAIN.

### F8 — Model & cost basis. CONFIRMED (measurement + multi-source)
- Only model available on this SuperGrok account: **`grok-4.5`** (runtime label `grok-4.5-build`),
  `agent_type=grok-build-plan`, **context window 500000** (`models_cache.json`, `initialize`, `session/new`
  all agree). Reasoning efforts: `low | medium | high` (default **high**). Auto-compact threshold 80–85%.
- **Public API rate card (for our virtual-cost calc):** grok-4.5 = **$2 / $6 per M (input/output), cached
  $0.50** (75% cache discount), 500K context; tiered higher >200K total tokens; server-side tools billed
  separately. Multi-source: apidog, OpenRouter, felloai, Spheron (2026-07). Grok-4.3 = $1.25/$2.50, 1M ctx.
- **REFUTED article claim:** "context ~256K." Measured **500000** in three independent runtime fields.
- Evidence tier: measurement (models_cache + ACP handshake) + ≥3 secondary sources for pricing.

---

## Counter-evidence / conflicts

- **Pricing spread:** resellers list grok-4.5 as low as $1.50/$4.50; xAI official is $2/$6. Runtime
  arithmetic confirms **$2/$6 with $0.30 cached** for this subscription — use those.
- **Secondary sources vs runtime on the cached rate** (F7): every article says $0.50/M cached; the runtime
  closes exactly at $0.30/M on three turns. **Resolved in favour of the runtime** — measurement beats
  articles, which is the whole premise of this research.
- **~~costUsdTicks vs rate card conflict~~** — this "conflict" was my own arithmetic error (1e-9 vs 1e-10),
  not a real discrepancy. Retracted; see F7.
- **Two turn-boundary signals** (F3): both the `session/prompt` request-result AND a `prompt_complete`
  notification mark turn end. Slight redundancy vs Codex's single `turn/completed`. Handle idempotently
  (emit one `turn_end`), or the session layer double-counts — a concrete implementation risk.

## Affected files (for Phase 2/3, do NOT touch in Phase 1)

- **New:** `app/backend_grok.py` — `GrokBackend(BackendLike)`, ACP JSON-RPC over `grok agent stdio`
  (model on `CodexBackend`: reader task, request/notification demux, write lock, event conversion, usage
  accounting, `session/load` resume, `session/cancel` interrupt, `compact` context).
- `app/runtime_registry.py`, `app/models.py` — register `grok` runtime + `grok-4.5` model + $2/$6/$0.50
  pricing + 500K window.
- `app/runtime_env.py` — already provides `MCP_STDIO_CMD` / `MCP_BASE_ENV` (reuse; maybe a Grok MCP-config
  translator since Grok wants ACP `mcpServers:[{name,type:"stdio",command,args,env:[{name,value}]}]`, a
  different shape than Codex's dotted `-c mcp_servers.*` overrides).
- `app/session.py` — backend selection by runtime; understand the two turn-end signals.
- Instruction mirror: a slim `AGENTS.md` (<10K chars) generator for Grok workers (analog of the Codex
  `AGENTS.md` mirror), because CLAUDE.md is truncated at 10K.
- `pipeline.yaml` / model routing — decide whether Grok gets a role (see Celesообразность).

## Risks / edge cases

1. ~~**10K-char instruction cap**~~ — REFUTED by measurement; no mitigation needed. (F5)
1b. **Mid-turn sends do NOT steer — they queue.** A second `session/prompt` during a live turn is accepted
   into a native queue (`_x.ai/queue/changed`) and runs as its **own** turn afterwards; both returned
   `stopReason=end_turn` with distinct `promptId`s. So `mid_turn_inject=False`, and **N sends ⇒ N turn_ends**.
   The session layer must not tear down its listener on the first `prompt_complete` while the queue is
   non-empty, or the queued turn streams into nobody. (measured)
2. **MCP env leak** — Grok auto-loads global `~/.claude` MCP servers and echoes their secrets; must isolate
   worker MCP set (clean env / `GROK_HOME`). (F4)
3. **Cost unit is 1e-10, and cached rate is $0.30/M** — hardcoding 1e-9 or the articles' $0.50 silently
   mis-bills every Grok turn (9.7× and 3% respectively). Pin both with a regression test using the three
   measured turns in F7. (F7)
4. **Terminal quota shape unknown** — must be observed empirically, not guessed. (F7)
5. **Double turn-end signal** — emit one `turn_end`. (F3 counter-evidence)
6. **`use_tool` meta-layer** — event mapper must unwrap `use_tool`→`orchestra__<tool>`. (F4)
7. **cwd-scoped resume** — `session/load` needs the original worktree cwd; if a worktree is relocated,
   resume key breaks (same class as Codex thread-cwd coupling).
8. **Proxy** — `grok agent stdio` inherits `HTTPS_PROXY` from env (verified working via 12343); the shell
   `grok` function reloads .env, but the backend must pass `HTTPS_PROXY` explicitly like Codex's `_build_env`.
   `web_fetch` has its own `GROK_WEB_FETCH_PROXY` / `[toolset.web_fetch] proxy_endpoint`.

---

## Целесообразность (honest, no enthusiasm)

**Is a third runtime worth it?** The integration is technically **cheap and low-risk** — Grok's ACP is a
near-clone of the Codex app-server we already wrap; `backend_grok.py` is mostly a re-parameterization of
`backend_codex.py`. No architectural change. So the cost side of the ledger is small.

**The value is exactly the stated argument: a separate quota pool.** Grok runs on SuperGrok, an entirely
independent subscription from the Claude Max pool and the Codex pool. Today Codex is "выбран до 2 августа,
28 сессий стоят" — a hard bottleneck. A third pool is real parallel capacity, not a quality play.
grok-4.5 is a credible frontier coding model (public benchmarks position it near Opus 4.8 / GPT-5.5 at ~60%
lower API price), so it is *usable* for real worker tasks, not just a toy.

**What would make it stillborn — and none of it happened:** no persistent process (H1) or no MCP (H2) would
kill it. Both are present and proven end-to-end.

**Honest downsides:** (a) 10K instruction cap is stricter than Codex — needs the slim-AGENTS.md work;
(b) quota-exhaustion handling is unproven and needs an empirical pass before Grok can be trusted unattended;
(c) it's a third code path to maintain (backends now 3× for every protocol change to message delivery /
sessions / usage). (c) is the only durable cost. (The "opaque cost telemetry" downside I listed in the first
draft is retracted — cost telemetry turned out to be exact, and *better* than Codex's.)

**Sharpening the quota argument with a number:** this research round itself was blocked from external review
because **Codex hit its usage limit** (see §Review status) — the exact failure mode the third pool is meant
to absorb. That is one concrete, dated data point, not a projection.

**Recommendation:** ВСТРАИВАЕТСЯ. The quota-pool argument is sound and the integration is a bounded,
Codex-shaped effort. Proceed to Phase 2, with the slim-AGENTS.md and the empirical quota-probe explicitly
scoped as tickets.

---

## Review status — NO EXTERNAL VERDICT

**Codex cross-review did not run.** `codex_review` (bg job `bg-ec3891396d`, mode=exec on this file) failed
terminally:

```
{"type":"error","message":"You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage
 to purchase more credits or try again at Aug 2nd, 2026 11:57 AM."}
{"type":"turn.failed", ...}
```

Per the project grail ("три одинаковых инфраструктурных падения → стоп, честная запись «вердикта нет»"), I am
**not** claiming external validation. There is no second-LLM verdict on this research. Retry is possible
after **2026-08-02**, or on another reviewer model if the orchestrator prefers.

**Self-review performed in its place**, targeting the load-bearing claims. It was not ceremonial — it
overturned one of my own findings:

| Claim | Self-review outcome |
|---|---|
| F7 "costUsdTicks unreliable, 9.7× gap" | **RETRACTED — I was wrong.** Unit is 1e-10, not 1e-9. Reconciles exactly (n=3, delta 0.0000). Also surfaced the true $0.30/M cached rate and that `reasoningTokens ⊆ outputTokens`. |
| F1 persistent stdio process | Holds. Directly measured ACP handshake; not inferred from articles. |
| F4 MCP works | Holds. Not just "server ready" — the model actually *invoked* `orchestra__list_agents` to completion. Initial failure was root-caused to my own launch command (`-m` without PYTHONPATH), not a Grok limitation. |
| F2 resume across restart | Holds. Falsifiable test used (recall of prior-process content), not just "load returned ok". |
| F3 two turn-end signals | Holds, and remains the top implementation risk (double `turn_end`). Ordering measured: `prompt_complete` notification *precedes* the `session/prompt` result. |
| F5 10K cap | Holds (primary README + live `inspect`). Project CLAUDE.md measured at 28580 bytes → will truncate. |
| F7 quota-exhaustion shape | Still **UNCERTAIN**. Unchanged — could not force-exhaust SuperGrok. Must be probed empirically, not guessed. |

**Lesson worth keeping:** a suspiciously round discrepancy (9.7× ≈ 10×) is a unit bug in my own arithmetic
until proven otherwise. My first draft would have shipped a wrong "don't trust the runtime" conclusion and
a 3%-wrong cached rate copied from articles.

## Sources (fetched/observed this session)

1. `grok --help`, `grok agent --help`, `grok agent stdio/serve --help`, `grok mcp add --help` — live CLI.
2. `grok agent stdio` ACP handshake + full 76-event session dump — live (attached `event-dump.json`).
3. `session/load` resume experiment (recalled "PONG") — live.
4. Orchestra `app/mcp_stdio.py` over ACP: `mcpToolCount=38`, `orchestra__list_agents` call — live.
5. `grok inspect` — CLAUDE.md + AGENTS.md + 65 skills discovery — live.
6. `~/.grok/README.md` (bundled, v0.2.112): §AGENTS.md (10K cap), §Sandbox, §"ACP Protocol Reference",
   §"Agent stdio (ACP)", §Configuration, §Environment Variables.
7. `~/.grok/models_cache.json`, `~/.grok/config.toml`, `~/.grok/sessions/**` — live filesystem.
8. `app/backend_codex.py`, `app/backend_protocol.py`, `app/runtime_env.py` — repo (contract to satisfy).
9. grok-4.5 pricing: apidog.com/blog/grok-4-5-pricing, openrouter.ai/x-ai/grok-4.5, felloai.com/grok-pricing,
   spheron.network (all 2026-07) — $2/$6/M, 500K ctx. NB: these sources say cached $0.50; **runtime
   arithmetic proves $0.30** (F7) — secondary sources superseded by measurement on this point.
10. [Agent Client Protocol](https://agentclientprotocol.com) — protocol identity (README-referenced).
11. Runtime cost reconciliation across 3 turns (`turn_completed.usage`) — live; the basis for F7.
12. Failed `codex_review` bg job `bg-ec3891396d` (usage limit until 2026-08-02) — see §Review status.
