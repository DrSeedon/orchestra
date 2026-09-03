# Research #96 — OpenCodeBackend

**Goal:** create `app/backend_opencode.py` — a third `BackendLike` backend wrapping the OpenCode daemon, with full `AgentEvent` parity to `ClaudeBackend`/`CodexBackend`.

> NOTE: the task brief references `docs/research/RESEARCH-OPENCODE.md` as "all experiments verified". **That file does not exist in this worktree** (never committed to `task-96`). So this research re-derives everything from first principles by probing the actually-installed binary and SDK. All facts below are verified against:
> - `opencode` binary **v1.17.6** (`/home/maxim/.npm-global/bin/opencode`)
> - Python SDK **`opencode-ai 0.1.0a36`** (on PyPI, downloaded + wheel extracted/inspected)

---

## 1. The seam — what a backend must satisfy

`app/backend_protocol.py` — structural `Protocol`:

```python
class BackendLike(Protocol):
    @property
    def session_id(self) -> Optional[str]: ...
    async def connect(self) -> None: ...
    async def send(self, message: str) -> None: ...
    async def events(self) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...
```

`app/events.py` — `AgentEvent(type, content, metadata)`. Event `type` values the session loop reacts to:
`text`, `thinking`, `tool_use`, `tool_result`, `file_change`, `turn_end`, `error`, `status`,
(+ `subagent_*` — Claude-only, OpenCode has no equivalent stream, skip).

### How `session.py` drives a backend (the contract that actually matters)
- `_make_backend()` (session.py:199) branches on `self.backend_type` (`"codex"` / else claude).
  **→ Phase 2 will add a `"opencode"` branch here + register in `app/models.py` `BACKENDS`.**
  (Phase 1 = the backend class only; wiring is a follow-up step but documented here so the class shape is right.)
- Listen loop consumes `async for event in backend.events()` (session.py:640). One `events()` call
  must drain exactly one turn and **terminate after `turn_end`** (same as Codex — the async generator
  returns when the turn is done, the loop re-arms on the next `send`).
- `send()` may be called **mid-turn** (session.py:286) for inject. ClaudeBackend supports it; Codex
  queues instead (`backend_type == "codex"` special-case at session.py:279). **OpenCode: the daemon is
  persistent and accepts new messages, BUT a clean MVP mirrors Codex — queue mid-turn, one turn per
  `chat()`.** Decision deferred to plan; the safe default is Codex-style (no mid-turn inject).
- `turn_end` metadata fields consumed downstream (CostTracker / TurnManager / dashboard). Required keys
  (cf. backend_codex.py:165-180): `session_id, ok, stop_reason, cost_usd, cost_usd_cached, context_pct,
  context_tokens, max_tokens, cache_hit, cache_read, cache_create, input_tokens, output_tokens`.

### `backend_type` plumbing (already exists, Codex paved this road)
- DB column `backend_type TEXT DEFAULT 'claude'` (db.py:262).
- `backend_for_model(model)` → `BACKENDS.get(model, "claude")` (models.py:260).
- hibernate guards check `s.backend_type != "claude"` (session_hibernate.py:33) — OpenCode, being a
  managed daemon, behaves like Codex here (non-claude). Worth a flag review in Phase 2.

---

## 2. OpenCode architecture (verified)

