# Research: Context Caching on Claude Code Max Subscription

**Task:** cache-optimization · **Phase:** 1 (Research + Experiment) · **Date:** 2026-07-09
**Author:** research-cache (Opus 4.8 full-cycle)

---

## Question (framed)

- **Context:** Orchestra runs a fleet of Claude Code agents (orchestrators + workers) on a **Max 20x subscription**. Every agent-turn re-sends the full context; the API prompt-caches the unchanged prefix.
- **Change under test:** How long does the prompt cache live (TTL), and how does idle time between turns change turn cost (cache hit → miss)?
- **Baseline / comparison:** 5-min vs 1-hour TTL; Opus 4.6 vs 4.8 cost and token profile.
- **Measurable outcome:** cost-per-turn (and size-normalized $/ctx%) as a function of idle gap, per model, from `data/orchestra.db`.

## Hypotheses considered

1. **H1 (leading):** Claude Code on Max uses the **1-hour** cache TTL by default (not the classic 5-min), because Max usage is plan-included so the higher 1h write cost is free. → Turn cost stays flat far past 5 min of idle, then spikes only after ~1h.
   - **Falsifier:** if cost jumped up after ~5 min idle, TTL would be 5-min.
2. **H2 (alt):** Default 5-min TTL (like Pro/API). → cost spikes after 5 min idle.
3. **H3 (alt):** 4.8 is intrinsically more expensive per turn than 4.6 (different tokenizer / pricing). → higher $/turn at equal work.

**Verdict up front:** H1 **CONFIRMED** (docs + empirics agree). H2 **REFUTED** for Max main conversations (but TRUE for subagents). H3 **REFUTED** — 4.8's higher $/turn is explained by more work per turn, not higher unit cost.

---

## Findings

### 1. Cache TTL — theory (primary sources)

**Claim 1.1 — Two TTLs exist: 5-minute (default) and 1-hour.** `cache_control: {type:"ephemeral"}` = 5 min; `{type:"ephemeral", ttl:"1h"}` = 1 hour. No other tiers. — **CONFIRMED** (Anthropic prompt-caching docs [1], claude-api skill primary reference).

**Claim 1.2 — On a Claude subscription, Claude Code requests the 1-hour TTL automatically.** *"On a Claude subscription, Claude Code requests the one-hour TTL automatically. Usage is included in your plan rather than billed per token, so the longer TTL costs you nothing extra and only affects how long your cache stays warm."* — **CONFIRMED** (Claude Code prompt-caching doc [2], verbatim). This is the crux for Orchestra: **our agents get 1-hour cache TTL, free.**
   - Exception: once over the plan usage limit and drawing on usage credits (billed), Claude Code **drops to 5-min TTL** [2].
   - On API key / Bedrock / Vertex / Foundry → 5-min default; opt into 1h with `ENABLE_PROMPT_CACHING_1H=1` [2].

**Claim 1.3 — TTL resets on every cache hit.** The cache expires only after a *gap of inactivity* longer than the TTL; each hit re-warms it. *"Each request that hits the cache resets the timer, so the cache stays warm as long as you keep working."* — **CONFIRMED** [1][2]. So a warm agent hit every few minutes keeps its cache alive indefinitely at zero extra cost.

**Claim 1.4 — Subagents always use 5-minute TTL, even on subscription.** *"Subagents use the five-minute TTL even on a subscription, since the automatic one-hour TTL applies to the main conversation."* — **CONFIRMED** [2]. Relevant: Orchestra spawns workers as *separate CLI sessions* (each a main conversation, so 1h), NOT as in-session Claude Code subagents — so our workers keep the 1h benefit. Only true in-session `Task`/subagent calls fall to 5-min.

**Claim 1.5 — Opus 4.6 vs 4.8 TTL is identical.** TTL is set by auth tier (subscription → 1h), not by model. Both 4.6 and 4.8 get 1h on Max. — **CONFIRMED** [2] (no per-model TTL logic documented; controlled by `ENABLE_PROMPT_CACHING_1H`/`FORCE_PROMPT_CACHING_5M`/auth only).

