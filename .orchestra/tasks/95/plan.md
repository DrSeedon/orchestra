# Task #95 — Grok Build runtime — PLAN (Phase 2, no code)

Basis: `docs/tasks/95/research.md` (Phase 1 + Phase-2 corrections). Every design choice below is anchored to
a measurement, not to vendor docs — twice this task the docs were wrong (cached rate, instruction cap).

**Read before planning, as instructed:** `app/models.py` @ `90747c7`, `app/runtime_registry.py`,
`app/backend_codex.py`, `app/backend_opencode.py`, `app/backend_claude.py`, `app/session.py`,
`app/workspace.py`, `app/runtime_env.py`, `app/backend_protocol.py`.

---

## 0. Two Phase-2 measurements that changed the plan

**(a) The 10K instruction cap does not exist.** A 62 077-char `AGENTS.md` was read in full via headless *and*
ACP; no truncation, no warning. Our CLAUDE.md is 19 252 chars → passes whole.
**→ Ticket "slim AGENTS.md generator" is DELETED.** Existing `workspace.sync_agents_md` is reused unchanged.
No section-priority decision to escalate — the question is moot. (This was your item 2; the answer is
"nothing to do", which I'd rather report than invent work to fill the ticket.)

**(b) Grok is not a fourth runtime — it's a fourth, and `opencode` already exists.** `BUILTIN_RUNTIMES =
("claude", "codex", "opencode")`. This matters for your item 4, below, and for a registration trap:
`_infer_backend()` routes anything not `gpt-*`/`claude-*` to **`opencode`**. An unregistered `grok-4.5`
silently becomes an OpenCode session. Registration must be explicit, and a test must pin it.

---

## 1. Answer to item 4 — do we abstract? **No. Measured, not felt.**

I classified every method of `backend_codex.py` (1105 method-lines):

| bucket | methods | lines | share |
|---|---|---|---|
| generic JSON-RPC-over-stdio transport (`_request/_notify/_write/_read_stdout/_drain_stderr/_build_env/connect/disconnect/interrupt`) | 9 | 220 | **20%** |
| Codex-specific event vocabulary (`_convert_notification` 181, `_item_completed` 172, `_item_started` 72, `_turn_completed` 58, `_collab_events` 48, MCP/TOML/rollout helpers…) | 18 | 826 | **75%** |

Grok's event vocabulary shares **nothing** with Codex's: Codex speaks `item/started`, `item/completed`,
`turn/completed`, `collabAgentToolCall`; Grok speaks `session/update{agent_message_chunk, agent_thought_chunk,
tool_call, tool_call_update}` + `_x.ai/*`. Divergence ≈ **80%**, far past your 30% threshold.

**Corroborating precedent:** the project already answered this question. `backend_opencode.py` (632 lines)
imports **nothing** from `backend_codex.py` — verified by grep. Three backends share exactly one thing: the
16-line `BackendLike` Protocol. That is the established, working pattern and it matches
"3 строки > абстракция" / "Один способ".

**Decision:** `backend_grok.py` standalone. Duplicate the ~220 lines of JSON-RPC plumbing. Do **not** extract
a shared JSON-RPC base class — it would have to serve two incompatible event vocabularies, which is exactly
the premature factory the project rules warn about. Revisit only if a *fifth* stdio-JSON-RPC runtime appears.

---

## 2. Ticket order — vertical slices

Each slice is independently testable and mergeable. T1 delivers a working minimum; nothing after it is
required for T1 to be useful.

### T1 — Minimum viable Grok worker: connect + one turn + MCP
**Goal:** a Grok worker can be spawned, take one turn, call an Orchestra MCP tool, and report DONE.

- `app/backend_grok.py` — new `GrokBackend`:
  - `connect()` → spawn `grok agent stdio` (cwd = worktree, `limit=16MB` per the Codex StreamReader grail),
    `initialize` → `session/new{cwd, mcpServers}` (or `session/load` when resuming, T3).
  - `send()` → `session/prompt`. **Fire, do not await** — the request future resolves only at turn end;
    awaiting it inside `send()` would deadlock the session layer.
  - `events()` → drain notifications, map per the table in research F3, terminate on
    `_x.ai/session/prompt_complete`.
  - `disconnect()`, `session_id` property.
  - System prompt: ACP has no `developerInstructions` equivalent → pass via `--rules` / agent profile;
    **verify which one actually lands** before relying on it (unverified today, see Risks R4).
- `app/runtime_registry.py` — `_grok_factory` + `register_runtime("grok", …)`, add to `BUILTIN_RUNTIMES`.
  Capabilities (all measured): `event_stream="per_turn"`, `mid_turn_inject=False`, `reconnect=False`,
  `hibernate=False`, `process_liveness=True`, `resume=True`, `resume_across_models=False`.
- `app/models.py` — `register_model(ModelSpec(id="grok-4.5", name="Grok 4.5", runtime="grok",
  provider="x-ai", context_length=500000, …))`, alias `grok` → `grok-4.5`.
- **Tests:** backend maps a recorded event fixture → expected `AgentEvent`s (reuse
  `docs/tasks/95/event-dump.json`); `backend_for_model("grok-4.5") == "grok"` (pins the `_infer_backend`
  → opencode trap); registry builds a `BackendLike`.
- **Manual gate:** spawn one real Grok worker, have it call `update_progress` + `send_message`, merge.

### T2 — MCP isolation (your item 1 — treated as a contract, not cosmetics)
**Problem, measured:** Grok auto-loads MCP servers from `~/.claude.json` / `.mcp.json` and broadcast a real
`OPENROUTER_API_KEY` in `_x.ai/mcp/servers_updated`. A worker would start with third-party tools and
third-party secrets.

**Contract:** a Grok worker's MCP set is **exactly** `{orchestra} ∪ scope ∪ (user if role.mcp_servers=="all")`
— the same composition `_claude_factory` already builds via `_load_scope_mcp_servers` /
`_load_user_mcp_servers` (both already exclude the `orchestra` key). Nothing is inherited implicitly.

- Reuse those two loaders in `_grok_factory` (do not write new ones — one way to do a thing).
- Pass the composed set explicitly in `session/new{mcpServers:[…]}`, translated to ACP shape
  `{name, type:"stdio", command, args, env:[{name,value}]}` — note ACP wants env as a **list of pairs**,
  not a dict; this is where a silent mistranslation would hide.
- Launch the Orchestra server with `runtime_env.MCP_STDIO_CMD` + `MCP_BASE_ENV` **verbatim** (absolute
  script path + `PYTHONPATH`). My Phase-1 failure was `-m app.mcp_stdio` without PYTHONPATH — ACP starts the
  MCP subprocess in the *session* cwd, not the repo.
- **Suppress implicit discovery.** `GROK_HOME` is the candidate lever, but per your instruction I checked it
  rather than assuming: `GROK_HOME` relocates the **whole** config dir — which also holds `auth.json` and
  `sessions/`. Pointing it at a scratch dir would break authentication and move the session store, i.e. break
  T3 resume. **So `GROK_HOME` is rejected as the isolation mechanism.** Investigate in this order instead:
  (1) project-scope `.grok/config.toml` in the worktree overriding `mcp_servers`; (2) whether an explicit
  `session/new.mcpServers` *replaces* rather than *merges* with discovered ones — **measure both**, don't
  infer. Fallback if neither suppresses discovery: fail loud at connect with a listing of unexpected servers,
  rather than silently running a worker with foreign tools.
- **Tests:** given a scope with a foreign `.mcp.json`, the composed set contains exactly the expected names;
  a regression test asserts no env value from outside our composition reaches the ACP payload.
- **Out of scope but must be raised:** the leaked `OPENROUTER_API_KEY` is real and now in a committed event
  dump — flagged to you separately for rotation. I did not rotate it myself.

### T3 — Resume across restart
- `session/load{sessionId, cwd}` when `resume_session_id` is set; persist `sessionId` exactly like the Codex
  thread id. Resume key is **(cwd, sessionId)** — a relocated worktree breaks it (same class as the Codex
  cwd coupling; see the #90 grail about judging worktree identity by git, not by path).
- Fallback: if `session/load` errors, start fresh and emit a loud `warning` event — never silently drop
  history.
- **Tests:** load path is chosen when an id exists; failure falls back and warns. Manual: restart Orchestra,
  confirm the worker keeps context.

### T4 — Usage, cost, context
- Consume `turn_completed.usage`: `inputTokens`, `cachedReadTokens`, `outputTokens`, `totalTokens`.
- Cost: `costUsdTicks * 1e-10`. **Independently double-confirmed** in Phase 2 — headless JSON emitted both
  `total_cost_usd: 0.0440884` and `total_cost_usd_ticks: 440884000` for the same turn (ratio exactly 1e-10).
  Keep the token formula `((in-cached)*2 + cached*0.30 + out*6)/1e6` as a cross-check.
- Prices live in `backend_grok.py`, **not** `models.py` — following the existing comment there ("Codex models
  intentionally absent — their prices live in backend_codex.py"), because `TOKEN_PRICES` has no `cached` tier
  and Grok needs one. Do not widen `TOKEN_PRICES` for a single consumer.
- Context: `context_pct = totalTokens / 500000`, live from `_meta.totalTokens` on every chunk — no rollout
  scraping needed, unlike Codex.
- **Tests:** the three measured turns from research F7 as fixtures, asserting zero residual (pins both the
  1e-10 unit and the $0.30 cached rate — the two numbers that would silently mis-bill every turn).

### T5 — Errors, quota, fail-loud (your item 3)
- **No text matching on the stream.** Classify in the error path only, mirroring
  `CodexBackend._classify_error` — structured `error` objects from ACP, plus non-`end_turn` `stopReason`.
- **Empirically unverified today** (could not exhaust SuperGrok). Until observed, the rule is: any
  unrecognised terminal error ⇒ `model_error="error"`, emit `error` + `turn_end(ok=False)`, `report_bug()`,
  stop. **No silent retry, no creative workaround** — per Agent Determinism.
- **How we will verify:** capture-first. Log the full raw error payload verbatim on every failed turn, so the
  first real quota hit gives us the true shape instead of a guess. Only then add a `rate_limit`
  classification. Ticket stays open with an explicit "shape unknown" note rather than shipping a fabricated
  pattern.
- Also handle: `_process/exited` equivalent (process death) and server→client `session/request_permission`
  (auto-allow, since workers run `--always-approve`; an unexpected one should fail loud, as Codex does).

### T6 — Dashboard + TG surface
- Palette entry for the `grok` runtime and provider `x-ai`; short TG name `grok`.
- Per the dashboard grail: find the **second** copy of any status/colour mapping before adding one — status
  dictionaries have been duplicated (`renderAgentItem` vs tabs) and drifted.
- Model cost uses fixed `MODEL_COST_CURRENCY='$'`, never `data-currency` (that's for task prices).

### T7 — Docs
- `CHANGELOG.md` (Added, new runtime), `architecture.md` if it exists, and a Грабли entry for the two
  documentation-vs-runtime burns. TODO.md updated: remove nothing that isn't done.

---

## 3. Risks (with the check that retires each)

| # | Risk | Retired by |
|---|---|---|
| R1 | **Queue ⇒ N turn_ends.** Mid-turn sends queue natively and each runs as its own turn. If `events()` returns on the first `prompt_complete` while the queue is non-empty, the queued turn streams to nobody. | T1: drive the loop off queue state (`_x.ai/queue/changed` reports `entries` + `runningPromptId`), not off the first completion. Test with two rapid sends. |
| R2 | **Double `turn_end`** — both the `session/prompt` *result* and `prompt_complete` mark the same turn end. | T1: emit exactly one, keyed by `promptId`; idempotence test. |
| R3 | **`_infer_backend` silently routes `grok-4.5` → `opencode`** if registration regresses. | T1 test asserting `backend_for_model("grok-4.5") == "grok"`. |
| R4 | **System prompt delivery unverified.** ACP `session/new` has no `developerInstructions`; `--rules` / agent profile is the presumed path but I have not proven our prompt lands. | T1 first task: prove it with a canary instruction, before anything depends on it. |
| R5 | **`session/cancel` unverified.** My probe sent it after the turns had already completed, so I observed nothing. `interrupt()` correctness is unproven. | T1/T5: cancel a long turn and assert it actually stops. Report honestly if it doesn't. |
| R6 | **MCP discovery may not be suppressible** (T2). | T2: measure replace-vs-merge; if unsuppressible, fail loud rather than ship leaky workers. |
| R7 | **Quota shape unknown.** | T5 capture-first; no invented pattern. |
| R8 | `AGENTS.md` mirror is shared with Codex workers in a worktree that switches runtime (`runtime_handoff`). Content is identical for both (byte mirror), so this is benign today — noted so it isn't rediscovered. | none needed; documented. |

## 4. Explicitly NOT doing
- No shared JSON-RPC abstraction (§1, measured).
- No slim-AGENTS.md generator (§0a, refuted).
- No `GROK_HOME` isolation (breaks auth + session store).
- No subagent/`deep-research`/`workflow`/`goal` plumbing — Grok ships these, we don't need them for a
  worker, and each is a determinism fork. `--no-subagents` for managed workers, matching the Codex
  `features.multi_agent=false` precedent for orchestrators.
- No rotation of the leaked API key without your say-so.

## 5. Decision I need from you
Only one, and it is not the AGENTS.md one (that evaporated):
**Does Grok get a pipeline role now, or land as registry-only first?** T1–T7 make the runtime *available*;
routing real work to it (`pipeline.yaml`) is a separate call about quota strategy, and per the Pricing rules
quota is a first-order factor, not my call to make silently.

## 6. Review status
No Codex cross-review — pool is dead until 2026-08-02, as you noted. This plan carries self-review only.
