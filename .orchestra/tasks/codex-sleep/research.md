# Research — why Codex/Sol workers call `sleep`

**Date:** 2026-07-25

**Phase:** 1 — research only

**Data cutoff:** SQLite snapshot of `data/orchestra.db` through log id `289716`
(`2026-07-25T04:06:55.064739+00:00`).

## Question

- **Context:** Orchestra workers running through Codex CLI 0.144.6, especially
  `gpt-5.6-sol` full-cycle workers.
- **Change under test:** stop agents from keeping an active turn alive with Bash
  `sleep N` while they wait for a background review, another worker, or a status
  transition.
- **Baseline:** current prompts and MCP responses.
- **Outcome:** zero Bash sleeps used for external-state polling, without blocking
  sleeps that are part of tests or bounded restart verification.

## Hypotheses and falsifiers

1. **H1 — MCP/runtime wording causes literal waiting.** `codex_review` says
   “do NOT poll, just wait,” but does not tell the agent to end its turn.
   **Falsifier:** sleeps are mostly unrelated to `codex_review` or other external
   state.
2. **H2 — Codex's own base instructions permit short waits.** The model is told
   only to avoid blocking waits longer than 60 seconds, so it selects shorter
   sleeps. **Falsifier:** observed sleeps commonly exceed 60 seconds, or affected
   rollouts did not contain that instruction.
3. **H3 — Orchestra role prompts directly require Bash waiting.**
   **Falsifier:** the relevant role prompts only use “wait” at phase gates and
   the sleeps occur before those gates.
4. **H4 — this is generic agent behavior, not Codex-specific.**
   **Falsifier:** Claude has no comparable Bash sleeps under the same Orchestra
   background-job mechanism.
5. **H5 — blocking all occurrences of `sleep` is safe.**
   **Falsifier:** legitimate tests, rate-limited scripts, or restart verification
   also contain sleeps.

## Method

`logs.content` stores a normalized JSON payload after the `Bash: ` prefix.
Codex-originated tool calls are positively identifiable per call, even across
model switches, when `CodexBackend._tool_use()` adds `_codex_item_id`; Claude's
converter does not add that marker.[2] Because the Codex code adds it only when
the upstream `item_id` is nonempty and the payload is a dictionary, the
marker-negative comparison group is labeled “unmarked/Claude-shaped” rather
than treated as conclusive Claude provenance.

The measurement selected Bash tool calls whose first parsed command action
contained `sleep` followed by a numeric duration:

```sql
WITH bash AS (
  SELECT l.id, l.session_id, l.ts,
         json_extract(substr(l.content, 7),
                      '$.command_actions[0].command') AS cmd,
         json_extract(substr(l.content, 7),
                      '$._codex_item_id') AS codex_item
  FROM logs l
  WHERE l.type = 'tool'
    AND l.content LIKE 'Bash: %'
    AND json_valid(substr(l.content, 7))
)
SELECT CASE WHEN codex_item IS NOT NULL
            THEN 'Codex-marked' ELSE 'unmarked/Claude-shaped' END,
       count(*) AS bash_calls,
       sum(lower(cmd) GLOB '*sleep [0-9]*') AS sleep_calls
FROM bash
GROUP BY 1;
```

This excludes source code containing `asyncio.sleep()` or `time.sleep()` but not
executing shell `sleep`. All 74 matching calls and their surrounding per-session
log records were inspected. A “burst” below means sleeps in the same session
separated by at most 120 seconds. The complete `log_id → class` annotation is
preserved in `sleep-call-annotations.tsv`; its three classes sum to 74 and can
be joined back to the frozen snapshot.

## Findings

### 1. The behavior is real, frequent, and entirely Codex-shaped

| Backend shape | Bash calls | Sessions | `sleep` calls | Sessions with sleep | Rate |
|---|---:|---:|---:|---:|---:|
| Codex-marked | 1,579 | 40 | **74** | 10 | **4.69%** |
| unmarked/Claude-shaped | 1,506 | 30 | **0** | 0 | **0.00%** |