`opencode serve --port N --hostname 127.0.0.1` → headless HTTP server + global SSE event bus.
- Port `0` = auto-pick; we must pass an explicit free port (register in `~/ports.md`, 1808x range).
- One daemon can host **many sessions** (SQLite-persistent, survive restart — "kill-proof, no cold start").
- **Architectural decision for Phase 2:** one shared daemon for all OpenCode workers, or one daemon per
  backend instance? MVP-simplest = **one daemon per backend instance** (matches Claude's "one client per
  session" principle, no shared-port contention, trivial lifecycle). Documented as the recommended path.

### Python SDK surface (`opencode-ai 0.1.0a36`, async client `AsyncOpencode`)
Client resources: `session`, `event`, `app`, `find`, `file`, `config`, `tui`.
Base URL via `base_url=` ctor arg or `OPENCODE_BASE_URL` env (default `http://localhost:54321`).

Key calls:
- `await client.session.create()` → `Session` (has `.id`). **This is our `session_id`.**
- `await client.session.chat(id, *, model_id, provider_id, parts=[{type:"text", text:msg}], system=, tools=)`
  → returns the **final `AssistantMessage`** (blocking — resolves when the turn completes).
  - `model_id` / `provider_id` are split: model format is `provider/model` (e.g. `anthropic/claude-...`).
  - `AssistantMessage` carries: `cost: float`, `tokens: {input, output, reasoning, cache:{read,write}}`,
    `error: Optional`, `id`, `time:{created,completed}`. **← native cost/token source.**
- `await client.session.abort(id)` → interrupt the running turn.
- `await client.session.delete(id)` → cleanup.
- `await client.event.list()` → `AsyncStream[EventListResponse]` — the **global SSE bus** (all sessions).

### The streaming model (CRITICAL — different from both Claude and Codex)
- `chat()` is **request/response** (returns only the final message). It does NOT stream.
- Live streaming = the **separate global `event.list()` SSE stream**, NOT scoped to a session.
- Therefore the backend pattern is:
  1. On `connect()`: start daemon, create SDK client, **open one persistent `event.list()` stream**,
     create a session.
  2. On `send()`: fire `session.chat(...)` (as a background task — it blocks until turn end).
  3. In `events()`: read from the SSE stream, **filter by our `sessionID`**, map to `AgentEvent`,
     and stop when we see `session.idle` for our session (turn boundary) — then synthesize `turn_end`
     from the `AssistantMessage` that `chat()` returned (await the chat task to get cost/tokens).

  → Need an `asyncio.Queue` or "await both" coordination: the SSE stream gives incremental parts;
    the awaited `chat()` future gives the authoritative final cost/tokens. `session.idle` is the
    turn-end signal. **This dual-source coordination is the main complexity of this backend.**

---

## 3. Event → AgentEvent mapping (verified against `EventListResponse` union)

The SSE bus emits a discriminated union (`type` field). Relevant members:

| OpenCode event (`type`)   | Payload                                  | → AgentEvent |
|---------------------------|------------------------------------------|--------------|
| `message.part.updated`    | `properties.part: Part` (see below)      | depends on part type |
| `message.updated`         | `properties.info: Message` (assistant)   | accumulate cost/tokens (final state) |
| `session.idle`            | `properties.sessionID`                   | **turn boundary** → emit `turn_end` |
| `session.error`           | `properties.error`, `sessionID`          | `error` |
| `file.edited`             | `properties.file`                        | `file_change` |
| `permission.updated`      | permission request                       | (auto-allowed via config; log as `status`) |
| `server.connected`        | —                                        | `status` (daemon ready) |
| `lsp.client.diagnostics`  | —                                        | ignore |
| `installation.updated`, `storage.write`, `file.watcher.updated`, `ide.installed` | — | ignore |

### `Part` union (`message.part.updated` → `properties.part`)
discriminated on `type`: `TextPart | FilePart | ToolPart | StepStartPart | StepFinishPart | SnapshotPart | PatchPart`.

- **`TextPart`** `{type:"text", text, synthetic?, time}` → `AgentEvent("text", text)`.
  (Skip `synthetic: true` parts — internal.)
- **`ToolPart`** `{type:"tool", tool, callID, state}` where `state` ∈
  `pending | running | completed | error`:
  - `running`/`pending` first seen → `AgentEvent("tool_use", f"{tool}: {json(input)}", metadata={tool_name, short_name})`.
  - `completed` `{input, output, title}` → `AgentEvent("tool_result", output)`.
  - `error` `{input, error}` → `AgentEvent("tool_result", error)` or `AgentEvent("error", error)`.
  - **Dedup needed:** a tool emits multiple `part.updated` as it transitions pending→running→completed.
    Track seen `callID` to emit `tool_use` once and `tool_result` once.
  - Tool namespacing: MCP tools surface as `{server}_{tool}` (e.g. `orchestra_spawn_worker`).
    `short_name` = strip server prefix for display (mirror Claude's `split('__')[-1]` idea).
- **`StepStartPart` / `StepFinishPart`** — agent reasoning step boundaries. `step_finish_part` may carry
  reasoning/token deltas. **There is NO dedicated `reasoning`/`thinking` Part type in this SDK version.**
  → `thinking` events likely unavailable from OpenCode (or only via step parts if they carry text).
  MVP: skip `thinking` mapping; note as a known parity gap. (Claude has `ThinkingBlock`; OpenCode doesn't expose one cleanly.)
- **`FilePart`** — file attachment in a message; not a file edit. Edits come via `file.edited` event.
- **`SnapshotPart` / `PatchPart`** — VCS snapshots/patches; ignore for event mapping (or `status`).

### `turn_end` synthesis (on `session.idle` for our session)
Await the `chat()` future → `AssistantMessage`. Build metadata:
- `cost_usd` = `msg.cost` (native OpenCode pricing — **use directly**, unlike Claude where SDK hardcodes rates).
- `input_tokens` = `msg.tokens.input`, `output_tokens` = `msg.tokens.output`.
- `cache_read` = `msg.tokens.cache.read`, `cache_create` = `msg.tokens.cache.write`.
- `cache_hit` = `int(cache_read*100/(cache_read+cache_create))` if any.
- `max_tokens` = context limit for model (need an OPENCODE_CONTEXT_LIMITS map, like Codex has).
- `context_pct` = `int(input_tokens*100/max_tokens)`.
- `cost_usd_cached` = `cost_usd` (OpenCode already accounts caching; mirror Codex which sets them equal).
- `ok` = `msg.error is None`, `stop_reason` = `"end_turn"` (or error name).
- `session_id` = our session id.

**Edge case (mirror Codex backend_codex.py:199):** if the daemon dies / chat raises before `session.idle`,
synthesize an error `turn_end` (`ok:False, stop_reason:"process_exit"/exception`) so session.py re-arms.

---

## 4. MCP injection (Orchestra stdio server)

Current Orchestra MCP config (manager.py:289, runtime_env.py):
```python
{"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": {...}, "alwaysLoad": True}}
# MCP_STDIO_CMD = [sys.executable, app/mcp_stdio.py]
# env: PYTHONPATH, HTTPS_PROXY, INTERNAL_TOKEN, ORCHESTRA_URL/SCOPE/ROLE, WORKER_NAME
```

OpenCode wants `McpLocalConfig` (verified shape):
```json
{ "type": "local", "command": ["<python>", "app/mcp_stdio.py"], "environment": {...}, "enabled": true }
```
→ translation: Claude's `{command, args, env}` becomes OpenCode's `{type:"local", command:[command,*args], environment:env, enabled:true}`.

**Where to put it:** OpenCode reads config from `opencode.json` (or `opencode.jsonc`) **in the cwd** (the
worktree), plus a global `~/.config/opencode/`. The backend should **write an `opencode.json` into the
worktree `cwd`** before launching the daemon, containing `mcp`, `permission`, `model`, `provider`.
(The SDK `config.get()` is read-only — there is no config-set API. Config = files.)

---

## 5. Permissions (from task brief — must verify in Phase 2)

OpenCode config `permission` block (NOT in the SDK's typed `Config` model — it's an extra/loose field,
opencode's own JSON schema supports it). Task brief says set these to `allow`:
`edit`, `bash`, `webfetch`, `external_directory`, `doom_loop`.

```json
"permission": { "edit": "allow", "bash": "allow", "webfetch": "allow" }
```
Exact key names + the `external_directory`/`doom_loop` keys must be confirmed against
`opencode` v1.17.6's config schema during planning (the brief asserts them but the missing RESEARCH doc
means we re-verify). Risk: schema drift between brief and installed version.

---

## 6. Files affected

**New:** `app/backend_opencode.py` (the deliverable).
**Phase-2 wiring (NOT this phase, listed for completeness):**
- `app/session.py:199` `_make_backend()` — add `opencode` branch.
- `app/models.py` — `BACKENDS`, `CONTEXT_LIMITS`, optionally `ALIASES`/`MODELS` for opencode model ids;
  add `OPENCODE_CONTEXT_LIMITS` (or reuse models.py CONTEXT_LIMITS).
- `pyproject.toml` — add `opencode-ai>=0.1.0a36` dependency.
- `~/ports.md` — register the daemon port(s).
- possibly `session_hibernate.py` flags review.

**Pricing:** OpenCode reports native `cost` in `AssistantMessage` → no TOKEN_PRICES table needed for
opencode models (unlike Claude/Codex). This is a genuine simplification.

---

## 7. Risks & edge cases

1. **Dual-source turn coordination** (SSE stream + awaited `chat()` future) is the core complexity.
   `session.idle` is the turn boundary; cost/tokens come from the chat return. Must not deadlock if one
   arrives before the other. Plan: run `chat()` as a task, drain SSE in `events()`, on `session.idle`
   (our session) await the chat task (with timeout) for final metadata.
2. **Global event bus, not session-scoped** — MUST filter every event by `sessionID == our session`.
   Otherwise events from sibling OpenCode workers leak in (if a daemon is shared).
3. **Tool part dedup** — pending→running→completed emits multiple `part.updated`; track `callID`.
4. **No `thinking` parity** — OpenCode (this SDK version) has no reasoning Part type. Known gap.
5. **No mid-turn inject in MVP** — mirror Codex (queue in session.py). Mid-turn inject possible later
   (daemon is persistent) but adds streaming-interleave complexity. Keep MVP simple.
6. **Daemon lifecycle** — must start `opencode serve` subprocess, wait for `server.connected` / port-ready
   before first SDK call, terminate on `disconnect()`. Port allocation (auto vs fixed). Zombie daemons on
   crash — `disconnect()` must `terminate()`+`kill()` like Codex's `_proc` handling.
7. **`provider_id`/`model_id` split** — OpenCode needs `provider/model`. Orchestra passes a single
   `model` string; backend must split (`anthropic/claude-...` → provider=`anthropic`, model=`claude-...`),
   or the model id is passed pre-split. Decide mapping in Phase 2.
8. **Permission schema drift** — brief's permission keys vs installed v1.17.6 schema. Verify.
9. **Config-as-files** — no config-set API; write `opencode.json` to worktree. Must not clobber a
   user-authored `opencode.json` if present (merge or own-file strategy).

---

## 8. External references
- SDK source inspected locally: `opencode-ai 0.1.0a36` wheel — `resources/session.py`, `resources/event.py`,
  `types/event_list_response.py`, `types/part.py`, `types/tool_part.py`, `types/assistant_message.py`,
  `types/config.py`, `types/mcp_local_config.py`.
- Binary: `opencode serve --help` (v1.17.6) — `--port`, `--hostname`, `--cors`, `--log-level`.
- Pattern reference in-repo: `app/backend_codex.py` (one-turn-per-send, error turn_end synthesis,
  stderr drain, subprocess lifecycle) — closest analog to OpenCode's shape.

---

## Recommendation
Proceed to Phase 2 (plan). The backend is **Codex-shaped** (managed subprocess, one turn per send, native
cost) but with a **Claude-shaped streaming richness** (parts → text/tool events) delivered over a
**separate global SSE bus** rather than inline. The single hardest design decision is the dual-source turn
coordination (§7.1); everything else is mechanical mapping. Native pricing + persistent sessions are real
wins over the other two backends.
