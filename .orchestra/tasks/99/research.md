# #99 — Conditional recurring jobs and TG topic status

## Question

**Context.** `intent-hunter` used a 15-minute `cron` job to run one monitoring
command through the LLM. The empty checks produced 32 turns, 63.1M input tokens,
and $25.86 of virtual API-equivalent cost on 2026-07-28/29; the same turns also
alternated the Telegram topic icon between running and idle [1].

**Change under test.** Move the periodic command and regex decision into the
server-side background job, wake the LLM only on a match, and delay only the
running→idle topic transition.

**Baseline.** Current `cron` always calls `session.send`; current `command` is a
one-shot watch; topic status applies both directions immediately [2][3].

**Measurable outcome.**

- four or more scheduled command runs with no match cause zero `session.send`
  calls and therefore zero `edit_forum_topic` calls;
- a matching run wakes the target while the recurring job remains active;
- an interactive task changes the topic to running immediately;
- idle is applied once after five minutes of uninterrupted inactivity;
- tests control subprocesses and delay completion directly, without wall-clock
  sleeps or short `wait_for` assertions.

## Hypotheses considered

### H1 — Make the existing `command` job recurring after a match

**Hypothesis.** Removing the `return` after `_trigger` is enough because the
runner already has an interval loop.

**Falsifier.** This is wrong if `_trigger` makes the job terminal or if the
published `command` contract is one-shot.

**Result: REFUTED.** `_trigger` atomically changes `active → triggering →
triggered`, so the next iteration cannot legitimately fire again [2]. The
original design and task #26 both explicitly classify `command` as one-shot
[4]. Removing only the `return` would leave a loop running for a terminal DB
row; changing the lifecycle would silently break existing “wait for first
match” jobs.

### H2 — Add optional `command` and `pattern` fields to `type="cron"`

**Hypothesis.** Reusing `cron` gives the smallest API.

**Falsifier.** This is unsafe if the immediately reloaded MCP client can send
the new fields to an old in-memory server that accepts but ignores them.

**Result: REFUTED FOR ROLLOUT.** The route accepts an arbitrary `config` dict
[5]. Current cron validation accepts extra keys, while `_start_task` passes
only `cron_expr` into `_run_cron` [2]. The measured probe returned
`cron_accepts_ignored_command_fields=true` [6]. During the MCP↔server version
window, a new conditional cron would therefore be accepted and would wake the
LLM unconditionally—the exact expensive failure being fixed.

### H3 — Add a distinct `cron_command` job type

**Hypothesis.** A distinct recurring type preserves both existing contracts and
fails closed during the hot MCP↔server version window.

**Falsifier.** This is wrong if adding a type needs a DB or route migration, or
if recurring jobs cannot remain active after a notification.

**Result: CONFIRMED.** `bg_jobs.type` is already free-form and the HTTP route
passes the config through unchanged [5]. Existing cron already has the
recurring scheduler, non-terminal send path, restart restoration, cancellation,
and `timeout_seconds=0` no-expiry model [2][4]. An old server rejects
`cron_command` as an unknown type instead of silently running the wrong
behavior [2]. The implementation can reuse cron scheduling and select the
conditional command action by the validated job type.

### H4 — Carry `wake_source` through `AgentSession.send` and suppress all
background-origin topic activity

**Hypothesis.** Source propagation is the cleanest way to stop icon flicker.

**Falsifier.** It is the wrong layer if it hides real LLM work or if another
topic-status path bypasses the hook.

**Result: REFUTED FOR #99.** The session hook is not the only ignition path:
`stream_logs` also sets running on every `text` or `tool` log [3]. A correct
source model would require changes to `app/session.py`, every automatic sender
(`app/bg_jobs.py`, `app/limit_wake.py`, retry/restart paths), hook signatures,
turn/queued-message provenance, and stream-log status decisions. It would also
hide a background notification that actually matched and started useful LLM
work. Eliminating no-match wakes at the job boundary is both cheaper and more
truthful: no LLM work means no running status; a matched notification means the
LLM really is running.

## Findings

### F1 — The main cost is avoidable LLM work, not the Telegram edit

**CONFIRMED — direct production measurement supplied by the orchestrator.**
Across 32 monitor turns on 2026-07-28/29, `intent-hunter` consumed 63.1M input
tokens and $25.86, averaging about 1.16M input tokens per single-command turn;
`cache_create` was zero [1]. A server-side no-match check reduces both the turn
count and topic edits to zero for those checks.

### F2 — Current `command` is one-shot and zero timeout lasts one second

**CONFIRMED — source plus isolated `/tmp` measurement.** On a match,
`_run_command_watch` calls the terminal `_trigger` and returns [2]. The
controlled probe observed exactly one trigger followed by runner return [6].
For `type="command", timeout_seconds=0`, the persisted and runner lifetime were
both exactly `1.0` second [6]. Cron is correctly exempted through persisted
`no_expiry`; the defect affects the watch types instead [2].