**CONFIRMED — direct DB measurement.** The 74 calls requested 1,953 seconds
(32m 33s) of blocking time. Median duration was 30s, mean 26.39s, p90 45s,
maximum 50s. They formed 21 bursts averaging 3.52 sleeps; the largest burst had
9 sleeps and requested 320 seconds.

Role split strengthens the result:

| Role / backend | Bash calls | `sleep` calls | Rate |
|---|---:|---:|---:|
| full-cycle / Codex | 996 | 67 | 6.73% |
| orchestrator / Codex | 64 | 7 | 10.94% |
| worker / Codex | 519 | 0 | 0.00% |
| all Claude roles | 1,506 | 0 | 0.00% |

### 2. Worker breakdown

| Worker | Calls | Requested seconds | Typical context |
|---|---:|---:|---|
| `sales` | 15 | 375 | wait for child artifacts, then `codex_review` |
| `research-html-eff` | 12 | 455 | `codex_review` / resume |
| `research-codex-cache` | 10 | 280 | plan and implementation reviews |
| `investigate-restart` | 9 | 235 | review and debate |
| `research-opus5` | 7 | 235 | review, `bg_list`, timeout |
| `kesha-tg-bot` | 7 | 87 | child worker readiness and merge race |
| `upgrade-claude5` | 6 | 150 | review while the user was waiting |
| `codex-limits-official` | 4 | 120 | review and resume |
| `sensar-roadmap` | 3 | 15 | review and resume |
| `mobile-os-strategy` | 1 | 1 | review completion wait |

### 3. Every observed sleep was waiting for external state

| Context class | Calls | Share | Evidence |
|---|---:|---:|---|
| Own `codex_review` job still pending | 62 | 83.8% | latest review-start result was newer than latest completion notification |
| Immediately after review completion | 3 | 4.1% | artifact/transition grace wait after the notification |
| Child artifact or worker/merge readiness | 9 | 12.2% | `find` sibling worktree files or retry `merge_worker` |

**CONFIRMED — direct context inspection.** Representative sequences:

- `research-codex-cache`, logs `267403 → 267421`: review starts, four
  `sleep 30` calls, then `[Background job completed]`.
- `research-html-eff`, logs `288093 → 288118`: review resume starts, repeated
  `sleep 45`, completion arrives, then another `sleep 45`.
- `sales`, logs `287387 → 287420`: review starts, sleeps `20,20,20,30,30,30,30,45`,
  with `list_agents`, output-file checks, and `bg_list` mixed in.
- `kesha-tg-bot`, logs `287266 → 287273` and `289697 → 289707`:
  `merge_worker` returns `worker is running — wait for idle before merge`; the
  agent sleeps and retries.

No observed shell sleep performed useful computation or tested sleep behavior.

### 4. The main trigger is strongly supported as an instruction mismatch

`codex_review` correctly runs in the background, but its result says:

> You WILL be notified ... do NOT poll, just wait.

That sentence is emitted by `app/mcp_stdio.py:1010-1014`.[3] Sol interprets
“wait” as “keep this turn alive,” commonly by Bash sleeping until the injected
notification arrives.

The affected Codex 0.144.6 rollout metadata contains two relevant base
instructions:

- avoid blocking sleep or wait calls **longer than 60 seconds**;
- for monitor/wait tasks, use the product's recurring-monitoring or wait
  mechanism.[6]

**CONFIRMED — exact rollout metadata and durations.** Every observed duration
was at most 50 seconds, which is consistent with Sol obeying the 60-second
ceiling rather than understanding that Orchestra needs no active wait.

Orchestra already implements the correct lifecycle:

1. When a turn ends with an active background job, the session becomes
   `WAITING` (`app/session_turns.py:188-199`).
