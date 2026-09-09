# Context Management in Claude Code CLI / Agent SDK / Orchestra — Full Map

**Date:** 2026-05-31
**Author:** research-context-full (worker)
**Status:** Research complete. Research-only — no code changed.
**SDK:** claude-agent-sdk 0.1.72 · bundled CLI 2.1.150
**Supersedes parts of:** `docs/research-context-bug.md` (RC1–RC6). That doc's proposed Fix A/D
have since *partially landed*; this doc verifies what's live, what's still broken, and adds
the missing root cause the previous research did not have transcript evidence for.

---

## TL;DR (the one thing that matters)

Orchestra tells the dashboard "1,000,000-token window" for every `[1m]` Opus worker, but the
worker's CLI is **actually running at a 200K window** and silently autocompacting at ~167K.
Two numbers, two owners, never reconciled →

- Orchestra's `context_pct` = `tokens / 1,000,000` → shows **~17%** when the CLI is at **~95%**.
- The CLI then fires its **own** autocompaction (`trigger:"auto"`, 374K→8K), summarizing the
  transcript. Orchestra never parses that event, so there's **no compact entry in our logs**.
- Operator sees: "context was huge, then dropped to nothing, and nobody compacted." Exactly the
  reported symptom. It is **real content loss** (CLI summarized), made invisible by a **wrong
  denominator**.

**Proof** (from a live Orchestra transcript, `claude-opus-4-6`, 2026-05-28):

```
compact_boundary  trigger=auto  preTokens=374787  postTokens=8778
compact_boundary  trigger=auto  preTokens=167562  postTokens=5119
compact_boundary  trigger=auto  preTokens=174977  postTokens=10544
... 8 more, all preTokens ≈ 167000–175000
```

The CLI compacts at ~167K every time — **not** near 1M. The 1M window is **never enabled**.

---

## Part 1 — Claude Code CLI: how it actually manages context

### 1.1 Where the transcript lives (physical)

- Per-project dir: `~/.claude/projects/<slugified-cwd>/<session-uuid>.jsonl`
  (e.g. `~/.claude/projects/-mnt-data-Projects-Python-orchestra/3f463fa3-….jsonl`).
- One JSONL line = one event. Top-level `type` values observed:
  `assistant`, `user`, `system`, `attachment`, `file-history-snapshot`, `ai-title`,
  `last-prompt`.
- `~/.claude/history.jsonl` is a separate global prompt history, **not** the per-session
  transcript.
- Resume reads this `.jsonl` back; the SDK can also materialize a temp JSONL to resume from
  (`types.py:1296` `SessionLoader.load(...)` docstring).

### 1.2 How the CLI represents compaction (verified from a real transcript)

When the CLI autocompacts it writes a **`system` / `subtype:"compact_boundary"`** line carrying:

```json
{
  "type": "system", "subtype": "compact_boundary",
  "logicalParentUuid": "4cf7b8e8-…",          // points at pre-compaction tail
  "compactMetadata": {
    "trigger": "auto",                          // "auto" = CLI did it, not us
    "preTokens": 374787, "postTokens": 8778,
    "preCompactDiscoveredTools": ["WebFetch","WebSearch"],
    "durationMs": 320735
  },
  "version": "2.1.150", "entrypoint": "sdk-py"
}
```

The actual summary lands as a `user`/`assistant` message flagged
**`"isCompactSummary": true`**, which "replaces earlier messages" — i.e. on resume the CLI
follows the summary, not the discarded tail. The SDK deliberately does **not** follow
`logicalParentUuid` on resume (`sessions.py:933-936`).

> **Key takeaway:** the CLI tells you exactly when it compacted, by how much, and why
> (`trigger`). Orchestra currently ignores this line entirely (see Part 3).

### 1.3 Autocompact thresholds (from Anthropic cookbook + observed)

- **Auto-compact buffer:** ~13K tokens — autocompact triggers when ~13K tokens of headroom
  remain.
- **Warning buffer:** ~20K tokens — `/context` warning appears at ~20K remaining.
- **Manual-compact buffer:** ~3K tokens — new requests blocked until manual compact.
- For a 200K window: 200K − ~13K ≈ **187K**, and "95% of effective" ≈ the ~167K we observe
  in the transcript. The numbers line up with a **200K window, not 1M**.

There is **no CLI/SDK setting exposed in 0.1.72 to disable autocompaction** (see Part 2.3).
You can influence *when* via the model's window size, not *whether*.