### F3 — `cron_command` is the safest compatible contract

**CONFIRMED — primary code paths.** No API route or DB schema change is needed
[5]. Existing job types keep their behavior. During the deployment window, the
new MCP tool may advertise `cron_command` before the Python service restarts,
but an old service rejects it with `unknown job type` rather than waking an
agent incorrectly [2].

### F4 — Five-minute asymmetric debounce is sufficient only after no-op wakes
are removed

**LIKELY — code-level reasoning; the five-minute policy is not production
measured.** Delaying idle alone cannot meet the zero-edit criterion: the first
empty cron wake would still produce one running edit. After `cron_command`
removes empty wakes, a five-minute idle delay coalesces short task/retry/worker
handoff gaps while bounding a stale running icon to five minutes. Running must
remain immediate. The existing per-topic status worker can own both the delay
and edit; every running schedule, including direct `stream_logs` calls, must
cancel and replace a delayed-idle worker before editing immediately [3].

### F5 — Startup synchronization should not erase a known identical state

**CONFIRMED — primary code.** `_sync_all_topic_statuses` explicitly removes the
cached state immediately before scheduling the same computed state [3]. The
cache is already empty after process start and `stop_bridge`, so removing the
`pop` preserves cold-start synchronization while making repeated deferred
startup calls idempotent [3].

## Counter-evidence and limits

- A source-propagation model can be useful if product semantics later become
  “show only interactive work.” It is not selected here because the current
  icon means “the scope has running LLM work,” and matched background work
  satisfies that definition.
- `cron_command` adds one public job type. Reusing `cron` would be cosmetically
  smaller, but the live-version experiment shows that it fails open during
  deployment.
- A five-minute idle delay can make a genuinely completed task look active for
  up to five minutes. This is intentional hysteresis; no production distribution
  of inter-turn gaps was available, so the exact duration remains a policy
  choice rather than a measured optimum.
- A persistent finding can match on every cron tick and wake repeatedly. The
  job correctly obeys its regex; deduplicating domain findings belongs in the
  monitoring command or a later explicit contract.
- Command timeout/non-zero exit behavior must remain observable in job state
  and logs. Regex decides the wake only for a completed process (including a
  completed non-zero exit); a timed-out invocation never wakes, even if its
  partial output matched before termination.

## Affected files

- `app/bg_jobs.py` — validate and dispatch `cron_command`, execute a bounded
  command per cron fire, keep the job active, support no-expiry watch lifetimes.
- `app/mcp_stdio.py` — expose the new type using existing `cron_expr`,
  `command`, and `pattern` parameters; document timeout semantics.
- `tests/test_bg_jobs.py` — conditional recurring behavior, restore/cancel,
  timeout, and no-match assertions.
- `tests/test_mcp_stdio.py` — exact API payload for `cron_command`.
- `app/tg_bridge.py` — delayed idle inside the existing status worker,
  immediate running cancellation, idempotent startup sync.
- `tests/test_tg_bridge.py` — deterministic delay-gate tests; no wall-clock
  performance assertions.

No change is planned for `app/routes/bg.py`, `app/session.py`, `app/limit_wake.py`,
or `app/db.py`.

## Raw measurements

Orchestrator production measurement [1]:

```text
28.07: 27 turns, input 31 295 716, cache_read 30 109 184,
cache_create 0, $24.55
29.07: 5 turns, $1.31
Total: 32 turns, $25.86, 63.1M tokens
```

Isolated current-code probes [6]:

```json
{"configured_timeout_passed_to_runner": 1, "persisted_lifetime_seconds": 1.0, "result": {"id": "bg-999ae5f762", "status": "active", "type": "command"}, "stored_config": {"command": "printf ok", "interval_seconds": 900, "pattern": "MATCH"}}
{"cron_accepts_ignored_command_fields": true, "runner_returned_after_match": true, "trigger_calls": 1}
```

## Sources

1. Production `turn_usage` and wake-log measurements supplied by
   `Orchestra-orchestrator` in the #99 task messages (evidence tier 1: direct
   measurement; raw production query was not rerun in this worktree).
2. `app/bg_jobs.py:42-99,133-218,316-434,464-490` and
   `app/db.py:1136-1190` (evidence tier 2: primary source).
3. `app/tg_bridge.py:1734-1854,2291-2293,2464-2468,2779-2812` (evidence tier 2:
   primary source).
4. `docs/tasks/26/research.md` and `docs/tasks/26/plan.md` (evidence tier 2:
   project design record corroborated by current source).
5. `app/routes/bg.py:12-40` and `app/mcp_stdio.py:760-798` (evidence tier 2:
   primary source).
6. Two isolated `/tmp` probes run on 2026-07-29 against the current worktree:
   temp SQLite DB plus mocked subprocess/trigger (evidence tier 1: direct,
   reproducible measurement; raw outputs above).