2. Job completion calls `session.send()` (`app/bg_jobs.py:281-298`).
3. If the worker is no longer running, that message starts a new turn; if it is
   still running, Codex receives a mid-turn steer (`app/session.py:447-477`).[4]

Claude demonstrates the intended path in real logs: `sensar-concrete-roadmap`
logs `275998 → 276004` show review start, explicit end-turn, `waiting for bg
jobs`, and a new turn on completion — no Bash sleep.

**HIGH confidence — multiple direct measurements and primary-source prompt
evidence.** The timing, wording, role-prompt gap, sub-60-second durations,
implemented lifecycle, and Claude comparison jointly support the instruction
mismatch. They do not isolate the phrase “just wait” as the sole cause through
a controlled intervention; post-change telemetry is the falsification test.

### 5. Prompt coverage is incomplete

`roles/worker.md:11` already says never use `until/while/sleep` loops to poll
external state, but the pipeline loads exactly `roles/{role}.md`. Full-cycle
workers therefore receive `roles/full-cycle.md`, not `roles/worker.md`; 67 of
74 sleeps came from that role.[5]

The existing worker rule is also too narrow: the observed pattern is repeated
one-shot `sleep` commands, not a literal shell loop. Full-cycle's “STOP. Wait
for approval” applies only after a phase report, while the measured sleeps
happen mid-phase during review, so the approval gates are not the cause.

### 6. “Model training likes sleep” is not needed to explain the data

**UNCERTAIN / unsupported.** Internal training data is not observable here.
The backend comparison proves a Sol-specific behavioral difference in this
runtime, but the exact tool response, prompt gap, sub-60 duration ceiling, and
external-state timing already explain the pattern. Training speculation adds
no actionable evidence.

## Fix options

### A. Explicit prompt rule — recommended, but make it precise

Add to the shared `base.md`, not only `worker.md`:

> Never use Bash `sleep`, `wait`, repeated one-shot checks, or `bg_list` to keep
> a turn alive while waiting for external state. End the turn immediately;
> Orchestra will deliver the completion message and start a new turn. A
> one-shot `sleep` is still polling. Exception: a delay that is itself part of
> a test or a bounded restart verification command.

**LIKELY effective.** It reaches full-cycle and orchestrator roles and directly
overrides Codex's weaker “not longer than 60 seconds” rule.

### B. Fix the `codex_review` result — recommended, highest leverage

Replace “do NOT poll, just wait” with:

> Do not poll, call `bg_list`, or run `sleep`. END YOUR TURN NOW. Orchestra will
> deliver completion as a new user message and automatically start a new turn.

**HIGH confidence.** At least 65/74 calls (87.8%) were directly adjacent to a
review pending/completion interval. The lifecycle already supports this.

### C. Fix merge readiness at the server — recommended for the residual race

`merge_session()` immediately rejects a still-running worker with “wait for
idle.” A parent often receives `send_message(DONE)` before the child turn has
fully transitioned to idle, then sleeps and retries.

Use a short bounded server-side wait under the session lock, or queue the merge
until the worker's turn-end transition. Do not make the LLM implement the
status-transition retry. This addresses 4 observed calls and removes a recurring
race independently of model behavior.

### D. Block all `sleep` in permissions — not as the primary fix

An absolute substring ban is too broad. The repo contains legitimate examples:

- `vps-deploy.md:37` waits 3 seconds before checking a restarted service;
- test/diagnostic scripts can contain `asyncio.sleep()` or `time.sleep()`;
- rate-limited scripts may intentionally sleep.

Codex PreToolUse hooks can inspect and block Bash commands, so a targeted
defense is possible.[7] If telemetry after A+B still shows violations, deny
only top-level standalone waiting commands such as `sleep N`, `sleep N; true`,
or `sleep N; date`, with a denial reason telling the agent to end its turn.
Do not block remote/test/restart commands merely because their text contains
the word `sleep`.

## Recommendation

Implement **B + A first**, then **C**:

1. Change `codex_review`'s return text to require ending the turn.
2. Add the explicit no-external-wait rule to shared `base.md`.
3. Remove the merge `RUNNING → IDLE` race from the LLM path.
4. Measure the next 7 days or 30 Sol review jobs. Target: zero external-state
   Bash sleeps.
5. Add a narrowly parsed PreToolUse guard only if residual violations remain.

This fixes the cause without disabling legitimate delays. Blocking `sleep`
alone would stop the symptom but may produce permission-denial retries and
leave the ambiguous “just wait” instruction intact.

## Counter-evidence and limitations

- Only 10 of 40 Codex-shaped sessions slept. The tool wording is a trigger, not
  a deterministic command; some sessions did useful work or ended their turn.
- The snapshot covers 2026-07-17 through 2026-07-25, not all historical
  Orchestra usage.
- Session rows can change model over time, so the comparison deliberately uses
  the positive per-tool `_codex_item_id`, not only `sessions.model`. Its absence
  is not independently conclusive Claude provenance, so that comparison group
  is reported as unmarked/Claude-shaped.
- The 120-second burst boundary is descriptive, not causal.
- The exact contribution of “just wait” versus Sol's broader external-state
  behavior remains unisolated until the wording change is measured.
- A prompt-only fix is not guaranteed; this is why the recommendation includes
  post-change telemetry and an optional targeted guard.

## Codex second opinion

Codex independently recomputed the aggregate counts, rates, durations, worker
totals, and burst measurements from the frozen snapshot. It found no blocking
factual, methodological, or safety error and approved the remediation order.
Its non-blocking qualifications prompted the marker-negative label, calibrated
causal confidence, and the preserved 74-call annotation table.[9]

## Affected files and tests for a later implementation phase

- `app/mcp_stdio.py` — `codex_review()` completion instructions.
- `pipelines/default/prompts/base.md` — shared no-wait rule.
- `app/routes/sessions.py` — merge readiness race.
- `tests/test_mcp_stdio.py` — assert end-turn wording and absence of “just wait.”
- merge route/session tests — bounded `RUNNING → IDLE` transition.
- Optional Codex hook/guard integration — only after residual telemetry.

## Sources

1. **Tier 1 — direct measurement:** `/tmp/orchestra-codex-sleep-20260725.db`,
   snapshot of `/mnt/data/Projects/Python/orchestra/data/orchestra.db` through
   log id 289716. Queries and representative log ids are reproduced above;
   `docs/tasks/codex-sleep/sleep-call-annotations.tsv` preserves all 74
   classifications.
2. **Tier 2 — primary source:** `app/backend_codex.py:1142-1161` and
   `app/backend_claude.py:365-573`.
3. **Tier 2 — primary source:** `app/mcp_stdio.py:840-1014`.
4. **Tier 2 — primary source:** `app/session_turns.py:188-199`,
   `app/bg_jobs.py:281-298`, and `app/session.py:447-477`.
5. **Tier 2 — primary source:** `pipelines/default/pipeline.yaml:48-70`,
   `pipelines/default/prompts/roles/worker.md:7-14`, and
   `pipelines/default/prompts/roles/full-cycle.md:36-44`.
6. **Tier 1 — exact runtime record:** Codex 0.144.6 rollout
   `/home/maxim/.codex/sessions/2026/07/24/rollout-2026-07-24T20-14-41-019f9443-8867-7393-8467-23f1df758d07.jsonl`,
   `session_meta.payload.base_instructions`.
7. **Tier 2 — official primary documentation:** OpenAI,
   [Codex manual](https://developers.openai.com/codex/codex-manual.md),
   fetched 2026-07-25; hooks section documents that `PreToolUse` covers Bash and
   can inspect/block/rewrite local tool calls.
8. **Tier 2 — primary source:** `pipelines/default/prompts/skills/vps-deploy.md:35-38`.
9. **Tier 1/2 — adversarial replication and source audit:**
   `docs/tasks/codex-sleep/codex-review-research.md`, generated 2026-07-25.