---

## Part 2 — Claude Agent SDK 0.1.72: the API surface

### 2.1 `get_context_usage()` — the authoritative source (THIS is `/context`)

- `ClaudeSDKClient.get_context_usage()` (`client.py:505`) → control request
  `{"subtype":"get_context_usage"}` (`_internal/query.py:678-680`). It is a **control
  request**, so it works mid-session, between turns — same data the `/context` slash command
  shows. (This API is the resolution of SDK issue #507 "add /context to SDK".)
- Returns `ContextUsageResponse` (`types.py:706-768`). Fields that matter:

| field | meaning |
|---|---|
| `totalTokens` | tokens **currently resident** in the window (the real number) |
| `maxTokens` | **effective** max (already minus autocompact buffer) |
| `rawMaxTokens` | raw model window (e.g. 200000 or 1000000) |
| `percentage` | 0–100, computed by the CLI — **use this directly** |
| `isAutoCompactEnabled` | whether CLI autocompact is on |
| `autoCompactThreshold` | token count at which it fires (NotRequired) |
| `model` | model the usage is computed for |
| `categories` / `mcpTools` / `memoryFiles` / `agents` | per-bucket breakdown |

`totalTokens` is whole-window resident tokens — **not** a per-iteration delta. This is the
fix for the estimation error.

### 2.2 `ResultMessage.usage` — why the per-iteration estimate is wrong

Observed `usage` keys on an assistant message:
`input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens,
server_tool_use, service_tier, cache_creation, inference_geo, iterations, speed`.

`iterations` is a list of per-API-call usages **within one turn** (tool loops). Orchestra reads
`iterations[-1]` and sums `input + cache_read + cache_create` of the **last** iteration. That
is "tokens billed on the final API call of the turn", which:
- swings turn-to-turn (a tool-heavy turn's last iteration can be a small delta),
- shifts as the cache boundary moves (`cache_read` vs `input`),
- **resets visibly right after a CLI compaction** (post-compact iteration is tiny).

It is a *billing* artifact, not a *window-occupancy* number. Right purpose: cost. Wrong
purpose: context %.

### 2.3 What the SDK CANNOT do (verified by grep of the whole package)

- **No compaction trigger.** Control subtypes in `query.py`: `initialize, interrupt,
  set_permission_mode, set_model, rewind_files, mcp_status, mcp_reconnect, mcp_toggle,
  stop_task, get_context_usage, get_mcp_status`. There is **no `compact` subtype**. Orchestra's
  "compact" is a `/compact`-style summarize-then-fork done by hand (`session.compact()`), not an
  SDK call.
- **No autocompact disable.** `isAutoCompactEnabled` is **output-only** in `ContextUsageResponse`;
  there is no input option in `ClaudeAgentOptions` to turn it off. → Previous research's **Open
  Q1 is answered: NO, you cannot disable CLI autocompact in 0.1.72.** Fix B part-2 ("own
  compaction by disabling the CLI's") is **not possible**; only "report it" is.
- **No compact callback.** But `compact_boundary` *is* delivered as a message: it parses through
  the `case _:` arm of the system handler → `SystemMessage(subtype="compact_boundary",
  data=<full dict incl. compactMetadata>)` (`message_parser.py:212-216`). So you don't get a
  typed event, but you **do** get the data if you inspect `SystemMessage`.

### 2.4 The 1M context window (the crux)

- `SdkBeta = Literal["context-1m-2025-08-07"]`; `ClaudeAgentOptions.betas: list[SdkBeta]`
  (`types.py:29, 1551-1556`). The docstring says **"Sonnet 4/4.5 only"**.
- **The beta is RETIRED as of 2026-04-30.** Per Anthropic docs, Sonnet 4.6 / Opus 4.6 / 4.7 (/4.8)
  ship 1M at standard pricing **without** a beta header.
- **BUT** the live transcript on `claude-opus-4-6` (2026-05-28) autocompacts at ~167K, i.e. a
  **200K effective window**. So in our runtime (CLI 2.1.150 via SDK 0.1.72), the model is **not**
  getting a 1M window by default. Whether 1M requires re-enabling via a header or a newer CLI is
  an open item (Open Q below), but the *empirical truth* is: **our workers run at 200K.**

---

## Part 3 — Orchestra: current implementation (what's live now)

> Note: parts of `research-context-bug.md`'s Fix A & D have **landed**. Verified below.

### 3.1 What's already implemented (good)

- **`context_usage()` exists** — `backend_claude.py:163-176` calls
  `self._client.get_context_usage()` and returns `percentage/total_tokens/max_tokens/
  auto_compact/auto_compact_threshold`. ✅ (Fix A backend half.)
- **`_refresh_context_from_api()` exists** — `session.py:692-706`: after a turn it pulls the
  authoritative usage, overwrites `_last_context`, logs a "context corrected" line if it
  diverges >20pp, and persists. ✅
- It's scheduled on `turn_end` (`session.py:422`) and on resume (`session.py:252`). ✅ (Fix D.)

### 3.2 What's STILL broken / risky

**B1 — `context_pct` still primarily comes from the per-iteration estimate.** `RESULT` path at
`backend_claude.py:245-257` still computes `ctx_pct = total/max_tokens` from `iterations[-1]`,
and `_handle_turn_end` sets `_last_context` from it (`session.py:410-420`) *before* the async
`_refresh_context_from_api()` fires. The refresh is fire-and-forget and corrects it a beat
later — so the dashboard/SSE can still flash the wrong number, and any consumer that reads
between the two sees the estimate. **The estimate is still the seed value, not the API.**

**B2 — the refresh silently no-ops in exactly the cases that matter.** `_refresh_context_from_api`
(`session.py:693`) early-returns if `self._backend is None`. But `compact()` sets
`self._backend = None` (`backend_claude.py:160` via `disconnect()`, and `session.py:640`). So
right after a compaction — when the number is most volatile — the refresh can't run. Same after
any disconnect/hibernate. The "authoritative correction" is skipped precisely when it's needed.

**B3 — WRONG DENOMINATOR (the headline bug).** `CONTEXT_LIMITS["claude-opus-4-6[1m]"] = 1000000`
(`models.py:14-23`), and `self.model` keeps the `[1m]` suffix, so `max_tokens = 1_000_000`
(`backend_claude.py:256`). But §2.4 proves the CLI window is **200K**. Every `[1m]` worker's
`context_pct` is therefore **~5× too low**. This is the single biggest cause of "phantom reset":
Orchestra shows ~17% while the CLI is at ~95% and about to autocompact. *Even with Fix A, if the
estimate path or any fallback uses `CONTEXT_LIMITS`, the denominator is wrong.* The
`get_context_usage()` `maxTokens` is correct (200K) — but B1/B2 mean we don't always use it.

**B4 — `[1m]` is stripped and no `betas` is passed, so 1M is never enabled.**
`backend_claude.py:109` `cli_model = self.model.replace("[1m]", "")`, and `ClaudeAgentOptions`
(`110-117`) sets **no `betas`, no `extra_args`** for 1M. So the `[1m]` label is cosmetic — the
worker gets a plain model at 200K. Either we *intend* 200K (then fix B3 to say 200K), or we
*want* 1M (then we must actually enable it and confirm the CLI honors it). Today it's neither:
labelled 1M, runs 200K, billed/measured as 1M.

**B5 — CLI autocompaction is invisible.** `_convert()` (`backend_claude.py:185-…`) handles
`AssistantMessage/UserMessage/Task*Message/ResultMessage` but **not** plain `SystemMessage`.
`compact_boundary` (with full `compactMetadata`) is dropped on the floor. So Orchestra logs no
compaction even though the CLI did one. (RC2 — still unaddressed.)

**B6 — `compact()` NULLs `session_id` across a crash window.** `session.py:648-649` sets
`self.session_id = None`; if `auto_resume_all` filters `WHERE session_id IS NOT NULL`
(`manager.py`), a restart in that window orphans the worker → full context loss. (RC4 — still
present; narrow but real.)

**B7 — our `_auto_compact()` at `>90%` races the CLI's autocompact.** `session.py:443`. Since we
can't disable the CLI's (§2.3) and our % is computed on the wrong denominator (B3), our trigger
almost never fires for `[1m]` workers (90% of 1M = 900K, never reached at a 200K window). So the
CLI always wins, and our compaction is effectively dead code for Opus workers. (RC2/RC6.)

### 3.3 Data flow (current, annotated)

```
turn_end (CLI)
  └─ backend_claude._convert(ResultMessage)
        ├─ ctx_pct = iterations[-1] / CONTEXT_LIMITS[model]   ← B1 estimate, B3 wrong max
        └─ emits "turn_end" {context_pct, context_tokens, max_tokens}
  └─ session._handle_turn_end
        ├─ _last_context = {from estimate}                    ← seed = wrong
        ├─ create_task(_refresh_context_from_api)             ← corrects… unless backend None (B2)
        ├─ if ctx_pct>90 → _auto_compact()                    ← never fires for [1m] (B7)
        └─ _persist() → DB context_pct                        ← persists the estimate first
SystemMessage(compact_boundary)  ← DROPPED, never logged (B5)
```

---

## Part 4 — Best practices (web research, 2026)

- **Read, don't estimate.** Anthropic's own answer to "give me /context in the SDK" (issue #507)
  is `get_context_usage()`. Use `percentage`/`maxTokens` from it as the source of truth; keep the
  `usage`-derived number for **cost only**.
- **Subagent / divide-and-conquer.** Each subagent gets its own window → no single session nears
  the limit. (Orchestra already does this — it's the whole point. Lean into it: prefer spawning a
  fresh worker over compacting a fat one.)
- **CLAUDE.md as the durable spine.** Re-injected every session; survives every compaction. Put
  "never-forget" facts there, not in chat. (Orchestra does this via system prompt + worktree
  CLAUDE.md.)
- **Custom compaction summary prompts** to preserve critical state — Orchestra's `COMPACT_PROMPT`
  (`session.py:595-606`) is already a strong, structured handoff. Keep it.
- **Context editing / tool-result clearing** (Anthropic "context editing" API) — strip stale
  tool outputs instead of summarizing everything. Future option, not in SDK 0.1.72 surface.
- **Monitor compaction, verify quality** — surface every compaction (ours *and* the CLI's) so a
  human can sanity-check the summary. Today we surface neither reliably for Opus.

### Competitors (how others handle it)

- **Aider:** explicit `/tokens` + a repo-map that is *recomputed and trimmed* to a token budget;
  the user owns context, no silent summarization. Lesson: **make the budget visible and trimmed,
  not estimated.**
- **Cursor / Windsurf:** retrieval over stuffing — they index the repo and inject only relevant
  chunks per turn rather than carrying a giant transcript. Lesson: **don't carry what you can
  re-fetch.** (Orchestra's worktree + grep hints already lean this way.)
- **Common pattern across all three:** the *displayed* context number is the *authoritative*
  one, and compaction/trim is an explicit, logged event. Orchestra's gap is precisely that the
  displayed number is derived and the (CLI) compaction is silent.

---

## Part 5 — Recommendations & concrete plan for Orchestra

Ordered by signal/effort. **No code changed in this task — this is the plan.**

### R1 (PRIMARY) — Fix the denominator. Decide 200K vs 1M, then make ONE number true.
- **If we accept 200K** (matches reality today): set `CONTEXT_LIMITS` for the `[1m]` Opus keys to
  `200000`, OR — better — **stop trusting `CONTEXT_LIMITS` for claude backend entirely** and use
  `maxTokens` from `get_context_usage()` as the denominator. Keep `CONTEXT_LIMITS` only as the
  offline/codex fallback.
- **If we want 1M:** in `_make_client` actually enable it (confirm the right mechanism for CLI
  2.1.150 — `betas=["context-1m-2025-08-07"]` is retired; native-1M models may need a newer CLI
  or an `extra_args`/header). Then **verify** with a `get_context_usage()` call that `rawMaxTokens
  == 1000000` before believing the label. Until verified, treat as 200K.
- *Files:* `app/models.py:14-23`, `app/backend_claude.py:109,256`.

### R2 (PRIMARY) — Make `get_context_usage()` the seed, not the correction.
- In the claude path, prefer the API number as the *primary* `context_pct`; fall back to the
  `usage` estimate only if the API call fails. Move the read so `_last_context` is set from the
  API *before* persist/SSE, or persist the estimate then immediately overwrite synchronously.
- Fix **B2**: don't early-return when `self._backend is None` right after compaction — either
  read via the freshly-reconnected client, or schedule the refresh after the post-compact turn's
  `turn_end` (which has a live backend). Ensure exactly one authoritative read lands after every
  compaction.
- *Files:* `app/session.py:410-422,692-706`, `app/backend_claude.py:245-257`.

### R3 (PRIMARY) — Detect & log the CLI's own autocompaction.
- In `backend_claude._convert`, add a branch: `isinstance(msg, SystemMessage) and
  msg.subtype == "compact_boundary"` → emit a `status`/`compact` event with
  `data["compactMetadata"]` (`trigger, preTokens, postTokens`). Then the operator sees
  "CLI auto-compacted 374K→8K" instead of a phantom drop.
- This makes RC2 *explainable* (we can't prevent it — §2.3 — but we can surface it).
- *Files:* `app/backend_claude.py:185-…` (add SystemMessage branch), `app/events.py` (event doc).

### R4 (SECONDARY) — Stop fighting the CLI's autocompact.
- Our `_auto_compact()` at `>90%` (`session.py:443`) can't win (B7) and can't disable the CLI's
  (§2.3). Options: (a) raise our trigger only as a *fallback* for backends that don't autocompact
  (codex), or (b) keep it but base it on the **authoritative** % so it's meaningful. Don't run two
  compactors against the same window.
- *Files:* `app/session.py:443,708-713`.

### R5 (SECONDARY) — Close the `session_id=NULL` crash window (RC4/B6).
- In `compact()` keep `old_session_id` persisted until the new compacted turn returns a real id,
  then swap. Don't persist `NULL`. Closes the "restart during compact → orphaned worker" hole.
- *Files:* `app/session.py:648-653`, `app/manager.py` (`auto_resume_all` filter).

### R6 (LOW) — Single owner for `_compacting`; tidy resume seed.
- Let `compact()` be the sole owner of `_compacting` (remove the double set/clear with
  `_auto_compact`). Keep `manager.py:756` `if pct or tokens` but rely on R2's post-resume read to
  self-heal the 0% case.

### Recommended order
1. **R1** (denominator) — without it every other number is wrong. Cheapest, biggest win.
2. **R2** (API as primary) — makes the % trustworthy and self-healing post-compact.
3. **R3** (surface CLI compaction) — kills the "phantom" perception; pure observability.
4. **R5** (crash window) — small, closes real data-loss path.
5. **R4 / R6** — cleanup, no behavior change.

---

## Open questions (need confirmation before coding R1/R4)

- **OQ1 — Does CLI 2.1.150 give Opus 4.6/4.7/4.8 a 1M window at all via the SDK, and how?**
  Beta header is retired; native-1M may need a newer CLI or a specific flag. Empirically our
  sessions run 200K. *Test:* spawn an Opus worker, call `get_context_usage()`, read
  `rawMaxTokens`. If 200000 → we are NOT on 1M; R1 should standardize on 200K (or upgrade CLI).
- **OQ2 — Is `get_context_usage()` cheap enough to call every turn?** It's a control round-trip.
  Default to once on `turn_end`/idle (already the pattern). Confirm no measurable latency hit on
  busy workers.
- **OQ3 — Confirmed RC2 with transcript (done).** `compact_boundary trigger=auto` proven present.
  No further proof needed; R3 just needs to parse it.

---

## Evidence index (file:line)

**SDK 0.1.72** (`~/.cache/uv/archive-v0/yzst9nGEp0gg74cpOT0jh/claude_agent_sdk/`):
- `client.py:505-539` — `get_context_usage()` (control request, mid-session safe)
- `_internal/query.py:678-680` — `{"subtype":"get_context_usage"}`; full subtype list `676-755`
- `types.py:706-768` — `ContextUsageResponse` (totalTokens/maxTokens/rawMaxTokens/percentage/
  isAutoCompactEnabled/autoCompactThreshold)
- `types.py:29,1551-1556` — `SdkBeta` / `betas` field ("Sonnet 4/4.5 only", retired)
- `_internal/message_parser.py:164-216` — system subtype handling; `compact_boundary` → generic
  `SystemMessage` with full `data`
- `_internal/sessions.py:283,933-936` — `isCompactSummary` "replaces earlier messages";
  `logicalParentUuid` not followed on resume

**Live transcript** (`~/.claude/projects/-mnt-data-Projects-Python-orchestra/3f463fa3-….jsonl`):
- 17 `isCompactSummary` + 12 `compact_boundary` entries
- All `trigger:"auto"`, preTokens 167K–374K → **200K window, CLI-owned compaction**

**Orchestra** (worktree `app/`):
- `backend_claude.py:109` — `[1m]` stripped, no `betas` (B4)
- `backend_claude.py:163-176` — `context_usage()` ✅
- `backend_claude.py:185-…` — `_convert`, no `SystemMessage` branch (B5)
- `backend_claude.py:245-257` — per-iteration estimate + `CONTEXT_LIMITS` denominator (B1,B3)
- `models.py:14-23` — `CONTEXT_LIMITS` (1M for `[1m]` keys) (B3)
- `session.py:410-422` — estimate seeds `_last_context`, then async refresh (B1)
- `session.py:443,708-713` — `_auto_compact` at >90% (B7)
- `session.py:595-662` — `compact()` (good prompt; NULLs session_id, B6)
- `session.py:692-706` — `_refresh_context_from_api` (early-returns if backend None, B2)
- `manager.py:754-759` — resume seed from DB

**Web:**
- Anthropic Cookbook — Automatic context compaction (buffers: 13K auto / 20K warn / 3K manual)
- GitHub anthropics/claude-agent-sdk-python #507 — "/context in SDK" → resolved by
  `get_context_usage()`
- Anthropic docs — `context-1m-2025-08-07` retired 2026-04-30; 1M native on Sonnet 4.6 / Opus
  4.6/4.7

---

## Part 6 — How to DISABLE / control CLI autocompaction (addendum)

Previous research (Open Q1) concluded "can't disable autocompact — no SDK option." That's true
for the **typed `ClaudeAgentOptions` field**, but the CLI binary (`2.1.150`) exposes the control
through **env vars / settings.json / a slash command** — and the SDK lets us reach all three
(`env=`, `setting_sources=`, and we already pass `env`). Verified by `strings` on the bundled
CLI.

### 6.1 The three levers (binary-confirmed)

| Lever | Key | Source |
|---|---|---|
| **Env — window size** | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | binary string: `"tokens (from CLAUDE_CODE_AUTO_COMPACT_WINDOW)"` |
| **Settings — on/off** | `autoCompactEnabled` (bool) in `settings.json` | binary symbols `autoCompactEnabled`, `AutoCompactEnabled` |
| **Interactive** | `/autocompact` slash command | binary string: `"/autocompact to configure"` |

Also present: `CLAUDE_CODE_COLD_COMPACT`, `CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP` (related knobs).

Buffer constants pulled straight from the binary (confirm the cookbook numbers):
`_F_=20000` (warning buffer = 20K), `VB7=1e6` (1M ceiling), `dG6=1e5` (100K). And an anti-thrash
guard string:

> "Autocompact is thrashing: the context refilled to the limit within 3 turns of the previous
> compact, 3 times in a row. A file being read or a tool output is likely too large…"

### 6.2 What this means for Orchestra (decision)

Two real options now that we know it's controllable:

**Option A — keep autocompact, just SIZE it correctly.** This is the cleanest given we run at
200K. We can leave autocompact ON (it's a safety net) but the real fix is still R1 (correct
denominator) + R3 (surface the boundary). No need to disable.

**Option B — DISABLE CLI autocompact and own compaction ourselves.** Now possible via
`settings.json: {"autoCompactEnabled": false}` (or the env var equiv). Since we pass
`setting_sources=["user","project","local"]` (`backend_claude.py:125`) and `env={...}`
(`backend_claude.py:116`), we can inject either:
- write `autoCompactEnabled: false` into a project/local `settings.json` the worker loads, **or**
- pass `env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "<huge>"}` to push the trigger out of reach.

> ⚠️ **Caution against Option B.** If we disable the CLI's autocompact and our own
> `_auto_compact()` is dead code for `[1m]` workers (B7), we'd hit the **hard context limit with
> no compaction at all** → the CLI starts *blocking requests* at the 3K manual buffer. Only take
> Option B if R4 first makes our own compaction trigger fire on the **authoritative** %. Disabling
> the safety net without a working replacement = worker wedged.

**Recommendation:** **Option A.** Don't disable. Fix the denominator (R1), surface the CLI's
compaction (R3), and treat the CLI autocompact as the safety net it is. Disabling adds risk for no
benefit at our scale. Revisit B only if we ever need deterministic, custom summaries on every
compaction.

*Files if we ever do B:* `app/backend_claude.py:116,125` (inject env/settings).

---

## Part 7 — Codex CLI as an IMPLEMENTER (not just reviewer) (addendum)

**Premise:** on SWE-rebench, GPT-5.5 reportedly beats Opus at coding (~59% vs ~52%). Idea: a
`codex_implement` tool — feed a `plan.md`, Codex writes the code. We already use Codex for review
(`codex_review` MCP tool); this asks whether it can *implement*. **Yes — `codex exec` is built for
exactly this.** Verified against `codex-cli 0.124.0` locally.

### 7.1 `codex exec` — the non-interactive implementer

```
codex exec [OPTIONS] [PROMPT]      # prompt as arg, or via stdin (use "-" or pipe)
```

Relevant flags (from `codex exec --help`, confirmed):

| Flag | Use for an implementer |
|---|---|
| `-m, --model <MODEL>` | pin `gpt-5.5` |
| `-C, --cd <DIR>` | **run in the worker's worktree** (isolated, like our workers) |
| `--add-dir <DIR>` | extra writable dirs if needed |
| `-s, --sandbox <MODE>` | `read-only` \| `workspace-write` \| `danger-full-access` |
| `--full-auto` | low-friction sandboxed auto-exec (workspace-write, no prompts) |
| `--json` | **JSONL event stream** — parse like we parse the SDK stream |
| `-o, --output-last-message <FILE>` | capture the final summary to a file |
| `--output-schema <FILE>` | force the final response into a JSON Schema (structured result) |
| `--skip-git-repo-check` | allow outside a git repo (we're always in one, skip) |
| `--ephemeral` | don't persist session files (or omit to allow `resume`/`fork`) |
| stdin `<PROMPT>` | pipe the full `plan.md` as instructions; if both arg+stdin, stdin appended as `<stdin>` block |

Companion subcommands:
- **`codex apply` / `codex a`** — "Apply the latest diff produced by Codex agent as a `git apply`
  to your local working tree." So Codex can produce a diff and we apply it deterministically.
- **`codex exec resume [--last]`** — resume a previous exec session (iterate on the same task).
- **`codex exec review`** — the review path we already wrap (`--uncommitted` reviews staged+
  unstaged+untracked).
- **`codex mcp-server`** — Codex can itself run as an MCP (stdio) server.

### 7.2 Proposed tool: `codex_implement(plan_path, output, model="gpt-5.5")`

Mirror the existing `codex_review` MCP tool, but in implement mode. Sketch:

```
codex exec \
  --model gpt-5.5 \
  --cd <worker_worktree> \
  --sandbox workspace-write \        # write only inside the worktree
  --json \                           # stream events → parse to Orchestra log
  -o docs/tasks/<id>/codex-impl-summary.md \
  - < docs/tasks/<id>/plan.md        # plan piped as instructions via stdin
```

Then the worker (or orchestrator) reviews the diff (`git diff`), runs tests, and commits — same
gate as a human-written change. **Determinism note (matches CLAUDE.md):** one path —
plan → `codex exec --full-auto` in worktree → diff → our review/test → commit. No improvisation.

### 7.3 Design decisions / risks to settle before building

- **Sandbox:** use `workspace-write` (or `--full-auto`) scoped to the worker's worktree via `-C`.
  **Never** `danger-full-access` / `--dangerously-bypass-approvals-and-sandbox` for an automated
  tool — that defeats worktree isolation.
- **Proxy:** Codex must also go through Hiddify. Pass `HTTPS_PROXY` via env (and/or
  `-c shell_environment_policy.inherit=all` so the subprocess inherits our proxy env).
- **Result capture:** `--json` for streaming into the dashboard log + `--output-schema` if we want
  a machine-readable "done/blocked/files-changed" summary; `-o` for the prose summary.
- **Review gate:** Codex-written code should still pass our `codex_review` (self-review by a
  *different* invocation) **or** an Opus review before merge. Don't let the implementer also be
  the sole reviewer of its own diff.
- **Cost/latency:** `codex exec` is a full agent run; budget it like spawning a worker, not like a
  quick tool call. Best for well-specified `plan.md` tasks (data layer, pure functions) where the
  spec is tight — exactly TDD-friendly work.
- **When to use:** tight, spec'd implementation tasks (per SWE-rebench strength). **Not** for
  fuzzy/exploratory work where a plan doesn't exist yet — that's still Opus/worker territory.

*Files if built:* new `codex_implement` in `app/mcp_stdio.py` (mirror `codex_review`), reusing the
existing Codex invocation plumbing.

### 7.4 Verified facts

- `codex-cli 0.124.0` installed at `/home/maxim/.npm-global/bin/codex`.
- `codex exec` flags above are from the live `--help` output (not from memory).
- `codex apply` exists and does `git apply` of the agent's last diff.
</content>