**Claim 1.6 — March 2026 regression.** Multiple reports: Claude Code's default silently dropped 1h→5m around early March 2026, inflating cost/quota [3][4]. Our July 2026 data shows clear 1h behavior, so on Max it is (back to) 1h. — **LIKELY** (multiple secondary reports [3][4] + our data consistent with 1h now). Flag: watch for silent regressions; `FORCE_PROMPT_CACHING_5M`/`ENABLE_PROMPT_CACHING_1H` are the levers.

### 2. Cache pricing multipliers (primary source [1])

| Component | Multiplier vs base input | Opus ($5/M base) |
|---|---|---|
| Base (uncached) input | 1.0× | $5.00/M |
| **Cache read** (hit) | **0.1×** | $0.50/M |
| **Cache write, 5-min** | **1.25×** | $6.25/M |
| **Cache write, 1-hour** | **2.0×** | $10.00/M |
| Output | — | $25.00/M |

- **Read↔write cost ratio:** create-5m/read = 12.5×; **create-1h/read = 20×**. A cache miss re-bills the whole prefix at 12.5–20× the read price.
- On Max these are *virtual* $ (plan-included), but they map 1:1 to **rate-limit / quota burn** — so cache misses still hurt by eating your Max limits faster.

### 3. Empirical TTL from our logs (measurement — strongest tier)

**Method:** Parsed 1027 `turn ended (...)` log lines (2026-07-03 → 07-09) from `logs` table. Each: `$X turn`, `N subturns`, `ctx:P%`. Metric = **cost per ctx% for single-subturn turns** (nturns=1, cost>0) — the cleanest cache signal (one LLM call, cost ∝ prefix size × price tier). Pass/fail defined before running: flat $/ctx% across idle buckets = cache HOT; a step up = eviction. Idle gap = minutes since previous turn ended.

**Result (Opus 4.6, single-subturn, $/ctx%):**

| Idle gap | n | median $/ctx% | vs hot baseline |
|---|---|---|---|
| 0–3 min | 87 | 0.00571 | 1.00× |
| 3–5 min | 19 | 0.00562 | 0.98× |
| 5–7 min | 10 | 0.00600 | 1.05× |
| 7–10 min | 4 | 0.00557 | 0.98× |
| **>120 min** | 9 | **0.10019** | **17.5×** |

**Result (all-turns "excess cost" model, Opus 4.6** — fills the sparse transition zone; ratio = actual / hot-predicted cost):

| Idle gap | n | actual/hot ratio |
|---|---|---|
| 0–3 min | 380 | 0.70 (cached) |
| 3–5 | 114 | 0.82 |
| 5–8 | 93 | 0.83 |
| 8–12 | 37 | 0.79 |
| 12–18 | 13 | 0.76 |
| 18–30 | 8 | 0.82 (still cached) |
| **30–60** | 10 | **1.12** (degrading) |
| **60–180** | 15 | **1.28** |
| **>180 min** | 42 | **4.65** (evicted, full re-bill) |

**Interpretation:**
- Cost is **flat 0–~30 min** of idle → cache HOT. This is **incompatible with a 5-min TTL** (H2 refuted) and matches the **1-hour TTL** (H1 confirmed). The apparent survival past 60 min in some buckets = TTL resetting on intervening hits (claim 1.3) — the "gap" is to the *previous logged turn*, but sub-requests within a turn also refresh the cache.
- The **>2h idle → 17.5× cost** multiplier lands right between the theoretical **12.5× (5m-write) and 20× (1h-write)** re-bill ratios [1] → confirms eviction re-bills the full prefix at cache-**create** price. This is a direct, independent confirmation of the pricing model from our own data.
- **Empirical effective TTL under our workload: ~30–60 min before cost visibly climbs, full eviction by ~2h.** Consistent with 1h TTL + hit-driven refresh.

**Confidence:** CONFIRMED — measurement (own reproducible data) + primary docs agree; the 17.5× multiplier matching the 20× theoretical tier is a decorrelated cross-check.

### 4. Opus 4.6 vs 4.8 — cost & tokens (measurement)

**Per-turn cost from logs (cost>0):**

| Model | n | median $/turn | median subturns/turn | median out tok/turn |
|---|---|---|---|---|
| Opus 4.6 | 725 | **$0.59** | 3 | 338 |
| Opus 4.8 | 137 | **$1.69** | **9** | **612** |

**Cumulative token profile (sessions, agents >5M cache_read):**

| Model | cache-hit % | read/create | out/turn | blended $/turn* |
|---|---|---|---|---|
| Opus 4.6 | 96.9% | 31.4× | 338 | $0.220 |
| Opus 4.8 | 97.0% | 31.9× | 612 | $0.217 |
| Sonnet 5 | 98.2% | 54.6× | 422 | $0.065 |

\* blended from cumulative tokens at Opus $5/$25, cache_read $0.5/M, 1h-write $10/M.

**Interpretation:**
- **4.8 median $/turn is ~2.9× that of 4.6 — but per *unit of work* they cost the same** (blended $0.217 vs $0.220/turn). The gap is because **4.8 does ~3× more subturns and ~1.8× more output per agent-turn** (its autonomy/overthinking — a deliberate feature for full-cycle/reviewer roles). It is NOT a more expensive tokenizer or price tier (both are $5/$25, same tokenizer family). **H3 REFUTED.**
- **Cache-hit rate is identical (~97%)** across 4.6/4.8 — caching efficiency doesn't differ by model; both benefit equally from the 1h TTL.
- Practical: 4.8 burns Max limits faster *per turn* because it packs more work in; that's a work-volume decision (which role gets 4.8), not a caching problem.

---

## Optimization strategies (subscription / limit burn)

Grounded in the invalidation rules [2] and the TTL/pricing above:

1. **Keep agents warm within the TTL.** With 1h TTL on Max, an agent idle <~1h resumes at cache-read price (0.1×). Idle >1h → next turn re-bills full prefix at 2× (a **20× jump** vs a hit). *Batch heavy multi-turn work into contiguous sessions; avoid long mid-task idles.* For scheduled heavy jobs, a cheap keep-alive turn under the TTL preserves the cache.
2. **Don't invalidate the prefix mid-session** [2]. Each of these forces a full uncached re-read (one slow, expensive turn):
   - **Model switch** (`/model`, opusplan plan↔exec toggle, Fable fallback) — each model has its own cache.
   - **Effort change** (`/effort`) — effort is part of the cache key.
   - **Fast mode toggle** (first time per convo).
   - **MCP server connect/disconnect** when tools load into the prefix (Haiku, or tool-search disabled). Deferred tools (default on Opus/Sonnet) are safe.
   - **Denying a whole tool** (`Bash`, `WebFetch` bare deny) — removes it from system prompt.
   - **`/compact`** invalidates the conversation layer by design (but the summarization call itself reads cache; net cost is the summary generation, not a miss).
   - **Upgrading Claude Code / resuming after upgrade** — new system prompt ⇒ full re-read.
   Rule for Orchestra: **pick model + effort at spawn, keep them fixed for the session.** Our worktree lifecycle already does merge+switch deterministically — avoid mid-task model/effort changes.
3. **Cache-safe actions** (free to do mid-session) [2]: editing repo files (append `<system-reminder>` + re-read), invoking skills/commands (appended as user messages), plan mode, `/recap`, `/rewind`, permission-mode changes, spawning subagents (parent prefix intact).
4. **Worktree cache isolation (important for Orchestra).** *"the cache is effectively scoped to one machine and directory… two sessions in different directories build different prefixes and miss each other's cache. That includes worktrees of the same repository"* [2]. Every Orchestra worker runs in its own worktree → **workers never share cache with each other or the orchestrator.** Each pays its own cold-start write. This is inherent to the isolation model; the payoff (parallel safety) outweighs it. To share cache across machines/dirs for Agent-SDK fleets, Anthropic documents suppressing per-machine system-prompt sections [2] — not applicable to CLI workers, noted for future SDK use.
5. **Fleet sizing for Max 20x.** Each parallel agent has an independent cache and independently burns ITPM/OTPM + daily limits. Since cache-read is 0.1× and hit-rate is ~97%, the dominant limit-burn is **output tokens** (full price) + **cache-create on cold starts / invalidations**. Optimal parallelism = as many warm, long-lived agents as the rate limit sustains; the anti-pattern is many short-lived agents that each pay a cold cache-create and never amortize it. Prefer **fewer, longer-lived, warm workers** over churn. (No hard N — depends on live ITPM/OTPM headroom; the ETA-to-limit tool in usage.js already surfaces burn rate.)
6. **Model routing by work volume, not unit price.** 4.6 and 4.8 cost the same per unit of work; 4.8 just does more per turn. Route 4.8 to roles that *need* the extra reasoning (full-cycle, reviewer); keep 4.6 for orchestrators (short answers) and Sonnet 5 for disposable system workers ($0.065/turn, 3.4× cheaper).

---

## Feature proposal: cache timer on the dashboard

**Goal:** per-agent indicator — 🔥 hot cache (X min left) / 🧊 cold — counting down from the last turn to cache eviction, so the user sees which agents are warm (cheap to resume) vs cold (next turn = expensive re-bill).

### Data model
- **`cache_expires_at` = last_turn_ts + TTL**, where TTL = **60 min** for main agents on Max (1h), **5 min** for in-session subagents. Orchestra workers are separate CLI sessions → 60 min.
- `last_turn_ts` = timestamp of the agent's most recent `turn ended` log (already in `logs.ts`), OR `sessions.finished_at`/last activity. Since TTL resets on every hit, `last_turn_ts` is the correct anchor (each turn is a hit).
- Colour thresholds (fraction of TTL remaining): **green >50%** (>30 min), **yellow 20–50%** (12–30 min), **red <20%** (<12 min), **grey = evicted** (past `cache_expires_at`).

### Backend (`app/main.py` or a small router)
Add endpoint `GET /api/agents/cache-status`:
```python
# returns [{name, last_turn_ts, ttl_seconds, expires_at, seconds_left, state}]
# ttl_seconds = 3600 (main) — Orchestra workers are main convos
# last_turn_ts: latest logs.ts WHERE content LIKE 'turn ended%' per session_id
```
- Source: `SELECT session_id, MAX(ts) FROM logs WHERE content LIKE 'turn ended%' GROUP BY session_id` joined to `sessions` (name, status). ~1 cheap query; can piggyback on the existing sessions SSE payload instead of a new endpoint to avoid extra polling (cheaper for agents — matches AI-efficiency principle).
- Compute `state` server-side from `now - last_turn_ts` vs `ttl_seconds` so the frontend only renders.
- **Caveat to encode:** if the agent is currently `running`, cache is being actively refreshed → force 🔥 green regardless of last logged turn. If status is over-limit (usage credits), TTL should show 5 min — but we don't currently track credit state; default to 60 min and note the assumption.

### Frontend (`app.js` / a leaf module like `usage.js`)
- Add a small pill next to each agent in the fleet list: `🔥 42m` / `🧊 evicted`.
- Client-side `setInterval` (30s) decrements `seconds_left` from `expires_at` so the countdown is live without re-polling; refresh `expires_at` from the SSE sessions payload whenever a new turn lands.
- Reuse the existing colour helpers; render:
  ```
  fresh  (>30m): 🔥 green   "hot 42m"
  warm (12–30m): 🟡 yellow  "warm 18m"
  cool  (<12m):  🔴 red     "cooling 6m"
  cold (expired):🧊 grey    "cold — next turn re-bills"
  ```
- Tooltip: "Cache warm for N more min. Resuming now = cache-read (0.1×). After eviction, next turn re-bills the full prefix at ~20× read price (burns limits faster)."

### Files to touch
- **Backend:** `app/main.py` (or `app/routers/*`) — add cache-status to the sessions serializer; TTL constant in `app/models.py` or config.
- **Frontend:** `app/static/js/usage.js` (or `app.js` fleet render) — pill component + countdown timer; colour thresholds reuse existing utils.
- **No new dependency, no DB migration** — `logs.ts` already has the data.

### Accuracy caveats (be honest in the UI)
- TTL reset-on-hit means the timer is a *lower bound on staleness*, not exact eviction — a running agent stays warm. Anchoring on last turn is correct because each turn is a hit.
- We infer, not measure, eviction (the API doesn't expose `cache_expires_at`). Empirically eviction cost climbs from ~30 min and is full by ~2h, so a 60-min timer is a reasonable, slightly-conservative signal.
- If Anthropic silently regresses to 5-min (March-2026 style [3][4]), the timer would over-promise; make the TTL a config constant so it can be flipped to 5 min fast.

---

## Counter-evidence & conflicts

- **March 2026 1h→5m regression** [3][4] directly contradicts "Max always gets 1h." Both presented: the *documented* behavior is 1h on subscription [2]; a *reported period* had it silently at 5m [3][4]. Our July-2026 data shows 1h. Mitigation: config-driven TTL constant + `FORCE_PROMPT_CACHING_5M`/`ENABLE_PROMPT_CACHING_1H` awareness.
- **Transition-zone sparsity:** the 10–60 min idle buckets have small n (single-subturn: n<5; excess-model: n=8–15). The flat-then-spike shape is clear at the extremes (n=87 hot, n=42 evicted) but the exact inflection minute is under-sampled. Stated as "~30–60 min," not a precise TTL.
- **`$/ctx%` metric differs between single-subturn (0.0057) and all-turn (0.017) analyses** — because multi-subturn turns bundle multiple LLM calls under one `ctx%`. Single-subturn is the cleaner cache signal; all-turn is used only for the *ratio* (self-normalized), which is robust to this.

---

## Affected files / risks (for Phase 2/3)
- **Feature is additive** — new read-only endpoint/serializer field + frontend pill. No change to caching behavior itself (we don't set `cache_control`; the CLI does).
- Risk: TTL assumption (60 min) hardcoded — mitigate with a config constant.
- Risk: `running` agents must force-hot or the timer misleads.
- No security surface; no migration.

## Sources
1. Anthropic — Prompt Caching (platform docs): TTL options, pricing multipliers, refresh-on-hit, min prefix. `https://platform.claude.com/docs/en/build-with-claude/prompt-caching` (fetched 2026-07-09) + claude-api skill primary reference.
2. Claude Code — How Claude Code uses prompt caching: **1h TTL auto on subscription**, subagent 5-min, invalidation/keep rules, worktree cache scope, env vars. `https://code.claude.com/docs/en/prompt-caching` (fetched 2026-07-09).
3. GitHub issue #46829 — "Cache TTL silently regressed from 1h to 5m around early March 2026." `https://github.com/anthropics/claude-code/issues/46829`
4. DEV Community — "Anthropic Silently Dropped Prompt Cache TTL from 1 Hour to 5 Minutes." `https://dev.to/whoffagents/anthropic-silently-dropped-prompt-cache-ttl-from-1-hour-to-5-minutes-16ao`
5. Own measurement — `data/orchestra.db` logs (1027 turn-end lines, 2026-07-03→07-09); scripts in `/tmp/cache_analysis*.py`, `/tmp/cache_ttl_*.py`, `/tmp/model_compare.py`.
